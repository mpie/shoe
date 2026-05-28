"""Generic, profile-driven site monitor.

One :class:`SiteMonitor` instance watches one site (described by a
:class:`~app.sites.SiteProfile`). The :class:`~app.manager.MonitorManager`
holds several of them so multiple shops run at the same time.
"""

from __future__ import annotations

import asyncio
import inspect
import os
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from scrapling.fetchers import Fetcher, StealthyFetcher

from app.sites import SiteProfile, config_dir


DEFAULT_INTERVAL_SECONDS = 20
LOG_TIMEZONE = ZoneInfo("Europe/Amsterdam")
SOLVE_CLOUDFLARE = os.getenv("SOLVE_CLOUDFLARE", "").casefold() in {"1", "true", "yes", "on"}
USE_STEALTH_FETCHER = os.getenv("USE_STEALTH_FETCHER", "").casefold() in {"1", "true", "yes", "on"}
AUTOMATION_WIDTH = 1600
AUTOMATION_HEIGHT = 1050
AUTOMATION_X = 160
AUTOMATION_Y = 40

# Persistent browser contexts keyed by site so each site keeps its own login
# session and reuses one window across runs.
OPEN_CONTEXTS: dict[str, tuple[Any, Any]] = {}


@dataclass
class MonitorResult:
    matched_text: str
    product_url: str
    found_at: str
    automation_log: list[str] = field(default_factory=list)
    # "carted" | "sold_out" | "size_not_found" | "failed"
    outcome: str = "carted"


@dataclass
class MonitorState:
    running: bool = False
    search_text: str = ""
    target_url: str = ""
    interval_seconds: int = DEFAULT_INTERVAL_SECONDS
    size: str = ""
    last_checked_at: str | None = None
    last_error: str | None = None
    result: MonitorResult | None = None
    checks: int = 0
    log_entries: list[str] = field(default_factory=list)


class SiteMonitor:
    def __init__(self, profile: SiteProfile) -> None:
        self.profile = profile
        self._state = MonitorState(
            search_text=profile.default_search_text,
            target_url=profile.default_target_url,
            size=profile.default_size,
        )
        self._task: asyncio.Task[None] | None = None
        self._lock = threading.Lock()

    @property
    def id(self) -> str:
        return self.profile.key

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            creds = self.profile.credentials()
            return {
                "id": self.profile.key,
                "label": self.profile.label,
                "loginConfigured": creds.present,
                "loginUser": creds.username if creds.present else "",
                "running": self._state.running,
                "searchText": self._state.search_text,
                "targetUrl": self._state.target_url,
                "intervalSeconds": self._state.interval_seconds,
                "size": self._state.size,
                "lastCheckedAt": self._state.last_checked_at,
                "lastError": self._state.last_error,
                "checks": self._state.checks,
                "logEntries": self._state.log_entries[-100:],
                "result": None
                if self._state.result is None
                else {
                    "matchedText": self._state.result.matched_text,
                    "productUrl": self._state.result.product_url,
                    "foundAt": self._state.result.found_at,
                    "automationLog": self._state.result.automation_log,
                    "outcome": self._state.result.outcome,
                },
            }

    async def start(
        self,
        search_text: str | None = None,
        target_url: str | None = None,
        interval_seconds: int = DEFAULT_INTERVAL_SECONDS,
        size: str | None = None,
    ) -> dict[str, Any]:
        await self.stop()

        clean_search_text = (search_text or "").strip() or self.profile.default_search_text
        clean_target_url = (target_url or "").strip() or self.profile.default_target_url
        clean_size = (size or "").strip() or self.profile.default_size

        with self._lock:
            self._state = MonitorState(
                running=True,
                search_text=clean_search_text,
                target_url=clean_target_url,
                interval_seconds=max(5, interval_seconds),
                size=clean_size,
            )
            self._append_log_unlocked(
                f'Start {self.profile.label}: zoekt naar "{clean_search_text}" op {clean_target_url} elke {max(5, interval_seconds)}s.'
            )

        self._task = asyncio.create_task(self._run())
        return self.snapshot()

    async def stop(self) -> dict[str, Any]:
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        self._task = None
        with self._lock:
            if self._state.running:
                self._append_log_unlocked("Monitor handmatig gestopt.")
            self._state.running = False

        return self.snapshot()

    def clear_logs(self) -> dict[str, Any]:
        with self._lock:
            self._state.log_entries = []
        return self.snapshot()

    async def _run(self) -> None:
        while True:
            state = self.snapshot()
            try:
                with self._lock:
                    self._append_log_unlocked(
                        f'Check #{self._state.checks + 1}: pagina ophalen met Scrapling voor "{state["searchText"]}".'
                    )

                match = await asyncio.to_thread(
                    self._check_once,
                    state["targetUrl"],
                    state["searchText"],
                    state["intervalSeconds"],
                )

                with self._lock:
                    self._state.checks += 1
                    self._state.last_checked_at = _now()
                    self._state.last_error = None
                    if match is None:
                        self._append_log_unlocked(f"Check #{self._state.checks}: geen match gevonden.")
                        self._append_log_unlocked(
                            f"Volgende check over {state['intervalSeconds']}s rond {_log_time_after(state['intervalSeconds'])}."
                        )

                if match is not None:
                    with self._lock:
                        self._append_log_unlocked(
                            f'Gevonden: "{match["matched_text"]}". Productpagina: {match["product_url"]}.'
                        )
                        self._append_log_unlocked(f'Automatisering gestart voor maat {state["size"]}.')

                    automation_log, outcome = await asyncio.to_thread(
                        self._select_size_and_add_to_cart,
                        match["product_url"],
                        state["size"],
                        match.get("release_epoch"),
                    )
                    with self._lock:
                        self._state.running = False
                        self._state.result = MonitorResult(
                            matched_text=match["matched_text"],
                            product_url=match["product_url"],
                            found_at=_now(),
                            automation_log=automation_log,
                            outcome=outcome,
                        )
                        for entry in automation_log:
                            self._append_log_unlocked(f"Automation: {entry}")
                        self._append_log_unlocked(_outcome_message(outcome, state["size"]))
                        self._append_log_unlocked("Monitor gestopt na match.")
                    return
            except Exception as exc:
                with self._lock:
                    self._state.last_error = str(exc)
                    self._state.last_checked_at = _now()
                    self._append_log_unlocked(f"Fout tijdens check: {exc}")
                    self._append_log_unlocked(
                        f"Nieuwe poging over {state['intervalSeconds']}s rond {_log_time_after(state['intervalSeconds'])}."
                    )

            await asyncio.sleep(int(state["intervalSeconds"]))

    def _append_log_unlocked(self, message: str) -> None:
        entry = f"{_log_now()} | [{self.profile.label}] {message}"
        self._state.log_entries.append(entry)
        self._state.log_entries = self._state.log_entries[-100:]
        print(entry, flush=True)

    # --- Detection ----------------------------------------------------------

    def _check_once(self, target_url: str, search_text: str, interval_seconds: int) -> dict[str, str] | None:
        page = _scrapling_fetch(
            target_url,
            timeout=max(8_000, min(15_000, int(interval_seconds) * 750)),
        )
        html = _response_html(page)
        soup = BeautifulSoup(html, "html.parser")
        page_text = _normalize(soup.get_text(" ", strip=True))

        if self.profile.detect_mode == "product":
            return self._check_product_page(target_url, search_text, page_text, html)

        needle = _normalize(search_text)
        if needle not in page_text:
            return None

        product_url = _find_best_product_url(soup, target_url, needle) or target_url
        return {"matched_text": search_text, "product_url": product_url}

    def _check_product_page(
        self, target_url: str, search_text: str, page_text: str, html: str
    ) -> dict[str, Any] | None:
        matched = {
            "matched_text": search_text or self.profile.label,
            "product_url": target_url,
            "release_epoch": None,
        }

        # Timed drop: the buy button is rendered client-side at releaseDate, so
        # the static page never shows it. Trigger on the clock instead and let
        # the live browser grab the button once it appears.
        release = _parse_release_date(html)
        if release is not None:
            now = datetime.now(timezone.utc)
            fire_at = release - timedelta(seconds=self.profile.prearm_seconds)
            if now < fire_at:
                with self._lock:
                    self._append_log_unlocked(
                        f"Release om {release.astimezone(LOG_TIMEZONE):%d-%m-%Y %H:%M:%S} "
                        f"(NL). Pre-arm over {int((fire_at - now).total_seconds())}s."
                    )
                return None
            matched["release_epoch"] = release.timestamp()
            return matched

        # No release timestamp: fall back to marker detection.
        coming_soon = any(_normalize(marker) in page_text for marker in self.profile.coming_soon_markers)
        if coming_soon:
            return None
        purchasable = any(_normalize(marker) in page_text for marker in self.profile.purchasable_markers)
        if not purchasable:
            return None
        return matched

    # --- Automation ---------------------------------------------------------

    def _select_size_and_add_to_cart(
        self, product_url: str, size: str, release_epoch: float | None = None
    ) -> tuple[list[str], str]:
        log: list[str] = []
        context = None
        page = None
        outcome = "failed"

        try:
            context, page = _automation_page(self.profile.key, log)
            page.on("dialog", lambda dialog: dialog.accept())

            if self.profile.login_stage == "upfront":
                self._ensure_login(page, log)

            page.goto(product_url, wait_until="domcontentloaded", timeout=45_000)
            log.append("Visible product page opened.")

            self._handle_cookie_window(page, log)
            _ensure_product_page(page, product_url, log)

            outcome = self._grab_size_and_cart(page, product_url, size, release_epoch, log)
            if outcome != "carted":
                _keep_open(self.profile.key, context, log)
                return log, outcome

            log.append("Waiting for shopping cart before checkout.")
            _wait_for_cart_sidebar(page, self.profile.cart_sidebar_selectors, log)
            checkout_clicked = _click_first(page, self.profile.checkout_selectors, log, "checkout", timeout_ms=12_000)
            if not checkout_clicked:
                log.append("Could not click checkout button.")

            if self.profile.login_stage == "checkout":
                _settle(page)
                self._login_inline(page, log)

            _keep_open(self.profile.key, context, log)
        except Exception as exc:
            log.append(f"Visible browser automation failed: {exc}")
            if context is not None:
                _keep_open(self.profile.key, context, log)

        return log, outcome

    def _grab_size_and_cart(
        self, page: Any, product_url: str, size: str, release_epoch: float | None, log: list[str]
    ) -> str:
        """Click size + add-to-cart and return the outcome.

        For timed drops, retry while the live buy button appears (page reloaded
        each round) until the buy window closes. If the size turns out to be
        sold out, report that explicitly instead of a generic failure.

        Returns one of: "carted", "sold_out", "size_not_found", "failed".
        """
        size_selectors = self.profile.size_selectors(size)
        deadline = None
        if self.profile.detect_mode == "product":
            base = release_epoch if release_epoch is not None else datetime.now(timezone.utc).timestamp()
            deadline = base + self.profile.buy_window_seconds

        attempt = 0
        size_ever_seen = False
        while True:
            attempt += 1
            size_clicked = _click_first(page, size_selectors, log, f"size {size}", timeout_ms=4_000)
            size_ever_seen = size_ever_seen or size_clicked

            if _click_first(page, self.profile.add_to_cart_selectors, log, "shopping cart", timeout_ms=4_000):
                return "carted"

            if self._size_sold_out(page, size):
                log.append(f"Maat {size} is uitverkocht / niet meer beschikbaar.")
                return "sold_out"

            if deadline is None or datetime.now(timezone.utc).timestamp() > deadline:
                if not size_ever_seen:
                    log.append(f"Maat {size} niet gevonden op de pagina.")
                    return "size_not_found"
                log.append(f"Add-to-cart niet gelukt na {attempt} pogingen.")
                return "failed"

            log.append(f"Knop nog niet live (poging {attempt}); herladen en opnieuw proberen.")
            try:
                page.reload(wait_until="domcontentloaded", timeout=30_000)
                _settle(page)
                self._dismiss_popups(page, log)
            except Exception:
                page.wait_for_timeout(1_000)

    def _size_sold_out(self, page: Any, size: str) -> bool:
        """Detect a sold-out size: a disabled/struck size control, or a
        sold-out marker text visible on the page."""
        for selector in _size_unavailable_selectors(size):
            try:
                if page.locator(selector).first.is_visible(timeout=1_000):
                    return True
            except Exception:
                continue

        try:
            page_text = _normalize(page.locator("body").inner_text(timeout=2_000))
        except Exception:
            return False
        return any(_normalize(marker) in page_text for marker in self.profile.sold_out_markers)

    def _ensure_login(self, page: Any, log: list[str]) -> None:
        """Upfront login: navigate to the site's own login page first."""
        creds = self.profile.credentials()
        if not creds.present:
            log.append("Geen inloggegevens ingesteld; ga verder zonder login.")
            return

        try:
            page.goto(self.profile.login_url, wait_until="domcontentloaded", timeout=45_000)
        except Exception as exc:
            log.append(f"Kon loginpagina niet openen: {exc}")
            return

        self._handle_cookie_window(page, log)

        if _any_visible(page, self.profile.logged_in_selectors):
            log.append("Al ingelogd (sessie hergebruikt).")
            return

        self._fill_login_form(page, creds, log)

    def _login_inline(self, page: Any, log: list[str]) -> None:
        """Checkout-stage login: fill the form that appears after checkout.

        No navigation — the login form sits on the checkout page itself.
        """
        creds = self.profile.credentials()
        if not creds.present:
            log.append("Geen inloggegevens ingesteld; vul login handmatig in de browser.")
            return

        self._handle_cookie_window(page, log)

        if _any_visible(page, self.profile.logged_in_selectors):
            log.append("Al ingelogd bij checkout.")
            return

        if not _any_visible(page, self.profile.login_password_selectors):
            log.append("Geen loginformulier bij checkout gevonden; rond handmatig af.")
            return

        log.append("Loginformulier bij checkout gevonden.")
        self._fill_login_form(page, creds, log)

    def _fill_login_form(self, page: Any, creds: Any, log: list[str]) -> None:
        if not _fill_first(page, self.profile.login_email_selectors, creds.username, log, "e-mail"):
            log.append("Login e-mailveld niet gevonden; mogelijk al ingelogd.")
            return

        _fill_first(page, self.profile.login_password_selectors, creds.password, log, "wachtwoord")
        if _click_first(page, self.profile.login_submit_selectors, log, "login-knop", timeout_ms=10_000):
            _settle(page)
            log.append(f"Ingelogd als {creds.username}.")
        else:
            log.append("Login-knop niet gevonden.")

    def _handle_cookie_window(self, page: Any, log: list[str]) -> None:
        clicked = _click_first(page, self.profile.cookie_selectors, log, "cookie window", timeout_ms=12_000)
        if not clicked:
            log.append("No cookie window found.")
        _settle(page)
        self._dismiss_popups(page, log)

    def _dismiss_popups(self, page: Any, log: list[str]) -> None:
        """Close newsletter / marketing overlays that intercept clicks."""
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass

        if _click_first(page, self.profile.popup_close_selectors, log, "popup", timeout_ms=800):
            _settle(page)
            return

        # Fallback: strip known Klaviyo overlay nodes so they stop blocking.
        try:
            removed = page.evaluate(
                """() => {
                    const sel = 'div[role=dialog][aria-label="POPUP Form"], .kl-private-reset-css, [class*=kl-private]';
                    const nodes = document.querySelectorAll(sel);
                    nodes.forEach(n => { try { n.remove(); } catch (e) {} });
                    return nodes.length;
                }"""
            )
            if removed:
                log.append("Marketing-popup verwijderd.")
        except Exception:
            pass


# --- Shared helpers ---------------------------------------------------------

def _response_html(page: Any) -> str:
    body = getattr(page, "body", b"")
    encoding = getattr(page, "encoding", None) or "utf-8"

    if isinstance(body, bytes):
        return body.decode(encoding, errors="ignore")

    html = getattr(page, "html", None)
    if callable(html):
        return str(html())

    return str(page)


def _scrapling_fetch(url: str, timeout: int) -> Any:
    if not USE_STEALTH_FETCHER:
        return Fetcher.get(
            url,
            timeout=timeout,
            stealthy_headers=True,
            impersonate="chrome",
        )

    return _stealth_fetch(
        url,
        headless=True,
        network_idle=False,
        wait=1_000,
        timeout=timeout,
        block_images=True,
        disable_ads=True,
    )


def _stealth_fetch(url: str, **kwargs: Any) -> Any:
    fetch_kwargs = {
        "block_webrtc": True,
        "humanize": True,
        **kwargs,
    }
    fetch_signature = inspect.signature(StealthyFetcher.fetch)

    if SOLVE_CLOUDFLARE and ("solve_cloudflare" in fetch_signature.parameters or any(
        param.kind is inspect.Parameter.VAR_KEYWORD for param in fetch_signature.parameters.values()
    )):
        fetch_kwargs["solve_cloudflare"] = True

    return StealthyFetcher.fetch(url, **fetch_kwargs)


def _find_best_product_url(soup: BeautifulSoup, target_url: str, needle: str) -> str | None:
    candidates: list[tuple[int, str]] = []

    for anchor in soup.select("a[href]"):
        text = _normalize(anchor.get_text(" ", strip=True))
        parent_text = _normalize(anchor.parent.get_text(" ", strip=True)) if anchor.parent else text
        haystack = f"{text} {parent_text}"

        if needle not in haystack:
            continue

        href = str(anchor.get("href"))
        score = 2 if "/p/" in href or "/product" in href else 1
        candidates.append((score, urljoin(target_url, href)))

    if not candidates:
        return None

    return sorted(candidates, key=lambda item: item[0], reverse=True)[0][1]


def _ensure_product_page(page: Any, product_url: str, log: list[str]) -> None:
    current_url = getattr(page, "url", "")
    if current_url.startswith(product_url):
        log.append("Productpagina actief.")
        return

    log.append("Terug naar productpagina na popup/login.")
    page.goto(product_url, wait_until="domcontentloaded", timeout=45_000)
    _settle(page)


def _click_first(page: Any, selectors: list[str], log: list[str], label: str, timeout_ms: int = 5_000) -> bool:
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            locator.wait_for(state="visible", timeout=timeout_ms)
            locator.click(timeout=timeout_ms)
            log.append(f"{label} aangeklikt.")
            return True
        except Exception:
            # Radio/label controls and overlay-covered buttons often reject a
            # normal click; retry forcing past actionability checks.
            try:
                page.locator(selector).first.click(timeout=2_000, force=True)
                log.append(f"{label} aangeklikt (force).")
                return True
            except Exception:
                continue
    return False


def _fill_first(page: Any, selectors: list[str], value: str, log: list[str], label: str, timeout_ms: int = 8_000) -> bool:
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            locator.wait_for(state="visible", timeout=timeout_ms)
            locator.fill(value, timeout=timeout_ms)
            log.append(f"{label} ingevuld.")
            return True
        except Exception:
            continue
    return False


def _any_visible(page: Any, selectors: list[str], timeout_ms: int = 2_500) -> bool:
    for selector in selectors:
        try:
            page.locator(selector).first.wait_for(state="visible", timeout=timeout_ms)
            return True
        except Exception:
            continue
    return False


def _settle(page: Any) -> None:
    try:
        page.wait_for_timeout(750)
    except Exception:
        return


def _wait_for_cart_sidebar(page: Any, selectors: list[str], log: list[str]) -> None:
    for selector in selectors:
        try:
            page.locator(selector).first.wait_for(state="visible", timeout=8_000)
            log.append("Shopping cart klaar.")
            page.wait_for_timeout(1_250)
            return
        except Exception:
            continue
    log.append("Shopping cart niet bevestigd; checkout wordt alsnog geprobeerd.")


def _automation_page(site_key: str, log: list[str]) -> tuple[Any, Any]:
    context = OPEN_CONTEXTS.get(site_key)
    if context is not None:
        _playwright, ctx = context
        try:
            log.append("Nieuwe tab geopend in bestaande browser.")
            return ctx, ctx.new_page()
        except Exception:
            OPEN_CONTEXTS.pop(site_key, None)

    playwright = sync_playwright().start()
    ctx = _launch_persistent_context(playwright, site_key)
    OPEN_CONTEXTS[site_key] = (playwright, ctx)
    log.append("Automation-browser geopend (persistente sessie).")
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    return ctx, page


def _launch_persistent_context(playwright: Any, site_key: str) -> Any:
    user_data_dir = config_dir() / "sessions" / site_key
    user_data_dir.mkdir(parents=True, exist_ok=True)
    launch_args = [
        f"--window-size={AUTOMATION_WIDTH},{AUTOMATION_HEIGHT}",
        f"--window-position={AUTOMATION_X},{AUTOMATION_Y}",
    ]
    kwargs = {
        "headless": False,
        "args": launch_args,
        "viewport": {"width": AUTOMATION_WIDTH, "height": AUTOMATION_HEIGHT},
    }
    try:
        return playwright.chromium.launch_persistent_context(str(user_data_dir), **kwargs)
    except Exception as exc:
        if "Executable doesn't exist" not in str(exc):
            raise
    return playwright.chromium.launch_persistent_context(str(user_data_dir), channel="chrome", **kwargs)


def _keep_open(site_key: str, context: Any, log: list[str]) -> None:
    # Persistent contexts are tracked in OPEN_CONTEXTS already; just leave open.
    if site_key not in OPEN_CONTEXTS:
        OPEN_CONTEXTS[site_key] = (None, context)
    log.append("Browser blijft open voor afronden.")


def _size_variants(size: str) -> set[str]:
    return {v for v in {size, size.replace(".", ","), size.replace(",", ".")} if v}


def _size_unavailable_selectors(size: str) -> list[str]:
    """Selectors matching a sold-out / disabled size control.

    NOTE: do NOT match on a bare ``disabled`` class — Tailwind utility classes
    like ``peer-disabled:`` / ``disabled:`` sit on *every* control and would
    flag available sizes. nakedcph marks sold-out sizes with ``line-through``
    and a disabled radio input; match those specific signals only.
    """
    selectors: list[str] = []
    for value in _size_variants(size):
        selectors.extend(
            [
                f'xpath=//label[(@data-default-value="{value}" or @for="{value}") and contains(concat(" ", normalize-space(@class), " "), " line-through ")]',
                f'xpath=//label[normalize-space()="{value}" and contains(concat(" ", normalize-space(@class), " "), " line-through ")]',
                f'input[id="{value}"][disabled]',
                f'xpath=//button[normalize-space()="{value}" and (@disabled or @aria-disabled="true")]',
                f'xpath=//*[@role="button" and normalize-space()="{value}" and @aria-disabled="true"]',
            ]
        )
    return selectors


def _outcome_message(outcome: str, size: str) -> str:
    return {
        "carted": "In winkelwagen gelegd; rond af in de browser.",
        "sold_out": f"Maat {size} is uitverkocht / niet meer beschikbaar.",
        "size_not_found": f"Maat {size} niet gevonden op de pagina.",
        "failed": "Add-to-cart niet gelukt; rond handmatig af in de browser.",
    }.get(outcome, "Automatisering afgerond.")


_RELEASE_DATE_RE = re.compile(r'"releaseDate"\s*:\s*"([^"]+)"')


def _parse_release_date(html: str) -> datetime | None:
    match = _RELEASE_DATE_RE.search(html)
    if not match:
        return None

    raw = match.group(1).strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold()).strip()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log_now() -> str:
    return datetime.now(LOG_TIMEZONE).strftime("%d-%m-%Y %H:%M:%S")


def _log_time_after(seconds: int) -> str:
    return (datetime.now(LOG_TIMEZONE) + timedelta(seconds=int(seconds))).strftime("%H:%M:%S")

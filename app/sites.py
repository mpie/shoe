"""Site profiles and credential loading for the multi-site monitor.

A profile describes everything site-specific: how to detect a release, how to
log in, and which selectors drive the size/cart/checkout automation. Adding a
new shop = adding a new SiteProfile here (no changes to the monitor engine).
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


# --- Config / credential storage -------------------------------------------

def config_dir() -> Path:
    """Writable directory for credentials and persistent browser sessions.

    Frozen desktop builds cannot write next to the executable, so they use a
    folder in the user's home directory. Source runs keep everything in the
    project's ``config/`` folder.
    """
    if getattr(sys, "frozen", False):
        base = Path.home() / ".solebox_monitor"
    else:
        base = Path(__file__).resolve().parent.parent / "config"
    base.mkdir(parents=True, exist_ok=True)
    return base


CREDENTIALS_FILE = "credentials.json"


@dataclass
class Credentials:
    username: str = ""
    password: str = ""

    @property
    def present(self) -> bool:
        return bool(self.username and self.password)


def load_credentials(site_key: str) -> Credentials:
    """Load credentials for a site from config/credentials.json.

    Environment variables override the file: ``<SITE>_USERNAME`` /
    ``<SITE>_PASSWORD`` (e.g. ``SOLEBOX_USERNAME``).
    """
    data: dict = {}
    path = config_dir() / CREDENTIALS_FILE
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            data = {}

    entry = data.get(site_key, {}) if isinstance(data, dict) else {}
    username = os.getenv(f"{site_key.upper()}_USERNAME") or entry.get("username", "")
    password = os.getenv(f"{site_key.upper()}_PASSWORD") or entry.get("password", "")
    return Credentials(username=str(username), password=str(password))


# --- Site profiles ----------------------------------------------------------

@dataclass
class SiteProfile:
    key: str
    label: str
    default_target_url: str
    default_search_text: str
    default_size: str
    # "listing": search_text must appear on a releases listing page.
    # "product": poll a single product page until it becomes purchasable.
    detect_mode: str
    # "upfront": log in before opening the product page (own login page).
    # "checkout": log in on the form that appears after clicking checkout.
    login_stage: str
    login_url: str
    cookie_selectors: list[str]
    # Newsletter / marketing overlays to close before interacting.
    popup_close_selectors: list[str]
    login_email_selectors: list[str]
    login_password_selectors: list[str]
    login_submit_selectors: list[str]
    # Signals a user is already logged in (any visible -> skip login).
    logged_in_selectors: list[str]
    add_to_cart_selectors: list[str]
    cart_sidebar_selectors: list[str]
    checkout_selectors: list[str]
    # For product mode: presence of any -> NOT yet purchasable.
    coming_soon_markers: list[str] = field(default_factory=list)
    # For product mode: presence of any (with no coming-soon marker) -> buy now.
    purchasable_markers: list[str] = field(default_factory=list)
    # Text that signals the (selected) size / product is sold out.
    sold_out_markers: list[str] = field(
        default_factory=lambda: [
            "uitverkocht",
            "niet meer beschikbaar",
            "niet beschikbaar",
            "sold out",
            "out of stock",
            "not available",
            "no longer available",
        ]
    )
    # Product mode: open the browser this many seconds before the parsed
    # releaseDate so login + page load finish before the drop goes live.
    prearm_seconds: int = 45
    # Product mode: keep retrying size+add-to-cart for this long after release
    # while the live buy button appears.
    buy_window_seconds: int = 180
    # Test button presets. test_mode "monitor" runs a normal start with these
    # params; "automate" skips detection and carts the test URL directly.
    test_mode: str = "monitor"
    test_search_text: str = ""
    test_target_url: str = ""
    test_size: str = ""
    test_interval_seconds: int = 15
    size_selectors: Callable[[str], list[str]] = None  # set below

    def credentials(self) -> Credentials:
        return load_credentials(self.key)


def _solebox_size_selectors(size: str) -> list[str]:
    import re

    escaped = re.escape(size)
    return [
        f'xpath=//button[normalize-space()="{size}"]',
        f'xpath=//*[@role="button" and normalize-space()="{size}"]',
        f'xpath=//*[normalize-space()="{size}"]/ancestor::button[1]',
        f'xpath=//*[normalize-space()="{size}" and (self::button or self::div or self::span)]',
        f'button:has-text("{size}")',
        f'text="{size}"',
        f'[role="button"]:has-text("{size}")',
        f'[aria-label="{size}"]',
        f'[aria-label*="{size}"]',
        f'[data-testid*="{size}"]',
        f'text=/^{escaped}$/',
    ]


def _nakedcph_size_selectors(size: str) -> list[str]:
    # nakedcph (Shopify Hydrogen) renders sizes as a hidden radio + <label>.
    # The label's `for` and `data-default-value` hold the exact value, so match
    # those instead of text (text "36" would also hit "36 2/3").
    variants = {size, size.replace(".", ","), size.replace(",", ".")}
    selectors: list[str] = []
    for value in variants:
        selectors.extend(
            [
                f'label[data-default-value="{value}"]',
                f'label[for="{value}"]',
                f'xpath=//label[normalize-space()="{value}"]',
            ]
        )
    return selectors


_COOKIE_SELECTORS = [
    "#cmpbntyestxt",
    'xpath=//*[@id="cmpbntyestxt"]/ancestor::button[1]',
    'button:has-text("Accept all")',
    'button:has-text("Accept All")',
    'button:has-text("Accept")',
    'button:has-text("Agree")',
    'button:has-text("Alles accepteren")',
    'button:has-text("Alle akzeptieren")',
    'button:has-text("Accepteren")',
    'button:has-text("Accepteer alles")',
    'button:has-text("Allow all")',
    '[aria-label*="accept" i]',
    '[id*="accept" i]',
    '[data-testid*="accept" i]',
]

_POPUP_CLOSE_SELECTORS = [
    "button.klaviyo-close-form",
    '[aria-label="Close dialog"]',
    'div[role="dialog"][aria-label="POPUP Form"] button[aria-label*="close" i]',
    '[aria-label="Close form"]',
    '[aria-label="Sluiten"]',
    'div[role="dialog"] button[aria-label*="close" i]',
    'div[role="dialog"] button[aria-label*="sluiten" i]',
]

_LOGIN_EMAIL_SELECTORS = [
    'input[name="customer[email]"]',
    'input[name="dwfrm_login_username"]',
    'input[type="email"]',
    "#email",
    "#login-form-email",
    'input[autocomplete="email"]',
    'input[name*="email" i]',
    'input[name*="username" i]',
    'input[id*="email" i]',
]

_LOGIN_PASSWORD_SELECTORS = [
    'input[name="customer[password]"]',
    'input[name="dwfrm_login_password"]',
    'input[type="password"]',
    "#password",
    'input[autocomplete="current-password"]',
    'input[name*="password" i]',
    'input[id*="password" i]',
]

_LOGIN_SUBMIT_SELECTORS = [
    'button[name="dwfrm_login_login"]',
    'form button[type="submit"]',
    'form input[type="submit"]',
    'button:has-text("Sign In")',
    'button:has-text("Sign in")',
    'button:has-text("Log in")',
    'button:has-text("Login")',
    'button:has-text("Inloggen")',
    'button:has-text("Aanmelden")',
    'button:has-text("Anmelden")',
    'input[value="Inloggen"]',
    'input[value="Sign In"]',
]

_LOGGED_IN_SELECTORS = [
    'a[href*="logout" i]',
    'a[href*="account/logout" i]',
    'a[href*="/account"]:has-text("Account")',
    'button:has-text("Log out")',
    'button:has-text("Uitloggen")',
    'text="Mijn account"',
    'text="My account"',
]


SOLEBOX = SiteProfile(
    key="solebox",
    label="Solebox",
    default_target_url="https://www.solebox.com/en-nl/s/releases",
    default_search_text="muslin shy pink",
    default_size="41",
    detect_mode="listing",
    login_stage="checkout",
    login_url="https://www.solebox.com/en-nl/login/",
    cookie_selectors=_COOKIE_SELECTORS,
    popup_close_selectors=_POPUP_CLOSE_SELECTORS,
    login_email_selectors=_LOGIN_EMAIL_SELECTORS,
    login_password_selectors=_LOGIN_PASSWORD_SELECTORS,
    login_submit_selectors=_LOGIN_SUBMIT_SELECTORS,
    logged_in_selectors=_LOGGED_IN_SELECTORS,
    add_to_cart_selectors=[
        'xpath=//button[contains(normalize-space(), "ADD TO CART")]',
        'xpath=//button[contains(normalize-space(), "Add to cart")]',
        'xpath=//*[contains(normalize-space(), "ADD TO CART")]/ancestor::button[1]',
        'button:has-text("Add to cart")',
        'button:has-text("ADD TO CART")',
        'button:has-text("Add to bag")',
        'button:has-text("In winkelwagen")',
        'button:has-text("Toevoegen")',
        '[aria-label*="cart" i]',
        '[aria-label*="bag" i]',
        '[aria-label*="winkelwagen" i]',
    ],
    cart_sidebar_selectors=[
        'text="Your shopping cart"',
        'text="The article has been added to the shopping cart."',
        'button:has-text("CHECKOUT")',
        'xpath=//button[normalize-space()="CHECKOUT"]',
    ],
    checkout_selectors=[
        'a[href="/en-nl/checkout"]',
        'a[href*="/checkout"]',
        'xpath=//a[@href="/en-nl/checkout"]',
        'xpath=//a[contains(@href, "/checkout")]',
        'xpath=//a[.//span[normalize-space()="CHECKOUT"]]',
        'xpath=//*[normalize-space()="CHECKOUT"]/ancestor::a[1]',
        'xpath=//button[normalize-space()="CHECKOUT"]',
        'xpath=//button[contains(normalize-space(), "CHECKOUT")]',
        'xpath=//button[contains(normalize-space(), "CHECK OUT")]',
        'xpath=//*[normalize-space()="CHECKOUT"]/ancestor::button[1]',
        'button:has-text("CHECKOUT")',
        'button:has-text("CHECK OUT")',
        'button:has-text("Checkout")',
        'button:has-text("Afrekenen")',
        '[aria-label*="checkout" i]',
        '[aria-label*="afrekenen" i]',
    ],
    size_selectors=_solebox_size_selectors,
    test_mode="monitor",
    test_search_text="Bloodline",
    test_target_url="https://www.solebox.com/en-nl/s/releases",
    test_size="44",
)


NAKEDCPH = SiteProfile(
    key="nakedcph",
    label="Naked Copenhagen",
    default_target_url="https://nakedcph.com/nl/products/jordan-brand-jordan-brand-x-travis-scott-air-jordan-1-low-og-tropical-pink-sail-tropical-pink-shy-pink-muslin-iq7604-101",
    default_search_text="travis scott air jordan 1 low",
    default_size="41",
    detect_mode="product",
    login_stage="upfront",
    login_url="https://nakedcph.com/nl/account/login",
    cookie_selectors=_COOKIE_SELECTORS
    + [
        'button:has-text("Accepteer")',
        'button:has-text("Akkoord")',
    ],
    popup_close_selectors=_POPUP_CLOSE_SELECTORS,
    login_email_selectors=_LOGIN_EMAIL_SELECTORS,
    login_password_selectors=_LOGIN_PASSWORD_SELECTORS,
    login_submit_selectors=_LOGIN_SUBMIT_SELECTORS,
    logged_in_selectors=_LOGGED_IN_SELECTORS,
    add_to_cart_selectors=[
        'form[action*="/cart/add"] button:has-text("Toevoegen aan winkelwagen")',
        'form[action*="/cart/add"] button:has-text("In winkelwagen")',
        'button:has-text("Toevoegen aan winkelwagen")',
        'button:has-text("Voeg toe aan winkelwagen")',
        'button:has-text("In winkelwagen")',
        'button:has-text("Add to cart")',
        'button:has-text("Add to bag")',
        'form[action*="/cart/add"] button[type="submit"]',
        '[aria-label*="winkelwagen" i]',
    ],
    cart_sidebar_selectors=[
        'text="Winkelwagen"',
        'text="Je winkelwagen"',
        'text="Your cart"',
        'a[href*="/checkout"]',
        'button:has-text("Afrekenen")',
        'button:has-text("Checkout")',
    ],
    checkout_selectors=[
        'a[href*="/checkout"]',
        'button[name="checkout"]',
        'xpath=//a[contains(@href, "/checkout")]',
        'button:has-text("Afrekenen")',
        'button:has-text("Verder naar afrekenen")',
        'button:has-text("Checkout")',
        'button:has-text("Check out")',
        '[aria-label*="checkout" i]',
        '[aria-label*="afrekenen" i]',
    ],
    coming_soon_markers=[
        "binnenkort online",
        "coming soon",
        "notify me",
        "email when available",
        "laat het me weten",
        "uitverkocht",
        "sold out",
    ],
    purchasable_markers=[
        "in winkelwagen",
        "toevoegen aan winkelwagen",
        "voeg toe aan winkelwagen",
        "add to cart",
        "add to bag",
    ],
    size_selectors=_nakedcph_size_selectors,
    test_mode="automate",
    test_search_text="adistar control 5 mary jane",
    test_target_url="https://nakedcph.com/nl/products/adidas-ori-adistar-control-5-mary-jane-carbon-tegrme-ntgrey-la1824",
    test_size="36",
)


PROFILES: dict[str, SiteProfile] = {
    SOLEBOX.key: SOLEBOX,
    NAKEDCPH.key: NAKEDCPH,
}


def get_profile(key: str) -> SiteProfile:
    profile = PROFILES.get(key)
    if profile is None:
        raise KeyError(f"Unknown site profile: {key}")
    return profile

from __future__ import annotations

import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn


HOST = "127.0.0.1"
PORT = 8018


def main() -> None:
    os.environ.setdefault("DESKTOP_APP", "1")
    _configure_bundled_browsers()

    from app.main import app
    from app import runtime

    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host=HOST,
            port=PORT,
            log_level="warning",
            access_log=False,
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    watchdog = threading.Thread(target=_watch_browser_heartbeat, args=(server, runtime), daemon=True)
    watchdog.start()

    url = f"http://{HOST}:{PORT}"
    _wait_for_server()
    webbrowser.open(url)

    try:
        while thread.is_alive():
            time.sleep(0.5)
    except KeyboardInterrupt:
        server.should_exit = True


def _configure_bundled_browsers() -> None:
    base_dir = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    bundled_browsers = base_dir / "ms-playwright"

    if bundled_browsers.exists():
        os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(bundled_browsers))


def _wait_for_server() -> None:
    deadline = time.monotonic() + 15

    while time.monotonic() < deadline:
        try:
            with socket.create_connection((HOST, PORT), timeout=0.5):
                return
        except OSError:
            time.sleep(0.2)


def _watch_browser_heartbeat(server: uvicorn.Server, runtime_module: object) -> None:
    # Give the opened browser enough time to load before enforcing heartbeats.
    time.sleep(25)

    while not server.should_exit:
        last_seen = getattr(runtime_module, "last_heartbeat_at", time.monotonic())

        if time.monotonic() - last_seen > 20:
            server.should_exit = True
            return

        time.sleep(5)


if __name__ == "__main__":
    main()

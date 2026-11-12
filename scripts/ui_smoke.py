#!/usr/bin/env python3
"""Browser smoke test for RaceCoach.

Checks the real UI in headless Chromium:

* the demo loads and shows five braking zones;
* selecting a different section changes the measured time delta;
* replay emits exactly one message per completed braking zone;
* the demo CSVs can be uploaded through the file inputs;
* external requests are blocked and none are attempted;
* the local server shuts down cleanly.

Prerequisites:

    uv sync --all-groups
    uv run playwright install chromium
    uv run python scripts/ui_smoke.py
"""

from __future__ import annotations

import platform
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from racecoach.demo import export_demo  # noqa: E402
from racecoach.server import create_server, server_url  # noqa: E402


def uv_version() -> str:
    try:
        return subprocess.check_output(["uv", "--version"], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return "uv not found on PATH"


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright is not installed. Run: uv sync --all-groups", file=sys.stderr)
        return 2

    server = create_server("127.0.0.1", 0, offline=True)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    url = server_url(server)
    external_requests: list[str] = []
    page_errors: list[str] = []
    temp_dir = tempfile.TemporaryDirectory(prefix="racecoach ui ")
    ref_path, prac_path = export_demo(Path(temp_dir.name) / "demo laps with spaces")

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1000})

            def route_handler(route):
                request_url = route.request.url
                parsed = urlparse(request_url)
                if parsed.scheme in ("data", "blob"):
                    route.continue_()
                    return
                if parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
                    external_requests.append(request_url)
                    route.abort()
                    return
                route.continue_()

            page.route("**/*", route_handler)
            page.on("pageerror", lambda error: page_errors.append(str(error)))

            page.goto(url, wait_until="domcontentloaded", timeout=20_000)
            page.wait_for_selector("#zone-list .zone-row:nth-child(5)", timeout=20_000)
            assert page.locator("#demo-status").inner_text() == "Demo loaded"
            assert page.locator("#zone-list .zone-row").count() == 5
            assert "44 m gap" in page.locator("#gap-list").inner_text()

            first_delta = page.locator("#detail-time-delta").inner_text()
            page.locator("#zone-list .zone-row").nth(1).click()
            page.wait_for_timeout(150)
            second_delta = page.locator("#detail-time-delta").inner_text()
            assert first_delta != second_delta, (first_delta, second_delta)
            assert first_delta.strip() == "+0.18 s", first_delta
            assert second_delta.strip() == "0.00 s", second_delta

            page.locator("#zone-list .zone-row").nth(0).click()
            page.wait_for_timeout(100)
            first_message = page.locator("#detail-message").inner_text()
            assert "12 metres earlier" in first_message
            assert "0.18 seconds longer" in first_message

            page.locator("#replay-speed").select_option("32")
            page.locator("#replay-reset").click()
            page.locator("#replay-play").click()
            page.wait_for_selector("#replay-status:has-text('Replay complete')", timeout=20_000)
            message_count = page.locator("#messages .message").count()
            assert message_count == 4, f"Expected 4 replay messages, got {message_count}."
            assert page.locator("#messages").inner_text().count("Skipped") == 0

            page.set_input_files("#reference-file", str(ref_path))
            page.set_input_files("#practice-file", str(prac_path))
            page.locator("#analyze-button").click()
            page.wait_for_selector("#app-status:has-text('Analysis loaded')", timeout=20_000)
            page.wait_for_selector("#zone-list .zone-row:nth-child(5)", timeout=20_000)
            assert page.locator("#demo-status").inner_text() == "Your laps"
            assert "12 metres earlier" in page.locator("#detail-message").inner_text()

            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        temp_dir.cleanup()

    assert not thread.is_alive(), "The local server did not shut down."
    assert not external_requests, f"External requests were attempted: {external_requests}"
    assert not page_errors, f"Browser page errors: {page_errors}"

    print("Environment")
    print(f"  OS:      {platform.platform()}")
    print(f"  Machine: {platform.machine()}")
    print(f"  Python:  {platform.python_version()}")
    print(f"  uv:      {uv_version()}")
    print("UI SMOKE PASS: demo, section change, replay messages, file upload, no external requests, clean shutdown.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

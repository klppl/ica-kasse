"""Optional Playwright flow to capture a Handla web session cookie.

Playwright is an **optional** dependency (``pip install '.[browser]'`` then
``playwright install chromium``). Everything else in the package works without
it; only ``ica handla login --browser`` needs it. Import of ``playwright`` is
deferred so the package imports fine when it is absent.
"""
from __future__ import annotations

import sys
import time
from typing import Any

from .handla import HANDLA_HOST, _store_base
from .errors import UsageError


def cookies_to_header(cookies: list[dict[str, Any]]) -> str:
    """Build a Cookie header from Playwright cookies for the Handla host."""
    parts: list[str] = []
    for c in cookies:
        dom = (c.get("domain") or "").lstrip(".").lower()
        if dom.endswith("handlaprivatkund.ica.se") and c.get("name"):
            parts.append(f"{c['name']}={c.get('value', '')}")
    return "; ".join(parts)


def capture_cookie(store_id: str, *, timeout: float = 300.0,
                   auto: bool = True) -> str:
    """Open a headed browser at the store; return the captured Cookie header.

    The user logs in in the window. If ``auto`` and stdin is not a TTY, we poll
    the cookie jar until Handla session cookies appear (up to ``timeout``);
    otherwise we wait for the user to press Enter.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:  # pragma: no cover - depends on optional dep
        py = sys.executable
        raise UsageError(
            "Playwright is not installed. Install it for this interpreter:\n"
            f"  {py} -m pip install playwright && {py} -m playwright install chromium\n"
            "(or: pip install '.[browser]'), then re-run `ica handla login --browser`.",
            code="handla_browser_login_failed",
        ) from e

    start_url = _store_base(store_id)
    sys.stderr.write("Opening a browser — log in to Handla; the cookie is captured "
                     "once your store loads.\n")
    sys.stderr.flush()
    interactive = sys.stdin is not None and sys.stdin.isatty()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        try:
            page.goto(start_url, wait_until="domcontentloaded", timeout=120_000)
            header = ""
            if interactive or not auto:
                try:
                    input("Press Enter once you're logged in and see your store… ")
                except EOFError:
                    pass
                header = cookies_to_header(context.cookies())
            else:
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    header = cookies_to_header(context.cookies())
                    # AZAINGRESSAUTHCOOKIE / session markers appear after login
                    if header and len(header) > 40 and "=" in header:
                        time.sleep(1.5)  # let post-login cookies settle
                        header = cookies_to_header(context.cookies())
                        break
                    time.sleep(2.0)
        finally:
            browser.close()

    if not header.strip():
        raise UsageError("No handlaprivatkund.ica.se cookies captured — finish login "
                         "and wait for the store page before continuing.",
                         code="handla_browser_login_failed")
    return header

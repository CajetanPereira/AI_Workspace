"""Browser session manager.

Safety model: we never store your passwords. Instead we launch a real Chromium
with a *persistent profile directory* per platform. You log in manually once;
the cookies/session live in that directory and get reused on every later run.
This mimics a normal human browser session and avoids automating the login flow
(the single biggest trigger for bot detection / account bans).
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from playwright.sync_api import BrowserContext, sync_playwright

from .config import BROWSER_PROFILE_DIR

# A realistic, non-headless-looking UA. We always run headed for these sites.
_LAUNCH_ARGS = ["--disable-blink-features=AutomationControlled"]


@contextmanager
def browser_context(platform: str, *, headless: bool = False) -> Iterator[BrowserContext]:
    """Yield a persistent browser context for the given platform.

    headless defaults to False — LinkedIn/Naukri detect headless aggressively, and
    you need a visible window for the manual login and the final apply click.
    """
    profile_dir = BROWSER_PROFILE_DIR / platform
    profile_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=headless,
            args=_LAUNCH_ARGS,
            viewport={"width": 1280, "height": 900},
            locale="en-US",
        )
        # Light stealth: hide webdriver flag.
        ctx.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )
        try:
            yield ctx
        finally:
            ctx.close()


# URLs we send you to for the one-time manual login.
LOGIN_URLS = {
    "linkedin": "https://www.linkedin.com/login",
    "naukri": "https://www.naukri.com/nlogin/login",
}

# A URL + selector we can check to confirm you're logged in.
LOGGED_IN_CHECK = {
    "linkedin": ("https://www.linkedin.com/feed/", "img.global-nav__me-photo, .feed-identity-module"),
    "naukri": ("https://www.naukri.com/mnjuser/homepage", ".nI-gNb-drawer__bars, .view-profile-wrapper"),
}


def interactive_login(platform: str, timeout_s: int = 240) -> bool:
    """Open the login page and wait for you to sign in manually.

    Returns True once a logged-in marker is detected (or the page reaches the
    home/feed). Closes the browser afterward; the session persists on disk.
    """
    if platform not in LOGIN_URLS:
        raise ValueError(f"Unknown platform: {platform}")

    with browser_context(platform, headless=False) as ctx:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(LOGIN_URLS[platform])
        print(
            f"\n[{platform}] A browser window opened. Log in manually.\n"
            f"Waiting up to {timeout_s}s for you to finish... (the window will close once detected)"
        )
        check_url, selector = LOGGED_IN_CHECK[platform]
        try:
            # Poll: once the user navigates past login, the marker appears.
            page.wait_for_selector(selector, timeout=timeout_s * 1000)
            print(f"[{platform}] Login detected and saved.")
            return True
        except Exception:
            print(f"[{platform}] Timed out waiting for login. Re-run to try again.")
            return False


def is_logged_in(platform: str) -> bool:
    """Best-effort check that a saved session is still valid."""
    check_url, selector = LOGGED_IN_CHECK[platform]
    with browser_context(platform, headless=False) as ctx:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(check_url)
        try:
            page.wait_for_selector(selector, timeout=8000)
            return True
        except Exception:
            return False

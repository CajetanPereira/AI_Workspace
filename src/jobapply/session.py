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

from .config import BROWSER_PROFILE_DIR, settings

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
        launch_kwargs = dict(
            user_data_dir=str(profile_dir),
            headless=headless,
            args=_LAUNCH_ARGS,
            viewport={"width": 1280, "height": 900},
            locale="en-US",
        )
        # On Windows the bundled Chromium can hit a side-by-side/runtime error;
        # using the installed system browser (Edge/Chrome) avoids it.
        if settings.browser_channel:
            launch_kwargs["channel"] = settings.browser_channel
        ctx = p.chromium.launch_persistent_context(**launch_kwargs)
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

# Per platform: home URL to check, marker selectors, and URL fragments that mean
# "logged in" (i.e. no longer on a login/checkpoint page).
LOGGED_IN_CHECK = {
    "linkedin": (
        "https://www.linkedin.com/feed/",
        "img.global-nav__me-photo, .feed-identity-module, .global-nav__me, div.scaffold-layout",
        ("/feed", "/mynetwork", "/in/", "/jobs"),
    ),
    "naukri": (
        "https://www.naukri.com/mnjuser/homepage",
        ".nI-gNb-drawer__bars, .view-profile-wrapper, .nI-gNb-menuItems",
        ("mnjuser", "homepage"),
    ),
}

# Fragments that mean we're still on a login / checkpoint page.
_LOGIN_FRAGMENTS = ("/login", "/checkpoint", "/uas/", "signup", "/nlogin")


def _looks_logged_in(page, selectors: str, ok_fragments) -> bool:
    url = (page.url or "").lower()
    if any(f in url for f in _LOGIN_FRAGMENTS):
        return False
    if any(f in url for f in ok_fragments):
        return True
    try:
        return page.locator(selectors).count() > 0
    except Exception:
        return False


def interactive_login(platform: str, timeout_s: int = 300) -> bool:
    """Open the login page and wait for you to sign in manually.

    Polls for a logged-in state (URL left the login/checkpoint flow, or a nav
    marker appeared). Closes the browser afterward; the session persists on disk.
    """
    if platform not in LOGIN_URLS:
        raise ValueError(f"Unknown platform: {platform}")

    check_url, selectors, ok_fragments = LOGGED_IN_CHECK[platform]
    with browser_context(platform, headless=False) as ctx:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(LOGIN_URLS[platform])
        print(
            f"\n[{platform}] A browser window opened. Log in manually.\n"
            f"Waiting up to {timeout_s}s... (the window closes once login is detected)"
        )
        import time

        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if _looks_logged_in(page, selectors, ok_fragments):
                # small settle so cookies are flushed to the profile dir
                page.wait_for_timeout(1500)
                print(f"[{platform}] Login detected and saved.")
                return True
            page.wait_for_timeout(2000)
        print(f"[{platform}] Timed out waiting for login. Re-run to try again.")
        return False


def is_logged_in(platform: str) -> bool:
    """Best-effort check that a saved session is still valid."""
    check_url, selectors, ok_fragments = LOGGED_IN_CHECK[platform]
    with browser_context(platform, headless=False) as ctx:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(check_url)
        page.wait_for_timeout(3000)
        return _looks_logged_in(page, selectors, ok_fragments)

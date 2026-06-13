"""Scrape the logged-in user's OWN LinkedIn profile into raw text.

Used to build the structured profile without a resume upload. We find the profile
URL from the nav, open it, expand the long sections, and grab the page text — Claude
turns that into structured data (same extractor used for resumes).

Fragility caveat applies (see linkedin.py). Adjust selectors with PWDEBUG=1 if needed.
"""
from __future__ import annotations

from ..session import browser_context
from .base import human_pause


def _find_own_profile_url(page) -> str:
    """Discover the signed-in user's profile URL from the global nav 'Me' link."""
    page.goto("https://www.linkedin.com/feed/")
    human_pause(2, 4)

    # The left-rail profile card and the "Me" photo both link to /in/<handle>/.
    candidates = [
        "a.profile-card-profile-picture-container",          # left-rail card
        "a[href*='/in/'].ember-view",
        ".feed-identity-module a[href*='/in/']",
        "a.global-nav__me-photo",                            # opens menu; href may be /in/
    ]
    for sel in candidates:
        loc = page.locator(sel)
        if loc.count():
            href = loc.first.get_attribute("href") or ""
            if "/in/" in href:
                return href if href.startswith("http") else "https://www.linkedin.com" + href

    # Fallback: open the Me menu and read the "View Profile" link.
    me = page.locator("button.global-nav__primary-link-me-menu-trigger, .global-nav__me")
    if me.count():
        me.first.click()
        human_pause(1, 2)
        view = page.locator("a:has-text('View Profile'), a:has-text('View profile')")
        if view.count():
            href = view.first.get_attribute("href") or ""
            if href:
                return href if href.startswith("http") else "https://www.linkedin.com" + href

    raise RuntimeError(
        "Couldn't locate your profile URL. Are you logged in? "
        "Run: jobapply login linkedin"
    )


def scrape_own_profile() -> str:
    """Return the raw text of your LinkedIn profile page."""
    with browser_context("linkedin", headless=False) as ctx:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        url = _find_own_profile_url(page)
        page.goto(url)
        human_pause(2, 4)

        # Scroll through to lazy-load Experience / Skills sections.
        for _ in range(6):
            page.mouse.wheel(0, 1600)
            human_pause(0.6, 1.2)

        # Best-effort: expand any "see more" / "Show all" toggles in About/Experience.
        for label in ("see more", "Show more", "…see more"):
            btns = page.locator(f"button:has-text('{label}')")
            for i in range(min(btns.count(), 8)):
                try:
                    btns.nth(i).click(timeout=1000)
                    human_pause(0.3, 0.8)
                except Exception:
                    pass

        main = page.locator("main")
        text = main.first.inner_text(timeout=5000) if main.count() else page.inner_text("body")
        return text.strip()

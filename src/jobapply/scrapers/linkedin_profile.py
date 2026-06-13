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
    """Discover the signed-in user's profile URL.

    LinkedIn's class names are obfuscated/hashed, but the left-rail identity card
    on the feed is always the FIRST `/in/<handle>` link on the page — that's you.
    """
    page.goto("https://www.linkedin.com/feed/")
    human_pause(3, 5)

    hrefs = page.eval_on_selector_all(
        "a[href*='/in/']",
        "els => els.map(e => e.getAttribute('href')).filter(Boolean)",
    )
    if hrefs:
        href = hrefs[0].split("?")[0]
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

"""LinkedIn job search scraper.

Two modes:
  - keyword search (titles/keywords from preferences)
  - "Recommended" feed (jobs LinkedIn already matched to YOUR profile)
Set `platforms.linkedin.use_recommended: true` in preferences.yaml to use the feed.

NOTE ON FRAGILITY: LinkedIn's DOM changes frequently and varies by A/B test and
locale. The selectors below are a reasonable starting point captured against the
public/desktop jobs UI, but you WILL likely need to adjust them. Run with a visible
browser and use Playwright's inspector (PWDEBUG=1) to fix selectors when they drift.

This scraper relies on a logged-in persistent session (see session.py).
"""
from __future__ import annotations

import re
import urllib.parse

from ..session import browser_context
from .base import BaseScraper, ScrapedJob, human_pause, passes_filters

# Profile-matched job collections. "recommended" = "Top job picks for you".
RECOMMENDED_URL = "https://www.linkedin.com/jobs/collections/recommended/"


class LinkedInScraper(BaseScraper):
    platform = "linkedin"
    SEARCH_URL = "https://www.linkedin.com/jobs/search/"

    def _cfg(self):
        return self.prefs.platforms.get("linkedin")

    def _build_url(self, keyword: str) -> str:
        f = self.prefs.filters
        params = {"keywords": keyword}
        if f.locations:
            params["location"] = f.locations[0]
        params["f_TPR"] = f"r{f.posted_within_days * 86400}"  # posted within N days
        if self._cfg().easy_apply_only:
            params["f_AL"] = "true"   # Easy Apply filter
        return self.SEARCH_URL + "?" + urllib.parse.urlencode(params)

    def search(self) -> list[ScrapedJob]:
        cfg = self._cfg()
        if not cfg or not cfg.enabled:
            return []

        results: list[ScrapedJob] = []
        seen: set[str] = set()

        with browser_context("linkedin", headless=False) as ctx:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()

            if cfg.use_recommended:
                # Profile-matched feed — no keywords needed; LinkedIn ranks by your profile.
                page.goto(RECOMMENDED_URL)
                human_pause(2, 4)
                self._harvest(page, cfg, results, seen)
            else:
                for keyword in self.prefs.titles or [""]:
                    page.goto(self._build_url(keyword))
                    human_pause(2, 4)
                    self._harvest(page, cfg, results, seen, paginate=True)
                    if len(results) >= cfg.max_results:
                        break

        return results

    def _harvest(self, page, cfg, results, seen, *, paginate: bool = False) -> None:
        """Read job cards from the current results/feed page, optionally paginating."""
        while len(results) < cfg.max_results:
            cards = page.locator(
                "div.job-card-container, li.jobs-search-results__list-item, "
                "li.scaffold-layout__list-item"
            )
            count = cards.count()
            if count == 0:
                break

            for i in range(count):
                if len(results) >= cfg.max_results:
                    break
                card = cards.nth(i)
                try:
                    link = card.locator("a.job-card-container__link, a.job-card-list__title")
                    href = link.first.get_attribute("href") or ""
                    ext_id = self._extract_id(href)
                    if not ext_id or ext_id in seen:
                        continue
                    seen.add(ext_id)

                    card.click()
                    human_pause(1.5, 3)

                    title = self._text(page, "h1.job-details-jobs-unified-top-card__job-title, .jobs-unified-top-card__job-title")
                    company = self._text(page, ".job-details-jobs-unified-top-card__company-name, .jobs-unified-top-card__company-name")
                    location = self._text(page, ".job-details-jobs-unified-top-card__bullet, .jobs-unified-top-card__bullet")
                    desc = self._text(page, "#job-details, .jobs-description__content")
                    easy = page.locator("button.jobs-apply-button:has-text('Easy Apply')").count() > 0

                    if cfg.easy_apply_only and not easy:
                        continue

                    job = ScrapedJob(
                        platform="linkedin",
                        external_id=ext_id,
                        url=f"https://www.linkedin.com/jobs/view/{ext_id}/",
                        title=title, company=company, location=location,
                        description=desc, easy_apply=easy,
                    )
                    if passes_filters(job, self.prefs):
                        results.append(job)
                except Exception as e:
                    print(f"[linkedin] skipped a card: {e}")
                    continue

            if not paginate:
                break
            nxt = page.locator("button[aria-label='View next page']")
            if nxt.count() and nxt.first.is_enabled():
                nxt.first.click()
                human_pause(2, 4)
            else:
                break

    @staticmethod
    def _extract_id(href: str) -> str:
        m = re.search(r"/jobs/view/(\d+)", href) or re.search(r"currentJobId=(\d+)", href)
        return m.group(1) if m else ""

    @staticmethod
    def _text(page, selector: str) -> str:
        loc = page.locator(selector)
        if loc.count():
            try:
                return (loc.first.inner_text(timeout=2000) or "").strip()
            except Exception:
                return ""
        return ""

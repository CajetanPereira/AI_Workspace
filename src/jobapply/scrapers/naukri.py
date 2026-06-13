"""Naukri job search scraper.

Same fragility caveat as LinkedIn: Naukri's DOM changes and is heavily client-rendered.
Selectors here target the desktop search results (naukri.com/<keyword>-jobs). Adjust as needed.
Relies on a logged-in persistent session (see session.py).
"""
from __future__ import annotations

import re
import urllib.parse

from ..session import browser_context
from .base import BaseScraper, ScrapedJob, human_pause, passes_filters


class NaukriScraper(BaseScraper):
    platform = "naukri"

    def _cfg(self):
        return self.prefs.platforms.get("naukri")

    def _build_url(self, keyword: str, page_num: int) -> str:
        # Naukri uses path-style search: /python-developer-jobs-in-bengaluru-2
        kw = keyword.strip().lower().replace(" ", "-")
        f = self.prefs.filters
        path = f"{kw}-jobs"
        if f.locations:
            loc = f.locations[0].strip().lower().replace(" ", "-")
            path += f"-in-{loc}"
        if page_num > 1:
            path += f"-{page_num}"
        params = {}
        if f.experience_years is not None:
            params["experience"] = f.experience_years
        qs = ("?" + urllib.parse.urlencode(params)) if params else ""
        return f"https://www.naukri.com/{path}{qs}"

    def search(self) -> list[ScrapedJob]:
        cfg = self._cfg()
        if not cfg or not cfg.enabled:
            return []

        results: list[ScrapedJob] = []
        seen: set[str] = set()

        with browser_context("naukri", headless=False) as ctx:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()

            for keyword in self.prefs.titles or [""]:
                page_num = 1
                while len(results) < cfg.max_results and page_num <= 10:
                    page.goto(self._build_url(keyword, page_num))
                    human_pause(2, 4)

                    cards = page.locator("div.srp-jobtuple-wrapper, article.jobTuple")
                    count = cards.count()
                    if count == 0:
                        break

                    for i in range(count):
                        if len(results) >= cfg.max_results:
                            break
                        card = cards.nth(i)
                        try:
                            link = card.locator("a.title")
                            href = link.first.get_attribute("href") or ""
                            ext_id = self._extract_id(href)
                            if not ext_id or ext_id in seen:
                                continue
                            seen.add(ext_id)

                            title = self._text(card, "a.title")
                            company = self._text(card, "a.comp-name, .companyInfo")
                            location = self._text(card, ".locWdth, .loc")
                            salary = self._text(card, ".salWdth, .sal")
                            desc = self._text(card, ".job-desc, .job-description")

                            job = ScrapedJob(
                                platform="naukri",
                                external_id=ext_id,
                                url=href,
                                title=title,
                                company=company,
                                location=location,
                                salary=salary,
                                description=desc,
                                easy_apply=True,  # Naukri "Apply" is mostly on-site
                            )
                            if passes_filters(job, self.prefs):
                                results.append(job)
                        except Exception as e:
                            print(f"[naukri] skipped a card: {e}")
                            continue

                    page_num += 1

        return results

    @staticmethod
    def _extract_id(href: str) -> str:
        # job URLs end with ...-<id> e.g. /job-listings-python-developer-acme-bengaluru-3-to-5-years-310524000123
        m = re.search(r"-(\d{6,})(?:\?|$)", href)
        return m.group(1) if m else href[-40:]

    @staticmethod
    def _text(scope, selector: str) -> str:
        loc = scope.locator(selector)
        if loc.count():
            try:
                return (loc.first.inner_text(timeout=2000) or "").strip()
            except Exception:
                return ""
        return ""

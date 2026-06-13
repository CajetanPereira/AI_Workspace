"""Base scraper utilities."""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, field

from sqlmodel import select

from ..config import Preferences
from ..db import get_session
from ..models import Job


@dataclass
class ScrapedJob:
    """A job as pulled from a board, before it's persisted."""

    platform: str
    external_id: str
    url: str
    title: str
    company: str = ""
    location: str = ""
    description: str = ""
    salary: str = ""
    posted_at: str | None = None
    easy_apply: bool = False


def human_pause(lo: float = 1.2, hi: float = 3.5) -> None:
    """Randomized delay to mimic human pacing and avoid rate-limit traps."""
    time.sleep(random.uniform(lo, hi))


def passes_filters(job: ScrapedJob, prefs: Preferences) -> bool:
    """Apply hard filters from preferences before we bother storing/ranking."""
    f = prefs.filters
    haystack = f"{job.title} {job.description}".lower()
    if any(kw.lower() in haystack for kw in f.exclude_keywords):
        return False
    if f.locations and not f.remote_ok:
        if not any(loc.lower() in job.location.lower() for loc in f.locations):
            return False
    return True


def save_jobs(scraped: list[ScrapedJob]) -> int:
    """Upsert scraped jobs into the DB by (platform, external_id). Returns # new."""
    new_count = 0
    with get_session() as session:
        for s in scraped:
            existing = session.exec(
                select(Job).where(
                    Job.platform == s.platform, Job.external_id == s.external_id
                )
            ).first()
            if existing:
                continue
            session.add(
                Job(
                    platform=s.platform,
                    external_id=s.external_id,
                    url=s.url,
                    title=s.title,
                    company=s.company,
                    location=s.location,
                    description=s.description,
                    salary=s.salary,
                    posted_at=s.posted_at,
                    easy_apply=s.easy_apply,
                )
            )
            new_count += 1
        session.commit()
    return new_count


class BaseScraper:
    platform: str = ""

    def __init__(self, prefs: Preferences):
        self.prefs = prefs

    def search(self) -> list[ScrapedJob]:  # pragma: no cover - interface
        raise NotImplementedError

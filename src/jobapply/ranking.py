"""Score scraped jobs against the user's profile + preferences using Claude."""
from __future__ import annotations

import json

from sqlmodel import select

from .config import Preferences
from .db import get_session
from .llm import complete_json
from .models import ApplicationStatus, Job, Profile

RANK_SYSTEM = (
    "You are a precise technical recruiter. Score how well a candidate fits a job, "
    "based only on the evidence provided. Be calibrated: 90+ means an excellent, "
    "clearly-qualified match; 50 means borderline; below 40 means poor fit."
)

RANK_PROMPT = """Score this candidate against this job posting.

CANDIDATE PROFILE (JSON):
{profile}

TARGET KEYWORDS (extra weight if present): {keywords}

JOB POSTING:
Title: {title}
Company: {company}
Location: {location}
Description:
{description}

Return JSON: {{"score": <0-100 integer>, "reasons": "<=2 sentences explaining the score, naming the biggest match and biggest gap"}}
"""


def rank_new_jobs(prefs: Preferences, limit: int | None = None) -> int:
    """Score all jobs in NEW status. Returns number scored."""
    with get_session() as session:
        profile = session.exec(select(Profile)).first()
        if not profile:
            raise RuntimeError("No profile found. Run `parse-resume` first.")
        profile_json = profile.structured_json or json.dumps(
            {"raw": profile.raw_resume_text[:4000]}
        )

        q = select(Job).where(Job.status == ApplicationStatus.NEW)
        if limit:
            q = q.limit(limit)
        jobs = session.exec(q).all()

        scored = 0
        for job in jobs:
            try:
                result = complete_json(
                    RANK_PROMPT.format(
                        profile=profile_json[:8000],
                        keywords=", ".join(prefs.keywords),
                        title=job.title,
                        company=job.company,
                        location=job.location,
                        description=(job.description or "")[:6000],
                    ),
                    system=RANK_SYSTEM,
                )
                job.score = int(result.get("score", 0))
                job.score_reasons = str(result.get("reasons", ""))
                job.status = ApplicationStatus.RANKED
                session.add(job)
                session.commit()
                scored += 1
            except Exception as e:
                print(f"[rank] failed for job {job.id} ({job.title}): {e}")
        return scored

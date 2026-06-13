"""Score scraped jobs against the user's profile + preferences using the LLM.

Jobs are scored in BATCHES (many jobs per LLM request) to stay within free-tier
request limits — e.g. Gemini's free tier caps requests per day, so one-request-
per-job quickly exhausts the quota. Batching ~12 jobs/request cuts 80 jobs down
to ~7 requests.
"""
from __future__ import annotations

import json

from sqlmodel import select

from .config import Preferences
from .db import get_session
from .llm import complete_json
from .models import ApplicationStatus, Job, Profile

# How many jobs to score per LLM request.
BATCH_SIZE = 12

RANK_SYSTEM = (
    "You are a precise technical recruiter. Score how well a candidate fits each job, "
    "based only on the evidence provided. Be calibrated: 90+ means an excellent, "
    "clearly-qualified match; 50 means borderline; below 40 means poor fit."
)

RANK_BATCH_PROMPT = """Score this candidate against EACH of the job postings below.

CANDIDATE PROFILE (JSON):
{profile}

TARGET KEYWORDS (extra weight if present): {keywords}

JOB POSTINGS (each starts with its numeric id):
{jobs}

Return a JSON object of this exact shape, with one entry per job id above:
{{"rankings": [{{"id": <job id>, "score": <0-100 integer>, "reasons": "<=2 sentences naming the biggest match and biggest gap"}}]}}
"""


def _job_block(job: Job) -> str:
    return (
        f"--- id: {job.id}\n"
        f"Title: {job.title}\n"
        f"Company: {job.company}\n"
        f"Location: {job.location}\n"
        f"Description: {(job.description or '')[:1800]}\n"
    )


def rank_new_jobs(prefs: Preferences, limit: int | None = None) -> int:
    """Score all jobs in NEW status, in batches. Returns number scored."""
    with get_session() as session:
        profile = session.exec(select(Profile)).first()
        if not profile:
            raise RuntimeError("No profile found. Run `parse-resume` or `profile-linkedin` first.")
        profile_json = profile.structured_json or json.dumps(
            {"raw": profile.raw_resume_text[:4000]}
        )

        q = select(Job).where(Job.status == ApplicationStatus.NEW)
        if limit:
            q = q.limit(limit)
        jobs = session.exec(q).all()

        scored = 0
        for start in range(0, len(jobs), BATCH_SIZE):
            batch = jobs[start : start + BATCH_SIZE]
            by_id = {j.id: j for j in batch}
            jobs_text = "\n".join(_job_block(j) for j in batch)
            try:
                result = complete_json(
                    RANK_BATCH_PROMPT.format(
                        profile=profile_json[:8000],
                        keywords=", ".join(prefs.keywords),
                        jobs=jobs_text,
                    ),
                    system=RANK_SYSTEM,
                    max_tokens=4000,
                )
                rankings = result.get("rankings", []) if isinstance(result, dict) else []
                for r in rankings:
                    job = by_id.get(r.get("id"))
                    if not job:
                        continue
                    job.score = int(r.get("score", 0))
                    job.score_reasons = str(r.get("reasons", ""))
                    job.status = ApplicationStatus.RANKED
                    session.add(job)
                    scored += 1
                session.commit()
                print(f"[rank] batch {start // BATCH_SIZE + 1}: scored {len(rankings)} jobs")
            except Exception as e:
                print(f"[rank] batch starting at {start} failed: {e}")
        return scored

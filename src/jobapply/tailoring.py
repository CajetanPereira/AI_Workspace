"""Generate tailored resume highlights + a cover letter per job using Claude."""
from __future__ import annotations

import json
import re
from pathlib import Path

from sqlmodel import select

from .config import OUTPUT_DIR
from .db import get_session
from .llm import complete
from .models import Application, ApplicationStatus, Job, Profile

TAILOR_SYSTEM = (
    "You are an expert career coach and resume writer. You tailor genuine candidate "
    "material to a specific job. Never fabricate experience, skills, or credentials — "
    "only re-emphasize and reword what the candidate actually has."
)

BULLETS_PROMPT = """Given the candidate profile and this job, write 5-7 tailored resume bullet points
that re-frame the candidate's REAL experience toward this role. Use strong action verbs and
quantified impact where the profile supports it. Do not invent anything.

CANDIDATE PROFILE (JSON):
{profile}

JOB:
{title} at {company}
{description}

Output the bullets as a plain markdown list, nothing else."""

COVER_PROMPT = """Write a concise, specific cover letter (about 200-250 words) for this candidate
and job. Reference 2-3 concrete, real strengths from the profile that match the job. Professional
but warm tone. No placeholders like [Your Name] — use the actual name if present, else omit.

CANDIDATE PROFILE (JSON):
{profile}

JOB:
{title} at {company}
{description}

Output only the cover letter body text."""


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60]


def tailor_job(job_id: int) -> Application:
    """Generate tailored bullets + cover letter for one job, save to output/ and DB."""
    with get_session() as session:
        job = session.get(Job, job_id)
        if not job:
            raise ValueError(f"No job with id {job_id}")
        profile = session.exec(select(Profile)).first()
        if not profile:
            raise RuntimeError("No profile found. Run `parse-resume` first.")
        profile_json = profile.structured_json or profile.raw_resume_text[:4000]

        bullets = complete(
            BULLETS_PROMPT.format(
                profile=profile_json[:8000],
                title=job.title,
                company=job.company,
                description=(job.description or "")[:6000],
            ),
            system=TAILOR_SYSTEM,
            max_tokens=1200,
        )
        cover = complete(
            COVER_PROMPT.format(
                profile=profile_json[:8000],
                title=job.title,
                company=job.company,
                description=(job.description or "")[:6000],
            ),
            system=TAILOR_SYSTEM,
            max_tokens=900,
        )

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        base = f"{job.id}-{_slug(job.company)}-{_slug(job.title)}"
        resume_path = OUTPUT_DIR / f"{base}-highlights.md"
        cover_path = OUTPUT_DIR / f"{base}-cover-letter.md"
        resume_path.write_text(
            f"# Tailored highlights — {job.title} @ {job.company}\n\n{bullets}\n",
            encoding="utf-8",
        )
        cover_path.write_text(cover + "\n", encoding="utf-8")

        app = session.exec(
            select(Application).where(Application.job_id == job.id)
        ).first() or Application(job_id=job.id)
        app.tailored_resume_path = str(resume_path)
        app.cover_letter_path = str(cover_path)
        session.add(app)

        job.status = ApplicationStatus.TAILORED
        session.add(job)
        session.commit()
        session.refresh(app)
        return app

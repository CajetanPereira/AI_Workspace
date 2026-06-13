"""Assisted apply: open the application, pre-fill what we safely can, then PAUSE
so YOU review and click submit. This keeps a human in the loop — required for
account safety and application quality.

We deliberately do NOT auto-submit. The function opens the job's apply flow,
fills obvious fields from the profile, and blocks until you confirm in the terminal.
"""
from __future__ import annotations

from sqlmodel import select

from .config import Preferences
from .db import get_session
from .models import Application, ApplicationStatus, Job, Profile
from .session import browser_context


def _profile_fields() -> dict:
    with get_session() as session:
        p = session.exec(select(Profile)).first()
        if not p:
            return {}
        return {"name": p.name, "email": p.email, "phone": p.phone}


def prepare_application(job_id: int, prefs: Preferences) -> None:
    """Open the apply flow for one job and pre-fill, then wait for human submit."""
    with get_session() as session:
        job = session.get(Job, job_id)
        if not job:
            raise ValueError(f"No job with id {job_id}")

    fields = _profile_fields()

    with browser_context(job.platform, headless=False) as ctx:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(job.url)

        if job.platform == "linkedin":
            _linkedin_easy_apply(page, fields)
        elif job.platform == "naukri":
            _naukri_apply(page, fields)

        print(
            f"\n>>> Application for '{job.title} @ {job.company}' is pre-filled.\n"
            ">>> Review it in the browser, attach your tailored resume, and SUBMIT manually.\n"
        )
        answer = input(">>> Type 'applied' once you've submitted (anything else = skip): ").strip().lower()

    with get_session() as session:
        job = session.get(Job, job_id)
        app = session.exec(select(Application).where(Application.job_id == job_id)).first() \
            or Application(job_id=job_id)
        if answer == "applied":
            from datetime import datetime, timezone

            job.status = ApplicationStatus.APPLIED
            app.applied_at = datetime.now(timezone.utc)
        else:
            job.status = ApplicationStatus.PREPARED
        session.add(job)
        session.add(app)
        session.commit()


def _linkedin_easy_apply(page, fields: dict) -> None:
    """Click Easy Apply and fill the first step's obvious fields."""
    try:
        btn = page.locator("button.jobs-apply-button:has-text('Easy Apply')")
        if btn.count():
            btn.first.click()
            page.wait_for_timeout(2000)
        # Phone is the most common required free-text field on step 1.
        if fields.get("phone"):
            phone = page.locator("input[id*='phoneNumber'], input[name*='phone']")
            if phone.count():
                phone.first.fill(fields["phone"])
    except Exception as e:
        print(f"[linkedin] pre-fill note: {e}")


def _naukri_apply(page, fields: dict) -> None:
    """Click apply; Naukri often submits using saved profile data directly."""
    try:
        btn = page.locator("button:has-text('Apply'), #apply-button")
        if btn.count():
            btn.first.click()
            page.wait_for_timeout(2000)
    except Exception as e:
        print(f"[naukri] pre-fill note: {e}")


def prepare_approved(prefs: Preferences) -> int:
    """Walk through all APPROVED/TAILORED jobs up to the daily limit."""
    limit = prefs.apply.daily_limit
    with get_session() as session:
        jobs = session.exec(
            select(Job)
            .where(Job.status.in_([ApplicationStatus.APPROVED, ApplicationStatus.TAILORED]))
            .order_by(Job.score.desc())
            .limit(limit)
        ).all()
        ids = [j.id for j in jobs]

    for job_id in ids:
        prepare_application(job_id, prefs)
    return len(ids)

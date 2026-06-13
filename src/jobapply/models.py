"""Database models (SQLModel over SQLite)."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlmodel import Field, SQLModel


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ApplicationStatus(str, Enum):
    NEW = "new"               # freshly scraped, not yet ranked
    RANKED = "ranked"         # scored against profile
    APPROVED = "approved"     # user approved for application
    REJECTED = "rejected"     # user rejected
    TAILORED = "tailored"     # resume/cover letter generated
    PREPARED = "prepared"     # form pre-filled, awaiting submit
    APPLIED = "applied"       # submitted (by user)
    SKIPPED = "skipped"       # could not apply (e.g. external site)


class Job(SQLModel, table=True):
    """A scraped job posting."""

    id: Optional[int] = Field(default=None, primary_key=True)
    # Stable de-dup key: platform + the platform's own job id
    platform: str = Field(index=True)             # "linkedin" | "naukri"
    external_id: str = Field(index=True)
    url: str

    title: str
    company: str = ""
    location: str = ""
    description: str = ""                          # full JD text
    salary: str = ""                               # raw text, parsing is best-effort
    posted_at: Optional[str] = None                # raw relative/absolute text from site
    easy_apply: bool = False                        # LinkedIn Easy Apply / Naukri quick-apply

    status: ApplicationStatus = Field(default=ApplicationStatus.NEW, index=True)
    score: Optional[int] = None                    # 0-100 relevance
    score_reasons: str = ""                        # short rationale from the ranker

    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class Application(SQLModel, table=True):
    """Per-job application artifacts and outcome."""

    id: Optional[int] = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="job.id", index=True)

    tailored_resume_path: str = ""
    cover_letter_path: str = ""
    notes: str = ""
    applied_at: Optional[datetime] = None

    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class Profile(SQLModel, table=True):
    """The user's structured profile, extracted from their resume."""

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = ""
    email: str = ""
    phone: str = ""
    raw_resume_text: str = ""
    structured_json: str = ""                       # JSON blob: skills, experience, education...
    resume_path: str = ""

    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

"""Resume parsing + structured profile extraction."""
from __future__ import annotations

import json
from pathlib import Path

from sqlmodel import select

from .db import get_session
from .llm import complete_json
from .models import Profile


def extract_text(resume_path: Path) -> str:
    """Extract raw text from a PDF or DOCX resume."""
    suffix = resume_path.suffix.lower()
    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(resume_path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    if suffix in (".docx", ".doc"):
        import docx

        doc = docx.Document(str(resume_path))
        return "\n".join(p.text for p in doc.paragraphs)
    if suffix in (".txt", ".md"):
        return resume_path.read_text(encoding="utf-8", errors="ignore")
    raise ValueError(f"Unsupported resume format: {suffix} (use .pdf, .docx, .txt)")


PROFILE_SYSTEM = (
    "You are an expert resume parser. Extract structured data from resumes accurately. "
    "Never invent information that isn't present."
)

PROFILE_PROMPT = """Extract a structured profile from this resume.

Return JSON with exactly these keys:
- name (string)
- email (string)
- phone (string)
- summary (string, 1-2 sentences)
- total_experience_years (number)
- skills (array of strings)
- titles (array of past/target job titles)
- experience (array of {{company, title, duration, highlights:[strings]}})
- education (array of {{degree, institution, year}})

RESUME:
{resume_text}
"""


def _store_profile(text: str, *, source: str) -> Profile:
    """Run Claude extraction on raw text and upsert the single Profile row."""
    if not text.strip():
        raise ValueError("No text to build a profile from.")
    data = complete_json(
        PROFILE_PROMPT.format(resume_text=text[:20000]),
        system=PROFILE_SYSTEM,
    )
    with get_session() as session:
        profile = session.exec(select(Profile)).first() or Profile()
        profile.name = str(data.get("name", ""))
        profile.email = str(data.get("email", ""))
        profile.phone = str(data.get("phone", ""))
        profile.raw_resume_text = text
        profile.structured_json = json.dumps(data, ensure_ascii=False, indent=2)
        profile.resume_path = source
        session.add(profile)
        session.commit()
        session.refresh(profile)
        return profile


def build_profile(resume_path: Path) -> Profile:
    """Parse a resume file into a stored Profile (replaces any existing profile)."""
    text = extract_text(resume_path)
    return _store_profile(text, source=str(resume_path))


def build_profile_from_linkedin() -> Profile:
    """Build the profile by scraping YOUR OWN LinkedIn profile page (logged-in session)."""
    from .scrapers.linkedin_profile import scrape_own_profile

    text = scrape_own_profile()
    return _store_profile(text, source="linkedin:profile")


def get_profile() -> Profile | None:
    with get_session() as session:
        return session.exec(select(Profile)).first()

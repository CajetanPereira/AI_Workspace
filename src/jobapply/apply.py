"""Apply automation.

Two modes:
- `prepare_application` (CLI): opens the apply flow, pre-fills, and pauses for you to submit.
- `auto_apply` (web dashboard): drives the real apply flow on the site and SUBMITS it.

Auto-apply uses your existing logged-in browser session, paces like a human, respects a
per-day cap, and REFUSES to submit (leaving the job "prepared" with a note) when a required
screening question or resume upload can't be satisfied — it never guesses a required answer.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone

from sqlmodel import select

from .config import Preferences, load_preferences
from .db import get_session
from .models import Application, ApplicationStatus, Job, Profile
from .session import browser_context
from .scrapers.base import human_pause

# Only one apply browser at a time — the persistent profile dir is single-locked.
_APPLY_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Profile + answer resolution
# ---------------------------------------------------------------------------

def _profile_fields() -> dict:
    with get_session() as session:
        p = session.exec(select(Profile)).first()
        if not p:
            return {}
        return {"name": p.name, "email": p.email, "phone": p.phone}


def _llm_answer(question: str, profile: dict) -> str | None:
    """Last-resort: ask the LLM to answer a screening question from the profile.

    Returns None on any failure (e.g. exhausted free-tier quota) so the caller can
    treat the question as unanswered rather than crash.
    """
    try:
        from .llm import complete

        ans = complete(
            f"Answer this job-application question for the candidate, concisely. "
            f"If it asks for a number of years, reply with just a number.\n\n"
            f"Question: {question}\n\nCandidate: {profile.get('summary', '')}",
            max_tokens=40,
        ).strip()
        return ans or None
    except Exception:
        return None


def _answer_for(question: str, prefs: Preferences, profile: dict) -> str | None:
    """Resolve an answer for a screening question: config answers -> profile -> LLM."""
    q = (question or "").lower().strip()
    if not q:
        return None

    # 1. Configured standard answers (substring match on the question label).
    for key, val in prefs.apply.answers.items():
        if key.lower() in q and str(val).strip():
            return str(val)

    # 2. Profile-derived fields.
    if any(w in q for w in ("phone", "mobile", "contact number")):
        return profile.get("phone") or None
    if "email" in q:
        return profile.get("email") or None
    if any(w in q for w in ("first name", "full name")):
        return profile.get("name") or None

    # 3. LLM fallback.
    return _llm_answer(question, profile)


# ---------------------------------------------------------------------------
# LinkedIn Easy Apply — multi-step form filling
# ---------------------------------------------------------------------------

_MODAL = "div.jobs-easy-apply-modal, div[role='dialog']"


def _label_for(page, el) -> str:
    """Best-effort human label for a form control."""
    try:
        aid = el.get_attribute("id")
        if aid:
            lbl = page.locator(f"label[for='{aid}']")
            if lbl.count():
                return (lbl.first.inner_text() or "").strip()
        return (el.get_attribute("aria-label") or "").strip()
    except Exception:
        return ""


def _is_required(el) -> bool:
    try:
        if (el.get_attribute("aria-required") or "").lower() == "true":
            return True
        if el.get_attribute("required") is not None:
            return True
    except Exception:
        pass
    return False


def _fill_step(page, prefs: Preferences, profile: dict) -> list[str]:
    """Fill visible fields in the current Easy Apply step. Returns unfilled REQUIRED labels."""
    modal = page.locator(_MODAL).first
    missing: list[str] = []

    # Resume upload (if a file input is present on this step).
    files = modal.locator("input[type='file']")
    if files.count() and prefs.apply.resume_path:
        try:
            files.first.set_input_files(prefs.apply.resume_path)
            human_pause(1, 2)
        except Exception as e:
            print(f"[apply] resume upload failed: {e}")

    # Text / number / email / tel inputs and textareas.
    text_inputs = modal.locator(
        "input[type='text'], input[type='number'], input[type='email'], "
        "input[type='tel'], input:not([type]), textarea"
    )
    for i in range(text_inputs.count()):
        el = text_inputs.nth(i)
        try:
            if (el.input_value() or "").strip():
                continue  # already filled
            label = _label_for(page, el)
            ans = _answer_for(label, prefs, profile)
            if ans:
                el.fill(ans)
                human_pause(0.3, 0.9)
            elif _is_required(el):
                missing.append(label or "(unlabeled text field)")
        except Exception:
            continue

    # Selects (dropdowns).
    selects = modal.locator("select")
    for i in range(selects.count()):
        el = selects.nth(i)
        try:
            label = _label_for(page, el)
            ans = _answer_for(label, prefs, profile)
            options = el.locator("option")
            chosen = False
            if ans:
                for j in range(options.count()):
                    otext = (options.nth(j).inner_text() or "").strip().lower()
                    if otext and (ans.lower() in otext or otext in ans.lower()):
                        el.select_option(label=(options.nth(j).inner_text() or "").strip())
                        chosen = True
                        break
            cur = (el.input_value() or "").lower()
            if not chosen and _is_required(el) and (not cur or "select" in cur):
                missing.append(label or "(dropdown)")
        except Exception:
            continue

    # Radio groups (e.g. Yes/No screening questions).
    radios = modal.locator("input[type='radio']")
    seen_groups: set[str] = set()
    for i in range(radios.count()):
        el = radios.nth(i)
        try:
            name = el.get_attribute("name") or ""
            if name in seen_groups:
                continue
            seen_groups.add(name)
            group = modal.locator(f"input[type='radio'][name='{name}']")
            # The question label is usually a group legend/label near the first radio.
            question = _label_for(page, el) or ""
            if not question:
                fs = el.locator("xpath=ancestor::fieldset[1]//legend")
                if fs.count():
                    question = (fs.first.inner_text() or "").strip()
            ans = _answer_for(question, prefs, profile)
            picked = False
            if ans:
                for j in range(group.count()):
                    opt = group.nth(j)
                    opt_label = _label_for(page, opt)
                    if opt_label and (ans.lower() in opt_label.lower() or opt_label.lower() in ans.lower()):
                        opt.check()
                        picked = True
                        break
            if not picked and _is_required(el):
                missing.append(question or "(choice)")
        except Exception:
            continue

    return missing


def _footer_button(page):
    """Return (kind, locator) for the primary footer button of the Easy Apply modal."""
    modal = page.locator(_MODAL).first
    for kind, sel in [
        ("submit", "button[aria-label='Submit application'], button:has-text('Submit application')"),
        ("review", "button[aria-label='Review your application'], button:has-text('Review')"),
        ("next", "button[aria-label='Continue to next step'], button:has-text('Next'), button:has-text('Continue')"),
    ]:
        loc = modal.locator(sel)
        if loc.count():
            return kind, loc.first
    return None, None


def _linkedin_auto_apply(page, job: Job, prefs: Preferences, profile: dict):
    """Drive LinkedIn Easy Apply to submission. Returns (ApplicationStatus, note)."""
    btn = page.locator("button.jobs-apply-button:has-text('Easy Apply'), button:has-text('Easy Apply')")
    if not btn.count():
        return ApplicationStatus.SKIPPED, "No Easy Apply on this job (external application)."
    btn.first.click()
    human_pause(1.5, 3)

    for _ in range(10):  # cap steps to avoid loops
        if not page.locator(_MODAL).count():
            break
        missing = _fill_step(page, prefs, profile)
        if missing:
            return ApplicationStatus.PREPARED, "Needs: " + "; ".join(missing[:5])

        kind, button = _footer_button(page)
        if button is None:
            break
        human_pause(0.8, 1.8)

        if kind == "submit":
            if not prefs.apply.auto_submit:
                return ApplicationStatus.PREPARED, "auto_submit is off; stopped before Submit."
            button.click()
            human_pause(2, 3.5)
            if page.locator(":has-text('application was sent'), :has-text('Application sent'), :has-text('Your application was sent')").count():
                return ApplicationStatus.APPLIED, "Submitted via Easy Apply."
            return ApplicationStatus.APPLIED, "Submitted (confirmation not detected)."
        button.click()
        human_pause(1.2, 2.5)

    return ApplicationStatus.PREPARED, "Could not reach Submit (flow changed or extra steps)."


# ---------------------------------------------------------------------------
# Naukri — usually one-click apply
# ---------------------------------------------------------------------------

def _naukri_auto_apply(page, job: Job, prefs: Preferences, profile: dict):
    """Click Naukri Apply and detect the outcome. Returns (ApplicationStatus, note)."""
    # External-site apply?
    if page.locator("button:has-text('Apply on company site'), a:has-text('Apply on company site')").count():
        return ApplicationStatus.SKIPPED, "Redirects to external company site."

    btn = page.locator("button#apply-button, button:has-text('Apply'), a:has-text('Apply')")
    if not btn.count():
        return ApplicationStatus.SKIPPED, "No Apply button found."
    if not prefs.apply.auto_submit:
        return ApplicationStatus.PREPARED, "auto_submit is off; stopped before Apply."
    btn.first.click()
    human_pause(2, 4)

    # A chatbot may ask a few questions.
    for _ in range(6):
        chat_q = page.locator(".chatbot_MessageContainer li, .botMsg, textarea.chatbot_TextInput")
        ta = page.locator("textarea.chatbot_TextInput, input.chatbot_input")
        if not ta.count():
            break
        question = ""
        qloc = page.locator(".botMsg, .chatbot_MessageContainer .botItem")
        if qloc.count():
            question = (qloc.last.inner_text() or "").strip()
        ans = _answer_for(question, prefs, profile)
        if not ans:
            return ApplicationStatus.PREPARED, f"Chatbot question unanswered: {question[:60]}"
        ta.first.fill(ans)
        send = page.locator(".sendMsg, .chatbot_send, button:has-text('Save')")
        if send.count():
            send.first.click()
        human_pause(1.5, 3)

    if page.locator(":has-text('successfully applied'), :has-text('You have already applied'), :has-text('Application sent')").count():
        return ApplicationStatus.APPLIED, "Applied on Naukri."
    return ApplicationStatus.APPLIED, "Apply clicked (confirmation not detected)."


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def _applied_today() -> int:
    since = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    with get_session() as session:
        apps = session.exec(select(Application).where(Application.applied_at.is_not(None))).all()
        return sum(1 for a in apps if a.applied_at and a.applied_at >= since)


def auto_apply(job_id: int, prefs: Preferences | None = None) -> tuple[str, str]:
    """Open the browser and actually apply to one job. Returns (status, note).

    Thread-safe (serialized) and safe to call from a web request's background thread.
    """
    prefs = prefs or load_preferences()

    with get_session() as session:
        job = session.get(Job, job_id)
        if not job:
            return "error", f"No job with id {job_id}"
        platform, url, title, company = job.platform, job.url, job.title, job.company

    if _applied_today() >= prefs.apply.daily_limit:
        _record(job_id, ApplicationStatus.PREPARED, "Daily apply limit reached.")
        return ApplicationStatus.PREPARED.value, "Daily apply limit reached."

    profile = _profile_fields()
    # include summary for the LLM fallback
    with get_session() as session:
        p = session.exec(select(Profile)).first()
        if p:
            profile["summary"] = (p.raw_resume_text or "")[:1500]

    with _APPLY_LOCK:
        try:
            with browser_context(platform, headless=False) as ctx:
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                page.goto(url)
                human_pause(2, 4)
                if platform == "linkedin":
                    status, note = _linkedin_auto_apply(page, job, prefs, profile)
                elif platform == "naukri":
                    status, note = _naukri_auto_apply(page, job, prefs, profile)
                else:
                    status, note = ApplicationStatus.SKIPPED, f"Unsupported platform: {platform}"
                human_pause(1, 2)  # let the page settle before closing
        except Exception as e:
            status, note = ApplicationStatus.PREPARED, f"Apply error: {e}"

    _record(job_id, status, note)
    print(f"[apply] {title} @ {company}: {status.value if hasattr(status,'value') else status} — {note}")
    return (status.value if hasattr(status, "value") else status), note


def _record(job_id: int, status: ApplicationStatus, note: str) -> None:
    with get_session() as session:
        job = session.get(Job, job_id)
        app = session.exec(select(Application).where(Application.job_id == job_id)).first() \
            or Application(job_id=job_id)
        if job:
            job.status = status
            session.add(job)
        app.notes = note
        if status == ApplicationStatus.APPLIED:
            app.applied_at = datetime.now(timezone.utc)
        session.add(app)
        session.commit()


# ---------------------------------------------------------------------------
# CLI-only assisted flow (unchanged behaviour: pre-fill, human submits)
# ---------------------------------------------------------------------------

def prepare_application(job_id: int, prefs: Preferences) -> None:
    """Open the apply flow for one job and pre-fill, then wait for human submit (CLI)."""
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

    _record(job_id, ApplicationStatus.APPLIED if answer == "applied" else ApplicationStatus.PREPARED,
            "Manual apply." if answer == "applied" else "Prepared (manual).")


def _linkedin_easy_apply(page, fields: dict) -> None:
    try:
        btn = page.locator("button.jobs-apply-button:has-text('Easy Apply')")
        if btn.count():
            btn.first.click()
            page.wait_for_timeout(2000)
        if fields.get("phone"):
            phone = page.locator("input[id*='phoneNumber'], input[name*='phone']")
            if phone.count():
                phone.first.fill(fields["phone"])
    except Exception as e:
        print(f"[linkedin] pre-fill note: {e}")


def _naukri_apply(page, fields: dict) -> None:
    try:
        btn = page.locator("button:has-text('Apply'), #apply-button")
        if btn.count():
            btn.first.click()
            page.wait_for_timeout(2000)
    except Exception as e:
        print(f"[naukri] pre-fill note: {e}")


def prepare_approved(prefs: Preferences) -> int:
    """Walk through all APPROVED/TAILORED jobs up to the daily limit (CLI assisted)."""
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

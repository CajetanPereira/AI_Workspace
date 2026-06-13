"""Minimal FastAPI review dashboard.

Shows ranked jobs, lets you approve/reject, trigger tailoring, and read the
generated cover letter. Apply is still driven from the CLI (`jobapply apply`)
because it needs a visible browser + your manual submit.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import select

from .db import get_session, init_db
from .models import Application, ApplicationStatus, Job
from .tailoring import tailor_job

app = FastAPI(title="jobapply dashboard")


@app.on_event("startup")
def _startup():
    init_db()


PAGE = """
<!doctype html><html><head><meta charset="utf-8"><title>jobapply</title>
<style>
 body{{font-family:system-ui,sans-serif;margin:2rem;background:#0f1115;color:#e6e6e6}}
 h1{{font-size:1.4rem}} table{{border-collapse:collapse;width:100%}}
 th,td{{padding:.5rem .6rem;border-bottom:1px solid #2a2f3a;text-align:left;vertical-align:top}}
 .score{{font-weight:700}} .s-hi{{color:#4ade80}} .s-mid{{color:#facc15}} .s-lo{{color:#f87171}}
 a{{color:#60a5fa}} button{{cursor:pointer;background:#1f2937;color:#e6e6e6;border:1px solid #374151;border-radius:6px;padding:.3rem .6rem}}
 .badge{{font-size:.75rem;padding:.1rem .4rem;border-radius:4px;background:#1f2937}}
 form{{display:inline}}
</style></head><body>
<h1>jobapply — review ({count} jobs, score ≥ {min_score})</h1>
<table><tr><th>Score</th><th>Title</th><th>Company</th><th>Loc</th><th>Status</th><th>Why</th><th>Actions</th></tr>
{rows}
</table></body></html>
"""

ROW = """
<tr>
 <td class="score {cls}">{score}</td>
 <td><a href="{url}" target="_blank">{title}</a> <span class="badge">{platform}</span>{easy}</td>
 <td>{company}</td><td>{location}</td><td>{status}</td>
 <td style="max-width:340px">{reasons}</td>
 <td>
  <form method="post" action="/approve/{id}"><button>✓ Approve</button></form>
  <form method="post" action="/reject/{id}"><button>✕ Reject</button></form>
  <form method="post" action="/tailor/{id}"><button>✎ Tailor</button></form>
  {cover}
 </td>
</tr>
"""


def _cls(score):
    if score is None:
        return ""
    return "s-hi" if score >= 75 else "s-mid" if score >= 55 else "s-lo"


@app.get("/", response_class=HTMLResponse)
def index(min_score: int = 0):
    with get_session() as session:
        jobs = sorted(
            session.exec(select(Job)).all(),
            key=lambda j: (j.score or -1), reverse=True,
        )
        apps = {a.job_id: a for a in session.exec(select(Application)).all()}

    rows = []
    shown = 0
    for j in jobs:
        if (j.score or 0) < min_score:
            continue
        shown += 1
        app_row = apps.get(j.id)
        cover = ""
        if app_row and app_row.cover_letter_path:
            cover = f'<a href="/cover/{j.id}" target="_blank">cover letter</a>'
        rows.append(ROW.format(
            id=j.id, score=j.score if j.score is not None else "-", cls=_cls(j.score),
            url=j.url, title=j.title, platform=j.platform,
            easy=' <span class="badge">easy</span>' if j.easy_apply else "",
            company=j.company, location=j.location, status=j.status.value,
            reasons=j.score_reasons or "", cover=cover,
        ))
    return PAGE.format(count=shown, min_score=min_score, rows="\n".join(rows))


@app.post("/approve/{job_id}")
def approve(job_id: int):
    _set_status(job_id, ApplicationStatus.APPROVED)
    return RedirectResponse("/", status_code=303)


@app.post("/reject/{job_id}")
def reject(job_id: int):
    _set_status(job_id, ApplicationStatus.REJECTED)
    return RedirectResponse("/", status_code=303)


@app.post("/tailor/{job_id}")
def tailor(job_id: int):
    tailor_job(job_id)
    return RedirectResponse("/", status_code=303)


@app.get("/cover/{job_id}", response_class=HTMLResponse)
def cover(job_id: int):
    with get_session() as session:
        a = session.exec(select(Application).where(Application.job_id == job_id)).first()
    if not a or not a.cover_letter_path or not Path(a.cover_letter_path).exists():
        return HTMLResponse("<p>No cover letter yet. Click 'Tailor' first.</p>")
    text = Path(a.cover_letter_path).read_text(encoding="utf-8")
    return HTMLResponse(f"<pre style='white-space:pre-wrap;font-family:system-ui;max-width:680px;margin:2rem'>{text}</pre>")


def _set_status(job_id: int, status: ApplicationStatus):
    with get_session() as session:
        job = session.get(Job, job_id)
        if job:
            job.status = status
            session.add(job)
            session.commit()

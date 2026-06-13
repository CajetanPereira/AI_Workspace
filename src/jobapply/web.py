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
<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>jobapply</title>
<style>
 :root{{
   --green:#16a34a; --green-dark:#15803d; --green-soft:#dcfce7; --green-tint:#f0fdf4;
   --ink:#1f2937; --muted:#6b7280; --line:#eef2f1; --card:#ffffff; --bg:#f4f9f5;
 }}
 *{{box-sizing:border-box}}
 body{{font-family:'Segoe UI',system-ui,-apple-system,sans-serif;margin:0;background:var(--bg);color:var(--ink);font-size:14px}}
 .wrap{{max-width:1180px;margin:2rem auto;padding:0 1rem}}
 .card{{background:var(--card);border:1px solid var(--line);border-radius:16px;overflow:hidden;
        box-shadow:0 1px 3px rgba(16,24,40,.04),0 8px 24px rgba(16,24,40,.05)}}
 .head{{background:linear-gradient(135deg,#16a34a,#22c55e);color:#fff;padding:1.4rem 1.6rem}}
 .head h1{{margin:0;font-size:1.35rem;font-weight:700;letter-spacing:.2px}}
 .head p{{margin:.25rem 0 0;opacity:.9;font-size:.9rem}}
 .toolbar{{display:flex;gap:.5rem;padding:1rem 1.6rem;border-bottom:1px solid var(--line);background:#fafdfb}}
 .chip{{text-decoration:none;color:var(--muted);background:#fff;border:1px solid #e5e7eb;
        padding:.35rem .85rem;border-radius:999px;font-size:.82rem;font-weight:500;transition:.15s}}
 .chip:hover{{border-color:var(--green);color:var(--green-dark)}}
 .chip.active{{background:var(--green-soft);border-color:var(--green);color:var(--green-dark)}}
 table{{border-collapse:collapse;width:100%}}
 th{{text-align:left;font-size:.72rem;text-transform:uppercase;letter-spacing:.6px;color:var(--muted);
     font-weight:600;padding:.85rem 1rem;border-bottom:1px solid #e5e7eb;background:#fafdfb;position:sticky;top:0}}
 td{{padding:.95rem 1rem;border-bottom:1px solid var(--line);vertical-align:top}}
 tr:last-child td{{border-bottom:none}}
 tbody tr:hover{{background:var(--green-tint)}}
 .title{{color:#0f172a;text-decoration:none;font-weight:600}}
 .title:hover{{color:var(--green-dark);text-decoration:underline}}
 .score{{display:inline-block;min-width:2.2rem;text-align:center;font-weight:700;font-size:.82rem;
         padding:.2rem .5rem;border-radius:8px;background:#f1f5f9;color:#94a3b8}}
 .s-hi{{background:var(--green-soft);color:var(--green-dark)}}
 .s-mid{{background:#fef9c3;color:#a16207}} .s-lo{{background:#fee2e2;color:#b91c1c}}
 .badge{{display:inline-block;font-size:.68rem;font-weight:600;padding:.15rem .5rem;border-radius:999px;
         margin-left:.3rem;text-transform:capitalize}}
 .b-linkedin{{background:#e0f2fe;color:#0369a1}} .b-naukri{{background:#ede9fe;color:#6d28d9}}
 .b-easy{{background:var(--green-soft);color:var(--green-dark)}}
 .pill{{display:inline-block;font-size:.72rem;font-weight:600;padding:.2rem .55rem;border-radius:999px;
        background:#f1f5f9;color:#475569;text-transform:capitalize}}
 .st-approved{{background:var(--green-soft);color:var(--green-dark)}}
 .st-rejected{{background:#fee2e2;color:#b91c1c}}
 .st-tailored,.st-prepared{{background:#e0f2fe;color:#0369a1}}
 .st-applied{{background:#dcfce7;color:#166534}}
 .why{{max-width:320px;color:var(--muted);font-size:.83rem;line-height:1.4}}
 .actions{{white-space:nowrap}}
 .actions form{{display:inline}}
 button{{cursor:pointer;font-size:.78rem;font-weight:600;border-radius:8px;padding:.4rem .7rem;
         margin-right:.3rem;border:1px solid transparent;transition:.15s}}
 .btn-approve{{background:var(--green);color:#fff}} .btn-approve:hover{{background:var(--green-dark)}}
 .btn-reject{{background:#fff;color:#dc2626;border-color:#fecaca}} .btn-reject:hover{{background:#fef2f2}}
 .btn-tailor{{background:#fff;color:var(--green-dark);border-color:#bbf7d0}} .btn-tailor:hover{{background:var(--green-tint)}}
 .cover{{display:inline-block;margin-top:.4rem;font-size:.78rem;color:var(--green-dark);text-decoration:none}}
 .cover:hover{{text-decoration:underline}}
 .empty{{padding:3rem;text-align:center;color:var(--muted)}}
</style></head><body>
<div class="wrap"><div class="card">
 <div class="head">
   <h1>🌿 jobapply</h1>
   <p>{count} jobs &middot; reviewing matches with score ≥ {min_score}</p>
 </div>
 <div class="toolbar">
   <a class="chip {f_all}" href="/?min_score=0">All</a>
   <a class="chip {f_60}" href="/?min_score=60">Good fit (≥60)</a>
   <a class="chip {f_75}" href="/?min_score=75">Strong (≥75)</a>
 </div>
 <table>
  <thead><tr><th>Score</th><th>Title</th><th>Company</th><th>Location</th><th>Status</th><th>Why</th><th>Actions</th></tr></thead>
  <tbody>
{rows}
  </tbody>
 </table>
</div></div>
</body></html>
"""

ROW = """
<tr>
 <td><span class="score {cls}">{score}</span></td>
 <td><a class="title" href="{url}" target="_blank">{title}</a>{badges}</td>
 <td>{company}</td><td>{location}</td>
 <td><span class="pill st-{status}">{status}</span></td>
 <td class="why">{reasons}</td>
 <td class="actions">
  <form method="post" action="/approve/{id}"><button class="btn-approve">✓ Approve</button></form>
  <form method="post" action="/reject/{id}"><button class="btn-reject">✕ Reject</button></form>
  <form method="post" action="/tailor/{id}"><button class="btn-tailor">✎ Tailor</button></form>
  {cover}
 </td>
</tr>
"""

EMPTY_ROW = '<tr><td colspan="7" class="empty">No jobs at this score yet. Run <code>jobapply rank</code> after adding your API key.</td></tr>'


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
            cover = f'<a class="cover" href="/cover/{j.id}" target="_blank">📄 cover letter</a>'
        badges = f'<span class="badge b-{j.platform}">{j.platform}</span>'
        if j.easy_apply:
            badges += '<span class="badge b-easy">easy</span>'
        rows.append(ROW.format(
            id=j.id, score=j.score if j.score is not None else "—", cls=_cls(j.score),
            url=j.url, title=j.title or "(untitled)", badges=badges,
            company=j.company, location=j.location, status=j.status.value,
            reasons=j.score_reasons or "", cover=cover,
        ))

    body = "\n".join(rows) if rows else EMPTY_ROW
    return PAGE.format(
        count=shown, min_score=min_score, rows=body,
        f_all="active" if min_score == 0 else "",
        f_60="active" if min_score == 60 else "",
        f_75="active" if min_score == 75 else "",
    )


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

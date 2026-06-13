"""jobapply command-line interface."""
from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .apply import prepare_approved, prepare_application
from .config import load_preferences
from .db import get_session, init_db
from .models import ApplicationStatus, Job
from .profile import build_profile, build_profile_from_linkedin, get_profile
from .ranking import rank_new_jobs
from .session import interactive_login, is_logged_in
from .tailoring import tailor_job

app = typer.Typer(help="Semi-automated job search & assisted-apply tool.", no_args_is_help=True)
console = Console()


@app.command()
def init():
    """Create the database and runtime folders."""
    init_db()
    console.print("[green]Database initialized.[/green]")


@app.command()
def login(platform: str = typer.Argument(..., help="linkedin | naukri")):
    """Open a browser to log in manually (session is saved for reuse)."""
    ok = interactive_login(platform)
    console.print("[green]Saved.[/green]" if ok else "[red]Login not detected.[/red]")


@app.command(name="check-login")
def check_login(platform: str):
    """Check whether a saved session is still valid."""
    console.print(f"{platform}: {'[green]logged in[/green]' if is_logged_in(platform) else '[red]not logged in[/red]'}")


@app.command(name="parse-resume")
def parse_resume(path: Path = typer.Argument(..., help="Path to your resume (.pdf/.docx/.txt)")):
    """Parse your resume into a structured profile (uses Claude)."""
    init_db()
    profile = build_profile(path)
    console.print(f"[green]Profile saved[/green] for {profile.name or '(name not found)'} <{profile.email}>")


@app.command(name="profile-linkedin")
def profile_linkedin():
    """Build your profile by scraping your own LinkedIn profile (needs `login linkedin`)."""
    init_db()
    profile = build_profile_from_linkedin()
    console.print(f"[green]Profile saved[/green] for {profile.name or '(name not found)'} <{profile.email}>")


@app.command()
def search():
    """Search configured platforms and store new jobs."""
    init_db()
    prefs = load_preferences()
    from .scrapers import SCRAPERS
    from .scrapers.base import save_jobs

    total_new = 0
    for name, cfg in prefs.platforms.items():
        if not cfg.enabled or name not in SCRAPERS:
            continue
        console.print(f"[cyan]Searching {name}...[/cyan]")
        scraper = SCRAPERS[name](prefs)
        scraped = scraper.search()
        new = save_jobs(scraped)
        total_new += new
        console.print(f"  {name}: {len(scraped)} found, {new} new")
    console.print(f"[green]Done. {total_new} new jobs stored.[/green]")


@app.command()
def rank(limit: int = typer.Option(None, help="Max jobs to score this run")):
    """Score newly-scraped jobs against your profile (uses Claude)."""
    prefs = load_preferences()
    n = rank_new_jobs(prefs, limit=limit)
    console.print(f"[green]Ranked {n} jobs.[/green]")


@app.command(name="list")
def list_jobs(
    status: str = typer.Option(None, help="Filter by status"),
    min_score: int = typer.Option(0, help="Minimum score"),
):
    """Show stored jobs in a table."""
    from sqlmodel import select

    with get_session() as session:
        q = select(Job)
        if status:
            q = q.where(Job.status == status)
        jobs = sorted(session.exec(q).all(), key=lambda j: (j.score or -1), reverse=True)

    table = Table(title="Jobs")
    for col in ("ID", "Score", "Status", "Title", "Company", "Platform", "Easy"):
        table.add_column(col)
    for j in jobs:
        if (j.score or 0) < min_score:
            continue
        table.add_row(
            str(j.id), str(j.score if j.score is not None else "-"), j.status.value,
            j.title[:40], j.company[:25], j.platform, "Y" if j.easy_apply else "",
        )
    console.print(table)


@app.command()
def approve(job_ids: list[int] = typer.Argument(..., help="Job IDs to approve")):
    """Mark jobs as approved for application."""
    with get_session() as session:
        for jid in job_ids:
            job = session.get(Job, jid)
            if job:
                job.status = ApplicationStatus.APPROVED
                session.add(job)
        session.commit()
    console.print(f"[green]Approved {len(job_ids)} job(s).[/green]")


@app.command()
def tailor(job_id: int):
    """Generate tailored resume highlights + cover letter for a job."""
    app_row = tailor_job(job_id)
    console.print(f"[green]Wrote[/green] {app_row.tailored_resume_path}")
    console.print(f"[green]Wrote[/green] {app_row.cover_letter_path}")


@app.command(name="apply")
def apply_cmd(
    job_id: int = typer.Option(None, help="Apply to one job; omit to walk all approved"),
):
    """Open the apply flow (pre-filled) and wait for you to submit."""
    prefs = load_preferences()
    if job_id:
        prepare_application(job_id, prefs)
    else:
        n = prepare_approved(prefs)
        console.print(f"[green]Walked through {n} application(s).[/green]")


@app.command()
def dashboard(port: int = 8000):
    """Launch the web review dashboard."""
    import uvicorn

    uvicorn.run("jobapply.web:app", host="127.0.0.1", port=port, reload=False)


def main():
    app()


if __name__ == "__main__":
    main()

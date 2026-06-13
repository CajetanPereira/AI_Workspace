# jobapply

A **semi-automated** job search & assisted-apply tool for LinkedIn and Naukri.

It automates the tedious 90%: finding relevant postings, ranking them against your
resume, and drafting tailored highlights + cover letters. **You** stay in the loop for
the final click — which keeps your accounts safe and your applications high-quality.

## Why semi-automated (please read)

LinkedIn and Naukri's terms of service **prohibit bots and scraping**, and both have
strong bot detection. Fully unattended "apply to everything" tools routinely get
accounts **permanently banned** and spray low-quality applications. This tool is
deliberately designed so that:

- It uses **your own logged-in browser session** (you log in manually once; we never
  store your password).
- It **pre-fills** applications but **pauses for you to review and submit**.
- It paces requests like a human and caps applications per day.

Use it on your own accounts, at sane volumes. You are responsible for compliance with
each platform's terms.

## Architecture

```
Resume (PDF/docx) ─┐
preferences.yaml  ─┴─► Profile ─► Search ─► Rank (Claude) ─► Tailor ─► Review ─► Assisted apply
                       (profile.py) (scrapers/) (ranking.py) (tailoring.py) (web.py) (apply.py)
```

Data lives in a local SQLite DB (`data/jobs.db`). Browser sessions persist in
`browser_profiles/` (gitignored — they contain your cookies).

## Setup

```powershell
# 1. Install deps (already done if you scaffolded via the assistant)
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium

# 2. Configure
copy .env.example .env                              # add your ANTHROPIC_API_KEY
copy config\preferences.example.yaml config\preferences.yaml   # edit titles/filters

# 3. Initialize DB
.\.venv\Scripts\python.exe -m jobapply.cli init
```

## Usage

```powershell
# convenience: $py = ".\.venv\Scripts\python.exe"; then `& $py -m jobapply.cli <cmd>`

# Log in once per platform (a browser opens; sign in manually)
& $py -m jobapply.cli login linkedin
& $py -m jobapply.cli login naukri

# Build your profile — EITHER from a resume file...
& $py -m jobapply.cli parse-resume "C:\path\to\resume.pdf"
# ...OR by scraping your own LinkedIn profile (no upload needed)
& $py -m jobapply.cli profile-linkedin

# Search -> rank -> review
# Search. To use LinkedIn's profile-matched "Top job picks" feed instead of
# keyword search, set platforms.linkedin.use_recommended: true in preferences.yaml
& $py -m jobapply.cli search
& $py -m jobapply.cli rank
& $py -m jobapply.cli dashboard          # open http://127.0.0.1:8000

# After approving jobs in the dashboard:
& $py -m jobapply.cli tailor 12          # generate highlights + cover letter for job 12
& $py -m jobapply.cli apply --job-id 12  # opens pre-filled apply flow; you submit
& $py -m jobapply.cli apply              # walk through all approved jobs
```

## Important caveat: scraper selectors

LinkedIn and Naukri change their HTML constantly and vary by region/A-B test. The
CSS selectors in `src/jobapply/scrapers/` are a **starting point** and will likely
need adjustment for your account. Run with the browser visible and use Playwright's
inspector to fix them:

```powershell
$env:PWDEBUG=1; & $py -m jobapply.cli search
```

## Roadmap / ideas
- ToS-friendly job APIs (Adzuna, JSearch) as additional sources
- Embedding-based pre-filter before the LLM ranker (cheaper)
- Per-job Q&A auto-fill for LinkedIn Easy Apply screening questions
- Application tracking / follow-up reminders
```

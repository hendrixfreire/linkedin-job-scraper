# Application Agent

Local, auditable job-application pipeline built to consume a job feed, prioritize opportunities, prepare application assets, and fill supported ATS forms safely.

It starts conservative: browser automation and automatic submission are disabled in the example configuration. The intended first step is **dry run** — fill and validate without submitting.

## What it does

- imports job listings from a JSON feed into SQLite;
- scores jobs with an explainable policy and recorded feedback;
- resolves external application URLs and recognizes supported ATS platforms;
- prepares a queue for per-job resume assets;
- fills known form fields with Playwright while detecting blocking questions;
- keeps an audit trail of jobs, decisions, applications, notifications, and feedback;
- serves a local dashboard and generates daily reports.

## Safety model

The project does **not** type passwords, bypass CAPTCHA/2FA, invent legal/demographic/salary answers, or submit when a required blocker remains. A human must configure their own profile locally.

`auto_submit` defaults to `false`. Even if enabled, submission is limited to explicit `allowed_ats` and only happens when the form has no blockers. Treat the mode change as a production deployment, not a checkbox with ambition issues.

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- Playwright Chromium (`scripts/setup.sh` installs it)
- A local JSON job feed compatible with the LinkedIn job scraper output

## Quick start

```bash
cd application-agent
./scripts/setup.sh
cp config.example.json config.json
mkdir -p data
cp data/profile.example.json data/profile.json
```

Edit **only your local, ignored files**:

- `config.json`: job-feed path, ATS allowlists, notification destination, dashboard port;
- `data/profile.json`: your identity, resume location, target roles, locations, and skill preferences.

Then run the first ingestion with browser automation disabled:

```bash
.venv/bin/python -m candidatura_agent.hourly
.venv/bin/python -m candidatura_agent.dashboard
```

Open `http://127.0.0.1:8765` in a browser. Run the automated test suite at any time:

```bash
.venv/bin/python -m pytest -q
```

## Configuration

Copy `config.example.json` to `config.json`; the real file is git-ignored.

| Field | Purpose | Safe default |
|---|---|---|
| `source_json` | Path to the job feed JSON | `../jobs_new.json` |
| `database` | Local SQLite database | `data/applications.db` |
| `profile` | Your local profile file | `data/profile.json` |
| `browser_enabled` | Enables Playwright form interaction | `false` |
| `headless` | Runs browser without a visible window | `true` |
| `auto_submit` | Allows confirmed form submission | `false` |
| `allowed_ats` | ATS domains allowed in auto-submit mode | `[]` |
| `dry_run_allowed_ats` | ATS domains allowed for fill-without-submit | supported platforms |
| `notification_target` | Hermes destination for confirmed submissions | `CHANGE_ME` |
| `dashboard_port` | Local dashboard port | `8765` |

## Profile format

Use `data/profile.example.json` as the schema. The real profile is never committed. Store the resume as a path on your own machine; do not place the PDF in this repository.

## Workflow

```text
Job feed JSON
    |
    v
SQLite ingestion -> explainable scoring -> qualified queue
    |                                      |
    |                                      v
    |                           resolve official apply URL
    |                                      |
    v                                      v
local dashboard <--- audit events <--- dry run / approved submission
```

## Commands

```bash
./scripts/run_hourly.sh       # ingest, score, and optionally run browser flow
./scripts/run_dashboard.sh    # start the local dashboard
./scripts/run_report.sh       # print and save a daily report
./scripts/status.sh           # local health and Git status
.venv/bin/python -m candidatura_agent.asset_cli queue --limit 1
```

## Supported ATS modes

The adapter identifies Greenhouse, Lever, Ashby, Gupy, PeopleForce, and Factorial URLs. Actual automated submission remains intentionally gated by `allowed_ats`, form validation, and your explicit configuration.

## Privacy and repository hygiene

Never commit:

- `config.json` or `data/profile.json`;
- resumes, PDFs, screenshots, reports, browser profiles, cookies, or SQLite databases;
- notification IDs, access tokens, passwords, or exported browser sessions.

The included `.gitignore` blocks these runtime artifacts. Before pushing changes, run the test suite and inspect `git status`.

## Limitations

- Application sites change their markup frequently; form support is best-effort and must be tested per ATS.
- Login, CAPTCHA, 2FA, legal acknowledgements, and sensitive questions are human gates.
- A dry run is not a submitted application.
- This repository contains code and generic examples, not a candidate profile or real application records.

## License

MIT — see the repository root [`LICENSE`](../LICENSE).

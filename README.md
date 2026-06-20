# LinkedIn Job Scraper

A Python scraper for [LinkedIn's public Guest API](https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search) that finds job postings, deduplicates them across runs, and prepares a JSON file for an LLM agent to classify and report.

Built to run on cron with zero infrastructure — no database, no auth, no LinkedIn login. Just plain files on disk.

## Features

- **No authentication** — uses LinkedIn's public Guest API (HTML scraping)
- **Triple deduplication**:
  1. Persistent job IDs (`seen.json`)
  2. Title + Company normalized keys (catches reposted jobs with new IDs)
  3. Reads agent's previous outputs and skips already-reported jobs
- **Heuristic scoring** — pre-computes a 1-5 star score per job so the LLM only re-evaluates borderline cases (~80% token savings)
- **Keyword yield tracking** — auto-prunes keywords that produce nothing after 15+ runs
- **Rate-limited parallel fetches** — 3 threads, 300ms between pages, 4-minute deadline
- **Filter by location and seniority** — only Brazil/São Paulo, drops junior/intern
- **Metrics dashboard** — see yield per keyword, recent runs, database size

## Requirements

- Python 3.8+
- No external dependencies (stdlib only)

## Installation

```bash
# Clone
git clone https://github.com/hendrixfreire/linkedin-job-scraper.git
cd linkedin-job-scraper

# Make scripts executable (optional)
chmod +x linkedin_jobs.py linkedin_metrics.py
```

That's it. No `pip install`, no virtualenv, no API keys.

## Quick Start

```bash
# Run once — creates ~/linkedin-jobs/ with all output files
python3 linkedin_jobs.py

# See what was collected
cat ~/linkedin-jobs/jobs_new.json

# Check the human-readable history
head ~/linkedin-jobs/jobs.md

# View metrics
python3 linkedin_metrics.py
```

## Configuration

All user-specific settings are configured via environment variables. No config file to edit.

| Variable | Default | Description |
|----------|---------|-------------|
| `LINKEDIN_OUTPUT_DIR` | `~/linkedin-jobs` | Where to save output files (jobs.md, jobs_new.json, seen.json, keywords.json) |
| `LINKEDIN_USER_NAME` | `User` | Name to use in the jobs.md header |
| `LINKEDIN_CRON_OUTPUT_DIR` | _(disabled)_ | Directory containing the agent's `.md` response files. When set, the scraper reads the last 3 files and excludes jobs already reported to the user. Requires the agent to write responses as `.md` files in this directory. |

### Example: custom output directory

```bash
export LINKEDIN_OUTPUT_DIR=~/my-job-search
python3 linkedin_jobs.py
```

### Example: enable cross-run dedup with an agent

If you have an LLM agent (e.g. [Hermes Agent](https://hermes-agent.nousresearch.com), Claude, ChatGPT) classifying jobs and writing responses to a directory:

```bash
export LINKEDIN_CRON_OUTPUT_DIR=~/.my-agent/outputs
python3 linkedin_jobs.py
```

The scraper will read the last 3 `.md` files in that directory, extract job titles and companies from the response format `**N. ⭐⭐⭐ Job Title**`, and skip those jobs on the next run.

### Customizing keywords

Edit the `KEYWORDS` list at the top of `linkedin_jobs.py`:

```python
KEYWORDS = [
    "data engineer",
    "analytics engineer",
    "data analyst",
    # ...add your own
]
```

Each keyword generates 2 queries: Remote Brazil + São Paulo (no work-type filter). Manager/Head roles skip the seniority filter (they're senior by definition).

### Customizing filters

Edit the `build_searches()` function to change:
- **Location**: replace `"Brazil"` and `"São Paulo, Brazil"` with your target locations
- **Seniority**: `f_E=4` means Mid-Senior. See [LinkedIn API filters](#linkedin-api-filters) below
- **Posting time**: `f_TPR=r2592000` means last 30 days. Use `r604800` for 7 days, `r86400` for 24h

### Customizing the heuristic score

The `heuristic_score()` function in `linkedin_jobs.py` scores each job 1-5 stars based on:
- **Tech stack** (0-2 points): high-relevance keywords (data engineer, AI engineer) vs. mid-relevance (data analyst, BI, SQL)
- **Seniority** (0-2 points): senior/lead/manager keywords, or assumed mid/senior if no indicator
- **Location** (0-1 point): remote, Brazil, or São Paulo

Edit the `high_skills` and `mid_skills` lists to match your profile.

## Output Files

All files are created in `LINKEDIN_OUTPUT_DIR` (default: `~/linkedin-jobs/`):

| File | Description |
|------|-------------|
| `jobs_new.json` | New jobs for the agent to classify. Includes `heuristic_score` and `heuristic_reason` per job. Empty array `[]` when no new jobs. |
| `jobs.md` | Human-readable job history. Append-only — never removes entries. Each job is a markdown block with title, company, location, mode, link, and short description. |
| `seen.json` | Dedup state. Contains `seen_ids` (LinkedIn numeric IDs) and `seen_keys` (normalized `title\|\|company` strings). |
| `keywords.json` | Per-keyword yield tracking. Each keyword has `total_runs`, `total_new`, `last_new`, `last_run`. Also tracks pruned keywords. |

### jobs_new.json format

```json
[
  {
    "id": "4429960220",
    "title": "Senior AI Engineer",
    "company": "Emma of Torre.ai",
    "location": "Brazil",
    "work_mode": "Remote",
    "date_label": "1 hour ago",
    "url": "https://www.linkedin.com/jobs/view/4429960220",
    "description": "Responsibilities and more: We are hiring...",
    "heuristic_score": 5,
    "heuristic_reason": "high stack, senior+, remote/BR"
  }
]
```

## Usage with an LLM Agent

The scraper is designed to feed an LLM agent that classifies jobs and reports to the user. Example agent prompt:

```text
You are a job classifier. 

1. Run: python3 linkedin_jobs.py
2. Read: ~/linkedin-jobs/jobs_new.json
3. If empty, respond "No new jobs." and stop.
4. For each job, use the heuristic_score as a starting point.
   Re-evaluate only if heuristic_reason seems wrong.
5. Filter to 3+ stars only.
6. Sort by posting date (newest first).
7. Report in this format:

   🔍 **N new jobs** — date

   **1. ⭐⭐⭐⭐⭐ 🔥 Job Title**
   Company | Location | Mode
   📅 Posted today | Match: short justification
   [View job](url)
```

Save the agent's response as a `.md` file in `LINKEDIN_CRON_OUTPUT_DIR` so the next scraper run can skip already-reported jobs.

### Cron example

```bash
# Run 3x daily: 8am, 1pm, 6pm
0 8,13,18 * * * LINKEDIN_OUTPUT_DIR=~/linkedin-jobs LINKEDIN_CRON_OUTPUT_DIR=~/.agent/outputs python3 ~/linkedin-job-scraper/linkedin_jobs.py
```

## Metrics Dashboard

```bash
python3 linkedin_metrics.py
```

Example output:

```
============================================================
  LinkedIn Job Scraper — Metrics Dashboard
  20/06/2026 15:00
============================================================

## Database
  Tracked IDs: 313
  Title+Company keys: 283
  Last update: 2026-06-20T15:01

## Yield per Keyword
  Keyword                         Runs  Yield     Last New
  ------------------------------ ----- ------ ------------
  data engineer                      5    12 (2.4/run) 2026-06-20
  AI engineer                        5     8 (1.6/run) 2026-06-20
  BI manager                         5     0 (0 total) never

## Recent Runs
        Date  Jobs First job title
  ------------ ------ ----------------------------------------
  2026-06-20 15-00      8 Senior Data Engineer
  2026-06-20 13-00      5 Data Tech Lead
  Total runs: 15

## MD File
  Jobs in MD: 313 (unique IDs: 313)
  Size: 97KB, 3630 lines

============================================================
```

## LinkedIn API Filters

Reference for customizing `build_searches()`:

| Filter | Values | Description |
|--------|--------|-------------|
| `f_TPR` | `r86400`, `r604800`, `r2592000` | Posting time: 24h, 7 days, 30 days |
| `f_E` | `1`-`6` | Experience: 1=Intern, 2=Entry, 3=Associate, 4=Mid-Senior, 5=Director, 6=Executive |
| `f_WT` | `1`, `2`, `3` | Work type: 1=On-site, 2=Remote, 3=Hybrid |
| `sortBy` | `DD`, `R` | Sort by date descending, relevance |
| `start` | `0`, `25`, `50`, ... | Pagination offset (25 per page) |

## Limitations

- **Guest API only** — no authenticated endpoints, no application status, no saved jobs
- **Rate limited** — LinkedIn may block if you hit the API too hard. The scraper uses 300ms between pages and 2s backoff on retries
- **HTML parsing** — if LinkedIn changes their HTML structure, the regex parsers will break. Open an issue if this happens
- **Max 8 jobs per run** — to stay within the 4-minute deadline and avoid API throttling. Adjust `MAX_DETAIL` in `main()` if you need more
- **Brazil-focused** — default filters target Brazil/São Paulo. Edit `build_searches()` for other regions

## How It Works

```
┌─────────────────────────────────────────────────────────────┐
│                     SCRAPER (this repo)                      │
│                                                              │
│  1. Load seen.json (IDs + keys)                             │
│  2. Read last 3 agent outputs (skip reported jobs)          │
│  3. Prune unproductive keywords                             │
│  4. Search LinkedIn Guest API (2 pages × N queries)         │
│  5. Triple dedup: ID + title/company + reported             │
│  6. Filter: Brazil/SP only, no junior                       │
│  7. Fetch details in parallel (3 threads, max 8 jobs)       │
│  8. Save: seen.json + keywords.json + jobs_new.json + jobs.md│
│                                                              │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼ jobs_new.json
┌─────────────────────────────────────────────────────────────┐
│                    LLM AGENT (separate)                      │
│                                                              │
│  1. Read jobs_new.json                                      │
│  2. Use heuristic_score as starting point                   │
│  3. Re-evaluate borderline cases (2-4 stars)                │
│  4. Filter to 3+ stars                                      │
│  5. Sort by date                                            │
│  6. Report to user (Telegram, email, etc.)                  │
│  7. Save response as .md in LINKEDIN_CRON_OUTPUT_DIR        │
│                                                              │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼ next scraper run reads this
                      (back to top)
```

## Troubleshooting

**"No new jobs" every run**
- Check `seen.json` — it may have grown too large. The scraper excludes any ID ever seen. To reset: delete `seen.json` and `jobs.md`.
- Check `keywords.json` — keywords may have been pruned. Reset: delete `keywords.json`.

**API returns empty results**
- LinkedIn may be rate-limiting you. Wait 10-15 minutes.
- The Guest API may be down. Try the URL directly in a browser: `https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords=data+engineer&location=Brazil&start=0`
- Your IP may be blocked. Try a VPN or different network.

**Duplicate jobs appearing**
- Make sure `LINKEDIN_CRON_OUTPUT_DIR` is set if you're using an agent. Without it, the scraper can't know what was already reported.
- Check that the agent's response format matches `**N. ⭐⭐⭐ Job Title**` (the regex expects stars).

## Contributing

1. Fork it
2. Create your feature branch (`git checkout -b feature/foo`)
3. Commit your changes (`git commit -am 'Add foo'`)
4. Push to the branch (`git push origin feature/foo`)
5. Create a Pull Request

## License

MIT — see [LICENSE](LICENSE).

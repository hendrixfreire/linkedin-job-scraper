#!/usr/bin/env python3
"""
LinkedIn Jobs Guest API scraper.

Uses LinkedIn's public (no-auth) Guest API to scrape job postings and apply
multi-layer deduplication. Designed to run on cron and feed an LLM agent
that classifies and reports new jobs to the user.

DEDUP ARCHITECTURE (3 layers):
  1. seen.json → persistent IDs + keys (title||company) — never repeats a job
  2. Cron output files → reads last N agent responses and excludes jobs
     already reported (requires LINKEDIN_CRON_OUTPUT_DIR env var)
  3. MD legacy → fallback IDs extracted from the jobs MD file

PIPELINE:
  Script (search → dedup → filter → fetch details) → JSON (new jobs with
  heuristic_score) → LLM agent (reads JSON + CV → classifies → reports)
  → Next script run reads previous agent outputs and skips reported jobs

OUTPUTS:
  - stdout: summary for the agent
  - jobs_new.json: new jobs for the agent to classify
  - jobs.md: human-readable history (append-only)
  - seen.json: dedup state
  - keywords.json: yield tracking per keyword

CONFIGURATION:
  All user-specific paths are configurable via environment variables:
  - LINKEDIN_OUTPUT_DIR: where to save output files (default: ~/linkedin-jobs)
  - LINKEDIN_CRON_OUTPUT_DIR: optional, dir with agent's .md outputs
    (enables cross-run dedup of reported jobs)
  - LINKEDIN_USER_NAME: name to use in MD header (default: "User")
"""
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlencode

# ═══════════════════════════════════════════════════════════════
# CONFIGURATION (override via environment variables)
# ═══════════════════════════════════════════════════════════════
BASE_DIR = Path(os.environ.get("LINKEDIN_OUTPUT_DIR", Path.home() / "linkedin-jobs"))
USER_NAME = os.environ.get("LINKEDIN_USER_NAME", "User")

VAGAS_FILE = BASE_DIR / "jobs.md"
JOBS_JSON = BASE_DIR / "jobs_new.json"
SEEN_JSON = BASE_DIR / "seen.json"
KEYWORDS_FILE = BASE_DIR / "keywords.json"

# Optional: directory with agent's markdown responses (cron output)
# Enables dedup of jobs already reported to the user across runs
CRON_OUTPUT_DIR = Path(os.environ["LINKEDIN_CRON_OUTPUT_DIR"]) if os.environ.get("LINKEDIN_CRON_OUTPUT_DIR") else None

BASE_SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
BASE_JOB_URL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{}"

# ---- API FILTERS ----
# f_TPR: posting time (r86400=24h, r604800=week, r2592000=month)
# f_E: experience level (1=Intern, 2=Entry, 3=Associate, 4=Mid-Senior,
#       5=Director, 6=Executive)
# f_WT: work type (1=On-site, 2=Remote, 3=Hybrid)
# sortBy=DD: sort by date descending (newest first)

# ---- KEYWORDS ----
# Customize these for your profile. Each generates 2 queries:
# Remote Brazil + São Paulo (no work-type filter)
KEYWORDS = [
    "data engineer",
    "analytics engineer",
    "data analyst",
    "data analytics manager",
    "BI manager",
    "head de dados",
    "AI engineer",
    "machine learning engineer",
]

SEARCHES = []


def build_searches(keywords):
    """Build search queries from the list of active keywords.

    Each keyword generates 2 queries: Remote Brazil + São Paulo (no
    work-type filter, so it returns remote+hybrid+on-site and we filter
    locally). Manager/Head roles skip the f_E=4 filter (already senior).
    """
    searches = []
    # Remote in Brazil — with seniority filter (f_E=4 for technical roles)
    for kw in keywords:
        search = {"keywords": kw, "location": "Brazil", "f_WT": "2",
                  "f_E": "4", "f_TPR": "r2592000", "sortBy": "DD"}
        if any(m in kw.lower() for m in ["manager", "head"]):
            del search["f_E"]  # manager/head are senior by definition
        searches.append(search)

    # São Paulo without work-type filter — returns remote+hybrid+on-site.
    # We filter on-site outside SP during detail fetch (fetch_one).
    for kw in keywords:
        search = {"keywords": kw, "location": "São Paulo, Brazil",
                  "f_TPR": "r2592000", "sortBy": "DD"}
        if not any(m in kw.lower() for m in ["manager", "head"]):
            search["f_E"] = "4"
        searches.append(search)

    return searches


# Initialize with all keywords (pruning can reduce this on later runs)
SEARCHES = build_searches(KEYWORDS)

# ---- HTTP HEADERS ----
# Chrome macOS User-Agent to avoid being blocked as a bot
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/126.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


def fetch_url(url, retries=1):
    """HTTP request with retry and rate limiting.

    Tries up to retries+1 times. On failure:
    - Waits 2s and retries (if attempts remain)
    - On last attempt, logs error and returns empty string

    8s timeout per request — LinkedIn API can be slow.
    """
    for attempt in range(retries + 1):
        try:
            req = Request(url, headers=HEADERS)
            with urlopen(req, timeout=8) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except Exception as e:
            if attempt < retries:
                time.sleep(2)  # fixed 2s backoff between attempts
            else:
                print(f"Error fetching {url}: {e}", file=sys.stderr)
                return ""


def parse_search_results(html):
    """Extract jobs from search HTML via regex.

    The Guest API HTML has a known structure:
    <li data-entity-urn="urn:li:jobPosting:123456"> ... </li>

    Each card contains: title (base-search-card__title), company
    (hidden-nested-link or base-search-card__subtitle), location
    (job-search-card__location), date (<time datetime="...">).

    Returns list of dicts with id, url, title, company, location,
    date (ISO), date_label (relative text like '1 week ago').
    """
    jobs = []
    seen_ids = set()  # intra-page dedup (API sometimes duplicates cards)

    # Each <li> with data-entity-urn is a job card
    card_pattern = re.compile(
        r'data-entity-urn="urn:li:jobPosting:(\d+)"(.*?)</li>',
        re.DOTALL
    )

    for match in card_pattern.finditer(html):
        job_id = match.group(1)        # numeric job ID
        card_html = match.group(2)     # inner HTML of the card

        if job_id in seen_ids:
            continue
        seen_ids.add(job_id)

        # Title: inside h3 with class base-search-card__title
        title_match = re.search(
            r'base-search-card__title[^>]*>\s*(.*?)\s*</h3>',
            card_html, re.DOTALL
        )
        title = title_match.group(1).strip() if title_match else ""
        title = re.sub(r'<[^>]+>', '', title).strip()  # strip inner HTML tags

        # Company: try hidden-nested-link first (most common)
        # fallback: base-search-card__subtitle
        company_match = re.search(
            r'hidden-nested-link[^>]*>\s*(.*?)\s*</a>',
            card_html, re.DOTALL
        )
        if not company_match:
            company_match = re.search(
                r'base-search-card__subtitle[^>]*>(.*?)</h4>',
                card_html, re.DOTALL
            )
        company = company_match.group(1).strip() if company_match else ""
        company = re.sub(r'<[^>]+>', '', company).strip()

        # Location: span with class job-search-card__location
        location_match = re.search(
            r'job-search-card__location[^>]*>\s*(.*?)\s*</span>',
            card_html, re.DOTALL
        )
        location = location_match.group(1).strip() if location_match else ""

        # Date: <time> tag with datetime attribute (ISO) and relative text
        date_match = re.search(
            r'<time[^>]*datetime="([^"]*)"[^>]*>(.*?)</time>',
            card_html, re.DOTALL
        )
        date_iso = date_match.group(1).strip() if date_match else ""
        date_label = re.sub(r'<[^>]+>', '', date_match.group(2)).strip() if date_match else ""

        jobs.append({
            "id": job_id,
            "url": f"https://www.linkedin.com/jobs/view/{job_id}",
            "title": title,
            "company": company,
            "location": location,
            "date": date_iso,
            "date_label": date_label,
        })

    return jobs


def search_jobs(params, max_pages=1, deadline=None):
    """Search jobs via Guest API with optional pagination.

    Each page returns up to 25 jobs. The 'start' parameter controls
    the offset (0, 25, 50, ...). If a page returns no new results
    (new_count == 0), pagination stops.

    Respects the global deadline — if time runs out, stops immediately.
    0.3s sleep between pages to avoid overwhelming the API.
    """
    all_jobs = []
    seen_ids = set()  # cross-page dedup

    for page in range(max_pages):
        if deadline and time.time() > deadline:
            print(f"Deadline reached — stopping search: {params.get('keywords','')}", file=sys.stderr)
            break
        start = page * 25
        p = {**params, "start": start}  # shallow copy + start offset
        url = f"{BASE_SEARCH_URL}?{urlencode(p)}"
        html = fetch_url(url)
        if not html:
            break

        jobs = parse_search_results(html)
        new_count = 0
        for job in jobs:
            if job["id"] not in seen_ids:
                seen_ids.add(job["id"])
                all_jobs.append(job)
                new_count += 1

        if new_count == 0:  # page with no new results → end pagination
            break
        time.sleep(0.3)     # rate limiting: 300ms between pages

    return all_jobs


def get_job_details(job_id):
    """Extract details from a specific job via the detail API.

    Fetches the individual job page (jobs-guest/jobs/api/jobPosting/{id}),
    cleans the HTML and extracts:
    - work_mode: Remote/Hybrid/On-site (case-insensitive regex)
    - description: first 500 chars after known markers
    - closed: True if the job is no longer accepting applications

    Returns empty dict if the API fails.
    """
    url = BASE_JOB_URL.format(job_id)
    html = fetch_url(url)
    if not html:
        return {}

    # Clean HTML: replace tags with spaces and collapse whitespace
    text = re.sub(r'<[^>]+>', ' ', html)
    text = re.sub(r'\s+', ' ', text).strip()

    details = {}

    # Extract work mode — look for keywords in cleaned text
    for pattern in [r'(Remote|Remoto|Hybrid|Híbrido|On-site|Presencial)']:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            details["work_mode"] = match.group(1)
            break

    # Extract description — locate the marker and grab up to 500 chars
    # Common markers from LinkedIn's detail API
    for marker in ["Job description", "Descrição da vaga", "About the job", "Responsibilities"]:
        idx = text.lower().find(marker.lower())
        if idx > 0:
            desc = text[idx:idx+800]
            details["description"] = desc.strip()[:500]
            break

    # Check if the job has been closed/discontinued
    if "no longer accepting applications" in text.lower() or "não aceita mais" in text.lower():
        details["closed"] = True

    return details


# ═══════════════════════════════════════════════════════════════
# PERSISTENT STATE MANAGEMENT
# ═══════════════════════════════════════════════════════════════
# All dedup and tracking data is saved to JSON on disk.
# Nothing depends on an external agent — the script is self-contained.


def load_seen_ids():
    """Load previously seen IDs from SEEN_JSON (primary dedup source).

    SEEN_JSON contains 'seen_ids': list of LinkedIn numeric IDs.
    If the file doesn't exist or is corrupted, returns empty set
    (first run).
    """
    try:
        data = json.loads(SEEN_JSON.read_text())
        return set(data.get("seen_ids", []))
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return set()


def load_existing_from_md():
    """Fallback: read IDs from the legacy MD file (jobs.md).

    Extracts all IDs from linkedin.com/jobs/view/XXXXX in the file.
    Used as a complement to SEEN_JSON to preserve jobs saved before
    the JSON dedup system was introduced.
    """
    try:
        content = VAGAS_FILE.read_text()
        return set(re.findall(r'linkedin\.com/jobs/view/(\d+)', content))
    except FileNotFoundError:
        return set()


def normalize_key(title, company):
    """Generate a normalized key for title+company dedup.

    Normalization applied:
    1. Strip HTML tags (&amp; → &, etc.)
    2. Lowercase
    3. Strip common suffixes: (PJ), - Remote, | Pleno, etc.

    Applied to BOTH title AND company — so
    'Bees Brasil' and 'Bees Brasil (AB InBev)' become the same key.

    Final format: 'title||company' (|| separator is safe).
    """
    t = re.sub(r'<[^>]+>', '', title).strip().lower()
    c = re.sub(r'<[^>]+>', '', company).strip().lower()
    t = t.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    c = c.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    # Strip common variations from title AND company
    # e.g. "Data Engineer - Remote" → "Data Engineer"
    # e.g. "Bees Brasil (AB InBev)" → "Bees Brasil"
    for pat in [r'\s*[-–—]\s*.*$', r'\s*\(.*?\)\s*$', r'\s*\|.*$']:
        t = re.sub(pat, '', t).strip()
        c = re.sub(pat, '', c).strip()
    return f"{t}||{c}"


def load_seen_keys():
    """Load previously seen title+company keys from SEEN_JSON.

    Complements load_seen_ids() — catches jobs reposted with a new ID
    but same title and company (LinkedIn generates a new ID when a job
    is closed and reopened).
    """
    try:
        data = json.loads(SEEN_JSON.read_text())
        return set(data.get("seen_keys", []))
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return set()


def save_full_state(seen_ids, seen_keys, new_ids, new_keys):
    """Save full state to SEEN_JSON (merge of old + new).

    IDs and keys are sorted for clean git diffs (if versioned).
    Updates count_ids, count_keys and timestamp.
    """
    all_ids = sorted(seen_ids | new_ids)
    all_keys = sorted(seen_keys | new_keys)
    SEEN_JSON.write_text(json.dumps({
        "seen_ids": all_ids,
        "seen_keys": all_keys,
        "count_ids": len(all_ids),
        "count_keys": len(all_keys),
        "updated_at": datetime.now().isoformat(),
    }, ensure_ascii=False, indent=2))


def load_recently_reported(max_files=6):
    """Read last N agent outputs and extract jobs already reported to the user.

    This closes the loop: agent reports jobs → script reads outputs →
    on next run, those jobs are excluded even if the API returns them.

    Requires LINKEDIN_CRON_OUTPUT_DIR env var to be set. If not set,
    returns empty set (feature disabled).

    Regex looks for '**N. ⭐⭐⭐ Title**' in the agent's markdown response,
    then extracts the company from the following line (format: 'Company | Location | ...').

    Filters out template placeholders ('job title' etc.).
    """
    reported = set()
    if not CRON_OUTPUT_DIR or not CRON_OUTPUT_DIR.exists():
        return reported
    files = sorted(CRON_OUTPUT_DIR.glob("*.md"), reverse=True)[:max_files]
    for f in files:
        try:
            content = f.read_text()
            # Pattern: **N. ⭐** or **N. ⭐⭐** in the response markdown
            for m in re.finditer(r'\*\d+\.\s*⭐+\s+(?:🔥\s+)?(.+?)\*\*', content):
                title = m.group(1).strip()
                # Extract company: look for lines after the title containing pipe |
                # Agent format is: Company | Location | Mode
                idx = m.end()
                after = content[idx:idx+500]
                lines = [l.strip() for l in after.split('\n') if l.strip()]
                company = ''
                for line in lines[:3]:
                    if '|' in line:
                        company = line.split('|')[0].strip()
                        break
                # Skip template placeholders
                placeholders = ("título da vaga", "titulo da vaga", "título",
                                "job title", "title")
                if title and company and title.lower() not in placeholders:
                    reported.add(normalize_key(title, company))
        except Exception:
            continue  # corrupted or inaccessible file → skip
    return reported


def load_keyword_stats():
    """Load per-keyword yield statistics from the tracking JSON.

    If the file doesn't exist (first run), returns empty structure:
    {'keywords': {}, 'pruned': []}
    """
    try:
        return json.loads(KEYWORDS_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {"keywords": {}, "pruned": []}


def save_keyword_stats(stats):
    """Save keyword stats to disk."""
    KEYWORDS_FILE.write_text(json.dumps(stats, ensure_ascii=False, indent=2))


def update_keyword_stats(stats, keyword, new_count):
    """Update a keyword's yield — increment runs and count new jobs.

    Tracks: total_runs (how many times it ran), total_new (jobs produced),
    last_new (timestamp of last time it found a job),
    last_run (last execution timestamp).

    If the keyword has never been seen, initializes the record.
    """
    if keyword not in stats["keywords"]:
        stats["keywords"][keyword] = {"total_runs": 0, "total_new": 0, "last_new": None}
    ks = stats["keywords"][keyword]
    ks["total_runs"] += 1
    ks["total_new"] += new_count
    ks["last_run"] = datetime.now().isoformat()
    if new_count > 0:
        ks["last_new"] = datetime.now().isoformat()


def prune_keywords(keywords, stats, min_runs=15, min_yield=2):
    """Remove keywords that produced nothing after N runs.

    Criteria: keyword with at least min_runs executions AND fewer than
    min_yield total jobs is removed. New keywords (< min_runs runs)
    have a grace period.

    If pruning removes too many, keeps at least 4 active.
    Removed keywords go to stats['pruned'] for audit.
    """
    active = []
    for kw in keywords:
        ks = stats["keywords"].get(kw)
        # New keyword or few runs → keep (grace period)
        if not ks or ks["total_runs"] < min_runs:
            active.append(kw)
            continue
        # Keyword ran a lot but produced little → remove
        if ks["total_new"] < min_yield:
            print(f"Keyword pruned: '{kw}' ({ks['total_runs']} runs, {ks['total_new']} jobs)", file=sys.stderr)
            stats["pruned"].append({"keyword": kw, "at": datetime.now().isoformat(),
                                    "runs": ks["total_runs"], "yield": ks["total_new"]})
            continue
        active.append(kw)
    # If pruning removed all or nearly all, keep 4+ originals
    if len(active) < 4:
        active = keywords[:max(4, len(keywords))]
    return active


def heuristic_score(job):
    """Heuristic 1-5 star score based on title + location.

    Used by the LLM agent as a starting point — it only needs to
    re-evaluate borderline cases (score 2-4). This cuts token usage
    and cost by ~80% compared to classifying everything with the LLM.

    Scoring (cumulative):
      Tech stack: +2 (high: data engineer, AI engineer, etc.)
                  +1 (mid: data analyst, BI, SQL, etc.)
                  +0 (not identified)
      Level:      +2 (senior, lead, manager, head, etc.)
                  +2 (no indicator — assumes mid/senior, BR market default)
                  →1 (junior/mid → discarded immediately)
      Location:   +1 (remote, hybrid SP, on-site SP)
                  +0 (others)

    Score → stars conversion:
      4+ → 5★ | 3 → 4★ | 2 → 3★ | 1 → 2★ | 0 → 1★
    """
    title = job.get("title", "").lower()
    loc = job.get("location", "").lower()
    # company available for future use (e.g. prestige weighting)
    # company = job.get("company", "").lower()

    score = 0
    reasons = []

    # ---- TECH STACK (0-2 points) ----
    # High-relevance keywords for a data/analytics/AI profile
    high_skills = ["data engineer", "analytics engineer", "bi manager", "data analytics",
                   "ai engineer", "machine learning", "head de dados", "gerente de dados",
                   "data tech lead", "chapter lead", "coordenador", "coordenadora"]
    # Medium-relevance keywords (analytics, BI, tools)
    mid_skills = ["data analyst", "data scientist", "business intelligence", "bi ", "etl",
                  "bigquery", "airflow", "spark", "dbt", "python", "sql"]

    if any(s in title for s in high_skills):
        score += 2
        reasons.append("high stack")
    elif any(s in title for s in mid_skills):
        score += 1
        reasons.append("mid stack")
    # No match → 0 stack points

    # ---- SENIORITY LEVEL (0-2 points) ----
    senior_kw = ["senior", "sênior", "lead", "manager", "head", "director", "coordenador",
                 "coordenadora", "gerente", "principal", "staff"]
    junior_kw = ["junior", "júnior", "jr", "intern", "estagiário", "trainee", "pleno",
                 "pl.", "mid-level"]

    # Junior/Mid → discard immediately (minimum score)
    if any(j in title for j in junior_kw):
        return (1, "junior/mid level")
    # Explicit senior+ → max score
    if any(s in title for s in senior_kw):
        score += 2
        reasons.append("senior+")
    else:
        # No level indicator → assume mid/senior
        # Rationale: BR data market rarely posts jobs without seniority;
        # bare "Data Engineer" titles are typically mid+
        score += 2
        reasons.append("mid/senior (assumed)")

    # ---- LOCATION (0-1 point) ----
    is_brazil = "brazil" in loc or "brasil" in loc
    is_sp = "são paulo" in loc or "sao paulo" in loc
    if "remote" in loc or "remoto" in loc or (is_brazil and not is_sp):
        score += 1
        reasons.append("remote/BR")
    elif is_sp:
        score += 1
        reasons.append("SP")
    # Not Brazil or SP → 0 points (international job)

    # ---- SCORE → STARS ----
    # theoretical max: 2+2+1 = 5 → 5 stars
    if score >= 4:
        return (5, ", ".join(reasons))
    elif score >= 3:
        return (4, ", ".join(reasons))
    elif score >= 2:
        return (3, ", ".join(reasons))
    elif score >= 1:
        return (2, ", ".join(reasons))
    else:
        return (1, ", ".join(reasons) if reasons else "no match")


def format_vaga_md(job, details):
    """Format a job as a markdown block for the jobs.md file.

    Structure:
      ## Job Title
      **Company:** Name
      **Location:** City, State, Country
      **Mode:** Remote/Hybrid/On-site
      **Posted:** 1 week ago
      **Link:** https://linkedin.com/jobs/view/ID

      > Short description (up to 3 sentences)
    """
    title = job.get("title", "Untitled job")
    company = job.get("company", "See link")
    location = job.get("location", "See link")
    work_mode = details.get("work_mode", "")
    date_label = job.get("date_label", job.get("date", "See link"))
    url = job.get("url", "")
    desc = details.get("description", "")

    # Summarize description into up to 3 sentences (each > 15 chars)
    desc_lines = []
    for line in desc.split(". "):
        line = line.strip()
        if line and len(line) > 15:
            desc_lines.append(line)
            if len(desc_lines) >= 3:
                break
    desc_text = ". ".join(desc_lines)

    block = f"""## {title}
**Company:** {company}
**Location:** {location}
**Mode:** {work_mode or "See link"}
**Posted:** {date_label}
**Link:** {url}

> {desc_text}

---"""
    return block


# ═══════════════════════════════════════════════════════════════
# MAIN — EXECUTION PIPELINE
# ═══════════════════════════════════════════════════════════════
# 1. Load persistent state (IDs, keys, keyword stats)
# 2. Read recent agent responses (jobs already reported)
# 3. Prune unproductive keywords (only after 15+ runs)
# 4. Search the API (2 pages per query, parallel with deadline)
# 5. Triple dedup (ID + title/company + recently reported)
# 6. Filter by location + level (drop junior, drop international)
# 7. Fetch job details in parallel (3 threads, max 8 jobs)
# 8. Save state, keyword stats, JSON for agent, MD history


def main():
    """Full pipeline to scrape and dedup LinkedIn jobs."""
    now = datetime.now().strftime("%d/%m/%Y %H:%M")

    # ═══ STEP 1: LOAD PERSISTENT STATE ═══
    seen_ids = load_seen_ids()          # IDs from SEEN_JSON (primary)
    seen_keys = load_seen_keys()        # title||company keys from SEEN_JSON
    md_ids = load_existing_from_md()    # IDs from legacy MD (fallback)
    all_known_ids = seen_ids | md_ids   # Union: any seen ID

    # ═══ STEP 2: JOBS ALREADY REPORTED BY AGENT ═══
    # Read the last 3 cron outputs — what the agent already showed
    # the user can't appear again, even if the API returns it
    recently_reported = load_recently_reported()
    print(f"Recently reported jobs: {len(recently_reported)}", file=sys.stderr)

    # ═══ STEP 3: KEYWORDS + PRUNING ═══
    kw_stats = load_keyword_stats()
    active_keywords = prune_keywords(KEYWORDS, kw_stats)
    searches = build_searches(active_keywords)

    deadline = time.time() + 240  # 4 minute total timeout

    print(f"Searching LinkedIn Guest API — {now}", file=sys.stderr)
    print(f"Seen IDs: {len(all_known_ids)} | Keys: {len(seen_keys)}", file=sys.stderr)
    print(f"Active keywords: {len(active_keywords)}/{len(KEYWORDS)}", file=sys.stderr)
    print(f"Queries: {len(searches)}, 2 pages each, deadline 240s", file=sys.stderr)

    # ═══ STEP 4: SEARCH THE API ═══
    # Iterate over all active queries. Each query = 2 pages of 25 jobs.
    # Global deadline: if exceeded, stop searching immediately.
    # source_keyword tracks which keyword produced the job (for yield tracking).
    # _key caches normalize_key (avoids recomputing 3x).
    all_jobs = []
    all_seen = set()  # cross-query dedup (same job can appear in multiple queries)

    for params in searches:
        if time.time() > deadline:
            print("Global deadline reached — stopping searches.", file=sys.stderr)
            break
        jobs = search_jobs(params, max_pages=2, deadline=deadline)
        kw = params.get("keywords", "")
        for job in jobs:
            if job["id"] not in all_seen:
                job["source_keyword"] = kw  # track which keyword found this job
                job["_key"] = normalize_key(job.get("title", ""), job.get("company", ""))
                all_seen.add(job["id"])
                all_jobs.append(job)
        time.sleep(0.3)

    print(f"Total jobs found: {len(all_jobs)}", file=sys.stderr)

    # ═══ STEP 5: TRIPLE DEDUP ═══
    # Three exclusion layers, in this order:
    #   a) Numeric ID already seen (all_known_ids = SEEN_JSON + legacy MD)
    #   b) title||company key already seen (reposted jobs with new ID)
    #   c) Job already reported by agent in last 3 outputs
    new_jobs = []
    skipped_ids = 0
    skipped_keys = 0
    skipped_reported = 0
    for j in all_jobs:
        if j["id"] in all_known_ids:
            skipped_ids += 1
            continue
        key = j.get("_key") or normalize_key(j.get("title", ""), j.get("company", ""))
        if key in seen_keys:
            skipped_keys += 1
            continue
        if key in recently_reported:
            skipped_reported += 1
            continue
        new_jobs.append(j)
    print(f"Dedup: {skipped_ids} IDs + {skipped_keys} title+company + {skipped_reported} reported", file=sys.stderr)
    print(f"New jobs: {len(new_jobs)}", file=sys.stderr)

    # ═══ STEP 6: FILTER BY LOCATION AND LEVEL ═══
    # Drop junior/intern jobs and jobs outside Brazil/São Paulo.
    # This filter is local (doesn't require API detail fetch).
    filtered = []
    for job in new_jobs:
        loc = job.get("location", "").lower()
        title = job.get("title", "").lower()

        # Exclude junior/intern/trainee jobs
        skip = False
        for kw in ["junior", "júnior", "jr", "intern", "estagiário", "trainee"]:
            if kw in title:
                skip = True
                break
        if skip:
            continue

        # Only Brazil or São Paulo (skip India, USA, etc.)
        is_brazil = "brazil" in loc or "brasil" in loc or "são paulo" in loc or "sao paulo" in loc
        if not is_brazil:
            continue

        filtered.append(job)

    print(f"After location+level filter: {len(filtered)}", file=sys.stderr)

    if not filtered:
        # Even with no jobs, save keyword stats (all ran)
        for params in searches:
            kw = params.get("keywords", "")
            update_keyword_stats(kw_stats, kw, 0)
        save_keyword_stats(kw_stats)
        print(f"No new jobs — {now}")
        return

    # ═══ STEP 7: FETCH DETAILS IN PARALLEL ═══
    # ThreadPoolExecutor with 3 workers — fetches description and work mode
    # of each job simultaneously. Max 8 jobs per run.
    # Filters applied during fetch: closed jobs and on-site outside SP.
    MAX_DETAIL = 8
    jobs_to_fetch = filtered[:MAX_DETAIL]

    def fetch_one(job):
        """Fetch details for ONE job and apply final filters.

        Returns (job, details) if the job passes all filters.
        Returns None if: deadline exceeded, no ID, closed job,
        or on-site outside São Paulo.
        """
        if time.time() > deadline:
            return None
        job_id = job.get("id")
        if not job_id:
            print(f"Skipping job without ID: {job.get('title', '?')}", file=sys.stderr)
            return None
        details = get_job_details(job_id)
        if details.get("closed"):
            print(f"Skipping closed job: {job['title']}", file=sys.stderr)
            return None
        work_mode = details.get("work_mode", "")
        # On-site only if in SP (hybrid and remote pass through)
        if work_mode.lower() in ("on-site", "presencial"):
            loc_lower = job.get("location", "").lower()
            is_sp = "são paulo" in loc_lower or "sao paulo" in loc_lower or re.search(r',\s*sp\b', loc_lower)
            if not is_sp:
                print(f"Skipping on-site job outside SP: {job['title']} — {job['location']}", file=sys.stderr)
                return None
        return (job, details)

    enriched = []
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(fetch_one, job): job for job in jobs_to_fetch}
        for future in as_completed(futures):
            if time.time() > deadline:
                for f in futures:
                    f.cancel()
                print("Deadline reached during detail fetch — stopping.", file=sys.stderr)
                break
            result = future.result()
            if result:
                enriched.append(result)

    if not enriched:
        print(f"No new jobs (all closed) — {now}")
        JOBS_JSON.write_text("[]")  # empty JSON → agent processes nothing
        return

    # ═══ STEP 8: SAVE STATE AND GENERATE OUTPUTS ═══

    # --- 8a. Update SEEN_JSON with IDs and keys of enriched jobs ---
    new_ids_to_mark = set()
    new_keys_to_mark = set()
    for job, details in enriched:
        new_ids_to_mark.add(job["id"])
        new_keys_to_mark.add(job.get("_key") or normalize_key(job.get("title", ""), job.get("company", "")))

    save_full_state(seen_ids, seen_keys, new_ids_to_mark, new_keys_to_mark)
    print(f"SEEN_JSON updated: +{len(new_ids_to_mark)} IDs, +{len(new_keys_to_mark)} keys", file=sys.stderr)

    # --- 8b. Update keyword stats with this run's yield ---
    kw_yield = {}
    for j in filtered:
        sk = j.get("source_keyword", "")
        if sk:
            kw_yield[sk] = kw_yield.get(sk, 0) + 1
    for kw, count in kw_yield.items():
        update_keyword_stats(kw_stats, kw, count)
    # Keywords that produced nothing are also recorded (total_runs++)
    for params in searches:
        kw = params.get("keywords", "")
        if kw not in kw_yield:
            update_keyword_stats(kw_stats, kw, 0)
    save_keyword_stats(kw_stats)

    # --- 8c. Generate JSON for the agent to classify ---
    # Includes pre-computed heuristic_score and heuristic_reason
    # Agent uses as starting point, only re-evaluating borderline cases
    jobs_for_agent = []
    for job, details in enriched:
        h_score, h_reason = heuristic_score(job)
        jobs_for_agent.append({
            "id": job["id"],
            "title": job.get("title", ""),
            "company": job.get("company", ""),
            "location": job.get("location", ""),
            "work_mode": details.get("work_mode", ""),
            "date_label": job.get("date_label", ""),
            "url": job.get("url", ""),
            "description": details.get("description", ""),
            "heuristic_score": h_score,
            "heuristic_reason": h_reason,
        })
    JOBS_JSON.write_text(json.dumps(jobs_for_agent, ensure_ascii=False, indent=2))
    print(f"JSON saved: {len(jobs_for_agent)} jobs for classification", file=sys.stderr)

    # --- 8d. Update MD history (append-only, never removes) ---
    vagas_md = []

    for job, details in enriched:
        block = format_vaga_md(job, details)
        vagas_md.append(block)

    # Rebuild MD: new header + new jobs + old content
    header = f"""# LinkedIn Jobs — {USER_NAME}

> Last updated: {now}
> Filters: Remote (Brazil) / Hybrid+On-site (São Paulo) | Senior+ | Max 1 month | Via LinkedIn Guest API

---"""

    try:
        current = VAGAS_FILE.read_text()
        if current.startswith("# LinkedIn Jobs"):
            parts = current.split("---", 1)
            rest = parts[1] if len(parts) > 1 else ""
        else:
            rest = current
    except FileNotFoundError:
        rest = ""

    new_content = header + "\n\n" + "\n\n".join(vagas_md) + rest
    VAGAS_FILE.write_text(new_content)

    print(f"✅ {len(enriched)} job(s) collected — {now}")


if __name__ == "__main__":
    main()

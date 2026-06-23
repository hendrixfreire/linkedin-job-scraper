#!/usr/bin/env python3
"""
CV Tailoring Tool — adapt your CV to specific job descriptions.

Two modes, auto-selected based on whether you have an LLM API key:

  With LLM_API_KEY set  → Full AI tailoring (like cv-job-fit skill).
                           Reads your CV, fetches the job description,
                           calls an LLM to generate a polished, ATS-optimized
                           CV tailored for that specific role.

  Without LLM_API_KEY   → Keyword-based analysis (free, no API).
                           Compares your CV against job keywords, shows
                           match %, identifies gaps, and generates an
                           LLM-ready prompt you can paste into ChatGPT.

Usage:
  # Full AI tailoring (requires LLM_API_KEY)
  python3 tailor_cv.py cv.md --job-id 4429960220

  # Analyze all scraped jobs (no LLM needed)
  python3 tailor_cv.py analyze cv.md jobs_new.json

  # Generate LLM prompt for manual pasting
  python3 tailor_cv.py prompt cv.md --job-id 4429960220

Configuration (env vars):
  LLM_API_KEY        — API key for OpenAI-compatible endpoint (required for full tailoring)
  LLM_API_BASE       — Base URL (default: https://api.openai.com/v1)
  LLM_MODEL          — Model name (default: gpt-4o-mini)
  TAILOR_CV_DIR      — Where to save tailored CVs (default: ~/linkedin-jobs/tailored/)
  LINKEDIN_OUTPUT_DIR — Base directory for scraper outputs
"""

import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

# ═══════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════
OUTPUT_DIR = Path(os.environ.get(
    "TAILOR_CV_DIR",
    Path(os.environ.get("LINKEDIN_OUTPUT_DIR",
         Path.home() / "linkedin-jobs")) / "tailored"
))

LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_API_BASE = os.environ.get("LLM_API_BASE", "https://api.openai.com/v1")
LLM_MODEL = os.environ.get("LLM_MODEL", "gpt-4o-mini")

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/126.0.0.0 Safari/537.36"),
}

# ═══════════════════════════════════════════════════════════════
# SKILL LEXICON — categorized keywords for fallback mode
# ═══════════════════════════════════════════════════════════════
TECH_TOOLS = {
    "bigquery", "snowflake", "redshift", "databricks", "spark", "pyspark",
    "airflow", "prefect", "dagster", "dbt", "looker", "tableau", "power bi",
    "powerbi", "looker studio", "google analytics", "ga4",
    "jupyter", "colab", "docker", "kubernetes", "k8s", "terraform",
    "git", "github", "gitlab", "aws", "gcp", "azure", "s3", "ec2",
    "lambda", "cloud functions", "postgres", "postgresql", "mysql",
    "mongodb", "redis", "elasticsearch", "kafka", "pub/sub", "pubsub",
    "segment", "fivetran", "stitch", "airbyte", "hightouch", "census",
    "mixpanel", "amplitude", "excel", "sheets", "google sheets",
    "notion", "confluence", "jira", "slack", "teams", "linear",
    "hadoop", "hive", "presto", "trino", "flink", "beam", "dataflow",
    "lakehouse", "delta lake", "iceberg", "hudi",
}

LANGUAGES = {
    "python", "sql", "scala", "java", "golang", "rust",
    "javascript", "typescript", "bash", "shell", "ruby",
    "html", "yaml", "json", "xml",
}

PYTHON_LIBS = {
    "pandas", "numpy", "scikit-learn", "sklearn", "tensorflow",
    "pytorch", "keras", "xgboost", "lightgbm", "catboost",
    "matplotlib", "seaborn", "plotly", "bokeh", "streamlit", "dash",
    "fastapi", "flask", "django", "pydantic", "sqlalchemy",
    "great expectations", "soda", "dlt", "meltano",
    "langchain", "llamaindex", "transformers", "huggingface",
    "spacy", "nltk", "openai", "anthropic",
}

DATA_CONCEPTS = {
    "etl", "elt", "pipeline", "data pipeline", "data warehouse",
    "data lake", "lakehouse", "medallion", "bronze", "silver", "gold",
    "data modeling", "dimensional modeling", "star schema",
    "cdc", "change data capture", "data governance", "data catalog",
    "data lineage", "data quality", "data mesh", "data contract",
    "ab testing", "a/b test", "experimentation", "hypothesis testing",
    "statistics", "regression", "classification", "clustering",
    "forecasting", "time series", "anomaly detection",
    "dashboard", "reporting", "kpi", "metric", "okr",
    "business intelligence", "bi", "analytics", "advanced analytics",
    "machine learning", "ml", "deep learning", "ai",
    "artificial intelligence", "generative ai", "genai",
    "llm", "rag", "vector database", "nlp", "natural language",
    "data engineering", "analytics engineering", "data science",
    "data analysis", "data architecture", "data platform",
    "data strategy", "data-driven", "orchestration",
    "monitoring", "alerting", "observability",
    "ci/cd", "devops", "mlops", "dataops",
}

SOFT_SKILLS = {
    "leadership", "management", "mentoring", "coaching", "stakeholder",
    "stakeholder management", "cross-functional", "collaboration",
    "communication", "presentation", "storytelling", "data storytelling",
    "client-facing", "client management", "consulting", "advisory",
    "project management", "agile", "scrum", "kanban", "sprint",
    "roadmap", "strategy", "strategic", "vision", "execution",
    "problem solving", "critical thinking", "analytical",
    "team building", "hiring", "team lead", "tech lead",
}

# Portuguese → English keyword mappings for bilingual matching
PT_TO_EN = {
    "liderança": "leadership", "liderar": "leadership",
    "gestão": "management", "gerenciamento": "management",
    "mentoria": "mentoring", "comunicação": "communication",
    "colaboração": "collaboration", "apresentação": "presentation",
    "estratégia": "strategy", "estratégico": "strategy",
    "analítico": "analytical", "equipe": "team building",
    "ágeis": "agile", "ágil": "agile", "scrum": "scrum",
    "stakeholders": "stakeholder management",
    "multidisciplinar": "collaboration",
    "cliente": "client-facing", "clientes": "client-facing",
    "aprendizado de máquina": "machine learning",
    "inteligência artificial": "ai", "ia": "ai",
    "ia generativa": "generative ai",
    "banco de dados": "data warehouse",
    "bases de dados": "data warehouse",
    "modelagem": "data modeling",
    "modelagem de dados": "data modeling",
    "transformação": "data transformation",
    "orquestração": "orchestration",
    "governança": "data governance",
    "governança de dados": "data governance",
    "painel": "dashboard", "painéis": "dashboard",
    "dashboards": "dashboard", "relatórios": "reporting",
    "experimentação": "ab testing", "teste a/b": "ab testing",
    "estatística": "statistics", "regressão": "regression",
    "classificação": "classification", "clusterização": "clustering",
    "extração": "data extraction", "ingestão": "data ingestion",
    "limpeza": "data cleaning", "integração": "data integration",
    "conectores": "data integration",
    "automação": "orchestration", "automatização": "orchestration",
    "pipeline": "data pipeline", "pipelines": "data pipeline",
    "monitoramento": "monitoring", "alertas": "alerting",
    "devops": "devops", "mlops": "mlops", "ci/cd": "ci/cd",
    "agentes": "ai", "agentes de ia": "ai",
    "engenharia de prompts": "nlp", "contextualização": "nlp",
    "llm": "llm", "rag": "rag", "vetorial": "vector database",
    "visualização": "data storytelling",
    "carregamento": "data loading",
    "qualidade de dados": "data quality",
    "catálogo": "data catalog", "linhagem": "data lineage",
    "previsão": "forecasting", "séries temporais": "time series",
}


def _word_match(keyword, text):
    """Check if keyword appears in text, with bilingual support."""
    kw_lower = keyword.lower()
    text_lower = text.lower()
    kw_clean = kw_lower.replace(" ", "").replace("-", "").replace("/", "")
    text_clean = text_lower.replace(" ", "").replace("-", "").replace("/", "")

    if kw_clean in text_clean:
        if len(kw_clean) <= 2:
            return bool(re.search(r'(?<![a-z])' + re.escape(kw_lower) +
                                  r'(?![a-z])', text_lower))
        return True

    for pt_word, en_word in PT_TO_EN.items():
        if en_word.lower() == kw_lower:
            if pt_word.replace(" ", "").replace("-", "") in text_clean:
                return True

    en_from_pt = PT_TO_EN.get(kw_lower)
    if en_from_pt:
        if en_from_pt.replace(" ", "").replace("-", "").replace("/", "") in text_clean:
            return True

    return False


def extract_cv_keywords(cv_text):
    """Extract tools, concepts, and soft skills from CV text."""
    text_lower = cv_text.lower()
    tools = {t for t in TECH_TOOLS | LANGUAGES | PYTHON_LIBS
             if _word_match(t, text_lower)}
    concepts = {c for c in DATA_CONCEPTS if _word_match(c, text_lower)}
    soft = {s for s in SOFT_SKILLS if _word_match(s, text_lower)}
    return tools, concepts, soft


# ═══════════════════════════════════════════════════════════════
# JOB FETCHING
# ═══════════════════════════════════════════════════════════════

def fetch_job_description(job_id, retries=1):
    """Fetch full job description + metadata from LinkedIn Guest API.

    Returns dict with 'title', 'company', 'description' or None on failure.
    Retries once on transient errors (consistent with scraper behavior).
    """
    url = f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"

    for attempt in range(retries + 1):
        try:
            req = Request(url, headers=HEADERS)
            with urlopen(req, timeout=10) as resp:
                html = resp.read().decode("utf-8", errors="replace")
            break
        except (HTTPError, URLError, OSError) as e:
            if attempt < retries:
                time.sleep(2)
            else:
                print(f"Error fetching job {job_id}: {e}", file=sys.stderr)
                return None

    # Clean HTML to text
    text = re.sub(r'<[^>]+>', ' ', html)
    text = re.sub(r'\s+', ' ', text).strip()

    # Try to extract job title from the HTML
    title = "Unknown Role"
    title_match = re.search(
        r'<title>\s*(.*?)\s*</title>', html, re.IGNORECASE)
    if not title_match:
        title_match = re.search(
            r'class="[^"]*top-card-layout__title[^"]*"[^>]*>\s*(.*?)\s*</h1>',
            html, re.IGNORECASE | re.DOTALL)
    if title_match:
        raw_title = re.sub(r'<[^>]+>', '', title_match.group(1)).strip()
        # LinkedIn titles often have "Job Details | LinkedIn" suffix
        raw_title = re.sub(r'\s*\|\s*LinkedIn\s*$', '', raw_title).strip()
        if raw_title and raw_title.lower() not in ('linkedin', 'job details'):
            title = raw_title

    # Try to extract company name
    company = "Unknown Company"
    company_match = re.search(
        r'class="[^"]*topcard__org-name-link[^"]*"[^>]*>\s*(.*?)\s*</a>',
        html, re.IGNORECASE | re.DOTALL)
    if not company_match:
        company_match = re.search(
            r'class="[^"]*top-card-layout__second-subline[^"]*"[^>]*>\s*(.*?)\s*</span>',
            html, re.IGNORECASE | re.DOTALL)
    if company_match:
        company = re.sub(r'<[^>]+>', '', company_match.group(1)).strip()
        if not company or company.lower() in ('linkedin', ''):
            company = "Unknown Company"

    return {"title": title, "company": company, "description": text}


def load_jobs_json(path):
    """Load jobs from the scraper's jobs_new.json."""
    try:
        data = json.loads(Path(path).read_text())
    except FileNotFoundError:
        print(f"Error: file not found: {path}", file=sys.stderr)
        print("  Run the scraper first: python3 linkedin_jobs.py", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error: invalid JSON in {path}: {e}", file=sys.stderr)
        sys.exit(1)
    return data if isinstance(data, list) else []


def get_job_from_json(jobs, job_id):
    """Find a specific job in the jobs array by ID."""
    for j in jobs:
        if j.get("id") == job_id:
            return j
    return None


# ═══════════════════════════════════════════════════════════════
# LLM API CALL (stdlib only — urllib)
# ═══════════════════════════════════════════════════════════════

def call_llm(system_prompt, user_prompt, max_tokens=3000):
    """Call an OpenAI-compatible chat completions endpoint.

    Uses urllib (stdlib) — zero external dependencies.
    Requires LLM_API_KEY env var.
    """
    if not LLM_API_KEY:
        return None

    url = f"{LLM_API_BASE.rstrip('/')}/chat/completions"
    body = json.dumps({
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.3,
    }).encode("utf-8")

    req = Request(url, data=body, headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LLM_API_KEY}",
    })

    try:
        with urlopen(req, timeout=180) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            if "choices" not in result:
                error_msg = result.get("error", {}).get("message", str(result))
                print(f"LLM API error: {error_msg}", file=sys.stderr)
                return None
            return result["choices"][0]["message"]["content"]
    except HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:300] if e.fp else ""
        print(f"LLM API HTTP {e.code}: {body}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"LLM API error: {e}", file=sys.stderr)
        return None


# ═══════════════════════════════════════════════════════════════
# CORE: CV TAILORING (LLM-powered — mirrors cv-job-fit skill)
# ═══════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """You are a professional CV/resume writer specializing in data,
analytics, AI, and engineering roles. Your job is to tailor a candidate's CV to
a specific job description without inventing anything.

RULES (follow strictly):
1. NEVER invent skills, experience, tools, metrics, employers, dates, education,
   certifications, or achievements. Only use what's in the original CV.
2. Rephrase, reorder, condense, and highlight only what is already supported.
3. Mirror relevant keywords from the job description when they are honestly
   supported by the CV.
4. If the job asks for something NOT evidenced in the CV, mark it as a GAP
   instead of faking alignment.
5. Keep the CV concise — target 1 page, max 2 pages.
6. Use strong, concrete language. Avoid corporate filler and generic buzzwords.
7. Optimize for both ATS scanning and human reading.
8. Output in clean markdown format.

OUTPUT FORMAT:
Return the tailored CV as markdown with these sections:

# [Candidate Name] — Tailored CV
> **Target:** [Job Title] at [Company]
> **Compatibility:** [X]/100

## Professional Profile
(3-5 sentences, keyword-optimized for this role)

## Professional Experience
(Reordered by relevance to this job. Each role gets ### header.
Add a 1-line annotation under each header showing why it's relevant.)

## Skills
(Grouped by category, with matching keywords emphasized)

## Tools & Technologies
(List matching tools first, then others)

## Education
(Keep as-is)

## Certifications
(Keep as-is, reorder if relevant)

## Languages
(Keep as-is)

---

## Tailoring Notes
- Compatibility score breakdown (hard skills / soft skills / domain)
- What was reordered and why
- Which keywords were emphasized
- **Real gaps** the candidate should address before applying
"""


def build_user_prompt(cv_text, job_title, job_company, job_description):
    """Build the user prompt with CV + job details."""
    return f"""## Target Job

**Title:** {job_title}
**Company:** {job_company}

### Job Description
{job_description[:3000]}

## Original CV
```markdown
{cv_text}
```
"""


def tailor_with_llm(cv_text, job_title, job_company, job_description):
    """Call LLM to generate tailored CV. Returns markdown string or None."""
    print(f"Calling {LLM_MODEL} for CV tailoring...", file=sys.stderr)
    print(f"  (set LLM_MODEL env var to change model)", file=sys.stderr)

    user_prompt = build_user_prompt(cv_text, job_title, job_company,
                                     job_description)

    result = call_llm(SYSTEM_PROMPT, user_prompt, max_tokens=3500)
    return result


# ═══════════════════════════════════════════════════════════════
# FALLBACK: keyword-based analysis (no LLM)
# ═══════════════════════════════════════════════════════════════

def parse_job_keywords(text):
    """Extract structured requirements from job description text."""
    text_lower = text.lower()
    tools = {t for t in TECH_TOOLS | LANGUAGES | PYTHON_LIBS
             if _word_match(t, text_lower)}
    concepts = {c for c in DATA_CONCEPTS if _word_match(c, text_lower)}
    soft = {s for s in SOFT_SKILLS if _word_match(s, text_lower)}

    seniority = "unknown"
    for s in ["senior", "sênior", "sr.", "lead", "staff", "principal"]:
        if _word_match(s, text_lower):
            seniority = "senior+"; break
    if seniority == "unknown":
        for s in ["manager", "head", "director"]:
            if _word_match(s, text_lower):
                seniority = "manager+"; break

    return {"tools": tools, "concepts": concepts, "soft": soft,
            "seniority": seniority}


def compute_match(cv_keywords, job_reqs):
    """Compare CV keywords against job requirements."""
    cv_tools, cv_concepts, cv_soft = cv_keywords
    cv_hard = cv_tools | cv_concepts
    job_hard = job_reqs["tools"] | job_reqs["concepts"]

    matched_hard = cv_hard & job_hard
    gaps_hard = job_hard - cv_hard
    matched_soft = cv_soft & job_reqs["soft"]
    gaps_soft = job_reqs["soft"] - cv_soft

    hard_pct = int(100 * len(matched_hard) / max(len(job_hard), 1))
    soft_pct = int(100 * len(matched_soft) / max(len(job_reqs["soft"]), 1))
    overall = int(0.7 * hard_pct + 0.3 * soft_pct)

    return {
        "overall": overall,
        "hard_match_pct": hard_pct, "soft_match_pct": soft_pct,
        "matched_hard": matched_hard, "gaps_hard": gaps_hard,
        "matched_soft": matched_soft, "gaps_soft": gaps_soft,
        "seniority": job_reqs["seniority"],
    }


def generate_llm_prompt(cv_text, job_title, job_company, job_description, match):
    """Generate structured LLM prompt for manual pasting (fallback mode)."""
    gaps = sorted(match["gaps_hard"] | match["gaps_soft"])
    matched = sorted(match["matched_hard"] | match["matched_soft"])

    return f"""{SYSTEM_PROMPT}

---

## Target Job

**Title:** {job_title}
**Company:** {job_company}
**Seniority:** {match['seniority']}

### Job Description
{job_description[:2000]}

## Match Analysis
**Overall Compatibility:** {match['overall']}/100
**Hard Skills Match:** {match['hard_match_pct']}% — in CV: {', '.join(matched[:15])}
**Soft Skills Match:** {match['soft_match_pct']}%
**Gaps (in job, not evident in CV):** {', '.join(gaps[:15])}

---

## Original CV
```markdown
{cv_text}
```
"""


# ═══════════════════════════════════════════════════════════════
# CLI COMMANDS
# ═══════════════════════════════════════════════════════════════

def cmd_tailor(cv_path, job_id=None, jobs_json=None, job_url=None,
               force_keyword=False):
    """Tailor CV for a specific job — LLM if available, keyword fallback.

    Set force_keyword=True to skip LLM even when API key is set
    (used by the 'prompt' command).
    """
    try:
        cv_text = Path(cv_path).read_text()
    except FileNotFoundError:
        print(f"Error: CV file not found: {cv_path}", file=sys.stderr)
        print("  Create a markdown file with your CV first.", file=sys.stderr)
        print("  See README for the recommended CV template.", file=sys.stderr)
        sys.exit(1)

    # --- Resolve job description ---
    job_title = "Unknown Role"
    job_company = "Unknown Company"
    job_description = ""

    if job_id and jobs_json:
        # Validate job_id
        if not re.match(r'^\d{1,20}$', str(job_id)):
            print(f"Error: invalid job ID: {job_id} (must be numeric)",
                  file=sys.stderr)
            sys.exit(1)
        jobs = load_jobs_json(jobs_json)
        target = get_job_from_json(jobs, job_id)
        if target:
            job_title = target.get("title", job_title)
            job_company = target.get("company", job_company)
            job_description = target.get("description", "")
        else:
            print(f"Job ID {job_id} not found in {jobs_json}", file=sys.stderr)
            sys.exit(1)
    elif job_id:
        # Validate job_id before making HTTP request
        if not re.match(r'^\d{1,20}$', str(job_id)):
            print(f"Error: invalid job ID: {job_id} (must be numeric)",
                  file=sys.stderr)
            sys.exit(1)
        print(f"Fetching job {job_id} from LinkedIn API...", file=sys.stderr)
        job_data = fetch_job_description(job_id)
        if not job_data:
            print("Failed to fetch job description.", file=sys.stderr)
            sys.exit(1)
        job_title = job_data.get("title", job_title)
        job_company = job_data.get("company", job_company)
        job_description = job_data.get("description", "")
    elif job_url:
        print("Paste the job description below (Ctrl+D to finish):", file=sys.stderr)
        job_description = sys.stdin.read()
    else:
        print("Provide --job-id, --json + --job-id, or --job-url.", file=sys.stderr)
        sys.exit(1)

    if not job_description.strip():
        print("Error: empty job description.", file=sys.stderr)
        sys.exit(1)

    print(f"Job: {job_title} @ {job_company}", file=sys.stderr)

    # --- Tailor ---
    safe_title = re.sub(r'[^a-zA-Z0-9_-]', '_', job_title)[:40]
    safe_company = re.sub(r'[^a-zA-Z0-9_-]', '_', job_company)[:20]
    # Guard against empty filenames (e.g., purely non-ASCII titles)
    if not safe_title.strip('_'):
        safe_title = f"job_{job_id or 'unknown'}"
    if not safe_company.strip('_'):
        safe_company = "company"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if LLM_API_KEY and not force_keyword:
        # ═══ FULL LLM TAILORING ═══
        tailored = tailor_with_llm(cv_text, job_title, job_company,
                                    job_description)
        if tailored:
            out_path = OUTPUT_DIR / f"cv_{safe_title}_{safe_company}.md"
            out_path.write_text(tailored)
            print(f"\n✅ Tailored CV saved: {out_path}")
            print(f"   Open it, review, and convert to PDF before submitting.")
            return
        else:
            print("\n⚠️  LLM call failed. Falling back to keyword mode.", file=sys.stderr)
            # Fall through to keyword mode

    # ═══ KEYWORD FALLBACK ═══
    cv_keywords = extract_cv_keywords(cv_text)
    job_reqs = parse_job_keywords(job_title + " " + job_description)
    match = compute_match(cv_keywords, job_reqs)

    prompt = generate_llm_prompt(cv_text, job_title, job_company,
                                  job_description, match)
    prompt_path = OUTPUT_DIR / f"prompt_{safe_title}_{safe_company}.md"
    prompt_path.write_text(prompt)

    gaps = sorted(match["gaps_hard"] | match["gaps_soft"])
    matched = sorted(match["matched_hard"] | match["matched_soft"])

    print(f"""
{'='*65}
  CV Analysis: {job_title}
  Company: {job_company}
  Compatibility: {match['overall']}/100 (hard {match['hard_match_pct']}%, soft {match['soft_match_pct']}%)
{'='*65}

  Matching: {', '.join(matched[:15]) or 'None'}
  Gaps:     {', '.join(gaps[:15]) or 'None'}

  LLM prompt saved: {prompt_path}

  To get a full tailored CV, either:
  a) Paste this prompt into ChatGPT / Claude / Hermes
  b) Set LLM_API_KEY env var and run again:
     export LLM_API_KEY="sk-..."
     python3 tailor_cv.py {cv_path} --job-id {job_id or ''}
""")


def cmd_analyze(cv_path, jobs_path):
    """Analyze CV against all jobs in jobs_new.json."""
    try:
        cv_text = Path(cv_path).read_text()
    except FileNotFoundError:
        print(f"Error: CV file not found: {cv_path}", file=sys.stderr)
        print("  Create a markdown file with your CV first.", file=sys.stderr)
        sys.exit(1)
    cv_keywords = extract_cv_keywords(cv_text)

    jobs = load_jobs_json(jobs_path)
    if not jobs:
        print("No jobs found in JSON file.")
        return

    print(f"{'='*65}")
    print(f"  CV-Job Match Analysis")
    print(f"  Jobs: {len(jobs)}  |  {'' if LLM_API_KEY else '(keyword mode)'}")
    print(f"{'='*65}\n")

    results = []
    for i, job in enumerate(jobs):
        title = job.get("title", "Untitled")
        company = job.get("company", "Unknown")
        desc = job.get("description", "")
        job_reqs = parse_job_keywords(title + " " + desc)
        match = compute_match(cv_keywords, job_reqs)
        results.append((match["overall"], title, company, match))
        gaps_show = sorted(match["gaps_hard"])[:4]
        print(f"  {i+1:>2}. [{match['overall']:>3}%] {title[:55]}")
        print(f"      {company[:45]}  |  {job_reqs['seniority']}")
        if gaps_show:
            print(f"      Gaps: {', '.join(gaps_show)}")
        print()

    results.sort(key=lambda x: x[0], reverse=True)
    print(f"{'='*65}")
    print(f"  Top matches:")
    for overall, title, company, _ in results[:5]:
        bar = "█" * (overall // 10) + "░" * (10 - overall // 10)
        print(f"  [{bar}] {overall:>3}% — {title[:50]} @ {company[:25]}")
    print(f"{'='*65}")

    if not LLM_API_KEY:
        print(f"\n  Tip: set LLM_API_KEY to enable full AI tailoring:")
        print(f"  export LLM_API_KEY=\"sk-...\"")
        print(f"  python3 tailor_cv.py {cv_path} --json {jobs_path} --job-id <id>")


def cmd_prompt(cv_path, job_id=None, jobs_json=None):
    """Generate LLM prompt for a specific job (always keyword-based)."""
    cmd_tailor(cv_path, job_id=job_id, jobs_json=jobs_json,
               force_keyword=True)


def print_usage():
    print("""Usage:
  python3 tailor_cv.py cv.md --job-id LINKEDIN_ID
  python3 tailor_cv.py cv.md --json jobs_new.json --job-id LINKEDIN_ID
  python3 tailor_cv.py analyze cv.md [jobs_new.json]
  python3 tailor_cv.py prompt cv.md --job-id LINKEDIN_ID

LLM-powered tailoring (recommended):
  export LLM_API_KEY="sk-..."          # OpenAI / OpenRouter / compatible
  export LLM_API_BASE="https://..."    # optional, defaults to OpenAI
  export LLM_MODEL="gpt-4o-mini"       # optional
  python3 tailor_cv.py cv.md --job-id 4429960220

Free keyword mode (no API key):
  python3 tailor_cv.py analyze cv.md jobs_new.json
  python3 tailor_cv.py cv.md --job-id 4429960220
""")


def main():
    args = sys.argv[1:]

    if not args or args[0] in ("--help", "-h", "help"):
        print_usage()
        return

    cmd = args[0]
    cv_path = None
    job_id = None
    jobs_json = None
    job_url = None
    unknown_flags = []

    i = 1 if cmd in ("analyze", "prompt") else 0

    # First positional arg is always cv.md (except analyze/prompt where cmd comes first)
    if cmd in ("analyze", "prompt"):
        if len(args) < 2:
            print(f"Error: cv.md path required.", file=sys.stderr)
            sys.exit(1)
        cv_path = args[1]
        i = 2
    else:
        cv_path = args[0]
        cmd = "tailor"  # implicit command
        i = 1

    while i < len(args):
        if args[i] == "--job-id":
            if i + 1 < len(args):
                job_id = args[i + 1]; i += 2
            else:
                print("Error: --job-id requires a value", file=sys.stderr)
                sys.exit(1)
        elif args[i] == "--json":
            if i + 1 < len(args):
                jobs_json = args[i + 1]; i += 2
            else:
                print("Error: --json requires a value", file=sys.stderr)
                sys.exit(1)
        elif args[i] == "--job-url":
            if i + 1 < len(args):
                job_url = args[i + 1]; i += 2
            else:
                print("Error: --job-url requires a value", file=sys.stderr)
                sys.exit(1)
        elif args[i].startswith("--"):
            unknown_flags.append(args[i])
            i += 1
        else:
            i += 1

    if unknown_flags:
        print(f"Warning: unknown flag(s): {', '.join(unknown_flags)}",
              file=sys.stderr)
        print("  Use --help for usage.", file=sys.stderr)

    if cmd == "analyze":
        # analyze cv.md [jobs_new.json] — second positional = jobs path
        if len(args) >= 3 and not args[2].startswith("--"):
            jobs_json = args[2]
        jpath = jobs_json or str(
            Path(os.environ.get("LINKEDIN_OUTPUT_DIR",
                 Path.home() / "linkedin-jobs")) / "jobs_new.json")
        cmd_analyze(cv_path, jpath)
    elif cmd == "tailor":
        cmd_tailor(cv_path, job_id=job_id, jobs_json=jobs_json,
                    job_url=job_url)
    elif cmd == "prompt":
        cmd_tailor(cv_path, job_id=job_id, jobs_json=jobs_json,
                    job_url=job_url, force_keyword=True)
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        print_usage()


if __name__ == "__main__":
    main()

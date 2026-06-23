#!/usr/bin/env python3
"""
CV Tailoring Tool for LinkedIn Job Scraper.

Takes your CV (markdown) and jobs from the scraper output, then helps you
tailor your CV per job. Works in two modes:

  analyze — Quick match/gap analysis for every job in jobs_new.json.
            Shows compatibility %, matching skills, missing keywords.
            No LLM required — pure keyword extraction.

  tailor  — Generate a keyword-optimized CV for a specific job.
            Reorders experience, highlights matching skills, flags gaps.
            Also outputs an LLM-ready prompt for AI-powered deep tailoring.

Usage:
  python3 tailor_cv.py analyze cv.md [jobs_new.json]
  python3 tailor_cv.py tailor cv.md [--job-id ID | --job-url URL | --job-file file.json]
  python3 tailor_cv.py tailor cv.md --json jobs_new.json --job-id 123456

Configuration (env vars):
  TAILOR_CV_DIR  — where to save tailored CVs (default: ~/linkedin-jobs/tailored/)
"""

import json
import os
import re
import sys
from collections import Counter
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

# ═══════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════
OUTPUT_DIR = Path(os.environ.get(
    "TAILOR_CV_DIR",
    Path(os.environ.get("LINKEDIN_OUTPUT_DIR", Path.home() / "linkedin-jobs")) / "tailored"
))

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/126.0.0.0 Safari/537.36",
}

# ═══════════════════════════════════════════════════════════════
# SKILL LEXICON — categorized keywords for extraction
# ═══════════════════════════════════════════════════════════════

# Tools & platforms commonly found in data job descriptions
TECH_TOOLS = {
    "bigquery", "snowflake", "redshift", "databricks", "spark", "pyspark",
    "airflow", "prefect", "dagster", "dbt", "looker", "tableau", "power bi",
    "powerbi", "looker studio", "data studio", "google analytics", "ga4",
    "mode", "metabase", "sigma", "hex", "jupyter", "colab",
    "docker", "kubernetes", "k8s", "terraform", "git", "github", "gitlab",
    "aws", "gcp", "azure", "s3", "ec2", "lambda", "cloud functions",
    "postgres", "postgresql", "mysql", "mongodb", "redis", "elasticsearch",
    "kafka", "pub/sub", "pubsub", "segment", "fivetran", "stitch", "airbyte",
    "hightouch", "census", "rudderstack", "mixpanel", "amplitude",
    "excel", "sheets", "google sheets", "notion", "confluence", "jira",
    "slack", "teams", "linear", "asana", "clickup",
    "hadoop", "hive", "presto", "trino", "flink", "beam", "dataflow",
    "nekt", "lakehouse", "delta lake", "iceberg", "hudi",
}

# Programming languages and query languages
LANGUAGES = {
    "python", "sql", "scala", "java", "golang", "rust",
    "javascript", "typescript", "bash", "shell", "ruby", "julia",
    "html", "yaml", "json", "xml",
}

# Python libraries / frameworks
PYTHON_LIBS = {
    "pandas", "numpy", "scikit-learn", "scikit", "sklearn", "tensorflow",
    "pytorch", "keras", "xgboost", "lightgbm", "catboost",
    "matplotlib", "seaborn", "plotly", "bokeh", "streamlit", "dash",
    "fastapi", "flask", "django", "pydantic", "sqlalchemy", "alembic",
    "great expectations", "soda", "dlt", "meltano",
    "langchain", "llamaindex", "transformers", "huggingface", "spacy",
    "nltk", "openai", "anthropic", "claude", "chatgpt", "llm",
}

# Data / analytics concepts
DATA_CONCEPTS = {
    "etl", "elt", "pipeline", "data pipeline", "data warehouse", "data lake",
    "lakehouse", "medallion", "bronze", "silver", "gold",
    "data modeling", "dimensional modeling", "star schema", "snowflake schema",
    "slowly changing dimension", "scd", "cdc", "change data capture",
    "data governance", "data catalog", "data lineage", "data quality",
    "data mesh", "data fabric", "data contract", "data product",
    "ab testing", "a/b test", "experimentation", "hypothesis testing",
    "statistical", "statistics", "regression", "classification", "clustering",
    "forecasting", "time series", "anomaly detection",
    "dashboard", "reporting", "kpi", "metric", "okr",
    "business intelligence", "bi", "analytics", "advanced analytics",
    "machine learning", "ml", "deep learning", "ai", "artificial intelligence",
    "generative ai", "genai", "llm", "rag", "vector database",
    "nlp", "natural language", "computer vision", "recommender",
    "data engineering", "analytics engineering", "data science",
    "data analysis", "data architecture", "data platform",
    "data strategy", "data-driven", "data literate", "data literacy",
    "sql", "nosql", "dataframe", "data wrangling", "data cleaning",
    "data ingestion", "data extraction", "data transformation", "data loading",
    "orchestration", "monitoring", "alerting", "observability",
    "ci/cd", "devops", "mlops", "dataops", "gitops",
}

# Soft skills / management
SOFT_SKILLS = {
    "leadership", "management", "mentoring", "coaching", "stakeholder",
    "stakeholder management", "cross-functional", "collaboration",
    "communication", "presentation", "storytelling", "data storytelling",
    "client-facing", "client management", "consulting", "advisory",
    "project management", "agile", "scrum", "kanban", "sprint",
    "roadmap", "strategy", "strategic", "vision", "execution",
    "problem solving", "critical thinking", "analytical", "detail-oriented",
    "team building", "hiring", "team lead", "tech lead",
}

# Seniority markers
SENIORITY = {
    "senior", "sênior", "sr.", "lead", "tech lead", "staff", "principal",
    "manager", "head", "director", "vp", "chief", "executive",
    "mid-level", "mid level", "junior", "júnior", "jr.", "intern", "associate",
}

# ═══════════════════════════════════════════════════════════════
# CV PARSING
# ═══════════════════════════════════════════════════════════════

def parse_cv_sections(md_text):
    """Parse a CV markdown file into named sections.

    Returns dict: section_name → full text of that section.
    Sections are delimited by ## headers.
    """
    sections = {}
    current_section = "_header"
    current_lines = []

    for line in md_text.split("\n"):
        if line.startswith("## "):
            if current_lines:
                sections[current_section] = "\n".join(current_lines).strip()
            current_section = line[3:].strip().lower()
            current_lines = []
        else:
            current_lines.append(line)

    if current_lines:
        sections[current_section] = "\n".join(current_lines).strip()

    return sections


def extract_cv_keywords(cv_text):
    """Extract all meaningful keywords from a CV.

    Returns:
      tools: set of tool/platform names found
      concepts: set of data/analytics concepts found
      soft: set of soft skills found
    """
    text_lower = cv_text.lower()

    tools = {t for t in TECH_TOOLS | LANGUAGES | PYTHON_LIBS
             if _word_match(t, text_lower)}
    concepts = {c for c in DATA_CONCEPTS if _word_match(c, text_lower)}
    soft = {s for s in SOFT_SKILLS if _word_match(s, text_lower)}

    return tools, concepts, soft


# Portuguese → English keyword mappings for bilingual matching
PT_TO_EN = {
    # Soft skills
    "liderança": "leadership",
    "liderar": "leadership",
    "liderei": "leadership",
    "gestão": "management",
    "gerenciamento": "management",
    "gerenciei": "management",
    "mentoria": "mentoring",
    "comunicação": "communication",
    "colaboração": "collaboration",
    "apresentação": "presentation",
    "estratégia": "strategy",
    "estratégico": "strategy",
    "resolução de problemas": "problem solving",
    "pensamento crítico": "critical thinking",
    "analítico": "analytical",
    "equipe": "team building",
    "contratação": "hiring",
    "ágeis": "agile",
    "ágil": "agile",
    "scrum": "scrum",
    "kanban": "kanban",
    "stakeholders": "stakeholder management",
    "partes interessadas": "stakeholder management",
    "cross-functional": "collaboration",
    "multidisciplinar": "collaboration",
    "cliente": "client-facing",
    "clientes": "client-facing",
    # Tools & concepts
    "aprendizado de máquina": "machine learning",
    "aprendizagem de máquina": "machine learning",
    "inteligência artificial": "ai",
    "ia generativa": "generative ai",
    "ia": "ai",
    "banco de dados": "data warehouse",
    "bases de dados": "data warehouse",
    "modelagem": "data modeling",
    "modelagem de dados": "data modeling",
    "transformação": "data transformation",
    "orquestração": "orchestration",
    "governança": "data governance",
    "governança de dados": "data governance",
    "qualidade de dados": "data quality",
    "catálogo": "data catalog",
    "linhagem": "data lineage",
    "painel": "dashboard",
    "painéis": "dashboard",
    "dashboards": "dashboard",
    "relatórios": "reporting",
    "experimentação": "ab testing",
    "teste a/b": "ab testing",
    "previsão": "forecasting",
    "séries temporais": "time series",
    "estatística": "statistics",
    "regressão": "regression",
    "classificação": "classification",
    "clusterização": "clustering",
    "visualização": "data storytelling",
    "extração": "data extraction",
    "ingestão": "data ingestion",
    "carregamento": "data loading",
    "limpeza": "data cleaning",
    "integração": "data integration",
    "conectores": "data integration",
    "automação": "orchestration",
    "automatização": "orchestration",
    "pipeline": "data pipeline",
    "pipelines": "data pipeline",
    "monitoramento": "monitoring",
    "alertas": "alerting",
    "observabilidade": "observability",
    "devops": "devops",
    "mlops": "mlops",
    "ci/cd": "ci/cd",
    "agentes": "ai",
    "agentes de ia": "ai",
    "engenharia de prompts": "nlp",
    "contextualização": "nlp",
    "ia": "ai",
    "llm": "llm",
    "rag": "rag",
    "vetorial": "vector database",
}


def _word_match(keyword, text):
    """Check if keyword appears as a word/phrase in text.

    Handles:
    - Multi-word keywords (e.g. 'power bi' matches 'powerbi')
    - Bilingual matching (Portuguese CV vs English job descriptions)
    - Word-boundary matching for short keywords (to avoid 'r' matching inside 'query')
    """
    kw_lower = keyword.lower()
    text_lower = text.lower()

    # Normalize: remove spaces, hyphens, slashes for substring matching
    kw_clean = kw_lower.replace(" ", "").replace("-", "").replace("/", "")
    text_clean = text_lower.replace(" ", "").replace("-", "").replace("/", "")

    # Direct match
    if kw_clean in text_clean:
        # For short keywords (<=2 chars), require word boundaries
        if len(kw_clean) <= 2:
            pattern = r'(?<![a-z])' + re.escape(kw_lower) + r'(?![a-z])'
            return bool(re.search(pattern, text_lower))
        return True

    # Bilingual: check if any Portuguese word maps TO this English keyword
    # and that Portuguese word appears in the text
    for pt_word, en_word in PT_TO_EN.items():
        if en_word.lower() == kw_lower:
            pt_clean = pt_word.replace(" ", "").replace("-", "")
            if pt_clean in text_clean:
                return True

    # Also check the keyword itself as a Portuguese word mapping to English
    # (e.g. if someone writes "machine learning" looking for "aprendizado de máquina")
    en_from_pt = PT_TO_EN.get(kw_lower)
    if en_from_pt:
        en_clean = en_from_pt.replace(" ", "").replace("-", "").replace("/", "")
        if en_clean in text_clean:
            return True

    return False


# ═══════════════════════════════════════════════════════════════
# JOB DESCRIPTION PARSING
# ═══════════════════════════════════════════════════════════════

def parse_job_description(text):
    """Extract structured requirements from a job description.

    Returns:
      title: detected job title
      seniority: detected seniority level
      tools: tools/platforms mentioned
      concepts: data concepts mentioned
      soft: soft skills mentioned
      must_have: sentences that look like requirements
      nice_to_have: sentences that look like nice-to-haves
    """
    text_lower = text.lower()

    # Tools, concepts, soft skills
    tools = {t for t in TECH_TOOLS | LANGUAGES | PYTHON_LIBS
             if _word_match(t, text_lower)}
    concepts = {c for c in DATA_CONCEPTS if _word_match(c, text_lower)}
    soft = {s for s in SOFT_SKILLS if _word_match(s, text_lower)}

    # Seniority detection
    seniority = "unknown"
    for s in ["senior", "sênior", "sr.", "lead", "staff", "principal"]:
        if _word_match(s, text_lower):
            seniority = "senior+"
            break
    if seniority == "unknown":
        for s in ["manager", "head", "director"]:
            if _word_match(s, text_lower):
                seniority = "manager+"
                break
    if seniority == "unknown":
        for s in ["mid-level", "mid level", "pleno", "associate"]:
            if _word_match(s, text_lower):
                seniority = "mid"
                break
    if seniority == "unknown":
        for s in ["junior", "júnior", "jr.", "intern"]:
            if _word_match(s, text_lower):
                seniority = "junior"
                break

    # Requirement sentences
    must_have = []
    nice_to_have = []

    sentences = re.split(r'[.;!?]\s+', text)
    for sent in sentences:
        sent_lower = sent.lower().strip()
        if len(sent_lower) < 20:
            continue
        # Nice-to-have indicators
        if any(w in sent_lower for w in ["nice to have", "bonus", "preferred",
                                           "a plus", "good to have", "differential"]):
            nice_to_have.append(sent.strip())
        # Must-have indicators
        elif any(w in sent_lower for w in ["required", "must have", "must-have",
                                            "you will", "you'll", "responsibilities",
                                            "qualifications", "requirements",
                                            "experience in", "experience with",
                                            "proven", "strong", "expert",
                                            "knowledge of", "proficiency",
                                            "familiarity with"]):
            must_have.append(sent.strip())

    return {
        "tools": tools,
        "concepts": concepts,
        "soft": soft,
        "seniority": seniority,
        "must_have": must_have[:15],      # cap to avoid flooding
        "nice_to_have": nice_to_have[:10],
    }


# ═══════════════════════════════════════════════════════════════
# MATCH ANALYSIS
# ═══════════════════════════════════════════════════════════════

def compute_match(cv_keywords, job_reqs):
    """Compare CV keywords against job requirements.

    Returns dict with match %, matched items, gaps, etc.
    """
    cv_tools, cv_concepts, cv_soft = cv_keywords

    # Combined "hard skills" = tools + concepts
    cv_hard = cv_tools | cv_concepts
    job_hard = job_reqs["tools"] | job_reqs["concepts"]

    matched_hard = cv_hard & job_hard
    gaps_hard = job_hard - cv_hard

    matched_soft = cv_soft & job_reqs["soft"]
    gaps_soft = job_reqs["soft"] - cv_soft

    # Scores
    hard_total = len(job_hard) or 1  # avoid div by zero
    soft_total = len(job_reqs["soft"]) or 1

    hard_pct = int(100 * len(matched_hard) / hard_total)
    soft_pct = int(100 * len(matched_soft) / soft_total)

    # Overall (hard skills weighted 70%, soft 30%)
    overall = int(0.7 * hard_pct + 0.3 * soft_pct)

    return {
        "overall": overall,
        "hard_match_pct": hard_pct,
        "soft_match_pct": soft_pct,
        "matched_hard": matched_hard,
        "gaps_hard": gaps_hard,
        "matched_soft": matched_soft,
        "gaps_soft": gaps_soft,
        "seniority": job_reqs["seniority"],
    }


# ═══════════════════════════════════════════════════════════════
# TAILORED CV GENERATION
# ═══════════════════════════════════════════════════════════════

def generate_tailored_cv(cv_text, job_reqs, match, job_title, job_company):
    """Generate a keyword-optimized CV for a specific job.

    This does NOT invent skills or experience. It:
    1. Reorders sections to emphasize matching experience
    2. Highlights matching keywords (with comments)
    3. Suggests keyword additions where the CV has evidence
    4. Flags genuine gaps

    Returns the tailored CV as markdown text.
    """
    cv_sections = parse_cv_sections(cv_text)

    # Find the most relevant experience blocks
    # Reorder to put matching experience first
    exp_section = cv_sections.get("experiência profissional",
                                   cv_sections.get("professional experience", ""))

    # Extract keywords the CV already HAS that match this job
    matched_keywords = match["matched_hard"] | match["matched_soft"]
    gaps_keywords = match["gaps_hard"] | match["gaps_soft"]

    # Build a compatibility header
    lines = []
    lines.append(f"# Tailored CV — {job_title}")
    lines.append(f"")
    lines.append(f"> **Target:** {job_title} at {job_company}")
    lines.append(f"> **Compatibility:** {match['overall']}/100 "
                 f"(hard skills {match['hard_match_pct']}%, soft {match['soft_match_pct']}%)")
    lines.append(f"> **Generated for:** {job_company} — tailor this further before submitting")
    lines.append(f"")

    # Gap warning if score is low
    if match["overall"] < 40:
        lines.append(f"### ⚠️ Low Compatibility Warning")
        lines.append(f"")
        lines.append(f"This CV has significant gaps for this role. The gaps below represent "
                     f"skills the job asks for that are not evident in your CV. **Only add them "
                     f"if you genuinely have that experience.** Never fabricate skills.")
        lines.append(f"")

    # ═══ HEADLINE ═══
    headline_key = None
    for k in cv_sections:
        if "headline" in k or "posicionamento" in k:
            headline_key = k
            break

    if headline_key:
        lines.append(f"## Headline")
        lines.append(f"")
        # Suggest tailoring headline to include top matching keywords
        top_matches = sorted(matched_keywords)[:5]
        if top_matches:
            lines.append(f"*Consider adding these matching keywords to your headline: "
                         f"{', '.join(top_matches)}*")
        lines.append(f"")
        lines.append(cv_sections[headline_key])
        lines.append(f"")

    # ═══ PROFILE / SUMMARY ═══
    profile_key = None
    for k in cv_sections:
        if "perfil" in k or "profile" in k or "summary" in k:
            profile_key = k
            break

    if profile_key:
        lines.append(f"## Professional Profile")
        lines.append(f"")
        # Note: inject 2-3 matching keywords that are already in the CV
        injectable = [kw for kw in sorted(matched_keywords)
                      if kw in cv_text.lower()][:3]
        if injectable:
            lines.append(f"*Keywords to emphasize: {', '.join(injectable)}*")
        lines.append(f"")
        lines.append(cv_sections[profile_key])
        lines.append(f"")

    # ═══ EXPERIENCE ═══
    lines.append(f"## Professional Experience")
    lines.append(f"")

    # Score each experience block by keyword overlap with job
    if exp_section:
        blocks = _split_experience_blocks(exp_section)
        scored_blocks = []
        for block_title, block_text in blocks:
            score = sum(1 for kw in matched_keywords if _word_match(kw, block_text.lower()))
            scored_blocks.append((score, block_title, block_text))

        # Sort by relevance (highest score first)
        scored_blocks.sort(key=lambda x: x[0], reverse=True)

        for score, block_title, block_text in scored_blocks:
            lines.append(f"### {block_title}")
            lines.append(f"")
            if score >= 3:
                lines.append(f"*✅ Strong match — {score} matching keywords*")
            elif score >= 1:
                lines.append(f"*⚠️ Partial match — {score} matching keywords*")
            else:
                lines.append(f"*⬜ Low relevance for this role*")
            lines.append(f"")
            lines.append(block_text)
            lines.append(f"")
    else:
        lines.append(cv_sections.get("experiência profissional",
                                      cv_sections.get("professional experience",
                                                       "*No experience section found*")))
        lines.append(f"")

    # ═══ SKILLS ═══
    lines.append(f"## Skills")
    lines.append(f"")

    # Split into matching vs non-matching, keep both but highlight matches
    skills_key = None
    for k in cv_sections:
        if "habilidade" in k or "skill" in k:
            if "técnica" in k.lower() or "technical" in k.lower():
                skills_key = k
                break
    if not skills_key:
        for k in cv_sections:
            if "habilidade" in k or "skill" in k:
                skills_key = k
                break

    if skills_key:
        lines.append(cv_sections[skills_key])
        lines.append(f"")
    else:
        # Build skills section from matched keywords
        lines.append(f"### Matching skills for this role")
        lines.append(f"")
        for kw in sorted(matched_keywords):
            lines.append(f"- {kw}")
        lines.append(f"")

    # ═══ TOOLS ═══
    tools_key = None
    for k in cv_sections:
        if "ferramenta" in k or "tool" in k:
            tools_key = k
            break

    if tools_key:
        lines.append(f"## Tools & Technologies")
        lines.append(f"")
        cv_tools_text = cv_sections[tools_key]
        # Highlight which tools match the job
        matching_tools_in_cv = []
        for tool in sorted(matched_keywords):
            if _word_match(tool, cv_tools_text.lower()):
                matching_tools_in_cv.append(tool)
        if matching_tools_in_cv:
            lines.append(f"*Matching: {', '.join(matching_tools_in_cv)}*")
        lines.append(f"")
        lines.append(cv_tools_text)
        lines.append(f"")

    # ═══ GAPS ═══
    if gaps_keywords:
        lines.append(f"## ⚠️ Identified Gaps")
        lines.append(f"")
        lines.append(f"These keywords appear in the job description but are **not evident** "
                     f"in your CV. Only add them if you genuinely have that experience.")
        lines.append(f"")
        for gap in sorted(gaps_keywords):
            lines.append(f"- {gap}")
        lines.append(f"")

    # ═══ REMAINING SECTIONS ═══
    # Pass through: education, certifications, languages — unchanged
    passthrough_sections = ["formação", "education", "certificações", "certifications",
                            "certificações e formação complementar",
                            "idiomas", "languages", "publicações", "publications",
                            "informações de contato", "contact", "contact information"]

    for section_name, section_text in cv_sections.items():
        if any(p in section_name.lower() for p in passthrough_sections):
            # Avoid duplicates — skip if already included above
            already_included = {headline_key, profile_key, skills_key, tools_key,
                                "experiência profissional", "professional experience"}
            if section_name not in already_included:
                original_header = _find_original_header(cv_text, section_name)
                lines.append(f"## {original_header}")
                lines.append(f"")
                lines.append(section_text)
                lines.append(f"")

    return "\n".join(lines)


def _split_experience_blocks(exp_text):
    """Split experience section into per-role blocks.

    Returns list of (role_title, block_text).
    """
    blocks = []
    current_title = ""
    current_lines = []

    for line in exp_text.split("\n"):
        if line.startswith("### "):
            if current_title and current_lines:
                blocks.append((current_title, "\n".join(current_lines).strip()))
            current_title = line[4:].strip()
            current_lines = [line]
        else:
            current_lines.append(line)

    if current_title and current_lines:
        blocks.append((current_title, "\n".join(current_lines).strip()))

    if not blocks:
        # No ### headers — treat entire section as one block
        return [("Experience", exp_text)]

    return blocks


def _find_original_header(cv_text, section_lower):
    """Find the original (cased) header for a section."""
    for line in cv_text.split("\n"):
        if line.startswith("## ") and line[3:].strip().lower() == section_lower:
            return line[3:].strip()
    return section_lower.title()


# ═══════════════════════════════════════════════════════════════
# LLM PROMPT GENERATION
# ═══════════════════════════════════════════════════════════════

def generate_llm_prompt(cv_text, job_title, job_company, job_description, match):
    """Generate a structured prompt for an LLM to deeply tailor the CV.

    This prompt can be used with Hermes Agent, ChatGPT, Claude, or any LLM.
    It includes the full CV, job description, match analysis, and instructions.
    """
    gaps = sorted(match["gaps_hard"] | match["gaps_soft"])
    matched = sorted(match["matched_hard"] | match["matched_soft"])

    prompt = f"""You are a professional CV/resume writer specializing in data and analytics roles.

## Task
Tailor the following CV for this specific job, optimizing for both ATS scanning and human reading.

## Job
**Title:** {job_title}
**Company:** {job_company}
**Seniority:** {match['seniority']}

### Job Description
{job_description[:2000]}

## Match Analysis
**Overall Compatibility:** {match['overall']}/100
**Hard Skills Match:** {match['hard_match_pct']}% — already in CV: {', '.join(matched[:15])}
**Gaps (keywords in job but not evident in CV):** {', '.join(gaps[:15])}

## Rules
1. NEVER invent skills, experience, tools, or achievements. Only use what's in the CV.
2. Rephrase, reorder, and highlight existing content — do not fabricate.
3. If a job requirement has no evidence in the CV, mark it as a gap instead of faking it.
4. Mirror keywords from the job description where honestly supported by the CV.
5. Keep the CV concise — target 1-2 pages.
6. Use strong, concrete language. Avoid corporate filler.
7. Output the tailored CV in clean markdown format.

## Original CV
```markdown
{cv_text}
```

## Output Format
Return the tailored CV as markdown with these sections:
- Contact Info
- Headline (1 line, keyword-optimized)
- Professional Profile (3-5 lines)
- Professional Experience (reordered by relevance to this job)
- Skills
- Tools & Technologies
- Education
- Certifications
- Languages

After the CV, add a section:
## Tailoring Notes
- What was reordered and why
- Which keywords were emphasized
- Genuine gaps the candidate should address
"""

    return prompt


# ═══════════════════════════════════════════════════════════════
# JOB FETCHING
# ═══════════════════════════════════════════════════════════════

def fetch_job_from_linkedin(job_id):
    """Fetch job description from LinkedIn Guest API."""
    url = f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"
    try:
        req = Request(url, headers=HEADERS)
        with urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except (HTTPError, URLError, OSError) as e:
        print(f"Error fetching job {job_id}: {e}", file=sys.stderr)
        return None

    # Clean HTML
    text = re.sub(r'<[^>]+>', ' ', html)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def load_jobs_json(path):
    """Load jobs from a JSON file (scraper output format)."""
    data = json.loads(Path(path).read_text())
    if isinstance(data, list):
        return data
    return []


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

def cmd_analyze(cv_path, jobs_path):
    """Analyze CV against all jobs in jobs_new.json."""
    cv_text = Path(cv_path).read_text()
    cv_keywords = extract_cv_keywords(cv_text)

    jobs = load_jobs_json(jobs_path)
    if not jobs:
        print("No jobs found in JSON file.")
        return

    print(f"{'='*70}")
    print(f"  CV-Job Match Analysis")
    print(f"  CV: {cv_path}  |  Jobs: {len(jobs)} in {jobs_path}")
    print(f"{'='*70}\n")

    results = []
    for i, job in enumerate(jobs):
        title = job.get("title", "Untitled")
        company = job.get("company", "Unknown")
        desc = job.get("description", "")

        job_reqs = parse_job_description(title + " " + desc)
        match = compute_match(cv_keywords, job_reqs)

        results.append((match["overall"], title, company, match))
        print(f"  {i+1:>2}. [{match['overall']:>3}%] {title[:60]}")
        print(f"      {company[:50]}  |  Seniority: {job_reqs['seniority']}")
        if match["gaps_hard"]:
            gaps_show = sorted(match["gaps_hard"])[:5]
            print(f"      Gaps: {', '.join(gaps_show)}")
        print()

    # Summary
    results.sort(key=lambda x: x[0], reverse=True)
    print(f"{'='*70}")
    print(f"  Top 5 matches:")
    for overall, title, company, _ in results[:5]:
        bar = "█" * (overall // 10) + "░" * (10 - overall // 10)
        print(f"  [{bar}] {overall:>3}% — {title[:55]} @ {company[:30]}")
    print(f"{'='*70}")


def cmd_tailor(cv_path, job_data=None, job_id=None, job_url=None, jobs_json=None):
    """Tailor CV for a specific job."""
    cv_text = Path(cv_path).read_text()
    cv_keywords = extract_cv_keywords(cv_text)

    # Determine job source
    job_title = "Unknown"
    job_company = "Unknown"
    job_description = ""

    if job_id and jobs_json:
        # Load from scraper output
        jobs = load_jobs_json(jobs_json)
        target = next((j for j in jobs if j.get("id") == job_id), None)
        if target:
            job_title = target.get("title", "Unknown")
            job_company = target.get("company", "Unknown")
            job_description = target.get("description", "")
        else:
            print(f"Job ID {job_id} not found in {jobs_json}", file=sys.stderr)
            sys.exit(1)

    elif job_id:
        # Fetch from LinkedIn API
        print(f"Fetching job {job_id} from LinkedIn...", file=sys.stderr)
        desc = fetch_job_from_linkedin(job_id)
        if not desc:
            print("Failed to fetch job description.", file=sys.stderr)
            sys.exit(1)
        job_description = desc
        job_title = f"LinkedIn Job {job_id}"

    elif job_data:
        # Direct JSON/string input
        if isinstance(job_data, dict):
            job_title = job_data.get("title", "Unknown")
            job_company = job_data.get("company", "Unknown")
            job_description = job_data.get("description", "")
        else:
            job_description = str(job_data)

    elif job_url:
        print("URL mode: paste the job description below (Ctrl+D to finish):", file=sys.stderr)
        job_description = sys.stdin.read()

    else:
        print("Provide job via --job-id, --job-url, --json + --job-id, or stdin.", file=sys.stderr)
        sys.exit(1)

    if not job_description.strip():
        print("Error: empty job description.", file=sys.stderr)
        sys.exit(1)

    # Analyze
    print(f"Analyzing: {job_title} @ {job_company}...", file=sys.stderr)
    job_reqs = parse_job_description(job_title + " " + job_description)
    match = compute_match(cv_keywords, job_reqs)

    # Generate tailored CV
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    safe_title = re.sub(r'[^a-zA-Z0-9_-]', '_', job_title)[:40]
    safe_company = re.sub(r'[^a-zA-Z0-9_-]', '_', job_company)[:20]
    out_name = f"cv_tailored_{safe_title}_{safe_company}.md"

    tailored_cv = generate_tailored_cv(cv_text, job_reqs, match, job_title, job_company)
    out_path = OUTPUT_DIR / out_name
    out_path.write_text(tailored_cv)

    # Generate LLM prompt
    prompt_name = f"prompt_{safe_title}_{safe_company}.md"
    prompt_path = OUTPUT_DIR / prompt_name
    llm_prompt = generate_llm_prompt(cv_text, job_title, job_company, job_description, match)
    prompt_path.write_text(llm_prompt)

    # Print summary
    print(f"""
{'='*70}
  CV Tailored for: {job_title}
  Company: {job_company}
  Seniority: {match['seniority']}
  Compatibility: {match['overall']}/100
{'='*70}

## Match Breakdown
  Hard skills: {match['hard_match_pct']}% ({len(match['matched_hard'])} matched, {len(match['gaps_hard'])} gaps)
  Soft skills: {match['soft_match_pct']}% ({len(match['matched_soft'])} matched, {len(match['gaps_soft'])} gaps)

## Matching Keywords
  {', '.join(sorted(match['matched_hard'] | match['matched_soft'])[:20]) or 'None'}

## Gaps (in job, not evident in CV)
  {', '.join(sorted(match['gaps_hard'] | match['gaps_soft'])[:20]) or 'None'}

## Files Generated
  Tailored CV:  {out_path}
  LLM Prompt:   {prompt_path}

## Next Steps
  1. Review {out_path} — check that no facts were altered
  2. For deeper tailoring, feed {prompt_path} to an LLM:
     - Hermes Agent: just drag the file into a chat
     - ChatGPT/Claude: copy-paste the prompt
     - CLI: cat {prompt_path} | your-llm-tool
  3. Edit the tailored CV further before submitting
""")


def print_usage():
    print("""Usage:
  python3 tailor_cv.py analyze cv.md [jobs_new.json]
  python3 tailor_cv.py tailor cv.md --job-id LINKEDIN_ID
  python3 tailor_cv.py tailor cv.md --json jobs_new.json --job-id LINKEDIN_ID
  python3 tailor_cv.py tailor cv.md --job-url URL

Examples:
  # Compare your CV against all scraped jobs
  python3 tailor_cv.py analyze cv.md ~/linkedin-jobs/jobs_new.json

  # Tailor CV for a specific LinkedIn job (fetches description via API)
  python3 tailor_cv.py tailor cv.md --job-id 4429960220

  # Tailor CV using job from scraper output
  python3 tailor_cv.py tailor cv.md --json ~/linkedin-jobs/jobs_new.json --job-id 4429960220

  # Tailor CV for a job at a specific URL (paste description)
  python3 tailor_cv.py tailor cv.md --job-url https://example.com/job

Configuration:
  TAILOR_CV_DIR  — where to save tailored CVs (default: ~/linkedin-jobs/tailored/)
  LINKEDIN_OUTPUT_DIR — base directory for scraper outputs
""")


def main():
    args = sys.argv[1:]

    if not args:
        print_usage()
        sys.exit(0)

    cmd = args[0].lower()

    if cmd == "analyze":
        if len(args) < 2:
            print("Error: cv.md path required.", file=sys.stderr)
            print_usage()
            sys.exit(1)
        cv_path = args[1]
        jobs_path = args[2] if len(args) > 2 else str(
            Path(os.environ.get("LINKEDIN_OUTPUT_DIR", Path.home() / "linkedin-jobs"))
            / "jobs_new.json"
        )
        cmd_analyze(cv_path, jobs_path)

    elif cmd == "tailor":
        if len(args) < 2:
            print("Error: cv.md path required.", file=sys.stderr)
            print_usage()
            sys.exit(1)

        cv_path = args[1]
        job_id = None
        job_url = None
        jobs_json = None
        job_data = None

        i = 2
        while i < len(args):
            if args[i] == "--job-id":
                job_id = args[i + 1]
                i += 2
            elif args[i] == "--job-url":
                job_url = args[i + 1]
                i += 2
            elif args[i] == "--json":
                jobs_json = args[i + 1]
                i += 2
            elif args[i] == "--job-data":
                job_data = args[i + 1]
                i += 2
            else:
                i += 1

        # If no job source specified, try reading from stdin
        if not job_id and not job_url and not job_data:
            print("Reading job description from stdin (Ctrl+D to finish)...", file=sys.stderr)
            job_data = sys.stdin.read()

        cmd_tailor(cv_path, job_data=job_data, job_id=job_id,
                   job_url=job_url, jobs_json=jobs_json)

    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        print_usage()
        sys.exit(1)


if __name__ == "__main__":
    main()

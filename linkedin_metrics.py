#!/usr/bin/env python3
"""Metrics dashboard for the LinkedIn job scraper.

Run this to see:
- How many jobs are tracked (IDs + title/company keys)
- Yield per keyword (runs, jobs found, last time it found something)
- Recent cron runs (date, job count, first job title)
- MD file stats (job count, file size)

Usage:
    python3 linkedin_metrics.py

Configuration:
    LINKEDIN_OUTPUT_DIR: where output files live (default: ~/linkedin-jobs)
    LINKEDIN_CRON_OUTPUT_DIR: optional, dir with agent's .md outputs
"""
import json
import os
import re
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(os.environ.get("LINKEDIN_OUTPUT_DIR", Path.home() / "linkedin-jobs"))
CRON_DIR = Path(os.environ["LINKEDIN_CRON_OUTPUT_DIR"]) if os.environ.get("LINKEDIN_CRON_OUTPUT_DIR") else None
SEEN_JSON = BASE_DIR / "seen.json"
KW_FILE = BASE_DIR / "keywords.json"
MD_FILE = BASE_DIR / "jobs.md"


def main():
    now = datetime.now()
    print(f"{'='*60}")
    print(f"  LinkedIn Job Scraper — Metrics Dashboard")
    print(f"  {now.strftime('%d/%m/%Y %H:%M')}")
    print(f"{'='*60}\n")

    # --- Tracked jobs ---
    print(f"## Database")
    try:
        seen = json.loads(SEEN_JSON.read_text())
        print(f"  Tracked IDs: {seen.get('count_ids', 0)}")
        print(f"  Title+Company keys: {seen.get('count_keys', 0)}")
        print(f"  Last update: {seen.get('updated_at', 'N/A')[:16]}")
    except Exception:
        print("  seen.json not found (run the scraper first)")

    # --- Keyword stats ---
    print(f"\n## Yield per Keyword")
    try:
        kw_data = json.loads(KW_FILE.read_text())
        kw_stats = kw_data.get("keywords", {})
        if kw_stats:
            sorted_kw = sorted(kw_stats.items(),
                               key=lambda x: x[1].get("total_new", 0),
                               reverse=True)
            print(f"  {'Keyword':<30} {'Runs':>5} {'Yield':>6} {'Last New':>12}")
            print(f"  {'-'*30} {'-'*5} {'-'*6} {'-'*12}")
            for kw, ks in sorted_kw:
                runs = ks.get("total_runs", 0)
                total_new = ks.get("total_new", 0)
                last_new = ks.get("last_new") or "never"
                if last_new != "never":
                    last_new = last_new[:10]
                yield_pct = f"{total_new/runs:.1f}/run" if runs >= 3 else f"{total_new} total"
                print(f"  {kw:<30} {runs:>5} {total_new:>5} ({yield_pct:>9}) {last_new:>12}")
        else:
            print("  No data yet (first run collects stats)")

        pruned = kw_data.get("pruned", [])
        if pruned:
            print(f"\n  Pruned keywords: {len(pruned)}")
            for p in pruned[-5:]:
                print(f"    - '{p['keyword']}' ({p['runs']} runs, {p['yield']} jobs)")
    except Exception:
        print("  keywords.json not found")

    # --- Cron runs ---
    print(f"\n## Recent Runs")
    if CRON_DIR and CRON_DIR.exists():
        files = sorted(CRON_DIR.glob("*.md"), reverse=True)[:10]
        print(f"  {'Date':>12} {'Jobs':>6} {'First job title'}")
        print(f"  {'-'*12} {'-'*6} {'-'*40}")
        for f in files:
            date_str = f.stem[:10]
            time_str = f.stem[11:] if len(f.stem) > 10 else ""
            try:
                content = f.read_text()
                vagas_match = re.search(r'(\d+) (?:jobs?|vagas)', content, re.IGNORECASE)
                n_vagas = vagas_match.group(1) if vagas_match else "?"
                title_match = re.search(r'\*\d+\.\s*⭐+\s+(?:🔥\s+)?(.+?)\*\*', content)
                first_title = title_match.group(1)[:40] if title_match else "-"
                placeholders = ("título da vaga", "titulo da vaga", "job title", "title")
                if first_title.lower() in placeholders:
                    first_title = "(template)"
                print(f"  {date_str} {time_str:>6} {n_vagas:>6} {first_title}")
            except Exception:
                print(f"  {f.stem} {'?':>6} {'(read error)':>40}")
        print(f"  Total runs: {len(list(CRON_DIR.glob('*.md')))}")
    else:
        print("  CRON_OUTPUT_DIR not configured or not found")

    # --- MD stats ---
    print(f"\n## MD File")
    try:
        content = MD_FILE.read_text()
        n_blocks = len(re.findall(r'^## ', content, re.MULTILINE))
        n_ids = len(set(re.findall(r'linkedin\.com/jobs/view/(\d+)', content)))
        lines = content.count('\n')
        print(f"  Jobs in MD: {n_blocks} (unique IDs: {n_ids})")
        print(f"  Size: {len(content)//1024}KB, {lines} lines")
    except Exception:
        print("  jobs.md not found")

    print(f"\n{'='*60}")


if __name__ == "__main__":
    main()

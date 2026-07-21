"""Aplica manualmente a uma vaga específica via pipeline do candidatura-agent.

Uso:
  .venv/bin/python scripts/apply_manual.py \
    --url 'https://jobs.ashbyhq.com/siena/.../application' \
    --resume '/abs/path/cv.pdf' \
    --title 'Deployment Manager, AI Agents' --company 'Siena AI' --location 'Brazil (Remote)'
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

from candidatura_agent.browser import run_application
from candidatura_agent.db import Database


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--resume", required=True)
    ap.add_argument("--title", default="Vaga manual")
    ap.add_argument("--company", default="Empresa")
    ap.add_argument("--location", default="")
    ap.add_argument("--description", default="")
    ap.add_argument("--dry-run", action="store_true", help="Não envia, só preenche")
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[1]
    config = json.loads((root / "config.json").read_text())
    db = Database(root / config["database"])
    db.initialize()

    source_url = args.url
    apply_url = args.url
    resume = str(Path(args.resume).expanduser())
    if not Path(resume).exists():
        raise SystemExit(f"CV não encontrado: {resume}")

    job_id = db.upsert_job({
        "source_url": source_url,
        "apply_url": apply_url,
        "resume_path": resume,
        "title": args.title,
        "company": args.company,
        "location": args.location,
        "description": args.description,
        "ats": "ashby",
        "status": "qualified",
        "fit_score": 100,
        "fit_reasons": ["candidatura manual solicitada pelo usuário"],
        "blockers": [],
    })
    # forçar qualified + apply_url + resume_path (upsert pode não gravar tudo)
    db.set_job_assets(job_id, apply_url=apply_url, ats="ashby", resume_path=resume, company=args.company)
    with db.connect() as conn:
        conn.execute(
            "UPDATE jobs SET status='qualified', fit_score=100 WHERE id=?", (job_id,)
        )

    profile = json.loads((root / config["profile"]).read_text())
    profile["resume"] = resume  # garantir que o profile aponta para o CV desta vaga

    auto_submit = (not args.dry_run) and bool(config.get("auto_submit", False))
    allowed_ats = set(config.get("allowed_ats") if auto_submit else config.get("dry_run_allowed_ats", []))

    screenshot_dir = root / config.get("screenshot_dir", "reports/screenshots") / f"job-{job_id}"

    print(f"[apply_manual] job_id={job_id} auto_submit={auto_submit} ats_allowed={allowed_ats}")
    with sync_playwright() as pw:
        context = None
        profiles = config.get("browser_profiles", {})
        last_err = []
        for item in config.get("browser_candidates", []):
            name, exe = item["name"], item.get("executable_path")
            if exe and not Path(exe).exists():
                continue
            bp = root / profiles.get(name, f"data/browser-profile-{name}")
            bp.mkdir(parents=True, exist_ok=True)
            kw = {"headless": bool(config.get("headless", True))}
            if exe:
                kw["executable_path"] = exe
            try:
                context = pw.chromium.launch_persistent_context(str(bp), **kw)
                print(f"[apply_manual] browser usado: {name}")
                break
            except Exception as e:
                last_err.append(f"{name}: {type(e).__name__}: {e}")
        if context is None:
            raise SystemExit("Falha ao lançar browser: " + "; ".join(last_err))
        page = context.pages[0] if context.pages else context.new_page()
        result = run_application(
            page, apply_url, profile,
            auto_submit=auto_submit,
            allowed_ats=allowed_ats,
            screenshot_dir=screenshot_dir,
        )
        context.close()

    db.record_application(job_id, result.status, result.ats, result.blockers)
    print(json.dumps({
        "status": result.status,
        "ats": result.ats,
        "final_url": result.final_url,
        "blockers": result.blockers,
        "filled": result.filled,
        "screenshot": result.screenshot,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

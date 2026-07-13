"""Execução horária: ingestão, score, fila e automação opcional."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .browser import run_application
from .db import Database
from .ingest import ingest_linkedin_json
from .policy import assess_job


def _resolve(root: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else root / path


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    tmp.replace(path)


def _profile_for_job(profile: dict[str, Any], job: dict[str, Any]) -> dict[str, Any] | None:
    job_profile = dict(profile)
    if profile.get("resume_strategy") == "tailor_per_job":
        if not job.get("resume_path"):
            return None
        job_profile["resume"] = job["resume_path"]
    return job_profile


def run_pipeline(config: dict[str, Any], root: Path) -> dict[str, Any]:
    started = datetime.now()
    db = Database(_resolve(root, config["database"]))
    db.initialize()
    profile = json.loads(_resolve(root, config["profile"]).read_text())
    ingested = ingest_linkedin_json(db, _resolve(root, config["source_json"]))

    weights = db.learned_weights()
    qualified = 0
    rejected = 0
    for job in db.list_jobs():
        if job["status"] in ("submitted", "dry_run", "blocked"):
            continue
        assessment = assess_job(job, profile, weights)
        status = "qualified" if assessment.eligible else "rejected"
        db.update_assessment(job["id"], assessment.score, assessment.reasons, assessment.blockers, status)
        if assessment.eligible:
            qualified += 1
        else:
            rejected += 1

    processed = 0
    submitted = db.submitted_today()
    remaining = max(0, int(config.get("daily_limit", 10)) - submitted)
    if config.get("browser_enabled") and remaining:
        from playwright.sync_api import sync_playwright

        browser_profile = _resolve(root, config.get("browser_profile", "data/browser-profile"))
        browser_profile.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                str(browser_profile), headless=bool(config.get("headless", True))
            )
            page = context.pages[0] if context.pages else context.new_page()
            require_resume = profile.get("resume_strategy") == "tailor_per_job"
            for job in db.daily_queue(limit=remaining, require_resume=require_resume):
                job_profile = _profile_for_job(profile, job)
                if job_profile is None:
                    continue
                result = run_application(
                    page, job.get("apply_url") or job["source_url"], job_profile,
                    auto_submit=bool(config.get("auto_submit", False)),
                    allowed_ats=set(config.get("allowed_ats", [])),
                    screenshot_dir=_resolve(root, config.get("screenshot_dir", "reports/screenshots")),
                )
                db.record_application(job["id"], result.status, result.ats, result.blockers)
                processed += 1
            context.close()

    payload = {
        "status": "ok",
        "started_at": started.isoformat(timespec="seconds"),
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "ingested": ingested,
        "qualified": qualified,
        "rejected": rejected,
        "processed": processed,
        "submitted_today": db.submitted_today(),
        "daily_limit": int(config.get("daily_limit", 10)),
        "browser_enabled": bool(config.get("browser_enabled", False)),
        "auto_submit": bool(config.get("auto_submit", False)),
    }
    _write_json_atomic(_resolve(root, config["run_control"]), payload)
    return payload


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    config = json.loads((root / "config.json").read_text())
    result = run_pipeline(config, root)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()

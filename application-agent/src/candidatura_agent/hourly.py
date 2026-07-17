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
from .run_lock import exclusive_run_lock


def _resolve(root: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else root / path


def _browser_candidates(config: dict[str, Any]) -> list[tuple[str, str | None]]:
    """Return the browser launch order: Brave, Chrome, then bundled Chromium."""
    configured = config.get("browser_candidates")
    if configured:
        return [(item["name"], item.get("executable_path")) for item in configured]
    return [
        ("brave", "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"),
        ("chrome", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        ("chromium", None),
    ]


def _allowed_ats_for_run(config: dict[str, Any], *, auto_submit: bool) -> set[str]:
    key = "allowed_ats" if auto_submit else "dry_run_allowed_ats"
    values = config.get(key)
    if values is None:
        values = config.get("allowed_ats", [])
    return set(values)


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
    browser_used: str | None = None
    if config.get("browser_enabled"):
        from playwright.sync_api import sync_playwright

        require_resume = profile.get("resume_strategy") == "tailor_per_job"
        ready_jobs = db.daily_queue(require_resume=require_resume)
        if ready_jobs:
            with sync_playwright() as playwright:
                context = None
                launch_errors: list[str] = []
                profiles = config.get("browser_profiles", {})
                for browser_name, executable_path in _browser_candidates(config):
                    if executable_path and not Path(executable_path).exists():
                        launch_errors.append(f"{browser_name}: executable not found")
                        continue
                    profile_value = profiles.get(browser_name, f"data/browser-profile-{browser_name}")
                    browser_profile = _resolve(root, profile_value)
                    browser_profile.mkdir(parents=True, exist_ok=True)
                    kwargs: dict[str, Any] = {
                        "headless": bool(config.get("headless", True)),
                    }
                    if executable_path:
                        kwargs["executable_path"] = executable_path
                    try:
                        context = playwright.chromium.launch_persistent_context(
                            str(browser_profile), **kwargs
                        )
                        browser_used = browser_name
                        break
                    except Exception as exc:
                        launch_errors.append(f"{browser_name}: {type(exc).__name__}")
                if context is None:
                    raise RuntimeError("Browser launch failed: " + "; ".join(launch_errors))
                page = context.pages[0] if context.pages else context.new_page()
                for job in ready_jobs:
                    job_profile = _profile_for_job(profile, job)
                    if job_profile is None:
                        continue
                    auto_submit = bool(config.get("auto_submit", False))
                    result = run_application(
                        page, job.get("apply_url") or job["source_url"], job_profile,
                        auto_submit=auto_submit,
                        allowed_ats=_allowed_ats_for_run(config, auto_submit=auto_submit),
                        screenshot_dir=(
                            _resolve(root, config.get("screenshot_dir", "reports/screenshots"))
                            / f"job-{job['id']}"
                        ),
                    )
                    db.record_application(job["id"], result.status, result.ats, result.blockers)
                    processed += 1
                context.close()

    submitted_today = db.submitted_today()
    daily_target_min = int(config.get("daily_target_min", 10))

    payload = {
        "status": "ok",
        "started_at": started.isoformat(timespec="seconds"),
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "ingested": ingested,
        "qualified": qualified,
        "rejected": rejected,
        "processed": processed,
        "submitted_today": submitted_today,
        "daily_target_min": daily_target_min,
        "target_gap": max(0, daily_target_min - submitted_today),
        "target_met": submitted_today >= daily_target_min,
        "browser_enabled": bool(config.get("browser_enabled", False)),
        "auto_submit": bool(config.get("auto_submit", False)),
        "browser_used": browser_used,
    }
    _write_json_atomic(_resolve(root, config["run_control"]), payload)
    return payload


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    config = json.loads((root / "config.json").read_text())
    lock_path = _resolve(root, config.get("hourly_lock", "data/hourly.lock"))
    with exclusive_run_lock(lock_path) as acquired:
        if not acquired:
            print(json.dumps({"status": "skipped", "reason": "hourly_already_running"}))
            return
        result = run_pipeline(config, root)
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()

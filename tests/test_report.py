from datetime import datetime
from pathlib import Path

from candidatura_agent.db import Database
from candidatura_agent.report import build_daily_report


def test_report_contains_submitted_and_blocked_jobs(tmp_path: Path):
    db = Database(tmp_path / "state.db")
    db.initialize()
    submitted = db.upsert_job({"external_id": "1", "title": "Data Engineer", "company": "Acme", "location": "Brazil", "source_url": "https://x/1", "fit_score": 88, "status": "qualified"})
    blocked = db.upsert_job({"external_id": "2", "title": "BI Manager", "company": "Beta", "location": "São Paulo", "source_url": "https://x/2", "fit_score": 81, "status": "qualified"})
    db.record_application(submitted, "submitted", "greenhouse", [])
    db.record_application(blocked, "blocked", "workday", ["login"])

    report = build_daily_report(db, datetime.now().date())
    assert "Data Engineer" in report
    assert "BI Manager" in report
    assert "1 candidatura enviada" in report
    assert "1 bloqueada" in report
    assert "88/100" in report

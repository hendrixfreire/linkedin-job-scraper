from pathlib import Path

from candidatura_agent.dashboard import dashboard_snapshot
from candidatura_agent.db import Database


def test_dashboard_snapshot_exposes_queue_and_feedback(tmp_path: Path):
    db = Database(tmp_path / "state.db")
    db.initialize()
    job_id = db.upsert_job({
        "external_id": "1", "title": "Data Engineer", "company": "Acme",
        "location": "Brazil", "source_url": "https://x/1", "fit_score": 85,
        "status": "qualified",
    })
    db.add_feedback(job_id, "good", "aderente")

    payload = dashboard_snapshot(db, daily_target_min=10)

    assert payload["stats"]["qualified"] == 1
    assert payload["daily_target"] == {"minimum": 10, "submitted": 0, "gap": 10, "met": False, "unlimited": True}
    assert payload["jobs"][0]["title"] == "Data Engineer"
    assert payload["feedback"][0]["rating"] == "good"

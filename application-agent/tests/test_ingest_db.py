import json
import sqlite3
from pathlib import Path

import pytest

from candidatura_agent.db import Database
from candidatura_agent.ingest import ingest_linkedin_json


def test_ingest_is_idempotent(tmp_path: Path):
    source = tmp_path / "jobs.json"
    source.write_text(json.dumps([
        {"id": "1", "title": "Senior Data Engineer", "company": "Acme", "location": "Brazil", "url": "https://linkedin.com/jobs/view/1", "heuristic_score": 5},
        {"id": "2", "title": "BI Manager", "company": "Beta", "location": "São Paulo", "url": "https://linkedin.com/jobs/view/2", "heuristic_score": 4},
    ]))
    db = Database(tmp_path / "state.db")
    db.initialize()

    assert ingest_linkedin_json(db, source) == 2
    assert ingest_linkedin_json(db, source) == 0
    assert len(db.list_jobs()) == 2
    assert db.list_jobs()[0]["source_score"] == 100


def test_ingest_accepts_versioned_job_candidate_contract(tmp_path: Path):
    source = tmp_path / "job-candidate.v1.json"
    source.write_text(json.dumps({
        "contract": "job-candidate", "schema_version": 1,
        "produced_at": "2026-07-19T12:00:00Z",
        "jobs": [{
            "source": "linkedin", "source_job_id": "123",
            "source_url": "https://www.linkedin.com/jobs/view/123",
            "title": "Senior Data Engineer", "company": "Acme", "location": "Brazil",
            "work_mode": "remote", "posted_at": "2026-07-19",
            "description": "Python SQL", "source_score": 90,
            "collected_at": "2026-07-19T11:59:00Z",
        }],
    }))
    db = Database(tmp_path / "state.db")
    db.initialize()

    assert ingest_linkedin_json(db, source) == 1
    job = db.list_jobs()[0]
    assert job["external_id"] == "123"
    assert job["source_score"] == 90
    assert job["description"] == "Python SQL"


def test_daily_queue_has_no_default_cap_but_accepts_optional_batch_size(tmp_path: Path):
    db = Database(tmp_path / "state.db")
    db.initialize()
    for idx in range(15):
        db.upsert_job({
            "external_id": str(idx), "title": f"Senior Data Engineer {idx}",
            "company": f"Company {idx}", "location": "Brazil",
            "source_url": f"https://example.test/{idx}", "fit_score": 90,
            "status": "qualified",
        })

    assert len(db.daily_queue()) == 15
    assert len(db.daily_queue(limit=4)) == 4

    first = db.daily_queue(limit=1)[0]
    db.record_application(first["id"], "submitted", "greenhouse", [])
    assert db.submitted_today() == 1
    assert len(db.daily_queue()) == 14


def test_feedback_updates_learned_weights_without_touching_hard_filters(tmp_path: Path):
    db = Database(tmp_path / "state.db")
    db.initialize()
    job_id = db.upsert_job({
        "external_id": "feedback-1", "title": "Senior Analytics Engineer",
        "company": "Acme", "location": "Brazil",
        "source_url": "https://example.test/feedback-1", "fit_score": 90,
        "status": "qualified",
    })

    db.add_feedback(job_id, "good", "cargo muito aderente")

    weights = db.learned_weights()
    assert weights["analytics engineer"] > 0
    assert db.list_feedback()[0]["rating"] == "good"


def test_tailored_resume_assets_are_persisted_and_gate_queue(tmp_path: Path):
    db = Database(tmp_path / "state.db")
    db.initialize()
    job_id = db.upsert_job({
        "external_id": "tailored-1", "title": "Senior Analytics Engineer",
        "company": "Wellhub", "location": "Brazil",
        "source_url": "https://linkedin.com/jobs/view/tailored-1",
        "fit_score": 90, "status": "qualified",
    })

    assert db.daily_queue(limit=10, require_resume=True) == []
    assert db.cv_queue(limit=10)[0]["id"] == job_id

    db.set_job_assets(
        job_id,
        apply_url="https://job-boards.greenhouse.io/example/jobs/1",
        ats="greenhouse",
        resume_path="/tmp/cv-tailored.pdf",
        company="Wellhub",
    )

    queued = db.daily_queue(limit=10, require_resume=True)
    assert queued[0]["company"] == "Wellhub"
    assert queued[0]["resume_path"] == "/tmp/cv-tailored.pdf"
    assert queued[0]["apply_url"].startswith("https://job-boards.greenhouse.io/")
    assert db.cv_queue(limit=10) == []


def test_database_context_closes_sqlite_connection_after_operation(tmp_path: Path):
    db = Database(tmp_path / "state.db")
    db.initialize()

    with db.connect() as conn:
        assert conn.execute("SELECT 1").fetchone()[0] == 1

    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        conn.execute("SELECT 1")

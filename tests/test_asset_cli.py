from pathlib import Path

from candidatura_agent.asset_cli import enrich_descriptions, queue_payload, record_resolution_failure
from candidatura_agent.db import Database


HTML = '<div class="show-more-less-html__markup"><p>Python SQL BigQuery</p></div>'


def test_queue_payload_returns_only_operational_job_fields(tmp_path: Path):
    db = Database(tmp_path / "state.db")
    db.initialize()
    db.upsert_job({
        "external_id": "123", "title": "Senior Data Engineer", "company": "Acme",
        "location": "Brazil", "source_url": "https://www.linkedin.com/jobs/view/123",
        "description": "Python SQL", "status": "qualified", "fit_score": 90,
    })

    payload = queue_payload(db, limit=1)

    assert payload == [{
        "id": 1,
        "external_id": "123",
        "title": "Senior Data Engineer",
        "company": "Acme",
        "location": "Brazil",
        "source_url": "https://www.linkedin.com/jobs/view/123",
        "apply_url": None,
        "ats": None,
        "description": "Python SQL",
        "fit_score": 90,
        "fit_reasons": [],
        "asset_stage": "resolve",
    }]


def test_enrich_descriptions_only_fetches_missing_descriptions(tmp_path: Path):
    db = Database(tmp_path / "state.db")
    db.initialize()
    first = db.upsert_job({
        "external_id": "123", "title": "A", "company": "Acme", "location": "Brazil",
        "source_url": "https://www.linkedin.com/jobs/view/123", "status": "qualified",
    })
    db.upsert_job({
        "external_id": "456", "title": "B", "company": "Beta", "location": "Brazil",
        "source_url": "https://www.linkedin.com/jobs/view/456", "description": "already here",
        "status": "qualified",
    })
    calls = []

    def fetch(url: str) -> str:
        calls.append(url)
        return HTML

    result = enrich_descriptions(db, limit=10, fetch_html=fetch)

    assert result == {"enriched": 1, "failed": 0}
    assert calls == ["https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/123"]
    assert next(j for j in db.list_jobs() if j["id"] == first)["description"] == "Python SQL BigQuery"


def test_record_resolution_failure_returns_retry_metadata(tmp_path: Path):
    db = Database(tmp_path / "state.db")
    db.initialize()
    job_id = db.upsert_job({
        "title": "A", "company": "Acme", "location": "Brazil",
        "source_url": "https://www.linkedin.com/jobs/view/1", "status": "qualified",
    })

    result = record_resolution_failure(db, job_id, "sem URL oficial", retry_hours=24)

    assert result == {"job_id": job_id, "resolution": "deferred", "retry_hours": 24}
    assert db.asset_queue(limit=10) == []

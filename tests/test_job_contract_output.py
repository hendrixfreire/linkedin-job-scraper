from datetime import datetime, timezone

from linkedin_jobs import build_job_candidate_feed


def test_build_job_candidate_feed_emits_versioned_handoff():
    feed = build_job_candidate_feed([
        {
            "id": "123",
            "title": "Senior Data Engineer",
            "company": "Acme",
            "location": "Brazil",
            "work_mode": "remote",
            "date": "2026-07-19",
            "url": "https://www.linkedin.com/jobs/view/123",
            "description": "Python and SQL",
            "heuristic_score": 5,
        }
    ], produced_at=datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc))

    assert feed["contract"] == "job-candidate"
    assert feed["schema_version"] == 1
    assert feed["jobs"][0]["source_job_id"] == "123"
    assert feed["jobs"][0]["source_score"] == 100
    assert feed["jobs"][0]["source_url"].startswith("https://")

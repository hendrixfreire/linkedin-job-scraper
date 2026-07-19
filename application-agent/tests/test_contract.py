import pytest

from candidatura_agent.contracts import ContractError, parse_job_candidate_feed


def valid_feed():
    return {
        "contract": "job-candidate",
        "schema_version": 1,
        "produced_at": "2026-07-19T12:00:00Z",
        "jobs": [{
            "source": "linkedin",
            "source_job_id": "123",
            "source_url": "https://www.linkedin.com/jobs/view/123",
            "title": "Senior Data Engineer",
            "company": "Acme",
            "location": "Brazil",
            "work_mode": "remote",
            "posted_at": "2026-07-19",
            "description": "Build pipelines with Python and SQL.",
            "source_score": 90,
            "collected_at": "2026-07-19T11:59:00Z",
        }],
    }


def test_parse_job_candidate_v1_normalizes_to_agent_input():
    jobs = parse_job_candidate_feed(valid_feed())

    assert jobs == [{
        "external_id": "123",
        "source_url": "https://www.linkedin.com/jobs/view/123",
        "title": "Senior Data Engineer",
        "company": "Acme",
        "location": "Brazil",
        "work_mode": "remote",
        "posted_at": "2026-07-19",
        "description": "Build pipelines with Python and SQL.",
        "source_score": 90,
        "source": "linkedin",
        "collected_at": "2026-07-19T11:59:00Z",
    }]


def test_parse_job_candidate_v1_rejects_missing_source_identity():
    feed = valid_feed()
    del feed["jobs"][0]["source_job_id"]

    with pytest.raises(ContractError, match="source_job_id"):
        parse_job_candidate_feed(feed)

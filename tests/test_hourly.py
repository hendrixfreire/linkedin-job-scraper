import json
from pathlib import Path

from candidatura_agent.hourly import _profile_for_job, run_pipeline


def test_profile_for_job_uses_tailored_resume_when_required():
    profile = {"resume": "/tmp/generic.pdf", "resume_strategy": "tailor_per_job"}
    assert _profile_for_job(profile, {"resume_path": None}) is None
    tailored = _profile_for_job(profile, {"resume_path": "/tmp/company.pdf"})
    assert tailored["resume"] == "/tmp/company.pdf"


def test_hourly_pipeline_ingests_scores_and_writes_control(tmp_path: Path):
    source = tmp_path / "jobs.json"
    source.write_text(json.dumps([{
        "id": "1", "title": "Senior Analytics Engineer", "company": "Acme",
        "location": "Brazil", "url": "https://boards.greenhouse.io/acme/jobs/1",
        "description": "Python SQL BigQuery GCP lakehouse", "heuristic_score": 5,
    }]))
    profile = {
        "full_name": "Test", "target_titles": ["analytics engineer"],
        "preferred_skills": ["python", "sql", "bigquery", "gcp", "lakehouse"],
        "blocked_title_terms": ["junior"], "allowed_locations": ["brazil"],
        "min_fit_score": 70, "daily_limit": 10,
    }
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps(profile))
    config = {
        "source_json": str(source), "database": str(tmp_path / "state.db"),
        "profile": str(profile_path), "run_control": str(tmp_path / "control.json"),
        "browser_enabled": False, "auto_submit": False, "allowed_ats": ["greenhouse"],
        "min_fit_score": 70, "daily_limit": 10,
    }

    result = run_pipeline(config, tmp_path)

    assert result["ingested"] == 1
    assert result["qualified"] == 1
    assert json.loads((tmp_path / "control.json").read_text())["status"] == "ok"

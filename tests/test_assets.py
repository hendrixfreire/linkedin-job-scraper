import json
from pathlib import Path

import pytest

from candidatura_agent.assets import (
    enrich_job_description,
    extract_linkedin_description,
    infer_ats,
    record_job_resolution,
    record_job_resume,
    validate_external_apply_url,
)
from candidatura_agent.db import Database


LINKEDIN_HTML = """
<section class="show-more-less-html">
  <div class="show-more-less-html__markup relative overflow-hidden">
    <p>Build reliable data pipelines.</p>
    <ul><li>Python and SQL</li><li>BigQuery</li></ul>
  </div>
</section>
"""


def test_extract_linkedin_description_preserves_visible_content():
    description = extract_linkedin_description(LINKEDIN_HTML)
    assert "Build reliable data pipelines." in description
    assert "Python and SQL" in description
    assert "BigQuery" in description


def test_infer_ats_recognizes_supported_domains():
    assert infer_ats("https://job-boards.greenhouse.io/acme/jobs/1") == "greenhouse"
    assert infer_ats("https://jobs.lever.co/acme/abc") == "lever"
    assert infer_ats("https://jobs.ashbyhq.com/acme/abc") == "ashby"
    assert infer_ats("https://acme.gupy.io/jobs/123") == "gupy"
    assert infer_ats("https://jobs.peopleforce.io/acme/123") == "peopleforce"
    assert infer_ats("https://acme.factorialhr.com.br/job_posting/123") == "factorial"


def test_infer_ats_recognizes_ats_common_in_brazil():
    """Quinze vagas tinham URL oficial correta e foram descartadas pelo validador."""
    assert infer_ats("https://acme.wd3.myworkdayjobs.com/pt-BR/careers/job/1") == "workday"
    assert infer_ats("https://jobs.smartrecruiters.com/Acme/744000") == "smartrecruiters"
    assert infer_ats("https://acme.solides.jobs/vacancies/123") == "solides"
    assert infer_ats("https://acme.recruitee.com/o/data-engineer") == "recruitee"
    assert infer_ats("https://apply.workable.com/acme/j/ABC123/") == "workable"
    assert infer_ats("https://acme.teamtailor.com/jobs/123") == "teamtailor"
    assert infer_ats("https://acme.bamboohr.com/careers/123") == "bamboohr"
    assert infer_ats("https://acme.inhire.app/vagas/123") == "inhire"
    assert infer_ats("https://www.vagas.com.br/vagas/v123") == "vagas"


def test_validate_external_apply_url_rejects_linkedin_and_unknown_hosts():
    with pytest.raises(ValueError, match="LinkedIn"):
        validate_external_apply_url("https://www.linkedin.com/jobs/view/1")
    with pytest.raises(ValueError, match="ATS não reconhecido"):
        validate_external_apply_url("https://example.com/jobs/1")
    with pytest.raises(ValueError, match="HTTPS"):
        validate_external_apply_url("http://job-boards.greenhouse.io/acme/jobs/1")


def test_ats_registry_is_shared_between_detection_and_validation():
    """Duas listas mantidas à mão divergiam; agora é uma fonte só."""
    from candidatura_agent.adapters import ATS_HOSTS
    from candidatura_agent.assets import ATS_HOST_MARKERS

    assert ATS_HOST_MARKERS is ATS_HOSTS


def test_database_tracks_resolution_and_resume_separately(tmp_path: Path):
    db = Database(tmp_path / "state.db")
    db.initialize()
    job_id = db.upsert_job({
        "title": "Senior Data Engineer",
        "company": "Acme",
        "location": "Brazil",
        "source_url": "https://www.linkedin.com/jobs/view/1",
        "status": "qualified",
    })

    db.update_job_description(job_id, "Python SQL BigQuery")
    db.set_job_resolution(
        job_id,
        apply_url="https://job-boards.greenhouse.io/acme/jobs/1",
        ats="greenhouse",
        company="Acme",
        resolution_source="exact_web_search",
    )
    resume = tmp_path / "cv.pdf"
    resume.write_bytes(b"%PDF-1.4\n%%EOF\n")
    db.set_job_resume(job_id, str(resume))

    job = next(item for item in db.list_jobs() if item["id"] == job_id)
    assert job["description"] == "Python SQL BigQuery"
    assert job["apply_url"].startswith("https://job-boards.greenhouse.io/")
    assert job["ats"] == "greenhouse"
    assert job["resume_path"] == str(resume)
    assert job["resolution_source"] == "exact_web_search"
    assert job["resolved_at"]


def test_asset_queue_prioritizes_unresolved_then_missing_resume(tmp_path: Path):
    db = Database(tmp_path / "state.db")
    db.initialize()
    unresolved = db.upsert_job({
        "title": "A", "company": "Acme", "location": "Brazil",
        "source_url": "https://www.linkedin.com/jobs/view/1", "status": "qualified", "fit_score": 90,
    })
    resolved = db.upsert_job({
        "title": "B", "company": "Beta", "location": "Brazil",
        "source_url": "https://www.linkedin.com/jobs/view/2", "status": "qualified", "fit_score": 80,
        "apply_url": "https://jobs.lever.co/beta/2", "ats": "lever",
    })

    queue = db.asset_queue(limit=10)

    assert [job["id"] for job in queue] == [unresolved, resolved]
    assert queue[0]["asset_stage"] == "resolve"
    assert queue[1]["asset_stage"] == "resume"


def test_enrich_job_description_fetches_guest_endpoint(tmp_path: Path):
    db = Database(tmp_path / "state.db")
    db.initialize()
    job_id = db.upsert_job({
        "external_id": "123", "title": "Data Engineer", "company": "Acme",
        "location": "Brazil", "source_url": "https://www.linkedin.com/jobs/view/123",
        "status": "qualified",
    })
    requested = []

    def fake_fetch(url: str) -> str:
        requested.append(url)
        return LINKEDIN_HTML

    description = enrich_job_description(db, db.list_jobs()[0], fetch_html=fake_fetch)

    assert requested == ["https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/123"]
    assert description.startswith("Build reliable data pipelines")
    assert next(job for job in db.list_jobs() if job["id"] == job_id)["description"] == description


def test_record_resolution_derives_ats_and_record_resume_requires_pdf(tmp_path: Path):
    db = Database(tmp_path / "state.db")
    db.initialize()
    job_id = db.upsert_job({
        "title": "Data Engineer", "company": "Acme", "location": "Brazil",
        "source_url": "https://www.linkedin.com/jobs/view/123", "status": "qualified",
    })
    ats = record_job_resolution(
        db, job_id, "https://jobs.lever.co/acme/abc", company="Acme",
        resolution_source="exact_web_search",
    )
    assert ats == "lever"

    invalid = tmp_path / "not-a-pdf.txt"
    invalid.write_text("nope")
    with pytest.raises(ValueError, match="PDF"):
        record_job_resume(db, job_id, invalid)

    valid = tmp_path / "cv.pdf"
    valid.write_bytes(b"%PDF-1.7\n%%EOF\n")
    record_job_resume(db, job_id, valid)
    assert db.list_jobs()[0]["resume_path"] == str(valid.resolve())


def test_failed_resolution_enters_cooldown_without_blocking_next_job(tmp_path: Path):
    db = Database(tmp_path / "state.db")
    db.initialize()
    first = db.upsert_job({
        "title": "A", "company": "Acme", "location": "Brazil",
        "source_url": "https://www.linkedin.com/jobs/view/1", "status": "qualified", "fit_score": 90,
    })
    second = db.upsert_job({
        "title": "B", "company": "Beta", "location": "Brazil",
        "source_url": "https://www.linkedin.com/jobs/view/2", "status": "qualified", "fit_score": 80,
    })

    db.mark_resolution_failed(first, "nenhuma URL oficial", retry_hours=24)

    queue = db.asset_queue(limit=10)
    assert [job["id"] for job in queue] == [second]
    failed = next(job for job in db.list_jobs() if job["id"] == first)
    assert failed["resolution_attempts"] == 1
    assert failed["resolution_last_error"] == "nenhuma URL oficial"
    assert failed["resolution_retry_at"]

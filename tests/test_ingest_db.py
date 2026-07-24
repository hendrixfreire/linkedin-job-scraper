import json
from pathlib import Path

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


def test_reopen_blocked_jobs_returns_resolvable_ones_to_the_queue(tmp_path: Path):
    """Sem isso, vagas bloqueadas nunca são retentadas — nem depois de a causa sumir."""
    db = Database(tmp_path / "state.db")
    db.initialize()
    fixable = db.upsert_job({
        "external_id": "fix-1", "title": "Data Engineer", "company": "Acme",
        "location": "Brazil", "source_url": "https://example.test/fix-1",
        "apply_url": "https://job-boards.greenhouse.io/acme/jobs/1",
        "resume_path": "/tmp/cv.pdf", "fit_score": 90, "status": "qualified",
    })
    human = db.upsert_job({
        "external_id": "human-1", "title": "Data Engineer", "company": "Beta",
        "location": "Brazil", "source_url": "https://example.test/human-1",
        "apply_url": "https://job-boards.greenhouse.io/beta/jobs/1",
        "resume_path": "/tmp/cv.pdf", "fit_score": 90, "status": "qualified",
    })
    db.record_application(fixable, "blocked", "greenhouse", ["CPF* CPF question_1"])
    db.record_application(human, "blocked", "greenhouse", ["captcha"])

    assert db.reopen_blocked_jobs() == 1

    queued = {job["id"] for job in db.daily_queue(require_resume=True)}
    assert fixable in queued
    assert human not in queued

    statuses = {job["id"]: job["status"] for job in db.list_jobs()}
    assert statuses[fixable] == "qualified"
    assert statuses[human] == "blocked"

    kinds = [row["kind"] for row in db.list_events(fixable)]
    assert "application_reopened" in kinds


def test_reopen_blocked_jobs_can_be_forced_for_human_blockers(tmp_path: Path):
    db = Database(tmp_path / "state.db")
    db.initialize()
    job_id = db.upsert_job({
        "external_id": "human-2", "title": "Data Engineer", "company": "Gamma",
        "location": "Brazil", "source_url": "https://example.test/human-2",
        "fit_score": 90, "status": "qualified",
    })
    db.record_application(job_id, "blocked", "greenhouse", ["2fa"])

    assert db.reopen_blocked_jobs() == 0
    assert db.reopen_blocked_jobs(include_human=True) == 1


def test_reopen_accepts_other_statuses_and_a_single_job(tmp_path: Path):
    """Vagas em dry_run também ficam fora da fila; reabrir é o que as libera."""
    db = Database(tmp_path / "state.db")
    db.initialize()
    ids = [
        db.upsert_job({
            "external_id": f"dry-{idx}", "title": "Data Engineer", "company": f"Co{idx}",
            "location": "Brazil", "source_url": f"https://example.test/dry-{idx}",
            "apply_url": "https://job-boards.greenhouse.io/co/jobs/1",
            "resume_path": "/tmp/cv.pdf", "fit_score": 90, "status": "qualified",
        })
        for idx in range(3)
    ]
    for job_id in ids:
        db.record_application(job_id, "dry_run", "greenhouse", [])

    assert db.daily_queue(require_resume=True) == []
    assert db.reopen_blocked_jobs(statuses=("dry_run",), job_id=ids[0]) == 1

    queued = [job["id"] for job in db.daily_queue(require_resume=True)]
    assert queued == [ids[0]]

    assert db.reopen_blocked_jobs(statuses=("dry_run",)) == 2
    assert len(db.daily_queue(require_resume=True)) == 3

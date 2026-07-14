from pathlib import Path

import pytest

from candidatura_agent.db import Database
from candidatura_agent.notifications import format_submission_message, send_pending_notifications


def _submitted_job(db: Database) -> int:
    job_id = db.upsert_job({
        "external_id": "notify-1",
        "title": "Senior Analytics Engineer",
        "company": "Acme",
        "location": "São Paulo, Brazil",
        "source_url": "https://linkedin.com/jobs/view/notify-1",
        "apply_url": "https://boards.greenhouse.io/acme/jobs/notify-1",
        "description": "Build analytics pipelines with Python, SQL and BigQuery for business teams.",
        "fit_score": 91,
        "fit_reasons": ["cargo-alvo", "Python", "SQL"],
        "status": "qualified",
    })
    db.record_application(job_id, "submitted", "greenhouse", [])
    return job_id


def test_submitted_application_creates_one_pending_notification(tmp_path: Path):
    db = Database(tmp_path / "state.db")
    db.initialize()
    job_id = _submitted_job(db)

    pending = db.pending_submission_notifications()
    assert len(pending) == 1
    assert pending[0]["job_id"] == job_id

    db.record_application(job_id, "submitted", "greenhouse", [])
    assert len(db.pending_submission_notifications()) == 1

    message = format_submission_message(pending[0])
    assert message.startswith("CANDIDATURA ENVIADA")
    assert "Senior Analytics Engineer" in message
    assert "Acme" in message
    assert "91/100" in message
    assert "https://boards.greenhouse.io/acme/jobs/notify-1" in message
    assert "Python, SQL and BigQuery" in message


def test_notification_is_marked_only_after_successful_discord_delivery(tmp_path: Path):
    db = Database(tmp_path / "state.db")
    db.initialize()
    _submitted_job(db)
    calls: list[tuple[str, str]] = []

    sent = send_pending_notifications(
        db,
        "discord:1526233025346666617:1526233025346666617",
        sender=lambda target, message: calls.append((target, message)),
    )
    assert sent == 1
    assert calls[0][0].startswith("discord:")
    assert db.pending_submission_notifications() == []


def test_failed_discord_delivery_stays_pending_for_retry(tmp_path: Path):
    db = Database(tmp_path / "state.db")
    db.initialize()
    _submitted_job(db)

    def fail(_target: str, _message: str) -> None:
        raise RuntimeError("Discord indisponível")

    with pytest.raises(RuntimeError, match="Discord indisponível"):
        send_pending_notifications(db, "discord:geral", sender=fail)

    assert len(db.pending_submission_notifications()) == 1

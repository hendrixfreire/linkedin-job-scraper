"""Notificações de candidaturas confirmadas via Hermes send."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

from .db import Database

Sender = Callable[[str, str], None]


def _clean_summary(text: str, limit: int = 300) -> str:
    clean = re.sub(r"\s+", " ", text or "").strip()
    if not clean:
        return "Descrição resumida não disponível."
    return clean if len(clean) <= limit else clean[: limit - 1].rstrip() + "…"


def format_submission_message(row: dict[str, Any]) -> str:
    try:
        reasons = json.loads(row.get("fit_reasons") or "[]")
    except (TypeError, json.JSONDecodeError):
        reasons = []
    highlights = ", ".join(str(reason) for reason in reasons[:3]) or "aderência aprovada pela política"
    vacancy_url = row.get("apply_url") or row["source_url"]
    lines = [
        "CANDIDATURA ENVIADA",
        "",
        f"Cargo: {row['title']}",
        f"Empresa: {row['company']}",
        f"Local: {row.get('location') or 'não informado'}",
        f"Aderência: {row['fit_score']}/100",
        f"Destaques: {highlights}",
        f"ATS: {row.get('ats') or 'não identificado'}",
        f"Enviada em: {row.get('submitted_at') or 'agora'}",
        "",
        f"Resumo: {_clean_summary(row.get('description') or '')}",
        "",
        f"Link da vaga: {vacancy_url}",
    ]
    if row.get("apply_url") and row.get("source_url") != row.get("apply_url"):
        lines.append(f"Origem: {row['source_url']}")
    return "\n".join(lines)


def _hermes_send(target: str, message: str) -> None:
    hermes = shutil.which("hermes")
    if not hermes:
        raise RuntimeError("CLI hermes não encontrado no PATH")
    subprocess.run(
        [hermes, "send", "--to", target, "--quiet", message],
        check=True,
        text=True,
        capture_output=True,
    )


def send_pending_notifications(db: Database, target: str, sender: Sender = _hermes_send) -> int:
    sent = 0
    for row in db.pending_submission_notifications():
        try:
            sender(target, format_submission_message(row))
        except Exception as exc:
            db.mark_notification_failed(row["notification_id"], str(exc))
            raise
        db.mark_notification_delivered(row["notification_id"])
        sent += 1
    return sent


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    config = json.loads((root / "config.json").read_text())
    db_path = Path(config["database"])
    if not db_path.is_absolute():
        db_path = root / db_path
    db = Database(db_path)
    db.initialize()
    send_pending_notifications(db, config["notification_target"])


if __name__ == "__main__":
    main()

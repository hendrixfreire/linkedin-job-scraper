"""CLI estreita para o agente preparar URLs, descrições e CVs por vaga."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Callable

from .assets import enrich_job_description, record_job_resolution, record_job_resume
from .db import Database


QUEUE_FIELDS = (
    "id", "external_id", "title", "company", "location", "source_url",
    "apply_url", "ats", "description", "fit_score", "fit_reasons", "asset_stage",
)


def queue_payload(db: Database, limit: int = 1) -> list[dict]:
    payload = []
    for job in db.asset_queue(limit=limit):
        item = {key: job.get(key) for key in QUEUE_FIELDS}
        reasons = item.get("fit_reasons")
        if isinstance(reasons, str):
            try:
                item["fit_reasons"] = json.loads(reasons)
            except json.JSONDecodeError:
                item["fit_reasons"] = []
        payload.append(item)
    return payload


def enrich_descriptions(
    db: Database, limit: int = 20, *, fetch_html: Callable[[str], str] | None = None,
) -> dict[str, int]:
    enriched = 0
    failed = 0
    jobs = [job for job in db.asset_queue(limit=limit) if not (job.get("description") or "").strip()]
    for job in jobs:
        try:
            kwargs = {"fetch_html": fetch_html} if fetch_html is not None else {}
            enrich_job_description(db, job, **kwargs)
            enriched += 1
        except Exception:
            failed += 1
    return {"enriched": enriched, "failed": failed}


def record_resolution_failure(
    db: Database, job_id: int, error: str, retry_hours: int = 24,
) -> dict[str, int | str]:
    hours = max(1, int(retry_hours))
    db.mark_resolution_failed(job_id, error, retry_hours=hours)
    return {"job_id": job_id, "resolution": "deferred", "retry_hours": hours}


def _root() -> Path:
    return Path(__file__).resolve().parents[2]


def _database(root: Path) -> Database:
    config = json.loads((root / "config.json").read_text())
    path = Path(config["database"]).expanduser()
    if not path.is_absolute():
        path = root / path
    db = Database(path)
    db.initialize()
    return db


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepara ativos de candidaturas")
    sub = parser.add_subparsers(dest="command", required=True)

    queue = sub.add_parser("queue")
    queue.add_argument("--limit", type=int, default=1)

    enrich = sub.add_parser("enrich")
    enrich.add_argument("--limit", type=int, default=20)

    resolve = sub.add_parser("resolve")
    resolve.add_argument("--job-id", type=int, required=True)
    resolve.add_argument("--url", required=True)
    resolve.add_argument("--company")
    resolve.add_argument("--source", default="exact_web_search")

    fail = sub.add_parser("fail-resolution")
    fail.add_argument("--job-id", type=int, required=True)
    fail.add_argument("--error", required=True)
    fail.add_argument("--retry-hours", type=int, default=24)

    resume = sub.add_parser("resume")
    resume.add_argument("--job-id", type=int, required=True)
    resume.add_argument("--path", required=True)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    db = _database(_root())
    if args.command == "queue":
        result = queue_payload(db, limit=args.limit)
    elif args.command == "enrich":
        result = enrich_descriptions(db, limit=args.limit)
    elif args.command == "resolve":
        ats = record_job_resolution(
            db, args.job_id, args.url, company=args.company,
            resolution_source=args.source,
        )
        result = {"job_id": args.job_id, "ats": ats, "apply_url": args.url}
    elif args.command == "fail-resolution":
        result = record_resolution_failure(
            db, args.job_id, args.error, retry_hours=args.retry_hours,
        )
    else:
        path = record_job_resume(db, args.job_id, args.path)
        result = {"job_id": args.job_id, "resume_path": path}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

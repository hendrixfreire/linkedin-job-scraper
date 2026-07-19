"""Ingestão do JSON produzido pelo scraper existente."""

from __future__ import annotations

import json
from pathlib import Path

from .contracts import parse_job_candidate_feed
from .db import Database


def ingest_linkedin_json(db: Database, source: str | Path) -> int:
    path = Path(source)
    if not path.exists():
        return 0
    payload = json.loads(path.read_text())
    jobs = parse_job_candidate_feed(payload) if isinstance(payload, dict) else payload
    known = {job["source_url"] for job in db.list_jobs()}
    inserted = 0
    for raw in jobs:
        url = raw.get("source_url") or raw.get("url")
        if not url:
            continue
        is_new = url not in known
        source_score = raw.get("source_score")
        if source_score is None:
            source_score = int(raw.get("heuristic_score") or 0) * 20
        db.upsert_job({
            **raw,
            "external_id": raw.get("external_id") or raw.get("id"),
            "source_url": url,
            "source_score": source_score,
            "fit_score": int(raw.get("heuristic_score") or 0) * 20,
            "status": "new",
        })
        if is_new:
            known.add(url)
            inserted += 1
    return inserted

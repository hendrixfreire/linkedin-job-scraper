"""Persistência SQLite do agente de candidaturas."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY,
    external_id TEXT,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    location TEXT NOT NULL DEFAULT '',
    source_url TEXT NOT NULL UNIQUE,
    apply_url TEXT,
    resume_path TEXT,
    description TEXT NOT NULL DEFAULT '',
    ats TEXT,
    source_score INTEGER NOT NULL DEFAULT 0,
    fit_score INTEGER NOT NULL DEFAULT 0,
    fit_reasons TEXT NOT NULL DEFAULT '[]',
    blockers TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'new',
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY,
    job_id INTEGER NOT NULL UNIQUE REFERENCES jobs(id),
    status TEXT NOT NULL,
    ats TEXT,
    blockers TEXT NOT NULL DEFAULT '[]',
    submitted_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY,
    application_id INTEGER NOT NULL UNIQUE REFERENCES applications(id),
    channel TEXT NOT NULL DEFAULT 'discord',
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    delivered_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY,
    job_id INTEGER NOT NULL REFERENCES jobs(id),
    rating TEXT NOT NULL CHECK (rating IN ('good','bad','irrelevant')),
    reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    job_id INTEGER REFERENCES jobs(id),
    kind TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS answers (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    approved INTEGER NOT NULL DEFAULT 0,
    sensitive INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
"""


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)")}
            if "source_score" not in columns:
                conn.execute("ALTER TABLE jobs ADD COLUMN source_score INTEGER NOT NULL DEFAULT 0")
            if "resume_path" not in columns:
                conn.execute("ALTER TABLE jobs ADD COLUMN resume_path TEXT")

    def upsert_job(self, job: dict[str, Any]) -> int:
        source_url = job.get("source_url") or job.get("url")
        if not source_url:
            raise ValueError("job sem source_url")
        values = {
            "external_id": str(job.get("external_id") or job.get("id") or ""),
            "title": job.get("title") or "Vaga sem título",
            "company": job.get("company") or "Empresa não informada",
            "location": job.get("location") or "",
            "source_url": source_url,
            "apply_url": job.get("apply_url"),
            "resume_path": job.get("resume_path"),
            "description": job.get("description") or "",
            "ats": job.get("ats"),
            "source_score": int(job.get("source_score") or 0),
            "fit_score": int(job.get("fit_score") or 0),
            "fit_reasons": json.dumps(job.get("fit_reasons") or [], ensure_ascii=False),
            "blockers": json.dumps(job.get("blockers") or [], ensure_ascii=False),
            "status": job.get("status") or "new",
        }
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO jobs (external_id,title,company,location,source_url,apply_url,resume_path,description,ats,source_score,fit_score,fit_reasons,blockers,status)
                VALUES (:external_id,:title,:company,:location,:source_url,:apply_url,:resume_path,:description,:ats,:source_score,:fit_score,:fit_reasons,:blockers,:status)
                ON CONFLICT(source_url) DO UPDATE SET
                  apply_url=COALESCE(excluded.apply_url,jobs.apply_url),
                  resume_path=COALESCE(excluded.resume_path,jobs.resume_path),
                  description=CASE WHEN excluded.description<>'' THEN excluded.description ELSE jobs.description END,
                  source_score=MAX(jobs.source_score,excluded.source_score), updated_at=datetime('now','localtime')""",
                values,
            )
            row = conn.execute("SELECT id FROM jobs WHERE source_url=?", (source_url,)).fetchone()
            return int(row["id"])

    def list_jobs(self, status: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM jobs"
        args: tuple[Any, ...] = ()
        if status:
            query += " WHERE status=?"
            args = (status,)
        query += " ORDER BY fit_score DESC, created_at ASC"
        with self.connect() as conn:
            return [dict(row) for row in conn.execute(query, args)]

    def daily_queue(self, limit: int | None = None, require_resume: bool = False) -> list[dict[str, Any]]:
        query = """SELECT j.* FROM jobs j LEFT JOIN applications a ON a.job_id=j.id
            WHERE j.status='qualified' AND a.id IS NULL
              AND (?=0 OR j.resume_path IS NOT NULL)
            ORDER BY j.fit_score DESC, j.created_at ASC"""
        args: tuple[Any, ...] = (int(require_resume),)
        if limit is not None:
            query += " LIMIT ?"
            args += (int(limit),)
        with self.connect() as conn:
            return [dict(row) for row in conn.execute(query, args)]

    def cv_queue(self, limit: int = 10) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT j.* FROM jobs j LEFT JOIN applications a ON a.job_id=j.id
                WHERE j.status='qualified' AND j.resume_path IS NULL AND a.id IS NULL
                ORDER BY j.fit_score DESC, j.created_at ASC LIMIT ?""",
                (limit,),
            )
            return [dict(row) for row in rows]

    def set_job_assets(
        self, job_id: int, *, apply_url: str, ats: str, resume_path: str,
        company: str | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """UPDATE jobs SET apply_url=?,ats=?,resume_path=?,company=COALESCE(?,company),
                updated_at=datetime('now','localtime') WHERE id=?""",
                (apply_url, ats, resume_path, company, job_id),
            )
            conn.execute(
                "INSERT INTO events(job_id,kind,payload) VALUES (?,?,?)",
                (job_id, "assets_prepared", json.dumps({
                    "apply_url": apply_url, "ats": ats, "resume_path": resume_path,
                    "company": company,
                }, ensure_ascii=False)),
            )

    def submitted_today(self) -> int:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM applications WHERE status='submitted' AND date(submitted_at)=date('now','localtime')"
            ).fetchone()
            return int(row["n"])

    def record_application(self, job_id: int, status: str, ats: str | None, blockers: list[str]) -> None:
        submitted_at = "datetime('now','localtime')" if status == "submitted" else "NULL"
        with self.connect() as conn:
            conn.execute(
                f"""INSERT INTO applications (job_id,status,ats,blockers,submitted_at)
                VALUES (?,?,?,?,{submitted_at})
                ON CONFLICT(job_id) DO UPDATE SET status=excluded.status, ats=excluded.ats,
                  blockers=excluded.blockers, submitted_at=COALESCE(excluded.submitted_at,applications.submitted_at),
                  updated_at=datetime('now','localtime')""",
                (job_id, status, ats, json.dumps(blockers, ensure_ascii=False)),
            )
            application_id = int(conn.execute(
                "SELECT id FROM applications WHERE job_id=?", (job_id,)
            ).fetchone()["id"])
            if status == "submitted":
                conn.execute(
                    "INSERT OR IGNORE INTO notifications(application_id,channel) VALUES (?,'discord')",
                    (application_id,),
                )
            conn.execute("UPDATE jobs SET status=?, blockers=?, updated_at=datetime('now','localtime') WHERE id=?", (status, json.dumps(blockers, ensure_ascii=False), job_id))
            conn.execute("INSERT INTO events(job_id,kind,payload) VALUES (?,?,?)", (job_id, f"application_{status}", json.dumps({"ats": ats, "blockers": blockers}, ensure_ascii=False)))

    def pending_submission_notifications(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT n.id AS notification_id,n.attempts,a.id AS application_id,
                    a.submitted_at,a.ats,j.id AS job_id,j.title,j.company,j.location,
                    j.source_url,j.apply_url,j.description,j.fit_score,j.fit_reasons
                FROM notifications n
                JOIN applications a ON a.id=n.application_id
                JOIN jobs j ON j.id=a.job_id
                WHERE n.delivered_at IS NULL AND a.status='submitted'
                ORDER BY n.created_at,n.id"""
            )
            return [dict(row) for row in rows]

    def mark_notification_delivered(self, notification_id: int) -> None:
        with self.connect() as conn:
            conn.execute(
                """UPDATE notifications SET delivered_at=datetime('now','localtime'),
                attempts=attempts+1,last_error=NULL,updated_at=datetime('now','localtime')
                WHERE id=?""",
                (notification_id,),
            )

    def mark_notification_failed(self, notification_id: int, error: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """UPDATE notifications SET attempts=attempts+1,last_error=?,
                updated_at=datetime('now','localtime') WHERE id=?""",
                (error[:500], notification_id),
            )

    def add_feedback(self, job_id: int, rating: str, reason: str = "") -> None:
        with self.connect() as conn:
            conn.execute("INSERT INTO feedback(job_id,rating,reason) VALUES (?,?,?)", (job_id, rating, reason))
            conn.execute("INSERT INTO events(job_id,kind,payload) VALUES (?,?,?)", (job_id, "feedback", json.dumps({"rating": rating, "reason": reason}, ensure_ascii=False)))

    def list_feedback(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT f.*,j.title,j.company FROM feedback f
                JOIN jobs j ON j.id=f.job_id ORDER BY f.created_at DESC,f.id DESC"""
            )
            return [dict(row) for row in rows]

    def learned_weights(self) -> dict[str, int]:
        phrases = (
            "data engineer", "analytics engineer", "data analyst", "bi manager",
            "data analytics manager", "ai engineer", "machine learning engineer",
            "head de dados", "product manager", "marketing analytics",
        )
        weights: dict[str, int] = {}
        for row in self.list_feedback():
            title = row["title"].lower()
            delta = {"good": 4, "bad": -4, "irrelevant": -8}[row["rating"]]
            for phrase in phrases:
                if phrase in title:
                    weights[phrase] = max(-15, min(15, weights.get(phrase, 0) + delta))
        return weights

    def update_assessment(self, job_id: int, score: int, reasons: list[str], blockers: list[str], status: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """UPDATE jobs SET fit_score=?,fit_reasons=?,blockers=?,status=?,updated_at=datetime('now','localtime')
                WHERE id=?""",
                (score, json.dumps(reasons, ensure_ascii=False), json.dumps(blockers, ensure_ascii=False), status, job_id),
            )
            conn.execute("INSERT INTO events(job_id,kind,payload) VALUES (?,?,?)", (job_id, "assessed", json.dumps({"score": score, "reasons": reasons, "blockers": blockers}, ensure_ascii=False)))

    def applications_for_date(self, day: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT a.*,j.title,j.company,j.source_url,j.fit_score,j.fit_reasons
                FROM applications a JOIN jobs j ON j.id=a.job_id
                WHERE date(a.updated_at)=? ORDER BY a.updated_at""",
                (day,),
            )
            return [dict(row) for row in rows]

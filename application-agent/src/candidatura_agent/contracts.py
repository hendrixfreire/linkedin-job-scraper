"""Versioned handoff contract between job collectors and the application agent."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse


class ContractError(ValueError):
    """Raised when a producer sends an incompatible job feed."""


_REQUIRED_JOB_FIELDS = (
    "source",
    "source_job_id",
    "source_url",
    "title",
    "company",
    "location",
    "collected_at",
)


def parse_job_candidate_feed(feed: Any) -> list[dict[str, Any]]:
    """Validate JobCandidate v1 and normalize it to the agent's job interface."""
    if not isinstance(feed, dict):
        raise ContractError("feed must be an object")
    if feed.get("contract") != "job-candidate":
        raise ContractError("contract must be job-candidate")
    if feed.get("schema_version") != 1:
        raise ContractError("unsupported schema_version")
    jobs = feed.get("jobs")
    if not isinstance(jobs, list):
        raise ContractError("jobs must be a list")

    normalized: list[dict[str, Any]] = []
    for index, job in enumerate(jobs):
        if not isinstance(job, dict):
            raise ContractError(f"jobs[{index}] must be an object")
        for field in _REQUIRED_JOB_FIELDS:
            if not isinstance(job.get(field), str) or not job[field].strip():
                raise ContractError(f"jobs[{index}].{field} is required")
        parsed = urlparse(job["source_url"])
        if parsed.scheme != "https" or not parsed.netloc:
            raise ContractError(f"jobs[{index}].source_url must be an HTTPS URL")
        score = job.get("source_score", 0)
        if not isinstance(score, int) or not 0 <= score <= 100:
            raise ContractError(f"jobs[{index}].source_score must be an integer from 0 to 100")
        normalized.append({
            "external_id": job["source_job_id"],
            "source_url": job["source_url"],
            "title": job["title"],
            "company": job["company"],
            "location": job["location"],
            "work_mode": job.get("work_mode", ""),
            "posted_at": job.get("posted_at", ""),
            "description": job.get("description", ""),
            "source_score": score,
            "source": job["source"],
            "collected_at": job["collected_at"],
        })
    return normalized

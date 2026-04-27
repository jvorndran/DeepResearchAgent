"""Persistence helpers for authenticated research jobs and saved reports."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.database import ResearchJob, SavedReport
from core.paths import OUTPUT_BASE_DIR
from services.research_types import JobStatus


def _now() -> datetime:
    return datetime.now(timezone.utc)


def get_job_for_user(db: Session, job_id: str, user_id: str) -> ResearchJob | None:
    job = db.get(ResearchJob, job_id)
    if job and job.user_id == user_id:
        return job
    return None


def upsert_research_job(
    db: Session,
    *,
    job_id: str,
    user_id: str,
    query: str,
    status: JobStatus,
    error: str | None = None,
) -> ResearchJob:
    job = db.get(ResearchJob, job_id)
    now = _now()
    if job is None:
        job = ResearchJob(
            id=job_id,
            user_id=user_id,
            query=query,
            status=status.value,
            output_path=str(OUTPUT_BASE_DIR / job_id),
        )
        db.add(job)
    else:
        job.user_id = user_id
        job.query = query
        job.status = status.value
        job.updated_at = now
    job.error = error
    job.completed_at = now if status == JobStatus.COMPLETED else None
    job.report_path = str(OUTPUT_BASE_DIR / job_id / "report.json") if status == JobStatus.COMPLETED else job.report_path
    db.commit()
    db.refresh(job)
    return job


def mark_job_status(
    db: Session,
    *,
    job_id: str,
    status: JobStatus,
    error: str | None = None,
) -> ResearchJob | None:
    job = db.get(ResearchJob, job_id)
    if not job:
        return None
    job.status = status.value
    job.updated_at = _now()
    job.error = error
    if status == JobStatus.COMPLETED:
        job.completed_at = _now()
        job.report_path = str(OUTPUT_BASE_DIR / job_id / "report.json")
    db.commit()
    db.refresh(job)
    return job


def save_completed_report(db: Session, *, job_id: str, user_id: str, query: str) -> SavedReport | None:
    report_path = OUTPUT_BASE_DIR / job_id / "report.json"
    if not report_path.is_file():
        return None
    report_json = json.loads(report_path.read_text(encoding="utf-8"))
    title = str(report_json.get("title") or query or job_id)

    report = db.scalar(select(SavedReport).where(SavedReport.job_id == job_id))
    if report is None:
        report = SavedReport(
            job_id=job_id,
            user_id=user_id,
            title=title,
            query=str(report_json.get("query") or query),
            report_json=report_json,
        )
        db.add(report)
    else:
        report.user_id = user_id
        report.title = title
        report.query = str(report_json.get("query") or query)
        report.report_json = report_json
        report.updated_at = _now()
    db.commit()
    db.refresh(report)
    return report


def list_saved_report_summaries(db: Session, user_id: str) -> list[dict[str, Any]]:
    reports = db.scalars(
        select(SavedReport)
        .where(SavedReport.user_id == user_id)
        .order_by(SavedReport.created_at.desc())
    ).all()
    return [
        {
            "id": report.id,
            "job_id": report.job_id,
            "title": report.title,
            "query": report.query,
            "created_at": report.created_at.isoformat(),
            "updated_at": report.updated_at.isoformat(),
        }
        for report in reports
    ]


def read_owned_report_from_disk(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))

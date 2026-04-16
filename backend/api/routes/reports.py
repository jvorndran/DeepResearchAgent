import json
import logging

from fastapi import APIRouter, HTTPException

from core.paths import OUTPUT_BASE_DIR
from services.job_status import read_job_status
from services.research_jobs import JOBS
from services.research_types import JobStatus

logger = logging.getLogger(__name__)

router = APIRouter(tags=["reports"])


@router.get("/api/reports/{job_id}")
async def get_report(job_id: str):
    """
    Return the completed ResearchReport for a finished job.

    Checks in-memory registry first, then report.json, then status.json.
    Returns 202 while running, 410 if interrupted, 404 if unknown.
    """
    report_path = OUTPUT_BASE_DIR / job_id / "report.json"

    job_state = JOBS.get(job_id)
    if job_state and job_state.status == JobStatus.RUNNING:
        raise HTTPException(status_code=202, detail="Research in progress")

    if report_path.exists():
        try:
            return json.loads(report_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.error("Failed to read report for job %s: %s", job_id, e)
            raise HTTPException(status_code=500, detail="Failed to read report")

    status_data = read_job_status(job_id)
    if status_data is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    on_disk = status_data.get("status")
    if on_disk == JobStatus.RUNNING.value:
        raise HTTPException(status_code=202, detail="Research in progress")
    if on_disk == JobStatus.INTERRUPTED.value:
        raise HTTPException(
            status_code=410,
            detail="Job was interrupted — server was restarted mid-job",
        )
    if on_disk == JobStatus.FAILED.value:
        raise HTTPException(status_code=500, detail="Research job failed")
    if on_disk == JobStatus.COMPLETED.value:
        raise HTTPException(
            status_code=500,
            detail="Job completed but report was not saved — the pipeline may have failed during report generation",
        )

    raise HTTPException(status_code=202, detail="Report not yet available")

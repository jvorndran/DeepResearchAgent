import asyncio
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from core.paths import OUTPUT_BASE_DIR
from services.research_jobs import JOBS, relay_subscriber_queue, subscribe, unsubscribe
from services.research_types import JobStatus
from services.stream_events import SSE_HEADERS, sse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["jobs"])


@router.get("/api/jobs/{job_id}/stream")
async def reconnect_job_stream(job_id: str):
    """
    Reconnect to a running research job's live SSE stream after a page refresh.

    Replays all events emitted so far, then streams live events until the job
    finishes. Returns 404 if the job is not currently active in memory.
    """
    job_state = JOBS.get(job_id)
    if not job_state or job_state.status != JobStatus.RUNNING:
        raise HTTPException(
            status_code=404,
            detail="No active job found — job may have finished or never started",
        )

    replay = list(job_state.events_log)
    q = subscribe(job_state)
    logger.info("Reconnect SSE for job %s — replaying %d events", job_id, len(replay))

    async def gen():
        try:
            yield sse({"type": "start", "job_id": job_id})
            for event in replay:
                yield sse(event)
            async for event in relay_subscriber_queue(q):
                if isinstance(event, dict) and "__bg_error__" in event:
                    yield sse({"type": "error", "errorText": event["__bg_error__"]})
                    yield "data: [DONE]\n\n"
                    return
                yield sse(event)
            report_path = OUTPUT_BASE_DIR / job_id / "report.json"
            yield sse({"type": "finish", "report_ready": report_path.exists()})
            yield "data: [DONE]\n\n"
        except asyncio.CancelledError:
            logger.info("Reconnect SSE client disconnected for job %s", job_id)
            return
        finally:
            unsubscribe(job_state, q)
            if job_state.status != JobStatus.RUNNING and job_state.subscriber_count == 0:
                JOBS.pop(job_id, None)

    return StreamingResponse(gen(), media_type="text/event-stream", headers=SSE_HEADERS)

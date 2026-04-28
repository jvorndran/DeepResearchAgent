"""
In-memory job registry, SSE fan-out, and background research task runner.
"""

import asyncio
import logging
from typing import Any

from agents.orchestrator import stream_research
from core.database import SessionLocal
from core.paths import OUTPUT_BASE_DIR
from services.job_status import write_job_status
from services.report_library import mark_job_status, save_completed_report
from services.stream_errors import build_error_event
from services.research_types import JobState, JobStatus
from services.stream_errors import build_exception_error_event
from services.stream_events import process_research_chunks

logger = logging.getLogger(__name__)

JOBS: dict[str, JobState] = {}
JOB_DONE = object()  # sentinel pushed into every subscriber queue when bg task finishes


def preview_text(value: str, limit: int = 180) -> str:
    value = " ".join(value.split())
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def subscribe(job_state: JobState) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue()
    job_state._subscriber_queues.append(q)
    job_state.subscriber_count += 1
    return q


def unsubscribe(job_state: JobState, q: asyncio.Queue) -> None:
    try:
        job_state._subscriber_queues.remove(q)
    except ValueError:
        pass
    job_state.subscriber_count = max(0, job_state.subscriber_count - 1)


async def publish(job_state: JobState, event: dict) -> None:
    """Append event to the replay log and push to all active subscriber queues."""
    job_state.events_log.append(event)
    for q in list(job_state._subscriber_queues):
        await q.put(event)


async def publish_done(job_state: JobState) -> None:
    """Push the done sentinel to every subscriber queue (not logged)."""
    for q in list(job_state._subscriber_queues):
        await q.put(JOB_DONE)


async def relay_subscriber_queue(q: asyncio.Queue):
    """Async generator that yields event dicts from a subscriber queue until done."""
    while True:
        event = await q.get()
        if event is JOB_DONE:
            return
        yield event


async def run_job_background(
    job_id: str,
    user_id: str,
    query: str,
    messages_dict: list,
    agent: Any,
    job_state: JobState,
) -> None:
    try:
        logger.info(
            "Starting background research job job_id=%s message_count=%d query=%r",
            job_id,
            len(messages_dict),
            preview_text(query),
        )
        raw_stream = stream_research(
            query=query,
            job_id=job_id,
            messages=messages_dict,
            agent=agent,
            user_id=user_id,
        )
        async for event_dict in process_research_chunks(raw_stream):
            await publish(job_state, event_dict)
        report_file = OUTPUT_BASE_DIR / job_id / "report.json"
        if not report_file.is_file():
            job_state.status = JobStatus.FAILED
            write_job_status(job_id, JobStatus.FAILED, query)
            with SessionLocal() as db:
                mark_job_status(
                    db,
                    job_id=job_id,
                    status=JobStatus.FAILED,
                    error="Research finished without report.json",
                )
            logger.error(
                "Background research finished without report.json job_id=%s expected=%s",
                job_id,
                report_file,
            )
            await publish(
                job_state,
                build_error_event(
                    job_id=job_id,
                    detail="Research finished but report.json was not saved under the job output directory.",
                    error_type="report_not_saved",
                    retryable=False,
                    stage="background_research",
                ),
            )
        else:
            job_state.status = JobStatus.COMPLETED
            write_job_status(job_id, JobStatus.COMPLETED, query)
            with SessionLocal() as db:
                mark_job_status(db, job_id=job_id, status=JobStatus.COMPLETED)
                save_completed_report(db, job_id=job_id, user_id=user_id, query=query)
            logger.info("Job %s completed", job_id)
    except asyncio.CancelledError:
        job_state.status = JobStatus.INTERRUPTED
        write_job_status(job_id, JobStatus.INTERRUPTED, query)
        with SessionLocal() as db:
            mark_job_status(db, job_id=job_id, status=JobStatus.INTERRUPTED)
        raise
    except Exception as e:
        job_state.status = JobStatus.FAILED
        write_job_status(job_id, JobStatus.FAILED, query)
        error_event = build_exception_error_event(job_id, "background_research", e)
        with SessionLocal() as db:
            mark_job_status(
                db,
                job_id=job_id,
                status=JobStatus.FAILED,
                error=error_event.get("errorText"),
            )
        logger.exception(
            "Background research job failed job_id=%s message_count=%d query=%r error_type=%s retryable=%s",
            job_id,
            len(messages_dict),
            preview_text(query),
            error_event["errorType"],
            error_event["retryable"],
        )
        await publish(job_state, {"__bg_error__": error_event})
    finally:
        await publish_done(job_state)
        JOBS.pop(job_id, None)

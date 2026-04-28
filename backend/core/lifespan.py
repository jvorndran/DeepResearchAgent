"""FastAPI lifespan: orchestrator startup and interrupted-job cleanup."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import select

from agents.orchestrator import create_orchestrator
from core.database import ResearchJob, SessionLocal, init_db
from core.paths import OUTPUT_BASE_DIR
from mcp_clients.fred_mcp_client import create_fred_mcp_client
from services.job_status import read_job_status, write_job_status
from services.report_library import mark_job_status
from services.research_types import JobStatus

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()

    if OUTPUT_BASE_DIR.exists():
        for job_dir in OUTPUT_BASE_DIR.iterdir():
            if not job_dir.is_dir():
                continue
            d = read_job_status(job_dir.name)
            if d and d.get("status") == JobStatus.RUNNING.value:
                logger.warning(
                    "Job %s was running at startup — marking interrupted",
                    job_dir.name,
                )
                write_job_status(job_dir.name, JobStatus.INTERRUPTED, d.get("query", ""))

    with SessionLocal() as db:
        running_jobs = db.scalars(
            select(ResearchJob).where(ResearchJob.status == JobStatus.RUNNING.value)
        ).all()
        for job in running_jobs:
            logger.warning(
                "Database job %s was running at startup — marking interrupted",
                job.id,
            )
            write_job_status(job.id, JobStatus.INTERRUPTED, job.query)
            mark_job_status(db, job_id=job.id, status=JobStatus.INTERRUPTED)

    logger.info("Initializing orchestrator agent (MCP connections, tool registration)...")
    fred_client = await create_fred_mcp_client()
    async with fred_client.session("fred") as fred_session:
        logger.info(
            "FRED MCP: persistent stdio session (required — one Node process for all FRED tool calls)"
        )
        app.state.agent = await create_orchestrator(fred_session=fred_session)
        logger.info("Orchestrator ready.")
        yield

"""FastAPI lifespan: orchestrator startup and interrupted-job cleanup."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from agents.orchestrator import create_orchestrator
from core.paths import OUTPUT_BASE_DIR
from services.job_status import read_job_status, write_job_status
from services.research_types import JobStatus

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
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

    logger.info("Initializing orchestrator agent (MCP connections, tool registration)...")
    app.state.agent = await create_orchestrator()
    logger.info("Orchestrator ready.")
    yield

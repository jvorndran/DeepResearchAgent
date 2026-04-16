"""Persist job status to outputs/{job_id}/status.json."""

import json
import os
from datetime import datetime, timezone

from core.paths import OUTPUT_BASE_DIR
from services.research_types import JobStatus


def write_job_status(job_id: str, status: JobStatus, query: str = "") -> None:
    """Write/overwrite status.json atomically. Creates outputs dir if needed."""
    outputs_dir = OUTPUT_BASE_DIR / job_id
    outputs_dir.mkdir(parents=True, exist_ok=True)
    tmp = outputs_dir / "status.json.tmp"
    final = outputs_dir / "status.json"
    tmp.write_text(
        json.dumps(
            {
                "job_id": job_id,
                "status": status.value,
                "query": query,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        ),
        encoding="utf-8",
    )
    os.replace(tmp, final)  # atomic rename (POSIX guarantee)


def read_job_status(job_id: str) -> dict | None:
    try:
        return json.loads((OUTPUT_BASE_DIR / job_id / "status.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None

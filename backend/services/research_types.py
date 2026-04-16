"""In-memory research job types (SSE fan-out + background task handle)."""

import asyncio
from dataclasses import dataclass, field
from enum import Enum


class JobStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


@dataclass
class JobState:
    job_id: str
    status: JobStatus
    query: str
    task: asyncio.Task | None = None
    # Every processed SSE event dict is appended here so reconnect can replay
    events_log: list = field(default_factory=list)
    # One asyncio.Queue per active SSE subscriber
    _subscriber_queues: list = field(default_factory=list)
    subscriber_count: int = 0

"""
Runtime context for the Deep Research Agent pipeline.

ResearchContext is passed at agent.ainvoke() / agent.astream() time and
auto-propagates to all subagents. Tools access it via ToolRuntime[ResearchContext].
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ResearchContext:
    """Per-run configuration injected into the agent at invoke time."""
    job_id: str
    output_dir: Optional[str] = None   # Absolute path: backend/outputs/{job_id}
    data_dir: Optional[str] = None     # Absolute path: backend/data/{job_id}
    user_id: Optional[str] = None
    preferences: Optional[dict] = field(default_factory=dict)

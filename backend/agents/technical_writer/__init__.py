"""
Technical Writer subagent (Deep Agents).

Synthesizes research reports from prior-stage outputs and produces report.json.
"""

from .subagent import TECHNICAL_WRITER_SUBAGENT
from .tools import (
    plan_report_structure,
    validate_research_report_file,
    write_research_report,
)

__all__ = [
    "TECHNICAL_WRITER_SUBAGENT",
    "plan_report_structure",
    "validate_research_report_file",
    "write_research_report",
]

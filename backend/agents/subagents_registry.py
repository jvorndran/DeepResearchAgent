"""
Static Deep Agents subagent specs shared by the orchestrator.

Root human-in-the-loop uses only request_research_approval + Command(resume=...);
interrupt_on is intentionally unset on create_deep_agent so subagents are not paused
by inherited interrupt maps.

The general-purpose subagent must be declared with tools=[] so the host chat tools
are not merged into it (deepagents merges host tools when tools is omitted).
"""

from .quantitative_developer import QUANT_DEVELOPER_SUBAGENT
from .technical_writer import TECHNICAL_WRITER_SUBAGENT
from .quality_analyst import QUALITY_ANALYST_SUBAGENT

GENERAL_PURPOSE_SUBAGENT = {
    "name": "general-purpose",
    "description": (
        "Use this agent only for overflow context-isolation tasks when no specialized "
        "subagent fits. It can summarize or reformat intermediate results. Do not use "
        "it for the main data → quant → writer → QA pipeline."
    ),
    "system_prompt": """
You are the general-purpose fallback subagent for the financial research pipeline.

Use this role only when the orchestrator needs isolated reasoning that does not fit a
specialized subagent. Do not fetch external financial data, write reports, or execute
code when one of the named specialist agents can do that better.

Deep Agents middleware may still expose standard file or shell tools on this graph.
You must not use them: return concise text summaries only and use no tools unless
the orchestrator explicitly required a tool-using task for this overflow step.
""",
    "tools": [],
    "model": "google_genai:gemini-3.1-flash-lite-preview",
}

SPECIALIST_SUBAGENTS_STATIC = [
    QUANT_DEVELOPER_SUBAGENT,
    TECHNICAL_WRITER_SUBAGENT,
    QUALITY_ANALYST_SUBAGENT,
]

__all__ = [
    "GENERAL_PURPOSE_SUBAGENT",
    "SPECIALIST_SUBAGENTS_STATIC",
    "QUANT_DEVELOPER_SUBAGENT",
    "TECHNICAL_WRITER_SUBAGENT",
    "QUALITY_ANALYST_SUBAGENT",
]

"""
Orchestrator Agent (Deep Agents Framework)

The Orchestrator is the main coordinator of the entire research workflow.
It uses LangChain's Deep Agents SDK to delegate tasks to specialized subagents,
manage retry logic, and maintain conversation context.

Role: Project Manager / Research Director
Model: Gemini 3.0 Flash Preview (excellent at reasoning and delegation)

Responsibilities:
- Parse and understand complex research queries
- Determine which subagents to delegate to and in what order
- Manage workflow state and retry logic
- Coordinate between multiple subagents
- Ensure data doesn't bloat the context window
- Return final artifacts to the user

Subagents it can delegate to:
- Data Engineer: For fetching and processing data
- Quantitative Developer: For code generation and execution
- Technical Writer: For report synthesis
- Quality Analyst: For final review
"""

import logging
import warnings
from pathlib import Path

# Suppress langchain_google_genai schema-key warnings ($schema, additionalProperties
# are stripped when converting Pydantic tool schemas for the Gemini API — harmless)
logging.getLogger("langchain_google_genai._function_utils").setLevel(logging.ERROR)

# Suppress Pydantic serialization warning for ResearchContext passed as graph context.
# The deepagents SDK types the 'context' field as None in its state schema; passing
# a ResearchContext object triggers a noisy UserWarning but causes no runtime error.
warnings.filterwarnings(
    "ignore",
    message=r"Pydantic serializer warnings",
    category=UserWarning,
)

from typing import Any, Dict, AsyncIterator  # Dict kept for graph_input annotation
from deepagents import create_deep_agent
from deepagents.backends import LocalShellBackend
from langgraph.checkpoint.memory import MemorySaver

# Import subagent configurations from separate files
from .data_engineer import get_data_engineer_subagent, MCPTimeoutError
from .quantitative_developer import QUANT_DEVELOPER_SUBAGENT
from .technical_writer import TECHNICAL_WRITER_SUBAGENT
from .quality_analyst import QUALITY_ANALYST_SUBAGENT
from .chat_surface_tool import emit_chat_message
from core.context import ResearchContext


_BACKEND_DIR = Path(__file__).resolve().parent.parent
_WORKSPACE_DIR = _BACKEND_DIR.parent
_CHECKPOINTER = MemorySaver()


# =============================================================================
# ORCHESTRATOR SYSTEM PROMPT
# =============================================================================

ORCHESTRATOR_SYSTEM_PROMPT = """
# ROLE
You are the **Orchestrator (Research Director)**. You coordinate end-to-end financial research by delegating tasks to specialized subagents. You plan, monitor, and synthesize; you do not analyze raw data yourself.

# CORE RULES
1. **DATA DECOUPLING:** NEVER ingest or pass raw financial data arrays. Use only metadata, schemas, and file paths.
2. **RETRY LIMIT:** Maximum 3 retries per subagent. If a subagent fails 3 times, abort gracefully.
3. **MANDATORY UI:** Call `emit_chat_message(markdown=...)` exactly once per turn to speak to the user.
4. **PATH NORMALIZATION:** All paths must be absolute with forward slashes only. Never use backslashes in paths.

# PHASE 1: INTAKE & CLARIFICATION
- **Clarify:** If tickers, metrics, or horizon are missing/vague, ask questions via `emit_chat_message`. Do NOT call `task()`.
- **Confirm:** Once fully specified (tickers, metrics, and horizon provided), call `emit_chat_message` with:
  *I now have what I need to proceed. Please click **Commence Deep Research** below to begin.*
  **Then STOP.** Do not call `task()` on this turn.
- **Execute:** On the NEXT turn (after user confirms), call `task(subagent_type="data-engineer", description="...", data={})` to delegate to **data-engineer**.

# PHASE 2-6: EXECUTION WORKFLOW

1. **data-engineer:** Fetch data and schemas. Store schemas in Graph State.
2. **quant-developer:** Write and run Python code. Receives schemas and paths. Saves `outputs/{job_id}/charts.json`.
   - When delegating to `quant-developer`, include absolute paths for all tools.
   - If the analysis uses quarterly labels, explicitly require `YYYY Qn` formatting and tell the quant developer not to use unsupported `strftime` directives like `%Q`.
3. **technical-writer:** Synthesize markdown report. Pass:
   - `charts_json_path` (absolute path to charts.json)
   - `execution_summary` (full JSON from quant-developer, including `statistical_summary`)
   - `data_sources` as JSON array, populated from data engineer output:
     `[{"provider": "FRED/FMP", "description": "...", "series_ids": [...], "date_range": {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}, "row_count": N}]`
   - `original_query`, `job_id`
   TW reads charts from disk. `charts_json_path` must be an absolute path.
4. **quality-analyst:** Validate `outputs/{job_id}/report.json`. If rejected, follow recovery skills.
5. **Handoff:** Confirm final `report.json` is saved and approved.

# TASK TOOL USAGE
- You delegate via `task(subagent_type="...", description="...")`.
- The `subagent_type` MUST be one of: "data-engineer", "quant-developer", "technical-writer", "quality-analyst".
- The `description` must be self-contained: include all needed context, the artifact paths the subagent should use, and the exact output you expect back.
- For `quant-developer`, the `description` must spell out path and label expectations so the subagent does not waste retries:
  - Use absolute paths for all tools including `execute`, `pandas.read_csv`, and filesystem tools
  - Quarterly labels should be formatted as `YYYY Qn`, never with `%Q`
- Treat each task invocation as stateless. Do not assume follow-up turns with the same subagent.

# TONE
Professional, analytical, and authoritative. Always expose your current pipeline state to the user.
"""


GENERAL_PURPOSE_SUBAGENT = {
    "name": "general-purpose",
    "description": (
        "Use this agent only for overflow context-isolation tasks when no specialized "
        "subagent fits. It can summarize, reformat, or inspect intermediate results "
        "without touching the host filesystem or running shell commands."
    ),
    "system_prompt": """
You are the general-purpose fallback subagent for the financial research pipeline.

Use this role only when the orchestrator needs isolated reasoning that does not fit a
specialized subagent. Do not fetch external financial data, write reports, or execute
code when one of the named specialist agents can do that better.

Filesystem and shell tools are blocked for this subagent. Return concise summaries only.
""",
    "tools": [],
    "model": "google_genai:gemini-3-flash-preview",
}


# =============================================================================
# CREATE ORCHESTRATOR AGENT
# =============================================================================

async def create_orchestrator():
    """Create the orchestrator agent with all subagents, including FMP MCP tools."""
    data_engineer = await get_data_engineer_subagent()

    return create_deep_agent(
        model="google_genai:gemini-3-flash-preview",
        system_prompt=ORCHESTRATOR_SYSTEM_PROMPT,
        tools=[emit_chat_message],
        subagents=[
            GENERAL_PURPOSE_SUBAGENT,
            data_engineer,
            QUANT_DEVELOPER_SUBAGENT,
            TECHNICAL_WRITER_SUBAGENT,
            QUALITY_ANALYST_SUBAGENT
        ],
        backend=LocalShellBackend(
            root_dir=_WORKSPACE_DIR,
            virtual_mode=False,
            inherit_env=True,
        ),
        context_schema=ResearchContext,
        checkpointer=_CHECKPOINTER,
        memory=[str(_BACKEND_DIR / "AGENTS.md")],
        skills=[str(_BACKEND_DIR / "skills" / "orchestrator")],
        name="orchestrator"
    )


# =============================================================================
# PUBLIC API FUNCTIONS
# =============================================================================

async def run_research(
    query: str,
    job_id: str,
    messages: list[dict] | None = None,
    agent: Any | None = None,
) -> Dict[str, Any]:
    """
    Run the complete research workflow and return final results.

    This is the main entrypoint for executing a research job.

    Args:
        query: The research query from the user
        job_id: Unique identifier for this research job
        messages: Optional full message history for multi-turn conversations.
                  When provided, overrides the default single-message format.

    Returns:
        Dict containing:
        - status: "completed" or "failed"
        - job_id: The job identifier
        - response: The final response content
        - result: Full result object from the agent
        - error: Error message if failed

    Example:
        >>> result = await run_research(
        ...     query="Analyze correlation between TSMC capex and wafer shipments",
        ...     job_id="abc123"
        ... )
        >>> print(result["status"])
        'completed'
    """
    try:
        if agent is None:
            agent = await create_orchestrator()

        if messages is None:
            messages = [{"role": "user", "content": f"Job ID: {job_id}\n\nResearch Query: {query}"}]

        ctx = ResearchContext(
            job_id=job_id,
            output_dir=str(_BACKEND_DIR / "outputs" / job_id),
            data_dir=str(_BACKEND_DIR / "data" / job_id),
        )

        config = {"configurable": {"thread_id": job_id}}
        result = await agent.ainvoke({"messages": messages}, context=ctx, config=config)

        messages = result.get("messages", [])
        if messages:
            last_message = messages[-1]
            if hasattr(last_message, 'content'):
                content = last_message.content
                if isinstance(content, list):
                    # Extract text parts from content blocks
                    text_parts = [
                        part.get("text", "") if isinstance(part, dict) else str(part)
                        for part in content
                    ]
                    response_content = "".join(text_parts)
                else:
                    response_content = str(content)
            else:
                response_content = str(last_message)

            return {
                "status": "completed",
                "job_id": job_id,
                "response": response_content,
                "result": result
            }

        return {
            "status": "completed",
            "job_id": job_id,
            "result": result
        }

    except MCPTimeoutError as e:
        return {
            "status": "failed",
            "job_id": job_id,
            "error": f"MCP timeout: {e}"
        }
    except Exception as e:
        return {
            "status": "failed",
            "job_id": job_id,
            "error": str(e)
        }


async def stream_research(
    query: str,
    job_id: str,
    messages: list[dict] | None = None,
    agent: Any | None = None,
) -> AsyncIterator[Dict[str, Any]]:
    """
    Stream the research workflow progress in real-time.

    Use this for WebSocket connections or when you want to show
    live progress updates to the user.

    Args:
        query: The research query from the user
        job_id: Unique identifier for this research job
        messages: Optional full message history for multi-turn conversations.
                  When provided, overrides the default single-message format.

    Yields:
        Dict events from the agent execution showing:
        - Tool calls being made
        - Subagent delegations
        - Progress through the workflow

    Example:
        >>> async for event in stream_research(query="...", job_id="abc123"):
        ...     print(event)
    """
    if agent is None:
        agent = await create_orchestrator()

    if messages is None:
        messages = [{"role": "user", "content": f"Job ID: {job_id}\n\nResearch Query: {query}"}]

    ctx = ResearchContext(
        job_id=job_id,
        output_dir=str(_BACKEND_DIR / "outputs" / job_id),
        data_dir=str(_BACKEND_DIR / "data" / job_id),
    )

    try:
        config = {"configurable": {"thread_id": job_id}}
        graph_input: Dict[str, Any] = {"messages": messages}

        async for event in agent.astream(
            graph_input,
            context=ctx,
            config=config,
            stream_mode=["updates", "messages", "custom"],
            subgraphs=True,
            version="v2",
        ):
            yield event
    except MCPTimeoutError as e:
        yield {"error": {"type": "mcp_timeout", "message": str(e)}}


__all__ = ["create_orchestrator", "run_research", "stream_research"]

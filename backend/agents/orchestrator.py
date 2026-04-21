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
import asyncio
import google.genai.errors

logger = logging.getLogger(__name__)

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

from typing import Any, AsyncIterator, Dict

from mcp import ClientSession
from deepagents import create_deep_agent
from deepagents.backends import LocalShellBackend
from langgraph.checkpoint.memory import MemorySaver
# Import subagent configurations from separate files
from .data_engineer import FredMCPRequiredError, get_data_engineer_subagent, MCPTimeoutError
from .graph_input import resolve_graph_input
from .subagents_registry import GENERAL_PURPOSE_SUBAGENT, SPECIALIST_SUBAGENTS_STATIC
from .chat_surface_tool import emit_chat_message
from .request_research_approval_tool import request_research_approval
from core.context import ResearchContext

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_WORKSPACE_DIR = _BACKEND_DIR.parent
_CHECKPOINTER = MemorySaver()


# =============================================================================
# ORCHESTRATOR SYSTEM PROMPT
# =============================================================================

ORCHESTRATOR_SYSTEM_PROMPT = """
# ROLE
You are the **Orchestrator (Research Director)**. You coordinate end-to-end financial research by delegating to specialized subagents. You do not analyze raw data yourself.

# CORE RULES
1. **DATA DECOUPLING:** NEVER ingest or pass raw financial data arrays. Use only metadata, schemas, and file paths.
2. **RETRY LIMIT:** Maximum 3 retries per subagent. If a subagent fails 3 times, abort gracefully.
3. **MANDATORY UI:** Call `emit_chat_message(markdown=...)` exactly once per turn to speak to the user.
4. **SPECIALISTS FOR THE PIPELINE:** Do not use `general-purpose` for the main data → quant → writer → QA pipeline. Reserve it for rare overflow tasks only.
5. **PATHS & ARTIFACTS:** Follow `AGENTS.md` and `skills/orchestrator/*.md` for job id copying, absolute paths, `%Q` avoidance, and `data_sources` JSON shape.

# PHASE 1: INTAKE & CLARIFICATION
- **Clarify:** If tickers, metrics, or horizon are missing/vague, ask questions via `emit_chat_message`. Do NOT call `task()`.
- **Confirm:** Once fully specified, call `emit_chat_message` with:
  *I now have what I need to proceed. Please click **Commence Deep Research** below to begin.*
  Then immediately call `request_research_approval(summary="<one-sentence summary of what will be researched>")`. Do NOT call `task()` before it returns.
- **Execute:** After `request_research_approval` returns, call `task(subagent_type="data-engineer", description="...", data={})`.

# PHASE 2–6: EXECUTION ORDER
1. **data-engineer** → 2. **quant-developer** → 3. **technical-writer** → 4. **quality-analyst** → confirm `report.json` is saved and approved.

# TASK TOOL
Delegate with `task(subagent_type="...", description="...")`. The `subagent_type` MUST be one of:
`data-engineer`, `quant-developer`, `technical-writer`, `quality-analyst`.

Each `description` must be self-contained (context, absolute paths, expected outputs). Treat each `task()` as stateless.

# TONE
Professional, analytical, and authoritative. Expose your current pipeline state to the user.
"""


# =============================================================================
# CREATE ORCHESTRATOR AGENT
# =============================================================================


async def create_orchestrator(fred_session: ClientSession | None = None):
    """Create the orchestrator agent with all subagents, including FMP MCP tools.

    **FRED MCP is required** for the data-engineer subagent: tool load and GDP probe must succeed.

    Pass ``fred_session`` from app lifespan (``async with fred_client.session("fred")``) so
    FRED tools reuse one stdio MCP session. If omitted (e.g. CLI), each FRED tool call spawns a
    new Node subprocess; FRED must still be reachable or startup raises ``FredMCPRequiredError``.

    Root human-in-the-loop uses only `request_research_approval` plus checkpoint resume
    (`Command(resume=...)`). `interrupt_on` is intentionally unset on `create_deep_agent`
    so subagents do not inherit root interrupt behavior that would pause file/shell work.
    """
    data_engineer = await get_data_engineer_subagent(fred_session=fred_session)

    return create_deep_agent(
        model="deepseek:deepseek-chat",
        system_prompt=ORCHESTRATOR_SYSTEM_PROMPT,
        tools=[emit_chat_message, request_research_approval],
        subagents=[
            GENERAL_PURPOSE_SUBAGENT,
            data_engineer,
            *SPECIALIST_SUBAGENTS_STATIC,
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
        name="orchestrator",
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

        graph_input = await resolve_graph_input(agent, config, messages)
        result = await agent.ainvoke(graph_input, context=ctx, config=config)

        messages = result.get("messages", [])
        if messages:
            last_message = messages[-1]
            if hasattr(last_message, "content"):
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
                "result": result,
            }

        return {"status": "completed", "job_id": job_id, "result": result}

    except MCPTimeoutError as e:
        return {"status": "failed", "job_id": job_id, "error": f"MCP timeout: {e}"}
    except Exception as e:
        return {"status": "failed", "job_id": job_id, "error": str(e)}


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

        graph_input = await resolve_graph_input(agent, config, messages)

        max_retries = 3
        retry_delay = 2
        for attempt in range(max_retries + 1):
            try:
                # If we are retrying (attempt > 0), pass None as graph input to resume
                # from the last checkpoint.
                current_input = graph_input if attempt == 0 else None
                async for event in agent.astream(
                    current_input,
                    context=ctx,
                    config=config,
                    stream_mode=["updates", "messages", "custom"],
                    subgraphs=True,
                    version="v2",
                ):
                    yield event
                break  # Success
            except Exception as e:
                # Catch transient 500/503 errors from Google GenAI SDK.
                err_msg = str(e).lower()
                is_transient = (
                    "500 internal" in err_msg
                    or "503 service unavailable" in err_msg
                    or isinstance(e, google.genai.errors.ServerError)
                )
                if is_transient and attempt < max_retries:
                    logger.warning(
                        "Transient API error for job %s (attempt %d/%d): %s. Retrying in %ds...",
                        job_id,
                        attempt + 1,
                        max_retries,
                        e,
                        retry_delay,
                    )
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2
                    continue
                raise
    except MCPTimeoutError as e:
        yield {"error": {"type": "mcp_timeout", "message": str(e)}}


__all__ = ["FredMCPRequiredError", "create_orchestrator", "run_research", "stream_research"]

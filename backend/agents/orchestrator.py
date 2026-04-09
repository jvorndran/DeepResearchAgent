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

from typing import Any, Dict, AsyncIterator
from deepagents import create_deep_agent
from deepagents.backends import LocalShellBackend
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

# Import subagent configurations from separate files
from .data_engineer import get_data_engineer_subagent, MCPTimeoutError
from .quantitative_developer import QUANT_DEVELOPER_SUBAGENT
from .technical_writer import TECHNICAL_WRITER_SUBAGENT
from .quality_analyst import QUALITY_ANALYST_SUBAGENT
from .chat_surface_tool import emit_chat_message
from core.context import ResearchContext

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_CHECKPOINTER = MemorySaver()


# =============================================================================
# ORCHESTRATOR SYSTEM PROMPT
# =============================================================================

ORCHESTRATOR_SYSTEM_PROMPT = """
# ROLE AND DIRECTIVE
You are the **Orchestrator (Research Director)** for an Asynchronous Deep Financial Research platform. You manage a team of specialized AI subagents.

Your primary directive is to coordinate end-to-end macroeconomic and stock market research. You do not analyze data yourself; you plan, delegate, monitor, and synthesize.

## User-visible chat (`emit_chat_message`) — mandatory
The web UI renders **only** this markdown — not your raw model stream. Call **`emit_chat_message(markdown=...)` exactly once** per assistant turn that speaks to the user.

- **Clarifying (questions only):** Short intro + markdown bullet questions. **Do not** call `task()` on this turn — no data fetch yet.
- **Ready to run research (intake complete):** After the user has answered your questions **or** the first user message was fully specified, you must:
  1. Call `emit_chat_message` with a brief acknowledgment AND a **final sentence** that tells them to click **Commence Deep Research** below to approve starting data collection. Use this pattern (adapt wording to context):  
     *I now have what I need to proceed. Please click **Commence Deep Research** below to approve and begin pulling data.*
  2. **Immediately after** that tool call, call `task(...)` to delegate to **data-engineer** (first pipeline step). Human-in-the-loop approval runs **before** any subagent executes — the user’s button click approves that `task()` call. **Do not** call `task()` before `emit_chat_message` on this turn.

IMPORTANT: After **Phase 1 — Intake** is complete, you must delegate all substantive work to your subagents using the `task()` tool. Never substitute your own analysis for sandbox-backed outputs. Your job is to:
1. Run intake (mandatory structure below): clarify when needed, or confirm a **fully specified** request
2. Break the request into actionable tasks and delegate each via `task()`
3. Coordinate results and report back to the user

**Clarification exception:** On the **first** user turn of a job, you **must not** call `task()` until intake is done. If the request is **not** fully specified, your first turn is **questions only** (`emit_chat_message`) — **no** `task()`. If the request **is** fully specified (rubric below), one assistant turn may run `emit_chat_message` (with the Commence Deep Research line) and then `task()` as above. When the user’s latest message **answers your intake questions**, treat intake as complete: run **`emit_chat_message` (with Commence line) then `task()`** in that turn — do not re-run full intake.

# SUBAGENT ROSTER
1. **data-engineer:** Fetches raw data from FMP/FRED APIs. Returns ONLY storage paths and deterministic pure-Python data schemas.
2. **quant-developer:** Writes and executes Python code in a secure sandbox. Receives schemas and paths, outputs mathematical findings and Recharts-compatible JSON.
3. **technical-writer:** Synthesizes the final Markdown report using the quant-developer's outputs and references the generated JSON charts.
4. **quality-analyst:** Validates the final report for formatting and compliance.

# STRICT OPERATING RULES

> **RULE 1: THE DATA DECOUPLING LAW**
> You must NEVER ingest, request, or pass raw financial data arrays through your context window. You operate purely on metadata, deterministic schemas, and file storage paths. Store schemas in your Graph State to pass to subagents.

> **RULE 2: THE RULE OF THREE (RETRY LIMIT)**
> If a subagent returns an error, you may instruct them to retry with corrected parameters. You are strictly limited to 3 retries per subagent. If a subagent fails 3 times, gracefully abort the workflow.

> **RULE 3: FACTUALITY OVER FLUENCY**
> You must strictly enforce that no subagent hallucinates a financial metric. Every number in the final output must map directly to the sandbox execution output.

# STANDARD OPERATING PROCEDURE (WORKFLOW)

## Phase 1: Intake & Clarification (MANDATORY FIRST)

First user message of a job: output the **Intake block** before any `task()`. Prefer asking over guessing: do not invent tickers, FRED series, or dates. If the horizon is missing, ask (e.g. offer "last 5 calendar years?" as an option). **Do not ask chart type** — infer: trend→line, compare→bar, correlation→scatter, breakdown→pie.

**Fully specified** — the only case where **Questions** may be a single line `None — proceeding to execution per rubric below.` — means the user **explicitly** stated all of: **(1)** tickers or unambiguous macro/FRED IDs, **(2)** concrete metric(s)/indicator(s), **(3)** a definite horizon (named years, "last N years", from–to, as-of). Vague scope ("tech stocks", "the market", "recently") → ask; no `task()` on that turn until they answer.

**Intake (internal):** Track tickers/FRED, metric, horizon, assumptions — prefer asking over guessing. For **chat**, put only the concise questions (or none-line) inside `emit_chat_message`, not the full internal checklist.

**Examples:** "AAPL annual revenue, last 5 years" → `emit_chat_message` confirming scope, then `task()`. "Tech stocks" or "MSFT operating margin" with no period → ask via `emit_chat_message` only.

**User replied to your questions:** follow the “Ready to run research” two-step (`emit_chat_message` with Commence line, then `task()`).

## Phase 2: Data Acquisition
- Delegate to **data-engineer** using task(name="data-engineer", task="..."). Request the specific datasets needed.
- Receive the data schemas and file paths. Store these in your state memory.

## Phase 3: Quantitative Analysis & Chart Generation
- Delegate to **quant-developer** using task(name="quant-developer", task="...").
- Pass: schemas, Windows file paths, analysis goal, and job_id.
- The quant-developer saves `outputs/{job_id}/charts.json` (dict keyed by snake_case chart ID) and prints chart IDs in its stdout summary.
- Store the chart IDs from the stdout summary in your state.

See the query-type workflow skills (`macro-correlation-workflow`, `equity-earnings-workflow`, `sector-comparison-workflow`) for specific analysis instructions and chart type recommendations per query type.

## Phase 4: Report Synthesis
- Delegate to **technical-writer** using task(name="technical-writer", task="...").
- Pass ONLY: `charts_json_path`, `execution_summary` (quant stdout JSON), `data_sources` (JSON list), `original_query`, `job_id`.
- Do NOT pass chart data — the technical writer reads charts.json directly from disk.
- `data_sources` must be a populated JSON list — never leave fields as null:
  ```json
  [{"provider": "FMP MCP Server", "description": "Annual income for AAPL", "tickers": ["AAPL"], "date_range": {"start": "2021", "end": "2025"}, "row_count": 5}]
  ```
- `job_id` is in your initial message. Always pass it explicitly in task() instructions — subagents use it to construct output paths.

## Phase 5: Quality Assurance
- Delegate to **quality-analyst** using task(name="quality-analyst", task="...").
- Pass the `report_json_path` (e.g. `outputs/{job_id}/report.json`).
- If `status: approved` → proceed to Phase 6.
- If `status: rejected` → see the **`qa-rejection-recovery`** skill for re-delegation instructions and Rule of Three enforcement.

## Phase 6: Final Handoff
- Output the final completion status, confirming that `outputs/{job_id}/report.json` has been saved and approved.
- The report.json is the single canonical artifact: it contains the markdown narrative with inline `<!-- CHART:id -->` markers, chart definitions, data sources, and metadata.

# TONE AND PERSONA
Professional, highly analytical, and authoritative. Expose your thought process and current state to the user so they have full observability of the pipeline.
"""


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
            data_engineer,
            QUANT_DEVELOPER_SUBAGENT,
            TECHNICAL_WRITER_SUBAGENT,
            QUALITY_ANALYST_SUBAGENT
        ],
        backend=LocalShellBackend(),  # gives subagents write_file, execute, read_file, ls, glob, grep
        context_schema=ResearchContext,
        checkpointer=_CHECKPOINTER,
        interrupt_on={
            "task": {"allowed_decisions": ["approve", "reject"]},
        },
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

        result = await agent.ainvoke({"messages": messages}, context=ctx)

        messages = result.get("messages", [])
        if messages:
            last_message = messages[-1]
            response_content = last_message.content if hasattr(last_message, 'content') else str(last_message)

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
    resume: Dict[str, Any] | None = None,
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
        graph_input: Dict[str, Any] | Command
        if resume is not None:
            graph_input = Command(resume=resume)
        else:
            graph_input = {"messages": messages}

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

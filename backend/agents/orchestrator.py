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

# Suppress langchain_google_genai schema-key warnings ($schema, additionalProperties
# are stripped when converting Pydantic tool schemas for the Gemini API — harmless)
logging.getLogger("langchain_google_genai._function_utils").setLevel(logging.ERROR)

from typing import Any, Dict, AsyncIterator
from deepagents import create_deep_agent
from deepagents.backends import LocalShellBackend

# Import subagent configurations from separate files
from .data_engineer import get_data_engineer_subagent
from .quantitative_developer import QUANT_DEVELOPER_SUBAGENT
from .technical_writer import TECHNICAL_WRITER_SUBAGENT
from .quality_analyst import QUALITY_ANALYST_SUBAGENT


# =============================================================================
# ORCHESTRATOR SYSTEM PROMPT
# =============================================================================

ORCHESTRATOR_SYSTEM_PROMPT = """
# ROLE AND DIRECTIVE
You are the **Orchestrator (Research Director)** for an Asynchronous Deep Financial Research platform. You manage a team of specialized AI subagents.

Your primary directive is to coordinate end-to-end macroeconomic and stock market research. You do not analyze data yourself; you plan, delegate, monitor, and synthesize.

IMPORTANT: You must ALWAYS delegate work to your subagents using the task() tool. Never attempt to do the work yourself. Your job is to:
1. Break down the user's request into actionable tasks
2. Delegate each task to the appropriate subagent via task()
3. Coordinate results and report back to the user

# SUBAGENT ROSTER
1. **data-engineer:** Fetches raw data from FMP/FRED APIs. Returns ONLY storage paths and deterministic pure-Python data schemas.
2. **quant-developer:** Writes and executes Python code in a secure sandbox. Receives schemas and paths, outputs mathematical findings and Recharts-compatible JSON. Uses OpenAI o1.
3. **technical-writer:** Synthesizes the final Markdown report using the quant-developer's outputs and references the generated JSON charts.
4. **quality-analyst:** Validates the final report for hallucinations and compliance.

# STRICT OPERATING RULES

> **RULE 1: THE DATA DECOUPLING LAW**
> You must NEVER ingest, request, or pass raw financial data arrays through your context window. You operate purely on metadata, deterministic schemas, and file storage paths. Store schemas in your Graph State to pass to subagents.

> **RULE 2: THE RULE OF THREE (RETRY LIMIT)**
> If a subagent returns an error, you may instruct them to retry with corrected parameters. You are strictly limited to 3 retries per subagent. If a subagent fails 3 times, gracefully abort the workflow.

> **RULE 3: FACTUALITY OVER FLUENCY**
> You must strictly enforce that no subagent hallucinates a financial metric. Every number in the final output must map directly to the sandbox execution output.

# STANDARD OPERATING PROCEDURE (WORKFLOW)

## Phase 1: Intake & Clarification (STRICT CHECKLIST)
Before initiating any backend data retrieval or delegating to subagents, you MUST verify that the user's request satisfies the following checklist. Only ask the user if the request is truly ambiguous. **Do NOT ask about visualization type** — infer it from context (revenue/trend → line chart, comparison → bar chart, correlation → scatter plot, breakdown → pie chart).
- [ ] Target assets or tickers are explicitly defined. If missing, ask.
- [ ] The exact macroeconomic indicators or metrics are specified. If missing, ask.
- [ ] The historical timeframe is defined. If missing, default to the last 5 years and proceed.
- [x] Visualization type: **Infer automatically** — do NOT ask the user. Defaults: trends/revenue → line, comparisons → bar, correlations → scatter, breakdowns → pie.

## Phase 2: Data Acquisition
- Delegate to **data-engineer** using task(name="data-engineer", task="..."). Request the specific datasets needed.
- Receive the data schemas and file paths. Store these in your state memory.

## Phase 3: Quantitative Analysis & Chart Generation
- Delegate to **quant-developer** using task(name="quant-developer", task="...").
- Pass the schemas, storage paths, and exact instructions on the math to perform.
- **CRITICAL CHARTING INSTRUCTION:** Command the quant-developer to save a named chart dict to `outputs/charts.json` (not a flat array). Each key is a snake_case chart ID; each value is a chart definition matching one of three Pydantic variants (AxisChartDef, ScatterChartDef, or PieChartDef). The quant-developer must print the chart IDs in its stdout summary so you can pass them forward.
- Extract the list of chart IDs from the quant-developer's stdout summary and store them in your state.

## Phase 4: Report Synthesis
- Delegate to **technical-writer** using task(name="technical-writer", task="...").
- Pass ONLY: `charts_json_path` (e.g. `outputs/{job_id}/charts.json`), `execution_summary` (the compact stdout JSON from the quant developer), `data_sources` metadata (provider, tickers, date range, row count — small), `original_query`, and `job_id`.
- Do NOT pass chart data arrays or chart summaries — the technical writer reads charts.json directly from disk.
- The technical writer calls `plan_report_structure` then `write_research_report` and produces `outputs/{job_id}/report.json`.

## Phase 5: Quality Assurance
- Delegate to **quality-analyst** using task(name="quality-analyst", task="...").
- Pass the `report_json_path` (e.g. `outputs/{job_id}/report.json`) and the quant-developer's raw execution output.
- The quality analyst loads report.json via Pydantic, validates schema, mandatory elements, chart marker resolution, and compliance. Minor issues (missing disclaimer, footer, broken chart markers) are autonomously patched before a final decision is made.
- If quality-analyst returns `status: approved` → proceed to Phase 6.
- If quality-analyst returns `status: rejected` → extract the `required_fixes` list and re-delegate to **technical-writer** with those fixes included in the task instructions. Apply the Rule of Three: abort after 3 QA rejections.

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
        tools=[],  # Orchestrator uses built-in task() and write_todos()
        subagents=[
            data_engineer,
            QUANT_DEVELOPER_SUBAGENT,
            TECHNICAL_WRITER_SUBAGENT,
            QUALITY_ANALYST_SUBAGENT
        ],
        backend=LocalShellBackend(),  # gives subagents write_file, execute, read_file, ls, glob, grep
        name="orchestrator"
    )


# =============================================================================
# PUBLIC API FUNCTIONS
# =============================================================================

async def run_research(
    query: str,
    job_id: str,
    messages: list[dict] | None = None,
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
        agent = await create_orchestrator()

        if messages is None:
            messages = [{"role": "user", "content": f"Job ID: {job_id}\n\nResearch Query: {query}"}]

        result = await agent.ainvoke({"messages": messages})

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
    agent = await create_orchestrator()

    if messages is None:
        messages = [{"role": "user", "content": f"Job ID: {job_id}\n\nResearch Query: {query}"}]

    async for event in agent.astream({"messages": messages}, stream_mode="updates"):
        yield event


__all__ = ["create_orchestrator", "run_research", "stream_research"]

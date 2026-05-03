"""Technical Writer Deep Agents subagent specification."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
import json
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest

from ..tool_utils import message_tool_name, tool_call_id, tool_call_name, tool_name
from .constants import TECHNICAL_WRITER_SKILLS_DIR
from .tools import (
    plan_report_structure,
    validate_research_report_file,
    write_research_report,
)

_ALLOWED_TOOL_NAMES = {
    "plan_report_structure",
    "write_research_report",
    "validate_research_report_file",
}


def _tool_name(tool: Any) -> str | None:
    return tool_name(tool)


def _tool_call_name(tool_call: Any) -> str | None:
    return tool_call_name(tool_call)


def _tool_call_id(tool_call: Any) -> str:
    return tool_call_id(tool_call, "technical-writer-blocked-tool")


def _message_tool_name(message: Any) -> str | None:
    return message_tool_name(message)


def _message_content(message: Any) -> str:
    content = getattr(message, "content", "")
    return content if isinstance(content, str) else str(content or "")


def _json_from_message(message: Any) -> dict[str, Any] | None:
    content = _message_content(message).strip()
    if not content:
        return None
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _latest_writer_report_path(messages: list[Any]) -> str:
    for message in reversed(messages):
        if _message_tool_name(message) != "write_research_report":
            continue
        parsed = _json_from_message(message)
        if isinstance(parsed, dict) and isinstance(parsed.get("report_path"), str):
            return parsed["report_path"]
    return ""


def _latest_successful_validation(messages: list[Any]) -> dict[str, Any] | None:
    for message in reversed(messages):
        if _message_tool_name(message) != "validate_research_report_file":
            continue
        parsed = _json_from_message(message)
        if isinstance(parsed, dict) and parsed.get("passes_gate") is True:
            return parsed
    return None


def _success_handoff_content(messages: list[Any]) -> str:
    validation = _latest_successful_validation(messages) or {}
    report_path = _latest_writer_report_path(messages)
    chart_ids = (
        (validation.get("charts") or {}).get("defined_charts")
        if isinstance(validation.get("charts"), dict)
        else []
    )
    if not isinstance(chart_ids, list):
        chart_ids = []
    return json.dumps(
        {
            "status": "success",
            "report_json": report_path,
            "chart_ids": chart_ids,
        }
    )


class TechnicalWriterToolBoundaryMiddleware(AgentMiddleware):
    """Expose only report-writing tools to prevent context-heavy file reads."""

    def _only_writer_tools(self, request: ModelRequest) -> ModelRequest:
        if _latest_successful_validation(list(request.messages)):
            return request.override(tools=[])
        tools = [tool for tool in request.tools if _tool_name(tool) in _ALLOWED_TOOL_NAMES]
        if len(tools) == len(request.tools):
            return request
        return request.override(tools=tools)

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        messages = list(request.messages)
        if _latest_successful_validation(messages):
            return ModelResponse(result=[AIMessage(content=_success_handoff_content(messages))])
        return handler(self._only_writer_tools(request))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        messages = list(request.messages)
        if _latest_successful_validation(messages):
            return ModelResponse(result=[AIMessage(content=_success_handoff_content(messages))])
        return await handler(self._only_writer_tools(request))

    def _blocked_tool_message(self, request: ToolCallRequest) -> ToolMessage:
        tool_name = _tool_call_name(request.tool_call) or "unknown_tool"
        return ToolMessage(
            content=(
                f"Blocked tool `{tool_name}` for technical-writer. "
                "Use only plan_report_structure, write_research_report, and "
                "validate_research_report_file. Do not call read_file, glob, "
                "grep, ls, write_file, edit_file, or execute; "
                "plan_report_structure already reads charts.json and returns chart_ids."
            ),
            name=tool_name,
            tool_call_id=_tool_call_id(request.tool_call),
            status="error",
        )

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage],
    ) -> ToolMessage:
        tool_name = _tool_call_name(request.tool_call)
        if tool_name not in _ALLOWED_TOOL_NAMES:
            return self._blocked_tool_message(request)
        return handler(request)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage]],
    ) -> ToolMessage:
        tool_name = _tool_call_name(request.tool_call)
        if tool_name not in _ALLOWED_TOOL_NAMES:
            return self._blocked_tool_message(request)
        return await handler(request)


_TOOL_BOUNDARY_MIDDLEWARE = TechnicalWriterToolBoundaryMiddleware()

TECHNICAL_WRITER_SUBAGENT = {
    "name": "technical-writer",
    "description": """Use this subagent to write and save the final ResearchReport artifact.

    Required first action: call plan_report_structure. Do not inspect files directly.

    Delegate when you need to:
    - Write the full markdown research narrative from execution_summary data
    - Embed chart references (<!-- CHART:id -->) inline in the narrative
    - Validate and save report.json (including static gate via validate_research_report_file)

    Pass ONLY: the charts_json_path, execution_summary (full JSON from quant developer, including
    statistical_summary, or the execution_summary_json path returned by quant-developer), data_sources
    metadata (populated with series_ids, date_range, row_count), and original_query.
    Do NOT pass chart data or raw arrays — the technical writer reads charts.json directly.

    The technical writer writes ALL prose itself. Do not expect the tool to generate content
    from execution_summary — the LLM writes every section with unique, cited analysis.""",
    "system_prompt": """# ROLE
You are the Technical Writer. You synthesize research reports from the `plan_report_structure` result, then write a complete markdown narrative.

# CORE TOOLS
1. `plan_report_structure`: Discover chart IDs from `charts.json`. Call this FIRST.
2. `write_research_report`: Save your finalized markdown to `report.json`.
3. `validate_research_report_file`: Static gate (schema + chart markers). Use `warnings` for non-blocking hints. `auto_patch=True` (default) re-syncs the auto disclaimer footer and strips broken chart markers.

# WORKFLOW
1. **Plan:** Call `plan_report_structure` before any other tool. Note the available `chart_ids` and the `general_rules`.
2. **Draft:** Draft internally, then pass the full markdown narrative directly as the `markdown` argument to `write_research_report`. Do not stream the draft or chart list in assistant message content before tool calls. The `plan_report_structure` result contains
   `execution_summary_for_draft`: dense computed numbers from the quant developer.
   READ this carefully and weave every specific number into the relevant analysis sections —
   exact slopes, r values, peak dates, deltas, p-values, etc. Do not paraphrase vaguely;
   cite the actual computed values in parentheticals (e.g., "slope of -0.05 pp/month", "r = -0.44, p < 0.001").
   Treat the "Exact headline metrics from execution_summary.json" block as controlling facts:
   copy current values, signs, directions, regime labels, explicitly supplied scenario probabilities,
   and company growth rates exactly. Do not substitute older public-memory values or infer an
   inversion/decline when the exact metric says the sign is positive. Scenario helper rows usually
   provide confidence labels, not probabilities; do not invent probability weights, Fed-cut paths,
   product mix estimates, or policy assumptions unless they appear in `execution_summary_for_draft`.
   - Do **not** write a disclaimer section: the pipeline appends a standard legal footer after save.
   - End the body with `## Research Query` (original question) near the bottom; do not duplicate system footer text.
   - `data_sources` must cite only providers evidenced by the handoff or `execution_summary_for_draft`.
     For the current public-source feature set, use exact provider names such as FRED, BLS Public Data,
     Census Data API, World Bank Indicators API, and SEC EDGAR. Do not cite OECD, BIS, IMF, generic
     "Company Filings", or paid/keyed providers unless the handoff explicitly says that provider was used.
3. **Save:** Call `write_research_report` exactly once with this shape:
   - `markdown`
   - `charts_json_path`
   - `data_sources`
   - `original_query`
   - optional: `title`, `executive_summary`, `analysis_type`
   - Do **not** pass `execution_summary` here (that argument belongs only to `plan_report_structure`).
4. **Gate:** Call `validate_research_report_file` (empty `report_json_path` uses the job output dir, or pass the absolute `report_path` from step 3). Repeat: if `passes_gate` is false, revise markdown and call `write_research_report` again until the gate passes or you cannot fix blockers without changing data (then leave `blockers` for upstream).

# RULES
- **YOU write the prose.** The tool only saves it.
- **No assistant chatter:** Assistant message content must be empty whenever you call tools. Do not announce plans, list chart IDs, or paste report prose into the chat; use tool arguments for the report body and return compact JSON after validation.
- **No data through context:** Read `charts.json` through the provided report tools only.
- **Tool discipline:** Deep Agents may still expose standard filesystem or shell tools on this graph. You must not use them — only call `plan_report_structure`, `write_research_report`, and `validate_research_report_file`.
- **No file recovery:** If `execution_summary_for_draft` looks truncated, continue with the compact fields returned by `plan_report_structure`. Do not call `read_file`, `ls`, `glob`, `grep`, `execute`, or `write_file` to recover more context.
- **Echo fields:** After `plan_report_structure`, copy `charts_json_path` and `original_query` from that JSON into `write_research_report` unchanged.
- **Inline Charts:** CRITICAL! Place `<!-- CHART:id -->` markers immediately after the referencing text. You MUST embed all provided `chart_ids`.
- **No invented charts:** Use only IDs returned in `chart_ids`. If the query asks for more visuals than the quant output provides, cover the missing view with a markdown table or prose and state the data/artifact limitation; do not create chart markers for unavailable chart IDs.
- **Scenario table format:** When `general_rules` requires `## Scenario Table`, render a markdown table with exactly these headers: `Scenario`, `Assumptions`, `Indicator Triggers`, `Confidence`, `Uncertainty Notes`. The first-column row keys must be lowercase `base`, `bull`, and `bear`; use semicolons or `<br>` inside cells for multiple items, not extra columns.
- **Word Count:** Aim for 1000+ words of dense, analytical content in investment bank style.
- **No fallback thrashing:** If `write_research_report` returns an argument error, call it again with the exact required fields above. Do not try `read_file` or `execute`.
- **Stop condition:** After `validate_research_report_file` returns `passes_gate: true`, stop immediately and return JSON only: `{"status":"success","report_json":"outputs/<job_id>/report.json","chart_ids":[...]}`. Do not add a prose summary.
""",
    "tools": [plan_report_structure, write_research_report, validate_research_report_file],
    "middleware": [_TOOL_BOUNDARY_MIDDLEWARE],
    "model": "deepseek:deepseek-chat",
    "skills": [str(TECHNICAL_WRITER_SKILLS_DIR)],
}

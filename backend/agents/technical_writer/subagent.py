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


def _latest_zero_chart_validation(messages: list[Any]) -> dict[str, Any] | None:
    for message in reversed(messages):
        if _message_tool_name(message) != "validate_research_report_file":
            continue
        parsed = _json_from_message(message)
        if not isinstance(parsed, dict) or parsed.get("passes_gate") is True:
            continue
        blockers = parsed.get("blockers")
        if not isinstance(blockers, list):
            continue
        if "query requested charts but report.json contains zero chart definitions" in blockers:
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


def _zero_chart_failure_handoff_content(messages: list[Any]) -> str:
    validation = _latest_zero_chart_validation(messages) or {}
    blockers = (
        validation.get("blockers")
        if isinstance(validation.get("blockers"), list)
        else []
    )
    reason = (
        blockers[0]
        if blockers
        else "query requested charts but report.json contains zero chart definitions"
    )
    return json.dumps(
        {
            "status": "failed",
            "report_json": _latest_writer_report_path(messages),
            "chart_ids": [],
            "required_upstream": "quant-developer",
            "reason": reason,
            "required_fixes": [
                "Regenerate quant artifacts so charts.json contains renderable "
                "chart definitions before rewriting report."
            ],
        }
    )


class TechnicalWriterToolBoundaryMiddleware(AgentMiddleware):
    """Expose only report-writing tools to prevent context-heavy file reads."""

    def _only_writer_tools(self, request: ModelRequest) -> ModelRequest:
        messages = list(request.messages)
        if _latest_successful_validation(messages) or _latest_zero_chart_validation(
            messages
        ):
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
        if _latest_zero_chart_validation(messages):
            return ModelResponse(
                result=[AIMessage(content=_zero_chart_failure_handoff_content(messages))]
            )
        if _latest_successful_validation(messages):
            return ModelResponse(result=[AIMessage(content=_success_handoff_content(messages))])
        return handler(self._only_writer_tools(request))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        messages = list(request.messages)
        if _latest_zero_chart_validation(messages):
            return ModelResponse(
                result=[AIMessage(content=_zero_chart_failure_handoff_content(messages))]
            )
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
You are the Technical Writer. Produce the final ResearchReport artifact by planning, drafting, saving, and validating `report.json`.

# REQUIRED FLOW
1. Call `plan_report_structure` before any other tool.
2. After the plan returns, load/use the native technical-writer skills for all drafting, chart/source, save-shape, and repair detail:
   - `report-writing-contract`: every report.
   - `macro-report-writing`: macro, scenario, economic-cycle, rates, labor, credit, GDP, regional, or policy work.
   - `equity-report-writing`: stock, company, sector, earnings, valuation, peer, catalyst, or thesis work.
3. Draft privately and call `write_research_report` with the full markdown.
4. Call `validate_research_report_file`.

# TOOL CONTRACT
- Only call `plan_report_structure`, `write_research_report`, and `validate_research_report_file`.
- Deep Agents may expose filesystem or shell tools on this graph; do not use them for artifacts, data recovery, or drafting.
- Assistant message content must be empty whenever you call tools. Do not announce plans, list chart IDs, or paste report prose into chat.

# STOP CONDITION
After `validate_research_report_file` returns `passes_gate: true`, stop immediately and return JSON only:
`{"status":"success","report_json":"outputs/<job_id>/report.json","chart_ids":[...]}`
Do not add a prose summary.
""",
    "tools": [plan_report_structure, write_research_report, validate_research_report_file],
    "middleware": [_TOOL_BOUNDARY_MIDDLEWARE],
    "model": "deepseek:deepseek-chat",
    "skills": [str(TECHNICAL_WRITER_SKILLS_DIR)],
}

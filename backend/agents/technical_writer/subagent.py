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


def _is_error_tool_message(message: Any) -> bool:
    return getattr(message, "status", None) == "error"


def _write_result_is_success(message: Any, parsed: dict[str, Any]) -> bool:
    if _is_error_tool_message(message) or parsed.get("status") == "error":
        return False
    report_path = parsed.get("report_path")
    if not isinstance(report_path, str) or not report_path.strip():
        return False
    validation_issues = parsed.get("validation_issues")
    if isinstance(validation_issues, list) and any(
        "Failed to write report.json" in str(issue) for issue in validation_issues
    ):
        return False
    return True


def _latest_writer_or_validation_result(
    messages: list[Any],
) -> tuple[int, str, Any, dict[str, Any]] | None:
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        name = _message_tool_name(message)
        if name not in {"write_research_report", "validate_research_report_file"}:
            continue
        parsed = _json_from_message(message)
        if parsed is None:
            parsed = {}
        return index, name, message, parsed
    return None


def _preceding_successful_write(
    messages: list[Any], validation_index: int, validation: dict[str, Any]
) -> dict[str, Any] | None:
    validation_report_path = validation.get("report_path")
    for message in reversed(messages[:validation_index]):
        if _message_tool_name(message) != "write_research_report":
            continue
        parsed = _json_from_message(message)
        if not isinstance(parsed, dict) or not _write_result_is_success(message, parsed):
            return None
        write_report_path = parsed.get("report_path")
        if (
            isinstance(validation_report_path, str)
            and validation_report_path.strip()
            and validation_report_path != write_report_path
        ):
            return None
        return parsed
    return None


def _terminal_successful_validation(
    messages: list[Any],
) -> tuple[dict[str, Any], dict[str, Any] | None] | None:
    latest = _latest_writer_or_validation_result(messages)
    if latest is None:
        return None
    validation_index, name, _message, validation = latest
    if name != "validate_research_report_file" or validation.get("passes_gate") is not True:
        return None
    return validation, _preceding_successful_write(messages, validation_index, validation)


def _terminal_zero_chart_validation(messages: list[Any]) -> dict[str, Any] | None:
    latest = _latest_writer_or_validation_result(messages)
    if latest is None:
        return None
    _index, name, _message, validation = latest
    if name != "validate_research_report_file" or validation.get("passes_gate") is True:
        return None
    blockers = validation.get("blockers")
    if not isinstance(blockers, list):
        return None
    if "query requested charts but report.json contains zero chart definitions" in blockers:
        return validation
    return None


def _latest_chart_handoff_mismatch(messages: list[Any]) -> dict[str, Any] | None:
    for message in reversed(messages):
        if _message_tool_name(message) not in {
            "write_research_report",
            "validate_research_report_file",
        }:
            continue
        parsed = _json_from_message(message)
        if not isinstance(parsed, dict):
            continue
        chart_handoff = parsed.get("chart_handoff")
        if (
            isinstance(chart_handoff, dict)
            and isinstance(chart_handoff.get("missing_report_chart_ids"), list)
            and chart_handoff["missing_report_chart_ids"]
        ):
            return parsed
        if parsed.get("failure_category") == "chart_handoff_mismatch":
            return parsed
    return None


def _latest_artifact_fact_mismatch(messages: list[Any]) -> dict[str, Any] | None:
    for message in reversed(messages):
        if _message_tool_name(message) not in {
            "write_research_report",
            "validate_research_report_file",
        }:
            continue
        parsed = _json_from_message(message)
        if not isinstance(parsed, dict):
            continue
        if parsed.get("failure_category") == "artifact_fact_mismatch":
            return parsed
        blockers = parsed.get("blockers")
        if not isinstance(blockers, list):
            continue
        if any(
            isinstance(blocker, str)
            and blocker.startswith("artifact_fact_mismatch:")
            for blocker in blockers
        ):
            return parsed
    return None


def _success_handoff_content(
    validation: dict[str, Any], successful_write: dict[str, Any]
) -> str:
    report_path = successful_write.get("report_path", "")
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


def _stale_validation_failure_handoff_content(
    messages: list[Any], validation: dict[str, Any]
) -> str:
    report_path = validation.get("report_path")
    if not isinstance(report_path, str) or not report_path.strip():
        report_path = _latest_writer_report_path(messages)
    return json.dumps(
        {
            "status": "failed",
            "report_json": report_path,
            "chart_ids": [],
            "required_upstream": "technical-writer",
            "failure_category": "stale_report_validation",
            "reason": (
                "validate_research_report_file passed, but the validation was not "
                "grounded in the nearest preceding successful write_research_report result."
            ),
            "required_fixes": [
                "Call write_research_report successfully for the repaired report, "
                "then validate that exact report_json_path before handoff."
            ],
        }
    )


def _zero_chart_failure_handoff_content(messages: list[Any]) -> str:
    validation = _terminal_zero_chart_validation(messages) or {}
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


def _chart_handoff_failure_handoff_content(messages: list[Any]) -> str:
    mismatch = _latest_chart_handoff_mismatch(messages) or {}
    chart_handoff = (
        mismatch.get("chart_handoff")
        if isinstance(mismatch.get("chart_handoff"), dict)
        else {}
    )
    blockers = (
        mismatch.get("blockers")
        if isinstance(mismatch.get("blockers"), list)
        else []
    )
    message = mismatch.get("message")
    if blockers:
        reason = blockers[0]
    elif isinstance(message, str):
        reason = message
    else:
        reason = (
            "chart_handoff_mismatch: final report did not preserve "
            "non-dropped chart IDs"
        )
    report_path = mismatch.get("report_path")
    if not isinstance(report_path, str) or not report_path:
        report_path = _latest_writer_report_path(messages)
    return json.dumps(
        {
            "status": "failed",
            "report_json": report_path,
            "chart_ids": chart_handoff.get("expected_chart_ids") or [],
            "missing_report_chart_ids": chart_handoff.get("missing_report_chart_ids")
            or [],
            "dropped_chart_ids": chart_handoff.get("dropped_chart_ids") or [],
            "required_upstream": "quant-developer",
            "reason": reason,
            "required_fixes": [
                "Regenerate quant artifacts so every non-dropped execution_summary.chart_ids "
                "entry has a renderable report chart definition, or mark intentionally omitted "
                "charts in dropped_chart_ids."
            ],
        }
    )


def _artifact_fact_failure_handoff_content(messages: list[Any]) -> str:
    mismatch = _latest_artifact_fact_mismatch(messages) or {}
    blockers = (
        mismatch.get("blockers")
        if isinstance(mismatch.get("blockers"), list)
        else []
    )
    message = mismatch.get("message")
    if blockers:
        reason = blockers[0]
    elif isinstance(message, str):
        reason = message
    else:
        reason = (
            "artifact_fact_mismatch: execution_summary.json, numeric_facts, "
            "and chart data disagree on a repeated quantitative fact"
        )
    report_path = mismatch.get("report_path") or mismatch.get("report_json")
    if not isinstance(report_path, str) or not report_path:
        report_path = _latest_writer_report_path(messages)
    return json.dumps(
        {
            "status": "failed",
            "report_json": report_path,
            "required_upstream": "quant-developer",
            "failure_category": "artifact_fact_mismatch",
            "reason": reason,
            "required_fixes": [
                "Regenerate quant artifacts so execution_summary.json, "
                "numeric_facts, and chart data use one consistent fact basis, "
                "or declare explicit transform_basis metadata for intentionally "
                "different calculations."
            ],
        }
    )


class TechnicalWriterToolBoundaryMiddleware(AgentMiddleware):
    """Expose only report-writing tools to prevent context-heavy file reads."""

    def _terminal_handoff_content(self, messages: list[Any]) -> str | None:
        if _latest_artifact_fact_mismatch(messages):
            return _artifact_fact_failure_handoff_content(messages)
        if _latest_chart_handoff_mismatch(messages):
            return _chart_handoff_failure_handoff_content(messages)
        if _terminal_zero_chart_validation(messages):
            return _zero_chart_failure_handoff_content(messages)
        terminal_validation = _terminal_successful_validation(messages)
        if terminal_validation is None:
            return None
        validation, successful_write = terminal_validation
        if successful_write is None:
            return _stale_validation_failure_handoff_content(messages, validation)
        return _success_handoff_content(validation, successful_write)

    def _only_writer_tools(self, request: ModelRequest) -> ModelRequest:
        messages = list(request.messages)
        if self._terminal_handoff_content(messages):
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
        handoff_content = self._terminal_handoff_content(messages)
        if handoff_content is not None:
            return ModelResponse(result=[AIMessage(content=handoff_content)])
        return handler(self._only_writer_tools(request))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        messages = list(request.messages)
        handoff_content = self._terminal_handoff_content(messages)
        if handoff_content is not None:
            return ModelResponse(result=[AIMessage(content=handoff_content)])
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

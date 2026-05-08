"""Tool-boundary middleware and guarded local backend for orchestrator."""
import json
import re
from pathlib import Path
from typing import Any

from .common import (
    AgentMiddleware,
    Awaitable,
    Callable,
    AIMessage,
    AnyMessage,
    EditResult,
    ExecuteResponse,
    GlobResult,
    GrepResult,
    LocalShellBackend,
    LsResult,
    ModelRequest,
    ModelResponse,
    ReadResult,
    ToolCallRequest,
    ToolMessage,
    WriteResult,
    _SECRET_SHELL_RE,
    _SENSITIVE_DIR_PARTS,
    _SENSITIVE_PATH_PARTS,
)
from ..tool_utils import (
    state_messages,
    tool_call_args,
    tool_call_id,
    tool_call_name,
    tool_name,
)

def _tool_name(tool: Any) -> str | None:
    return tool_name(tool)


def _tool_call_name(tool_call: Any) -> str | None:
    return tool_call_name(tool_call)


class HideTodoToolMiddleware(AgentMiddleware):
    """Remove DeepAgents' planning tool from model-visible tools for pipeline agents."""

    def _without_todo_tool(self, request: ModelRequest) -> ModelRequest:
        tools = [tool for tool in request.tools if _tool_name(tool) != "write_todos"]
        if len(tools) == len(request.tools):
            return request
        return request.override(tools=tools)

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        return handler(self._without_todo_tool(request))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        return await handler(self._without_todo_tool(request))


_HIDE_TODO_TOOL_MIDDLEWARE = HideTodoToolMiddleware()


class OrchestratorToolBoundaryMiddleware(AgentMiddleware):
    """Keep top-level execution focused on status updates and delegation."""

    _ALLOWED_TOOL_NAMES = {"emit_chat_message", "task"}
    _PIPELINE_SUBAGENTS = {
        "data-engineer",
        "quant-developer",
        "technical-writer",
        "quality-analyst",
    }

    def _without_specialist_tools(self, request: ModelRequest) -> ModelRequest:
        tools = [
            tool
            for tool in request.tools
            if _tool_name(tool) in self._ALLOWED_TOOL_NAMES
        ]
        if len(tools) == len(request.tools):
            return request
        return request.override(tools=tools)

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        return handler(self._without_specialist_tools(request))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        return await handler(self._without_specialist_tools(request))

    @staticmethod
    def _tool_call_id(tool_call: Any) -> str:
        return tool_call_id(tool_call, "orchestrator-blocked-task")

    @staticmethod
    def _tool_call_args(tool_call: Any) -> dict[str, Any]:
        return tool_call_args(tool_call)

    def _blocked_task_message(self, request: ToolCallRequest, subagent_type: str) -> ToolMessage:
        return ToolMessage(
            content=(
                f"Blocked task delegation to `{subagent_type}`. The execution "
                "pipeline may delegate only to data-engineer, quant-developer, "
                "technical-writer, or quality-analyst. Do not use general-purpose "
                "to inspect artifacts or recover from QA rejection; re-delegate to "
                "the specialist named by the pipeline rules with a self-contained "
                "description."
            ),
            name="task",
            tool_call_id=self._tool_call_id(request.tool_call),
            status="error",
        )

    def _blocked_repeat_quant_failure_message(self, request: ToolCallRequest) -> ToolMessage:
        return ToolMessage(
            content=(
                "Blocked repeat quant-developer delegation. The prior quant-developer "
                "task already returned a failed guardrail handoff after exhausting its "
                "script-write retry budget. Do not restart the same quant task. Proceed "
                "to technical-writer with the returned charts_json and "
                "execution_summary_json paths, and require explicit caveats about the "
                "missing local quantitative artifacts only if QA has not already "
                "rejected the report for missing computed artifacts. A QA-driven "
                "quant-developer recovery is allowed only when the delegation "
                "description names the QA rejection and the missing, stale, or invalid "
                "computed artifacts. If QA has already rejected for computed artifacts "
                "and this repeat quant delegation is blocked, stop the pipeline with a "
                "concise QA-rejected status instead of cycling through writer and QA "
                "again."
            ),
            name="task",
            tool_call_id=self._tool_call_id(request.tool_call),
            status="error",
        )

    def _blocked_repeat_quant_success_message(self, request: ToolCallRequest) -> ToolMessage:
        return ToolMessage(
            content=(
                "Blocked repeat quant-developer delegation. A prior quant-developer "
                "task already returned a usable artifact handoff with charts_json, "
                "execution_summary_json, and chart_ids. Do not restart quant merely "
                "to inspect or verify artifacts. Proceed to technical-writer with "
                "those paths. If QA rejected a report-vs-execution_summary "
                "contradiction, route the exact reason and required_fixes to "
                "technical-writer; do not reinterpret that as a quant recalculation "
                "request unless QA explicitly says computed artifacts are missing, "
                "stale, invalid, or require new analysis."
            ),
            name="task",
            tool_call_id=self._tool_call_id(request.tool_call),
            status="error",
        )

    def _blocked_orchestrator_tool_message(
        self, request: ToolCallRequest, tool_name: str
    ) -> ToolMessage:
        return ToolMessage(
            content=(
                f"Blocked orchestrator tool `{tool_name}`. The top-level execution "
                "agent may only call `emit_chat_message` and `task`; it must not "
                "inspect, write, or execute artifacts directly. Delegate to the "
                "appropriate specialist, or if quant-developer already returned a "
                "failed guardrail handoff, proceed to technical-writer with the "
                "returned `charts_json` and `execution_summary_json` paths and "
                "require explicit caveats about missing quantitative artifacts."
            ),
            name=tool_name,
            tool_call_id=self._tool_call_id(request.tool_call),
            status="error",
        )

    def _blocked_terminal_approval_after_rejection_message(
        self, request: ToolCallRequest
    ) -> ToolMessage:
        return ToolMessage(
            content=(
                "Blocked terminal approval message because the latest structured "
                "quality-analyst decision is rejected. Do not tell the user the "
                "report is approved. Re-delegate exactly once to the specialist "
                "named by the QA required_fixes, or if the repair budget is "
                "exhausted, emit a concise status explaining that QA rejected the "
                "report and include the rejection reason."
            ),
            name="emit_chat_message",
            tool_call_id=self._tool_call_id(request.tool_call),
            status="error",
        )

    @staticmethod
    def _has_failed_quant_guardrail_handoff(messages: list[Any]) -> bool:
        for message in messages:
            content = str(getattr(message, "content", "") or "")
            if (
                "quant-developer exceeded the pre-write guardrail retry budget" in content
                or '"failure_stage": "quant_initial_script_write"' in content
                or '"methods_used": ["quant_prewrite_retry_budget_guard"]' in content
            ):
                return True
        return False

    @staticmethod
    def _has_successful_quant_artifact_handoff(messages: list[Any]) -> bool:
        for message in messages:
            content = str(getattr(message, "content", "") or "")
            if re.search(r'"chart_ids"\s*:\s*\[\s*\]', content):
                continue
            if "quant-developer exceeded the pre-write guardrail retry budget" in content:
                continue
            execution_summary_match = re.search(
                r'"execution_summary_json"\s*:\s*"([^"]+)"', content
            )
            charts_match = re.search(r'"charts_json"\s*:\s*"([^"]+)"', content)
            chart_ids_match = re.search(r'"chart_ids"\s*:\s*\[(.*?)\]', content, re.S)
            if not (execution_summary_match and charts_match and chart_ids_match):
                continue
            if not re.search(r'"[^"]+"', chart_ids_match.group(1)):
                continue
            execution_summary_path = Path(execution_summary_match.group(1))
            charts_path = Path(charts_match.group(1))
            if execution_summary_path.is_absolute() and charts_path.is_absolute():
                if not execution_summary_path.exists() or not charts_path.exists():
                    continue
            return True
        return False

    @staticmethod
    def _is_explicit_qa_quant_fix(description: str) -> bool:
        text = description.lower()
        if not (
            "qa rejected" in text
            or "qa rejection" in text
            or "quality-analyst rejected" in text
            or "quality-analyst rejection" in text
            or "quality analyst rejected" in text
            or "quality analyst rejection" in text
            or "qa says" in text
            or "qa flagged" in text
            or "qa asked" in text
            or "qa is asking" in text
            or "qa analyst says" in text
            or "qa analyst flagged" in text
            or "qa analyst asked" in text
            or "qa analyst is asking" in text
            or "quality analyst says" in text
            or "quality analyst flagged" in text
            or "quality analyst asked" in text
            or "quality analyst is asking" in text
            or "quality-analyst says" in text
            or "quality-analyst flagged" in text
            or "quality-analyst asked" in text
            or "quality-analyst is asking" in text
            or "required_fixes" in text
            or "required fixes" in text
        ):
            return False
        if OrchestratorToolBoundaryMiddleware._is_report_fidelity_quant_misdirection(text):
            return False
        quant_fix_markers = (
            "computed artifacts are missing",
            "quantitative artifacts are missing",
            "computed artifacts are stale",
            "quantitative artifacts are stale",
            "computed artifacts are invalid",
            "quantitative artifacts are invalid",
            "computed artifact failures",
            "computed artifact failure",
            "computed charts are missing",
            "computed charts are stale",
            "computed charts are invalid",
            "chart data rendering",
            "chart rendering",
            "chart render",
            "chart data issue",
            "charts.json data",
            "charts.json still has",
            "stale charts",
            "invalid charts",
            "missing charts",
            "non-finite",
            "no finite numeric values",
            "nan/inf",
            "nan or inf",
            "nan values",
            "infinite values",
            "chart markers are missing",
            "chart definitions are missing",
            "charts.json has zero",
            "charts.json has no",
            "chart_count:0",
            "chart_count=0",
            "chart_ids are empty",
            "chart ids are empty",
            "required quantitative artifacts are missing or failed",
            "execution_summary lacks",
            "execution_summary.json lacks",
            "execution_summary packet must include",
            "execution_summary metadata",
            "execution_summary.json metadata",
            "backtest_summary",
            "model_comparison",
            "historical_simulations",
            "structured json keys",
            "structured keys",
            "enrichment keys",
            "need recalculation",
            "needs recalculation",
            "require recalculation",
            "requires recalculation",
            "requires new analysis",
            "need new analysis",
            "rerun quant",
            "rerun quant-developer",
            "regenerate the analysis",
            "regenerate analysis",
        )
        return any(marker in text for marker in quant_fix_markers)

    @staticmethod
    def _is_report_fidelity_quant_misdirection(description: str) -> bool:
        """Detect QA report-fidelity repairs that should go back to writer.

        The orchestrator may be tempted to treat a report-vs-summary mismatch as
        stale quant output. The pipeline contract says those fixes belong to
        technical-writer unless QA explicitly names computed artifacts as the
        broken item.
        """

        text = description.lower()
        writer_repair_markers = (
            "report-vs-execution_summary",
            "report vs execution_summary",
            "report's composite",
            "report prose",
            "writer used",
            "report writer used",
            "narrative wording",
            "numerical discrepancies between report",
            "discrepancies between report",
            "fundamentally disagrees with the execution_summary",
            "disagrees with the execution_summary",
            "contradiction between report",
            "report fidelity",
        )
        if not any(marker in text for marker in writer_repair_markers):
            return False

        explicit_artifact_markers = (
            "computed artifacts are missing",
            "quantitative artifacts are missing",
            "computed artifacts are stale",
            "quantitative artifacts are stale",
            "computed artifacts are invalid",
            "quantitative artifacts are invalid",
            "computed artifact failures",
            "computed artifact failure",
            "computed charts are missing",
            "computed charts are stale",
            "computed charts are invalid",
            "chart rendering",
            "chart render",
            "charts.json data",
            "non-finite",
            "no finite numeric values",
            "execution_summary lacks",
            "execution_summary.json lacks",
            "backtest_summary",
            "model_comparison",
            "historical_simulations",
            "chart_ids are empty",
            "chart ids are empty",
        )
        return not any(marker in text for marker in explicit_artifact_markers)

    @staticmethod
    def _state_messages(state: Any) -> list[Any]:
        return state_messages(state)

    @staticmethod
    def _latest_structured_quality_status(messages: list[Any]) -> str | None:
        latest: str | None = None
        for message in messages:
            content = getattr(message, "content", None)
            if not isinstance(content, str):
                continue
            try:
                payload = json.loads(content)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            status = payload.get("status")
            if status not in {"approved", "rejected"}:
                continue
            if "report_path" not in payload:
                continue
            if status == "rejected" and "required_fixes" not in payload:
                continue
            latest = status
        return latest

    def _is_blocked_terminal_approval_emit(self, request: ToolCallRequest) -> bool:
        args = self._tool_call_args(request.tool_call)
        markdown = args.get("markdown") if isinstance(args, dict) else None
        if not (isinstance(markdown, str) and markdown.startswith("Report approved:")):
            return False
        return (
            self._latest_structured_quality_status(
                self._state_messages(getattr(request, "state", None))
            )
            == "rejected"
        )

    def _enforce_tool_boundary(self, request: ToolCallRequest) -> ToolMessage | None:
        tool_name = _tool_call_name(request.tool_call)
        if tool_name and tool_name not in self._ALLOWED_TOOL_NAMES:
            return self._blocked_orchestrator_tool_message(request, tool_name)
        if tool_name == "emit_chat_message" and self._is_blocked_terminal_approval_emit(
            request
        ):
            return self._blocked_terminal_approval_after_rejection_message(request)
        if tool_name != "task":
            return None
        args = self._tool_call_args(request.tool_call)
        subagent_type = str(args.get("subagent_type") or "").strip()
        description = str(args.get("description") or "")
        if subagent_type and subagent_type not in self._PIPELINE_SUBAGENTS:
            return self._blocked_task_message(request, subagent_type)
        if (
            subagent_type == "quant-developer"
            and self._has_failed_quant_guardrail_handoff(
                self._state_messages(getattr(request, "state", None))
            )
            and not self._is_explicit_qa_quant_fix(description)
        ):
            return self._blocked_repeat_quant_failure_message(request)
        if (
            subagent_type == "quant-developer"
            and self._has_successful_quant_artifact_handoff(
                self._state_messages(getattr(request, "state", None))
            )
            and not self._is_explicit_qa_quant_fix(description)
        ):
            return self._blocked_repeat_quant_success_message(request)
        return None

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage],
    ) -> ToolMessage:
        if blocked := self._enforce_tool_boundary(request):
            return blocked
        return handler(request)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage]],
    ) -> ToolMessage:
        if blocked := self._enforce_tool_boundary(request):
            return blocked
        return await handler(request)


_ORCHESTRATOR_TOOL_BOUNDARY_MIDDLEWARE = OrchestratorToolBoundaryMiddleware()


class StripToolCallContentMiddleware(AgentMiddleware):
    """Drop assistant narration already represented by tool/status messages."""

    @staticmethod
    def _has_tool_call(message: AnyMessage) -> bool:
        tool_calls = getattr(message, "tool_calls", None)
        if tool_calls:
            return True
        additional_kwargs = getattr(message, "additional_kwargs", None)
        return bool(
            isinstance(additional_kwargs, dict)
            and additional_kwargs.get("tool_calls")
        )

    @staticmethod
    def _iter_tool_calls(message: AnyMessage) -> list[dict[str, Any]]:
        tool_calls = getattr(message, "tool_calls", None)
        if tool_calls:
            return [call for call in tool_calls if isinstance(call, dict)]
        additional_kwargs = getattr(message, "additional_kwargs", None)
        if not isinstance(additional_kwargs, dict):
            return []
        raw_tool_calls = additional_kwargs.get("tool_calls")
        if not isinstance(raw_tool_calls, list):
            return []
        calls: list[dict[str, Any]] = []
        for call in raw_tool_calls:
            if not isinstance(call, dict):
                continue
            function = call.get("function")
            if isinstance(function, dict):
                calls.append(
                    {
                        "name": function.get("name"),
                        "args": function.get("arguments"),
                    }
                )
            else:
                calls.append(call)
        return calls

    @classmethod
    def _is_terminal_approval_emit(cls, message: AnyMessage) -> bool:
        for call in cls._iter_tool_calls(message):
            name = call.get("name")
            if name != "emit_chat_message":
                continue
            args = call.get("args")
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    pass
            markdown = args.get("markdown") if isinstance(args, dict) else str(args)
            if isinstance(markdown, str) and markdown.startswith("Report approved: outputs/"):
                return True
        return False

    @staticmethod
    def _is_terminal_approval_result(message: AnyMessage) -> bool:
        content = getattr(message, "content", None)
        if content == "Approved.":
            return True
        if not isinstance(content, str):
            return False
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            return False
        return (
            isinstance(payload, dict)
            and payload.get("status") == "approved"
            and isinstance(payload.get("report_path"), str)
            and payload["report_path"].endswith("/report.json")
        )

    @classmethod
    def _terminal_approval_chat_emitted(cls, request: ModelRequest) -> bool:
        messages = getattr(request, "messages", None)
        if not messages:
            return False
        return any(cls._is_terminal_approval_emit(message) for message in messages)

    @classmethod
    def _terminal_approval_result_seen(cls, request: ModelRequest) -> bool:
        messages = getattr(request, "messages", None)
        if not messages:
            return False
        return any(cls._is_terminal_approval_result(message) for message in messages)

    @staticmethod
    def _latest_approved_report_path(request: ModelRequest) -> str | None:
        messages = getattr(request, "messages", None)
        if not messages:
            return None
        latest: str | None = None
        for message in messages:
            content = getattr(message, "content", None)
            if not isinstance(content, str):
                continue
            try:
                payload = json.loads(content)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict) or payload.get("status") != "approved":
                continue
            report_path = payload.get("report_path")
            if isinstance(report_path, str) and report_path.endswith("/report.json"):
                latest = report_path
        return latest

    @staticmethod
    def _approval_markdown(report_path: str) -> str:
        normalized = report_path.replace("\\", "/")
        marker = "/outputs/"
        if marker in normalized:
            normalized = "outputs/" + normalized.split(marker, 1)[1]
        return f"Report approved: {normalized}"

    @classmethod
    def _response_has_terminal_approval_emit(cls, response: ModelResponse) -> bool:
        return any(cls._is_terminal_approval_emit(message) for message in response.result)

    @classmethod
    def _terminal_approval_in_progress(cls, request: ModelRequest) -> bool:
        return cls._terminal_approval_chat_emitted(
            request
        ) or cls._terminal_approval_result_seen(request)

    @staticmethod
    def _empty_response(response: ModelResponse | None = None) -> ModelResponse:
        return ModelResponse(
            result=[AIMessage(content="")],
            structured_response=(
                response.structured_response if response is not None else None
            ),
        )

    @classmethod
    def _forced_terminal_approval_response(
        cls, request: ModelRequest, response: ModelResponse
    ) -> ModelResponse:
        if cls._response_has_terminal_approval_emit(response):
            updated = [
                cls._strip_message_content(message)
                if cls._has_tool_call(message)
                else message
                for message in response.result
            ]
            return ModelResponse(
                result=updated,
                structured_response=response.structured_response,
            )

        report_path = cls._latest_approved_report_path(request)
        if not report_path:
            return ModelResponse(
                result=[cls._strip_message_content(message) for message in response.result],
                structured_response=response.structured_response,
            )
        return ModelResponse(
            result=[
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "emit_chat_message",
                            "args": {"markdown": cls._approval_markdown(report_path)},
                            "id": "terminal-approval-emit",
                        }
                    ],
                )
            ],
            structured_response=response.structured_response,
        )

    @staticmethod
    def _strip_message_content(message: AnyMessage) -> AnyMessage:
        if not getattr(message, "content", None):
            return message
        return message.model_copy(update={"content": ""})

    def _strip_tool_call_content(self, response: ModelResponse) -> ModelResponse:
        updated = []
        changed = False
        for message in response.result:
            if self._has_tool_call(message) and getattr(message, "content", None):
                updated.append(self._strip_message_content(message))
                changed = True
            else:
                updated.append(message)
        if not changed:
            return response
        return ModelResponse(
            result=updated,
            structured_response=response.structured_response,
        )

    def _strip_terminal_approval_content(
        self, request: ModelRequest, response: ModelResponse
    ) -> ModelResponse:
        if not self._terminal_approval_in_progress(request):
            return response

        updated = []
        changed = False
        for message in response.result:
            stripped = self._strip_message_content(message)
            updated.append(stripped)
            changed = changed or stripped is not message
        if not changed:
            return response
        return ModelResponse(
            result=updated,
            structured_response=response.structured_response,
        )

    def _strip_content(self, request: ModelRequest, response: ModelResponse) -> ModelResponse:
        response = self._strip_tool_call_content(response)
        return self._strip_terminal_approval_content(request, response)

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        if self._terminal_approval_chat_emitted(request):
            return self._empty_response()
        response = handler(request)
        if self._terminal_approval_result_seen(request):
            return self._forced_terminal_approval_response(request, response)
        return self._strip_content(request, response)

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        if self._terminal_approval_chat_emitted(request):
            return self._empty_response()
        response = await handler(request)
        if self._terminal_approval_result_seen(request):
            return self._forced_terminal_approval_response(request, response)
        return self._strip_content(request, response)


_STRIP_TOOL_CALL_CONTENT_MIDDLEWARE = StripToolCallContentMiddleware()


def _with_hidden_todo_tool(subagent: dict[str, Any]) -> dict[str, Any]:
    """Return a subagent spec that hides write_todos while preserving local config."""
    configured = dict(subagent)
    configured["middleware"] = [
        *list(configured.get("middleware") or []),
        _HIDE_TODO_TOOL_MIDDLEWARE,
        _STRIP_TOOL_CALL_CONTENT_MIDDLEWARE,
    ]
    return configured


def _is_sensitive_path(path: str) -> bool:
    """Return True when a path points at likely credentials or local secrets."""
    if not path:
        return False
    normalized = path.replace("\\", "/").strip().strip("\"'")
    parts = [part for part in normalized.split("/") if part]
    lower_parts = [part.lower() for part in parts]
    lowered = "/".join(lower_parts)
    if any(part in _SENSITIVE_PATH_PARTS for part in lower_parts):
        return True
    return any(dir_part in lowered for dir_part in _SENSITIVE_DIR_PARTS)


class GuardedLocalShellBackend(LocalShellBackend):
    """Local backend with credential-file guardrails for agent tool use."""

    _DENIED = "Access denied: sensitive local credential files are not available to agents."
    _PACKAGE_INSTALL_DENIED = (
        "Access denied: package installation is not available in the agent shell. "
        "Use the backend dependencies installed by the application environment; "
        "do not vendor packages into the repository."
    )
    _PACKAGE_INSTALL_RE = re.compile(
        r"(?ix)"
        r"(^|[\s;&|()])("
        r"(?:[\w./-]+/)?pip(?:3(?:\.\d+)?)?(?:\s+-[^\s;&|()]+)*\s+install"
        r"|(?:[\w./-]+/)?python(?:3(?:\.\d+)?)?\s+-m\s+pip(?:\s+-[^\s;&|()]+)*\s+install"
        r"|(?:[\w./-]+/)?uv\s+pip(?:\s+-[^\s;&|()]+)*\s+install"
        r"|(?:[\w./-]+/)?uv\s+add"
        r"|(?:[\w./-]+/)?poetry\s+add"
        r"|(?:[\w./-]+/)?conda\s+install"
        r"|(?:[\w./-]+/)?mamba\s+install"
        r")($|[\s;&|()])"
    )

    def _is_denied_path(self, file_path: str) -> bool:
        return _is_sensitive_path(file_path)

    def read(self, file_path: str, offset: int = 0, limit: int = 2000):
        if self._is_denied_path(file_path):
            return ReadResult(error=self._DENIED)
        return super().read(file_path, offset=offset, limit=limit)

    def write(self, file_path: str, content: str):
        if self._is_denied_path(file_path):
            return WriteResult(error=self._DENIED)
        return super().write(file_path, content)

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ):
        if self._is_denied_path(file_path):
            return EditResult(error=self._DENIED)
        return super().edit(file_path, old_string, new_string, replace_all=replace_all)

    def ls(self, path: str):
        if self._is_denied_path(path):
            return LsResult(error=self._DENIED, entries=[])
        return super().ls(path)

    def glob(self, pattern: str, path: str = "/"):
        if self._is_denied_path(pattern) or self._is_denied_path(path):
            return GlobResult(error=self._DENIED, matches=[])
        return super().glob(pattern, path=path)

    def grep(self, pattern: str, path: str | None = None, glob: str | None = None):
        if (path is not None and self._is_denied_path(path)) or (
            glob is not None and self._is_denied_path(glob)
        ):
            return GrepResult(error=self._DENIED, matches=[])
        return super().grep(pattern, path=path, glob=glob)

    def execute(self, command: str, *, timeout: int | None = None):
        if _SECRET_SHELL_RE.search(command or ""):
            return ExecuteResponse(output=self._DENIED, exit_code=1, truncated=False)
        if self._PACKAGE_INSTALL_RE.search(command or ""):
            return ExecuteResponse(
                output=self._PACKAGE_INSTALL_DENIED,
                exit_code=1,
                truncated=False,
            )
        return super().execute(command, timeout=timeout)

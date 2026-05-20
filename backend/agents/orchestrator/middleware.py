"""Tool-boundary middleware and guarded local backend for orchestrator."""
from dataclasses import dataclass
import json
import re
from pathlib import Path
from typing import Any

from langgraph.types import Command
from pydantic import ValidationError

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
from .qa_recovery import (
    description_requests_qa_quant_fix,
    latest_quality_decision,
    latest_pipeline_status,
    qa_repair_budget_exhausted,
)
from ..quantitative_developer.handoff import (
    _job_id_from_runtime,
    _prewrite_failure_handoff,
)
from ..quantitative_developer.constants import get_output_base_dir
from ..quantitative_developer.path_helpers import _job_id_from_text
from ..quant_macro_stats.artifacts.evidence_bundle import EvidenceBundle
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


@dataclass(frozen=True)
class _QuantHandoffRoutingFailure:
    """Latest quant handoff state that must route back upstream before writing."""

    payload: dict[str, Any]
    failure_category: str
    reason: str
    required_fixes: tuple[str, ...]


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
    _QUANT_HANDOFF_FIELDS = (
        "charts_json",
        "execution_summary_json",
        "evidence_bundle_json",
        "chart_ids",
    )
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
                "task already returned a failed guardrail handoff. Do not delegate "
                "technical-writer from failed or structurally invalid quant artifacts. "
                "A QA-driven quant-developer recovery must be grounded in structured "
                "QA required_fixes that name missing, stale, or invalid computed "
                "artifacts; if it is still blocked, stop with a concise failed "
                "status naming quant-developer as the required recovery owner."
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
                "execution_summary_json, evidence_bundle_json, and chart_ids. "
                "Proceed to technical-writer with those paths for inspection, "
                "verification, or a "
                "report-vs-execution_summary contradiction. Re-run quant only when "
                "structured QA required_fixes say computed artifacts are missing, "
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
                "failed or invalid artifact handoff, stop with a concise failed "
                "status naming quant-developer as the required recovery owner."
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
                "quality-analyst decision is rejected or report gate failed. Do "
                "not tell the user the report is approved. Re-delegate exactly once to the specialist "
                "named by the QA required_fixes, or if the repair budget is "
                "exhausted, emit a concise status explaining that QA rejected the "
                "report and include the rejection reason."
            ),
            name="emit_chat_message",
            tool_call_id=self._tool_call_id(request.tool_call),
            status="error",
        )

    def _blocked_qa_repair_budget_message(self, request: ToolCallRequest) -> ToolMessage:
        return ToolMessage(
            content=(
                "Blocked recovery task because the QA repair budget is exhausted. "
                "Stop the pipeline with a concise QA-rejected status that includes "
                "the latest rejection reason and required_fixes; do not call another "
                "specialist on the same rejected report."
            ),
            name="task",
            tool_call_id=self._tool_call_id(request.tool_call),
            status="error",
        )

    def _blocked_wrong_qa_repair_owner_message(
        self,
        request: ToolCallRequest,
        subagent_type: str,
        required_upstream: str,
    ) -> ToolMessage:
        return ToolMessage(
            content=(
                f"Blocked QA recovery delegation to `{subagent_type}`. The latest "
                f"structured quality-analyst decision sets required_upstream="
                f"`{required_upstream}`. Re-delegate exactly once to "
                f"`{required_upstream}` with the QA reason, required_fixes, and "
                "artifact paths; do not inspect artifacts with another specialist."
            ),
            name="task",
            tool_call_id=self._tool_call_id(request.tool_call),
            status="error",
        )

    def _blocked_downstream_quant_handoff_message(
        self,
        request: ToolCallRequest,
        failure: _QuantHandoffRoutingFailure,
        subagent_type: str,
    ) -> ToolMessage:
        payload = failure.payload
        blocked_payload: dict[str, Any] = {
            "status": "failed",
            "blocked_subagent": subagent_type,
            "failure_category": failure.failure_category,
            "required_upstream": "quant-developer",
            "reason": failure.reason,
            "required_fixes": list(failure.required_fixes),
            "charts_json": str(payload.get("charts_json") or ""),
            "execution_summary_json": str(payload.get("execution_summary_json") or ""),
            "evidence_bundle_json": str(payload.get("evidence_bundle_json") or ""),
            "chart_ids": self._string_list(payload.get("chart_ids")),
        }
        for key in ("failure_stage", "error", "methods_used"):
            value = payload.get(key)
            if value:
                blocked_payload[key] = value
        return ToolMessage(
            content=json.dumps(blocked_payload, sort_keys=True),
            name="task",
            tool_call_id=self._tool_call_id(request.tool_call),
            status="error",
        )

    @staticmethod
    def _has_failed_quant_guardrail_handoff(messages: list[Any]) -> bool:
        for message in messages:
            content = str(getattr(message, "content", "") or "")
            if (
                "quant-developer exceeded the pre-write guardrail retry budget" in content
                or re.search(
                    r'"failure_stage"\s*:\s*"('
                    r"quant_initial_script_write|quant_malformed_tool_call|"
                    r'quant_invalid_task_handoff)"',
                    content,
                )
                or re.search(
                    r'"methods_used"\s*:\s*\[\s*"('
                    r"quant_prewrite_retry_budget_guard|"
                    r"quant_malformed_tool_call_guard|"
                    r'orchestrator_quant_task_result_guard)"',
                    content,
                )
            ):
                return True
        return False

    @classmethod
    def _latest_quant_handoff_payload(cls, messages: list[Any]) -> dict[str, Any] | None:
        for message in reversed(messages):
            content = str(getattr(message, "content", "") or "")
            if payload := cls._quant_handoff_payload_from_content(content):
                return payload
        return None

    @staticmethod
    def _quant_handoff_failed(payload: dict[str, Any], summary: Any) -> bool:
        return payload.get("status") == "failed" or (
            isinstance(summary, dict) and summary.get("status") == "failed"
        )

    def _latest_quant_handoff_routing_failure(
        self,
        messages: list[Any],
    ) -> _QuantHandoffRoutingFailure | None:
        payload = self._latest_quant_handoff_payload(messages)
        if payload is None or self._valid_quant_handoff_payload(payload):
            return None

        summary = self._load_json_file(Path(payload["execution_summary_json"]))
        if self._quant_handoff_failed(payload, summary):
            reason = (
                "Blocked downstream delegation because the latest quant-developer "
                "handoff is failed."
            )
            failure_category = "quant_artifact_handoff_failed"
        else:
            reason = (
                "Blocked downstream delegation because the latest quant-developer "
                "handoff is structurally invalid or its artifacts do not validate."
            )
            failure_category = "quant_artifact_handoff_invalid"

        if isinstance(summary, dict):
            for key in ("failure_stage", "error", "methods_used"):
                if key not in payload and summary.get(key):
                    payload[key] = summary[key]

        return _QuantHandoffRoutingFailure(
            payload=payload,
            failure_category=failure_category,
            reason=reason,
            required_fixes=(
                "Re-delegate to quant-developer to regenerate a valid compact handoff "
                "with charts_json, execution_summary_json, evidence_bundle_json, and "
                "nonempty chart_ids before technical-writer or quality-analyst.",
            ),
        )

    @classmethod
    def _has_successful_quant_artifact_handoff(cls, messages: list[Any]) -> bool:
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
            evidence_bundle_match = re.search(
                r'"evidence_bundle_json"\s*:\s*"([^"]+)"', content
            )
            chart_ids_match = re.search(r'"chart_ids"\s*:\s*\[(.*?)\]', content, re.S)
            if not (
                execution_summary_match
                and charts_match
                and evidence_bundle_match
                and chart_ids_match
            ):
                continue
            if not re.search(r'"[^"]+"', chart_ids_match.group(1)):
                continue
            execution_summary_path = Path(execution_summary_match.group(1))
            charts_path = Path(charts_match.group(1))
            evidence_bundle_path = Path(evidence_bundle_match.group(1))
            chart_ids = re.findall(r'"([^"]+)"', chart_ids_match.group(1))
            if (
                execution_summary_path.is_absolute()
                and charts_path.is_absolute()
                and evidence_bundle_path.is_absolute()
            ):
                if (
                    not execution_summary_path.exists()
                    or not charts_path.exists()
                    or not evidence_bundle_path.exists()
                ):
                    continue
            evidence_bundle = cls._valid_evidence_bundle_from_file(
                evidence_bundle_path,
                required_chart_ids=chart_ids,
                charts_json=charts_path,
                execution_summary_json=execution_summary_path,
            )
            if evidence_bundle is None:
                continue
            return True
        return False

    @staticmethod
    def _state_messages(state: Any) -> list[Any]:
        return state_messages(state)

    def _latest_active_required_upstream(self, messages: list[Any]) -> str | None:
        latest_decision = latest_quality_decision(messages)
        if latest_decision is None or latest_decision.status not in {
            "rejected",
            "failed",
        }:
            return None
        required_upstream = latest_decision.required_upstream
        if required_upstream != "quant-developer":
            return required_upstream

        for message in reversed(messages):
            content = str(getattr(message, "content", "") or "")
            if payload := self._quant_handoff_payload_from_content(content):
                if self._valid_quant_handoff_payload(payload):
                    return None
            decision = latest_quality_decision([message])
            if decision is not None and decision.status in {"rejected", "failed"}:
                return decision.required_upstream
        return required_upstream

    def _is_blocked_terminal_approval_emit(self, request: ToolCallRequest) -> bool:
        args = self._tool_call_args(request.tool_call)
        markdown = args.get("markdown") if isinstance(args, dict) else None
        if not (isinstance(markdown, str) and markdown.startswith("Report approved:")):
            return False
        return latest_pipeline_status(self._state_messages(getattr(request, "state", None))) in {
            "rejected",
            "failed",
        }

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
        messages = self._state_messages(getattr(request, "state", None))
        if qa_repair_budget_exhausted(messages):
            return self._blocked_qa_repair_budget_message(request)
        required_upstream = self._latest_active_required_upstream(messages)
        if (
            required_upstream
            and subagent_type
            and subagent_type not in {required_upstream, "quality-analyst"}
        ):
            return self._blocked_wrong_qa_repair_owner_message(
                request,
                subagent_type,
                required_upstream,
            )
        if (
            subagent_type in {"technical-writer", "quality-analyst"}
            and (
                failure := self._latest_quant_handoff_routing_failure(messages)
            )
        ):
            return self._blocked_downstream_quant_handoff_message(
                request,
                failure,
                subagent_type,
            )
        if (
            subagent_type == "quant-developer"
            and self._has_failed_quant_guardrail_handoff(messages)
            and not description_requests_qa_quant_fix(description, messages)
        ):
            return self._blocked_repeat_quant_failure_message(request)
        if (
            subagent_type == "quant-developer"
            and self._has_successful_quant_artifact_handoff(messages)
            and not description_requests_qa_quant_fix(description, messages)
        ):
            return self._blocked_repeat_quant_success_message(request)
        return None

    @classmethod
    def _is_quant_handoff_payload(cls, payload: Any) -> bool:
        if not isinstance(payload, dict):
            return False
        if not all(field in payload for field in cls._QUANT_HANDOFF_FIELDS):
            return False
        return (
            isinstance(payload.get("charts_json"), str)
            and isinstance(payload.get("execution_summary_json"), str)
            and isinstance(payload.get("evidence_bundle_json"), str)
            and isinstance(payload.get("chart_ids"), list)
        )

    @classmethod
    def _quant_handoff_payload_from_content(cls, content: str) -> dict[str, Any] | None:
        decoder = json.JSONDecoder()
        for index, char in enumerate(content):
            if char != "{":
                continue
            try:
                payload, _ = decoder.raw_decode(content, index)
            except json.JSONDecodeError:
                continue
            if cls._is_quant_handoff_payload(payload):
                return payload
        return None

    @classmethod
    def _has_quant_handoff_fields(cls, content: str) -> bool:
        return cls._quant_handoff_payload_from_content(content) is not None

    @staticmethod
    def _load_json_file(path: Path) -> Any:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    @staticmethod
    def _same_path(left: str | Path, right: str | Path) -> bool:
        try:
            return Path(left).expanduser().resolve(strict=False) == Path(
                right
            ).expanduser().resolve(strict=False)
        except OSError:
            return str(left) == str(right)

    @staticmethod
    def _valid_evidence_bundle_from_file(
        path: Path,
        *,
        required_chart_ids: list[str] | None = None,
        charts_json: Path | None = None,
        execution_summary_json: Path | None = None,
    ) -> EvidenceBundle | None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        try:
            bundle = EvidenceBundle.model_validate(payload)
        except ValidationError:
            return None
        if not bundle.validation.valid:
            return None
        if required_chart_ids:
            bundle_chart_ids = {chart.chart_id for chart in bundle.charts}
            if any(chart_id not in bundle_chart_ids for chart_id in required_chart_ids):
                return None
        artifacts = bundle.artifacts
        if not OrchestratorToolBoundaryMiddleware._same_path(
            artifacts.evidence_bundle_json,
            path,
        ):
            return None
        if charts_json is not None and not OrchestratorToolBoundaryMiddleware._same_path(
            artifacts.charts_json,
            charts_json,
        ):
            return None
        if (
            execution_summary_json is not None
            and not OrchestratorToolBoundaryMiddleware._same_path(
                artifacts.execution_summary_json,
                execution_summary_json,
            )
        ):
            return None
        return bundle

    @staticmethod
    def _chart_ids_from_payload(payload: Any) -> list[str]:
        if isinstance(payload, dict):
            return [str(chart_id) for chart_id, chart in payload.items() if chart_id and chart]
        if isinstance(payload, list):
            return [
                str(chart["id"])
                for chart in payload
                if isinstance(chart, dict) and chart.get("id")
            ]
        return []

    @staticmethod
    def _string_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        ids: list[str] = []
        seen: set[str] = set()
        for item in value:
            text = str(item).strip() if item is not None else ""
            if not text or text in seen:
                continue
            seen.add(text)
            ids.append(text)
        return ids

    def _valid_quant_handoff_payload(self, payload: dict[str, Any]) -> bool:
        if payload.get("status") == "failed":
            return False

        charts_path = Path(payload["charts_json"])
        summary_path = Path(payload["execution_summary_json"])
        evidence_bundle_path = Path(payload["evidence_bundle_json"])

        charts_payload = self._load_json_file(charts_path)
        available_chart_ids = self._chart_ids_from_payload(charts_payload)
        if charts_payload is None:
            return False

        summary = self._load_json_file(summary_path)
        if not isinstance(summary, dict) or summary.get("status") == "failed":
            return False

        payload_chart_ids = self._string_list(payload.get("chart_ids"))
        if not payload_chart_ids:
            return False

        summary_chart_ids = self._string_list(summary.get("chart_ids"))
        if payload_chart_ids and summary_chart_ids and payload_chart_ids != summary_chart_ids:
            return False

        required_chart_ids = payload_chart_ids
        available_chart_id_set = set(available_chart_ids)
        if any(chart_id not in available_chart_id_set for chart_id in required_chart_ids):
            return False

        return (
            self._valid_evidence_bundle_from_file(
                evidence_bundle_path,
                required_chart_ids=required_chart_ids,
                charts_json=charts_path,
                execution_summary_json=summary_path,
            )
            is not None
        )

    def _candidate_quant_output_dirs(
        self,
        request: ToolCallRequest,
        result_content: str,
    ) -> list[Path]:
        output_base = Path(get_output_base_dir())
        candidates: list[Path] = []

        def add_job_id(job_id: str | None) -> None:
            if not job_id:
                return
            path = output_base / job_id
            if path not in candidates:
                candidates.append(path)

        add_job_id(_job_id_from_runtime(getattr(request, "runtime", None)))
        args = self._tool_call_args(request.tool_call)
        add_job_id(_job_id_from_text(str(args.get("description") or "")))
        add_job_id(_job_id_from_text(result_content))
        for message in reversed(self._state_messages(getattr(request, "state", None))):
            add_job_id(_job_id_from_text(str(getattr(message, "content", "") or "")))
        return candidates

    def _quant_artifact_handoff_from_files(
        self,
        request: ToolCallRequest,
        result_content: str,
    ) -> dict[str, Any] | None:
        for output_dir in self._candidate_quant_output_dirs(request, result_content):
            charts_path = output_dir / "charts.json"
            summary_path = output_dir / "execution_summary.json"
            evidence_bundle_path = output_dir / "evidence_bundle.json"
            summary = self._load_json_file(summary_path)
            if not isinstance(summary, dict) or summary.get("status") == "failed":
                continue
            charts_payload = self._load_json_file(charts_path)
            available_chart_ids = self._chart_ids_from_payload(charts_payload)
            if not available_chart_ids:
                continue
            available_chart_id_set = set(available_chart_ids)
            chart_ids = [
                str(chart_id)
                for chart_id in summary.get("chart_ids", [])
                if isinstance(chart_id, str) and chart_id
            ]
            if not chart_ids:
                chart_ids = available_chart_ids
            if any(chart_id not in available_chart_id_set for chart_id in chart_ids):
                continue
            evidence_bundle = self._valid_evidence_bundle_from_file(
                evidence_bundle_path,
                required_chart_ids=chart_ids,
                charts_json=charts_path,
                execution_summary_json=summary_path,
            )
            if evidence_bundle is None:
                continue
            handoff: dict[str, Any] = {
                "charts_json": str(charts_path),
                "execution_summary_json": str(summary_path),
                "evidence_bundle_json": str(evidence_bundle_path),
                "chart_ids": chart_ids,
            }
            dropped_chart_ids = summary.get("dropped_chart_ids")
            if isinstance(dropped_chart_ids, list):
                handoff["dropped_chart_ids"] = [
                    str(chart_id) for chart_id in dropped_chart_ids if chart_id
                ]
            statistical_summary = summary.get("statistical_summary")
            if isinstance(statistical_summary, str) and statistical_summary.strip():
                handoff["statistical_summary_excerpt"] = statistical_summary[:600]
            return handoff
        return None

    def _quant_task_failure_handoff_message(
        self,
        request: ToolCallRequest,
        result: ToolMessage,
    ) -> ToolMessage:
        args = self._tool_call_args(request.tool_call)
        description = str(args.get("description") or "")
        result_content = str(getattr(result, "content", "") or "")
        state = getattr(request, "state", None)
        messages = [
            *self._state_messages(state),
            AIMessage(content=description),
            AIMessage(content=result_content[:2_000]),
        ]
        handoff = _prewrite_failure_handoff(
            messages,
            job_id=_job_id_from_runtime(getattr(request, "runtime", None)),
            failure_stage="quant_invalid_task_handoff",
            error=(
                "quant-developer task completed without returning a compact artifact "
                "handoff containing charts_json, execution_summary_json, "
                "evidence_bundle_json, and chart_ids"
            ),
            methods_used=["orchestrator_quant_task_result_guard"],
        )
        return ToolMessage(
            content=handoff,
            name="task",
            tool_call_id=self._tool_call_id(request.tool_call),
            status="success",
        )

    def _postprocess_quant_tool_message(
        self,
        request: ToolCallRequest,
        result: ToolMessage,
    ) -> ToolMessage:
        if getattr(result, "status", None) == "error":
            return result
        content = str(getattr(result, "content", "") or "")
        if payload := self._quant_handoff_payload_from_content(content):
            if self._valid_quant_handoff_payload(payload):
                return ToolMessage(
                    content=json.dumps(payload, sort_keys=True),
                    name="task",
                    tool_call_id=self._tool_call_id(request.tool_call),
                    status="success",
                )
        if payload := self._quant_artifact_handoff_from_files(request, content):
            return ToolMessage(
                content=json.dumps(payload, sort_keys=True),
                name="task",
                tool_call_id=self._tool_call_id(request.tool_call),
                status="success",
            )
        return self._quant_task_failure_handoff_message(request, result)

    def _postprocess_task_result(
        self,
        request: ToolCallRequest,
        result: ToolMessage | Command,
    ) -> ToolMessage | Command:
        args = self._tool_call_args(request.tool_call)
        if str(args.get("subagent_type") or "").strip() != "quant-developer":
            return result
        if type(result).__name__ == "ToolMessage":
            return self._postprocess_quant_tool_message(request, result)
        if isinstance(result, Command) and isinstance(result.update, dict):
            messages = result.update.get("messages")
            if (
                isinstance(messages, list)
                and len(messages) == 1
                and type(messages[0]).__name__ == "ToolMessage"
            ):
                normalized = self._postprocess_quant_tool_message(request, messages[0])
                if normalized is not messages[0]:
                    update = {**result.update, "messages": [normalized]}
                    return Command(
                        graph=result.graph,
                        update=update,
                        resume=result.resume,
                        goto=result.goto,
                    )
        return result

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage],
    ) -> ToolMessage:
        if blocked := self._enforce_tool_boundary(request):
            return blocked
        result = handler(request)
        return self._postprocess_task_result(request, result)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage]],
    ) -> ToolMessage:
        if blocked := self._enforce_tool_boundary(request):
            return blocked
        result = await handler(request)
        return self._postprocess_task_result(request, result)


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
        latest_decision = latest_quality_decision(messages)
        if latest_decision is not None:
            return latest_decision.status == "approved"
        return any(cls._is_terminal_approval_result(message) for message in messages)

    @staticmethod
    def _latest_approved_report_path(request: ModelRequest) -> str | None:
        messages = getattr(request, "messages", None)
        if not messages:
            return None
        latest_decision = latest_quality_decision(messages)
        if latest_decision is not None:
            if latest_decision.status != "approved":
                return None
            return latest_decision.report_path
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
    def _terminal_qa_failure_response(request: ModelRequest) -> ModelResponse | None:
        messages = getattr(request, "messages", None)
        if not messages or not qa_repair_budget_exhausted(messages):
            return None
        decision = latest_quality_decision(messages)
        if decision is None or decision.status not in {"rejected", "failed"}:
            return None
        payload = {
            "status": decision.status,
            "report_path": decision.report_path,
            "reason": decision.reason,
            "required_fixes": list(decision.required_fixes),
            "ready_for_upload": False,
        }
        if decision.required_upstream:
            payload["required_upstream"] = decision.required_upstream
        if decision.failure_category:
            payload["failure_category"] = decision.failure_category
        return ModelResponse(
            result=[AIMessage(content=json.dumps(payload, sort_keys=True))],
        )

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
        if qa_failure := self._terminal_qa_failure_response(request):
            return qa_failure
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
        if qa_failure := self._terminal_qa_failure_response(request):
            return qa_failure
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

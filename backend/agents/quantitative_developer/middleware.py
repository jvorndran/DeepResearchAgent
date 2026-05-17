"""Middleware guardrails for the quantitative developer subagent."""

import ast
import json
import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest

from ..quant_macro_stats import format_quant_helper_catalog_for_prompt
from .constants import (
    _AFTER_WRITE_TOOL_NAMES,
    _BACKEND_DIR,
    _DATA_FILE_SUFFIXES,
    _FIRST_WRITE_TOOL_NAMES,
    _INSPECTION_TOOL_NAMES,
    _MAX_ANALYSIS_SCRIPT_CHARS,
    _MAX_ANALYSIS_SCRIPT_LINES,
    _TRUNCATED_ARGUMENT_MARKERS,
)
from .handoff import (
    _job_id_from_runtime,
    _has_successful_quant_handoff,
    _has_written_analysis_script,
    _is_final_prewrite_opportunity,
    _latest_successful_quant_handoff_content,
    _prewrite_failure_handoff,
    _should_stop_prewrite_loop,
)
from .path_helpers import (
    _is_allowed_analysis_script_path,
    _job_id_from_request,
    _required_script_path_hint,
)
from .script_inspection import (
    _align_period_output_period_reference,
    _calls_named,
    _extract_data_files_manifest_from_tree,
    _has_empty_list_call_arg,
    _imports_forbidden_forecast_library,
    _literal_string_arg,
    _looped_direct_forecasts_without_backtest_skip,
    _needs_period_alignment_guard,
    _python_tree_for_write,
    _request_with_tool_content,
    _rewrite_manifest_paths,
    _uses_runtime_installer,
    _unique_existing_sibling_data_path,
)
from .tool_utils import (
    _state_messages,
    _tool_call_args,
    _tool_call_id,
    _tool_call_name,
    _tool_name,
)


_SKILL_TOOL_NAMES = {"load_skill", "loadSkill"}
_SKILL_READ_TOOL_NAMES = {"read_file"}
_QUANT_SKILLS_DIR = (_BACKEND_DIR / "skills" / "quant-developer").resolve()
_PSEUDO_TOOL_CALL_MARKERS = (
    "<｜｜DSML｜｜tool_calls",
    "<｜｜DSML｜｜invoke",
    "<|tool_calls|",
    "<tool_calls",
)
_PSEUDO_INVOKE_RE = re.compile(
    r"<[^>]*invoke\s+name=[\"'](?P<name>[^\"']+)[\"'][^>]*>",
    re.IGNORECASE,
)
_PSEUDO_PARAMETER_RE = re.compile(
    r"<[^>]*parameter\s+name=[\"'](?P<name>[^\"']+)[\"'][^>]*>"
    r"(?P<value>.*?)"
    r"</[^>]*parameter>",
    re.DOTALL | re.IGNORECASE,
)
_PSEUDO_PARAMETER_OPEN_RE = re.compile(
    r"<[^>]*parameter\s+name=[\"'](?P<name>[^\"']+)[\"'][^>]*>",
    re.IGNORECASE,
)
_FORECAST_EVIDENCE_HELPERS = {
    "direct_ols_forecast",
    "walk_forward_ols_backtest",
    "event_signal_backtest",
    "normalize_forecast_table",
    "forecast_model_comparison_rows",
    "forecast_failure_episodes",
    "forecast_false_alarm_episodes",
    "forecast_band_rows",
    "predictor_contribution_rows",
}
_FORECAST_EVIDENCE_KEYS = {
    "forecast_table",
    "model_comparison_by_horizon",
    "historical_failure_episodes",
    "event_backtest_metrics",
    "signal_false_positive_windows",
    "forecast_band_rows",
    "predictor_contribution_rows",
}
_REMOVED_QUANT_OUTPUT_PRESERVATION_SURFACES = {
    "preserve_report_aligned_charts",
    "supplemental_validation_only",
    "merge_quant_validation_summary",
}


def _pseudo_parameter_values(content: str) -> dict[str, str]:
    """Extract DSML parameter values, including a final unterminated value."""
    params = {
        match.group("name"): match.group("value")
        for match in _PSEUDO_PARAMETER_RE.finditer(content)
    }

    openings = list(_PSEUDO_PARAMETER_OPEN_RE.finditer(content))
    for index, opening in enumerate(openings):
        name = opening.group("name")
        if name in params:
            continue
        start = opening.end()
        end = len(content)
        if index + 1 < len(openings):
            end = min(end, openings[index + 1].start())
        closing = re.search(
            r"</[^>]*(?:parameter|invoke|tool_calls)>",
            content[start:],
            re.IGNORECASE,
        )
        if closing:
            end = min(end, start + closing.start())
        value = content[start:end].strip()
        if value:
            params[name] = value
    return params


def _pseudo_write_file_tool_call(content: str) -> dict[str, object] | None:
    """Recover complete DSML-style write_file markup emitted as text."""
    invoke_match = _PSEUDO_INVOKE_RE.search(content)
    if not invoke_match or invoke_match.group("name").lower() != "write_file":
        return None

    params = _pseudo_parameter_values(content)
    file_path = str(params.get("file_path") or params.get("path") or "").strip()
    script_content = params.get("content")
    if not file_path or not isinstance(script_content, str) or not script_content.strip():
        return None

    return {
        "name": "write_file",
        "args": {
            "file_path": file_path,
            "content": script_content.strip(),
        },
        "id": f"call_quant_pseudo_write_file_{uuid.uuid4().hex[:8]}",
    }


def _balanced_brace_block(text: str, start: int) -> str | None:
    if start >= len(text) or text[start] != "{":
        return None

    depth = 0
    quote: str | None = None
    escaped = False
    for index, char in enumerate(text[start:], start=start):
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in {"'", '"'}:
            quote = char
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def _coerce_data_files(value: object) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    data_files = {
        str(key): str(path) for key, path in value.items() if isinstance(path, str) and path
    }
    return data_files or None


def _messages_text(messages: list[object]) -> str:
    return "\n".join(str(getattr(message, "content", "") or "") for message in messages)


def _non_tool_messages_text(messages: list[object]) -> str:
    """Return request/model text without prompt or tool results used for routing."""

    return "\n".join(
        str(getattr(message, "content", "") or "")
        for message in messages
        if type(message).__name__ not in {"SystemMessage", "ToolMessage"}
    )


def _data_files_from_text(text: str) -> dict[str, str] | None:
    data_files: dict[str, str] = {}
    decoder = json.JSONDecoder()
    for match in re.finditer(r'["`]?data_files["`]?\s*[:=]\s*', text):
        start = match.end()
        while start < len(text) and text[start].isspace():
            start += 1
        if start >= len(text) or text[start] != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            if block := _balanced_brace_block(text, start):
                try:
                    value = ast.literal_eval(block)
                except (SyntaxError, ValueError):
                    continue
            else:
                continue
        if parsed_data_files := _coerce_data_files(value):
            data_files.update(parsed_data_files)

    lowered = text.lower()
    path_suffixes = "|".join(re.escape(suffix.lstrip(".")) for suffix in _DATA_FILE_SUFFIXES)
    if "data_files" in lowered or "data files" in lowered:
        line_pattern = re.compile(
            rf"""(?im)^\s*
            (?:[-*]\s*)?
            [`"']?(?P<key>[A-Za-z][A-Za-z0-9_.-]{{1,}})[`"']?
            \s*[:=]\s*
            [`"']?(?P<path>/[^\s`"',;]+\.(?:{path_suffixes}))[`"']?
            \s*,?\s*$""",
            re.VERBOSE,
        )
        data_files.update(
            {match.group("key"): match.group("path") for match in line_pattern.finditer(text)}
        )

    fred_path_pattern = re.compile(
        rf"(?P<path>/[^\s`\"',;]+/fred_get_series_"
        rf"(?P<key>[A-Za-z0-9]+)_[^\s`\"',;]+\.(?:{path_suffixes}))"
    )
    for match in fred_path_pattern.finditer(text):
        series_key = match.group("key").upper()
        if any(
            existing_key == series_key or existing_key.startswith(f"{series_key}_")
            for existing_key in {str(key).upper() for key in data_files}
        ):
            continue
        data_files[series_key] = match.group("path")

    if data_files:
        return data_files
    return None


def _query_from_text(text: str) -> str:
    patterns = (
        r"Full approved user request for `original_query`:\s*(?P<query>.+?)(?:\n|$)",
        r"original_query[\"`]?\s*[:=]\s*[\"'](?P<query>.+?)[\"']",
        r"(?:Approved research request|Approved user request|User request|Analysis goal|Task goal|Research brief|Research objective):\s*(?P<query>.+?)(?:\n|$)",
        r"Research Query:\s*(?P<query>.+?)(?:\n\n|$)",
        r"Research summary:\s*(?P<query>.+?)(?:\n|$)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return " ".join(match.group("query").split())
    return ""


def _query_from_runtime(runtime: object) -> str:
    context = getattr(runtime, "context", None)
    keys = ("query", "original_query", "research_query")
    if isinstance(context, dict):
        values = (context.get(key) for key in keys)
    else:
        values = (getattr(context, key, None) for key in keys)
    for value in values:
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())
    return ""


def _best_query(*candidates: str) -> str:
    cleaned = [" ".join(candidate.split()) for candidate in candidates if candidate.strip()]
    if not cleaned:
        return ""
    return max(cleaned, key=len)


def _has_forecast_evidence_script(tree: ast.Module) -> bool:
    if any(_calls_named(tree, helper) for helper in _FORECAST_EVIDENCE_HELPERS):
        return True
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key in node.keys:
            if isinstance(key, ast.Constant) and key.value in _FORECAST_EVIDENCE_KEYS:
                return True
    return False


@dataclass(frozen=True)
class WriteFileDraft:
    args: dict[str, object]
    file_path: str
    content: str | None
    tree: ast.Module | None
    syntax_error: SyntaxError | None
    manifest: dict[str, str] | None

    @classmethod
    def from_args(cls, args: dict[str, object]) -> "WriteFileDraft":
        file_path = str(args.get("file_path") or args.get("path") or "")
        raw_content = args.get("content")
        content = raw_content if isinstance(raw_content, str) else None
        tree: ast.Module | None = None
        syntax_error: SyntaxError | None = None
        manifest: dict[str, str] | None = None
        if content is not None and file_path.endswith(".py"):
            tree, syntax_error = _python_tree_for_write(content)
            if tree is not None and syntax_error is None:
                manifest = _extract_data_files_manifest_from_tree(tree)
        return cls(
            args=args,
            file_path=file_path,
            content=content,
            tree=tree,
            syntax_error=syntax_error,
            manifest=manifest,
        )

    @property
    def is_python(self) -> bool:
        return self.file_path.endswith(".py")

    @property
    def line_count(self) -> int:
        return 0 if self.content is None else self.content.count("\n") + 1

    @property
    def char_count(self) -> int:
        return 0 if self.content is None else len(self.content)


@dataclass(frozen=True)
class QuantToolCallContext:
    request: ToolCallRequest
    tool_name: str | None
    tool_call_id: str
    args: dict[str, object]
    state_messages: list[object]
    write: WriteFileDraft | None
    has_successful_handoff: bool
    has_written_analysis_script: bool
    is_final_prewrite_opportunity: bool

    @classmethod
    def from_request(cls, request: ToolCallRequest) -> "QuantToolCallContext":
        tool_name = _tool_call_name(request.tool_call)
        args = _tool_call_args(request.tool_call)
        state_messages = _state_messages(getattr(request, "state", None))
        return cls(
            request=request,
            tool_name=tool_name,
            tool_call_id=_tool_call_id(request.tool_call),
            args=args,
            state_messages=state_messages,
            write=WriteFileDraft.from_args(args) if tool_name == "write_file" else None,
            has_successful_handoff=_has_successful_quant_handoff(state_messages),
            has_written_analysis_script=_has_written_analysis_script(state_messages),
            is_final_prewrite_opportunity=_is_final_prewrite_opportunity(state_messages),
        )


@dataclass(frozen=True)
class QuantGuardrailDecision:
    request: ToolCallRequest
    message: ToolMessage | None = None

    @classmethod
    def allow(cls, context: QuantToolCallContext) -> "QuantGuardrailDecision":
        return cls(request=context.request)

    @classmethod
    def block(
        cls, context: QuantToolCallContext, message: ToolMessage
    ) -> "QuantGuardrailDecision":
        return cls(request=context.request, message=message)

    @classmethod
    def replace_request(
        cls, request: ToolCallRequest
    ) -> "QuantGuardrailDecision":
        return cls(request=request)

    @property
    def blocked(self) -> bool:
        return self.message is not None


def _is_skill_tool_name(tool_name: str | None) -> bool:
    if not tool_name:
        return False
    normalized = tool_name.replace("-", "_")
    return tool_name in _SKILL_TOOL_NAMES or normalized == "load_skill"


def _is_skill_read_tool_name(tool_name: str | None) -> bool:
    return tool_name in _SKILL_READ_TOOL_NAMES


def _is_quant_skill_file_path(file_path: object) -> bool:
    if not file_path:
        return False
    try:
        path = Path(str(file_path)).expanduser().resolve()
        if (
            path.name == "SKILL.md"
            and path.parent != _QUANT_SKILLS_DIR
            and path.is_relative_to(_QUANT_SKILLS_DIR)
        ):
            return True
    except (OSError, RuntimeError, TypeError, ValueError):
        pass
    normalized = str(file_path).replace("\\", "/").strip().strip("\"'")
    marker = "backend/skills/quant-developer/"
    return (
        normalized.endswith("/SKILL.md")
        and marker in normalized
        and not normalized.endswith("backend/skills/quant-developer/SKILL.md")
    )


def _pseudo_read_file_tool_call(content: str) -> dict[str, object] | None:
    """Recover DSML-style read_file markup for allowed quant skill files."""
    invoke_match = _PSEUDO_INVOKE_RE.search(content)
    if not invoke_match or invoke_match.group("name").lower() != "read_file":
        return None

    params = _pseudo_parameter_values(content)
    file_path = str(params.get("file_path") or params.get("path") or "").strip()
    if not _is_quant_skill_file_path(file_path):
        return None
    return {
        "name": "read_file",
        "args": {"file_path": file_path},
        "id": f"call_quant_pseudo_read_file_{uuid.uuid4().hex[:8]}",
    }


def _is_quant_skill_read_request(request: ToolCallRequest) -> bool:
    if not _is_skill_read_tool_name(_tool_call_name(request.tool_call)):
        return False
    args = _tool_call_args(request.tool_call)
    return _is_quant_skill_file_path(args.get("file_path") or args.get("path"))


def _has_read_quant_native_skill(messages: list[object]) -> bool:
    for message in messages:
        if type(message).__name__ != "ToolMessage":
            continue
        content = str(getattr(message, "content", "") or "")
        if (
            "backend/skills/quant-developer/" in content
            or "name: quant-" in content
            or re.search(r"(?m)^name:\s+quant-[a-z0-9-]+", content)
        ):
            return True
    return False


@dataclass(frozen=True)
class QuantModelCallContext:
    request: ModelRequest
    messages: list[object]
    tools: list[object]
    runtime: object | None
    runtime_job_id: str | None
    runtime_query: str
    routing_text: str
    full_text: str
    data_files: dict[str, str]
    query: str
    latest_successful_handoff: str | None
    has_successful_handoff: bool
    has_written_analysis_script: bool
    should_stop_prewrite_loop: bool
    has_read_quant_native_skill: bool

    @classmethod
    def from_request(cls, request: ModelRequest) -> "QuantModelCallContext":
        return cls._from_parts(
            request=request,
            messages=list(request.messages),
            tools=list(request.tools),
            runtime=getattr(request, "runtime", None),
        )

    @classmethod
    def _from_parts(
        cls,
        *,
        request: ModelRequest,
        messages: list[object],
        tools: list[object],
        runtime: object | None,
    ) -> "QuantModelCallContext":
        full_text = _messages_text(messages)
        routing_text = _non_tool_messages_text(messages)
        runtime_query = _query_from_runtime(runtime)
        query = _best_query(
            _query_from_text(routing_text),
            _query_from_text(full_text),
            runtime_query,
        )
        latest_handoff = _latest_successful_quant_handoff_content(messages)
        return cls(
            request=request,
            messages=messages,
            tools=tools,
            runtime=runtime,
            runtime_job_id=_job_id_from_runtime(runtime),
            runtime_query=runtime_query,
            routing_text=routing_text,
            full_text=full_text,
            data_files=_data_files_from_text(full_text) or {},
            query=query,
            latest_successful_handoff=latest_handoff,
            has_successful_handoff=latest_handoff is not None,
            has_written_analysis_script=_has_written_analysis_script(messages),
            should_stop_prewrite_loop=_should_stop_prewrite_loop(messages),
            has_read_quant_native_skill=_has_read_quant_native_skill(messages),
        )

    @property
    def available_tool_names(self) -> set[str]:
        return {name for tool in self.tools if (name := _tool_name(tool))}

    @property
    def can_recover_before_write(self) -> bool:
        return not self.has_written_analysis_script and not self.has_successful_handoff

    def with_response_message(self, message: object) -> "QuantModelCallContext":
        return self._from_parts(
            request=self.request,
            messages=[*self.messages, message],
            tools=self.tools,
            runtime=self.runtime,
        )

    def prewrite_failure_response(
        self,
        *,
        structured_response: object | None = None,
        extra_message: object | None = None,
        failure_stage: str = "quant_initial_script_write",
        error: str | None = None,
        methods_used: list[str] | None = None,
    ) -> ModelResponse:
        messages = [*self.messages]
        if extra_message is not None:
            messages.append(extra_message)
        return ModelResponse(
            result=[
                AIMessage(
                    content=_prewrite_failure_handoff(
                        messages,
                        job_id=self.runtime_job_id,
                        failure_stage=failure_stage,
                        error=error,
                        methods_used=methods_used,
                    )
                )
            ],
            structured_response=structured_response,
        )


@dataclass(frozen=True)
class QuantModelResponseDecision:
    request: ModelRequest
    response: object | None = None

    @classmethod
    def call_model(cls, request: ModelRequest) -> "QuantModelResponseDecision":
        return cls(request=request)

    @classmethod
    def respond(
        cls,
        context: QuantModelCallContext,
        response: object,
    ) -> "QuantModelResponseDecision":
        return cls(request=context.request, response=response)

    @property
    def should_call_model(self) -> bool:
        return self.response is None


class QuantDeveloperToolBoundaryMiddleware(AgentMiddleware):
    """Force quant-developer to write the analysis script before probing data."""

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
        r"|(?:[\w./-]+/)?apt(?:-get)?\s+install"
        r"|ensurepip"
        r"|get-pip\.py"
        r")($|[\s;&|()])"
    )

    def _allowed_tools(self, context: QuantModelCallContext) -> set[str]:
        if context.has_written_analysis_script:
            return _AFTER_WRITE_TOOL_NAMES
        return _FIRST_WRITE_TOOL_NAMES

    def _filter_tools(self, context: QuantModelCallContext) -> ModelRequest:
        if context.has_successful_handoff:
            return context.request.override(tools=[])
        allowed = self._allowed_tools(context)
        tools = [
            tool
            for tool in context.request.tools
            if (
                (
                    _tool_name(tool) in allowed
                    or _is_skill_tool_name(_tool_name(tool))
                    or _is_skill_read_tool_name(_tool_name(tool))
                )
                and _tool_name(tool) not in _INSPECTION_TOOL_NAMES
            )
        ]
        if len(tools) == len(context.request.tools):
            return context.request
        return context.request.override(tools=tools)

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        context = QuantModelCallContext.from_request(request)
        decision = self._pre_model_response_decision(context)
        if not decision.should_call_model:
            return decision.response
        response = handler(decision.request)
        return self._post_model_response_decision(context, response).response

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        context = QuantModelCallContext.from_request(request)
        decision = self._pre_model_response_decision(context)
        if not decision.should_call_model:
            return decision.response
        response = await handler(decision.request)
        return self._post_model_response_decision(context, response).response

    def _pre_model_response_decision(
        self,
        context: QuantModelCallContext,
    ) -> QuantModelResponseDecision:
        if context.should_stop_prewrite_loop:
            return QuantModelResponseDecision.respond(
                context, context.prewrite_failure_response()
            )
        return QuantModelResponseDecision.call_model(self._filter_tools(context))

    def _post_model_response_decision(
        self,
        context: QuantModelCallContext,
        response: object,
    ) -> QuantModelResponseDecision:
        if not isinstance(response, ModelResponse):
            return QuantModelResponseDecision.respond(context, response)

        structured_response = getattr(response, "structured_response", None)
        if context.should_stop_prewrite_loop:
            return QuantModelResponseDecision.respond(
                context,
                context.prewrite_failure_response(
                    structured_response=structured_response,
                ),
            )
        if context.latest_successful_handoff is not None:
            return QuantModelResponseDecision.respond(
                context,
                ModelResponse(
                    result=[AIMessage(content=context.latest_successful_handoff)],
                    structured_response=structured_response,
                ),
            )
        if not context.can_recover_before_write:
            return QuantModelResponseDecision.respond(context, response)

        for message in getattr(response, "result", []) or []:
            content = str(getattr(message, "content", "") or "")
            if not any(marker in content for marker in _PSEUDO_TOOL_CALL_MARKERS):
                continue
            if not getattr(message, "tool_calls", None):
                recovered_tool_call = _pseudo_read_file_tool_call(content)
                if recovered_tool_call is not None:
                    return QuantModelResponseDecision.respond(
                        context,
                        self._tool_call_model_response(
                            recovered_tool_call,
                            structured_response=structured_response,
                        ),
                    )
                recovered_tool_call = _pseudo_write_file_tool_call(content)
                if recovered_tool_call is not None:
                    return QuantModelResponseDecision.respond(
                        context,
                        self._tool_call_model_response(
                            recovered_tool_call,
                            structured_response=structured_response,
                        ),
                    )
            return QuantModelResponseDecision.respond(
                context,
                context.prewrite_failure_response(
                    structured_response=structured_response,
                    extra_message=message,
                    failure_stage="quant_malformed_tool_call",
                    error=(
                        "quant-developer emitted pseudo tool-call markup instead of a "
                        "callable write_file request before creating code/analysis.py"
                    ),
                    methods_used=["quant_malformed_tool_call_guard"],
                ),
            )

        return QuantModelResponseDecision.respond(context, response)

    @staticmethod
    def _tool_call_model_response(
        tool_call: dict[str, object],
        *,
        structured_response: object | None,
    ) -> ModelResponse:
        return ModelResponse(
            result=[AIMessage(content="", tool_calls=[tool_call])],
            structured_response=structured_response,
        )

    def _blocked_tool_message(self, request: ToolCallRequest) -> ToolMessage:
        tool_name = _tool_call_name(request.tool_call) or "unknown_tool"
        path_hint = _required_script_path_hint(_job_id_from_request(request, ""))
        return ToolMessage(
            content=(
                f"Blocked tool `{tool_name}` for quant-developer. "
                "First write a compact analysis.py from the provided data_files and "
                "schema_summary. Do not inspect CSVs with shell probes; put loading, "
                "validation, and chart generation inside analysis.py. After the first "
                "script write, use execute/read_file/edit_file only for running and "
                "repairing that script. Import `save_quant_outputs` from "
                "`agents.quant_macro_stats` for artifact serialization; do not import "
                "`agents.quant_utils`. For econometric forecast tasks, import "
                "`direct_ols_forecast` from `agents.quant_macro_stats` and do not "
                "import `statsmodels` or hand-roll OLS diagnostics. Do not read "
                "`agents/quant_macro_stats/**`; the helper catalog in your prompt "
                "and skill context are sufficient. If you call "
                "`direct_ols_forecast` inside a recursive pseudo-OOS validation loop, "
                "pass `run_backtests=False` in those repeated calls and run the full "
                "helper backtests once for the current forecast artifact. For broad macro + equity + "
                "regional + international requests, your next script must be under "
                "120 lines and FRED/helper-centered. Use 3-4 computed charts for "
                "ordinary prompts, but target 6-8 distinct renderable charts for "
                "explicit chart, chart-pack, dashboard, visual-evidence, or "
                "chart-validation prompts. If the user explicitly requested international peers, "
                "regional consumers, or company earnings risk and those CSVs are in "
                "`data_files`, include compact table-style summaries in "
                "`execution_summary` from the handed-off schemas; otherwise preserve "
                'unused paths under `execution_summary["source_context_files"]`. '
                f"{path_hint} Your next assistant response should contain only the "
                "`write_file` tool call: exactly one `write_file` call to that path "
                "and no prose."
            ),
            name=tool_name,
            tool_call_id=_tool_call_id(request.tool_call),
            status="error",
        )

    def _runtime_install_rule(
        self, context: QuantToolCallContext
    ) -> QuantGuardrailDecision | None:
        if context.tool_name == "execute":
            command = str(context.args.get("command") or "")
            if self._PACKAGE_INSTALL_RE.search(command):
                return QuantGuardrailDecision.block(
                    context,
                    ToolMessage(
                        content=(
                            "Blocked quant-developer runtime package installation. "
                            "The quant execution environment already includes the "
                            "backend Python dependencies such as pandas, numpy, and scipy. "
                            "Run the generated analysis script with the configured "
                            "interpreter; do not run pip, uv, apt, poetry, conda, "
                            "mamba, ensurepip, or get-pip.py."
                        ),
                        name="execute",
                        tool_call_id=context.tool_call_id,
                        status="error",
                    ),
                )

        draft = context.write
        if draft is not None and draft.is_python and draft.tree is not None:
            if draft.syntax_error is None and _uses_runtime_installer(draft.tree):
                return QuantGuardrailDecision.block(
                    context,
                    ToolMessage(
                        content=(
                            "Blocked quant analysis script before writing because it "
                            "attempts runtime package installation. The quant "
                            "environment already includes pandas, numpy, and scipy; "
                            "optional libraries must degrade through the local helper "
                            "fallbacks instead of installing packages."
                        ),
                        name="write_file",
                        tool_call_id=context.tool_call_id,
                        status="error",
                    ),
                )
        return None

    def _script_budget_rule(
        self, context: QuantToolCallContext
    ) -> QuantGuardrailDecision | None:
        draft = context.write
        if draft is None:
            return None
        if not draft.is_python:
            return None
        if draft.content is None:
            return None
        line_count = draft.line_count
        char_count = draft.char_count
        if line_count <= _MAX_ANALYSIS_SCRIPT_LINES and char_count <= _MAX_ANALYSIS_SCRIPT_CHARS:
            return None
        return QuantGuardrailDecision.block(
            context,
            ToolMessage(
                content=(
                    "Blocked oversized quant analysis script before writing. "
                    f"Proposed script has {line_count} lines and {char_count} characters; "
                    f"limit is {_MAX_ANALYSIS_SCRIPT_LINES} lines and "
                    f"{_MAX_ANALYSIS_SCRIPT_CHARS} characters. Rewrite a compact "
                    "analysis.py under 120 lines. After three blocked drafts, the "
                    "next write is the final compact rewrite opportunity before a "
                    "failed handoff. Produce 3-4 computed charts for ordinary prompts, "
                    "or 6-8 distinct renderable charts for explicit chart, chart-pack, "
                    "dashboard, visual-evidence, or chart-validation prompts. Prioritize "
                    "recession-risk, unemployment outlook, scenario, and regime artifacts, "
                    "use a small DATA_FILES subset containing "
                    "only exact paths you will load. Include at most one compact "
                    "non-FRED summary block when the user explicitly requested peer, "
                    "state, or company metrics and matching World Bank, Census, SEC "
                    "EDGAR, or BLS CSVs were handed off; otherwise preserve those paths "
                    'under `execution_summary["source_context_files"]`. Loop over DATA_FILES '
                    "instead of repeating chart blocks, call "
                    "`save_quant_outputs(output_dir, charts, execution_summary)`, and "
                    "print only the compact handoff JSON. Use this minimum viable broad-macro "
                    "shape: one DATA_FILES subset with FRED keys plus any explicitly "
                    "required compact context CSVs, one `load_series` "
                    "helper, one `series_frames` dict, one `align_period_features(...)` "
                    "call, then helper calls for composite risk and either "
                    "caller-composed historical evidence (`build_analog_evidence(...)`, "
                    "`historical_scenario_replay(...)`, and/or "
                    "`signal_framework_backtest(...)`) for prior-cycle, "
                    "historical-simulation, replay, false-alarm, or pre-downturn "
                    "evidence with explicit replay windows, or the direct forecast path "
                    "when the user explicitly asks for a point forecast. Add scenario "
                    "table or regime classification only when requested or clearly "
                    "needed by the prompt. Do not add verbose SEC, "
                    "Census, World Bank, BLS, company, state, or country parsing loops to "
                    "the rewrite, and never leave requested provider sections as "
                    "`not processed` placeholders when data_files include those sources. "
                    "For explicit analog-window prompts, use the analog fast path "
                    "instead of the full broad macro template: define "
                    "`analog_windows` with explicit label/start/end dictionaries, align "
                    "the core FRED panel, call `build_analog_evidence(...)`, optionally call "
                    "`summarize_sec_company_facts(path)` for AAPL/MSFT, make three to "
                    "five charts from analog ranking/profile rows by default or six to "
                    "eight when the prompt explicitly asks for a chart-heavy pack, then save. Do not "
                    "add unemployment forecast, scenario, or regime-classifier helper "
                    "calls unless the user explicitly asked for those artifacts. "
                    "Do not inspect files before rewriting."
                ),
                name="write_file",
                tool_call_id=context.tool_call_id,
                status="error",
            ),
        )

    def _script_path_rule(
        self, context: QuantToolCallContext
    ) -> QuantGuardrailDecision | None:
        draft = context.write
        if draft is None:
            return None
        if _is_allowed_analysis_script_path(draft.file_path):
            return None
        path_hint = _required_script_path_hint(
            _job_id_from_request(context.request, draft.file_path)
        )
        reason = (
            "the target path is empty"
            if not draft.file_path
            else (
                f"the target path `{draft.file_path}` is outside the required code artifact location"
            )
        )
        return QuantGuardrailDecision.block(
            context,
            ToolMessage(
                content=(
                    "Blocked quant analysis script before writing because "
                    f"{reason}. {path_hint} Do not write analysis scripts directly "
                    "in the job output root."
                ),
                name="write_file",
                tool_call_id=context.tool_call_id,
                status="error",
            ),
        )

    def _existing_initial_script_rule(
        self, context: QuantToolCallContext
    ) -> QuantGuardrailDecision | None:
        draft = context.write
        if draft is None:
            return None
        if context.has_written_analysis_script:
            return None
        if not draft.file_path.replace("\\", "/").endswith("/code/analysis.py"):
            return None
        path = Path(draft.file_path).expanduser()
        if not path.exists():
            return None
        fallback_path = path.with_name("analysis_v2.py")
        return QuantGuardrailDecision.block(
            context,
            ToolMessage(
                content=(
                    "Blocked initial quant script write because `analysis.py` already "
                    f"exists at `{path}` from an earlier quant attempt for this job. "
                    f"Write one compact replacement script to `{fallback_path}` and "
                    "execute that file. Still save final artifacts to the job output "
                    "directory via `save_quant_outputs`; do not inspect, delete, or "
                    "overwrite the existing `analysis.py` first."
                ),
                name="write_file",
                tool_call_id=context.tool_call_id,
                status="error",
            ),
        )

    def _truncated_argument_rule(
        self, context: QuantToolCallContext
    ) -> QuantGuardrailDecision | None:
        draft = context.write
        if draft is None:
            return None
        if draft.content is None:
            return None
        marker = next(
            (marker for marker in _TRUNCATED_ARGUMENT_MARKERS if marker in draft.content),
            None,
        )
        if marker is None:
            return None
        return QuantGuardrailDecision.block(
            context,
            ToolMessage(
                content=(
                    "Blocked quant analysis script before writing because the proposed "
                    f"`write_file` content contains the tool-argument truncation marker "
                    f"`{marker}`. This is not a recoverable script draft. Rewrite a much "
                    "smaller complete analysis.py under 180 lines, with one DATA_FILES "
                    "dictionary, small helper functions, and compact JSON outputs. Do not "
                    "write, execute, delete, or patch a truncated placeholder file."
                ),
                name="write_file",
                tool_call_id=context.tool_call_id,
                status="error",
            ),
        )

    def _python_static_lint_rule(
        self, context: QuantToolCallContext
    ) -> QuantGuardrailDecision | None:
        draft = context.write
        if draft is None:
            return None
        if not draft.is_python:
            return None
        if draft.content is None:
            return None

        if draft.syntax_error is not None:
            syntax_error = draft.syntax_error
            location = (
                f"line {syntax_error.lineno}, column {syntax_error.offset}"
                if syntax_error.lineno is not None
                else "unknown location"
            )
            return QuantGuardrailDecision.block(
                context,
                ToolMessage(
                    content=(
                        "Blocked quant analysis script before writing because Python "
                        f"syntax validation failed at {location}: {syntax_error.msg}. "
                        "Rewrite a complete compact file before calling `write_file`; "
                        "do not rely on execute/read/edit cycles to close truncated "
                        "dicts, strings, or JSON handoff blocks."
                    ),
                    name="write_file",
                    tool_call_id=context.tool_call_id,
                    status="error",
                ),
            )

        tree = draft.tree
        if tree is None:
            return None
        for call in _calls_named(tree, "align_period_features"):
            if len(call.args) > 1:
                return QuantGuardrailDecision.block(
                    context,
                    ToolMessage(
                        content=(
                            "Blocked quant analysis script before writing because "
                            "`align_period_features` accepts only `series_frames` as a "
                            "positional argument. Use keyword arguments for the rest: "
                            'align_period_features(series_frames, frequency="M", '
                            'how="outer", timestamp_position="start", '
                            'fill_method="ffill", fill_limit=2).'
                        ),
                        name="write_file",
                        tool_call_id=context.tool_call_id,
                        status="error",
                    ),
                )
        if period_ref_name := _align_period_output_period_reference(tree):
            return QuantGuardrailDecision.block(
                context,
                ToolMessage(
                    content=(
                        "Blocked quant analysis script before writing because "
                        f"`{period_ref_name}` is assigned from `align_period_features(...)` "
                        "and then read as if it has a `period` column. "
                        "`align_period_features` returns only `date` plus one column per "
                        "series key; use the returned `date` column for chart labels, "
                        "sorting, and forecast frames. Do not reference "
                        f'`{period_ref_name}["period"]` or `{period_ref_name}.period`.'
                    ),
                    name="write_file",
                    tool_call_id=context.tool_call_id,
                    status="error",
                ),
            )
        for call in _calls_named(tree, "to_period"):
            freq = _literal_string_arg(call)
            if freq in {"ME", "QE"}:
                replacement = "M" if freq == "ME" else "Q"
                return QuantGuardrailDecision.block(
                    context,
                    ToolMessage(
                        content=(
                            "Blocked quant analysis script before writing because "
                            f"`to_period({freq!r})` uses a pandas resample alias. "
                            f"Use `to_period({replacement!r})` for Period conversion. "
                            "Keep `resample('ME')`/`resample('QE')` only for "
                            "resampling, then convert dates to period keys with "
                            "`to_period('M')` or `to_period('Q')`."
                        ),
                        name="write_file",
                        tool_call_id=context.tool_call_id,
                        status="error",
                    ),
                )
        return None

    def _data_manifest_rule(
        self, context: QuantToolCallContext
    ) -> QuantGuardrailDecision | None:
        draft = context.write
        if draft is None:
            return None
        if not draft.is_python:
            return None
        if draft.content is None:
            return None

        manifest = draft.manifest
        if not manifest:
            return None

        invalid: list[str] = []
        missing: list[str] = []
        for key, path_text in manifest.items():
            suffix = Path(path_text).suffix.lower()
            if suffix not in _DATA_FILE_SUFFIXES:
                invalid.append(f"{key} -> {path_text}")
                continue
            if not Path(path_text).expanduser().exists():
                missing.append(f"{key} -> {path_text}")
        if not invalid and not missing:
            return None

        details: list[str] = []
        if invalid:
            details.append("non-data extension: " + "; ".join(invalid[:4]))
        if missing:
            details.append("missing file: " + "; ".join(missing[:4]))
        return QuantGuardrailDecision.block(
            context,
            ToolMessage(
                content=(
                    "Blocked quant analysis script before writing because its DATA_FILES "
                    "manifest does not match existing data artifacts ("
                    + " | ".join(details)
                    + "). Copy exact CSV paths from the task description for only the "
                    "DATA_FILES keys the script will load; do not mutate CSV paths into "
                    "chart/image paths, hand-edit auto-save suffixes, or guess filenames."
                ),
                name="write_file",
                tool_call_id=context.tool_call_id,
                status="error",
            ),
        )

    def _data_manifest_repair_rule(
        self, context: QuantToolCallContext
    ) -> QuantGuardrailDecision | None:
        draft = context.write
        if draft is None:
            return None
        if not draft.is_python:
            return None
        if draft.content is None:
            return None

        manifest = draft.manifest
        if not manifest:
            return None

        replacements: dict[str, str] = {}
        for path_text in manifest.values():
            if Path(path_text).expanduser().exists():
                continue
            if repaired := _unique_existing_sibling_data_path(path_text):
                replacements[path_text] = repaired
            else:
                return None
        if not replacements:
            return None

        rewritten = _rewrite_manifest_paths(draft.content, replacements)
        if rewritten is None:
            return None
        return QuantGuardrailDecision.replace_request(
            _request_with_tool_content(context.request, rewritten)
        )

    def _period_alignment_rule(
        self, context: QuantToolCallContext
    ) -> QuantGuardrailDecision | None:
        draft = context.write
        if draft is None:
            return None
        if not draft.is_python:
            return None
        if draft.content is None:
            return None
        manifest = draft.manifest
        if not manifest or not _needs_period_alignment_guard(manifest):
            return None
        if "align_period_features(" in draft.content:
            return None
        return QuantGuardrailDecision.block(
            context,
            ToolMessage(
                content=(
                    "Blocked mixed-frequency FRED analysis script before writing. "
                    "The DATA_FILES manifest combines high-frequency series such as "
                    "Treasury yields or initial claims with monthly/quarterly macro "
                    "series. Import and call `align_period_features(series_frames, "
                    'frequency="M", how="outer", timestamp_position="start", '
                    'fill_method="ffill", fill_limit=2)` '
                    "from `agents.quant_macro_stats` before deriving features or "
                    "calling `direct_ols_forecast`; do not first merge resampled "
                    "month-end timestamps against month-start FRED observations."
                ),
                name="write_file",
                tool_call_id=context.tool_call_id,
                status="error",
            ),
        )

    def _sec_company_facts_rule(
        self, context: QuantToolCallContext
    ) -> QuantGuardrailDecision | None:
        draft = context.write
        if draft is None:
            return None
        if not draft.is_python:
            return None
        content = draft.content
        if content is None:
            return None
        lowered = content.lower()
        tree = draft.tree
        manifest = draft.manifest or {}
        has_sec_company_facts = any(
            "sec_edgar_company_facts" in Path(path_text).name.lower()
            for path_text in manifest.values()
        )
        has_sec_company_facts = has_sec_company_facts or "sec_edgar_company_facts" in lowered
        if not has_sec_company_facts:
            return None
        positional_numeric_patterns = (
            "select_dtypes",
            ".iloc[:,-",
            ".iloc[:, -",
            ".iloc[: , -",
            "numeric_columns[-",
        )
        if any(pattern in lowered for pattern in positional_numeric_patterns):
            return QuantGuardrailDecision.block(
                context,
                ToolMessage(
                    content=(
                        "Blocked SEC company-facts analysis before writing because it "
                        "derives issuer metrics from positional numeric columns. SEC "
                        "company-facts CSVs include shares, assets, liabilities, and other "
                        "numeric fields, so positional inference can produce impossible "
                        "margins or growth rates. Import `summarize_sec_company_facts` "
                        "from `agents.quant_macro_stats`, call it once per issuer CSV, and "
                        "use named fields such as `revenue`, `net_income`, "
                        "`operating_income`, `assets`, and `long_term_debt` for reusable "
                        "fundamentals, trend diagnostics, sensitivity rows, and charts "
                        "composed in `analysis.py`."
                    ),
                    name="write_file",
                    tool_call_id=context.tool_call_id,
                    status="error",
                ),
            )

        computes_order_sensitive_growth = (
            "pct_change(" in lowered
            or "cagr" in lowered
            or "values[-1]" in lowered
            or ".iloc[-1]" in lowered
        )
        if (
            computes_order_sensitive_growth
            and tree is not None
            and _calls_named(tree, "summarize_sec_company_facts")
            and not _calls_named(tree, "read_csv")
        ):
            return None
        fiscal_year_sort_patterns = (
            '.sort_values("fiscal_year"',
            ".sort_values('fiscal_year'",
            '.sort_values(by="fiscal_year"',
            ".sort_values(by='fiscal_year'",
        )
        if (
            computes_order_sensitive_growth
            and "fiscal_year" in lowered
            and not any(pattern in lowered for pattern in fiscal_year_sort_patterns)
        ):
            return QuantGuardrailDecision.block(
                context,
                ToolMessage(
                    content=(
                        "Blocked SEC company-facts analysis before writing because it "
                        "computes year-over-year growth, latest/first values, or CAGR "
                        "without first sorting rows by `fiscal_year` ascending. SEC "
                        "company-facts handoffs may arrive latest-first; unsorted "
                        "`pct_change()`, `.iloc[-1]`, or `values[-1] / values[0]` "
                        "can invert growth rates and misstate the report. After loading "
                        "each issuer CSV, run "
                        '`frame = frame.sort_values("fiscal_year").reset_index(drop=True)` '
                        "before deriving growth, CAGR, latest rows, chart rows, or "
                        "execution_summary values. Prefer `summarize_sec_company_facts` "
                        "for compact named-column issuer summaries."
                    ),
                    name="write_file",
                    tool_call_id=context.tool_call_id,
                    status="error",
                ),
            )
        return None

    def _macro_helper_contract_rule(
        self, context: QuantToolCallContext
    ) -> QuantGuardrailDecision | None:
        draft = context.write
        if draft is None:
            return None
        if not draft.is_python:
            return None
        content = draft.content
        if content is None:
            return None

        if draft.syntax_error is not None:
            return None

        tree = draft.tree
        if tree is None:
            return None
        scenario_calls = _calls_named(tree, "normalize_scenario_evidence_rows")
        if any(_has_empty_list_call_arg(call) for call in scenario_calls):
            return QuantGuardrailDecision.block(
                context,
                ToolMessage(
                    content=(
                        "Blocked scenario evidence normalization before writing because "
                        "`normalize_scenario_evidence_rows([])` always fails validation "
                        "and causes avoidable edit loops. Define caller-specific "
                        "`scenario_rows` first with scenario labels plus reusable "
                        "metrics, scores, values, drivers, notes, or evidence, not "
                        "report narrative, then save the normalized rows as top-level "
                        "`scenario_score_rows` or another generic evidence key in "
                        "`execution_summary`."
                    ),
                    name="write_file",
                    tool_call_id=context.tool_call_id,
                    status="error",
                ),
            )

        manifest = draft.manifest or {}
        manifest_keys = {key.upper() for key in manifest}
        has_recession_indicator = "USREC" in manifest_keys
        lowered = content.lower()
        if (
            _calls_named(tree, "save_quant_outputs")
            and "chart_ids = list(charts.keys())" in content
        ):
            return QuantGuardrailDecision.block(
                context,
                ToolMessage(
                    content=(
                        "Blocked stale quant handoff before writing. "
                        "`save_quant_outputs(...)` may drop chart definitions that do "
                        "not satisfy the frontend render contract, so do not rebuild "
                        "`chart_ids` from the original `charts` dict after calling it. "
                        "Use `handoff = save_quant_outputs(output_dir, charts, "
                        "execution_summary)` and `print(json.dumps(handoff))` so the "
                        "writer receives only saved chart IDs."
                    ),
                    name="write_file",
                    tool_call_id=context.tool_call_id,
                    status="error",
                ),
            )
        removed_preservation_surfaces = sorted(
            surface
            for surface in _REMOVED_QUANT_OUTPUT_PRESERVATION_SURFACES
            if surface in content
        )
        if removed_preservation_surfaces:
            surfaces = ", ".join(
                f"`{surface}`" for surface in removed_preservation_surfaces
            )
            return QuantGuardrailDecision.block(
                context,
                ToolMessage(
                    content=(
                        "Blocked stale quant-output preservation surface before writing. "
                        f"Remove {surfaces}. `save_quant_outputs(...)` now writes only "
                        "the current `analysis.py` chart payload and execution summary; "
                        "compose any validation rows directly in `execution_summary` "
                        "before saving."
                    ),
                    name="write_file",
                    tool_call_id=context.tool_call_id,
                    status="error",
                ),
            )

        missing_helpers: list[tuple[str, str]] = []
        regime_keys = (
            "current_regime_row",
            "regime_evidence_rows",
            "regime_history_rows",
            "regime_analog_rows",
            "missing_indicator_rows",
            "regime_design",
            "category_scores",
        )
        if any(key in content for key in regime_keys) and not _calls_named(
            tree, "classify_recession_regime"
        ):
            missing_helpers.append(("regime classification", "classify_recession_regime"))
        if "scenario_table" in content:
            return QuantGuardrailDecision.block(
                context,
                ToolMessage(
                    content=(
                        "Blocked report-specific scenario_table handoff before writing. "
                        "Quant helper scripts should preserve reusable scenario evidence "
                        "rows such as `scenario_score_rows`; compose any base/bull/bear "
                        "report table inside the writer-facing narrative or report layer."
                    ),
                    name="write_file",
                    tool_call_id=context.tool_call_id,
                    status="error",
                ),
            )
        if "scenario_score_rows" in content and not _calls_named(
            tree, "normalize_scenario_evidence_rows"
        ):
            missing_helpers.append(
                ("scenario evidence rows", "normalize_scenario_evidence_rows")
            )
        recession_risk_keys = (
            "composite_risk",
            "recession_risk",
            "composite_current_row",
            "composite_index",
            "weights_or_model",
        )
        if (
            has_recession_indicator
            and any(key in lowered for key in recession_risk_keys)
            and not _calls_named(tree, "build_composite_predictive_indicator")
        ):
            missing_helpers.append(
                ("recession-risk framework", "build_composite_predictive_indicator")
            )
        signal_framework_markers = (
            "false_alarm",
            "pre_recession",
            "recession_calls_correct",
            "signal_framework",
        )
        if (
            has_recession_indicator
            and any(marker in lowered for marker in signal_framework_markers)
            and not _calls_named(tree, "signal_framework_backtest")
            and not _calls_named(tree, "event_signal_backtest")
            and not _calls_named(tree, "historical_scenario_replay")
        ):
            missing_helpers.append(
                ("signal framework hit/miss evidence", "signal_framework_backtest")
            )
        if "analog_similarity_ranking" in content and not (
            _calls_named(tree, "build_analog_evidence")
            or _calls_named(tree, "compare_analog_windows")
        ):
            missing_helpers.append(
                ("analog evidence rows", "build_analog_evidence")
            )

        bad_signal_recession_cols: list[str] = []
        for call in _calls_named(tree, "signal_framework_backtest"):
            recession_col = _literal_string_arg(call, keyword_name="recession_col")
            if recession_col and recession_col.upper() in {
                "UNRATE",
                "UNEMPLOY",
                "UEMPMEAN",
            }:
                bad_signal_recession_cols.append(recession_col)
        if bad_signal_recession_cols:
            bad_cols = ", ".join(sorted(set(bad_signal_recession_cols)))
            return QuantGuardrailDecision.block(
                context,
                ToolMessage(
                    content=(
                        "Blocked invalid signal-framework backtest before writing. "
                        "`signal_framework_backtest(...)` requires `recession_col` to "
                        "be a binary 0/1 event indicator such as `USREC`, not a "
                        f"continuous labor-market level like {bad_cols}. Keep UNRATE "
                        "as the forecast target/outcome, derive binary component "
                        "columns for warning signals, and call "
                        "`signal_framework_backtest(panel, component_cols=component_cols, "
                        'recession_col="USREC", date_col="date", threshold=2, '
                        "lookback_periods=12, false_alarm_lookahead_periods=12)`."
                    ),
                    name="write_file",
                    tool_call_id=context.tool_call_id,
                    status="error",
                ),
            )

        if not missing_helpers:
            return None

        details = "; ".join(
            f"{artifact} requires `{helper}`" for artifact, helper in missing_helpers[:3]
        )
        missing_helper_names = {helper for _, helper in missing_helpers}
        targeted_forecast_recipe = ""
        if (
            "signal_framework_backtest" in missing_helper_names
            and _has_forecast_evidence_script(tree)
        ):
            targeted_forecast_recipe = (
                "For a script that already composes reusable forecast evidence rows "
                "and is missing signal hit/miss evidence, derive predictor, "
                "component-score, and event columns on the aligned panel, then compose "
                "`direct_ols_forecast`, `walk_forward_ols_backtest`, "
                "`event_signal_backtest`, and generic forecast row helpers such as "
                "`forecast_band_rows`, `forecast_model_comparison_rows`, "
                "`forecast_failure_episodes`, `forecast_false_alarm_episodes`, and "
                "`predictor_contribution_rows`. Preserve top-level `forecast_table`, "
                "`model_comparison_by_horizon`, `historical_failure_episodes`, "
                "`event_backtest_metrics`, `signal_false_positive_windows`, "
                "diagnostics, methods, and limitations in `execution_summary`; "
                "compose any baseline comparison wording, false-positive prose, and "
                "requested charts locally from those reusable evidence rows. "
            )
        recovery_recipe = (
            f"{targeted_forecast_recipe}"
            "Use these canonical calls without inspecting helper source: "
            "`composite = build_composite_predictive_indicator(panel, "
            'target_col="USREC", feature_cols=feature_cols, date_col="date", '
            'target="recession_risk", prediction_horizon=1, '
            'feature_transforms={feature: "level" for feature in feature_cols}, '
            "feature_directions=feature_directions, "
            'normalization_method="zscore", min_feature_coverage=3)`; '
            "merge `composite_current_row`, `composite_score_rows`, "
            "`composite_validation_metrics`, `composite_validation_design`, "
            "`feature_coverage`, `feature_transforms`, `normalization_stats`, "
            "`weights_or_model`, and `thresholds` into `execution_summary`; "
            "`scenario_score_rows = normalize_scenario_evidence_rows(rows)` "
            "where rows contain caller-chosen scenario labels plus reusable "
            "metrics, scores, values, drivers, notes, or evidence, not report "
            "narrative, then preserve `scenario_score_rows` as top-level "
            "`execution_summary` evidence; "
            '`regime = classify_recession_regime(scored_frame, date_col="date", '
            'indicator_specs=indicator_specs, recession_col="USREC", '
            "momentum_periods=3, min_categories=3, analog_count=3)`. "
            "Merge `current_regime_row`, `regime_evidence_rows`, "
            "`regime_history_rows`, `regime_analog_rows`, "
            "`missing_indicator_rows`, and `regime_design` into "
            "`execution_summary`; compose any prose labels, caveats, or report "
            "sections inside `analysis.py`, not inside the helper contract. "
            "`replay = historical_scenario_replay(panel, "
            'signal_cols=["composite_index"], outcome_col="USREC", '
            'date_col="date", windows=replay_windows, lookahead_periods=12)` '
            "after attaching the composite score to the aligned panel, then "
            'copy `replay["replay_rows"]` and `replay["replay_design"]` into '
            "`execution_summary` when historical replay evidence is relevant. "
            "For threshold component frameworks, "
            "`signal_bt = signal_framework_backtest(panel, component_cols=component_cols, "
            'recession_col="USREC", date_col="date", threshold=3, '
            "lookback_periods=12, false_alarm_lookahead_periods=12)` and merge "
            "its reusable backtest rows into `execution_summary`. "
            "`analog = build_analog_evidence(panel, value_cols=value_cols, "
            'current_window={"start": current_start, "end": latest_date}, '
            "analog_windows=analog_windows)` after defining explicit "
            "label/start/end windows in `analysis.py`; preserve rankings, coverage, "
            "profile rows, and diagnostics as generic evidence. "
            "For an explicit analog-window prompt, this analog call is the main "
            "quant framework; do not also add forecast, scenario, or regime helper "
            "calls unless those outputs were explicitly requested. "
            "Merge returned dictionaries into `execution_summary` and keep the "
            "script under 120 lines. Use 3-4 charts for ordinary prompts, or "
            "6-8 distinct renderable charts for explicit chart, chart-pack, "
            "dashboard, visual-evidence, or chart-validation prompts."
        )
        return QuantGuardrailDecision.block(
            context,
            ToolMessage(
                content=(
                    "Blocked broad macro analysis script before writing because it "
                    "hand-rolls helper-owned quantitative artifacts. "
                    f"{details}. Import the required helper(s) from "
                    "`agents.quant_macro_stats`, call them inside `analysis.py`, merge "
                    "their returned dictionaries into `execution_summary`, and then "
                    "write artifacts with `save_quant_outputs`. This prevents oversized "
                    "scripts and avoidable repair loops from bespoke regime, scenario, "
                    "or recession-risk code. "
                    f"{recovery_recipe}"
                ),
                name="write_file",
                tool_call_id=context.tool_call_id,
                status="error",
            ),
        )

    def _quant_output_contract_rule(
        self, context: QuantToolCallContext
    ) -> QuantGuardrailDecision | None:
        draft = context.write
        if draft is None:
            return None
        if not draft.is_python:
            return None
        content = draft.content
        if content is None:
            return None

        tree = draft.tree
        if draft.syntax_error is not None or tree is None:
            return None
        if _calls_named(tree, "save_quant_outputs"):
            return None

        writes_quant_artifacts = "charts.json" in content or "execution_summary.json" in content
        if not writes_quant_artifacts:
            return None
        if not (
            _calls_named(tree, "json.dump")
            or _calls_named(tree, "dumps")
            or ".write_text(" in content
            or "open(" in content
        ):
            return None

        return QuantGuardrailDecision.block(
            context,
            ToolMessage(
                content=(
                    "Blocked manual quant artifact serialization before writing. "
                    "Do not write `charts.json` or `execution_summary.json` with "
                    "`json.dump`, `Path.write_text`, or raw file handles. Import "
                    "`save_quant_outputs` from `agents.quant_macro_stats`, call "
                    "`handoff = save_quant_outputs(output_dir, charts, execution_summary)`, "
                    "and `print(json.dumps(handoff))`. The helper writes strict JSON "
                    "with non-finite values converted to null, canonicalizes chart "
                    "shapes, drops non-renderable charts, and returns the saved "
                    "`chart_ids` so downstream report markers cannot drift."
                ),
                name="write_file",
                tool_call_id=context.tool_call_id,
                status="error",
            ),
        )

    def _forecast_helper_contract_rule(
        self, context: QuantToolCallContext
    ) -> QuantGuardrailDecision | None:
        draft = context.write
        if draft is None:
            return None
        if not draft.is_python:
            return None
        content = draft.content
        if content is None:
            return None

        if draft.syntax_error is not None:
            return None

        tree = draft.tree
        if tree is None:
            return None
        lowered = content.lower()
        forecast_context = any(
            token in lowered
            for token in (
                "forecast",
                "unemployment outlook",
                "unrate",
                "prediction_interval",
            )
        )
        handrolled_forecast = _imports_forbidden_forecast_library(tree) or bool(
            _calls_named(tree, "LinearRegression")
        )
        if (
            forecast_context
            and handrolled_forecast
            and not _calls_named(tree, "direct_ols_forecast")
        ):
            return QuantGuardrailDecision.block(
                context,
                ToolMessage(
                    content=(
                        "Blocked econometric forecast script before writing because it "
                        "hand-rolls a local regression forecast. Importing "
                        "`direct_ols_forecast` is not enough. For governed "
                        "forecast evidence, compose `direct_ols_forecast(...)`, "
                        "`walk_forward_ols_backtest(...)`, and generic forecast "
                        "row helpers such as `forecast_model_comparison_rows(...)`, "
                        "`forecast_failure_episodes(...)`, and "
                        "`forecast_band_rows(...)`; then compose top-level "
                        "`forecast_table`, `model_comparison_by_horizon`, "
                        "`historical_failure_episodes`, diagnostics, methods, and "
                        "limitations in `analysis.py`. Compose baseline "
                        "comparison conclusions from `model_comparison_by_horizon`. "
                        "Do not "
                        "import sklearn/statsmodels or write a second manual forecast loop. "
                        "If you need many recursive pseudo-OOS forecast calls, use "
                        "`run_backtests=False` on those repeated helper calls so each "
                        "iteration does not recursively run a full walk-forward backtest."
                    ),
                    name="write_file",
                    tool_call_id=context.tool_call_id,
                    status="error",
                ),
            )
        if forecast_context and handrolled_forecast and _calls_named(tree, "direct_ols_forecast"):
            return QuantGuardrailDecision.block(
                context,
                ToolMessage(
                    content=(
                        "Blocked econometric forecast script before writing because it "
                        "adds a manual sklearn/statsmodels forecast or replay loop next "
                        "to `direct_ols_forecast(...)`. The helper already owns the OLS "
                        "forecast rows, walk-forward backtests, model validation rows, "
                        "and diagnostics. When you need forecast bands, baseline "
                        "comparisons, false-positive rows, and reusable forecast rows, compose "
                        "`direct_ols_forecast(...)`, `walk_forward_ols_backtest(...)`, "
                        "`event_signal_backtest(...)`, and generic forecast row "
                        "helpers and compose the execution summary from those reusable "
                        "rows instead of "
                        "importing sklearn/statsmodels or fitting another regression loop."
                    ),
                    name="write_file",
                    tool_call_id=context.tool_call_id,
                    status="error",
                ),
            )
        if forecast_context and _looped_direct_forecasts_without_backtest_skip(tree):
            return QuantGuardrailDecision.block(
                context,
                ToolMessage(
                    content=(
                        "Blocked econometric forecast script before writing because it "
                        "calls `direct_ols_forecast` inside a loop without "
                        "`run_backtests=False`. Recursive pseudo-OOS validation loops "
                        "must use `direct_ols_forecast(..., run_backtests=False)` for "
                        "the repeated cut-date forecasts, then run one default full "
                        "`direct_ols_forecast(...)` call plus reusable forecast row "
                        "helpers for the current forecast evidence."
                    ),
                    name="write_file",
                    tool_call_id=context.tool_call_id,
                    status="error",
                ),
            )
        return None

    def _helper_source_read_rule(
        self, context: QuantToolCallContext
    ) -> QuantGuardrailDecision | None:
        if context.tool_name != "read_file":
            return None
        file_path = str(context.args.get("file_path") or context.args.get("path") or "")
        if not file_path:
            return None
        helper_package_dir = (_BACKEND_DIR / "agents" / "quant_macro_stats").resolve()
        try:
            helper_source_path = Path(file_path).expanduser().resolve()
            legacy_helper_file = (
                _BACKEND_DIR / "agents" / "quant_macro_stats.py"
            ).resolve()
            is_helper_source = (
                helper_source_path == legacy_helper_file
                or helper_source_path == helper_package_dir
                or helper_package_dir in helper_source_path.parents
            )
        except OSError:
            normalized_path = file_path.replace("\\", "/")
            is_helper_source = normalized_path.endswith(
                "/agents/quant_macro_stats.py"
            ) or "/agents/quant_macro_stats/" in normalized_path
        if not is_helper_source:
            return None
        return QuantGuardrailDecision.block(
            context,
            ToolMessage(
                content=(
                    "Blocked helper-source inspection for quant-developer. Do not read "
                    "`agents/quant_macro_stats/**` to rediscover signatures during a "
                    "repair loop. Patch the local analysis script using this helper "
                    "catalog instead:\n"
                    f"{format_quant_helper_catalog_for_prompt()}\n"
                    "For composite recession risk, preserve reusable composite rows, "
                    "validation metrics, design, coverage, transforms, normalization "
                    "stats, weights, and thresholds as top-level `execution_summary` "
                    "evidence. For scenarios use `normalize_scenario_evidence_rows(rows)`. "
                    "For analog work call `build_analog_evidence(panel, value_cols=value_cols, "
                    "current_window=current_window, analog_windows=analog_windows)`; and "
                    '`classify_recession_regime(scored_frame, date_col="date", '
                    'indicator_specs=indicator_specs, recession_col="USREC", '
                    "momentum_periods=3, min_categories=3, analog_count=3)` and "
                    "preserve its generic regime rows/design in `execution_summary`; "
                    "`historical_scenario_replay(panel, signal_cols=signal_cols, "
                    'outcome_col="USREC", date_col="date", windows=replay_windows, '
                    'lookahead_periods=12)`; '
                    'and `event_signal_backtest(panel, signal_col="composite", '
                    'target_col="USREC", date_col="date", threshold=3, '
                    'direction="high", prediction_horizon=12)`; or '
                    "`signal_framework_backtest(panel, component_cols=component_cols, "
                    'recession_col="USREC", date_col="date", threshold=3, '
                    "lookback_periods=12, false_alarm_lookahead_periods=12)` for "
                    "multi-component threshold score frameworks. "
                    "Use `read_file` only for the generated analysis script or traceback "
                    "context, then repair with `edit_file`."
                ),
                name="read_file",
                tool_call_id=context.tool_call_id,
                status="error",
            ),
        )

    def _handoff_complete_message(self, request: ToolCallRequest) -> ToolMessage:
        tool_name = _tool_call_name(request.tool_call) or "unknown_tool"
        return ToolMessage(
            content=(
                "Blocked post-success quant tool call. A prior execute result already "
                "returned the compact handoff fields `charts_json`, "
                "`execution_summary_json`, and `chart_ids`. Return only that compact "
                "JSON now; do not run exploratory checks, read files, or edit the "
                "successful script unless a later tool result reported a concrete "
                "validation failure."
            ),
            name=tool_name,
            tool_call_id=_tool_call_id(request.tool_call),
            status="error",
        )

    def _tool_runtime_exception_message(
        self, request: ToolCallRequest, exc: Exception
    ) -> ToolMessage:
        tool_name = _tool_call_name(request.tool_call) or "unknown_tool"
        exc_type = type(exc).__name__
        exc_text = str(exc).strip() or "<empty exception message>"
        content = (
            f"Recoverable `{tool_name}` tool runtime error for quant-developer: "
            f"{exc_type}: {exc_text}. "
        )
        if tool_name == "write_file" and not _has_written_analysis_script(
            _state_messages(getattr(request, "state", None))
        ):
            content += (
                "The initial analysis script was not confirmed written. Retry with "
                "exactly one compact `write_file` call using both named arguments: "
                "`file_path` ending in `/code/analysis.py` and complete `content` "
                "under the script budget. Do not call read_file, execute, ls, glob, "
                "or shell probes before that write succeeds."
            )
        else:
            content += (
                "Inspect the last concrete tool result, then retry the smallest "
                "valid tool call or return a failed quant handoff if recovery is not "
                "possible."
            )
        return ToolMessage(
            content=content,
            name=tool_name,
            tool_call_id=_tool_call_id(request.tool_call),
            status="error",
        )

    def _run_guardrail_rules(
        self,
        context: QuantToolCallContext,
        rules: tuple[
            Callable[[QuantToolCallContext], QuantGuardrailDecision | None],
            ...,
        ],
    ) -> QuantGuardrailDecision:
        for rule in rules:
            decision = rule(context)
            if decision is None:
                continue
            if decision.blocked:
                return decision
            if decision.request is not context.request:
                context = QuantToolCallContext.from_request(decision.request)
        return QuantGuardrailDecision.allow(context)

    def _pre_handler_tool_call_decision(
        self, request: ToolCallRequest
    ) -> QuantGuardrailDecision:
        context = QuantToolCallContext.from_request(request)
        if context.has_successful_handoff:
            return QuantGuardrailDecision.block(
                context, self._handoff_complete_message(request)
            )
        if _is_skill_tool_name(context.tool_name):
            return QuantGuardrailDecision.allow(context)
        if not context.has_written_analysis_script:
            if _is_quant_skill_read_request(request):
                return QuantGuardrailDecision.allow(context)
            if context.tool_name not in _FIRST_WRITE_TOOL_NAMES:
                return QuantGuardrailDecision.block(
                    context, self._blocked_tool_message(request)
                )
        if context.tool_name not in _AFTER_WRITE_TOOL_NAMES:
            return QuantGuardrailDecision.block(context, self._blocked_tool_message(request))

        hard_decision = self._run_guardrail_rules(
            context,
            (
                self._runtime_install_rule,
                self._script_path_rule,
                self._existing_initial_script_rule,
                self._helper_source_read_rule,
                self._truncated_argument_rule,
                self._script_budget_rule,
                self._python_static_lint_rule,
                self._data_manifest_repair_rule,
                self._data_manifest_rule,
            ),
        )
        if hard_decision.blocked:
            return hard_decision
        context = QuantToolCallContext.from_request(hard_decision.request)
        if context.is_final_prewrite_opportunity:
            return QuantGuardrailDecision.allow(context)
        return self._run_guardrail_rules(
            context,
            (
                self._period_alignment_rule,
                self._sec_company_facts_rule,
                self._quant_output_contract_rule,
                self._macro_helper_contract_rule,
                self._forecast_helper_contract_rule,
            ),
        )

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage],
    ) -> ToolMessage:
        guarded_request = request
        try:
            decision = self._pre_handler_tool_call_decision(request)
            guarded_request = decision.request
            if decision.message is not None:
                return decision.message
            return handler(guarded_request)
        except Exception as exc:
            return self._tool_runtime_exception_message(guarded_request, exc)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage]],
    ) -> ToolMessage:
        guarded_request = request
        try:
            decision = self._pre_handler_tool_call_decision(request)
            guarded_request = decision.request
            if decision.message is not None:
                return decision.message
            return await handler(guarded_request)
        except Exception as exc:
            return self._tool_runtime_exception_message(guarded_request, exc)

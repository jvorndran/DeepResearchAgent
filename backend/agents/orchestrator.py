"""
Orchestrator — deterministic intake → approval → execution pipeline.

The orchestrator is a parent ``StateGraph`` that wires together:

1. **evaluate_intake**: structured-output LLM call that decides completeness.
2. **intake_chat**: single-pass model call for Q&A clarification (no ``task()``).
3. **approval_gate**: deterministic ``interrupt()`` — human-in-the-loop gate.
4. **execute**: full ``create_deep_agent`` with all subagents for the pipeline.

Subagents available to the execution agent:
- Data Engineer: For fetching and processing data
- Quantitative Developer: For code generation and execution
- Technical Writer: For report synthesis
- Quality Analyst: For final review
"""

import logging
import warnings
from pathlib import Path
import asyncio
import json
import os
import re
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, AsyncIterator, Dict

import google.genai.errors
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.types import interrupt

logger = logging.getLogger(__name__)

# Suppress langchain_google_genai schema-key warnings ($schema, additionalProperties
# are stripped when converting Pydantic tool schemas for the Gemini API — harmless)
logging.getLogger("langchain_google_genai._function_utils").setLevel(logging.ERROR)

# Suppress Pydantic serialization warning for ResearchContext passed as graph context.
warnings.filterwarnings(
    "ignore",
    message=r"Pydantic serializer warnings",
    category=UserWarning,
)

from mcp import ClientSession
from deepagents import create_deep_agent
from deepagents.backends import LocalShellBackend
from deepagents.backends.protocol import (
    EditResult,
    ExecuteResponse,
    GlobResult,
    GrepResult,
    LsResult,
    ReadResult,
    WriteResult,
)
from langgraph.checkpoint.memory import MemorySaver

from .data_engineer import FredMCPRequiredError, get_data_engineer_subagent, MCPTimeoutError
from .graph_input import resolve_graph_input
from .subagents_registry import GENERAL_PURPOSE_SUBAGENT, SPECIALIST_SUBAGENTS_STATIC
from .chat_surface_tool import emit_chat_message
from .intake import (
    intake_chat_node,
    evaluate_intake_node,
    emit_approval_message_node,
)
from core.context import ResearchContext

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_WORKSPACE_DIR = _BACKEND_DIR.parent
_CHECKPOINTER = MemorySaver()

_SAFE_SHELL_ENV = {
    "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
    "PYTHONPATH": str(_BACKEND_DIR),
}

_SENSITIVE_PATH_PARTS = {
    ".env",
    ".env.local",
    ".env.development",
    ".env.production",
    ".env.test",
    ".envrc",
    ".netrc",
    ".pypirc",
    ".npmrc",
    ".docker/config.json",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
}
_SENSITIVE_DIR_PARTS = {".ssh", ".gnupg", ".aws", ".azure", ".config/gcloud"}
_SECRET_SHELL_RE = re.compile(
    r"(?ix)"
    r"(^|[\s;&|()])("
    r"env|printenv|set|export"
    r")($|[\s;&|()])"
    r"|"
    r"(^|[/\s;&|()])("
    r"\.env(?:\.[\w-]+)?|\.envrc|\.netrc|\.pypirc|\.npmrc|"
    r"id_rsa|id_dsa|id_ecdsa|id_ed25519"
    r")($|[/\s;&|()])"
    r"|"
    r"(^|[/\s;&|()])("
    r"\.ssh|\.gnupg|\.aws|\.azure|\.config/gcloud"
    r")($|[/\s;&|()])"
)


def _tool_name(tool: Any) -> str | None:
    """Return a LangChain/OpenAI-style tool name without depending on one schema."""
    if isinstance(tool, dict):
        function = tool.get("function")
        if isinstance(function, dict) and isinstance(function.get("name"), str):
            return function["name"]
        name = tool.get("name")
        return name if isinstance(name, str) else None
    name = getattr(tool, "name", None)
    return name if isinstance(name, str) else None


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
        return self._strip_content(request, handler(request))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        if self._terminal_approval_chat_emitted(request):
            return self._empty_response()
        return self._strip_content(request, await handler(request))


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
        return super().execute(command, timeout=timeout)


# =============================================================================
# STATE SCHEMA
# =============================================================================

class OrchestratorState(dict):
    """Parent graph state for the deterministic orchestrator pipeline.

    Uses ``add_messages`` reducer so both subgraph agents and deterministic
    nodes can append messages without overwriting.
    """
    messages: Annotated[list[AnyMessage], add_messages]
    phase: str  # "intake" | "executing"
    research_summary: str


# Re-declare as a proper TypedDict for LangGraph (it needs __annotations__).
from typing import TypedDict  # noqa: E402

class OrchestratorState(TypedDict):  # type: ignore[no-redef]  # noqa: F811
    messages: Annotated[list[AnyMessage], add_messages]
    phase: str
    research_summary: str


# =============================================================================
# EXECUTION SYSTEM PROMPT (pipeline only — no intake instructions)
# =============================================================================

EXECUTION_SYSTEM_PROMPT = """
# ROLE
You are the **Orchestrator (Research Director)**. You coordinate end-to-end financial research by delegating to specialized subagents. You do not analyze raw data yourself.

# OVERRIDE
These execution rules override generic Deep Agent guidance that says to inspect files before acting. At this point intake and approval are complete; do not investigate the repository, skills, outputs, or prior artifacts before delegating.

# CORE RULES
1. **DATA DECOUPLING:** NEVER ingest or pass raw financial data arrays. Use only metadata, schemas, and file paths.
2. **RETRY LIMIT:** Maximum 3 retries per subagent. If a subagent fails 3 times, abort gracefully.
3. **MANDATORY UI:** Call `emit_chat_message(markdown=...)` exactly once per turn to speak to the user. Keep it to one short sentence.
4. **SPECIALISTS FOR THE PIPELINE:** Do not use `general-purpose` for the main data → quant → writer → QA pipeline. Reserve it for rare overflow tasks only.
5. **PATHS & ARTIFACTS:** Use absolute forward-slash paths. Copy the Job ID verbatim into output paths under `/home/vorndranj/projects/DeepResearchAgent/backend/outputs/{job_id}/`; never invent, shorten, or rename the folder. Do not demand exact data filenames or job-folder copies from data-engineer. If FRED returns `status:auto_saved`, the returned `file_path` (often under `backend/data/_auto/`) is already the canonical data path; pass it unchanged to quant-developer. Use quarterly labels like `YYYY Qn`, never `%Q`. Pass `data_sources` as metadata JSON only: provider, description, series_ids, date_range, row_count.
6. **HANDS OFF ARTIFACTS:** NEVER use `read_file`, `edit_file`, `write_file`, or `execute` on report.json or charts.json directly. Only the technical-writer and quant-developer should touch these files. If a report needs fixes, re-delegate to the appropriate subagent.
7. **SINGLE PASS:** After quality-analyst approves, the pipeline is DONE. Do not re-read or re-edit the report. Emit one final chat message and stop.
8. **NO ASSISTANT PROSE DURING EXECUTION:** When making tool calls, assistant message content must be empty. Do not stream narrative planning, assumptions, bullet lists, status prose, delivered-summary tables, or "I'll..." text. Tool calls are the work; `emit_chat_message` is the only user-visible status channel.
9. **START FAST:** On the first execution turn after approval, make exactly two tool calls and no assistant text: one brief `emit_chat_message` update and one `task(subagent_type="data-engineer", ...)` delegation. Put assumptions and indicator choices inside the data-engineer task description.
10. **NO STARTUP FILESYSTEM INSPECTION:** Before the first data-engineer result, do not call `ls`, `glob`, `grep`, `read_file`, `execute`, or `write_todos`. The job id, output path, data path, memory, and skills are already available; begin by delegating data collection.
11. **DIRECT HANDOFFS:** After receiving a subagent result, immediately delegate to the next subagent or emit the final chat message. The subagents are specialists — trust their output.
12. **TERMINAL APPROVAL RESPONSE:** When `quality-analyst` returns approved, call `emit_chat_message` with only `Report approved: outputs/{job_id}/report.json`. Do not add any assistant content after that tool call. Do not summarize deliverables, list component statuses, mention validation details, or produce a markdown table.
13. **COMPACT QUANT HANDOFF:** If `quant-developer` returns `execution_summary_json`, pass that absolute path to `technical-writer` and tell it to use the file's contents as `execution_summary`. Do not ask `quant-developer` to restate or expand the full statistical summary inline.
14. **TECHNICAL-WRITER TOOL CONTRACT:** The technical-writer task description must explicitly say: call `plan_report_structure` first with `charts_json_path`, `execution_summary`, and `original_query`; then call `write_research_report`; then call `validate_research_report_file`; never call `read_file`, `ls`, `glob`, `grep`, `execute`, or `write_file`. If `plan_report_structure` returns truncated-looking text, use `execution_summary_for_draft` as-is and continue; do not try to recover by reading files.
15. **DATA → QUANT HANDOFF:** The quant-developer task description must include a compact JSON `data_files` map from series ID or metric name to absolute CSV path, plus `schema_summary` and row counts from data-engineer. Tell quant-developer to use those exact paths and not call `glob`, `ls`, or `read_file` to rediscover them.
16. **REAL WAGE SOURCE FIDELITY:** For labor-market questions asking about real wages, real average hourly earnings, or inflation-adjusted earnings, tell data-engineer to verify that any FRED earnings series title/units explicitly says real or inflation-adjusted. If only nominal earnings are available, require a FRED price index such as CPIAUCSL and tell quant-developer to construct the real earnings measure before analyzing wage gains. Never let a nominal average-hourly-earnings series stand in for "real" wages.

# EXECUTION ORDER
1. **data-engineer** → 2. **quant-developer** → 3. **technical-writer** → 4. **quality-analyst** → confirm `report.json` is saved and approved.

# TASK TOOL
Delegate with `task(subagent_type="...", description="...")`. The `subagent_type` MUST be one of:
`data-engineer`, `quant-developer`, `technical-writer`, `quality-analyst`.

Each `description` must be self-contained (context, absolute paths, expected outputs). Treat each `task()` as stateless.

# TONE
Professional, analytical, and authoritative. Expose your current pipeline state only through brief `emit_chat_message` updates.
"""


# =============================================================================
# DETERMINISTIC NODE FUNCTIONS
# =============================================================================


def approval_gate_node(state: dict) -> dict:
    """Deterministic interrupt — pauses graph for user approval.

    On resume with ``"approved"`` → sets phase to executing.
    On resume with any other string → loops back to intake with feedback.
    """
    result = interrupt(
        {
            "type": "research_approval_needed",
            "summary": state.get("research_summary", ""),
            "approval_action": "commence_research",
        }
    )
    if result == "approved":
        return {"phase": "executing"}
    # User sent feedback instead of approving — loop back to intake.
    return {
        "phase": "intake",
        "research_summary": "",
        "messages": [HumanMessage(content=str(result))],
    }


# =============================================================================
# CONDITIONAL EDGE FUNCTIONS
# =============================================================================


def route_by_phase(state: dict) -> str:
    """Entry router: send to intake or execution based on current phase."""
    return state.get("phase") or "intake"


def route_after_evaluate(state: dict) -> str:
    """After evaluate_intake: complete if summary was set, else wait."""
    if state.get("research_summary"):
        return "complete"
    return "needs_more"


def route_after_approval(state: dict) -> str:
    """After approval_gate: execute or loop back to intake (feedback)."""
    if state.get("phase") == "executing":
        return "executing"
    return "intake"


def _fred_setup_error_payload(error: FredMCPRequiredError) -> dict[str, Any]:
    """Build a compact, actionable setup error for required FRED failures."""
    message = str(error)
    lowered = message.lower()
    retryable = False
    if "fetch failed" in lowered or "network" in lowered or "timeout" in lowered:
        retryable = True
        hint = (
            "FRED MCP loaded, but its outbound FRED API request failed. "
            "Check network/DNS/proxy access from the backend environment and retry after access is restored; "
            "do not re-enable FMP for this FRED-only flow."
        )
    elif "api_key" in lowered or "api key" in lowered or "unauthorized" in lowered:
        hint = (
            "FRED is required for this research flow. Verify the FRED_API_KEY value "
            "available to the FRED MCP subprocess before retrying."
        )
    else:
        hint = (
            "FRED is required for this research flow. Verify FRED_MCP_SERVER_PATH, "
            "FRED_API_KEY, and backend network access before retrying."
        )

    return {
        "type": "fred_mcp_required",
        "message": message,
        "phase": "setup",
        "retryable": retryable,
        "agent_recoverable": False,
        "hint": hint,
    }


# =============================================================================
# AGENT FACTORIES
# =============================================================================


async def _create_execution_agent(fred_session: ClientSession | None = None):
    """Full deep agent for the pipeline execution phase.

    Has all subagents (data-engineer, quant-developer, technical-writer,
    quality-analyst) and the ``task()`` tool. No intake / approval tools.
    ``interrupt_on`` is intentionally unset so subagents do not inherit
    interrupt behavior that would pause file/shell work.
    """
    data_engineer = await get_data_engineer_subagent(fred_session=fred_session)

    return create_deep_agent(
        model="deepseek:deepseek-chat",
        system_prompt=EXECUTION_SYSTEM_PROMPT,
        tools=[emit_chat_message],
        middleware=[_HIDE_TODO_TOOL_MIDDLEWARE, _STRIP_TOOL_CALL_CONTENT_MIDDLEWARE],
        subagents=[
            _with_hidden_todo_tool(GENERAL_PURPOSE_SUBAGENT),
            _with_hidden_todo_tool(data_engineer),
            *[_with_hidden_todo_tool(subagent) for subagent in SPECIALIST_SUBAGENTS_STATIC],
        ],
        backend=GuardedLocalShellBackend(
            root_dir=_WORKSPACE_DIR,
            virtual_mode=False,
            env=_SAFE_SHELL_ENV,
            inherit_env=False,
        ),
        context_schema=ResearchContext,
        # No checkpointer — parent graph owns the checkpoint.
        memory=[str(_BACKEND_DIR / "AGENTS.md")],
        name="orchestrator",
    )


# =============================================================================
# CREATE ORCHESTRATOR (parent StateGraph)
# =============================================================================


async def create_orchestrator(fred_session: ClientSession | None = None):
    """Build the deterministic orchestrator pipeline.

    Returns a compiled ``StateGraph`` with nodes:
    evaluate_intake → emit_approval_message → approval_gate → execute
                    ↘ intake_chat → END when clarification is needed

    Complete requests skip ``intake_chat`` so explicit prompts do not burn
    message budget on streamed clarification text before approval, but still
    emit the deterministic approval prompt the frontend uses for the
    "Commence Deep Research" affordance.

    **FRED MCP is required** for the data-engineer subagent used in the
    execution phase.
    """
    execution_agent = await _create_execution_agent(fred_session=fred_session)

    graph = StateGraph(OrchestratorState, context_schema=ResearchContext)

    # --- nodes ---
    graph.add_node("intake_chat", intake_chat_node)
    graph.add_node("evaluate_intake", evaluate_intake_node)
    graph.add_node("emit_approval_message", emit_approval_message_node)
    graph.add_node("approval_gate", approval_gate_node)
    graph.add_node("execute", execution_agent)

    # --- edges ---
    graph.add_conditional_edges(START, route_by_phase, {
        "intake": "evaluate_intake",
        "executing": "execute",
    })
    graph.add_conditional_edges("evaluate_intake", route_after_evaluate, {
        "needs_more": "intake_chat",
        "complete": "emit_approval_message",
    })
    graph.add_edge("intake_chat", END)
    graph.add_edge("emit_approval_message", "approval_gate")
    graph.add_conditional_edges("approval_gate", route_after_approval, {
        "executing": "execute",
        "intake": "evaluate_intake",
    })
    graph.add_edge("execute", END)

    return graph.compile(
        checkpointer=_CHECKPOINTER,
    ).with_config(
        {
            "recursion_limit": 9_999,
            "metadata": {"lc_agent_name": "orchestrator"},
        }
    )


# =============================================================================
# PUBLIC API FUNCTIONS
# =============================================================================


async def run_research(
    query: str,
    job_id: str,
    messages: list[dict] | None = None,
    agent: Any | None = None,
    user_id: str | None = None,
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
            user_id=user_id,
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

    except FredMCPRequiredError as e:
        error = _fred_setup_error_payload(e)
        return {
            "status": "failed",
            "job_id": job_id,
            "error": error["message"],
            "error_type": error["type"],
            "phase": error["phase"],
            "retryable": error["retryable"],
            "agent_recoverable": error["agent_recoverable"],
            "hint": error["hint"],
        }
    except MCPTimeoutError as e:
        return {"status": "failed", "job_id": job_id, "error": f"MCP timeout: {e}"}
    except Exception as e:
        return {"status": "failed", "job_id": job_id, "error": str(e)}


async def stream_research(
    query: str,
    job_id: str,
    messages: list[dict] | None = None,
    agent: Any | None = None,
    user_id: str | None = None,
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
    try:
        if agent is None:
            agent = await create_orchestrator()

        if messages is None:
            messages = [{"role": "user", "content": f"Job ID: {job_id}\n\nResearch Query: {query}"}]

        ctx = ResearchContext(
            job_id=job_id,
            output_dir=str(_BACKEND_DIR / "outputs" / job_id),
            data_dir=str(_BACKEND_DIR / "data" / job_id),
            user_id=user_id,
        )

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
    except FredMCPRequiredError as e:
        yield {"error": _fred_setup_error_payload(e)}
    except MCPTimeoutError as e:
        yield {"error": {"type": "mcp_timeout", "message": str(e)}}


__all__ = ["FredMCPRequiredError", "create_orchestrator", "run_research", "stream_research"]

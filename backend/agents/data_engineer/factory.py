"""Build the data-engineer subagent with FRED MCP tools."""
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableLambda
from langgraph.prebuilt.tool_node import ToolCallRequest
from mcp import ClientSession

from mcp_clients.fred_mcp_client import create_fred_mcp_client, load_fred_tools_with_session

from .mcp_wrappers import (
    _FRED_TIMEOUT,
    _run_mcp_request,
    _with_timeout,
)
from .prompts import build_system_prompt
from .tools import extract_schema, save_data

logger = logging.getLogger(__name__)

_FRED_PROBE_SERIES_IDS = ("GDP", "UNRATE")
_BLOCKED_DEEP_AGENT_TOOL_NAMES = {
    "execute",
    "read_file",
    "write_file",
    "edit_file",
    "ls",
    "glob",
    "grep",
    "write_todos",
}


class FredMCPRequiredError(RuntimeError):
    """Raised when FRED MCP tools cannot be loaded or probed (FRED is required for this agent)."""


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


def _tool_call_name(tool_call: Any) -> str | None:
    if isinstance(tool_call, dict):
        name = tool_call.get("name")
        return name if isinstance(name, str) else None
    name = getattr(tool_call, "name", None)
    return name if isinstance(name, str) else None


def _tool_call_id(tool_call: Any) -> str:
    if isinstance(tool_call, dict):
        value = tool_call.get("id") or tool_call.get("tool_call_id")
        return str(value or "data-engineer-blocked-tool")
    return str(
        getattr(tool_call, "id", None)
        or getattr(tool_call, "tool_call_id", None)
        or "data-engineer-blocked-tool"
    )


class DataEngineerToolBoundaryMiddleware(AgentMiddleware):
    """Hide and block generic filesystem/shell tools from the data-engineer subagent."""

    def _without_blocked_tools(self, request: ModelRequest) -> ModelRequest:
        tools = [
            tool
            for tool in request.tools
            if _tool_name(tool) not in _BLOCKED_DEEP_AGENT_TOOL_NAMES
        ]
        if len(tools) == len(request.tools):
            return request
        return request.override(tools=tools)

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        return handler(self._without_blocked_tools(request))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        return await handler(self._without_blocked_tools(request))

    def _blocked_tool_message(self, request: ToolCallRequest) -> ToolMessage:
        tool_name = _tool_call_name(request.tool_call) or "unknown_tool"
        return ToolMessage(
            content=(
                f"Blocked tool `{tool_name}` for data-engineer. "
                "Use only FRED MCP tools, save_data, and extract_schema. "
                "FRED auto-saved file_path values are already persisted; return those "
                "paths directly instead of copying, reading, or rewriting CSV files."
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
        if tool_name in _BLOCKED_DEEP_AGENT_TOOL_NAMES:
            return self._blocked_tool_message(request)
        return handler(request)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage]],
    ) -> ToolMessage:
        tool_name = _tool_call_name(request.tool_call)
        if tool_name in _BLOCKED_DEEP_AGENT_TOOL_NAMES:
            return self._blocked_tool_message(request)
        return await handler(request)


_DATA_ENGINEER_TOOL_BOUNDARY_MIDDLEWARE = DataEngineerToolBoundaryMiddleware()


def _build_data_engineer_runnable(fred_tools: list[Any]) -> RunnableLambda:
    """Build a non-Deep-Agents runnable so data-engineer gets no filesystem tools."""
    agent = create_agent(
        "deepseek:deepseek-chat",
        system_prompt=build_system_prompt(),
        tools=[save_data, extract_schema] + fred_tools,
        middleware=[_DATA_ENGINEER_TOOL_BOUNDARY_MIDDLEWARE],
        name="data-engineer",
    )
    return RunnableLambda(
        agent.invoke,
        afunc=agent.ainvoke,
        name="data-engineer",
    )


async def _probe_required_fred_tool(probe_tool) -> None:
    """Verify outbound FRED access without making one transient series failure fatal."""
    probe_errors: list[str] = []
    for series_id in _FRED_PROBE_SERIES_IDS:
        try:
            await _run_mcp_request(
                provider="FRED",
                operation=f"fred_get_series({series_id})",
                timeout_secs=_FRED_TIMEOUT,
                request_factory=lambda series_id=series_id: probe_tool.ainvoke(
                    {"series_id": series_id}
                ),
            )
            if series_id != _FRED_PROBE_SERIES_IDS[0]:
                logger.warning(
                    "FRED MCP health probe succeeded with fallback series %s after earlier failure(s): %s",
                    series_id,
                    " | ".join(probe_errors),
                )
            return
        except Exception as e:
            probe_errors.append(f"{series_id}: {e}")

    raise FredMCPRequiredError(
        "FRED MCP is required but health probes failed (check FRED_API_KEY and network). "
        "Probe errors: " + " | ".join(probe_errors)
    )


async def get_data_engineer_subagent(fred_session: ClientSession | None = None):
    """
    Create and return the data engineer subagent config with **FRED** MCP tools.

    **FRED is required:** loading tools or the GDP probe must succeed or this function raises
    ``FredMCPRequiredError``.

    When ``fred_session`` is provided (e.g. from ``async with client.session("fred")`` in app
    lifespan), FRED tools share one MCP stdio subprocess. Without it, langchain-mcp-adapters
    creates a new session per tool call (CLI/tests only — still requires a working FRED server).

    Returns:
        Dictionary with full agent configuration
    """
    # FRED (required — same stdio server as app lifespan when fred_session is set)
    try:
        if fred_session is not None:
            fred_tools = await _run_mcp_request(
                provider="FRED",
                operation="load_tools(session)",
                timeout_secs=_FRED_TIMEOUT,
                request_factory=lambda: load_fred_tools_with_session(fred_session),
            )
        else:
            fred_client = await create_fred_mcp_client()
            fred_tools = await _run_mcp_request(
                provider="FRED",
                operation="get_tools",
                timeout_secs=_FRED_TIMEOUT,
                request_factory=fred_client.get_tools,
            )
    except Exception as e:
        raise FredMCPRequiredError(
            "FRED MCP is required but tools could not be loaded. "
            "Set FRED_API_KEY and FRED_MCP_SERVER_PATH (Node fred-mcp-server build). "
            f"Original error: {e}"
        ) from e

    if not fred_tools:
        raise FredMCPRequiredError(
            "FRED MCP returned no tools (required). Check FRED_MCP_SERVER_PATH and server build."
        )

    probe_tool = next((t for t in fred_tools if getattr(t, "name", "") == "fred_get_series"), None)
    if probe_tool is None:
        raise FredMCPRequiredError(
            "FRED MCP tools are missing required tool `fred_get_series`. Reinstall/update fred-mcp-server."
        )

    await _probe_required_fred_tool(probe_tool)

    fred_tools = [_with_timeout(t, _FRED_TIMEOUT, "FRED") for t in fred_tools]

    description = """Use this subagent to fetch macroeconomic data from FRED, or extract schemas from saved data files.

    Delegate when you need to:
    - Fetch macroeconomic series from FRED (GDP, CPI, interest rates, employment, etc.)
    - Save fetched data to storage
    - Extract exact schemas (column names, dtypes, sample rows) from data files

    Note: FMP tools are intentionally disabled until a paid FMP plan is available. This agent
    returns only storage paths and compact metadata, never raw data."""

    return {
        "name": "data-engineer",
        "description": description,
        # Use a compiled agent instead of a declarative Deep Agents subagent.
        # Declarative subagents inherit Deep Agents filesystem/shell tooling by
        # default; data-engineer must be limited to FRED, save_data, and schema
        # extraction so it cannot drift into setup or CSV rewrite shell calls.
        "runnable": _build_data_engineer_runnable(fred_tools),
    }

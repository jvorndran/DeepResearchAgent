"""Build the data-engineer subagent with FRED MCP tools."""

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import SystemMessage, ToolMessage
from langchain_core.runnables import RunnableLambda
from langgraph.prebuilt.tool_node import ToolCallRequest
from mcp import ClientSession

from ..data_toolbox import (
    DATA_TOOLBOX_PREFERENCE_KEY,
    PROVIDER_LABELS,
    PROVIDER_ORDER,
    normalize_data_toolbox,
)
from core.context import ResearchContext
from mcp_clients.fred_mcp_client import create_fred_mcp_client, load_fred_tools_with_session

from ..tool_utils import tool_call_id, tool_call_name, tool_name
from .mcp_wrappers import (
    _FRED_TIMEOUT,
    _run_mcp_request,
    _with_timeout,
)
from .prompts import DATA_ENGINEER_CORE_PROMPT, build_system_prompt
from .tools import (
    bls_get_series,
    bls_search_known_series,
    census_get_table,
    extract_schema,
    save_data,
    sec_fetch_company_facts,
    worldbank_get_indicator,
)

logger = logging.getLogger(__name__)

# Probe a small cross-section of high-traffic endpoints so one stale FRED
# series failure does not block unrelated macro/chart runs during setup.
_FRED_PROBE_SERIES_IDS = (
    "GDP",
    "UNRATE",
    "CPIAUCSL",
    "CPILFESL",
    "FEDFUNDS",
    "USREC",
)
_FRED_PROBE_OBSERVATION_LIMIT = 1
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
_HELPER_TOOL_NAMES = {"save_data", "extract_schema"}
_PROVIDER_TOOL_NAMES = {
    "fred": {"fred_search", "fred_browse", "fred_get_series"},
    "bls": {"bls_search_known_series", "bls_get_series"},
    "census": {"census_get_table"},
    "worldbank": {"worldbank_get_indicator"},
    "sec": {"sec_fetch_company_facts"},
}
_ALL_PROVIDER_TOOL_NAMES = {
    tool_name for provider_tools in _PROVIDER_TOOL_NAMES.values() for tool_name in provider_tools
}


class FredMCPRequiredError(RuntimeError):
    """Raised when FRED MCP tools cannot be loaded or probed (FRED is required for this agent)."""


def _tool_name(tool: Any) -> str | None:
    return tool_name(tool)


def _tool_call_name(tool_call: Any) -> str | None:
    return tool_call_name(tool_call)


def _tool_call_id(tool_call: Any) -> str:
    return tool_call_id(tool_call, "data-engineer-blocked-tool")


class DataEngineerToolBoundaryMiddleware(AgentMiddleware):
    """Hide blocked tools and provider tools not selected for this run."""

    def _selected_providers(self, request: Any) -> list[str]:
        runtime = getattr(request, "runtime", None)
        context = getattr(runtime, "context", None)
        preferences = getattr(context, "preferences", None)
        if not isinstance(preferences, dict):
            return list(PROVIDER_ORDER)
        toolbox = normalize_data_toolbox(
            preferences.get(DATA_TOOLBOX_PREFERENCE_KEY),
            broad_if_missing=False,
        )
        if toolbox is None:
            return list(PROVIDER_ORDER)
        return list(toolbox.get("providers") or PROVIDER_ORDER)

    def _allowed_tool_names_for_providers(self, selected_providers: list[str]) -> set[str]:
        allowed = set(_HELPER_TOOL_NAMES)
        for provider in selected_providers:
            allowed.update(_PROVIDER_TOOL_NAMES.get(provider, set()))
        return allowed

    def _allowed_tool_names(self, request: Any) -> set[str]:
        return self._allowed_tool_names_for_providers(self._selected_providers(request))

    def _with_runtime_prompt_and_tools(self, request: ModelRequest) -> ModelRequest:
        selected_providers = self._selected_providers(request)
        allowed_tools = self._allowed_tool_names_for_providers(selected_providers)
        tools = [
            tool
            for tool in request.tools
            if _tool_name(tool) not in _BLOCKED_DEEP_AGENT_TOOL_NAMES
            and _tool_name(tool) in allowed_tools
        ]
        return request.override(
            tools=tools,
            system_message=SystemMessage(content=build_system_prompt(selected_providers)),
        )

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        return handler(self._with_runtime_prompt_and_tools(request))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        return await handler(self._with_runtime_prompt_and_tools(request))

    def _blocked_tool_message(self, request: ToolCallRequest) -> ToolMessage:
        tool_name = _tool_call_name(request.tool_call) or "unknown_tool"
        return ToolMessage(
            content=(
                f"Blocked tool `{tool_name}` for data-engineer. "
                "Use only FRED MCP tools, BLS public data, Census public data, "
                "World Bank annual indicators, SEC EDGAR company facts, save_data, "
                "and extract_schema. "
                "FRED auto-saved file_path values are already persisted; return those "
                "paths directly instead of copying, reading, or rewriting CSV files."
            ),
            name=tool_name,
            tool_call_id=_tool_call_id(request.tool_call),
            status="error",
        )

    def _hidden_provider_tool_message(self, request: ToolCallRequest) -> ToolMessage:
        tool_name = _tool_call_name(request.tool_call) or "unknown_tool"
        selected = self._selected_providers(request)
        selected_labels = ", ".join(
            f"{PROVIDER_LABELS.get(provider, provider)} (`{provider}`)" for provider in selected
        )
        return ToolMessage(
            content=(
                f"Blocked tool `{tool_name}` for data-engineer because its provider "
                "was not selected for this approved query. "
                f"Selected data providers: {selected_labels}. "
                "Use only the selected provider tools plus save_data and extract_schema. "
                "If the research scope now requires this provider, ask the orchestrator "
                "to reroute the toolbox before calling it."
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
        if tool_name in _ALL_PROVIDER_TOOL_NAMES and tool_name not in self._allowed_tool_names(
            request
        ):
            return self._hidden_provider_tool_message(request)
        return handler(request)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage]],
    ) -> ToolMessage:
        tool_name = _tool_call_name(request.tool_call)
        if tool_name in _BLOCKED_DEEP_AGENT_TOOL_NAMES:
            return self._blocked_tool_message(request)
        if tool_name in _ALL_PROVIDER_TOOL_NAMES and tool_name not in self._allowed_tool_names(
            request
        ):
            return self._hidden_provider_tool_message(request)
        return await handler(request)


_DATA_ENGINEER_TOOL_BOUNDARY_MIDDLEWARE = DataEngineerToolBoundaryMiddleware()


def _build_data_engineer_runnable(fred_tools: list[Any]) -> RunnableLambda:
    """Build a non-Deep-Agents runnable so data-engineer gets no filesystem tools."""
    agent = create_agent(
        "deepseek:deepseek-chat",
        system_prompt=DATA_ENGINEER_CORE_PROMPT,
        tools=[
            save_data,
            extract_schema,
            bls_search_known_series,
            bls_get_series,
            census_get_table,
            worldbank_get_indicator,
            sec_fetch_company_facts,
        ]
        + fred_tools,
        middleware=[_DATA_ENGINEER_TOOL_BOUNDARY_MIDDLEWARE],
        context_schema=ResearchContext,
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
            probe_payload = {
                "series_id": series_id,
                "limit": _FRED_PROBE_OBSERVATION_LIMIT,
                "sort_order": "desc",
            }
            await _run_mcp_request(
                provider="FRED",
                operation=f"fred_get_series({series_id})",
                timeout_secs=_FRED_TIMEOUT,
                request_factory=lambda probe_payload=probe_payload: probe_tool.ainvoke(
                    probe_payload
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

    description = """Use this subagent to fetch macroeconomic data from FRED/BLS, World Bank annual indicators, Census regional context, SEC company fundamentals, or extract schemas from saved data files.

    Delegate when you need to:
    - Fetch macroeconomic series from FRED (GDP, CPI, interest rates, employment, etc.)
    - Fetch direct BLS public labor, wage, CPI/PPI, employment, or productivity series for source reconciliation
    - Fetch World Bank annual inflation or GDP-growth indicators for USA/CAN/DEU/JPN/MEX cross-country context
    - Fetch Census state/county population, income, or housing context
    - Fetch public-company SEC EDGAR facts (revenue, net income, margin, cash-flow, balance-sheet, shares, filing metadata) for a ticker or CIK
    - Save fetched data to storage
    - Extract exact schemas (column names, dtypes, sample rows) from data files

    Note: FMP tools are intentionally disabled until a paid FMP plan is available. This agent
    returns only storage paths or compact no-key FRED/BLS/World Bank/Census/SEC metadata, never bulky raw data."""

    return {
        "name": "data-engineer",
        "description": description,
        # Use a compiled agent instead of a declarative Deep Agents subagent.
        # Declarative subagents inherit Deep Agents filesystem/shell tooling by
        # default; data-engineer must be limited to FRED, save_data, and schema
        # extraction/public-data helpers so it cannot drift into setup or CSV
        # rewrite shell calls.
        "runnable": _build_data_engineer_runnable(fred_tools),
    }

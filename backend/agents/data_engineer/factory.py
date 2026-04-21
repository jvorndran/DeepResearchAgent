"""Build the data-engineer subagent with FMP/FRED MCP tools."""
import logging

from mcp import ClientSession

from mcp_clients.fmp_mcp_client import create_fmp_mcp_client
from mcp_clients.fred_mcp_client import create_fred_mcp_client, load_fred_tools_with_session

from .mcp_wrappers import (
    _FMP_TIMEOUT,
    _FRED_TIMEOUT,
    _run_mcp_request,
    _with_timeout,
)
from .paths import BACKEND_DIR
from .prompts import build_system_prompt
from .tools import extract_schema, save_data

logger = logging.getLogger(__name__)


class FredMCPRequiredError(RuntimeError):
    """Raised when FRED MCP tools cannot be loaded or probed (FRED is required for this agent)."""


async def get_data_engineer_subagent(fred_session: ClientSession | None = None):
    """
    Create and return the data engineer subagent config with FMP and **FRED** MCP tools.

    **FRED is required:** loading tools or the GDP probe must succeed or this function raises
    ``FredMCPRequiredError``.

    When ``fred_session`` is provided (e.g. from ``async with client.session("fred")`` in app
    lifespan), FRED tools share one MCP stdio subprocess. Without it, langchain-mcp-adapters
    creates a new session per tool call (CLI/tests only — still requires a working FRED server).

    Returns:
        Dictionary with full agent configuration
    """
    # FMP (required, hosted)
    fmp_client = await create_fmp_mcp_client()
    fmp_tools = await _run_mcp_request(
        provider="FMP",
        operation="get_tools",
        timeout_secs=_FMP_TIMEOUT,
        request_factory=fmp_client.get_tools,
    )

    enable_tool = next((t for t in fmp_tools if getattr(t, "name", "") == "enable_toolset"), None)
    if enable_tool:
        try:
            await _run_mcp_request(
                provider="FMP",
                operation="enable_toolset(statements)",
                timeout_secs=_FMP_TIMEOUT,
                request_factory=lambda: enable_tool.ainvoke({"name": "statements"}),
            )
        except Exception as _e:
            logger.warning("Failed to pre-enable FMP 'statements' toolset: %s", _e)
    fmp_tools = await _run_mcp_request(
        provider="FMP",
        operation="get_tools",
        timeout_secs=_FMP_TIMEOUT,
        request_factory=fmp_client.get_tools,
    )

    fmp_tools = [_with_timeout(t, _FMP_TIMEOUT, "FMP") for t in fmp_tools]

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

    try:
        await _run_mcp_request(
            provider="FRED",
            operation="fred_get_series(GDP)",
            timeout_secs=_FRED_TIMEOUT,
            request_factory=lambda: probe_tool.ainvoke({"series_id": "GDP"}),
        )
    except Exception as e:
        raise FredMCPRequiredError(
            "FRED MCP is required but the GDP probe failed (check FRED_API_KEY and network). "
            f"Original error: {e}"
        ) from e

    fred_tools = [_with_timeout(t, _FRED_TIMEOUT, "FRED") for t in fred_tools]

    description = """Use this subagent to fetch financial or macroeconomic data, or extract schemas from saved data files.

    Delegate when you need to:
    - Fetch stock data from Financial Modeling Prep (FMP) via MCP Server (250+ tools across 24 categories)
    - Get real-time quotes, historical prices, financial statements, market data
    - Access technical indicators, insider trading data, SEC filings, news, and more
    - Fetch macroeconomic series from FRED (GDP, CPI, interest rates, employment, etc.)
    - Save fetched data to storage
    - Extract exact schemas (column names, dtypes, sample rows) from data files

    Note: FMP uses dynamic toolset loading — the agent will call enable_toolset() before using
    financial tools. It returns only storage paths and compact metadata, never raw data."""

    return {
        "name": "data-engineer",
        "description": description,
        "system_prompt": build_system_prompt(),
        "tools": [save_data, extract_schema] + fmp_tools + fred_tools,
        "model": "deepseek:deepseek-chat",
        "skills": [str(BACKEND_DIR / "skills" / "data-engineer")],
    }

"""
Data Engineer Subagent (Deep Agents)

The Data Engineer is responsible for all data operations: fetching financial
data from APIs and extracting schemas.

Role: Data Engineer / Data Analyst
Model: Gemini 3.0 Flash Preview (good at API reasoning and data manipulation)

Responsibilities:
- Fetch data from financial APIs via FMP MCP Server (250+ tools available)
- Save raw data to storage (GCS or local)
- Extract exact schemas from saved data (deterministic, no hallucinations)
- Return only storage paths and metadata (NOT raw data)

Key Principle: NEVER pass raw data back to the Orchestrator.
Only return storage paths and compact metadata to prevent context window bloat.

Integration: Uses the Financial Modeling Prep (FMP) MCP Server for all data fetching.
The MCP server provides tools for stock quotes, financial statements, market data,
technical indicators, and much more.
"""

from typing import Dict, Any, List, Optional, Union
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig
from langchain_core.callbacks import AsyncCallbackManagerForToolRun
from langchain.tools import ToolRuntime
import pandas as pd
import os
import json
import asyncio
from pathlib import Path
from mcp_clients.fmp_mcp_client import create_fmp_mcp_client, get_fmp_mcp_config, list_fmp_tools as list_fmp_tools_async
from mcp_clients.fred_mcp_client import create_fred_mcp_client
from core.context import ResearchContext


# =============================================================================
# MCP TIMEOUT HANDLING
# =============================================================================

# Inherits from BaseException (not Exception) so LangGraph's ToolNode — which
# catches `except Exception` — cannot swallow it.  The exception propagates
# straight through the subagent graph and out of stream_research / run_research,
# where it is caught and turned into a clean error response.
class MCPTimeoutError(BaseException):
    """Raised when an FMP or FRED MCP tool call exceeds its timeout."""

_FMP_TIMEOUT = 30   # seconds per tool call (FMP is a hosted remote API)
_FRED_TIMEOUT = 30  # seconds per tool call (FRED local server)


# FMP statement tools that accept a `period` parameter.
# The API only accepts these exact values — reject anything else at the call site
# so the LLM sees the error immediately and retries with the correct value.
_VALID_FMP_PERIODS = {"FY", "Q1", "Q2", "Q3", "Q4"}
_PERIOD_ALIASES = {
    "annual": "FY",
    "yearly": "FY",
    "fy": "FY",
    "quarter": "Q1",   # best-effort: map generic "quarter" to Q1 so the call succeeds
    "quarterly": "Q1",
    "q1": "Q1", "q2": "Q2", "q3": "Q3", "q4": "Q4",
}
_STATEMENT_TOOLS = {
    "getIncomeStatement", "getBalanceSheetStatement",
    "getCashFlowStatement", "getKeyMetrics", "getRatios",
    # AsReported variants also accept a period param (though they need premium tier)
    "getIncomeStatementAsReported", "getBalanceSheetStatementAsReported",
    "getCashFlowStatementAsReported",
}

import logging as _logging
import re as _re
import time as _time

_de_logger = _logging.getLogger(__name__)

_MCP_INLINE_LIMIT = 800  # chars — MCP results longer than this go to a temp file


def _sanitize_nan(result: str) -> str:
    """Replace bare NaN/Infinity tokens so Gemini accepts the JSON payload."""
    result = _re.sub(r'\bNaN\b', 'null', result)
    result = _re.sub(r'\bInfinity\b', 'null', result)
    result = _re.sub(r'\b-Infinity\b', 'null', result)
    return result


async def _auto_save_result(result: str, tool_name: str) -> str:
    """
    Prevent large MCP tool results from entering the LLM message history.

    Two-stage interception:
    1. Structured data arrays (FRED/FMP time-series): saved to a job-scoped CSV via
       _save_data_to_storage so save_data can pick it up later.
    2. Any other result exceeding _MCP_INLINE_LIMIT chars: written verbatim to a raw
       JSON file under DATA_STORAGE_DIR/_mcp_raw/; the LLM only sees a small preview
       dict with the file path and the first 400 chars.
    """
    if not isinstance(result, str):
        return result

    try:
        data = json.loads(result)
    except Exception:
        # Not valid JSON — apply size limit to raw string too
        data = None

    if data is not None:
        is_data_array = isinstance(data, list) and len(data) > 0
        is_data_dict = (
            isinstance(data, dict)
            and "data" in data
            and isinstance(data["data"], list)
            and len(data["data"]) > 0
        )

        if is_data_array or is_data_dict:
            try:
                timestamp = int(_time.time())
                file_path = DATA_STORAGE_DIR / "_auto" / f"{tool_name}_{timestamp}.csv"
                meta = _run_async(_save_data_to_storage(data, file_path))
                saved_path = meta["storage_path"]
                pointer = {
                    "status": "auto_saved",
                    "file_path": saved_path,
                    "row_count": meta["row_count"],
                    "columns": meta["columns"],
                    "note": "Raw data auto-saved. Pass this entire JSON to save_data.",
                }
                return json.dumps(pointer)
            except Exception as e:
                _de_logger.warning("Auto-save failed for tool '%s': %s", tool_name, e)
                # Fall through to the size-limit check below

    # Fallback: any result still longer than the inline limit goes to a raw file.
    if len(result) > _MCP_INLINE_LIMIT:
        try:
            timestamp = int(_time.time())
            raw_dir = DATA_STORAGE_DIR / "_mcp_raw"
            raw_dir.mkdir(parents=True, exist_ok=True)
            raw_path = raw_dir / f"{tool_name}_{timestamp}.json"
            raw_path.write_text(result, encoding="utf-8")
            rel = raw_path.relative_to(Path.cwd()).as_posix()
            preview = {
                "file_path": rel,
                "preview": result[:400],
                "byte_size": len(result.encode()),
                "note": "Full MCP response saved to file. Read it only if you need specific fields.",
            }
            return json.dumps(preview)
        except Exception as e:
            _de_logger.warning("MCP raw save failed for tool '%s': %s", tool_name, e)

    return result


def _with_timeout(mcp_tool, timeout_secs: float):
    """
    Wrap an MCP BaseTool so any call exceeding *timeout_secs* raises
    MCPTimeoutError instead of hanging indefinitely.

    Also normalises the `period` kwarg for FMP statement tools — the FMP MCP
    server only accepts "FY"|"Q1"|"Q2"|"Q3"|"Q4"; the LLM sometimes passes
    "annual" or "quarter" which causes a -32602 validation error.

    MCPTimeoutError(BaseException) bypasses LangGraph's ToolNode error
    handler and aborts the entire agent workflow immediately.
    """
    original_arun = mcp_tool._arun
    tool_name = getattr(mcp_tool, "name", "")

    async def _arun_with_timeout(
        *args,
        config: RunnableConfig,
        run_manager: AsyncCallbackManagerForToolRun | None = None,
        **kwargs,
    ):
        # Normalise period param for statement tools before hitting the API.
        # The period may arrive in three different locations depending on how
        # LangChain/LangGraph invokes the tool:
        #   - kwargs['period']          direct keyword arg
        #   - kwargs['input']['period'] dict packed under 'input' kwarg
        #   - args[0]['period']         dict passed as first positional arg
        if tool_name in _STATEMENT_TOOLS:
            def _fix(d: dict) -> tuple[dict, bool]:
                raw = str(d.get("period", ""))
                if raw and raw not in _VALID_FMP_PERIODS:
                    corrected = _PERIOD_ALIASES.get(raw.lower(), "FY")
                    _de_logger.warning(
                        "FMP tool '%s': invalid period=%r — correcting to %r",
                        tool_name, raw, corrected,
                    )
                    return {**d, "period": corrected}, True
                return d, False

            if "period" in kwargs:
                kwargs, _ = _fix(kwargs)
            elif isinstance(kwargs.get("input"), dict) and "period" in kwargs["input"]:
                fixed, changed = _fix(kwargs["input"])
                if changed:
                    kwargs = {**kwargs, "input": fixed}
            elif args and isinstance(args[0], dict) and "period" in args[0]:
                fixed, changed = _fix(args[0])
                if changed:
                    args = (fixed,) + args[1:]

        try:
            result = await asyncio.wait_for(
                original_arun(*args, config=config, run_manager=run_manager, **kwargs),
                timeout=timeout_secs,
            )
        except asyncio.TimeoutError:
            raise MCPTimeoutError(
                f"MCP tool '{mcp_tool.name}' did not respond within {timeout_secs}s. "
                "The MCP server is unresponsive — aborting workflow."
            )

        # Fix 2: sanitize NaN/Infinity tokens before they reach Gemini (causes 400 errors)
        if isinstance(result, str):
            result = _sanitize_nan(result)

        # Fix 1: auto-save raw data arrays to CSV — never expose them to the LLM context
        result = await _auto_save_result(result, tool_name)

        return result

    mcp_tool._arun = _arun_with_timeout
    return mcp_tool


# =============================================================================
# DATA ENGINEER TOOLS
# =============================================================================

# Storage directory for fetched data — use absolute path to avoid CWD ambiguity
_BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_STORAGE_DIR = Path(os.getenv("DATA_STORAGE_DIR", str(_BACKEND_DIR / "data")))


def _run_async(coro):
    """Helper to run async coroutines in sync context."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


async def _save_data_to_storage(data: Any, file_path: Path) -> dict:
    """
    Save data to storage and return metadata. Handles both raw data and pointers.
    """
    # Ensure parent directory exists
    file_path.parent.mkdir(parents=True, exist_ok=True)

    # Handle large tool result pointers
    if isinstance(data, str) and '"file_path": "/large_tool_results/' in data:
        try:
            pointer = json.loads(data)
            pointer_path = pointer.get("file_path")
            if pointer_path:
                # Resolve physical path to the large result
                temp_dir = Path(os.getenv("TEMP_DIR", str(Path.home() / ".gemini" / "tmp" / "deepresearchagent")))
                filename = Path(pointer_path).name
                physical_path = temp_dir / "large_tool_results" / filename
                if physical_path.exists():
                    data = physical_path.read_text(encoding="utf-8")
        except Exception as e:
            _de_logger.warning("Failed to resolve large tool result pointer: %s", e)

    # Parse JSON string if needed (LLM may pass MCP tool output as a string)
    if isinstance(data, str):
        import json as _json
        try:
            data = _json.loads(data)
        except Exception:
            data = [{"raw": data}]

    # Convert data to DataFrame if needed
    if isinstance(data, dict):
        # FRED / FMP time-series format: {"series_id": "GDP", ..., "data": [{date, value}, ...]}
        # Expand the nested records list into proper rows so quant-developer can read the file
        # with a plain pd.read_csv() — no JSON parsing needed downstream.
        if "data" in data and isinstance(data["data"], list) and data["data"]:
            records = data["data"]
            meta = {k: v for k, v in data.items()
                    if k != "data" and not isinstance(v, (list, dict))}
            df = pd.DataFrame(records)
            for key, val in meta.items():
                df[key] = val
        else:
            df = pd.DataFrame([data])
    elif isinstance(data, list):
        df = pd.DataFrame(data)
    elif isinstance(data, pd.DataFrame):
        df = data
    else:
        df = pd.DataFrame([{"raw": str(data)}])

    # Fix 3: replace NaN with None (written as empty string in CSV) so downstream
    # schema extraction and LLM tool results never contain bare NaN tokens.
    df = df.where(pd.notna(df), other=None)

    # Save to CSV
    df.to_csv(file_path, index=False)

    # Return metadata
    return {
        "storage_path": file_path.relative_to(Path.cwd()).as_posix(),
        "row_count": len(df),
        "columns": df.columns.tolist(),
        "size_bytes": file_path.stat().st_size
    }


@tool
def save_data(
    data: str,
    ticker: str,
    data_type: str,
    runtime: ToolRuntime[ResearchContext],
    metadata: Optional[Dict[str, str | int | float | bool | None]] = None
) -> str:
    """
    Save data fetched from any MCP tool (FMP, FRED, or other sources) to storage.

    Use this after fetching any financial or macroeconomic data to persist it to
    local storage and get back a storage path. Never return raw data — always save
    it first and return the path.

    The job_id is automatically read from runtime context — do NOT pass it as an argument.

    Args:
        data: JSON string returned by any MCP tool, or a pointer JSON string
        ticker: Stock ticker, FRED series ID, or other identifier (e.g., "AAPL", "UNRATE", "SP500")
        data_type: Descriptive type of data (e.g., "income_statement", "unemployment_rate", "cpi_monthly")
        metadata: Optional metadata to include (date ranges, source, units, etc.)

    Returns:
        JSON string with storage path and metadata (NOT the raw data)
    """
    job_id = runtime.context.job_id

    async def _save():
        # Create file path
        file_name = f"{ticker}_{data_type}_{job_id}.csv"
        file_path = DATA_STORAGE_DIR / job_id / file_name

        # Save data
        meta = await _save_data_to_storage(data, file_path)

        # Add additional metadata if provided
        if metadata:
            meta.update(metadata)

        return meta

    try:
        result = _run_async(_save())

        return json.dumps({
            "status": "success",
            "ticker": ticker,
            "data_type": data_type,
            **result
        })
    except Exception as e:
        return json.dumps({
            "status": "error",
            "error": str(e),
            "message": f"Failed to save data for {ticker}"
        })


@tool
def extract_schema(file_paths: str | list[str]) -> str:
    """
    Extract exact schemas from saved data files.

    This is DETERMINISTIC - uses pure pandas to extract column names, types,
    and sample rows. No LLM guessing.

    Use this tool after fetching data to understand the structure of the data
    files before passing them to the code generation agent.

    Args:
        file_paths: List of paths to CSV or JSON data files

    Returns:
        JSON string with schemas for each file. Each schema contains:
        - file_path: Original storage path
        - columns: List of exact column names
        - dtypes: Dictionary mapping column names to data types
        - sample_rows: First 2 rows as list of dictionaries
        - shape: Tuple of (num_rows, num_columns)
    """
    if isinstance(file_paths, str):
        try:
            import json as _json
            file_paths = _json.loads(file_paths)
            if not isinstance(file_paths, list):
                file_paths = [str(file_paths)]
        except Exception:
            file_paths = [file_paths]
    if not isinstance(file_paths, list):
        file_paths = [str(file_paths)]

    schemas = {}

    for file_path in file_paths:
        try:
            df = pd.read_csv(file_path)
            schema = {
                "file_path": file_path,
                "columns": df.columns.tolist(),
                "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()},
                "sample_rows": df.head(2).to_dict('records'),
                "shape": list(df.shape)
            }
            schemas[file_path] = schema

        except Exception as e:
            schemas[file_path] = {
                "status": "error",
                "error": str(e)
            }

    return json.dumps({
        "status": "success",
        "schemas": schemas
    })


# =============================================================================
# SUBAGENT CONFIGURATION
# =============================================================================

def _build_system_prompt() -> str:
    """Build the data engineer system prompt."""
    return f"""# ROLE
You are the Data Engineer. You fetch financial data and extract deterministic schemas while preventing context bloat.

# DATA SOURCE RULES — STRICT
| Data type | Source | Tools |
|-----------|--------|-------|
| Stock quotes, financial statements, market data, SEC filings | **FMP** | `getIncomeStatement`, `getQuote`, etc. |
| Macroeconomic series (GDP, CPI, unemployment, rates, payrolls…) | **FRED** | `fred_search`, `fred_get_series` |

# CORE RULES
1. **NO RAW DATA:** NEVER return raw data arrays. ALWAYS call `save_data` and return only the storage path + metadata.
2. **TOOL BOUNDARY:** Filesystem and shell tools are blocked. Use only MCP tools plus `save_data` and `extract_schema`.
3. **FMP TOOLS:** Call FMP tools directly as functions.
   - `limit ≤ 5` for statement tools.
   - `period` must be: "FY", "Q1", "Q2", "Q3", "Q4". NEVER "annual" or "quarterly".
4. **POINTERS:** If a tool returns `"file_path": "/large_tool_results/..."`, pass that JSON string as-is to `save_data`.
5. **MACRO DATA → PREFER FRED:** For macroeconomic series (GDP, CPI, unemployment,
   interest rates, payrolls, wages, participation rate, etc.) prefer FRED tools
   (`fred_search`, `fred_get_series`) over FMP economics tools. FMP economics tools
   exist but FRED provides richer historical macro data.
6. **CONCISENESS:** Final response must be under 150 words. Return ONLY the JSON result (data_files, row_counts, metadata).

# INTEGRATION
- **FMP:** `statements` toolset is pre-enabled. Call `enable_toolset(name=...)` for other FMP toolsets.
- **FRED:** Use `fred_search(query=...)` to find a series ID, then `fred_get_series(series_id=...)`. Pass series ID as `ticker` in `save_data`.
- **Workflow:** Fetch → `save_data` → `extract_schema` (if requested) → Return JSON summary.

# OUTPUT FORMAT
{{
    "status": "success",
    "data_files": {{"TICKER": "path/to/file.csv"}},
    "row_counts": {{"TICKER": 10}},
    "metadata": {{"data_type": "income_statement", "source": "FMP"}}
}}
"""


async def get_data_engineer_subagent():
    """
    Create and return the data engineer subagent config with FMP and (optionally) FRED MCP tools.

    FRED tools are optional — if the local FRED MCP server is unavailable, the agent starts
    with FMP tools only and logs a warning.

    Returns:
        Dictionary with full agent configuration
    """
    import logging
    logger = logging.getLogger(__name__)

    # FMP (required, hosted — never degraded)
    fmp_client = await create_fmp_mcp_client()
    fmp_tools = await fmp_client.get_tools()

    # Pre-enable `statements` so financial statement tools are available from turn 1.
    enable_tool = next((t for t in fmp_tools if getattr(t, "name", "") == "enable_toolset"), None)
    if enable_tool:
        try:
            await asyncio.wait_for(
                enable_tool.ainvoke({"name": "statements"}),
                timeout=_FMP_TIMEOUT,
            )
        except Exception as _e:
            logger.warning("Failed to pre-enable FMP 'statements' toolset: %s", _e)
    fmp_tools = await fmp_client.get_tools()  # re-fetch with statements tools included

    # Wrap all FMP tools so any single call that hangs raises MCPTimeoutError
    fmp_tools = [_with_timeout(t, _FMP_TIMEOUT) for t in fmp_tools]

    # FRED (optional, local server)
    fred_tools = []
    try:
        fred_client = await create_fred_mcp_client()
        fred_tools = await asyncio.wait_for(
            fred_client.get_tools(),
            timeout=_FRED_TIMEOUT,
        )

        # Validate the FRED MCP server can actually call FRED by invoking fred_get_series.
        # get_tools() only fetches tool definitions; it does NOT verify the API key works.
        # fred_get_series is the only tool that actually calls FRED's data API.
        probe_tool = next(
            (t for t in fred_tools if getattr(t, "name", "") == "fred_get_series"),
            None
        )
        if probe_tool:
            try:
                await asyncio.wait_for(
                    probe_tool.ainvoke({"series_id": "GDP"}),
                    timeout=_FRED_TIMEOUT,
                )
            except Exception as probe_err:
                logger.warning(
                    "FRED MCP server probe failed — FRED tools not loaded. "
                    "Ensure the FRED MCP server was started with a valid FRED_API_KEY.\n"
                    "Error: %s", probe_err
                )
                fred_tools = []
    except Exception as e:
        logger.error(
            "FRED MCP server unreachable at %s. Start with: "
            "cd fred-mcp-server && FRED_API_KEY=<key> node build/index.js --http\nError: %s",
            os.getenv("FRED_MCP_URL", "http://localhost:3000/mcp"), e
        )

    # Wrap all FRED tools the same way
    fred_tools = [_with_timeout(t, _FRED_TIMEOUT) for t in fred_tools]

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
        "system_prompt": _build_system_prompt(),
        "tools": [save_data, extract_schema] + fmp_tools + fred_tools,
        "model": "google_genai:gemini-3-flash-preview",
        "skills": [str(_BACKEND_DIR / "skills" / "data-engineer")]
    }

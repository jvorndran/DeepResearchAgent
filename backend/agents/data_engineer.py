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
import pandas as pd
import os
import json
import asyncio
from pathlib import Path
from mcp_clients.fmp_mcp_client import create_fmp_mcp_client, get_fmp_mcp_config, list_fmp_tools as list_fmp_tools_async
from mcp_clients.fred_mcp_client import create_fred_mcp_client


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
_de_logger = _logging.getLogger(__name__)


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
            return await asyncio.wait_for(
                original_arun(*args, config=config, run_manager=run_manager, **kwargs),
                timeout=timeout_secs,
            )
        except asyncio.TimeoutError:
            raise MCPTimeoutError(
                f"MCP tool '{mcp_tool.name}' did not respond within {timeout_secs}s. "
                "The MCP server is unresponsive — aborting workflow."
            )

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
    Save data to storage and return metadata.

    Args:
        data: Data to save (DataFrame, dict, or list)
        file_path: Path where data should be saved

    Returns:
        Dictionary with storage path and metadata
    """
    # Ensure parent directory exists
    file_path.parent.mkdir(parents=True, exist_ok=True)

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
def save_fmp_data(
    data: str,
    ticker: str,
    data_type: str,
    job_id: str,
    metadata: Optional[Dict[str, Any]] = None
) -> str:
    """
    Save data fetched from FMP MCP tools to storage.

    After using FMP MCP tools to fetch financial data, use this tool to
    save the data to local storage and get back only the storage path.

    Args:
        data: The data fetched from FMP (dict, list, or DataFrame)
        ticker: Stock ticker or identifier (e.g., "TSMC", "AAPL")
        data_type: Type of data (e.g., "quote", "income_statement", "historical_price")
        job_id: Unique job identifier for organizing storage
        metadata: Optional metadata to include (date ranges, etc.)

    Returns:
        JSON string with storage path and metadata (NOT the raw data)
    """
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
        # Convert path to forward slashes to avoid escaping issues
        if "storage_path" in result:
            result["storage_path"] = result["storage_path"].replace("\\", "/")
            
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
def extract_schema(file_paths: List[str]) -> str:
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
    schemas = {}

    for file_path in file_paths:
        try:
            # Convert any backslashes to forward slashes
            clean_path = file_path.replace("\\", "/")
            df = pd.read_csv(clean_path)
            schema = {
                "file_path": clean_path,
                "columns": df.columns.tolist(),
                "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()},
                "sample_rows": df.head(2).to_dict('records'),
                "shape": list(df.shape)
            }
            schemas[clean_path] = schema

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

def _build_system_prompt(fred_available: bool) -> str:
    """Build the data engineer system prompt, optionally including FRED tools."""
    fred_section = ""
    if fred_available:
        fred_section = """
## FRED MCP Integration

You also have direct access to the **Federal Reserve Economic Data (FRED) MCP Server** which provides macroeconomic series:
- `fred_browse`: Browse available FRED data categories and series
- `fred_search`: Search for specific economic series by keyword
- `fred_get_series`: Fetch time-series data for a given FRED series ID (e.g., GDP, CPIAUCSL, FEDFUNDS, UNRATE)

**When to use FRED vs FMP**:
- Use **FRED** for macroeconomic indicators: GDP, inflation (CPI/PCE), interest rates, unemployment, money supply, trade balance, etc.
- Use **FMP** for company/equity data: stock prices, financial statements, earnings, market data, etc.
- For mixed queries (e.g., "compare TSMC revenue with US GDP growth"), use both: FMP for company data, FRED for macro series.

Save FRED data with `save_fmp_data` just like FMP data — use the series ID as the `ticker` and a descriptive `data_type` (e.g., `ticker="GDP"`, `data_type="real_gdp_annual"`).
"""
    else:
        fred_section = """
## FRED MCP Server

The FRED MCP server is currently **offline**. FRED macroeconomic tools are not available.
To enable FRED data: start the server with `node build/index.js --http` in the fred-mcp-server directory.
"""

    return f"""You are the Data Engineer for a financial research platform.

Your role is to handle all data operations while preventing context window bloat.

## ⚠️ CRITICAL: HOW TO CALL FMP TOOLS

FMP tools (like `getIncomeStatement`, `getHistoricalPrice`, etc.) are **direct tool function
calls** — NOT shell commands. Call them exactly like any other tool by their function name.

✅ CORRECT — call the tool directly as a function:
  getIncomeStatement(symbol="AAPL", period="FY", limit=5)

  Valid period values: "FY" (full fiscal year), "Q1", "Q2", "Q3", "Q4" (quarterly).
  NEVER use "annual", "quarter", "yearly", or any other value — the API will reject them.

❌ WRONG — never use shell/execute for FMP data:
  execute("fmp getIncomeStatement --symbol AAPL")   ← fmp is NOT a CLI program
  execute("python -c '...'")                         ← wrong

The `execute`, `write_file`, and `read_file` shell tools belong to the quant developer.
**Do NOT use shell tools for any data fetching.** Your tools are: FMP tools, FRED tools,
`save_fmp_data`, and `extract_schema` — nothing else.

## FMP MCP Integration

You have access to the **Financial Modeling Prep (FMP) MCP Server** which provides 250+ tools
across categories. The `statements` toolset is **already enabled** — `getIncomeStatement`,
`getBalanceSheetStatement`, `getCashFlowStatement`, `getKeyMetrics`, and `getRatios` are
ready to call immediately.

For other data types, enable the relevant toolset first:

**Common toolset → tool mappings:**
- Revenue / income data → `statements` (already on) → `getIncomeStatement` (limit ≤ 5)
- Balance sheet → `statements` (already on) → `getBalanceSheetStatement` (limit ≤ 5)
- Cash flow → `statements` (already on) → `getCashFlowStatement` (limit ≤ 5)
- Stock price history → enable `charts` → `getHistoricalPrice`
- Current quote → enable `quotes` → `getQuote`
- Company info → enable `company` → `getCompanyProfile`
- Economic indicators → enable `economics` → `getEconomicIndicators`

**Workflow:**
```
# For statements data (already enabled — go straight to step 2):
1. [skip] enable_toolset already done at startup
2. getIncomeStatement(symbol="AAPL", period="FY", limit=5)   # ← limit MAX 5 (plan limit)
3. save_fmp_data(data=<result>, ticker="AAPL", data_type="income_statement", job_id=<job_id>)
4. extract_schema(file_paths=[<saved_path>])

# For other data types:
1. enable_toolset(name="charts")   # or "quotes", "company", etc.
2. getHistoricalPrice(symbol="AAPL", ...)
3. save_fmp_data(...)
```

**Meta-tools (use only when needed):**
- `list_toolsets` — see all toolsets and their status
- `enable_toolset` — activate a toolset
- `list_tools` — list currently active tools
- `describe_toolset` — get parameter details for a toolset's tools
{fred_section}
## Responsibilities

1. **Data Fetching**:
   - Call FMP MCP tools directly to fetch financial/equity data
   - Call FRED MCP tools directly to fetch macroeconomic series (when available)
   - Use `save_fmp_data` to save fetched data to storage
   - Return ONLY storage paths, never raw data

2. **Schema Extraction**:
   - Use `extract_schema` to load data from storage and extract exact schemas
   - Deterministically extract: column names, data types, sample rows (2 rows max)
   - Return compact schema metadata

## Critical Rules

- NEVER return raw data in your response
- ALWAYS save data to storage first using save_fmp_data, then return the path
- Schemas must be exact - use the extract_schema tool which uses pandas, not LLM inference
- Keep responses compact: paths + metadata only
- **API LIMIT**: statements tools (getIncomeStatement, getBalanceSheetStatement, etc.) support a maximum of `limit=5`. Never request more than 5 rows — it returns a 402 error. If the user asks for 10 years, fetch 5.

## Output Format

For data fetching tasks, return:
{{
    "status": "success",
    "data_files": {{
        "TSMC": "./data/job123/TSMC_quote_job123.csv"
    }},
    "row_counts": {{
        "TSMC": 1
    }},
    "metadata": {{
        "data_type": "quote",
        "source": "FMP MCP Server"
    }}
}}

For schema extraction, return:
{{
    "status": "success",
    "schemas": {{
        "./data/job123/TSMC_quote_job123.csv": {{
            "columns": ["symbol", "price", "volume", "change"],
            "dtypes": {{"symbol": "object", "price": "float64"}},
            "sample_rows": [{{}}, {{}}],
            "shape": [1, 4]
        }}
    }}
}}

## Chart Schema Awareness

The quant developer is responsible for producing `outputs/charts.json` — a named dict of
chart definitions (AxisChartDef / ScatterChartDef / PieChartDef per the ResearchReport v1 schema).
Your job ends at data storage and schema extraction; you are not responsible for chart structure.

Remember: You are the data pipeline. Keep the orchestrator's context clean by returning only references, not raw data."""


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

    # Pre-enable the `statements` toolset so getIncomeStatement / getBalanceSheetStatement /
    # getCashFlowStatement / getKeyMetrics / getRatios are available from the very first
    # LLM turn — eliminates the 3-turn discovery loop (list_toolsets→enable→list_tools).
    enable_tool = next((t for t in fmp_tools if getattr(t, "name", "") == "enable_toolset"), None)
    if enable_tool:
        await asyncio.wait_for(
            enable_tool.ainvoke({"name": "statements"}),
            timeout=_FMP_TIMEOUT,
        )
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
        logger.warning(
            "FRED MCP server unavailable at %s — FRED tools not loaded. "
            "Start with: node build/index.js --http\nError: %s",
            os.getenv("FRED_MCP_URL", "http://localhost:3000/mcp"), e
        )

    # Wrap all FRED tools the same way
    fred_tools = [_with_timeout(t, _FRED_TIMEOUT) for t in fred_tools]

    fred_available = len(fred_tools) > 0

    if fred_available:
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
    else:
        description = """Use this subagent to fetch financial data from the FMP MCP Server or extract schemas from saved data files.

    Delegate when you need to:
    - Fetch stock data from Financial Modeling Prep (FMP) via MCP Server (250+ tools across 24 categories)
    - Get real-time quotes, historical prices, financial statements, market data
    - Access technical indicators, insider trading data, SEC filings, news, and more
    - Save fetched data to storage
    - Extract exact schemas (column names, dtypes, sample rows) from data files

    Note: FMP uses dynamic toolset loading — the agent will call enable_toolset() before using
    financial tools. It returns only storage paths and compact metadata, never raw data."""

    return {
        "name": "data-engineer",
        "description": description,
        "system_prompt": _build_system_prompt(fred_available),
        "tools": [save_fmp_data, extract_schema] + fmp_tools + fred_tools,
        "model": "google_genai:gemini-3-flash-preview"
    }

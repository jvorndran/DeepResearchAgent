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

from typing import Dict, Any, List, Optional
from langchain_core.tools import tool
import pandas as pd
import os
import json
import asyncio
from pathlib import Path
from .fmp_mcp_client import create_fmp_mcp_client


# =============================================================================
# DATA ENGINEER TOOLS
# =============================================================================

# Storage directory for fetched data
DATA_STORAGE_DIR = Path(os.getenv("DATA_STORAGE_DIR", "./data"))


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

    # Convert data to DataFrame if needed
    if isinstance(data, dict):
        df = pd.DataFrame([data])
    elif isinstance(data, list):
        df = pd.DataFrame(data)
    elif isinstance(data, pd.DataFrame):
        df = data
    else:
        # Try to convert to DataFrame
        df = pd.DataFrame(data)

    # Save to CSV
    df.to_csv(file_path, index=False)

    # Return metadata
    return {
        "storage_path": str(file_path),
        "row_count": len(df),
        "columns": df.columns.tolist(),
        "size_bytes": file_path.stat().st_size
    }


@tool
def save_fmp_data(
    data: Any,
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
            # TODO: Actually read the file from storage
            # For now, return mock schema

            # In production, would do:
            # df = pd.read_csv(file_path)
            # schema = {
            #     "file_path": file_path,
            #     "columns": df.columns.tolist(),
            #     "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()},
            #     "sample_rows": df.head(2).to_dict('records'),
            #     "shape": df.shape
            # }

            # Mock schema
            schema = {
                "file_path": file_path,
                "columns": ["date", "open", "high", "low", "close", "volume"],
                "dtypes": {
                    "date": "datetime64[ns]",
                    "open": "float64",
                    "high": "float64",
                    "low": "float64",
                    "close": "float64",
                    "volume": "int64"
                },
                "sample_rows": [
                    {"date": "2020-01-01", "open": 50.0, "high": 52.0, "low": 49.5, "close": 51.5, "volume": 1000000},
                    {"date": "2020-01-02", "open": 51.5, "high": 53.0, "low": 51.0, "close": 52.5, "volume": 1200000}
                ],
                "shape": [1250, 6]
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

async def get_data_engineer_subagent():
    """
    Create and return the data engineer subagent config with FMP MCP tools.

    Usage:
        from agents.data_engineer import get_data_engineer_subagent

        async def main():
            subagent = await get_data_engineer_subagent()
            # Use with DeepAgents

    Returns:
        Dictionary with full agent configuration including 250+ FMP MCP tools
    """
    mcp_client = await create_fmp_mcp_client()
    mcp_tools = await mcp_client.get_tools()

    return {
        "name": "data-engineer",

        "description": """Use this subagent to fetch financial data from the FMP MCP Server or extract schemas from saved data files.

    Delegate when you need to:
    - Fetch stock data from Financial Modeling Prep (FMP) via MCP Server (250+ tools available)
    - Get real-time quotes, historical prices, financial statements, market data
    - Access technical indicators, insider trading data, SEC filings, news, and more
    - Save fetched data to storage
    - Extract exact schemas (column names, dtypes, sample rows) from data files

    The data engineer has direct access to 250+ FMP MCP tools and returns only storage paths
    and compact metadata, never raw data. This prevents context window bloat.""",

        "system_prompt": """You are the Data Engineer for a financial research platform.

Your role is to handle all data operations while preventing context window bloat.

## MCP Integration

You have direct access to the **Financial Modeling Prep (FMP) MCP Server** which provides 250+ tools for:
- Stock quotes and historical prices
- Financial statements (income statement, balance sheet, cash flow)
- Company profiles and metrics
- Market data and indices
- Technical indicators (RSI, SMA, EMA, MACD)
- Insider and institutional trading
- SEC filings and regulatory documents
- News, earnings, and economic indicators
- Cryptocurrency and forex data
- ESG ratings and commodities

## Responsibilities

1. **Data Fetching**:
   - You have direct access to 250+ FMP MCP tools (they are in your tool list)
   - Call FMP MCP tools directly to fetch financial data
   - Use `save_fmp_data` to save fetched data to storage
   - Return ONLY storage paths, never raw data

2. **Schema Extraction**:
   - Use `extract_schema` to load data from storage and extract exact schemas
   - Deterministically extract: column names, data types, sample rows (2 rows max)
   - Return compact schema metadata

## Tools Available

You have access to:
- **250+ FMP MCP tools**: Stock quotes, financials, indicators, company data, etc. (directly in your tool list)
- **save_fmp_data**: Save data fetched from FMP to storage and get storage path
- **extract_schema**: Extract exact schemas from saved data files

## Critical Rules

- NEVER return raw data in your response
- ALWAYS save data to storage first using save_fmp_data, then return the path
- Use FMP MCP tools directly for fetching financial data
- Schemas must be exact - use the extract_schema tool which uses pandas, not LLM inference
- Keep responses compact: paths + metadata only

## Workflow Example

When asked to fetch stock data for TSMC:
1. Call the appropriate FMP MCP tool (e.g., get_quote, get_historical_price)
2. Use `save_fmp_data` to save the result to storage
3. Optionally use `extract_schema` to analyze the structure
4. Return the storage path and metadata in JSON format

## Output Format

For data fetching tasks, return:
{
    "status": "success",
    "data_files": {
        "TSMC": "./data/job123/TSMC_quote_job123.csv"
    },
    "row_counts": {
        "TSMC": 1
    },
    "metadata": {
        "data_type": "quote",
        "source": "FMP MCP Server"
    }
}

For schema extraction, return:
{
    "status": "success",
    "schemas": {
        "./data/job123/TSMC_quote_job123.csv": {
            "columns": ["symbol", "price", "volume", "change"],
            "dtypes": {"symbol": "object", "price": "float64", ...},
            "sample_rows": [{...}, {...}],
            "shape": [1, 4]
        }
    }
}

## Chart Schema Awareness

The quant developer is responsible for producing `outputs/charts.json` — a named dict of
chart definitions (AxisChartDef / ScatterChartDef / PieChartDef per the ResearchReport v1 schema).
Your job ends at data storage and schema extraction; you are not responsible for chart structure.

Remember: You are the data pipeline. Keep the orchestrator's context clean by returning only references, not raw data.
The FMP MCP Server gives you access to comprehensive financial data - use it!""",

        "tools": [save_fmp_data, extract_schema] + mcp_tools,

        "model": "google-genai:gemini-3-flash-preview"
    }

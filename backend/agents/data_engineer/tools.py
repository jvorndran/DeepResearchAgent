"""LangChain tools for save_data and extract_schema."""
from typing import Dict, Optional
import json

import pandas as pd
from langchain_core.tools import tool
from langchain.tools import ToolRuntime

from core.context import ResearchContext

from .storage import _run_async, _save_data_to_storage
from .paths import DATA_STORAGE_DIR


@tool
def save_data(
    data: str,
    ticker: str,
    data_type: str,
    runtime: ToolRuntime[ResearchContext],
    metadata: Optional[Dict[str, str | int | float | bool | None]] = None,
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

        return json.dumps({"status": "success", "ticker": ticker, "data_type": data_type, **result})
    except Exception as e:
        return json.dumps(
            {"status": "error", "error": str(e), "message": f"Failed to save data for {ticker}"}
        )


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
                "sample_rows": df.head(2).to_dict("records"),
                "shape": list(df.shape),
            }
            schemas[file_path] = schema

        except Exception as e:
            schemas[file_path] = {"status": "error", "error": str(e)}

    return json.dumps({"status": "success", "schemas": schemas})

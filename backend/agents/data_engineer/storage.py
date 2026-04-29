"""Persist fetched MCP payloads and resolve pointer paths."""
import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

import pandas as pd

from .paths import BACKEND_DIR

logger = logging.getLogger(__name__)


def _resolve_pointer_path(pointer_path: str) -> Path | None:
    path = Path(pointer_path)
    candidates = [path]
    if not path.is_absolute():
        candidates.append(Path.cwd() / path)
        candidates.append(BACKEND_DIR / path)
        candidates.append(BACKEND_DIR.parent / path)

    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return None


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

    # Handle large tool result pointers from Gemini temp files or our own spill-to-disk flow.
    if isinstance(data, str) and '"file_path"' in data:
        try:
            pointer = json.loads(data)
            pointer_path = pointer.get("file_path")
            if pointer_path:
                resolved = _resolve_pointer_path(pointer_path)
                if resolved and resolved.exists():
                    if resolved.suffix.lower() == ".csv":
                        data = pd.read_csv(resolved)
                    elif resolved.suffix.lower() == ".json":
                        data = resolved.read_text(encoding="utf-8")
                    else:
                        data = resolved.read_text(encoding="utf-8")
                else:
                    temp_dir = Path(
                        os.getenv(
                            "TEMP_DIR", str(Path.home() / ".gemini" / "tmp" / "deepresearchagent")
                        )
                    )
                    filename = Path(pointer_path).name
                    physical_path = temp_dir / "large_tool_results" / filename
                    if physical_path.exists():
                        data = physical_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning("Failed to resolve large tool result pointer: %s", e)

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
            meta = {
                k: v for k, v in data.items() if k != "data" and not isinstance(v, (list, dict))
            }
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
        "storage_path": file_path.resolve().as_posix(),
        "row_count": len(df),
        "columns": df.columns.tolist(),
        "size_bytes": file_path.stat().st_size,
    }

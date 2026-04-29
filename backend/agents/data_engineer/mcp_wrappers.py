"""MCP client timeouts, result compaction, and tool wrappers."""
from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import time
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable

from langchain_core.callbacks import AsyncCallbackManagerForToolRun
from langchain_core.runnables import RunnableConfig

from .paths import DATA_STORAGE_DIR
from .storage import _save_data_to_storage

logger = logging.getLogger(__name__)

# Raised after repeated MCP request timeouts. This is a normal Exception so the
# tool error can flow back into the subagent and the agent can reformulate the
# request instead of aborting the whole workflow immediately.
class MCPTimeoutError(Exception):
    """Raised when an FMP or FRED MCP tool call times out."""


class MCPRequestError(Exception):
    """Raised when an FMP or FRED MCP tool call fails and should be corrected by the agent."""


_FMP_TIMEOUT = 30  # seconds per tool call (FMP is a hosted remote API)
_FRED_TIMEOUT = 30  # seconds per tool call (FRED local server)


# FMP statement tools that accept a `period` parameter.
# The API only accepts these exact values — reject anything else at the call site
# so the LLM sees the error immediately and retries with the correct value.
_VALID_FMP_PERIODS = {"FY", "Q1", "Q2", "Q3", "Q4"}
_PERIOD_ALIASES = {
    "annual": "FY",
    "yearly": "FY",
    "fy": "FY",
    "quarter": "Q1",  # best-effort: map generic "quarter" to Q1 so the call succeeds
    "quarterly": "Q1",
    "q1": "Q1",
    "q2": "Q2",
    "q3": "Q3",
    "q4": "Q4",
}
_STATEMENT_TOOLS = {
    "getIncomeStatement",
    "getBalanceSheetStatement",
    "getCashFlowStatement",
    "getKeyMetrics",
    "getRatios",
    # AsReported variants also accept a period param (though they need premium tier)
    "getIncomeStatementAsReported",
    "getBalanceSheetStatementAsReported",
    "getCashFlowStatementAsReported",
}

_MCP_INLINE_LIMIT = 800  # chars — MCP results longer than this go to a temp file

# FRED search/browse return JSON lists of series metadata — NOT time-series observations.
# Do not run those through the list→CSV spill or the 400-char preview path, or the model
# never sees series IDs and may call fred_search in a loop.
_MCP_METADATA_TOOLS = frozenset({"fred_search", "fred_browse"})
_METADATA_RESULT_MAX_CHARS = 100_000


def _sanitize_nan(result: str) -> str:
    """Replace bare NaN/Infinity tokens so Gemini accepts the JSON payload."""
    result = re.sub(r"\bNaN\b", "null", result)
    result = re.sub(r"\bInfinity\b", "null", result)
    result = re.sub(r"\b-Infinity\b", "null", result)
    return result


def _sanitize_jsonish(value: Any) -> Any:
    """Recursively replace non-finite floats so JSON serialization is safe."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, list):
        return [_sanitize_jsonish(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_sanitize_jsonish(item) for item in value)
    if isinstance(value, dict):
        return {key: _sanitize_jsonish(item) for key, item in value.items()}
    return value


def _json_dumps_compact(value: Any) -> str:
    return json.dumps(_sanitize_jsonish(value), ensure_ascii=False)


def _json_loads_safe(value: str) -> Any | None:
    try:
        return json.loads(value)
    except Exception:
        return None


def _looks_like_content_blocks(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) > 0
        and all(isinstance(block, dict) and "type" in block for block in value)
    )


def _content_blocks_to_text(blocks: list[dict[str, Any]]) -> str:
    text_parts: list[str] = []
    for block in blocks:
        if block.get("type") == "text":
            text = block.get("text")
            if isinstance(text, str) and text:
                text_parts.append(text)
            continue
        text_parts.append(_json_dumps_compact(block))
    return "\n".join(part for part in text_parts if part)


def _extract_structured_content(artifact: Any) -> Any | None:
    if artifact is None:
        return None
    if isinstance(artifact, dict):
        if "structured_content" in artifact:
            return artifact["structured_content"]
        if "structuredContent" in artifact:
            return artifact["structuredContent"]
    structured = getattr(artifact, "structured_content", None)
    if structured is not None:
        return structured
    return getattr(artifact, "structuredContent", None)


def _fail_closed_large_result(tool_name: str, byte_size: int, reason: str) -> str:
    return json.dumps(
        {
            "status": "mcp_result_omitted",
            "tool": tool_name,
            "byte_size": byte_size,
            "reason": reason,
            "note": "Large MCP payload omitted to protect model context.",
        }
    )


def _safe_filename_part(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return cleaned[:80].strip("._-")


def _auto_save_file_path(data: Any, tool_name: str) -> Path:
    series_id = ""
    if isinstance(data, dict):
        candidate = data.get("series_id")
        if not isinstance(candidate, str) and isinstance(data.get("metadata"), dict):
            candidate = data["metadata"].get("series_id")
        series_id = _safe_filename_part(candidate)

    stem_parts = [tool_name]
    if series_id:
        stem_parts.append(series_id)
    stem_parts.extend([str(time.time_ns()), uuid.uuid4().hex[:8]])
    return DATA_STORAGE_DIR / "_auto" / f"{'_'.join(stem_parts)}.csv"


def _compact_artifact(artifact: Any, compact_content: str, tool_name: str) -> Any:
    if artifact is None:
        return None

    structured = _extract_structured_content(artifact)
    content_pointer = _json_loads_safe(compact_content)
    if structured is not None:
        compact: dict[str, Any] = {}
        if isinstance(artifact, dict):
            for key, value in artifact.items():
                if key in {"structured_content", "structuredContent"}:
                    continue
                serialized = _json_dumps_compact(value)
                if len(serialized) <= _MCP_INLINE_LIMIT:
                    compact[key] = _sanitize_jsonish(value)
        compact["structured_content_pointer"] = (
            content_pointer
            if isinstance(content_pointer, dict)
            else {"tool": tool_name, "status": "saved_to_file"}
        )
        return compact

    serialized = _json_dumps_compact(artifact)
    if len(serialized) > _MCP_INLINE_LIMIT:
        return {
            "status": "artifact_omitted",
            "tool": tool_name,
            "byte_size": len(serialized.encode("utf-8")),
        }
    return _sanitize_jsonish(artifact)


async def _auto_save_result(result: Any, tool_name: str) -> str:
    """
    Prevent large MCP tool results from entering the LLM message history.

    Two-stage interception (does **not** apply to ``fred_search`` / ``fred_browse``):
    1. Structured data arrays (FRED/FMP time-series): saved to a job-scoped CSV via
       _save_data_to_storage so the agent can hand off the returned file path directly.
    2. Any other result exceeding _MCP_INLINE_LIMIT chars: written verbatim to a raw
       JSON file under DATA_STORAGE_DIR/_mcp_raw/; the LLM only sees a small preview
       dict with the file path and the first 400 chars.
    """
    data = None
    if isinstance(result, str):
        result_str = _sanitize_nan(result)
        data = _json_loads_safe(result_str)
    else:
        result = _sanitize_jsonish(result)
        data = result
        try:
            result_str = _json_dumps_compact(result)
        except Exception:
            result_str = str(result)

    if tool_name in _MCP_METADATA_TOOLS:
        if len(result_str) <= _METADATA_RESULT_MAX_CHARS:
            return result_str
        return (
            result_str[:_METADATA_RESULT_MAX_CHARS]
            + "\n...[truncated; narrow fred_search query if needed]"
        )

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
                file_path = _auto_save_file_path(data, tool_name)
                meta = await _save_data_to_storage(data, file_path)
                saved_path = meta["storage_path"]
                pointer = {
                    "status": "auto_saved",
                    "file_path": saved_path,
                    "row_count": meta["row_count"],
                    "columns": meta["columns"],
                    "note": "Raw data auto-saved. Use file_path directly; do not call save_data for this result.",
                }
                return json.dumps(pointer)
            except Exception as e:
                logger.warning("Auto-save failed for tool '%s': %s", tool_name, e)

    # Fallback: any result still longer than the inline limit goes to a raw file.
    if len(result_str) > _MCP_INLINE_LIMIT:
        try:
            timestamp = int(time.time())
            raw_dir = DATA_STORAGE_DIR / "_mcp_raw"
            raw_dir.mkdir(parents=True, exist_ok=True)
            raw_path = raw_dir / f"{tool_name}_{timestamp}.json"
            raw_path.write_text(result_str, encoding="utf-8")
            rel = raw_path.relative_to(Path.cwd()).as_posix()
            preview = {
                "file_path": rel,
                "preview": result_str[:400],
                "byte_size": len(result_str.encode()),
                "note": "Full MCP response saved to file. Read it only if you need specific fields.",
            }
            return json.dumps(preview)
        except Exception as e:
            logger.warning("MCP raw save failed for tool '%s': %s", tool_name, e)
            return _fail_closed_large_result(
                tool_name,
                len(result_str.encode("utf-8")),
                "Failed to persist oversized MCP payload to disk.",
            )

    return result_str


async def _normalize_mcp_result_for_llm(result: Any, tool_name: str) -> Any:
    """
    Normalize adapter-specific MCP return shapes before LangChain formats them
    into ToolMessages. This is where we enforce file-backed spill behavior.
    """
    if isinstance(result, tuple) and len(result) == 2:
        content, artifact = result
        structured = _extract_structured_content(artifact)
        payload = structured
        if payload is None:
            payload = (
                _content_blocks_to_text(content) if _looks_like_content_blocks(content) else content
            )
        compact_content = await _auto_save_result(payload, tool_name)
        compact_artifact = _compact_artifact(artifact, compact_content, tool_name)
        return compact_content, compact_artifact

    if _looks_like_content_blocks(result):
        return await _auto_save_result(_content_blocks_to_text(result), tool_name)

    return await _auto_save_result(result, tool_name)


async def _run_mcp_request(
    *,
    provider: str,
    operation: str,
    timeout_secs: float,
    request_factory: Callable[[], Awaitable[Any]],
) -> Any:
    try:
        return await asyncio.wait_for(request_factory(), timeout=timeout_secs)
    except asyncio.TimeoutError as last_error:
        raise MCPTimeoutError(
            f"{provider} MCP request '{operation}' timed out after {timeout_secs}s. "
            "Use the error to adjust the next request instead of repeating it unchanged."
        ) from last_error
    except Exception as last_error:
        raise MCPRequestError(
            f"{provider} MCP request '{operation}' failed: {last_error}. "
            "Use the exact error to adjust the next request instead of repeating it unchanged."
        ) from last_error


def _build_mcp_tool_error_payload(
    provider: str, tool_name: str, error: Exception
) -> dict[str, Any]:
    return {
        "status": "error",
        "provider": provider,
        "tool": tool_name,
        "error": str(error),
        "retryable": True,
        "hint": "Read the exact error, then change the next series/query/parameters instead of repeating the same request.",
    }


def _with_timeout(mcp_tool, timeout_secs: float, provider: str):
    """
    Wrap an MCP BaseTool so any call surfaces a tool-visible failure quickly.

    Also normalises the `period` kwarg for FMP statement tools — the FMP MCP
    server only accepts "FY"|"Q1"|"Q2"|"Q3"|"Q4"; the LLM sometimes passes
    "annual" or "quarter" which causes a -32602 validation error.

    Tool failures are raised as normal Exceptions so the subagent can see the
    exact error immediately and choose a corrected follow-up request.
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
                    logger.warning(
                        "FMP tool '%s': invalid period=%r — correcting to %r",
                        tool_name,
                        raw,
                        corrected,
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
            result = await _run_mcp_request(
                provider=provider,
                operation=tool_name,
                timeout_secs=timeout_secs,
                request_factory=lambda: original_arun(
                    *args,
                    config=config,
                    run_manager=run_manager,
                    **kwargs,
                ),
            )
        except (MCPTimeoutError, MCPRequestError) as exc:
            logger.warning(
                "%s tool '%s' returned recoverable error: %s", provider, tool_name, exc
            )
            error_payload = _build_mcp_tool_error_payload(provider, tool_name, exc)
            if getattr(mcp_tool, "response_format", "") == "content_and_artifact":
                return await _normalize_mcp_result_for_llm(
                    (
                        json.dumps(error_payload),
                        {"structured_content": error_payload},
                    ),
                    tool_name,
                )
            return json.dumps(error_payload)

        # Normalize tuple/content-block MCP results before LangChain builds the
        # final ToolMessage so only compact pointers/previews enter model context.
        result = await _normalize_mcp_result_for_llm(result, tool_name)

        return result

    mcp_tool._arun = _arun_with_timeout
    return mcp_tool

"""Persist fetched MCP payloads and resolve pointer paths."""
import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator

from mcp_clients.provider_payload import provider_payload_sha256
from .paths import BACKEND_DIR

logger = logging.getLogger(__name__)

_SECRET_KEY_FRAGMENTS = (
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "client_secret",
    "password",
    "secret",
    "token",
    "user_id",
    "userid",
)


class SourceSnapshotDescriptor(BaseModel):
    """Typed descriptor for a persisted raw provider response snapshot."""

    model_config = ConfigDict(extra="forbid")

    snapshot_id: str
    provider: str
    source_id: str | None = None
    source_keys: list[str] = Field(default_factory=list)
    endpoint: str
    method: str
    request_params: dict[str, Any] = Field(default_factory=dict)
    request_body: dict[str, Any] = Field(default_factory=dict)
    retrieved_at: str
    freshness_policy: str
    response_sha256: str
    path: str
    byte_count: int = Field(ge=0)
    content_type: str = "application/json"
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator(
        "snapshot_id",
        "provider",
        "endpoint",
        "method",
        "retrieved_at",
        "freshness_policy",
        "path",
        "content_type",
    )
    @classmethod
    def _text_required(cls, value: str, info: Any) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError(f"{info.field_name} is required")
        return text

    @field_validator("response_sha256")
    @classmethod
    def _sha256_hex(cls, value: str) -> str:
        text = str(value).strip().lower()
        if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
            raise ValueError("response_sha256 must be a 64-character lowercase hex digest")
        return text

    @field_validator("source_keys")
    @classmethod
    def _source_keys_are_text(cls, value: list[str]) -> list[str]:
        out = []
        seen = set()
        for item in value:
            text = str(item).strip()
            if text and text not in seen:
                seen.add(text)
                out.append(text)
        return out


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


def save_source_snapshot(
    *,
    storage_dir: Path,
    provider: str,
    endpoint: str,
    method: str,
    response_payload: Any,
    retrieved_at: str,
    freshness_policy: str,
    source_id: str | None = None,
    source_keys: list[str] | tuple[str, ...] | None = None,
    request_params: dict[str, Any] | None = None,
    request_body: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> SourceSnapshotDescriptor:
    """Persist a raw provider response envelope and return its typed descriptor."""

    clean_provider = str(provider).strip()
    clean_source_id = str(source_id).strip() if source_id is not None else None
    clean_source_keys = _clean_text_list(source_keys or ())
    if clean_source_id is None and clean_source_keys:
        clean_source_id = clean_source_keys[0]

    response_sha256 = provider_payload_sha256(response_payload)
    source_slug = _slug_for_snapshot_path(clean_source_id or "-".join(clean_source_keys))
    provider_slug = _slug_for_snapshot_path(clean_provider)
    snapshot_id = f"{provider_slug}:{source_slug}:{response_sha256[:16]}"
    snapshot_dir = storage_dir / "source_snapshots"
    snapshot_path = snapshot_dir / f"{provider_slug}_{source_slug}_{response_sha256}.json"

    envelope = {
        "schema_version": 1,
        "snapshot_type": "raw_provider_response",
        "snapshot_id": snapshot_id,
        "provider": clean_provider,
        "source_id": clean_source_id,
        "source_keys": clean_source_keys,
        "endpoint": str(endpoint).strip(),
        "method": str(method).strip().upper(),
        "request_params": _redact_secrets(request_params or {}),
        "request_body": _redact_secrets(request_body or {}),
        "retrieved_at": str(retrieved_at).strip(),
        "freshness_policy": str(freshness_policy).strip(),
        "response_sha256": response_sha256,
        "content_type": "application/json",
        "metadata": _redact_secrets(metadata or {}),
        "raw_response": response_payload,
    }
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_bytes(_canonical_snapshot_bytes(envelope))

    return SourceSnapshotDescriptor(
        snapshot_id=snapshot_id,
        provider=clean_provider,
        source_id=clean_source_id,
        source_keys=clean_source_keys,
        endpoint=str(endpoint).strip(),
        method=str(method).strip().upper(),
        request_params=_redact_secrets(request_params or {}),
        request_body=_redact_secrets(request_body or {}),
        retrieved_at=str(retrieved_at).strip(),
        freshness_policy=str(freshness_policy).strip(),
        response_sha256=response_sha256,
        path=snapshot_path.resolve().as_posix(),
        byte_count=snapshot_path.stat().st_size,
        content_type="application/json",
        metadata=_redact_secrets(metadata or {}),
    )


def _canonical_snapshot_bytes(payload: dict[str, Any]) -> bytes:
    return (
        json.dumps(
            payload,
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
            allow_nan=False,
            default=str,
        )
        + "\n"
    ).encode("utf-8")


def _clean_text_list(values: list[str] | tuple[str, ...]) -> list[str]:
    out = []
    seen = set()
    for value in values:
        text = str(value).strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def _redact_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        out = {}
        for key, child in value.items():
            key_text = str(key)
            if _is_secret_key(key_text):
                out[key_text] = "[REDACTED]"
            else:
                out[key_text] = _redact_secrets(child)
        return out
    if isinstance(value, list):
        return [_redact_secrets(child) for child in value]
    if isinstance(value, tuple):
        return [_redact_secrets(child) for child in value]
    return value


def _is_secret_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_").replace(" ", "_")
    return any(fragment in normalized for fragment in _SECRET_KEY_FRAGMENTS)


def _slug_for_snapshot_path(value: str | None) -> str:
    text = str(value or "snapshot").strip().lower()
    slug = "".join(char if char.isalnum() else "_" for char in text)
    return "_".join(part for part in slug.split("_") if part) or "snapshot"

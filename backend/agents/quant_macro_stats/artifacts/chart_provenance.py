"""Structured chart provenance helpers for quant artifacts."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from .json_safety import to_json_safe


_PROVENANCE_KEYS = (
    "source_series",
    "source_files",
    "raw_window",
    "raw_latest_observation",
    "displayed_window",
    "displayed_latest_label",
    "frequency",
    "resampling",
    "normalization",
    "limitations",
)


def chart_provenance(
    *,
    source_series: Mapping[str, Any] | Iterable[Any] | str | Path | None = None,
    source_files: Mapping[str, Any] | Iterable[Any] | None = None,
    raw_window: Mapping[str, Any] | None = None,
    raw_latest_observation: str | Mapping[str, Any] | None = None,
    displayed_window: Mapping[str, Any] | None = None,
    displayed_latest_label: str | Mapping[str, Any] | None = None,
    frequency: str | None = None,
    resampling: str | Mapping[str, Any] | None = None,
    normalization: Mapping[str, Any] | None = None,
    limitations: str | Iterable[Any] | None = None,
) -> dict[str, Any]:
    """Build compact chart provenance metadata for saved quant charts.

    Generated analysis scripts attach this object to a chart definition under
    ``provenance``. ``save_quant_outputs`` then mirrors it into
    ``execution_summary["chart_provenance"]`` so writer and QA handoffs keep the
    raw source window distinct from display labels, resampling, and
    normalization choices.
    """

    payload = {
        "source_series": source_series,
        "source_files": source_files,
        "raw_window": raw_window,
        "raw_latest_observation": raw_latest_observation,
        "displayed_window": displayed_window,
        "displayed_latest_label": displayed_latest_label,
        "frequency": frequency,
        "resampling": resampling,
        "normalization": normalization,
        "limitations": limitations,
    }
    return normalize_chart_provenance(payload)


def normalize_chart_provenance(payload: Any) -> dict[str, Any]:
    """Return normalized chart provenance, dropping empty fields."""

    if not isinstance(payload, Mapping):
        return {}

    normalized: dict[str, Any] = {}
    for key in _PROVENANCE_KEYS:
        value = payload.get(key)
        if key == "source_series":
            value = _normalize_source_series(value)
        elif key == "source_files":
            value = _normalize_mapping_or_list(value)
        elif key in {"raw_window", "displayed_window", "normalization"}:
            value = _normalize_mapping(value)
        elif key == "limitations":
            value = _normalize_limitations(value)
        elif isinstance(value, Path):
            value = str(value)
        elif isinstance(value, Mapping):
            value = _normalize_mapping(value)

        if _has_value(value):
            normalized[key] = to_json_safe(value)

    return normalized


def _normalize_source_series(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _normalize_mapping(value)
    if isinstance(value, (str, Path)):
        return _split_source_series_text(str(value))
    if isinstance(value, Iterable):
        items: list[str] = []
        for item in value:
            if isinstance(item, (str, Path)):
                items.extend(_split_source_series_text(str(item)))
            elif _has_value(item):
                items.append(str(item).strip())
        return _unique_texts(items)
    return value


def _split_source_series_text(value: str) -> list[str]:
    return _unique_texts(part.strip() for part in value.split(",") if part.strip())


def _unique_texts(values: Iterable[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _normalize_mapping_or_list(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _normalize_mapping(value)
    if isinstance(value, (str, Path)):
        return [str(value)]
    if isinstance(value, Iterable):
        return [str(item) if isinstance(item, Path) else item for item in value]
    return value


def _normalize_mapping(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    normalized = {
        str(key): str(child) if isinstance(child, Path) else child
        for key, child in value.items()
        if _has_value(child)
    }
    return normalized or None


def _normalize_limitations(value: Any) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, Iterable) and not isinstance(value, (Mapping, bytes, bytearray)):
        items = [str(item) for item in value if _has_value(item)]
    else:
        items = [str(value)]
    cleaned = [item.strip() for item in items if item.strip()]
    return cleaned or None


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True

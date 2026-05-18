"""Source-unit metadata and comparison helpers for quant artifacts."""

from __future__ import annotations

import csv
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from mcp_clients.bls_client import KNOWN_BLS_SERIES, series_info_to_dict

from .json_safety import to_json_safe


_FAILED_STATUSES = {"failed", "error", "incompatible"}
_PASSING_STATUSES = {"passed", "converted", "compatible", "ok"}


def source_unit_metadata(
    source_key: str,
    *,
    source_file: str | Path | None = None,
    series_id: str | None = None,
    title: str | None = None,
    units: str | None = None,
    frequency: str | None = None,
    source: str | None = None,
    seasonal_adjustment: str | None = None,
    value_column: str = "value",
    unit_family: str | None = None,
    unit_basis: str | None = None,
    measure: str | None = None,
    transformation: str | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build compact source-unit metadata for one numeric source.

    Generated quant scripts should attach these records to
    ``execution_summary["source_unit_metadata"]`` before comparing values from
    different source files. When ``source_file`` is provided, first-row CSV
    metadata such as BLS/FRED ``series_id``, ``title``, ``units``, and
    ``frequency`` is used as defaults.
    """

    csv_meta = _metadata_from_csv(source_file) if source_file is not None else {}
    known_meta = _known_bls_metadata(series_id or csv_meta.get("series_id"))
    metadata = {
        **known_meta,
        **{key: value for key, value in csv_meta.items() if _has_value(value)},
    }

    values: dict[str, Any] = {
        "source_key": source_key,
        "source_file": str(source_file) if source_file is not None else None,
        "series_id": series_id or metadata.get("series_id"),
        "title": title or metadata.get("title"),
        "units": units or metadata.get("units"),
        "frequency": frequency or metadata.get("frequency"),
        "source": source or metadata.get("source"),
        "seasonal_adjustment": seasonal_adjustment or metadata.get("seasonal_adjustment"),
        "value_column": value_column,
        "transformation": transformation,
    }

    inferred = infer_unit_contract(values)
    values["unit_family"] = _clean_token(unit_family) or inferred.get("unit_family")
    values["unit_basis"] = _clean_token(unit_basis) or inferred.get("unit_basis")
    values["measure"] = _clean_token(measure) or inferred.get("measure")

    return _drop_empty(to_json_safe(values))


def source_unit_metadata_from_csv(
    source_file: str | Path,
    *,
    source_key: str | None = None,
    value_column: str = "value",
) -> dict[str, Any]:
    """Return source-unit metadata inferred from a saved CSV file."""

    path = Path(source_file)
    csv_meta = _metadata_from_csv(path)
    key = source_key or csv_meta.get("series_id") or path.stem
    return source_unit_metadata(
        str(key),
        source_file=path,
        value_column=value_column,
    )


def source_unit_metadata_from_files(source_files: Any) -> list[dict[str, Any]]:
    """Return source-unit metadata records for a data_files/source_files payload."""

    records: list[dict[str, Any]] = []
    for source_key, source_file in _iter_source_file_items(source_files):
        record = source_unit_metadata_from_csv(source_file, source_key=source_key)
        if _is_useful_source_unit_metadata(record):
            records.append(record)
    return records


def normalize_source_unit_metadata(value: Any) -> list[dict[str, Any]]:
    """Normalize a source-unit metadata payload into a list of compact records."""

    if isinstance(value, Mapping):
        if _looks_like_source_unit_record(value):
            candidates: Iterable[Any] = (value,)
        else:
            candidates = value.values()
    elif isinstance(value, list):
        candidates = value
    else:
        return []

    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        record = _normalize_source_unit_record(candidate)
        key = _source_identity(record)
        if not key or key in seen:
            continue
        seen.add(key)
        records.append(record)
    return records


def infer_unit_contract(metadata: Mapping[str, Any]) -> dict[str, str]:
    """Infer a coarse unit contract from source metadata."""

    units = _clean_text(metadata.get("units"))
    title = _clean_text(metadata.get("title"))
    text = f"{units} {title}".lower()
    result: dict[str, str] = {}

    if any(token in text for token in ("dollars per hour", "dollar per hour", "per hour")):
        result["unit_family"] = "currency_per_time"
        result["unit_basis"] = "hour"
    elif any(token in text for token in ("dollars per week", "dollar per week", "per week")):
        result["unit_family"] = "currency_per_time"
        result["unit_basis"] = "week"
    elif "percent" in text or units == "%":
        result["unit_family"] = "percent"
    elif "index" in text:
        result["unit_family"] = "index"
    elif "dollar" in text or "$" in text:
        result["unit_family"] = "currency"
    elif "hour" in text:
        result["unit_family"] = "time"
        result["unit_basis"] = "hour"

    if any(token in text for token in ("wage", "earnings", "payroll earnings")):
        result["measure"] = "wage"
    elif "price" in text or "cpi" in text:
        result["measure"] = "price"
    elif "unemployment" in text:
        result["measure"] = "labor_rate"

    return result


def unit_comparison(
    comparison_id: str,
    sources: Iterable[Mapping[str, Any]],
    *,
    operation: str = "difference",
    metric: str | None = None,
    conversion: str | Mapping[str, Any] | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Validate whether source units can support a direct comparison."""

    source_records = normalize_source_unit_metadata(list(sources))
    families = sorted(
        {
            str(record.get("unit_family"))
            for record in source_records
            if _has_value(record.get("unit_family"))
        }
    )
    bases = sorted(
        {
            str(record.get("unit_basis"))
            for record in source_records
            if _has_value(record.get("unit_basis"))
        }
    )
    incompatible_reason = _incompatible_reason(source_records)
    has_conversion = _has_value(conversion)
    if incompatible_reason and not has_conversion:
        status = "failed"
        compatible = False
    elif incompatible_reason and has_conversion:
        status = "converted"
        compatible = True
    elif families:
        status = "passed"
        compatible = True
    else:
        status = "unknown"
        compatible = None

    payload: dict[str, Any] = {
        "id": comparison_id,
        "operation": operation,
        "metric": metric,
        "status": status,
        "compatible": compatible,
        "sources": source_records,
        "unit_families": families,
        "unit_bases": bases,
        "conversion": conversion,
        "notes": notes,
    }
    if incompatible_reason:
        payload["incompatible_reason"] = incompatible_reason
    if status == "failed":
        payload["error"] = _comparison_error_message(payload)
    return _drop_empty(to_json_safe(payload))


def normalize_unit_comparisons(value: Any) -> list[dict[str, Any]]:
    """Normalize unit-comparison records from an execution summary."""

    if isinstance(value, Mapping):
        candidates: Iterable[Any]
        if _looks_like_unit_comparison(value):
            candidates = (value,)
        else:
            candidates = value.values()
    elif isinstance(value, list):
        candidates = value
    else:
        return []

    records: list[dict[str, Any]] = []
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        record = dict(candidate)
        if "sources" in record:
            record["sources"] = normalize_source_unit_metadata(record.get("sources"))
        records.append(_drop_empty(to_json_safe(record)))
    return records


def failed_unit_comparison_messages(summary: Mapping[str, Any]) -> list[str]:
    """Return actionable source-unit error messages from an execution summary."""

    messages: list[str] = []
    existing = summary.get("source_unit_errors")
    if isinstance(existing, list):
        messages.extend(str(item) for item in existing if str(item).strip())
    elif isinstance(existing, str) and existing.strip():
        messages.append(existing.strip())

    for comparison in normalize_unit_comparisons(summary.get("unit_comparisons")):
        status = str(comparison.get("status") or "").lower()
        compatible = comparison.get("compatible")
        if status in _FAILED_STATUSES or compatible is False:
            messages.append(_comparison_error_message(comparison))
    return list(dict.fromkeys(messages))


def mixed_wage_period_sources(metadata: Any) -> dict[str, list[str]]:
    """Return wage source labels grouped by incompatible time bases."""

    grouped: dict[str, list[str]] = {}
    for record in normalize_source_unit_metadata(metadata):
        if not _is_wage_currency_per_time(record):
            continue
        basis = str(record.get("unit_basis") or "").strip().lower()
        if not basis:
            continue
        grouped.setdefault(basis, []).append(_source_label(record))
    return {basis: labels for basis, labels in grouped.items() if labels}


def has_passing_mixed_wage_unit_comparison(summary: Mapping[str, Any]) -> bool:
    """Return True when summary records a passing conversion for mixed wage units."""

    for comparison in normalize_unit_comparisons(summary.get("unit_comparisons")):
        status = str(comparison.get("status") or "").lower()
        compatible = comparison.get("compatible")
        if status not in _PASSING_STATUSES and compatible is not True:
            continue
        if len(mixed_wage_period_sources(comparison.get("sources"))) < 2:
            continue
        if status == "converted" or _has_value(comparison.get("conversion")):
            return True
    return False


def attach_source_unit_metadata(summary: dict[str, Any]) -> None:
    """Attach normalized source-unit metadata inferred from summary source files."""

    existing = normalize_source_unit_metadata(summary.get("source_unit_metadata"))
    by_identity = {_source_identity(record): record for record in existing}
    for key in ("source_files", "data_files"):
        for record in source_unit_metadata_from_files(summary.get(key)):
            identity = _source_identity(record)
            if identity and identity not in by_identity:
                by_identity[identity] = record

    if by_identity:
        summary["source_unit_metadata"] = list(by_identity.values())

    comparisons = normalize_unit_comparisons(summary.get("unit_comparisons"))
    if comparisons:
        summary["unit_comparisons"] = comparisons

    errors = failed_unit_comparison_messages(summary)
    if errors:
        summary["source_unit_errors"] = errors


def _metadata_from_csv(source_file: str | Path | None) -> dict[str, Any]:
    if source_file is None:
        return {}
    path = Path(source_file)
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            row = next(csv.DictReader(handle), {})
    except (OSError, StopIteration, csv.Error, UnicodeDecodeError):
        return {}
    if not isinstance(row, dict):
        return {}

    metadata: dict[str, Any] = {}
    for key in (
        "series_id",
        "title",
        "units",
        "frequency",
        "seasonal_adjustment",
        "source",
    ):
        value = row.get(key)
        if _has_value(value):
            metadata[key] = str(value).strip()

    known = _known_bls_metadata(metadata.get("series_id"))
    return {**known, **metadata}


def _known_bls_metadata(series_id: Any) -> dict[str, Any]:
    key = str(series_id or "").strip().upper()
    if key not in KNOWN_BLS_SERIES:
        return {}
    return series_info_to_dict(KNOWN_BLS_SERIES[key])


def _iter_source_file_items(source_files: Any) -> Iterable[tuple[str, str | Path]]:
    if isinstance(source_files, Mapping):
        for key, value in source_files.items():
            if isinstance(value, (str, Path)) and str(value).strip():
                yield str(key), value
    elif isinstance(source_files, list):
        for value in source_files:
            if isinstance(value, (str, Path)) and str(value).strip():
                path = Path(value)
                yield path.stem, value


def _normalize_source_unit_record(candidate: Mapping[str, Any]) -> dict[str, Any]:
    values = {str(key): value for key, value in candidate.items()}
    inferred = infer_unit_contract(values)
    for key in ("unit_family", "unit_basis", "measure"):
        values[key] = _clean_token(values.get(key)) or inferred.get(key)
    if not values.get("source_key"):
        values["source_key"] = values.get("series_id") or values.get("label")
    return _drop_empty(to_json_safe(values))


def _looks_like_source_unit_record(value: Mapping[str, Any]) -> bool:
    return any(
        key in value
        for key in (
            "source_key",
            "series_id",
            "title",
            "units",
            "unit_family",
            "unit_basis",
        )
    )


def _looks_like_unit_comparison(value: Mapping[str, Any]) -> bool:
    return any(key in value for key in ("id", "comparison_id", "sources", "compatible", "status"))


def _is_useful_source_unit_metadata(record: Mapping[str, Any]) -> bool:
    return any(
        _has_value(record.get(key))
        for key in ("series_id", "title", "units", "unit_family", "measure")
    )


def _incompatible_reason(records: list[dict[str, Any]]) -> str | None:
    known = [
        record
        for record in records
        if _has_value(record.get("unit_family"))
    ]
    if len(known) < 2:
        return None

    families = {str(record.get("unit_family")).lower() for record in known}
    if len(families) > 1:
        return "source unit families differ"

    bases = {
        str(record.get("unit_basis")).lower()
        for record in known
        if _has_value(record.get("unit_basis"))
    }
    if len(bases) > 1:
        return "source unit bases differ"
    return None


def _comparison_error_message(comparison: Mapping[str, Any]) -> str:
    comparison_id = comparison.get("id") or comparison.get("comparison_id") or "unit comparison"
    reason = comparison.get("incompatible_reason") or "source units are incompatible"
    sources = comparison.get("sources")
    if isinstance(sources, list):
        labels = "; ".join(_source_label(source) for source in sources if isinstance(source, Mapping))
    else:
        labels = ""
    suffix = f": {labels}" if labels else ""
    return (
        f"{comparison_id} failed source-unit validation ({reason}){suffix}. "
        "Convert compared sources to a common unit and document the conversion, "
        "or remove the direct gap/divergence calculation."
    )


def _is_wage_currency_per_time(record: Mapping[str, Any]) -> bool:
    family = str(record.get("unit_family") or "").lower()
    measure = str(record.get("measure") or "").lower()
    text = f"{record.get('title') or ''} {record.get('units') or ''}".lower()
    return family == "currency_per_time" and (
        measure == "wage" or "wage" in text or "earnings" in text
    )


def _source_label(record: Mapping[str, Any]) -> str:
    key = record.get("source_key") or record.get("series_id") or record.get("title") or "source"
    units = record.get("units")
    basis = record.get("unit_basis")
    if units:
        return f"{key} ({units})"
    if basis:
        return f"{key} (per {basis})"
    return str(key)


def _source_identity(record: Mapping[str, Any]) -> str:
    for key in ("source_key", "series_id", "source_file", "title"):
        value = record.get(key)
        if _has_value(value):
            return str(value).strip()
    return ""


def _drop_empty(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): value for key, value in payload.items() if _has_value(value)}


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _clean_token(value: Any) -> str | None:
    text = _clean_text(value).lower().replace("-", "_").replace(" ", "_")
    return text or None


__all__ = [
    "attach_source_unit_metadata",
    "failed_unit_comparison_messages",
    "has_passing_mixed_wage_unit_comparison",
    "infer_unit_contract",
    "mixed_wage_period_sources",
    "normalize_source_unit_metadata",
    "normalize_unit_comparisons",
    "source_unit_metadata",
    "source_unit_metadata_from_csv",
    "source_unit_metadata_from_files",
    "unit_comparison",
]

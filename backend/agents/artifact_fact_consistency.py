"""Cross-artifact fact consistency checks for report handoffs."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations
import re
from typing import Any, Iterable


_CORRELATION_VALUE_KEYS = ("correlation", "corr", "c", "raw_value", "value")
_EXPLICIT_TRANSFORM_KEYS = (
    "transform_basis",
    "correlation_basis",
    "correlation_transform",
    "value_transform",
    "calculation_basis",
)
_TEMPORAL_ROW_KEYS = {
    "date",
    "period",
    "month",
    "quarter",
    "year",
    "timestamp",
    "time",
    "window",
    "rolling_window",
    "horizon",
    "scenario",
}
_CORRELATION_LABEL_RE = re.compile(
    r"\bcorrelation\s*\(\s*([^,()]+?)\s*,\s*([^,()]+?)\s*\)",
    re.IGNORECASE,
)
_CORRELATION_ID_RE = re.compile(
    r"(?:^|[.:/])(?:corr|correlation)[._:/-]([A-Za-z0-9]+)[._:/-]([A-Za-z0-9]+)$",
    re.IGNORECASE,
)
_PAIR_LABEL_SPLIT_RE = re.compile(r"\s*(?:/|\||,|\bvs\.?\b|\band\b)\s*", re.IGNORECASE)
_DEFAULT_CORRELATION_TOLERANCE = 0.005


@dataclass(frozen=True)
class _CorrelationObservation:
    pair_key: tuple[str, str]
    pair_display: tuple[str, str]
    value: float
    source: str
    transform_basis: str | None = None
    tolerance: float | None = None


def artifact_fact_consistency_dict(
    *,
    execution_summary: dict[str, Any] | None = None,
    charts: dict[str, Any] | list[Any] | None = None,
    report_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare compact quantitative facts repeated across sibling artifacts."""

    observations: list[_CorrelationObservation] = []
    if isinstance(execution_summary, dict):
        observations.extend(
            _extract_numeric_fact_correlations(
                execution_summary.get("numeric_facts"),
                "execution_summary.numeric_facts",
                _explicit_transform_basis(execution_summary),
            )
        )
        observations.extend(
            _extract_summary_matrix_correlations(
                execution_summary,
                "execution_summary",
                _explicit_transform_basis(execution_summary),
            )
        )

    chart_payload: dict[str, Any] | list[Any] | None = charts
    chart_source = "charts"
    if chart_payload is None and isinstance(report_data, dict):
        chart_payload = report_data.get("charts")
        chart_source = "report.charts"
    if chart_payload is not None:
        observations.extend(_extract_chart_correlations(chart_payload, chart_source))

    pair_observations: dict[tuple[str, str], list[_CorrelationObservation]] = defaultdict(list)
    for observation in observations:
        pair_observations[observation.pair_key].append(observation)

    mismatches: list[dict[str, Any]] = []
    skipped_comparisons: list[dict[str, Any]] = []
    checked_pairs: list[str] = []
    for pair_key in sorted(pair_observations):
        pair_items = pair_observations[pair_key]
        comparable_pair_seen = False
        for left, right in combinations(pair_items, 2):
            if _explicitly_different_transforms(left, right):
                skipped_comparisons.append(
                    {
                        "pair": list(left.pair_display),
                        "sources": [left.source, right.source],
                        "transform_bases": [
                            left.transform_basis,
                            right.transform_basis,
                        ],
                    }
                )
                continue
            comparable_pair_seen = True
            tolerance = max(
                _DEFAULT_CORRELATION_TOLERANCE,
                left.tolerance or 0.0,
                right.tolerance or 0.0,
            )
            if abs(left.value - right.value) <= tolerance:
                continue
            comparable = [
                item
                for item in pair_items
                if not _explicitly_different_transforms(left, item)
            ]
            values = [item.value for item in comparable]
            mismatch_tolerance = max(
                [_DEFAULT_CORRELATION_TOLERANCE]
                + [item.tolerance or 0.0 for item in comparable]
            )
            mismatches.append(
                {
                    "fact_type": "correlation",
                    "pair": list(left.pair_display),
                    "max_delta": round(max(values) - min(values), 6),
                    "tolerance": mismatch_tolerance,
                    "observations": [_observation_dict(item) for item in comparable],
                }
            )
            break
        if comparable_pair_seen:
            checked_pairs.append("/".join(pair_items[0].pair_display))

    return {
        "valid": not mismatches,
        "fact_type": "correlation",
        "checked_observation_count": len(observations),
        "checked_pairs": checked_pairs,
        "mismatches": mismatches,
        "skipped_comparisons": skipped_comparisons,
    }


def artifact_fact_consistency_blocker(consistency: dict[str, Any] | None) -> str | None:
    """Return a concise blocking message for the first artifact fact mismatch."""

    if not consistency or consistency.get("valid", True):
        return None
    mismatches = consistency.get("mismatches")
    if not isinstance(mismatches, list) or not mismatches:
        return None
    mismatch = mismatches[0]
    pair = mismatch.get("pair") if isinstance(mismatch, dict) else None
    pair_label = "/".join(str(item) for item in pair) if isinstance(pair, list) else "unknown"
    observations = mismatch.get("observations") if isinstance(mismatch, dict) else None
    details: list[str] = []
    if isinstance(observations, list):
        for observation in observations[:4]:
            if not isinstance(observation, dict):
                continue
            source = observation.get("source")
            value = observation.get("value")
            details.append(f"{source}={value}")
    tolerance = mismatch.get("tolerance") if isinstance(mismatch, dict) else None
    detail_text = "; ".join(details) if details else "conflicting observations"
    return (
        "artifact_fact_mismatch: conflicting correlation values for "
        f"{pair_label} ({detail_text}; tolerance={tolerance}). Regenerate "
        "quant artifacts so execution_summary.json, numeric_facts, and chart data "
        "share one basis or declare explicit transform_basis metadata."
    )


def _observation_dict(observation: _CorrelationObservation) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "source": observation.source,
        "pair": list(observation.pair_display),
        "value": observation.value,
    }
    if observation.transform_basis:
        payload["transform_basis"] = observation.transform_basis
    if observation.tolerance is not None:
        payload["tolerance"] = observation.tolerance
    return payload


def _extract_numeric_fact_correlations(
    value: Any,
    path: str,
    inherited_transform: str | None,
) -> Iterable[_CorrelationObservation]:
    if not isinstance(value, list):
        return []

    observations: list[_CorrelationObservation] = []
    for index, fact in enumerate(value):
        if not isinstance(fact, dict):
            continue
        pair = (
            _pair_from_mapping(fact)
            or _pair_from_correlation_identifier(fact.get("id"))
            or _pair_from_correlation_identifier(fact.get("fact_id"))
            or _pair_from_correlation_identifier(fact.get("source_key"))
            or _pair_from_correlation_label(fact.get("label"))
        )
        if pair is None:
            continue
        number = _first_finite_value(fact, ("raw_value", "value", "correlation", "corr", "c"))
        if number is None:
            continue
        observations.append(
            _build_observation(
                pair,
                number,
                f"{path}[{index}]",
                _explicit_transform_basis(fact, inherited_transform),
                _finite_float(fact.get("tolerance")),
            )
        )
    return observations


def _extract_summary_matrix_correlations(
    value: Any,
    path: str,
    inherited_transform: str | None,
) -> Iterable[_CorrelationObservation]:
    observations: list[_CorrelationObservation] = []
    if not isinstance(value, dict):
        return observations

    current_transform = _explicit_transform_basis(value, inherited_transform)
    for key, child in value.items():
        child_path = f"{path}.{key}"
        if key in {"corr", "correlation", "correlations", "correlation_matrix"}:
            observations.extend(_extract_matrix_observations(child, child_path, current_transform))
        if isinstance(child, dict):
            observations.extend(
                _extract_summary_matrix_correlations(child, child_path, current_transform)
            )
    return observations


def _extract_matrix_observations(
    value: Any,
    path: str,
    transform_basis: str | None,
) -> Iterable[_CorrelationObservation]:
    if not isinstance(value, dict) or not _looks_like_correlation_matrix(value):
        return []

    observations: list[_CorrelationObservation] = []
    for left, row in value.items():
        if not isinstance(row, dict):
            continue
        for right, raw_number in row.items():
            if _normalize_metric_name(left) == _normalize_metric_name(right):
                continue
            number = _finite_float(raw_number)
            if number is None:
                continue
            observations.append(
                _build_observation(
                    (str(left), str(right)),
                    number,
                    f"{path}.{left}.{right}",
                    transform_basis,
                    None,
                )
            )
    return observations


def _extract_chart_correlations(
    charts: dict[str, Any] | list[Any],
    source_prefix: str,
) -> Iterable[_CorrelationObservation]:
    observations: list[_CorrelationObservation] = []
    for chart_id, chart in _iter_chart_items(charts):
        chart_data = _as_mapping(chart)
        if not chart_data:
            continue
        chart_transform = _explicit_transform_basis(chart_data)
        data = chart_data.get("data")
        if not isinstance(data, list):
            continue
        for index, row in enumerate(data):
            if not isinstance(row, dict):
                continue
            pair = _pair_from_mapping(row)
            number = _first_finite_value(row, _CORRELATION_VALUE_KEYS)
            if pair is None or number is None or not _is_single_fact_row(row):
                continue
            observations.append(
                _build_observation(
                    pair,
                    number,
                    f"{source_prefix}.{chart_id}.data[{index}]",
                    _explicit_transform_basis(row, chart_transform),
                    _finite_float(row.get("tolerance")),
                )
            )
    return observations


def _iter_chart_items(charts: dict[str, Any] | list[Any]) -> Iterable[tuple[str, Any]]:
    if isinstance(charts, dict):
        for key, value in charts.items():
            yield str(key), value
        return
    if isinstance(charts, list):
        for index, value in enumerate(charts):
            chart = _as_mapping(value)
            chart_id = chart.get("id") if chart else None
            yield str(chart_id or index), value


def _as_mapping(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        if isinstance(dumped, dict):
            return dumped
    return None


def _looks_like_correlation_matrix(value: dict[str, Any]) -> bool:
    observed_pairs = 0
    for row in value.values():
        if not isinstance(row, dict):
            continue
        observed_pairs += sum(1 for item in row.values() if _finite_float(item) is not None)
        if observed_pairs >= 2:
            return True
    return False


def _pair_from_mapping(value: dict[str, Any]) -> tuple[str, str] | None:
    pair_keys = (
        ("var1", "var2"),
        ("metric1", "metric2"),
        ("metric_a", "metric_b"),
        ("series1", "series2"),
        ("series_a", "series_b"),
    )
    for left_key, right_key in pair_keys:
        left = _non_empty_string(value.get(left_key))
        right = _non_empty_string(value.get(right_key))
        if left and right:
            return left, right
    for key in ("pair", "metric_pair"):
        pair = _pair_from_pair_label(value.get(key))
        if pair is not None:
            return pair
    return None


def _pair_from_pair_label(value: Any) -> tuple[str, str] | None:
    text = _non_empty_string(value)
    if text is None:
        return None
    text = text.strip("()[]{} ")
    parts = [part.strip("()[]{} ") for part in _PAIR_LABEL_SPLIT_RE.split(text)]
    parts = [part for part in parts if part]
    if len(parts) != 2:
        return None
    return parts[0], parts[1]


def _pair_from_correlation_label(value: Any) -> tuple[str, str] | None:
    if not isinstance(value, str):
        return None
    match = _CORRELATION_LABEL_RE.search(value)
    if not match:
        return None
    return match.group(1), match.group(2)


def _pair_from_correlation_identifier(value: Any) -> tuple[str, str] | None:
    text = _non_empty_string(value)
    if text is None:
        return None
    match = _CORRELATION_ID_RE.search(text)
    if not match:
        return None
    return match.group(1), match.group(2)


def _build_observation(
    pair: tuple[str, str],
    value: float,
    source: str,
    transform_basis: str | None,
    tolerance: float | None,
) -> _CorrelationObservation:
    left_display = str(pair[0]).strip()
    right_display = str(pair[1]).strip()
    left_key = _normalize_metric_name(left_display)
    right_key = _normalize_metric_name(right_display)
    if right_key < left_key:
        left_key, right_key = right_key, left_key
    return _CorrelationObservation(
        pair_key=(left_key, right_key),
        pair_display=(left_display, right_display),
        value=value,
        source=source,
        transform_basis=transform_basis,
        tolerance=tolerance,
    )


def _first_finite_value(value: dict[str, Any], keys: Iterable[str]) -> float | None:
    for key in keys:
        number = _finite_float(value.get(key))
        if number is not None:
            return number
    return None


def _finite_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in {float("inf"), float("-inf")}:
        return None
    return number


def _explicit_transform_basis(
    value: dict[str, Any],
    inherited: str | None = None,
) -> str | None:
    for key in _EXPLICIT_TRANSFORM_KEYS:
        text = _non_empty_string(value.get(key))
        if text:
            return text
    return inherited


def _explicitly_different_transforms(
    left: _CorrelationObservation,
    right: _CorrelationObservation,
) -> bool:
    return (
        bool(left.transform_basis)
        and bool(right.transform_basis)
        and left.transform_basis != right.transform_basis
    )


def _is_single_fact_row(row: dict[str, Any]) -> bool:
    if "pair" in row or "metric_pair" in row:
        return True
    return not any(key in row for key in _TEMPORAL_ROW_KEYS)


def _normalize_metric_name(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value).strip()).upper()


def _non_empty_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None

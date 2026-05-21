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
_DEFAULT_SIGNAL_TOLERANCE = 0.005
_DEFAULT_CHART_NUMERIC_TOLERANCE = 0.005
_CHART_SIGNAL_DATE_KEYS = ("date", "period", "month", "timestamp", "time")


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

    signal_mismatches: list[dict[str, Any]] = []
    signal_checked_facts: list[str] = []
    if isinstance(execution_summary, dict):
        signal_checked_facts, signal_mismatches = _current_signal_fact_mismatches(
            execution_summary.get("current_signal_facts"),
            chart_payload,
            chart_source,
        )
    chart_numeric_checked_facts: list[str] = []
    chart_numeric_mismatches: list[dict[str, Any]] = []
    if isinstance(execution_summary, dict):
        (
            chart_numeric_checked_facts,
            chart_numeric_mismatches,
        ) = _chart_numeric_fact_mismatches(
            execution_summary.get("numeric_facts"),
            chart_payload,
            chart_source,
        )

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

    all_mismatches = [*mismatches, *signal_mismatches, *chart_numeric_mismatches]
    return {
        "valid": not all_mismatches,
        "fact_type": "correlation",
        "checked_observation_count": len(observations),
        "checked_pairs": checked_pairs,
        "mismatches": all_mismatches,
        "skipped_comparisons": skipped_comparisons,
        "checked_signal_facts": signal_checked_facts,
        "signal_mismatches": signal_mismatches,
        "checked_chart_numeric_facts": chart_numeric_checked_facts,
        "chart_numeric_mismatches": chart_numeric_mismatches,
    }


def artifact_fact_consistency_blocker(consistency: dict[str, Any] | None) -> str | None:
    """Return a concise blocking message for the first artifact fact mismatch."""

    if not consistency or consistency.get("valid", True):
        return None
    mismatches = consistency.get("mismatches")
    if not isinstance(mismatches, list) or not mismatches:
        return None
    mismatch = mismatches[0]
    if isinstance(mismatch, dict) and mismatch.get("fact_type") == "current_signal":
        return _current_signal_blocker(mismatch)
    if isinstance(mismatch, dict) and mismatch.get("fact_type") == "chart_numeric_fact":
        return _chart_numeric_fact_blocker(mismatch)
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


def _current_signal_blocker(mismatch: dict[str, Any]) -> str:
    signal_id = str(mismatch.get("signal_id") or "unknown")
    reason = str(mismatch.get("reason") or "mismatch")
    observations = mismatch.get("observations")
    details: list[str] = []
    if isinstance(observations, list):
        for observation in observations[:4]:
            if not isinstance(observation, dict):
                continue
            source = observation.get("source")
            value = observation.get("value")
            triggered = observation.get("triggered")
            threshold = observation.get("threshold")
            pieces = [f"{source}={value}"]
            if threshold is not None:
                pieces.append(f"threshold={threshold}")
            if triggered is not None:
                pieces.append(f"triggered={triggered}")
            details.append(", ".join(str(piece) for piece in pieces if piece))
    detail_text = "; ".join(details) if details else "conflicting observations"
    return (
        "artifact_fact_mismatch: conflicting current signal fact for "
        f"{signal_id} ({reason}: {detail_text}). Regenerate quant artifacts so "
        "execution_summary.json current_signal_facts and chart data share one "
        "threshold basis."
    )


def _chart_numeric_fact_blocker(mismatch: dict[str, Any]) -> str:
    fact_id = str(mismatch.get("fact_id") or "unknown")
    reason = str(mismatch.get("reason") or "mismatch")
    observations = mismatch.get("observations")
    details: list[str] = []
    if isinstance(observations, list):
        for observation in observations[:4]:
            if not isinstance(observation, dict):
                continue
            source = observation.get("source")
            value = observation.get("value")
            as_of_date = observation.get("as_of_date")
            pieces = [f"{source}={value}"]
            if as_of_date is not None:
                pieces.append(f"as_of={as_of_date}")
            details.append(", ".join(str(piece) for piece in pieces if piece))
    detail_text = "; ".join(details) if details else "conflicting observations"
    return (
        "artifact_fact_mismatch: conflicting chart-linked numeric fact for "
        f"{fact_id} ({reason}: {detail_text}). Regenerate quant artifacts so "
        "execution_summary.json numeric_facts and charts.json latest data points "
        "share one current value."
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


def _current_signal_fact_mismatches(
    value: Any,
    charts: dict[str, Any] | list[Any] | None,
    chart_source: str,
) -> tuple[list[str], list[dict[str, Any]]]:
    if not isinstance(value, list):
        return [], []

    checked: list[str] = []
    mismatches: list[dict[str, Any]] = []
    for index, fact in enumerate(value):
        source = f"execution_summary.current_signal_facts[{index}]"
        if not isinstance(fact, dict):
            mismatches.append(
                _signal_mismatch(
                    signal_id=f"current_signal_facts[{index}]",
                    reason="malformed_current_signal_fact",
                    observations=[{"source": source, "value": None}],
                )
            )
            continue
        signal_id = str(fact.get("signal_id") or f"current_signal_facts[{index}]")
        checked.append(signal_id)
        row_observation = _signal_fact_observation(fact, source)
        direction = str(fact.get("direction") or "").strip().lower()
        value_number = _finite_float(fact.get("value"))
        threshold = _finite_float(fact.get("threshold"))
        distance = _finite_float(fact.get("threshold_distance"))
        tolerance = _finite_float(fact.get("tolerance"))
        if tolerance is None:
            tolerance = _DEFAULT_SIGNAL_TOLERANCE
        triggered = fact.get("triggered")
        if (
            direction not in {"high", "low"}
            or value_number is None
            or threshold is None
            or distance is None
            or not isinstance(triggered, bool)
        ):
            mismatches.append(
                _signal_mismatch(
                    signal_id=signal_id,
                    reason="malformed_current_signal_fact",
                    observations=[row_observation],
                    tolerance=tolerance,
                )
            )
            continue

        expected_triggered = (
            value_number >= threshold
            if direction == "high"
            else value_number <= threshold
        )
        if triggered is not expected_triggered:
            mismatches.append(
                _signal_mismatch(
                    signal_id=signal_id,
                    reason="trigger_state_mismatch",
                    observations=[
                        row_observation,
                        {
                            "source": "threshold_math",
                            "value": value_number,
                            "threshold": threshold,
                            "direction": direction,
                            "triggered": expected_triggered,
                        },
                    ],
                    tolerance=tolerance,
                )
            )
        expected_distance = (
            value_number - threshold
            if direction == "high"
            else threshold - value_number
        )
        if abs(distance - expected_distance) > max(tolerance, 1e-9):
            mismatches.append(
                _signal_mismatch(
                    signal_id=signal_id,
                    reason="threshold_distance_mismatch",
                    observations=[
                        row_observation,
                        {
                            "source": "threshold_math",
                            "value": expected_distance,
                            "threshold": threshold,
                            "direction": direction,
                            "triggered": expected_triggered,
                        },
                    ],
                    tolerance=tolerance,
                )
            )

        if charts is None:
            continue
        chart_id = _non_empty_string(fact.get("chart_id"))
        data_key = _non_empty_string(fact.get("data_key"))
        if not chart_id or not data_key:
            mismatches.append(
                _signal_mismatch(
                    signal_id=signal_id,
                    reason="missing_chart_reference",
                    observations=[row_observation],
                    tolerance=tolerance,
                )
            )
            continue
        chart_observation = _latest_chart_signal_observation(
            charts,
            chart_id=chart_id,
            data_key=data_key,
            as_of_date=_non_empty_string(fact.get("as_of_date")),
            source_prefix=chart_source,
        )
        if chart_observation is None:
            mismatches.append(
                _signal_mismatch(
                    signal_id=signal_id,
                    reason="chart_reference_missing",
                    observations=[row_observation],
                    tolerance=tolerance,
                )
            )
            continue
        chart_value = _finite_float(chart_observation.get("value"))
        if chart_value is None or abs(chart_value - value_number) > max(tolerance, 1e-9):
            mismatches.append(
                _signal_mismatch(
                    signal_id=signal_id,
                    reason="chart_latest_value_mismatch",
                    observations=[row_observation, chart_observation],
                    tolerance=tolerance,
                )
            )
    return checked, mismatches


def _chart_numeric_fact_mismatches(
    value: Any,
    charts: dict[str, Any] | list[Any] | None,
    chart_source: str,
) -> tuple[list[str], list[dict[str, Any]]]:
    if not isinstance(value, list) or charts is None:
        return [], []

    checked: list[str] = []
    mismatches: list[dict[str, Any]] = []
    for index, fact in enumerate(value):
        if not isinstance(fact, dict):
            continue
        chart_id = _non_empty_string(fact.get("chart_id"))
        data_key = _non_empty_string(fact.get("data_key"))
        if not chart_id and not data_key:
            continue

        fact_id = str(fact.get("id") or f"numeric_facts[{index}]")
        checked.append(fact_id)
        source = f"execution_summary.numeric_facts[{index}]"
        fact_observation = _numeric_fact_chart_observation(fact, source)
        tolerance = _finite_float(fact.get("tolerance"))
        if tolerance is None:
            tolerance = _DEFAULT_CHART_NUMERIC_TOLERANCE
        value_number = _finite_float(fact.get("raw_value", fact.get("value")))
        if not chart_id or not data_key or value_number is None:
            mismatches.append(
                _chart_numeric_mismatch(
                    fact_id=fact_id,
                    reason="malformed_chart_numeric_fact",
                    observations=[fact_observation],
                    tolerance=tolerance,
                )
            )
            continue

        chart_observation = _latest_chart_numeric_observation(
            charts,
            chart_id=chart_id,
            data_key=data_key,
            source_prefix=chart_source,
        )
        if chart_observation is None:
            mismatches.append(
                _chart_numeric_mismatch(
                    fact_id=fact_id,
                    reason="chart_reference_missing",
                    observations=[fact_observation],
                    tolerance=tolerance,
                )
            )
            continue
        chart_value = _finite_float(chart_observation.get("value"))
        if chart_value is None or abs(chart_value - value_number) > max(tolerance, 1e-9):
            mismatches.append(
                _chart_numeric_mismatch(
                    fact_id=fact_id,
                    reason="chart_latest_value_mismatch",
                    observations=[fact_observation, chart_observation],
                    tolerance=tolerance,
                )
            )
            continue

        fact_date = _non_empty_string(fact.get("as_of_date"))
        chart_date = _non_empty_string(chart_observation.get("as_of_date"))
        if fact_date and chart_date and not _dates_match(fact_date, chart_date):
            mismatches.append(
                _chart_numeric_mismatch(
                    fact_id=fact_id,
                    reason="chart_latest_date_mismatch",
                    observations=[fact_observation, chart_observation],
                    tolerance=tolerance,
                )
            )
    return checked, mismatches


def _numeric_fact_chart_observation(
    fact: dict[str, Any],
    source: str,
) -> dict[str, Any]:
    observation = {
        "source": source,
        "value": _finite_float(fact.get("raw_value", fact.get("value"))),
    }
    for key in ("as_of_date", "chart_id", "data_key", "source_key"):
        if fact.get(key) is not None:
            observation[key] = fact.get(key)
    return observation


def _chart_numeric_mismatch(
    *,
    fact_id: str,
    reason: str,
    observations: list[dict[str, Any]],
    tolerance: float | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "fact_type": "chart_numeric_fact",
        "fact_id": fact_id,
        "reason": reason,
        "observations": observations,
    }
    if tolerance is not None:
        payload["tolerance"] = tolerance
    return payload


def _signal_fact_observation(fact: dict[str, Any], source: str) -> dict[str, Any]:
    observation = {
        "source": source,
        "value": _finite_float(fact.get("value")),
        "threshold": _finite_float(fact.get("threshold")),
        "direction": fact.get("direction"),
        "triggered": fact.get("triggered"),
        "threshold_distance": _finite_float(fact.get("threshold_distance")),
    }
    for key in ("as_of_date", "chart_id", "data_key", "source_key"):
        if fact.get(key) is not None:
            observation[key] = fact.get(key)
    return observation


def _signal_mismatch(
    *,
    signal_id: str,
    reason: str,
    observations: list[dict[str, Any]],
    tolerance: float | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "fact_type": "current_signal",
        "signal_id": signal_id,
        "reason": reason,
        "observations": observations,
    }
    if tolerance is not None:
        payload["tolerance"] = tolerance
    return payload


def _latest_chart_signal_observation(
    charts: dict[str, Any] | list[Any],
    *,
    chart_id: str,
    data_key: str,
    as_of_date: str | None,
    source_prefix: str,
) -> dict[str, Any] | None:
    for candidate_id, chart in _iter_chart_items(charts):
        if candidate_id != chart_id:
            continue
        chart_data = _as_mapping(chart)
        if not chart_data:
            return None
        data = chart_data.get("data")
        if not isinstance(data, list):
            return None
        matched = _latest_chart_signal_row(
            data,
            data_key=data_key,
            as_of_date=as_of_date,
        )
        if matched is None:
            return None
        index, row, value = matched
        observation = {
            "source": f"{source_prefix}.{chart_id}.data[{index}].{data_key}",
            "value": value,
        }
        row_date = _chart_row_date(row)
        if row_date is not None:
            observation["as_of_date"] = row_date
        return observation
    return None


def _latest_chart_numeric_observation(
    charts: dict[str, Any] | list[Any],
    *,
    chart_id: str,
    data_key: str,
    source_prefix: str,
) -> dict[str, Any] | None:
    for candidate_id, chart in _iter_chart_items(charts):
        if candidate_id != chart_id:
            continue
        chart_data = _as_mapping(chart)
        if not chart_data:
            return None
        data = chart_data.get("data")
        if not isinstance(data, list):
            return None
        matched = _latest_chart_signal_row(
            data,
            data_key=data_key,
            as_of_date=None,
        )
        if matched is None:
            return None
        index, row, value = matched
        observation = {
            "source": f"{source_prefix}.{chart_id}.data[{index}].{data_key}",
            "value": value,
        }
        row_date = _chart_row_date(row)
        if row_date is not None:
            observation["as_of_date"] = row_date
        return observation
    return None


def _latest_chart_signal_row(
    rows: list[Any],
    *,
    data_key: str,
    as_of_date: str | None,
) -> tuple[int, dict[str, Any], float] | None:
    if as_of_date:
        for index in range(len(rows) - 1, -1, -1):
            row = rows[index]
            if not isinstance(row, dict) or not _chart_row_matches_date(row, as_of_date):
                continue
            value = _finite_float(row.get(data_key))
            if value is not None:
                return index, row, value
    for index in range(len(rows) - 1, -1, -1):
        row = rows[index]
        if not isinstance(row, dict):
            continue
        value = _finite_float(row.get(data_key))
        if value is not None:
            return index, row, value
    return None


def _chart_row_matches_date(row: dict[str, Any], as_of_date: str) -> bool:
    expected = str(as_of_date).strip()
    if not expected:
        return False
    for key in _CHART_SIGNAL_DATE_KEYS:
        value = row.get(key)
        if value is None:
            continue
        actual = str(value).strip()
        if actual == expected or actual[:10] == expected[:10]:
            return True
    return False


def _chart_row_date(row: dict[str, Any]) -> str | None:
    for key in _CHART_SIGNAL_DATE_KEYS:
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _dates_match(left: str, right: str) -> bool:
    left_text = str(left).strip()
    right_text = str(right).strip()
    return left_text == right_text or left_text[:10] == right_text[:10]


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

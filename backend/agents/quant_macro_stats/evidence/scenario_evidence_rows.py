"""Scenario evidence and recession-regime helper functions."""
from collections.abc import Iterable
from typing import Any

import numpy as np
import pandas as pd

from .._utils import (
    DEFAULT_REGIME_CATEGORIES,
    DEFAULT_REGIME_WEIGHTS,
    METHOD_RECESSION_REGIME_CLASSIFIER,
    _finite_float,
    _iso_date,
    _require_columns,
)


def _finite_dict(values: dict[str, Any]) -> dict[str, float]:
    cleaned: dict[str, float] = {}
    for key, value in values.items():
        numeric = _finite_float(value)
        if numeric is not None:
            cleaned[str(key)] = numeric
    return cleaned


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        candidates = [value]
    elif isinstance(value, Iterable) and not isinstance(value, dict):
        candidates = [str(item) for item in value]
    else:
        candidates = [str(value)]
    return [item.strip() for item in candidates if item.strip()]


def normalize_scenario_evidence_rows(
    rows: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Normalize caller-composed scenario evidence rows without choosing report shape.

    The helper validates local evidence rows only. It does not require base,
    bull, and bear rows, does not choose table columns, and does not create a
    top-level report contract. ``analysis.py`` owns any report-facing scenario
    labels, prose, and table layout.
    """

    if rows is None:
        raise ValueError("scenario evidence rows are required")
    normalized: list[dict[str, Any]] = []
    text_fields = (
        "metric",
        "indicator",
        "source_key",
        "direction",
        "basis",
        "confidence",
        "note",
        "notes",
    )
    list_fields = ("evidence", "drivers", "inputs")
    numeric_fields = (
        "score",
        "value",
        "current_value",
        "baseline_value",
        "delta",
        "threshold_value",
        "reference_value",
        "weight",
    )
    for raw in rows:
        if not isinstance(raw, dict):
            raise ValueError("each scenario evidence row must be a JSON object")
        scenario = str(raw.get("scenario", raw.get("name", ""))).strip()
        if not scenario:
            raise ValueError("each scenario evidence row requires `scenario` or `name`")

        row: dict[str, Any] = {"scenario": scenario}
        for field in text_fields:
            value = raw.get(field)
            if value is not None and str(value).strip():
                row[field] = str(value).strip()
        for field in list_fields:
            values = _string_list(raw.get(field))
            if values:
                row[field] = values
        for field in numeric_fields:
            numeric = _finite_float(raw.get(field))
            if numeric is not None:
                row[field] = numeric

        if len(row) == 1:
            raise ValueError(
                "each scenario evidence row needs at least one metric, score, "
                "value, note, driver, or evidence field"
            )
        normalized.append(row)

    if not normalized:
        raise ValueError("scenario evidence rows must include at least one row")
    return normalized


def _score_indicator_value(
    value: Any,
    *,
    favorable_when: str = "high",
    weak_threshold: float = -0.5,
    strong_threshold: float = 0.5,
) -> float | None:
    numeric = _finite_float(value)
    if numeric is None:
        return None
    if favorable_when not in {"high", "low"}:
        raise ValueError("indicator favorable_when must be 'high' or 'low'")
    weak = _finite_float(weak_threshold)
    strong = _finite_float(strong_threshold)
    if weak is None or strong is None or weak == strong:
        raise ValueError(
            "indicator thresholds must be finite and weak_threshold < strong_threshold"
        )
    if weak > strong:
        weak, strong = strong, weak

    if numeric <= weak:
        score = -1.0
    elif numeric >= strong:
        score = 1.0
    else:
        midpoint = (weak + strong) / 2
        half_range = (strong - weak) / 2
        score = (numeric - midpoint) / half_range
    if favorable_when == "low":
        score *= -1
    return float(np.clip(score, -1.0, 1.0))


def _category_scores_from_row(
    row: pd.Series,
    indicator_specs: Iterable[dict[str, Any]],
) -> tuple[dict[str, float], list[dict[str, Any]], list[dict[str, str]]]:
    grouped: dict[str, list[tuple[float, float]]] = {}
    evidence: list[dict[str, Any]] = []
    missing: list[dict[str, str]] = []
    for raw_spec in indicator_specs:
        spec = dict(raw_spec)
        name = str(spec.get("name") or spec.get("column") or "").strip()
        column = str(spec.get("column") or name).strip()
        category = str(spec.get("category") or name).strip().lower()
        if not name or not column or not category:
            raise ValueError("each indicator spec requires name, column, and category")
        if column not in row.index:
            missing.append({"indicator": name, "category": category, "reason": "missing_column"})
            continue
        raw_value = row[column]
        raw_score = _score_indicator_value(
            raw_value,
            favorable_when=str(spec.get("favorable_when", "high")),
            weak_threshold=float(spec.get("weak_threshold", -0.5)),
            strong_threshold=float(spec.get("strong_threshold", 0.5)),
        )
        if raw_score is None:
            missing.append({"indicator": name, "category": category, "reason": "missing_value"})
            continue
        indicator_weight = float(spec.get("indicator_weight", 1.0))
        if not np.isfinite(indicator_weight) or indicator_weight <= 0:
            raise ValueError("indicator_weight must be a positive finite number")
        grouped.setdefault(category, []).append((raw_score, indicator_weight))
        evidence.append(
            {
                "indicator": name,
                "category": category,
                "value": _finite_float(raw_value),
                "score": _finite_float(raw_score),
                "weight": _finite_float(indicator_weight),
                "signal": "supportive"
                if raw_score >= 0.25
                else "weak"
                if raw_score <= -0.25
                else "neutral",
                "rationale": str(spec.get("rationale", "")).strip()
                or "Positive score supports expansion; negative score points to slowdown or recession risk.",
            }
        )

    category_scores: dict[str, float] = {}
    for category, values in grouped.items():
        weight_sum = sum(weight for _, weight in values)
        if weight_sum > 0:
            category_scores[category] = sum(score * weight for score, weight in values) / weight_sum
    return category_scores, evidence, missing


def _weighted_regime_score(
    category_scores: dict[str, float],
    category_weights: dict[str, float],
) -> tuple[float | None, dict[str, float]]:
    usable_weights = {
        category: float(category_weights.get(category, 0.0))
        for category in category_scores
        if np.isfinite(float(category_weights.get(category, 0.0)))
        and float(category_weights.get(category, 0.0)) > 0
    }
    total = sum(usable_weights.values())
    if total <= 0:
        return None, {}
    normalized = {category: weight / total for category, weight in usable_weights.items()}
    score = sum(category_scores[category] * weight for category, weight in normalized.items())
    return _finite_float(score), normalized


def _classify_regime(
    score: float,
    momentum: float | None,
    *,
    recession_flag: bool,
    weak_categories: int,
) -> str:
    if recession_flag or (score <= -0.45 and weak_categories >= 3):
        return "recession"
    if momentum is not None and momentum >= 0.25 and score < 0.35:
        return "recovery"
    if score >= 0.25 and momentum is not None and momentum >= 0.20:
        return "reacceleration"
    if score <= 0.20 and ((momentum is not None and momentum <= -0.15) or weak_categories >= 2):
        return "slowdown"
    return "expansion"


def _regime_analog_rows(
    scored: pd.DataFrame,
    *,
    date_col: str,
    category_columns: list[str],
    latest_index: int,
    limit: int,
) -> list[dict[str, Any]]:
    if latest_index <= 0 or not category_columns:
        return []
    latest_vector = scored.loc[latest_index, category_columns].to_numpy(dtype=float)
    analogs: list[dict[str, Any]] = []
    for index, row in scored.iloc[:latest_index].iterrows():
        candidate = row[category_columns].to_numpy(dtype=float)
        if np.isnan(candidate).any() or np.isnan(latest_vector).any():
            continue
        distance = float(np.linalg.norm(candidate - latest_vector))
        analogs.append(
            {
                "date": _iso_date(row[date_col]),
                "distance": _finite_float(distance),
                "regime_score": _finite_float(row["_regime_score"]),
                "regime": row.get("_regime"),
            }
        )
    return sorted(
        analogs, key=lambda item: item["distance"] if item["distance"] is not None else np.inf
    )[:limit]


def _regime_summary_row(payload: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "date",
        "status",
        "regime",
        "regime_score",
        "score_momentum",
        "category_scores",
        "category_weights",
        "weak_categories",
        "recession_indicator",
        "recession_indicator_active",
        "available_categories",
    )
    return {key: payload[key] for key in keys if key in payload}


def _missing_indicator_rows(payloads: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for payload in payloads:
        date = payload.get("date")
        missing = payload.get("missing_indicator_rows")
        if not isinstance(missing, list):
            continue
        for item in missing:
            if isinstance(item, dict):
                rows.append({"date": date, **item})
    return rows


def classify_recession_regime(
    data: pd.DataFrame,
    *,
    date_col: str = "date",
    indicator_specs: Iterable[dict[str, Any]] | None = None,
    category_weights: dict[str, float] | None = None,
    recession_col: str | None = None,
    momentum_periods: int = 3,
    min_categories: int = 3,
    analog_count: int = 3,
) -> dict[str, Any]:
    """
    Classify the latest macro regime with transparent local scoring.

    Inputs should be local, already-fetched observations. By default the helper
    treats columns named rates, labor, inflation, credit, and output as
    pre-scored category signals where +1 supports expansion and -1 signals
    contraction/stress. Custom ``indicator_specs`` can score raw columns with
    explicit weak/strong thresholds and high/low favorable direction.
    """

    if data is None or data.empty:
        raise ValueError("data must include at least one local observation")
    if momentum_periods < 1:
        raise ValueError("momentum_periods must be at least 1")
    if min_categories < 1:
        raise ValueError("min_categories must be at least 1")
    if analog_count < 0:
        raise ValueError("analog_count must be non-negative")

    weights = {**DEFAULT_REGIME_WEIGHTS, **(category_weights or {})}
    if indicator_specs is None:
        specs = [
            {
                "name": category,
                "column": category,
                "category": category,
                "weak_threshold": -0.5,
                "strong_threshold": 0.5,
                "favorable_when": "high",
            }
            for category in DEFAULT_REGIME_CATEGORIES
        ]
    else:
        specs = list(indicator_specs)
        if not specs:
            raise ValueError("indicator_specs must include at least one indicator when provided")

    frame = data.copy()
    _require_columns(frame, [date_col])
    frame[date_col] = pd.to_datetime(frame[date_col], errors="coerce")
    frame = frame.dropna(subset=[date_col]).sort_values(date_col).reset_index(drop=True)
    if frame.empty:
        raise ValueError("data has no usable dates after cleaning")

    scored_rows: list[dict[str, Any]] = []
    payloads: list[dict[str, Any]] = []
    for row_index, row in frame.iterrows():
        category_scores, evidence_rows, missing_rows = _category_scores_from_row(row, specs)
        score, normalized_weights = _weighted_regime_score(category_scores, weights)
        if score is None or len(category_scores) < min_categories:
            payload = {
                "date": _iso_date(row[date_col]),
                "status": "insufficient_categories",
                "regime": "unclassified",
                "regime_score": score,
                "available_categories": sorted(category_scores),
                "missing_indicator_rows": missing_rows,
                "regime_evidence_rows": evidence_rows,
            }
        else:
            prior_position = row_index - momentum_periods
            prior_score = (
                scored_rows[prior_position]["_regime_score"]
                if prior_position >= 0
                and scored_rows[prior_position].get("_regime_score") is not None
                else None
            )
            momentum = _finite_float(score - prior_score) if prior_score is not None else None
            recession_value = (
                _finite_float(row[recession_col]) if recession_col in row.index else None
            )
            recession_flag = bool(
                recession_col and recession_value is not None and recession_value > 0
            )
            weak_categories = sum(1 for value in category_scores.values() if value <= -0.25)
            regime = _classify_regime(
                score,
                momentum,
                recession_flag=recession_flag,
                weak_categories=weak_categories,
            )
            payload = {
                "date": _iso_date(row[date_col]),
                "status": "ok",
                "regime": regime,
                "regime_score": score,
                "score_momentum": momentum,
                "category_scores": {
                    key: _finite_float(value) for key, value in category_scores.items()
                },
                "category_weights": normalized_weights,
                "weak_categories": weak_categories,
                "recession_indicator": recession_col if recession_col else None,
                "recession_indicator_active": recession_flag if recession_col else None,
                "available_categories": sorted(category_scores),
                "missing_indicator_rows": missing_rows,
                "regime_evidence_rows": evidence_rows,
            }

        scored_row = {
            date_col: row[date_col],
            "_regime_score": payload["regime_score"],
            "_regime": payload["regime"],
            **{f"_category_{key}": value for key, value in category_scores.items()},
        }
        scored_rows.append(scored_row)
        payloads.append(payload)

    assert payloads  # for type checkers
    selected_index = len(payloads) - 1
    latest_payload = payloads[selected_index]
    for index in range(len(payloads) - 1, -1, -1):
        if payloads[index]["status"] == "ok":
            selected_index = index
            latest_payload = payloads[index]
            break
    scored = pd.DataFrame(scored_rows)
    category_columns = [
        column
        for column in scored.columns
        if column.startswith("_category_") and pd.notna(scored[column].iloc[selected_index])
    ]
    analog_rows = (
        _regime_analog_rows(
            scored,
            date_col=date_col,
            category_columns=category_columns,
            latest_index=selected_index,
            limit=analog_count,
        )
        if latest_payload["status"] == "ok"
        else []
    )

    return {
        "current_regime_row": _regime_summary_row(latest_payload),
        "regime_evidence_rows": latest_payload.get("regime_evidence_rows", []),
        "regime_history_rows": [_regime_summary_row(payload) for payload in payloads],
        "regime_analog_rows": analog_rows,
        "missing_indicator_rows": _missing_indicator_rows(payloads),
        "regime_design": {
            "method": METHOD_RECESSION_REGIME_CLASSIFIER,
            "indicator_count": len(specs),
            "min_categories": min_categories,
            "momentum_periods": momentum_periods,
            "analog_count": analog_count,
            "category_weights": latest_payload.get("category_weights", {}),
            "selected_date": latest_payload.get("date"),
            "selected_row_status": latest_payload.get("status"),
            "latest_observation_date": payloads[-1].get("date"),
            "latest_observation_status": payloads[-1].get("status"),
            "used_latest_usable_row": selected_index != len(payloads) - 1,
        },
        "methods_used": [METHOD_RECESSION_REGIME_CLASSIFIER],
    }

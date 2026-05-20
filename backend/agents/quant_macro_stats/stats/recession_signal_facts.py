"""Canonical recession-signal fact helpers."""

from __future__ import annotations

from typing import Any

import pandas as pd

from .._utils import (
    METHOD_SAHM_RULE_SIGNAL,
    _as_ordered_frame,
    _finite_float,
    _iso_date,
)
from ..artifacts.numeric_fact_contracts import numeric_fact


def sahm_rule_signal(
    data: pd.DataFrame,
    *,
    unemployment_col: str = "UNRATE",
    date_col: str = "date",
    signal_id: str = "sahm_rule",
    threshold: float = 0.5,
    source_key: str | None = None,
    chart_id: str = "sahm_rule_signal",
    data_key: str = "sahm_gap",
    precision: int = 3,
    tolerance: float = 0.005,
) -> dict[str, Any]:
    """Compute the Sahm rule as a current threshold-signal contract.

    The signal is the 3-month average unemployment rate minus the minimum
    3-month average over the prior 12 months. The helper returns chart-ready
    rows, a scalar numeric fact, and a ``current_signal_facts`` row that gates
    threshold and chart consistency downstream.
    """

    frame = _as_ordered_frame(data, date_col, [unemployment_col])
    frame = frame.dropna(subset=[unemployment_col]).reset_index(drop=True)
    source = str(source_key or unemployment_col)
    threshold_value = _finite_float(threshold)
    if threshold_value is None:
        raise ValueError("threshold must be a finite number")

    if frame.empty:
        return {
            "status": "insufficient_observations",
            "signal_score_rows": [],
            "current_signal_facts": [],
            "numeric_facts": [],
            "signal_design": _sahm_design(
                unemployment_col=unemployment_col,
                date_col=date_col,
                signal_id=signal_id,
                threshold=threshold_value,
                source_key=source,
                chart_id=chart_id,
                data_key=data_key,
            ),
            "methods_used": [METHOD_SAHM_RULE_SIGNAL],
            "limitations": [
                "Sahm rule signal skipped because no finite unemployment observations were available."
            ],
        }

    frame["_unrate_3m_avg"] = frame[unemployment_col].rolling(
        window=3,
        min_periods=3,
    ).mean()
    frame["_sahm_baseline_3m_min"] = frame["_unrate_3m_avg"].shift(1).rolling(
        window=12,
        min_periods=1,
    ).min()
    frame["_sahm_gap"] = frame["_unrate_3m_avg"] - frame["_sahm_baseline_3m_min"]

    all_rows = [
        _sahm_row(
            row,
            date_col=date_col,
            unemployment_col=unemployment_col,
            threshold=threshold_value,
            data_key=data_key,
        )
        for _, row in frame.iterrows()
    ]
    rows = [row for row in all_rows if row.get(data_key) is not None]
    valid_current = frame.dropna(subset=["_sahm_gap"])
    if valid_current.empty:
        return {
            "status": "insufficient_observations",
            "signal_score_rows": rows,
            "current_signal_facts": [],
            "numeric_facts": [],
            "signal_design": _sahm_design(
                unemployment_col=unemployment_col,
                date_col=date_col,
                signal_id=signal_id,
                threshold=threshold_value,
                source_key=source,
                chart_id=chart_id,
                data_key=data_key,
            ),
            "methods_used": [METHOD_SAHM_RULE_SIGNAL],
            "limitations": [
                "Sahm rule signal requires a 3-month unemployment average and a prior 12-month baseline."
            ],
        }

    latest = valid_current.iloc[-1]
    value = _finite_float(latest["_sahm_gap"])
    as_of_date = _iso_date(latest[date_col])
    triggered = bool(value is not None and value >= threshold_value)
    distance = _finite_float(value - threshold_value if value is not None else None)
    current_signal = {
        "signal_id": str(signal_id),
        "label": "Sahm rule unemployment gap",
        "value": value,
        "threshold": threshold_value,
        "direction": "high",
        "triggered": triggered,
        "threshold_distance": distance,
        "as_of_date": as_of_date,
        "source_key": source,
        "chart_id": str(chart_id),
        "data_key": str(data_key),
        "unit": "percentage_point",
        "tolerance": float(tolerance),
        "method": METHOD_SAHM_RULE_SIGNAL,
    }
    latest_fact = numeric_fact(
        fact_id=f"{signal_id}.latest_gap",
        label="Sahm rule unemployment gap",
        raw_value=value,
        unit="percentage_point",
        precision=precision,
        tolerance=tolerance,
        source_key=f"{source}.{data_key}",
        as_of_date=as_of_date,
        subject="US unemployment",
        metric=data_key,
        operation="three_month_average_minus_prior_12_month_minimum",
        transform_basis="3-month unemployment average minus prior 12-month minimum",
    )
    return {
        "status": "ok",
        "signal_score_rows": rows,
        "current_signal_facts": [current_signal],
        "numeric_facts": [latest_fact] if latest_fact else [],
        "signal_design": _sahm_design(
            unemployment_col=unemployment_col,
            date_col=date_col,
            signal_id=signal_id,
            threshold=threshold_value,
            source_key=source,
            chart_id=chart_id,
            data_key=data_key,
        ),
        "methods_used": [METHOD_SAHM_RULE_SIGNAL],
        "limitations": [
            "Sahm rule uses revised unemployment data unless the local input panel is vintage data.",
            "The threshold is a recession-start warning rule, not a probability estimate.",
        ],
    }


def _sahm_design(
    *,
    unemployment_col: str,
    date_col: str,
    signal_id: str,
    threshold: float,
    source_key: str,
    chart_id: str,
    data_key: str,
) -> dict[str, Any]:
    return {
        "method": METHOD_SAHM_RULE_SIGNAL,
        "signal_id": str(signal_id),
        "date_col": str(date_col),
        "unemployment_col": str(unemployment_col),
        "source_key": str(source_key),
        "chart_id": str(chart_id),
        "data_key": str(data_key),
        "threshold": threshold,
        "direction": "high",
        "formula": "unemployment_3m_avg - min(unemployment_3m_avg over prior 12 months)",
    }


def _sahm_row(
    row: pd.Series,
    *,
    date_col: str,
    unemployment_col: str,
    threshold: float,
    data_key: str,
) -> dict[str, Any]:
    value = _finite_float(row.get("_sahm_gap"))
    return {
        "date": _iso_date(row.get(date_col)),
        "unemployment_rate": _finite_float(row.get(unemployment_col)),
        "unemployment_3m_avg": _finite_float(row.get("_unrate_3m_avg")),
        "sahm_baseline_3m_min": _finite_float(row.get("_sahm_baseline_3m_min")),
        str(data_key): value,
        "score": value,
        "threshold": threshold,
        "above_threshold": bool(value is not None and value >= threshold),
    }


__all__ = ["sahm_rule_signal"]

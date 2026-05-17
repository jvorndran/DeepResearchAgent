"""Reusable forecast evidence row helpers for quant scripts."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

import numpy as np
import pandas as pd

from .._utils import (
    finite_number as _finite,
    latest_finite_value,
    month_label as _date_label,
    rounded_number as _round,
)


def _date_month(value: Any) -> str | None:
    try:
        return _date_label(value)
    except (TypeError, ValueError):
        text = str(value or "").strip()
        return text[:7] if len(text) >= 7 and text[4:5] == "-" else text or None


def _horizon_int(value: Any) -> int | None:
    number = _finite(value)
    if number is None:
        return None
    horizon = int(number)
    return horizon if horizon > 0 else None


def _rows_from(value: Any, key: str | None = None) -> list[Mapping[str, Any]]:
    source = value.get(key) if key and isinstance(value, Mapping) else value
    if (
        key == "forecast_table"
        and isinstance(value, Mapping)
        and not source
        and isinstance(value.get("forecast_rows"), Iterable)
    ):
        source = value.get("forecast_rows")
    if not isinstance(source, Iterable) or isinstance(source, (str, bytes, Mapping)):
        return []
    return [item for item in source if isinstance(item, Mapping)]


def normalize_forecast_table(
    forecast_result_or_rows: Mapping[str, Any] | Iterable[Mapping[str, Any]],
    *,
    latest_value: Any = None,
) -> list[dict[str, Any]]:
    """Return compact forecast rows from a helper result or raw forecast table."""

    rows: list[dict[str, Any]] = []
    for item in _rows_from(forecast_result_or_rows, "forecast_table"):
        forecast = _round(item.get("forecast"))
        if forecast is None and str(item.get("status") or "").lower() == "ok":
            continue
        baseline = item.get("last_value_baseline")
        if baseline is None:
            baseline = latest_value
        rows.append(
            {
                "horizon": item.get("horizon"),
                "date": _date_month(item.get("date") or item.get("forecast_period")),
                "forecast": forecast,
                "lower": _round(item.get("lower")),
                "upper": _round(item.get("upper")),
                "prediction_interval": item.get("prediction_interval"),
                "last_value_baseline": _round(baseline),
                "status": item.get("status"),
            }
        )
    return rows


def forecast_model_comparison_rows(
    model_comparison: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Pivot direct-forecast model comparison rows by forecast horizon."""

    rows_by_horizon: dict[int, dict[str, Any]] = {}
    metric_keys = {
        "direct_ols": "direct_ols",
        "baseline_last_value": "last_value",
        "baseline_train_mean": "train_mean",
    }
    for item in model_comparison:
        if not isinstance(item, Mapping):
            continue
        horizon = _horizon_int(item.get("horizon") or item.get("prediction_horizon") or 1)
        prefix = metric_keys.get(str(item.get("model") or ""))
        if horizon is None or prefix is None:
            continue
        row = rows_by_horizon.setdefault(horizon, {"horizon": horizon})
        for metric in ("mae", "rmse", "bias", "directional_accuracy"):
            row[f"{prefix}_{metric}"] = _round(item.get(metric))

    rows: list[dict[str, Any]] = []
    for horizon in sorted(rows_by_horizon):
        row = rows_by_horizon[horizon]
        mae_candidates = {
            model: value
            for model in ("direct_ols", "last_value", "train_mean")
            if (value := _finite(row.get(f"{model}_mae"))) is not None
        }
        if mae_candidates:
            row["winner_by_mae"] = min(mae_candidates, key=mae_candidates.get)
        direct = _finite(row.get("direct_ols_mae"))
        last_value = _finite(row.get("last_value_mae"))
        train_mean = _finite(row.get("train_mean_mae"))
        row["direct_beats_last_value"] = (
            direct < last_value if direct is not None and last_value is not None else None
        )
        row["direct_beats_train_mean"] = (
            direct < train_mean if direct is not None and train_mean is not None else None
        )
        row["direct_vs_last_value_mae_ratio"] = _round(
            direct / last_value if direct is not None and last_value not in (None, 0) else None,
            3,
        )
        rows.append(row)
    return rows


def forecast_failure_episodes(
    backtest: Mapping[str, Any],
    *,
    max_rows: int = 8,
) -> list[dict[str, Any]]:
    """Rank the largest walk-forward forecast misses from a backtest helper result."""

    rows: list[dict[str, Any]] = []
    for item in backtest.get("backtest_table", []):
        if not isinstance(item, Mapping):
            continue
        error = _finite(item.get("error"))
        actual = _finite(item.get("actual"))
        forecast = _finite(item.get("forecast"))
        if error is None or actual is None or forecast is None:
            continue
        baseline = _finite(item.get("baseline_last_value"))
        baseline_abs_error = abs(baseline - actual) if baseline is not None else None
        rows.append(
            {
                "prediction_date": str(item.get("prediction_date") or ""),
                "target_date": str(item.get("target_date") or ""),
                "actual": _round(actual),
                "forecast": _round(forecast),
                "error": _round(error),
                "absolute_error": _round(abs(error)),
                "baseline_last_value": _round(baseline),
                "baseline_absolute_error": _round(baseline_abs_error),
                "classification": (
                    "large_overprediction"
                    if error >= 1.0
                    else "large_underprediction"
                    if error <= -1.0
                    else "baseline_underperformance"
                    if baseline_abs_error is not None and abs(error) > baseline_abs_error
                    else "validation_miss"
                ),
            }
        )
    return sorted(
        rows,
        key=lambda item: float(item.get("absolute_error") or 0),
        reverse=True,
    )[:max_rows]


def forecast_false_alarm_episodes(
    frame: pd.DataFrame,
    *,
    signal_col: str,
    event_col: str,
    date_col: str = "date",
    threshold: float = 0.5,
    direction: str = "high",
    prediction_horizon: int = 6,
    max_rows: int = 8,
) -> list[dict[str, Any]]:
    """Return signal blocks not followed by the configured future event."""

    if frame.empty:
        return []
    if direction not in {"high", "low"}:
        raise ValueError("direction must be 'high' or 'low'")
    if prediction_horizon < 1:
        raise ValueError("prediction_horizon must be at least 1")
    working = frame.copy().sort_values(date_col).reset_index(drop=True)
    future_event = (
        pd.to_numeric(working[event_col], errors="coerce")
        .shift(-prediction_horizon)
        .fillna(0)
        >= 0.5
    )
    signal_values = pd.to_numeric(working[signal_col], errors="coerce")
    predicted = signal_values >= threshold if direction == "high" else signal_values <= threshold
    blocks = (predicted != predicted.shift(fill_value=False)).cumsum()
    episodes: list[dict[str, Any]] = []
    for _, block in working.loc[predicted].groupby(blocks[predicted]):
        if bool(future_event.loc[block.index].any()):
            continue
        peak_index = (
            signal_values.loc[block.index].idxmax()
            if direction == "high"
            else signal_values.loc[block.index].idxmin()
        )
        peak = working.loc[peak_index]
        start_date = pd.Timestamp(block[date_col].iloc[0])
        end_date = pd.Timestamp(block[date_col].iloc[-1])
        episodes.append(
            {
                "period": (
                    f"{start_date.year}"
                    if start_date.year == end_date.year
                    else f"{start_date.year}-{end_date.year}"
                ),
                "start": start_date.date().isoformat(),
                "end": end_date.date().isoformat(),
                "peak_date": pd.Timestamp(peak[date_col]).date().isoformat(),
                "max_signal": _round(peak.get(signal_col)),
                "threshold": threshold,
                "lookahead_periods": prediction_horizon,
            }
        )
    return episodes[-max_rows:]


def _panel_history_rows(
    panel: Any,
    *,
    target_col: str,
    date_col: str,
    history_tail: int,
) -> Iterable[Any]:
    if hasattr(panel, "dropna") and hasattr(panel, "tail") and hasattr(panel, "iterrows"):
        history = panel.dropna(subset=[target_col]).tail(history_tail)
        for _, row in history.iterrows():
            yield row
        return

    rows = [
        row
        for row in panel
        if hasattr(row, "get") and _finite(row.get(target_col)) is not None
    ]
    yield from rows[-history_tail:]


def forecast_band_rows(
    panel: Any,
    forecast_table: Iterable[Mapping[str, Any]],
    *,
    latest_value: Any = None,
    target_col: str,
    date_col: str = "date",
    history_tail: int = 72,
) -> list[dict[str, Any]]:
    """Combine recent actual values and future forecast interval rows."""

    rows = [
        {
            "date": _date_month(row.get(date_col)),
            "actual": _round(row.get(target_col)),
            "forecast": None,
            "lower": None,
            "upper": None,
            "last_value_baseline": None,
        }
        for row in _panel_history_rows(
            panel,
            target_col=target_col,
            date_col=date_col,
            history_tail=history_tail,
        )
    ]
    baseline = _round(latest_value)
    if baseline is None and rows:
        baseline = rows[-1]["actual"]
    if rows and baseline is not None:
        rows[-1]["forecast"] = rows[-1]["actual"]
        rows[-1]["lower"] = rows[-1]["actual"]
        rows[-1]["upper"] = rows[-1]["actual"]
        rows[-1]["last_value_baseline"] = baseline
    for item in forecast_table:
        if not isinstance(item, Mapping):
            continue
        forecast = _round(item.get("forecast"))
        if forecast is None:
            continue
        rows.append(
            {
                "date": _date_month(item.get("date") or item.get("forecast_period")),
                "actual": None,
                "forecast": forecast,
                "lower": _round(item.get("lower")),
                "upper": _round(item.get("upper")),
                "last_value_baseline": baseline,
            }
        )
    return rows


def _coefficient_importance(
    forecast_result: Mapping[str, Any],
    forecast_frame: pd.DataFrame,
    terms: list[str],
) -> dict[str, float]:
    models = forecast_result.get("diagnostics", {}).get("horizon_models", [])
    selected = next(
        (
            item
            for item in models
            if item.get("horizon") == forecast_result.get("diagnostics", {}).get("selected_horizon")
        ),
        models[-1] if models else {},
    )
    coefs = {
        str(item.get("term")): abs(float(item.get("estimate") or 0.0))
        for item in selected.get("coefficients", [])
        if isinstance(item, dict)
    }
    raw: dict[str, float] = {}
    for term in terms:
        if term not in forecast_frame:
            raw[term] = 0.0
            continue
        scale = float(pd.to_numeric(forecast_frame[term], errors="coerce").std(skipna=True) or 0.0)
        raw[term] = coefs.get(term, 0.0) * scale
    max_value = max(raw.values()) if raw else 0.0
    if max_value <= 0:
        return {term: 1.0 for term in terms}
    return {term: round(max(1.0, value / max_value * 100.0), 1) for term, value in raw.items()}


def predictor_contribution_rows(
    *,
    forecast_result: Mapping[str, Any],
    forecast_frame: pd.DataFrame,
    target_col: str,
    feature_cols: Iterable[str],
    panel: pd.DataFrame | None = None,
    component_specs: Iterable[tuple[str, str, str]] | None = None,
) -> list[dict[str, Any]]:
    """Return generic latest-signal and model-importance rows for forecast inputs."""

    features = list(dict.fromkeys(str(column) for column in feature_cols))
    terms = [target_col, *features]
    importance = _coefficient_importance(forecast_result, forecast_frame, terms)
    source_panel = panel if panel is not None else forecast_frame
    specs = list(component_specs or ())
    if not specs:
        specs = [(column, column, column) for column in features]
    rows: list[dict[str, Any]] = []
    for label, term, score_col in specs:
        if term not in forecast_frame:
            continue
        rows.append(
            {
                "metric": label,
                "feature": term,
                "model_importance": importance.get(term, 1.0),
                "latest_signal": latest_finite_value(source_panel, score_col, default=None, digits=3)
                if score_col in source_panel
                else None,
            }
        )
    return rows


def forecast_uncertainty_decomposition(
    forecast_table: Iterable[Mapping[str, Any]],
    *,
    validation_diagnostics: Mapping[str, Any] | None = None,
    signal_values: Iterable[Any] | None = None,
) -> dict[str, Any]:
    """Return generic rows for visualizing forecast uncertainty contributors."""

    interval_widths = [
        float(item["upper"]) - float(item["lower"])
        for item in forecast_table
        if isinstance(item, Mapping)
        and _finite(item.get("upper")) is not None
        and _finite(item.get("lower")) is not None
    ]
    metrics = (
        validation_diagnostics.get("metrics", {})
        if isinstance(validation_diagnostics, Mapping)
        else {}
    )
    baseline_metrics = (
        validation_diagnostics.get("baseline_comparison", {})
        if isinstance(validation_diagnostics, Mapping)
        else {}
    )
    signal_std = None
    if signal_values is not None:
        values = pd.to_numeric(pd.Series(list(signal_values)), errors="coerce")
        signal_std = values.tail(24).std(skipna=True)
    return {
        "name": "Forecast uncertainty",
        "children": [
            {
                "name": "Prediction interval width",
                "value": _round(max(1.0, abs(float(np.mean(interval_widths))))) if interval_widths else 1.0,
            },
            {
                "name": "Model backtest RMSE",
                "value": _round(max(1.0, abs(float(metrics.get("rmse") or 1.0)))),
            },
            {
                "name": "Baseline disagreement",
                "value": _round(
                    max(
                        1.0,
                        abs(
                            float(
                                (baseline_metrics.get("last_value", {}) or {}).get("mae")
                                if isinstance(baseline_metrics, Mapping)
                                else 1.0
                            )
                        ),
                    )
                ),
            },
            {
                "name": "Signal volatility",
                "value": _round(max(1.0, abs(float(signal_std or 1.0)))),
            },
        ],
    }

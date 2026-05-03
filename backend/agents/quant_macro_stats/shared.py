"""Deterministic macro statistics helpers for quant-developer scripts.

These helpers only operate on local pandas dataframes. Data retrieval stays with
data-engineer; report validation stays with technical-writer/QA.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

try:  # scipy is a project dependency, but quant scripts should degrade cleanly.
    from scipy import stats as _scipy_stats
except Exception:  # pragma: no cover - exercised by monkeypatch in tests
    _scipy_stats = None

try:  # statsmodels is optional for richer econometrics.
    import statsmodels.api as _statsmodels_api
    from statsmodels.tsa.stattools import adfuller as _adfuller
except Exception:  # pragma: no cover - exercised by monkeypatch in tests
    _statsmodels_api = None
    _adfuller = None


METHOD_ROLLING_CORRELATION = "rolling_pearson_correlation"
METHOD_LEAD_LAG_CORRELATION = "lead_lag_pearson_correlation"
METHOD_RECESSION_WINDOW_SUMMARY = "recession_window_summary"
METHOD_OLS_REGRESSION = "ols_regression"
METHOD_DIRECT_OLS_FORECAST = "direct_ols_forecast"
METHOD_WALK_FORWARD_OLS_BACKTEST = "walk_forward_ols_backtest"
METHOD_EVENT_SIGNAL_BACKTEST = "event_signal_backtest"
METHOD_SIGNAL_FRAMEWORK_BACKTEST = "signal_framework_backtest"
METHOD_HISTORICAL_SCENARIO_REPLAY = "historical_scenario_replay"
METHOD_STATIONARITY_CHECK = "stationarity_check"
METHOD_COMPOSITE_PREDICTIVE_INDICATOR = "composite_predictive_indicator"
METHOD_ANALOG_WINDOW_COMPARISON = "analog_window_comparison"
METHOD_PERIOD_KEY_ALIGNMENT = "period_key_alignment"
METHOD_SCENARIO_STRESS_TEST = "scenario_stress_test"
METHOD_RECESSION_REGIME_CLASSIFIER = "recession_regime_classifier"
METHOD_SEC_COMPANY_FACTS_SUMMARY = "sec_company_facts_summary"
REQUIRED_SCENARIOS = ("base", "bull", "bear")
SCENARIO_ALIASES = {
    "base case": "base",
    "baseline": "base",
    "upside": "bull",
    "upside case": "bull",
    "bull case": "bull",
    "reacceleration": "bull",
    "downside": "bear",
    "downside case": "bear",
    "bear case": "bear",
    "recession": "bear",
}
DEFAULT_REGIME_CATEGORIES = ("rates", "labor", "inflation", "credit", "output")
DEFAULT_REGIME_WEIGHTS = {
    "rates": 0.20,
    "labor": 0.25,
    "inflation": 0.15,
    "credit": 0.20,
    "output": 0.20,
}


def _require_columns(data: pd.DataFrame, columns: Iterable[str]) -> None:
    missing = [column for column in columns if column not in data.columns]
    if missing:
        raise ValueError(f"Missing required column(s): {', '.join(missing)}")


def _as_ordered_frame(data: pd.DataFrame, date_col: str, columns: Iterable[str]) -> pd.DataFrame:
    _require_columns(data, [date_col, *columns])
    frame = data[[date_col, *columns]].copy()
    frame[date_col] = pd.to_datetime(frame[date_col], errors="coerce")
    frame = frame.dropna(subset=[date_col]).sort_values(date_col).reset_index(drop=True)
    for column in columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


def _clean_regression_frame(
    data: pd.DataFrame,
    date_col: str,
    target_col: str,
    feature_cols: Iterable[str],
) -> pd.DataFrame:
    columns = [target_col, *list(feature_cols)]
    frame = _as_ordered_frame(data, date_col, columns)
    return frame.dropna(subset=columns).reset_index(drop=True)


def _iso_date(value: Any) -> str | None:
    if pd.isna(value):
        return None
    return pd.Timestamp(value).date().isoformat()


def _finite_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if np.isfinite(numeric) else None


def _direction_multiplier(value: Any) -> float:
    """Normalize model-friendly direction hints into numeric multipliers."""

    if isinstance(value, str):
        cleaned = value.strip().lower()
        if cleaned in {"high", "higher", "positive", "procyclical", "expansion"}:
            return 1.0
        if cleaned in {"low", "lower", "negative", "countercyclical", "stress"}:
            return -1.0
    numeric = _finite_float(value)
    if numeric is None:
        raise ValueError("feature_directions values must be numeric or 'high'/'low'")
    return 1.0 if numeric >= 0 else -1.0


def to_json_safe(value: Any) -> Any:
    """Recursively convert pandas/numpy objects into strict JSON values."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if np.isfinite(value) else None
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        numeric = float(value)
        return numeric if np.isfinite(numeric) else None
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, pd.Period):
        return str(value)
    if isinstance(value, dict):
        return {str(key): to_json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_json_safe(item) for item in value]
    if isinstance(value, np.ndarray):
        return [to_json_safe(item) for item in value.tolist()]
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return str(value)


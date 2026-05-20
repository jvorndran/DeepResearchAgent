"""Deterministic macro statistics helpers for quant-developer scripts.

These helpers only operate on local pandas dataframes. Data retrieval stays with
data-engineer; report validation stays with technical-writer/QA.
"""

from __future__ import annotations

import json  # noqa: F401 - re-exported for legacy star-import modules.
from copy import deepcopy  # noqa: F401 - re-exported for legacy star-import modules.
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
METHOD_RECESSION_REGIME_CLASSIFIER = "recession_regime_classifier"
METHOD_SEC_COMPANY_FACTS_SUMMARY = "sec_company_facts_summary"
METHOD_SAHM_RULE_SIGNAL = "sahm_rule_signal"
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


def find_data_file_key(
    data_files: dict[str, str],
    candidates: tuple[str, ...],
    *,
    allow_prefix: bool = False,
    search_path_stem: bool = False,
) -> str | None:
    """Return the first candidate key found in a FRED/BLS artifact mapping."""

    normalized = {str(key).upper(): str(key) for key in data_files}
    for candidate in candidates:
        candidate_upper = str(candidate).upper()
        if candidate_upper in normalized:
            return normalized[candidate_upper]
        if allow_prefix:
            for key_upper, original_key in normalized.items():
                if key_upper.startswith(f"{candidate_upper}_"):
                    return original_key
        if search_path_stem:
            for original_key, path_text in data_files.items():
                if candidate_upper in Path(str(path_text)).stem.upper():
                    return str(original_key)
    return None


def read_value_series(path: str, key: str) -> pd.DataFrame:
    """Read a local date/value or BLS year/period CSV as a sorted value series."""

    frame = pd.read_csv(path)
    if "date" in frame.columns:
        dates = pd.to_datetime(frame["date"], errors="coerce")
    elif {"year", "period"}.issubset(frame.columns):
        period = frame["period"].astype(str).str.extract(r"M(\d{2})", expand=False)
        dates = pd.to_datetime(
            frame["year"].astype(str) + "-" + period.fillna("01") + "-01",
            errors="coerce",
        )
    else:
        raise ValueError(f"{path} must include either date or BLS year/period columns")
    if "value" not in frame.columns:
        raise ValueError(f"{path} must include a value column")
    values = pd.to_numeric(frame["value"].replace(".", pd.NA), errors="coerce")
    return (
        pd.DataFrame({"date": dates, key: values})
        .dropna(subset=["date"])
        .sort_values("date")
        .reset_index(drop=True)
    )


def read_monthly_series(path: str, key: str) -> pd.DataFrame:
    """Read a local date/value or BLS year/period CSV and resample it monthly."""

    frame = read_value_series(path, key)
    monthly = (
        frame.set_index("date")[[key]]
        .resample("MS")
        .mean(numeric_only=True)
        .reset_index()
    )
    return monthly.dropna(subset=[key]).reset_index(drop=True)


def month_label(value: Any) -> str:
    timestamp = pd.Timestamp(value)
    return f"{timestamp.year:04d}-{timestamp.month:02d}"


def finite_number(value: Any) -> float | None:
    return _finite_float(value)


def rounded_number(value: Any, digits: int = 3) -> float | None:
    number = finite_number(value)
    return None if number is None else round(number, digits)


def chart_records(
    frame: pd.DataFrame,
    columns: list[str],
    *,
    digits: int = 3,
) -> list[dict[str, Any]]:
    rows = frame[["date", *columns]].dropna(how="all", subset=columns).copy()
    records: list[dict[str, Any]] = []
    for _, row in rows.iterrows():
        record: dict[str, Any] = {"date": month_label(row["date"])}
        for column in columns:
            record[column] = rounded_number(row.get(column), digits)
        records.append(record)
    return records


def recession_bands(panel: pd.DataFrame) -> list[dict[str, Any]]:
    if "USREC" not in panel:
        return []
    rows = panel[["date", "USREC"]].dropna(subset=["date"]).copy()
    rows["_in_recession"] = pd.to_numeric(rows["USREC"], errors="coerce").fillna(0) >= 0.5
    bands: list[dict[str, Any]] = []
    start: pd.Timestamp | None = None
    previous: pd.Timestamp | None = None
    for _, row in rows.iterrows():
        current = pd.Timestamp(row["date"])
        if bool(row["_in_recession"]) and start is None:
            start = current
        if not bool(row["_in_recession"]) and start is not None:
            bands.append(
                {
                    "x1": month_label(start),
                    "x2": month_label(previous or start),
                    "label": f"{start.year} recession",
                    "fill": "#e5e7eb",
                    "opacity": 0.35,
                }
            )
            start = None
        previous = current
    if start is not None:
        bands.append(
            {
                "x1": month_label(start),
                "x2": month_label(previous or start),
                "label": f"{start.year} recession",
                "fill": "#e5e7eb",
                "opacity": 0.35,
            }
        )
    return bands


def stress_score_series(
    series: pd.Series,
    *,
    high_is_stress: bool,
    empty_score: float | None = 50.0,
) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    finite = values.dropna()
    if finite.empty:
        if empty_score is None:
            return pd.Series([pd.NA] * len(values), index=values.index, dtype="Float64")
        return pd.Series([float(empty_score)] * len(values), index=values.index)
    low = float(finite.quantile(0.10))
    high = float(finite.quantile(0.90))
    if high <= low:
        return pd.Series([50.0] * len(values), index=values.index)
    score = (values - low) / (high - low) * 100.0
    if not high_is_stress:
        score = 100.0 - score
    return score.clip(lower=0.0, upper=100.0)


def latest_finite_observation(
    panel: pd.DataFrame,
    key: str,
    *,
    digits: int = 3,
) -> tuple[float | None, str | None]:
    if key not in panel:
        return None, None
    rows = panel[["date", key]].dropna(subset=[key]).copy()
    if rows.empty:
        return None, None
    row = rows.iloc[-1]
    return rounded_number(row[key], digits), month_label(row["date"])


def latest_finite_value(
    panel: pd.DataFrame,
    column: str,
    *,
    default: float | None = None,
    digits: int = 3,
) -> float | None:
    if column not in panel:
        return default
    values = pd.to_numeric(panel[column], errors="coerce").dropna()
    if values.empty:
        return default
    return rounded_number(values.iloc[-1], digits)


def expected_month_count(start: Any, end: Any) -> int:
    try:
        return max(1, len(pd.period_range(pd.Timestamp(start), pd.Timestamp(end), freq="M")))
    except (TypeError, ValueError):
        return 1


def window_coverage(
    panel: pd.DataFrame,
    window: dict[str, Any],
    value_cols: list[str],
    *,
    min_required_cap: int = 12,
    min_coverage: float = 0.5,
) -> dict[str, Any]:
    start = window["start"]
    end = window["end"]
    rows = panel[(panel["date"] >= pd.Timestamp(start)) & (panel["date"] <= pd.Timestamp(end))]
    expected = expected_month_count(start, end)
    available = [column for column in value_cols if column in rows]
    observed = int(rows[available].notna().any(axis=1).sum()) if available else 0
    coverage_ratio = round(observed / expected, 3) if expected else 0.0
    min_required = max(1, min(min_required_cap, int(np.ceil(expected * min_coverage))))
    if observed >= min_required and coverage_ratio >= min_coverage:
        status = "covered"
    elif observed:
        status = "partial"
    else:
        status = "not_available"
    return {
        "label": window["label"],
        "start": start,
        "end": end,
        "expected_months": expected,
        "observed_months": observed,
        "coverage_ratio": coverage_ratio,
        "min_required_months": min_required,
        "status": status,
    }


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

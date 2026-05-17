"""OLS forecasting, event backtests, and historical replay helpers."""
import sys
from typing import Any, Iterable

import numpy as np
import pandas as pd

from .._utils import (
    METHOD_ANALOG_WINDOW_COMPARISON,
    METHOD_DIRECT_OLS_FORECAST,
    METHOD_EVENT_SIGNAL_BACKTEST,
    METHOD_HISTORICAL_SCENARIO_REPLAY,
    METHOD_OLS_REGRESSION,
    METHOD_SIGNAL_FRAMEWORK_BACKTEST,
    METHOD_STATIONARITY_CHECK,
    METHOD_WALK_FORWARD_OLS_BACKTEST,
    _adfuller,
    _as_ordered_frame,
    _clean_regression_frame,
    _finite_float,
    _iso_date,
    _scipy_stats,
    _statsmodels_api,
)


def _model_spec(
    target_col: str, feature_cols: list[str], *, forecast_horizon: int | None = None
) -> str:
    left = f"{target_col}(t+{forecast_horizon})" if forecast_horizon else target_col
    return f"{left} ~ const + " + " + ".join(feature_cols)


def _stationarity_check(series: pd.Series, variable: str) -> dict[str, Any]:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if len(values) < 8:
        return {
            "variable": variable,
            "nobs": int(len(values)),
            "method": METHOD_STATIONARITY_CHECK,
            "status": "insufficient_observations",
            "p_value": None,
            "warning": "Stationarity check skipped because fewer than 8 observations were available.",
        }

    public_module = sys.modules.get("agents.quant_macro_stats")
    adfuller = getattr(public_module, "_adfuller", _adfuller)
    if adfuller is not None:
        try:
            statistic, p_value, *_ = adfuller(values.to_numpy(dtype=float), autolag="AIC")
            warning = (
                "ADF p-value is above 0.10; level regression may be sensitive to trends "
                "or non-stationarity."
                if p_value > 0.10
                else None
            )
            return {
                "variable": variable,
                "nobs": int(len(values)),
                "method": METHOD_STATIONARITY_CHECK,
                "test": "adf",
                "statistic": _finite_float(statistic),
                "p_value": _finite_float(p_value),
                "status": "warning" if warning else "ok",
                "warning": warning,
            }
        except Exception as exc:
            return {
                "variable": variable,
                "nobs": int(len(values)),
                "method": METHOD_STATIONARITY_CHECK,
                "status": "error",
                "p_value": None,
                "warning": f"ADF stationarity check failed: {exc}",
            }

    scale = float(values.std(ddof=1)) if len(values) > 1 else 0.0
    drift = float(abs(values.iloc[-1] - values.iloc[0]))
    warning = (
        "statsmodels_unavailable: ADF stationarity test skipped; large endpoint drift "
        "suggests checking transformed or differenced data."
        if scale > 0 and drift > 2 * scale
        else "statsmodels_unavailable: ADF stationarity test skipped."
    )
    return {
        "variable": variable,
        "nobs": int(len(values)),
        "method": METHOD_STATIONARITY_CHECK,
        "test": "endpoint_drift_heuristic",
        "statistic": _finite_float(drift / scale) if scale > 0 else None,
        "p_value": None,
        "status": "warning" if scale > 0 and drift > 2 * scale else "unavailable",
        "warning": warning,
    }


def _normal_quantile(probability: float) -> float:
    public_module = sys.modules.get("agents.quant_macro_stats")
    scipy_stats = getattr(public_module, "_scipy_stats", _scipy_stats)
    if scipy_stats is not None:
        return float(scipy_stats.norm.ppf(probability))
    return 1.96


def _metric_summary(actual: pd.Series, predicted: pd.Series) -> dict[str, float | None]:
    pairs = pd.DataFrame({"actual": actual, "predicted": predicted}).dropna()
    if pairs.empty:
        return {"mae": None, "rmse": None, "bias": None, "directional_accuracy": None}
    errors = pairs["predicted"] - pairs["actual"]
    actual_direction = np.sign(pairs["actual"].diff())
    predicted_direction = np.sign(pairs["predicted"].diff())
    direction_pairs = pd.DataFrame(
        {"actual": actual_direction, "predicted": predicted_direction}
    ).dropna()
    direction_pairs = direction_pairs[
        (direction_pairs["actual"] != 0) | (direction_pairs["predicted"] != 0)
    ]
    return {
        "mae": _finite_float(errors.abs().mean()),
        "rmse": _finite_float(np.sqrt(np.mean(errors**2))),
        "bias": _finite_float(errors.mean()),
        "directional_accuracy": _finite_float(
            (direction_pairs["actual"] == direction_pairs["predicted"]).mean()
            if not direction_pairs.empty
            else None
        ),
    }


def _event_metrics(actual: pd.Series, predicted: pd.Series) -> dict[str, Any]:
    actual_bool = actual.astype(bool)
    predicted_bool = predicted.astype(bool)
    tp = int((actual_bool & predicted_bool).sum())
    fp = int((~actual_bool & predicted_bool).sum())
    tn = int((~actual_bool & ~predicted_bool).sum())
    fn = int((actual_bool & ~predicted_bool).sum())
    observations = int(len(actual_bool))
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    return {
        "accuracy": _finite_float((tp + tn) / observations if observations else None),
        "precision": _finite_float(precision),
        "recall": _finite_float(recall),
        "f1": _finite_float(
            2 * precision * recall / (precision + recall)
            if precision is not None and recall is not None and precision + recall
            else None
        ),
        "true_positive": tp,
        "false_positive": fp,
        "true_negative": tn,
        "false_negative": fn,
    }


def _first_event_dates(frame: pd.DataFrame, date_col: str, event_col: str) -> list[pd.Timestamp]:
    events = frame[event_col].fillna(False).astype(bool)
    starts = events & ~events.shift(1, fill_value=False)
    return [pd.Timestamp(value) for value in frame.loc[starts, date_col].tolist()]


def walk_forward_ols_backtest(
    data: pd.DataFrame,
    target_col: str,
    feature_cols: Iterable[str],
    *,
    date_col: str = "date",
    horizon: int = 1,
    include_target_lag: bool = True,
    min_observations: int = 12,
    initial_train_fraction: float = 0.6,
    max_table_rows: int = 24,
) -> dict[str, Any]:
    """Validate a direct OLS forecast with expanding-window, no-lookahead tests."""

    if horizon < 1:
        raise ValueError("horizon must be at least 1")
    if min_observations < 3:
        raise ValueError("min_observations must be at least 3")
    if not 0 < initial_train_fraction < 1:
        raise ValueError("initial_train_fraction must be between 0 and 1")

    requested_features = list(dict.fromkeys(feature_cols))
    if not requested_features:
        raise ValueError("feature_cols must include at least one feature")
    base_features = [feature for feature in requested_features if feature != target_col]
    if not base_features and not include_target_lag:
        raise ValueError("feature_cols must include at least one non-target feature")
    model_features = (
        [target_col, *base_features]
        if include_target_lag
        else base_features
    )
    frame = _clean_regression_frame(data, date_col, target_col, base_features)
    if len(frame) < min_observations + horizon + 1:
        return {
            "status": "insufficient_observations",
            "model_spec": _model_spec(target_col, model_features, forecast_horizon=horizon),
            "target_variable": target_col,
            "features": model_features,
            "prediction_horizon": horizon,
            "test_observations": 0,
            "methods_used": [METHOD_WALK_FORWARD_OLS_BACKTEST],
            "limitations": [
                "Walk-forward validation skipped because the complete local panel is too short."
            ],
        }

    initial_train_end = max(min_observations, int(len(frame) * initial_train_fraction))
    initial_train_end = min(initial_train_end, len(frame) - horizon)
    validation_rows: list[dict[str, Any]] = []
    for predict_index in range(initial_train_end, len(frame) - horizon):
        train_source = frame.iloc[:predict_index].copy()
        train_source["_target_future"] = train_source[target_col].shift(-horizon)
        train = train_source.dropna(subset=["_target_future", *model_features])
        if len(train) < min_observations:
            continue
        x_train = np.column_stack(
            [np.ones(len(train)), train[model_features].to_numpy(dtype=float)]
        )
        y_train = train["_target_future"].to_numpy(dtype=float)
        fitted = _fit_ols_arrays(y_train, x_train, model_features)
        predictor_values = frame[model_features].iloc[predict_index].to_numpy(dtype=float)
        x_latest = np.concatenate([[1.0], predictor_values])
        coefficients = np.array([item["estimate"] for item in fitted["coefficients"]])
        prediction = float(x_latest @ coefficients)
        actual = frame[target_col].iloc[predict_index + horizon]
        train_target = train["_target_future"]
        validation_rows.append(
            {
                "prediction_date": _iso_date(frame[date_col].iloc[predict_index]),
                "target_date": _iso_date(frame[date_col].iloc[predict_index + horizon]),
                "actual": _finite_float(actual),
                "forecast": _finite_float(prediction),
                "baseline_last_value": _finite_float(frame[target_col].iloc[predict_index]),
                "baseline_train_mean": _finite_float(train_target.mean()),
                "error": _finite_float(prediction - actual),
                "train_observations": int(len(train)),
            }
        )

    if not validation_rows:
        return {
            "status": "insufficient_test_observations",
            "model_spec": _model_spec(target_col, model_features, forecast_horizon=horizon),
            "target_variable": target_col,
            "features": model_features,
            "prediction_horizon": horizon,
            "test_observations": 0,
            "methods_used": [METHOD_WALK_FORWARD_OLS_BACKTEST],
            "limitations": [
                "No validation rows remained after enforcing complete predictors and future targets."
            ],
        }

    validation = pd.DataFrame(validation_rows)
    model_metrics = _metric_summary(validation["actual"], validation["forecast"])
    last_value_metrics = _metric_summary(validation["actual"], validation["baseline_last_value"])
    train_mean_metrics = _metric_summary(validation["actual"], validation["baseline_train_mean"])
    comparisons = [
        {"model": "direct_ols", **model_metrics},
        {"model": "baseline_last_value", **last_value_metrics},
        {"model": "baseline_train_mean", **train_mean_metrics},
    ]
    valid_mae = [
        item for item in comparisons if item.get("mae") is not None
    ]
    best_model = min(valid_mae, key=lambda item: float(item["mae"]))["model"] if valid_mae else None

    table = validation_rows[-max_table_rows:] if max_table_rows else validation_rows
    return {
        "status": "ok",
        "model_spec": _model_spec(target_col, model_features, forecast_horizon=horizon),
        "target_variable": target_col,
        "features": model_features,
        "prediction_horizon": horizon,
        "validation_window": {
            "start": validation_rows[0]["target_date"],
            "end": validation_rows[-1]["target_date"],
        },
        "test_observations": int(len(validation_rows)),
        "metrics": model_metrics,
        "baseline_comparison": {
            "last_value": last_value_metrics,
            "train_mean": train_mean_metrics,
        },
        "model_comparison": comparisons,
        "best_model_by_mae": best_model,
        "backtest_table": table,
        "methods_used": [METHOD_WALK_FORWARD_OLS_BACKTEST],
        "limitations": [
            "Expanding-window validation uses only data available before each prediction date.",
            "Backtest results are sample-dependent and do not account for real-time data revisions unless the input panel is vintage data.",
        ],
    }


def event_signal_backtest(
    data: pd.DataFrame,
    *,
    signal_col: str,
    target_col: str,
    date_col: str = "date",
    threshold: float = 0.5,
    direction: str = "high",
    prediction_horizon: int = 6,
    min_observations: int = 12,
) -> dict[str, Any]:
    """Backtest whether a local signal anticipates a future event."""

    if direction not in {"high", "low"}:
        raise ValueError("direction must be 'high' or 'low'")
    if prediction_horizon < 1:
        raise ValueError("prediction_horizon must be at least 1")
    frame = _as_ordered_frame(data, date_col, [signal_col, target_col])
    frame["_target_future"] = frame[target_col].shift(-prediction_horizon)
    frame = frame.dropna(subset=[signal_col, "_target_future"]).reset_index(drop=True)
    if len(frame) < min_observations:
        return {
            "status": "insufficient_observations",
            "test_observations": int(len(frame)),
            "methods_used": [METHOD_EVENT_SIGNAL_BACKTEST],
            "limitations": ["Event backtest skipped because too few complete rows were available."],
        }
    predicted = (
        frame[signal_col] >= threshold if direction == "high" else frame[signal_col] <= threshold
    )
    actual = frame["_target_future"] >= 0.5
    metrics = _event_metrics(actual, predicted)
    first_target_events = _first_event_dates(frame, date_col, "_target_future")
    signal_dates = [pd.Timestamp(value) for value in frame.loc[predicted, date_col].tolist()]
    lead_times: list[int] = []
    for event_date in first_target_events:
        prior_signals = [date for date in signal_dates if date <= event_date]
        if prior_signals:
            lead_times.append(int(round((event_date - max(prior_signals)).days / 30.4375)))
    lead_time_rows: list[dict[str, Any]] = []
    for event_date in first_target_events:
        prior_signals = [date for date in signal_dates if date <= event_date]
        prior_signal = max(prior_signals) if prior_signals else None
        lead_time_rows.append(
            {
                "event_date": event_date.date().isoformat(),
                "prior_signal_date": prior_signal.date().isoformat() if prior_signal else None,
                "lead_periods": (
                    int(round((event_date - prior_signal).days / 30.4375))
                    if prior_signal is not None
                    else None
                ),
                "status": "covered" if prior_signal is not None else "missed",
            }
        )
    false_alarm_rows: list[dict[str, Any]] = []
    false_alarm_frame = frame.loc[predicted & ~actual]
    for _, row in false_alarm_frame.iterrows():
        signal_date = pd.Timestamp(row[date_col])
        target_date = signal_date + pd.DateOffset(months=prediction_horizon)
        false_alarm_rows.append(
            {
                "signal_date": signal_date.date().isoformat(),
                "target_date": target_date.date().isoformat(),
                "signal_value": _finite_float(row[signal_col]),
                "threshold": _finite_float(threshold),
                "direction": direction,
            }
        )
    event_backtest_metrics = {
        **metrics,
        "average_lead_periods": _finite_float(np.mean(lead_times) if lead_times else None),
    }
    test_window = {
        "start": _iso_date(frame[date_col].iloc[0]),
        "end": _iso_date(frame[date_col].iloc[-1]),
    }
    return {
        "status": "ok",
        "signal": signal_col,
        "target_event": target_col,
        "threshold": threshold,
        "direction": direction,
        "prediction_horizon": prediction_horizon,
        "test_window": test_window,
        "test_observations": int(len(frame)),
        "event_backtest_metrics": event_backtest_metrics,
        "lead_time_rows": lead_time_rows,
        "false_alarm_rows": false_alarm_rows,
        "backtest_design": {
            "signal_col": signal_col,
            "target_col": target_col,
            "threshold": _finite_float(threshold),
            "direction": direction,
            "prediction_horizon": int(prediction_horizon),
        },
        "methods_used": [METHOD_EVENT_SIGNAL_BACKTEST],
        "limitations": [
            "Signal backtests depend on the chosen threshold and target-event definition.",
            "Historical hits are not guarantees that future events will follow the same lead time.",
        ],
    }


def signal_framework_backtest(
    data: pd.DataFrame,
    *,
    component_cols: Iterable[str],
    recession_col: str,
    date_col: str = "date",
    threshold: float = 3,
    recession_start_dates: Iterable[Any] | None = None,
    lookback_periods: int = 12,
    false_alarm_lookahead_periods: int = 12,
    component_labels: dict[str, str] | None = None,
    min_observations: int = 24,
) -> dict[str, Any]:
    """Backtest a thresholded multi-component macro signal against recession starts.

    The caller owns the economic component definitions. This helper returns
    reusable no-lookahead rows and metrics for analysis.py to compose.
    """

    components = list(component_cols)
    if not components:
        raise ValueError("component_cols must include at least one component column")
    if lookback_periods < 1:
        raise ValueError("lookback_periods must be at least 1")
    if false_alarm_lookahead_periods < 0:
        raise ValueError("false_alarm_lookahead_periods must be non-negative")

    frame = _as_ordered_frame(data, date_col, [*components, recession_col])
    frame = frame.dropna(subset=[recession_col]).reset_index(drop=True)
    recession_values = pd.to_numeric(frame[recession_col], errors="coerce").dropna()
    unique_recession_values = set(recession_values.unique().tolist())
    if unique_recession_values and not unique_recession_values.issubset({0, 1, 0.0, 1.0}):
        sample_values = sorted(unique_recession_values)[:5]
        raise ValueError(
            "recession_col must be a binary 0/1 recession indicator such as USREC; "
            f"{recession_col!r} contains non-binary values like {sample_values}"
        )
    for column in components:
        frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0.0)
    frame["_score"] = frame[components].sum(axis=1)
    frame["_recession"] = pd.to_numeric(frame[recession_col], errors="coerce").fillna(0.0) >= 0.5
    if len(frame) < min_observations:
        return {
            "status": "insufficient_observations",
            "test_observations": int(len(frame)),
            "signal_validation_metrics": {
                "method": METHOD_SIGNAL_FRAMEWORK_BACKTEST,
                "status": "insufficient_observations",
                "observations": int(len(frame)),
            },
            "methods_used": [METHOD_SIGNAL_FRAMEWORK_BACKTEST],
            "limitations": ["Signal-framework backtest skipped because too few rows were available."],
        }

    if recession_start_dates is None:
        starts = frame.loc[
            frame["_recession"] & ~frame["_recession"].shift(1, fill_value=False),
            date_col,
        ].tolist()
    else:
        starts = [pd.Timestamp(value) for value in recession_start_dates]
    starts = [pd.Timestamp(value) for value in starts]

    labels = component_labels or {}

    def triggered(row: pd.Series) -> list[str]:
        return [
            str(labels.get(component, component))
            for component in components
            if _finite_float(row.get(component)) and float(row.get(component)) != 0.0
        ]

    pre_recession_scores: dict[str, Any] = {}
    correct_calls = 0
    for start in starts:
        window = frame[
            (frame[date_col] >= start - pd.DateOffset(months=lookback_periods))
            & (frame[date_col] < start)
        ]
        key = f"{start.year}_recession_{lookback_periods}m_before"
        if window.empty:
            pre_recession_scores[key] = {"status": "no_observations"}
            continue
        peak = window.loc[window["_score"].idxmax()]
        score = _finite_float(peak["_score"])
        if score is not None and score >= threshold:
            correct_calls += 1
        pre_recession_scores[key] = {
            "event_date": start.date().isoformat(),
            "score": score,
            "components_triggered": triggered(peak),
            "max_score_date": _iso_date(peak[date_col]),
        }

    signal = frame["_score"] >= threshold
    blocks = (signal != signal.shift(1, fill_value=False)).cumsum()
    false_alarms: list[dict[str, Any]] = []
    for _, block in frame.loc[signal].groupby(blocks[signal]):
        start_date = pd.Timestamp(block[date_col].iloc[0])
        end_date = pd.Timestamp(block[date_col].iloc[-1])
        follow = frame[
            (frame[date_col] >= start_date)
            & (
                frame[date_col]
                <= end_date + pd.DateOffset(months=false_alarm_lookahead_periods)
            )
        ]
        if bool(follow["_recession"].any()):
            continue
        peak = block.loc[block["_score"].idxmax()]
        false_alarms.append(
            {
                "window_label": (
                    f"{start_date.year}"
                    if start_date.year == end_date.year
                    else f"{start_date.year}-{end_date.year}"
                ),
                "start": start_date.date().isoformat(),
                "end": end_date.date().isoformat(),
                "max_score": _finite_float(peak["_score"]),
                "components_at_peak": triggered(peak),
                "threshold": _finite_float(threshold),
                "lookahead_periods": int(false_alarm_lookahead_periods),
            }
        )

    latest = frame.iloc[-1]
    latest_score = _finite_float(latest["_score"])
    threshold_value = _finite_float(threshold)
    signal_event_rows: list[dict[str, Any]] = []
    for label, row in pre_recession_scores.items():
        if not isinstance(row, dict):
            continue
        score = _finite_float(row.get("score"))
        met_threshold = (
            score is not None and threshold_value is not None and score >= threshold_value
        )
        signal_event_rows.append(
            {
                "event_label": str(label),
                "event_date": row.get("event_date"),
                "score": score,
                "met_threshold": met_threshold,
                "max_score_date": row.get("max_score_date"),
                "components_triggered": row.get("components_triggered", []),
                "status": row.get("status", "ok"),
            }
        )

    precision = _finite_float(
        correct_calls / (correct_calls + len(false_alarms))
        if correct_calls + len(false_alarms) > 0
        else None
    )
    signal_validation_metrics = {
        "method": METHOD_SIGNAL_FRAMEWORK_BACKTEST,
        "status": "ok",
        "components": [str(labels.get(component, component)) for component in components],
        "threshold": threshold_value,
        "lookback_periods": int(lookback_periods),
        "false_alarm_lookahead_periods": int(false_alarm_lookahead_periods),
        "observations": int(len(frame)),
        "event_count": int(len(starts)),
        "events_met_threshold": int(correct_calls),
        "events_below_threshold": max(int(len(starts)) - int(correct_calls), 0),
        "false_positive_windows": int(len(false_alarms)),
        "true_positive_rate": _finite_float(correct_calls / len(starts) if starts else None),
        "precision": precision,
    }
    latest_signal_observation = {
        "date": _iso_date(latest[date_col]),
        "score": latest_score,
        "threshold": threshold_value,
        "above_threshold": (
            latest_score is not None
            and threshold_value is not None
            and latest_score >= threshold_value
        ),
        "threshold_distance": (
            _finite_float(latest_score - threshold_value)
            if latest_score is not None and threshold_value is not None
            else None
        ),
        "components_triggered": triggered(latest),
    }
    signal_score_rows = [
        {
            "date": _iso_date(row[date_col]),
            "score": _finite_float(row["_score"]),
            "threshold": threshold_value,
            "above_threshold": bool(row["_score"] >= threshold),
            "components_triggered": triggered(row),
            "event_observed": bool(row["_recession"]),
        }
        for _, row in frame.iterrows()
    ]
    return {
        "status": "ok",
        "signal_score_rows": signal_score_rows,
        "signal_event_rows": signal_event_rows,
        "signal_false_positive_windows": false_alarms,
        "signal_validation_metrics": signal_validation_metrics,
        "latest_signal_observation": latest_signal_observation,
        "signal_design": {
            "event_col": recession_col,
            "component_cols": components,
            "threshold": threshold_value,
            "lookback_periods": int(lookback_periods),
            "false_alarm_lookahead_periods": int(false_alarm_lookahead_periods),
        },
        "methods_used": [METHOD_SIGNAL_FRAMEWORK_BACKTEST],
        "limitations": [
            "Component thresholds are analyst-defined and should be sensitivity-tested.",
            "Small recession event counts make true-positive rates unstable.",
            "False alarms are defined as signal blocks not followed by a recession within the configured lookahead window.",
        ],
    }


def historical_scenario_replay(
    data: pd.DataFrame,
    *,
    date_col: str = "date",
    signal_cols: Iterable[str],
    outcome_col: str,
    windows: Iterable[dict[str, Any]],
    lookahead_periods: int = 6,
) -> dict[str, Any]:
    """Return reusable replay rows for caller-selected historical windows."""

    signals = list(signal_cols or [])
    if not signals:
        raise ValueError("signal_cols must include at least one signal")
    if not outcome_col:
        raise ValueError("outcome_col is required")
    replay_windows = list(windows or [])
    if not replay_windows:
        raise ValueError("windows must include at least one explicit historical window")
    if lookahead_periods < 1:
        raise ValueError("lookahead_periods must be at least 1")
    frame = _as_ordered_frame(data, date_col, [*signals, outcome_col])
    rows: list[dict[str, Any]] = []
    for item in replay_windows:
        label = str(item.get("label") or item.get("name") or "historical_window")
        start = pd.Timestamp(item.get("start"))
        end = pd.Timestamp(item.get("end"))
        window = frame[(frame[date_col] >= start) & (frame[date_col] <= end)]
        if window.empty:
            rows.append(
                {
                    "label": label,
                    "start": start.date().isoformat(),
                    "end": end.date().isoformat(),
                    "status": "no_observations",
                }
            )
            continue
        after = frame[frame[date_col] > window[date_col].iloc[-1]].head(lookahead_periods)
        signal_summary = {
            signal: {
                "start": _finite_float(window[signal].iloc[0]),
                "end": _finite_float(window[signal].iloc[-1]),
                "min": _finite_float(window[signal].min()),
                "max": _finite_float(window[signal].max()),
                "mean": _finite_float(window[signal].mean()),
            }
            for signal in signals
        }
        rows.append(
            {
                "label": label,
                "start": _iso_date(window[date_col].iloc[0]),
                "end": _iso_date(window[date_col].iloc[-1]),
                "status": "ok",
                "signal_path": signal_summary,
                "outcome_during_window": {
                    "start": _finite_float(window[outcome_col].iloc[0]),
                    "end": _finite_float(window[outcome_col].iloc[-1]),
                    "min": _finite_float(window[outcome_col].min()),
                    "max": _finite_float(window[outcome_col].max()),
                    "mean": _finite_float(window[outcome_col].mean()),
                },
                "subsequent_outcome": {
                    "periods": int(len(after)),
                    "end": _finite_float(after[outcome_col].iloc[-1]) if not after.empty else None,
                    "min": _finite_float(after[outcome_col].min()) if not after.empty else None,
                    "max": _finite_float(after[outcome_col].max()) if not after.empty else None,
                },
            }
        )
    return {
        "replay_rows": rows,
        "replay_design": {
            "date_col": date_col,
            "outcome_variable": outcome_col,
            "signal_variables": signals,
            "lookahead_periods": int(lookahead_periods),
            "window_count": int(len(replay_windows)),
        },
        "methods_used": [METHOD_HISTORICAL_SCENARIO_REPLAY],
        "limitations": [
            "Historical replay compares observed windows; it is not a counterfactual causal simulation.",
            "Results depend on the chosen windows and the frequency of the local input panel.",
        ],
    }


def compare_analog_windows(
    data: pd.DataFrame,
    *,
    date_col: str = "date",
    value_cols: Iterable[str],
    windows: Iterable[dict[str, Any]],
    current_window: dict[str, Any],
    top_n_divergences: int = 3,
) -> dict[str, Any]:
    """Compare current macro averages against named historical analog windows.

    Distances are Euclidean z-score distances over variables with finite
    current, analog, and sample-standard-deviation values. Variables without
    usable variation are excluded instead of silently contributing zero.
    """

    values = [str(column) for column in value_cols if str(column)]
    if not values:
        raise ValueError("value_cols must include at least one column")
    if top_n_divergences < 1:
        raise ValueError("top_n_divergences must be at least 1")

    frame = _as_ordered_frame(data, date_col, values)
    stds = {
        column: _finite_float(frame[column].std(skipna=True))
        for column in values
    }

    def window_profile(window_spec: dict[str, Any]) -> dict[str, Any]:
        label = str(window_spec.get("label") or window_spec.get("name") or "window")
        start = pd.Timestamp(window_spec.get("start"))
        end = pd.Timestamp(window_spec.get("end"))
        window = frame[(frame[date_col] >= start) & (frame[date_col] <= end)]
        means = {
            column: _finite_float(window[column].mean(skipna=True))
            for column in values
        }
        return {
            "label": label,
            "start": start.date().isoformat(),
            "end": end.date().isoformat(),
            "observation_count": int(len(window)),
            "values": means,
        }

    current_profile = window_profile({**current_window, "label": "current"})
    analog_profiles = [window_profile(item) for item in windows]
    ranking: list[dict[str, Any]] = []

    for profile in analog_profiles:
        divergences: list[dict[str, Any]] = []
        squared_distance = 0.0
        for column in values:
            std = stds.get(column)
            current_value = _finite_float(current_profile["values"].get(column))
            analog_value = _finite_float(profile["values"].get(column))
            if (
                std is None
                or std <= 0
                or current_value is None
                or analog_value is None
            ):
                continue
            diff_std = (current_value - analog_value) / std
            squared_distance += diff_std**2
            divergences.append(
                {
                    "variable": column,
                    "current": current_value,
                    "analog": analog_value,
                    "diff_std": _finite_float(diff_std),
                }
            )

        divergences.sort(
            key=lambda item: abs(float(item["diff_std"] or 0.0)),
            reverse=True,
        )
        distance = _finite_float(np.sqrt(squared_distance)) if divergences else None
        normalized_similarity = (
            _finite_float(100.0 / (1.0 + max(float(distance), 0.0)))
            if distance is not None
            else None
        )
        label = str(profile["label"])
        ranking.append(
            {
                "analog": label,
                "distance": distance,
                "raw_distance": distance,
                "distance_score": distance,
                "normalized_similarity": normalized_similarity,
                "common_variables": [item["variable"] for item in divergences],
                "top_divergences": divergences[:top_n_divergences],
                "divergence_facts": divergences[:top_n_divergences],
                "status": "ok" if divergences else "insufficient_common_variables",
            }
        )
    ranking.sort(
        key=lambda item: item["distance"] if item["distance"] is not None else np.inf
    )
    return {
        "analog_similarity_ranking": ranking,
        "analog_profiles": {
            profile["label"]: profile["values"]
            for profile in [*analog_profiles, current_profile]
        },
        "comparison_design": {
            "date_col": date_col,
            "value_cols": values,
            "current_window": {
                "start": pd.Timestamp(current_window.get("start")).date().isoformat(),
                "end": pd.Timestamp(current_window.get("end")).date().isoformat(),
            },
            "distance": "euclidean_z_distance_on_window_means",
            "standardization_sample": "all rows with usable observations",
        },
        "methods_used": [METHOD_ANALOG_WINDOW_COMPARISON],
        "limitations": [
            "Analog distances compare window-average conditions, not causal mechanisms.",
            "Variables with missing means or zero sample variation are excluded from each distance.",
        ],
    }


def _fit_ols_arrays(
    y: np.ndarray,
    x: np.ndarray,
    feature_names: list[str],
    *,
    robust_cov: str = "HC1",
) -> dict[str, Any]:
    parameter_names = ["const", *feature_names]
    public_module = sys.modules.get("agents.quant_macro_stats")
    statsmodels_api = getattr(public_module, "_statsmodels_api", _statsmodels_api)
    scipy_stats = getattr(public_module, "_scipy_stats", _scipy_stats)
    if statsmodels_api is not None:
        model = statsmodels_api.OLS(y, x, missing="drop").fit(cov_type=robust_cov)
        coefficients = [
            {
                "term": term,
                "estimate": _finite_float(model.params[index]),
                "std_error": _finite_float(model.bse[index]),
                "p_value": _finite_float(model.pvalues[index]),
            }
            for index, term in enumerate(parameter_names)
        ]
        residuals = np.asarray(model.resid, dtype=float)
        return {
            "coefficients": coefficients,
            "diagnostics": {
                "nobs": int(model.nobs),
                "r_squared": _finite_float(model.rsquared),
                "df_resid": _finite_float(model.df_resid),
                "residual_std_error": _finite_float(np.sqrt(np.mean(residuals**2))),
                "covariance": robust_cov,
            },
            "method_notes": [f"statsmodels_ols_covariance:{robust_cov}"],
            "_prediction_model": model,
        }

    beta, _, _, _ = np.linalg.lstsq(x, y, rcond=None)
    fitted = x @ beta
    residuals = y - fitted
    nobs, k_params = x.shape
    df_resid = max(nobs - k_params, 0)
    sigma2 = float(np.sum(residuals**2) / df_resid) if df_resid else 0.0
    try:
        covariance = sigma2 * np.linalg.pinv(x.T @ x)
        std_errors = np.sqrt(np.diag(covariance))
    except np.linalg.LinAlgError:
        std_errors = np.full(k_params, np.nan)

    p_values: list[float | None] = []
    for estimate, std_error in zip(beta, std_errors, strict=False):
        if not np.isfinite(std_error) or std_error == 0 or df_resid <= 0 or scipy_stats is None:
            p_values.append(None)
        else:
            p_values.append(float(2 * scipy_stats.t.sf(abs(estimate / std_error), df_resid)))

    total_ss = float(np.sum((y - np.mean(y)) ** 2))
    residual_ss = float(np.sum(residuals**2))
    r_squared = 1 - residual_ss / total_ss if total_ss else None
    return {
        "coefficients": [
            {
                "term": term,
                "estimate": _finite_float(beta[index]),
                "std_error": _finite_float(std_errors[index]),
                "p_value": p_values[index],
            }
            for index, term in enumerate(parameter_names)
        ],
        "diagnostics": {
            "nobs": int(nobs),
            "r_squared": _finite_float(r_squared),
            "df_resid": int(df_resid),
            "residual_std_error": _finite_float(np.sqrt(np.mean(residuals**2))),
            "covariance": "classic",
        },
        "method_notes": [
            "statsmodels_unavailable: used numpy.linalg.lstsq with classic standard errors."
        ],
        "_prediction_model": None,
    }


def ols_regression(
    data: pd.DataFrame,
    target_col: str,
    feature_cols: Iterable[str],
    *,
    date_col: str = "date",
    robust_cov: str = "HC1",
    min_observations: int = 8,
) -> dict[str, Any]:
    """Return a stable JSON-ready OLS regression summary for local data."""

    features = list(feature_cols)
    if not features:
        raise ValueError("feature_cols must include at least one feature")
    frame = _clean_regression_frame(data, date_col, target_col, features)
    if len(frame) < min_observations:
        raise ValueError(
            f"At least {min_observations} complete observations are required; got {len(frame)}"
        )

    x = np.column_stack([np.ones(len(frame)), frame[features].to_numpy(dtype=float)])
    y = frame[target_col].to_numpy(dtype=float)
    fitted = _fit_ols_arrays(y, x, features, robust_cov=robust_cov)
    fitted.pop("_prediction_model", None)
    stationarity = [
        _stationarity_check(frame[column], column) for column in [target_col, *features]
    ]

    return {
        "model_spec": _model_spec(target_col, features),
        "estimation_window": {
            "start": _iso_date(frame[date_col].iloc[0]),
            "end": _iso_date(frame[date_col].iloc[-1]),
            "observations": int(len(frame)),
        },
        "target_variable": target_col,
        "features": features,
        "coefficients": fitted["coefficients"],
        "diagnostics": {
            **fitted["diagnostics"],
            "stationarity": stationarity,
            "warnings": [
                check["warning"]
                for check in stationarity
                if check.get("warning") and check.get("status") == "warning"
            ],
        },
        "methods_used": [METHOD_OLS_REGRESSION, METHOD_STATIONARITY_CHECK],
        "method_notes": fitted["method_notes"],
        "caveats": [
            "Regression coefficients are conditional associations, not proof of causality.",
            "Forecasts assume the latest predictor values remain informative for future horizons.",
        ],
    }


def direct_ols_forecast(
    data: pd.DataFrame,
    target_col: str,
    feature_cols: Iterable[str],
    *,
    date_col: str = "date",
    horizon: int = 6,
    include_target_lag: bool = True,
    min_observations: int = 12,
    prediction_interval: float = 0.95,
    run_backtests: bool = True,
) -> dict[str, Any]:
    """
    Forecast ``target_col`` h periods ahead with direct OLS models.

    Each horizon fits ``target(t+h) ~ predictors(t)`` on local data and predicts
    from the latest complete predictor row. The result is JSON-ready and never
    includes raw statsmodels result objects.
    """

    if horizon < 1:
        raise ValueError("horizon must be at least 1")
    if not 0 < prediction_interval < 1:
        raise ValueError("prediction_interval must be between 0 and 1")

    requested_features = list(dict.fromkeys(feature_cols))
    if not requested_features:
        raise ValueError("feature_cols must include at least one feature")
    base_features = [feature for feature in requested_features if feature != target_col]
    if not base_features and not include_target_lag:
        raise ValueError("feature_cols must include at least one non-target feature")
    model_features = (
        [target_col, *base_features]
        if include_target_lag
        else base_features
    )
    frame = _clean_regression_frame(data, date_col, target_col, base_features)
    if len(frame) < min_observations + horizon:
        raise ValueError(
            "Not enough complete observations for requested forecast: "
            f"need at least {min_observations + horizon}, got {len(frame)}"
        )

    latest_predictors = frame[model_features].iloc[-1].to_numpy(dtype=float)
    latest_x = np.concatenate([[1.0], latest_predictors])
    alpha = 1 - prediction_interval
    z_score = _normal_quantile(1 - alpha / 2)
    interval_pct = int(round(prediction_interval * 100))
    lower_key = f"lower_{interval_pct}"
    upper_key = f"upper_{interval_pct}"

    forecast_rows: list[dict[str, Any]] = []
    diagnostics_by_horizon: list[dict[str, Any]] = []
    method_notes: list[str] = []
    for step in range(1, horizon + 1):
        working = frame.copy()
        working["_target_future"] = working[target_col].shift(-step)
        working = working.dropna(subset=["_target_future", *model_features]).reset_index(drop=True)
        if len(working) < min_observations:
            forecast_rows.append(
                {
                    "horizon": step,
                    "forecast_period": None,
                    "forecast": None,
                    "lower": None,
                    "upper": None,
                    lower_key: None,
                    upper_key: None,
                    "prediction_interval": prediction_interval,
                    "status": "insufficient_observations",
                }
            )
            continue

        x = np.column_stack([np.ones(len(working)), working[model_features].to_numpy(dtype=float)])
        y = working["_target_future"].to_numpy(dtype=float)
        fitted = _fit_ols_arrays(y, x, model_features)
        method_notes.extend(fitted["method_notes"])
        forecast = float(latest_x @ np.array([item["estimate"] for item in fitted["coefficients"]]))
        residual_std = fitted["diagnostics"]["residual_std_error"] or 0.0
        margin = float(z_score * residual_std)
        latest_date = pd.Timestamp(frame[date_col].iloc[-1])
        forecast_period = (latest_date + pd.DateOffset(months=step)).date().isoformat()

        lower = _finite_float(forecast - margin)
        upper = _finite_float(forecast + margin)
        forecast_rows.append(
            {
                "horizon": step,
                "date": forecast_period,
                "forecast_period": forecast_period,
                "forecast": _finite_float(forecast),
                "lower": lower,
                "upper": upper,
                lower_key: lower,
                upper_key: upper,
                "prediction_interval": prediction_interval,
                "status": "ok",
            }
        )
        diagnostics_by_horizon.append(
            {
                "horizon": step,
                **fitted["diagnostics"],
                "coefficients": fitted["coefficients"],
            }
        )

    stationarity = [
        _stationarity_check(frame[column], column) for column in [target_col, *base_features]
    ]
    walk_forward_rows: list[dict[str, Any]] = []
    model_validation_rows: list[dict[str, Any]] = []
    if run_backtests:
        for step in range(1, horizon + 1):
            backtest = walk_forward_ols_backtest(
                frame,
                target_col,
                base_features,
                date_col=date_col,
                horizon=step,
                include_target_lag=include_target_lag,
                min_observations=min_observations,
            )
            compact_backtest = {
                key: value
                for key, value in backtest.items()
                if key
                in {
                    "status",
                    "prediction_horizon",
                    "validation_window",
                    "test_observations",
                    "metrics",
                    "baseline_comparison",
                    "best_model_by_mae",
                    "limitations",
                }
            }
            walk_forward_rows.append(compact_backtest)
            if backtest.get("status") == "ok":
                for item in backtest.get("model_comparison", []):
                    if isinstance(item, dict):
                        model_validation_rows.append({"horizon": step, **item})
    selected_diagnostics = next(
        (
            item
            for item in diagnostics_by_horizon
            if item.get("horizon") == horizon
        ),
        diagnostics_by_horizon[-1] if diagnostics_by_horizon else {},
    )
    compact_selected_diagnostics = {
        key: selected_diagnostics.get(key)
        for key in (
            "horizon",
            "nobs",
            "r_squared",
            "df_resid",
            "residual_std_error",
            "covariance",
        )
        if key in selected_diagnostics
    }

    return {
        "model_spec": _model_spec(target_col, model_features, forecast_horizon=horizon),
        "estimation_window": {
            "start": _iso_date(frame[date_col].iloc[0]),
            "end": _iso_date(frame[date_col].iloc[-1]),
            "observations": int(len(frame)),
        },
        "target_variable": target_col,
        "features": model_features,
        "diagnostics": {
            "horizon_models": diagnostics_by_horizon,
            "selected_horizon": horizon,
            "selected_horizon_model": compact_selected_diagnostics,
            "r_squared": compact_selected_diagnostics.get("r_squared"),
            "residual_std_error": compact_selected_diagnostics.get("residual_std_error"),
            "stationarity": stationarity,
            "warnings": [
                check["warning"]
                for check in stationarity
                if check.get("warning") and check.get("status") == "warning"
            ],
        },
        "forecast_rows": forecast_rows,
        "walk_forward_backtest_rows": walk_forward_rows,
        "model_validation_rows": model_validation_rows,
        "methods_used": [
            METHOD_DIRECT_OLS_FORECAST,
            *([METHOD_WALK_FORWARD_OLS_BACKTEST] if run_backtests else []),
            METHOD_OLS_REGRESSION,
            METHOD_STATIONARITY_CHECK,
        ],
        "method_notes": list(dict.fromkeys(method_notes)),
        "caveats": [
            "This is a predictive reduced-form model, not evidence that predictors causally move the target.",
            "Intervals are simple residual-error bands and do not capture all parameter or data-revision uncertainty.",
            "Macroeconomic level regressions can be trend-sensitive; review stationarity diagnostics before overclaiming.",
        ],
    }

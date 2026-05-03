"""Execution-summary validation and legacy handoff normalization."""
from .shared import *
from .shared import (
    _adfuller,
    _as_ordered_frame,
    _clean_regression_frame,
    _direction_multiplier,
    _finite_float,
    _iso_date,
    _require_columns,
    _scipy_stats,
    _statsmodels_api,
)
from .scenarios import validate_scenario_table

def _first_mapping(*values: Any) -> dict[str, Any] | None:
    for value in values:
        if isinstance(value, dict) and value:
            return value
    return None


def _first_non_empty_list(*values: Any) -> list[Any] | None:
    for value in values:
        if isinstance(value, list) and value:
            return value
    return None


def _first_non_empty_replay(*values: Any) -> list[Any] | dict[str, Any] | None:
    for value in values:
        if isinstance(value, list) and value:
            return value
        if isinstance(value, dict) and value:
            return value
    return None


def _signal_framework_payload(summary: dict[str, Any]) -> dict[str, Any] | None:
    """Return the canonical signal-framework payload when a helper produced one."""

    candidates: list[Any] = [
        summary.get("historical_simulations"),
        summary.get("signal_framework_backtest"),
        summary.get("signal_framework"),
    ]
    signal_backtest = summary.get("signal_backtest")
    if isinstance(signal_backtest, dict):
        candidates.extend(
            [
                signal_backtest,
                signal_backtest.get("historical_simulations"),
            ]
        )

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        payload = candidate.get("signal_framework_backtest")
        if payload is None and isinstance(candidate.get("historical_simulations"), dict):
            payload = candidate["historical_simulations"].get("signal_framework_backtest")
        if payload is None:
            payload = candidate
        if isinstance(payload, dict) and payload.get("status") == "ok":
            return payload
    return None


def _signal_framework_summary(payload: dict[str, Any]) -> dict[str, Any]:
    correct = _finite_float(payload.get("recession_calls_correct"))
    false_alarms = _finite_float(payload.get("false_alarms"))
    precision = None
    if correct is not None and false_alarms is not None and correct + false_alarms > 0:
        precision = correct / (correct + false_alarms)
    current_signal = payload.get("current_signal")
    if not isinstance(current_signal, dict):
        current_signal = {}
    return {
        "method": METHOD_SIGNAL_FRAMEWORK_BACKTEST,
        "observations": int(payload.get("total_observations") or 0),
        "recession_count": int(payload.get("recession_count") or 0),
        "recession_calls_correct": int(payload.get("recession_calls_correct") or 0),
        "false_alarms": int(payload.get("false_alarms") or 0),
        "true_positive_rate": _finite_float(payload.get("true_positive_rate")),
        "precision": _finite_float(precision),
        "threshold": _finite_float(payload.get("threshold")),
        "lookback_periods": int(payload.get("lookback_periods") or 0),
        "false_alarm_lookahead_periods": int(
            payload.get("false_alarm_lookahead_periods") or 0
        ),
        "current_signal": {
            "score": _finite_float(current_signal.get("score")),
            "interpretation": current_signal.get("interpretation"),
            "components_triggered": current_signal.get("components_triggered", []),
            "date": current_signal.get("date"),
        },
        "pre_recession_scores": payload.get("pre_recession_scores", {}),
        "false_alarm_episodes": payload.get("false_alarm_episodes", []),
        "methods_used": [METHOD_SIGNAL_FRAMEWORK_BACKTEST],
    }


def _normalize_validation_handoff(summary: dict[str, Any]) -> None:
    """Promote real nested validation artifacts to canonical QA/writer keys."""

    direct_nested = [
        value
        for key in (
            "composite_predictive_indicator",
            "composite_indicator",
            "forecast_diagnostics",
            "event_signal_backtest",
            "statistical_summary",
            "unemployment_forecast",
            "forecast",
            "recession_risk",
            "historical_scenario_replay",
            "historical_replay",
            "regime_classification",
            "composite",
            "signal_framework",
            "signal_backtest",
            "scenario",
            "scenarios",
        )
        if isinstance((value := summary.get(key)), dict)
    ]
    nested = list(_iter_nested_mappings(*direct_nested))

    signal_payload = _signal_framework_payload(summary)
    if signal_payload is not None:
        summary["signal_framework_summary"] = _signal_framework_summary(signal_payload)

    backtest_summary = _first_mapping(
        summary.get("backtest_summary"),
        *(payload.get("backtest_summary") for payload in nested),
        *(payload.get("backtest") for payload in nested),
    )
    if backtest_summary is not None:
        summary["backtest_summary"] = backtest_summary

    model_comparison = _first_non_empty_list(
        summary.get("model_comparison"),
        *(payload.get("model_comparison") for payload in nested),
    )
    if model_comparison is not None:
        summary["model_comparison"] = model_comparison

    historical_simulations = _first_non_empty_replay(
        summary.get("historical_simulations"),
        *(payload.get("historical_simulations") for payload in nested),
        *(payload.get("historical_analogs") for payload in nested),
        *(_historical_simulations_from_score_history(payload) for payload in nested),
        summary.get("prior_downturn_comparison"),
    )
    if historical_simulations is not None:
        summary["historical_simulations"] = historical_simulations

    scenario_table = _first_non_empty_list(
        summary.get("scenario_table"),
        *(payload.get("scenario_table") for payload in nested),
    )
    if scenario_table is not None:
        try:
            summary["scenario_table"] = validate_scenario_table(scenario_table)
            if not isinstance(summary.get("scenario_analysis"), dict):
                summary["scenario_analysis"] = {
                    "topic": "scenario_stress_test",
                    "scenario_table": summary["scenario_table"],
                    "methods_used": [METHOD_SCENARIO_STRESS_TEST],
                }
        except ValueError:
            pass

    _normalize_macro_regime_validation(summary)
    _normalize_recession_window_replay(summary)
    _normalize_signal_stack_replay(summary)
    backtest_summary = summary.get("backtest_summary")
    model_comparison = summary.get("model_comparison")
    historical_simulations = summary.get("historical_simulations")

    methods = summary.setdefault("methods_used", [])
    if isinstance(methods, str):
        methods = [methods]
        summary["methods_used"] = methods
    if isinstance(methods, list):
        for payload in (
            backtest_summary,
            {"model_comparison": model_comparison},
            *nested,
        ):
            payload_methods = payload.get("methods_used") if isinstance(payload, dict) else None
            if isinstance(payload_methods, str):
                payload_methods = [payload_methods]
            if isinstance(payload_methods, list):
                for method in payload_methods:
                    if isinstance(method, str) and method not in methods:
                        methods.append(method)


def _iter_nested_mappings(*values: Any, max_depth: int = 3) -> Iterable[dict[str, Any]]:
    """Yield mapping payloads reachable from helper handoff containers."""

    def walk(value: Any, depth: int) -> Iterable[dict[str, Any]]:
        if depth > max_depth or not isinstance(value, dict):
            return
        yield value
        for child in value.values():
            if isinstance(child, dict):
                yield from walk(child, depth + 1)

    for value in values:
        yield from walk(value, 0)


def _historical_simulations_from_score_history(
    payload: dict[str, Any],
) -> list[dict[str, Any]] | None:
    """Convert composite score history with outcomes into compact replay rows."""

    history = payload.get("score_history")
    if not isinstance(history, list) or not history:
        return None
    thresholds = payload.get("thresholds")
    high_threshold = (
        thresholds.get("high") if isinstance(thresholds, dict) else None
    )
    rows: list[dict[str, Any]] = []
    for raw in history:
        if not isinstance(raw, dict):
            continue
        date = raw.get("date")
        score = _finite_float(raw.get("composite_index"))
        percentile = _finite_float(raw.get("composite_percentile_0_100"))
        target_event = raw.get("target_event")
        if not isinstance(target_event, bool):
            continue
        predicted_event = (
            score is not None
            and (threshold := _finite_float(high_threshold)) is not None
            and score >= threshold
        )
        if not target_event and not predicted_event:
            continue
        if predicted_event and target_event:
            classification = "hit"
        elif predicted_event:
            classification = "false_positive"
        else:
            classification = "miss"
        rows.append(
            {
                "date": str(date),
                "status": "ok",
                "classification": classification,
                "signal_percentile_0_100": percentile,
                "composite_index": score,
                "target_value": _finite_float(raw.get("target_value")),
                "target_future": _finite_float(raw.get("target_future")),
            }
        )
    if not rows:
        return None
    return rows[-60:]


def _normalize_macro_regime_validation(summary: dict[str, Any]) -> None:
    """Preserve custom current-vs-history regime comparisons as validation artifacts."""

    regime = summary.get("macro_regime_comparison")
    if not isinstance(regime, dict):
        return

    current = regime.get("current")
    baseline = (
        regime.get("pre_recession_avg")
        or regime.get("pre_recession_average")
        or regime.get("historical_average")
    )
    if not isinstance(current, dict) or not isinstance(baseline, dict):
        return

    comparable_keys = sorted(set(current).intersection(baseline))
    if not comparable_keys:
        return

    if not isinstance(summary.get("backtest_summary"), dict):
        summary["backtest_summary"] = {
            "method": "current_vs_historical_regime_replay",
            "comparison": "current conditions versus historical baseline averages",
            "current_values": {
                key: current.get(key) for key in comparable_keys if current.get(key) is not None
            },
            "historical_baseline_values": {
                key: baseline.get(key) for key in comparable_keys if baseline.get(key) is not None
            },
            "n_indicators_compared": len(comparable_keys),
            "limitations": (
                "Descriptive historical replay, not an out-of-sample forecast or causal estimate."
            ),
            "methods_used": ["current_vs_historical_regime_replay"],
        }

    if not summary.get("historical_simulations"):
        summary["historical_simulations"] = {
            "method": "current_vs_historical_regime_replay",
            "comparison_period": (
                "pre_recession_avg"
                if "pre_recession_avg" in regime or "pre_recession_average" in regime
                else "historical_average"
            ),
            "current_values": summary["backtest_summary"].get("current_values", {}),
            "historical_baseline_values": summary["backtest_summary"].get(
                "historical_baseline_values", {}
            ),
            "n_indicators_compared": len(comparable_keys),
            "note": "Generated from macro_regime_comparison current and baseline values.",
        }


def _normalize_recession_window_replay(summary: dict[str, Any]) -> None:
    """Promote real recession-window replay rows to QA-visible validation fields."""

    if summary.get("backtest_summary") and summary.get("historical_simulations"):
        return

    pre_windows = summary.get("pre_recession_windows")
    forward_outcomes = summary.get("forward_outcomes")
    if not isinstance(pre_windows, dict) or not isinstance(forward_outcomes, dict):
        return

    rows: list[dict[str, Any]] = []
    for window_start, pre_values in pre_windows.items():
        if not isinstance(pre_values, dict):
            continue
        outcomes = forward_outcomes.get(window_start)
        if not isinstance(outcomes, dict):
            continue
        clean_pre = {
            str(key): value
            for key, value in pre_values.items()
            if value is not None
        }
        clean_outcomes = {
            str(key): value
            for key, value in outcomes.items()
            if value is not None
        }
        if clean_pre or clean_outcomes:
            rows.append(
                {
                    "window_start": str(window_start),
                    "pre_window_values": clean_pre,
                    "subsequent_outcomes": clean_outcomes,
                }
            )

    if not rows:
        return

    if not summary.get("historical_simulations"):
        summary["historical_simulations"] = rows

    if not isinstance(summary.get("backtest_summary"), dict):
        outcome_keys = sorted(
            {
                key
                for row in rows
                for key in row.get("subsequent_outcomes", {})
            }
        )
        summary["backtest_summary"] = {
            "method": "historical_recession_window_replay",
            "status": "descriptive_replay",
            "window_count": len(rows),
            "outcome_fields": outcome_keys,
            "replay_window": "12 months before recession starts to 12 months after",
            "limitations": (
                "Descriptive historical replay from observed recession windows; "
                "not an out-of-sample forecast, causal estimate, or validated "
                "nearest-neighbor model."
            ),
            "methods_used": [METHOD_HISTORICAL_SCENARIO_REPLAY],
        }

    methods = summary.setdefault("methods_used", [])
    if isinstance(methods, str):
        methods = [methods]
        summary["methods_used"] = methods
    if isinstance(methods, list) and METHOD_HISTORICAL_SCENARIO_REPLAY not in methods:
        methods.append(METHOD_HISTORICAL_SCENARIO_REPLAY)


def _normalize_signal_stack_replay(summary: dict[str, Any]) -> None:
    """Promote generated signal-stack metrics into canonical QA validation fields."""

    lead_signals = summary.get("recession_lead_signals")
    if not isinstance(lead_signals, dict) or not lead_signals:
        return

    rows: list[dict[str, Any]] = []
    for raw_key, raw_signals in sorted(lead_signals.items()):
        if isinstance(raw_signals, list):
            signals = [str(signal) for signal in raw_signals if str(signal)]
        else:
            signals = []
        key = str(raw_key)
        event, _, horizon = key.rpartition("_")
        rows.append(
            {
                "event": event or key,
                "lead_horizon": horizon if event else None,
                "signals_flashing": signals,
                "signal_count": len(signals),
            }
        )

    if rows and not summary.get("historical_simulations"):
        summary["historical_simulations"] = rows

    metric_keys = (
        "composite_precision",
        "composite_recall",
        "composite_fpr",
        "composite_accuracy",
        "false_positive_count",
        "true_positive_count",
        "false_negative_count",
    )
    metrics = {
        key: numeric
        for key in metric_keys
        if (numeric := _finite_float(summary.get(key))) is not None
    }
    if metrics and not isinstance(summary.get("backtest_summary"), dict):
        summary["backtest_summary"] = {
            "method": METHOD_EVENT_SIGNAL_BACKTEST,
            "status": "descriptive_signal_stack_backtest",
            "metrics": metrics,
            "historical_replay_rows": len(rows),
            "limitations": (
                "Generated from a historical signal-stack evaluation over observed "
                "recession outcomes; not a causal model or prospective "
                "out-of-sample forecast."
            ),
            "methods_used": [METHOD_EVENT_SIGNAL_BACKTEST],
        }

    methods = summary.setdefault("methods_used", [])
    if isinstance(methods, str):
        methods = [methods]
        summary["methods_used"] = methods
    if isinstance(methods, list):
        for method in (METHOD_EVENT_SIGNAL_BACKTEST, METHOD_HISTORICAL_SCENARIO_REPLAY):
            if method not in methods:
                methods.append(method)


def _normalize_legacy_scenario_summary(summary: dict[str, Any]) -> None:
    """Preserve canonical scenario handoff fields from common generated shapes."""

    if "scenario_table" in summary or "scenarios" not in summary:
        return

    scenarios = summary.get("scenarios")
    if isinstance(scenarios, dict):
        rows = [row for row in scenarios.values() if isinstance(row, dict)]
    elif isinstance(scenarios, list):
        rows = [row for row in scenarios if isinstance(row, dict)]
    else:
        return

    try:
        summary["scenario_table"] = validate_scenario_table(rows)
    except ValueError:
        return

    methods = summary.setdefault("methods_used", [])
    if isinstance(methods, str):
        methods = [methods]
        summary["methods_used"] = methods
    if isinstance(methods, list) and METHOD_SCENARIO_STRESS_TEST not in methods:
        methods.append(METHOD_SCENARIO_STRESS_TEST)

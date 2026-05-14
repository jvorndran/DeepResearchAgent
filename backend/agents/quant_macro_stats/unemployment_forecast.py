"""Deterministic unemployment forecast-overlay chart artifacts."""

from __future__ import annotations

from functools import reduce
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .forecasting import direct_ols_forecast, event_signal_backtest, walk_forward_ols_backtest
from .outputs import save_quant_outputs

_PALETTE = ["#2563eb", "#f59e0b", "#10b981", "#ef4444", "#7c3aed", "#0891b2"]
_METHOD = "deterministic_unemployment_forecast_chart_pack"


def _matching_key(data_files: dict[str, str], candidates: tuple[str, ...]) -> str | None:
    normalized = {str(key).upper(): str(key) for key in data_files}
    for candidate in candidates:
        candidate_upper = candidate.upper()
        for key_upper, original_key in normalized.items():
            if key_upper == candidate_upper or key_upper.startswith(f"{candidate_upper}_"):
                return original_key
        for original_key, path_text in data_files.items():
            stem = Path(str(path_text)).stem.upper()
            if candidate_upper in stem:
                return str(original_key)
    return None


def _read_monthly_series(path: str, key: str) -> pd.DataFrame:
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
    monthly = (
        pd.DataFrame({"date": dates, key: values})
        .dropna(subset=["date"])
        .sort_values("date")
        .set_index("date")[[key]]
        .resample("MS")
        .mean(numeric_only=True)
        .reset_index()
    )
    return monthly.dropna(subset=[key]).reset_index(drop=True)


def _date_label(value: Any) -> str:
    timestamp = pd.Timestamp(value)
    return f"{timestamp.year:04d}-{timestamp.month:02d}"


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def _round(value: Any, digits: int = 3) -> float | None:
    number = _finite(value)
    return None if number is None else round(number, digits)


def _positive(value: Any, digits: int = 3) -> float:
    number = _finite(value)
    if number is None:
        return 1.0
    return round(max(1.0, abs(number)), digits)


def _stress_series(series: pd.Series, *, high_is_stress: bool) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    finite = values.dropna()
    if finite.empty:
        return pd.Series([50.0] * len(values), index=values.index)
    low = float(finite.quantile(0.10))
    high = float(finite.quantile(0.90))
    if high <= low:
        return pd.Series([50.0] * len(values), index=values.index)
    score = (values - low) / (high - low) * 100.0
    if not high_is_stress:
        score = 100.0 - score
    return score.clip(lower=0.0, upper=100.0)


def _records(frame: pd.DataFrame, columns: list[str]) -> list[dict[str, Any]]:
    rows = frame[["date", *columns]].dropna(how="all", subset=columns).copy()
    records: list[dict[str, Any]] = []
    for _, row in rows.iterrows():
        record: dict[str, Any] = {"date": _date_label(row["date"])}
        for column in columns:
            record[column] = _round(row.get(column))
        records.append(record)
    return records


def _latest_score(panel: pd.DataFrame, column: str) -> float:
    values = pd.to_numeric(panel[column], errors="coerce").dropna() if column in panel else pd.Series(dtype=float)
    if values.empty:
        return 50.0
    return round(float(values.iloc[-1]), 1)


def _comparison_rows(model_comparison: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows_by_horizon: dict[int, dict[str, Any]] = {}
    model_keys = {
        "direct_ols": "ols_mae",
        "baseline_last_value": "last_value_mae",
        "baseline_train_mean": "train_mean_mae",
    }
    for item in model_comparison:
        horizon = int(item.get("horizon") or 0)
        model = str(item.get("model") or "")
        key = model_keys.get(model)
        mae = _round(item.get("mae"))
        if not horizon or key is None or mae is None:
            continue
        row = rows_by_horizon.setdefault(horizon, {"horizon": f"{horizon}m"})
        row[key] = mae
    return [rows_by_horizon[horizon] for horizon in sorted(rows_by_horizon)]


def _forecast_band_rows(
    panel: pd.DataFrame,
    forecast_table: list[dict[str, Any]],
    latest_unrate: float,
) -> list[dict[str, Any]]:
    rows = [
        {
            "date": _date_label(row["date"]),
            "actual": _round(row.get("UNRATE")),
            "forecast": None,
            "lower": None,
            "upper": None,
            "last_value_baseline": None,
        }
        for _, row in panel.dropna(subset=["UNRATE"]).tail(72).iterrows()
    ]
    if rows:
        rows[-1]["forecast"] = rows[-1]["actual"]
        rows[-1]["lower"] = rows[-1]["actual"]
        rows[-1]["upper"] = rows[-1]["actual"]
        rows[-1]["last_value_baseline"] = rows[-1]["actual"]
    for item in forecast_table:
        forecast = _round(item.get("forecast"))
        if forecast is None:
            continue
        rows.append(
            {
                "date": str(item.get("date") or item.get("forecast_period")),
                "actual": None,
                "forecast": forecast,
                "lower": _round(item.get("lower")),
                "upper": _round(item.get("upper")),
                "last_value_baseline": _round(latest_unrate),
            }
        )
    return rows


def _backtest_rows(backtest: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in backtest.get("backtest_table", []):
        rows.append(
            {
                "date": str(item.get("target_date")),
                "actual": _round(item.get("actual")),
                "model_fitted": _round(item.get("forecast")),
                "last_value_baseline": _round(item.get("baseline_last_value")),
            }
        )
    return rows


def _scatter_rows(backtest: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in backtest.get("backtest_table", []):
        actual = _finite(item.get("actual"))
        forecast = _finite(item.get("forecast"))
        if actual is None or forecast is None:
            continue
        error = forecast - actual
        rows.append(
            {
                "actual": round(actual, 3),
                "forecast": round(forecast, 3),
                "abs_error": round(max(abs(error), 0.05), 3),
                "color": "#ef4444" if error > 0 else "#2563eb",
            }
        )
    return rows


def _coefficient_importance(
    forecast_result: dict[str, Any],
    forecast_frame: pd.DataFrame,
    terms: list[str],
) -> dict[str, float]:
    models = forecast_result.get("diagnostics", {}).get("horizon_models", [])
    selected = next(
        (item for item in models if item.get("horizon") == 6),
        models[-1] if models else {},
    )
    coefs = {
        str(item.get("term")): abs(float(item.get("estimate") or 0.0))
        for item in selected.get("coefficients", [])
        if isinstance(item, dict)
    }
    raw: dict[str, float] = {}
    for term in terms:
        scale = float(pd.to_numeric(forecast_frame[term], errors="coerce").std(skipna=True) or 0.0)
        raw[term] = coefs.get(term, 0.0) * scale
    max_value = max(raw.values()) if raw else 0.0
    if max_value <= 0:
        return {term: 1.0 for term in terms}
    return {term: round(max(1.0, value / max_value * 100.0), 1) for term, value in raw.items()}


def build_unemployment_forecast_chart_pack_outputs(
    data_files: dict[str, str],
    output_dir: str | Path,
    *,
    query: str | None = None,
) -> dict[str, Any]:
    """Build governed unemployment forecast charts from local labor CSV files."""

    required = {
        "UNRATE": _matching_key(data_files, ("UNRATE", "LNS14000000")),
        "PAYEMS": _matching_key(data_files, ("PAYEMS",)),
    }
    missing = [name for name, key in required.items() if key is None]
    if missing:
        raise ValueError(
            f"missing required series for unemployment forecast chart pack: {', '.join(missing)}"
        )
    optional = {
        "ICSA": _matching_key(data_files, ("ICSA", "IC4WSA")),
        "U6RATE": _matching_key(data_files, ("U6RATE",)),
        "DGS10": _matching_key(data_files, ("DGS10", "GS10")),
        "FEDFUNDS": _matching_key(data_files, ("FEDFUNDS",)),
        "NROU": _matching_key(data_files, ("NROU",)),
        "CPIAUCSL": _matching_key(data_files, ("CPIAUCSL", "PCEPI")),
        "GDPC1": _matching_key(data_files, ("GDPC1", "GDP")),
    }

    frames = [
        _read_monthly_series(data_files[source_key], target_key)
        for target_key, source_key in required.items()
        if source_key is not None
    ]
    for target_key, source_key in optional.items():
        if source_key is not None:
            frames.append(_read_monthly_series(data_files[source_key], target_key))

    panel = reduce(lambda left, right: left.merge(right, on="date", how="outer"), frames)
    panel = panel.sort_values("date").reset_index(drop=True)
    for column in panel.columns:
        if column != "date":
            panel[column] = pd.to_numeric(panel[column], errors="coerce").ffill(limit=3)
    latest_core_dates = [
        panel.loc[pd.to_numeric(panel[column], errors="coerce").notna(), "date"].max()
        for column in ("UNRATE", "PAYEMS")
    ]
    latest_date = min(date for date in latest_core_dates if pd.notna(date))
    panel = panel.loc[panel["date"] <= latest_date].reset_index(drop=True)

    panel["PAYEMS_3M_PCT"] = panel["PAYEMS"].pct_change(3) * 100
    feature_cols = ["PAYEMS_3M_PCT"]
    if "ICSA" in panel:
        panel["ICSA_LOG"] = np.log(panel["ICSA"].clip(lower=1))
        panel["claims_3m_pct"] = panel["ICSA"].pct_change(3) * 100
        feature_cols.append("ICSA_LOG")
    if "U6RATE" in panel:
        feature_cols.append("U6RATE")
    if "NROU" in panel:
        panel["UNRATE_NROU_GAP"] = panel["UNRATE"] - panel["NROU"]
        feature_cols.append("UNRATE_NROU_GAP")
    if "DGS10" in panel and "FEDFUNDS" in panel:
        panel["RATE_SPREAD"] = panel["DGS10"] - panel["FEDFUNDS"]
        feature_cols.append("RATE_SPREAD")
    elif "DGS10" in panel:
        feature_cols.append("DGS10")
    elif "FEDFUNDS" in panel:
        feature_cols.append("FEDFUNDS")
    if "CPIAUCSL" in panel:
        panel["CPI_YOY"] = panel["CPIAUCSL"].pct_change(12) * 100
        feature_cols.append("CPI_YOY")
    if "GDPC1" in panel:
        panel["GDPC1_YOY"] = panel["GDPC1"].pct_change(12) * 100
        feature_cols.append("GDPC1_YOY")

    panel["unemployment_level_score"] = _stress_series(panel["UNRATE"], high_is_stress=True)
    panel["payroll_drag_score"] = _stress_series(panel["PAYEMS_3M_PCT"], high_is_stress=False)
    if "ICSA_LOG" in panel:
        panel["claims_pressure_score"] = _stress_series(panel["ICSA_LOG"], high_is_stress=True)
    if "U6RATE" in panel:
        panel["underemployment_score"] = _stress_series(panel["U6RATE"], high_is_stress=True)
    if "UNRATE_NROU_GAP" in panel:
        panel["slack_gap_score"] = _stress_series(panel["UNRATE_NROU_GAP"], high_is_stress=True)
    if "RATE_SPREAD" in panel:
        panel["rate_spread_stress_score"] = _stress_series(panel["RATE_SPREAD"], high_is_stress=False)
    elif "DGS10" in panel:
        panel["long_rate_stress_score"] = _stress_series(panel["DGS10"], high_is_stress=True)
    elif "FEDFUNDS" in panel:
        panel["policy_rate_stress_score"] = _stress_series(panel["FEDFUNDS"], high_is_stress=True)
    if "CPI_YOY" in panel:
        panel["inflation_pressure_score"] = _stress_series(panel["CPI_YOY"], high_is_stress=True)
    if "GDPC1_YOY" in panel:
        panel["growth_drag_score"] = _stress_series(panel["GDPC1_YOY"], high_is_stress=False)
    score_columns = [
        column
        for column in (
            "unemployment_level_score",
            "claims_pressure_score",
            "payroll_drag_score",
            "underemployment_score",
            "slack_gap_score",
            "rate_spread_stress_score",
            "long_rate_stress_score",
            "policy_rate_stress_score",
            "inflation_pressure_score",
            "growth_drag_score",
        )
        if column in panel
    ]
    panel["composite_signal"] = panel[score_columns].mean(axis=1)
    panel["unrate_deterioration_event"] = (panel["UNRATE"].diff(6) >= 0.4).astype(int)

    forecast_frame = panel[["date", "UNRATE", *feature_cols]].dropna(
        subset=["UNRATE", *feature_cols]
    )
    min_observations = 60 if len(forecast_frame) >= 90 else 24
    forecast_result = direct_ols_forecast(
        forecast_frame,
        target_col="UNRATE",
        feature_cols=feature_cols,
        date_col="date",
        horizon=6,
        include_target_lag=True,
        min_observations=min_observations,
        prediction_interval=0.95,
    )
    backtest_1m = walk_forward_ols_backtest(
        forecast_frame,
        "UNRATE",
        feature_cols,
        date_col="date",
        horizon=1,
        include_target_lag=True,
        min_observations=min_observations,
        max_table_rows=72,
    )
    backtest_6m = walk_forward_ols_backtest(
        forecast_frame,
        "UNRATE",
        feature_cols,
        date_col="date",
        horizon=6,
        include_target_lag=True,
        min_observations=min_observations,
        max_table_rows=72,
    )
    signal_backtest_frame = panel[["date", "composite_signal", "unrate_deterioration_event"]].dropna()
    try:
        signal_backtest = event_signal_backtest(
            signal_backtest_frame,
            signal_col="composite_signal",
            target_col="unrate_deterioration_event",
            date_col="date",
            threshold=65,
            direction="high",
            prediction_horizon=6,
            min_observations=min_observations,
        )
    except Exception as exc:  # pragma: no cover - defensive fallback for odd local panels
        signal_backtest = {"status": "error", "error": str(exc)}

    latest_row = panel.dropna(subset=["UNRATE"]).tail(1).iloc[0]
    latest_unrate = float(latest_row["UNRATE"])
    forecast_table = forecast_result.get("forecast_table", [])
    comparison_rows = _comparison_rows(forecast_result.get("model_comparison", []))
    component_specs = [
        ("Unemployment inertia", "UNRATE", "unemployment_level_score"),
        ("Payroll momentum", "PAYEMS_3M_PCT", "payroll_drag_score"),
        ("Claims pressure", "ICSA_LOG", "claims_pressure_score"),
        ("U-6 underemployment", "U6RATE", "underemployment_score"),
        ("Natural-rate gap", "UNRATE_NROU_GAP", "slack_gap_score"),
        ("Rate-spread pressure", "RATE_SPREAD", "rate_spread_stress_score"),
        ("Long-rate pressure", "DGS10", "long_rate_stress_score"),
        ("Policy-rate pressure", "FEDFUNDS", "policy_rate_stress_score"),
        ("Inflation pressure", "CPI_YOY", "inflation_pressure_score"),
        ("Growth drag", "GDPC1_YOY", "growth_drag_score"),
    ]
    usable_components = [
        item for item in component_specs if item[1] in forecast_frame and item[2] in panel
    ]
    importance = _coefficient_importance(
        forecast_result,
        forecast_frame,
        ["UNRATE", *feature_cols],
    )
    radar_rows = [
        {
            "metric": label,
            "model_importance": importance.get(term, 1.0),
            "latest_signal": _latest_score(panel, score_col),
        }
        for label, term, score_col in usable_components
    ]
    radial_rows = [
        {
            "name": label,
            "value": round(max(1.0, row["latest_signal"]), 1),
            "color": _PALETTE[index % len(_PALETTE)],
        }
        for index, (row, (label, _, _)) in enumerate(zip(radar_rows, usable_components, strict=False))
    ]
    recent_scores = panel.tail(120)
    score_overlay_cols = [score_col for _, _, score_col in usable_components]
    score_overlay_series = [
        {
            "dataKey": score_col,
            "label": label,
            "color": _PALETTE[index % len(_PALETTE)],
            "type": "line",
        }
        for index, (label, _, score_col) in enumerate(usable_components)
    ]

    interval_widths = [
        (float(item["upper"]) - float(item["lower"]))
        for item in forecast_table
        if _finite(item.get("upper")) is not None and _finite(item.get("lower")) is not None
    ]
    horizon_6_metrics = backtest_6m.get("metrics", {}) if isinstance(backtest_6m, dict) else {}
    baseline_metrics = backtest_6m.get("baseline_comparison", {}) if isinstance(backtest_6m, dict) else {}
    uncertainty_tree = {
        "name": "Forecast uncertainty",
        "children": [
            {
                "name": "Prediction interval width",
                "value": _positive(np.mean(interval_widths) if interval_widths else None),
            },
            {
                "name": "Model backtest RMSE",
                "value": _positive(horizon_6_metrics.get("rmse")),
            },
            {
                "name": "Baseline disagreement",
                "value": _positive(
                    (baseline_metrics.get("last_value", {}) or {}).get("mae")
                    if isinstance(baseline_metrics, dict)
                    else None
                ),
            },
            {
                "name": "Signal volatility",
                "value": _positive(panel["composite_signal"].tail(24).std(skipna=True)),
            },
        ],
    }
    valid_horizons = sum(
        1
        for item in forecast_result.get("backtest_summary", {}).get("horizon_results", [])
        if item.get("status") == "ok"
    )
    sankey_nodes = [
        {"name": "Labor predictors"},
        {"name": "Direct OLS model"},
        {"name": "Naive baselines"},
        {"name": "Walk-forward validation"},
        {"name": "Six-month forecast"},
        {"name": "Governed chart pack"},
    ]
    sankey_links = [
        {"source": 0, "target": 1, "value": _positive(len(feature_cols))},
        {"source": 2, "target": 3, "value": 2},
        {"source": 1, "target": 3, "value": _positive(valid_horizons)},
        {"source": 1, "target": 4, "value": 6},
        {"source": 3, "target": 5, "value": _positive(backtest_6m.get("test_observations", 1) / 12)},
        {"source": 4, "target": 5, "value": 6},
    ]

    charts = {
        "unemployment_forecast_band": {
            "id": "unemployment_forecast_band",
            "type": "composed",
            "title": "Unemployment Forecast With 95% Band",
            "description": "Actual unemployment history is extended with the six-month direct OLS forecast, residual-error interval, and last-value baseline.",
            "xAxisKey": "date",
            "series": [
                {"dataKey": "actual", "label": "Actual UNRATE", "color": _PALETTE[0], "type": "line"},
                {"dataKey": "forecast", "label": "OLS forecast", "color": _PALETTE[3], "type": "line"},
                {"dataKey": "lower", "label": "95% lower", "color": "#94a3b8", "type": "line", "strokeDasharray": "4 4"},
                {"dataKey": "upper", "label": "95% upper", "color": "#64748b", "type": "line", "strokeDasharray": "4 4"},
                {"dataKey": "last_value_baseline", "label": "Last-value baseline", "color": _PALETTE[1], "type": "line", "strokeDasharray": "3 3"},
            ],
            "data": _forecast_band_rows(panel, forecast_table, latest_unrate),
            "referenceLines": [
                {"axis": "x", "value": _date_label(latest_date), "label": "Forecast start", "color": "#111827", "dashed": True}
            ],
            "methods_used": [_METHOD, "direct_ols_forecast"],
        },
        "actual_vs_fitted_backtest": {
            "id": "actual_vs_fitted_backtest",
            "type": "line",
            "title": "Actual Versus One-Month Fitted Values",
            "description": "Walk-forward fitted values are compared with actual unemployment and a naive last-value baseline.",
            "xAxisKey": "date",
            "series": [
                {"dataKey": "actual", "label": "Actual", "color": _PALETTE[0]},
                {"dataKey": "model_fitted", "label": "OLS fitted", "color": _PALETTE[3]},
                {"dataKey": "last_value_baseline", "label": "Last value", "color": _PALETTE[1], "strokeDasharray": "3 3"},
            ],
            "data": _backtest_rows(backtest_1m),
            "methods_used": [_METHOD, "walk_forward_ols_backtest"],
        },
        "backtest_error_by_horizon": {
            "id": "backtest_error_by_horizon",
            "type": "bar",
            "title": "Backtest MAE By Forecast Horizon",
            "description": "Direct OLS forecast errors are compared with simple last-value and train-mean baselines across horizons.",
            "xAxisKey": "horizon",
            "series": [
                {"dataKey": "ols_mae", "label": "OLS MAE", "color": _PALETTE[3]},
                {"dataKey": "last_value_mae", "label": "Last-value MAE", "color": _PALETTE[1]},
                {"dataKey": "train_mean_mae", "label": "Train-mean MAE", "color": _PALETTE[4]},
            ],
            "data": comparison_rows,
            "methods_used": [_METHOD, "walk_forward_ols_backtest"],
        },
        "fitted_vs_actual_scatter": {
            "id": "fitted_vs_actual_scatter",
            "type": "scatter",
            "title": "Six-Month Fitted Versus Actual Unemployment",
            "description": "Bubble size is absolute forecast error from the six-month walk-forward validation table.",
            "xKey": "actual",
            "yKey": "forecast",
            "xLabel": "Actual unemployment rate",
            "yLabel": "OLS fitted unemployment rate",
            "sizeKey": "abs_error",
            "colorKey": "color",
            "color": _PALETTE[0],
            "data": _scatter_rows(backtest_6m),
            "methods_used": [_METHOD, "walk_forward_ols_backtest"],
        },
        "predictor_signal_overlay": {
            "id": "predictor_signal_overlay",
            "type": "composed",
            "title": "Predictor Pressure Scores",
            "description": "Labor-market, claims, payroll, inflation, and growth signals are normalized to show whether forecast evidence is broad or concentrated.",
            "xAxisKey": "date",
            "series": score_overlay_series,
            "data": _records(recent_scores, score_overlay_cols),
            "methods_used": [_METHOD],
        },
        "predictor_contribution_radar": {
            "id": "predictor_contribution_radar",
            "type": "radar",
            "title": "Model Contribution And Latest Signal Profile",
            "description": "Standardized coefficient importance is compared with the latest normalized pressure signal.",
            "angleKey": "metric",
            "series": [
                {"dataKey": "model_importance", "label": "Model importance", "color": _PALETTE[0]},
                {"dataKey": "latest_signal", "label": "Latest signal", "color": _PALETTE[3]},
            ],
            "data": radar_rows,
            "methods_used": [_METHOD, "direct_ols_forecast"],
        },
        "current_signal_scores": {
            "id": "current_signal_scores",
            "type": "radialBar",
            "title": "Latest Unemployment Forecast Signal Scores",
            "description": "Positive 0-100 scores summarize current labor-market pressure across the model inputs.",
            "data": radial_rows,
            "methods_used": [_METHOD],
        },
        "uncertainty_signal_flow": {
            "id": "uncertainty_signal_flow",
            "type": "sankey",
            "title": "Forecast Signal Flow And Validation",
            "description": "Signal flow shows how labor predictors, naive baselines, validation evidence, and the six-month forecast feed the governed chart pack.",
            "data": {"nodes": sankey_nodes, "links": sankey_links},
            "methods_used": [_METHOD],
        },
        "forecast_uncertainty_hierarchy": {
            "id": "forecast_uncertainty_hierarchy",
            "type": "sunburst",
            "title": "Forecast Uncertainty Decomposition",
            "description": "Residual error, interval width, baseline disagreement, and signal volatility explain why the band matters for the decision.",
            "valueKey": "value",
            "data": uncertainty_tree,
            "methods_used": [_METHOD],
        },
    }
    # Keep the chart-heavy pack inside the governed 6-8 chart target while
    # preserving the requested non-time-series signal-flow family.
    charts.pop("predictor_signal_overlay")

    latest_forecast = next(
        (item for item in reversed(forecast_table) if _finite(item.get("forecast")) is not None),
        {},
    )
    execution_summary = {
        "status": "success",
        "analysis_type": "unemployment_forecast_chart_pack",
        "query": query,
        "latest_snapshot": {
            "date": _date_label(latest_date),
            "unemployment_rate": _round(latest_unrate),
            "payroll_3m_pct": _round(latest_row.get("PAYEMS_3M_PCT")),
            "initial_claims": _round(latest_row.get("ICSA")),
            "composite_signal": _round(latest_row.get("composite_signal")),
        },
        "forecast_result": forecast_result,
        "backtest_summary": {
            "one_month": backtest_1m,
            "six_month": backtest_6m,
            "signal_false_alarm_test": signal_backtest,
        },
        "model_comparison": forecast_result.get("model_comparison", []),
        "predictor_signal_scores": {row["name"]: row["value"] for row in radial_rows},
        "uncertainty_decomposition": uncertainty_tree,
        "chart_insight_map": {
            "unemployment_forecast_band": "Tests whether the next-six-month path is materially different from a simple no-change baseline and exposes interval width without clipping.",
            "actual_vs_fitted_backtest": "Shows whether the local model tracked realized unemployment in recent walk-forward validation.",
            "backtest_error_by_horizon": "Compares the statistical model with simple baselines before using the forecast.",
            "fitted_vs_actual_scatter": "Reveals bias, dispersion, and large misses in six-month validation.",
            "predictor_contribution_radar": "Separates model-weighted predictors from currently hot indicators.",
            "current_signal_scores": "Condenses the latest predictor readings into decision-ready component scores.",
            "uncertainty_signal_flow": "Shows how predictors, baselines, validation, and forecast artifacts flow into the final chart pack.",
            "forecast_uncertainty_hierarchy": "Explains the main drivers of forecast uncertainty and why the band should shape confidence.",
        },
        "methods_used": list(
            dict.fromkeys([_METHOD, *forecast_result.get("methods_used", []), "event_signal_backtest"])
        ),
        "statistical_summary": (
            f"The deterministic chart pack models UNRATE with direct OLS over six "
            f"horizons using payroll momentum, claims, and optional inflation/growth "
            f"predictors. The latest six-month forecast is "
            f"{_round(latest_forecast.get('forecast'))}% with a 95% interval of "
            f"{_round(latest_forecast.get('lower'))}% to {_round(latest_forecast.get('upper'))}%."
        ),
        "limitations": [
            "The OLS forecast is reduced-form and does not prove predictor causality.",
            "Prediction intervals are residual-error bands and do not include all data-revision or parameter uncertainty.",
            "FRED data are latest vintage, so walk-forward validation is not a real-time vintage backtest.",
        ],
    }
    return save_quant_outputs(
        output_dir,
        charts,
        execution_summary,
        statistical_summary_excerpt=execution_summary["statistical_summary"],
    )

"""Deterministic historical-replay chart artifacts for macro FRED panels."""

from __future__ import annotations

from functools import reduce
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .forecasting import compare_analog_windows
from .outputs import save_quant_outputs

_PALETTE = ["#2563eb", "#f59e0b", "#10b981", "#ef4444", "#7c3aed", "#0891b2"]
_METHOD = "deterministic_historical_replay_chart_pack"
_ANALOG_WINDOWS = [
    {"label": "2001 recession", "start": "2000-07-01", "end": "2002-12-01"},
    {"label": "2008 financial crisis", "start": "2007-07-01", "end": "2009-12-01"},
    {"label": "2020 covid shock", "start": "2019-08-01", "end": "2021-12-01"},
    {"label": "post-pandemic inflation", "start": "2021-01-01", "end": "2023-12-01"},
]
_COMPONENTS = [
    ("Labor slack", "labor_stress"),
    ("Inflation pressure", "inflation_stress"),
    ("Policy restraint", "policy_stress"),
    ("Production drag", "production_stress"),
    ("Consumer strain", "consumer_stress"),
    ("Claims pressure", "claims_stress"),
]


def _matching_key(data_files: dict[str, str], candidates: tuple[str, ...]) -> str | None:
    normalized = {str(key).upper(): str(key) for key in data_files}
    for candidate in candidates:
        if candidate in normalized:
            return normalized[candidate]
    return None


def _read_monthly_series(path: str, key: str) -> pd.DataFrame:
    frame = pd.read_csv(path, usecols=["date", "value"])
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame[key] = pd.to_numeric(frame["value"].replace(".", pd.NA), errors="coerce")
    frame = frame.dropna(subset=["date"]).sort_values("date")
    monthly = frame.set_index("date")[[key]].resample("MS").mean(numeric_only=True)
    return monthly.reset_index().dropna(subset=[key]).reset_index(drop=True)


def _date_label(value: Any) -> str:
    timestamp = pd.Timestamp(value)
    return f"{timestamp.year:04d}-{timestamp.month:02d}"


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(number):
        return None
    return number


def _round(value: Any, digits: int = 3) -> float | None:
    number = _finite(value)
    return None if number is None else round(number, digits)


def _records(frame: pd.DataFrame, columns: list[str]) -> list[dict[str, Any]]:
    rows = frame[["date", *columns]].dropna(how="all", subset=columns).copy()
    records: list[dict[str, Any]] = []
    for _, row in rows.iterrows():
        record: dict[str, Any] = {"date": _date_label(row["date"])}
        for column in columns:
            record[column] = _round(row.get(column))
        records.append(record)
    return records


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


def _window_mean(panel: pd.DataFrame, column: str, start: Any, end: Any) -> float | None:
    if column not in panel:
        return None
    mask = (panel["date"] >= pd.Timestamp(start)) & (panel["date"] <= pd.Timestamp(end))
    values = pd.to_numeric(panel.loc[mask, column], errors="coerce").dropna()
    return _round(values.mean(skipna=True), 3) if not values.empty else None


def _window_score(panel: pd.DataFrame, column: str, start: Any, end: Any) -> float:
    value = _window_mean(panel, column, start, end)
    return 50.0 if value is None else round(max(1.0, min(100.0, value)), 1)


def _series_window(
    panel: pd.DataFrame,
    column: str,
    start: Any,
    end: Any,
    *,
    limit: int = 30,
) -> list[float | None]:
    if column not in panel:
        return []
    rows = panel[(panel["date"] >= pd.Timestamp(start)) & (panel["date"] <= pd.Timestamp(end))]
    values = pd.to_numeric(rows[column], errors="coerce").head(limit)
    return [_round(value) for value in values]


def _replay_records(
    panel: pd.DataFrame,
    column: str,
    current_window: dict[str, str],
    *,
    limit: int = 30,
) -> list[dict[str, Any]]:
    series_by_key = {
        "current": _series_window(
            panel, column, current_window["start"], current_window["end"], limit=limit
        )
    }
    for window in _ANALOG_WINDOWS:
        key = _window_key(window["label"])
        series_by_key[key] = _series_window(
            panel, column, window["start"], window["end"], limit=limit
        )
    rows: list[dict[str, Any]] = []
    max_len = max((len(values) for values in series_by_key.values()), default=0)
    for index in range(max_len):
        row: dict[str, Any] = {"month": index}
        for key, values in series_by_key.items():
            row[key] = values[index] if index < len(values) else None
        rows.append(row)
    return rows


def _median_replay_records(
    panel: pd.DataFrame,
    current_window: dict[str, str],
    current_column: str,
    analog_column: str,
    current_key: str,
    analog_key: str,
    *,
    limit: int = 30,
) -> list[dict[str, Any]]:
    current_values = _series_window(
        panel, current_column, current_window["start"], current_window["end"], limit=limit
    )
    analog_series = [
        _series_window(panel, analog_column, window["start"], window["end"], limit=limit)
        for window in _ANALOG_WINDOWS
    ]
    rows: list[dict[str, Any]] = []
    max_len = max([len(current_values), *(len(values) for values in analog_series)], default=0)
    for index in range(max_len):
        analog_values = [
            values[index]
            for values in analog_series
            if index < len(values) and values[index] is not None
        ]
        rows.append(
            {
                "month": index,
                current_key: current_values[index] if index < len(current_values) else None,
                analog_key: _round(np.median(analog_values)) if analog_values else None,
            }
        )
    return rows


def _window_key(label: str) -> str:
    return (
        label.lower()
        .replace("-", "_")
        .replace(" ", "_")
        .replace("covid", "covid")
        .replace("financial_crisis", "gfc")
    )


def _positive(value: Any) -> float:
    number = _finite(value)
    if number is None:
        return 1.0
    return round(max(1.0, abs(number)), 3)


def build_historical_replay_chart_pack_outputs(
    data_files: dict[str, str],
    output_dir: str | Path,
    *,
    query: str | None = None,
) -> dict[str, Any]:
    """Build renderable historical-replay charts from FRED macro CSV files."""

    required = {
        "UNRATE": _matching_key(data_files, ("UNRATE",)),
        "CPIAUCSL": _matching_key(data_files, ("CPIAUCSL",)),
        "FEDFUNDS": _matching_key(data_files, ("FEDFUNDS",)),
        "INDPRO": _matching_key(data_files, ("INDPRO",)),
        "USREC": _matching_key(data_files, ("USREC",)),
    }
    missing = [name for name, key in required.items() if key is None]
    if missing:
        raise ValueError(
            f"missing required FRED series for historical replay: {', '.join(missing)}"
        )

    optional = {
        "DGS10": _matching_key(data_files, ("DGS10",)),
        "ICSA": _matching_key(data_files, ("ICSA",)),
        "CIVPART": _matching_key(data_files, ("CIVPART",)),
        "AHE": _matching_key(data_files, ("CES0500000003", "AHETPI", "CEU0500000003")),
        "PCE": _matching_key(
            data_files,
            ("PCE", "PCEC96", "DPCERA3M086SBEA", "DPCERA3Q086SBEA"),
        ),
        "DSPIC96": _matching_key(data_files, ("DSPIC96",)),
        "GDPC1": _matching_key(data_files, ("GDPC1",)),
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
    core_latest = [
        panel.loc[pd.to_numeric(panel[column], errors="coerce").notna(), "date"].max()
        for column in ("UNRATE", "CPIAUCSL", "FEDFUNDS", "INDPRO", "USREC")
    ]
    latest_date = min(date for date in core_latest if pd.notna(date))
    panel = panel.loc[panel["date"] <= latest_date].reset_index(drop=True)
    for column in panel.columns:
        if column != "date":
            panel[column] = pd.to_numeric(panel[column], errors="coerce").ffill(limit=2)

    panel["cpi_yoy"] = panel["CPIAUCSL"].pct_change(12) * 100
    panel["fed_real_gap"] = panel["FEDFUNDS"] - panel["cpi_yoy"]
    panel["indpro_yoy"] = panel["INDPRO"].pct_change(12) * 100
    panel["consumer_yoy"] = (
        panel["DSPIC96"].pct_change(12) * 100
        if "DSPIC96" in panel
        else panel["PCE"].pct_change(12) * 100
        if "PCE" in panel
        else panel["UNRATE"].rolling(6, min_periods=3).mean() * -1
    )
    panel["claims_pressure"] = (
        _stress_series(panel["ICSA"], high_is_stress=True)
        if "ICSA" in panel
        else _stress_series(panel["UNRATE"], high_is_stress=True)
    )
    panel["labor_stress"] = _stress_series(panel["UNRATE"], high_is_stress=True)
    panel["inflation_stress"] = _stress_series(panel["cpi_yoy"], high_is_stress=True)
    panel["policy_stress"] = _stress_series(panel["fed_real_gap"], high_is_stress=True)
    panel["production_stress"] = _stress_series(panel["indpro_yoy"], high_is_stress=False)
    panel["consumer_stress"] = _stress_series(panel["consumer_yoy"], high_is_stress=False)
    panel["claims_stress"] = _stress_series(panel["claims_pressure"], high_is_stress=True)

    current_start = max(panel["date"].min(), pd.Timestamp(latest_date) - pd.DateOffset(months=29))
    current_window = {
        "label": "current",
        "start": _date_label(current_start),
        "end": _date_label(latest_date),
    }
    value_cols = [
        "UNRATE",
        "cpi_yoy",
        "FEDFUNDS",
        "indpro_yoy",
        "consumer_yoy",
        "claims_pressure",
    ]
    analog = compare_analog_windows(
        panel.dropna(how="all", subset=value_cols),
        date_col="date",
        value_cols=value_cols,
        windows=_ANALOG_WINDOWS,
        current_window=current_window,
    )
    ranking = analog["analog_similarity_ranking"]
    closest = next(
        (row["analog"] for row in ranking if row.get("status") == "ok"),
        _ANALOG_WINDOWS[0]["label"],
    )
    closest_window = next(
        (window for window in _ANALOG_WINDOWS if window["label"] == closest),
        _ANALOG_WINDOWS[0],
    )

    replay_series = [
        {"dataKey": "current", "label": "Current window", "color": _PALETTE[0]},
        {"dataKey": "2001_recession", "label": "2001", "color": _PALETTE[1]},
        {"dataKey": "2008_gfc", "label": "2008", "color": _PALETTE[2]},
        {"dataKey": "2020_covid_shock", "label": "2020", "color": _PALETTE[3]},
        {
            "dataKey": "post_pandemic_inflation",
            "label": "Post-pandemic",
            "color": _PALETTE[4],
        },
    ]
    inflation_rows = _median_replay_records(
        panel, current_window, "cpi_yoy", "cpi_yoy", "current_cpi_yoy", "analog_median_cpi_yoy"
    )
    policy_rows = _median_replay_records(
        panel, current_window, "FEDFUNDS", "FEDFUNDS", "current_fedfunds", "analog_median_fedfunds"
    )
    inflation_policy_rows = [
        {**left, **{k: v for k, v in right.items() if k != "month"}}
        for left, right in zip(inflation_rows, policy_rows, strict=False)
    ]
    production_rows = _median_replay_records(
        panel,
        current_window,
        "indpro_yoy",
        "indpro_yoy",
        "current_indpro_yoy",
        "analog_median_indpro_yoy",
    )
    consumer_rows = _median_replay_records(
        panel,
        current_window,
        "consumer_yoy",
        "consumer_yoy",
        "current_consumer_yoy",
        "analog_median_consumer_yoy",
    )
    production_consumer_rows = [
        {**left, **{k: v for k, v in right.items() if k != "month"}}
        for left, right in zip(production_rows, consumer_rows, strict=False)
    ]

    current_profile = {
        label: _window_score(panel, column, current_window["start"], current_window["end"])
        for label, column in _COMPONENTS
    }
    closest_profile = {
        label: _window_score(panel, column, closest_window["start"], closest_window["end"])
        for label, column in _COMPONENTS
    }
    radar_rows = [
        {
            "metric": label,
            "current": current_profile[label],
            "closest_analog": closest_profile[label],
        }
        for label, _ in _COMPONENTS
    ]
    latest_component_rows = [
        {
            "name": label,
            "value": round(
                max(1.0, _window_score(panel, column, latest_date, latest_date)),
                1,
            ),
            "color": _PALETTE[index % len(_PALETTE)],
        }
        for index, (label, column) in enumerate(_COMPONENTS)
    ]
    distance_rows = []
    current_values = analog["analog_profiles"].get("current", {})
    for item in ranking:
        profile = analog["analog_profiles"].get(str(item["analog"]), {})
        distance_rows.append(
            {
                "analog": item["analog"],
                "labor_gap": _round(
                    _finite(current_values.get("UNRATE")) - _finite(profile.get("UNRATE"))
                    if _finite(current_values.get("UNRATE")) is not None
                    and _finite(profile.get("UNRATE")) is not None
                    else None
                ),
                "inflation_gap": _round(
                    _finite(current_values.get("cpi_yoy")) - _finite(profile.get("cpi_yoy"))
                    if _finite(current_values.get("cpi_yoy")) is not None
                    and _finite(profile.get("cpi_yoy")) is not None
                    else None
                ),
                "distance_score": _positive(item.get("distance")),
            }
        )
    contribution_rows = []
    closest_breakdown = analog["analogy_breakdown"].get(closest, {})
    for item in closest_breakdown.get("top_divergences", []):
        label = str(item.get("variable", "indicator")).replace("_", " ").title()
        size = _positive(item.get("diff_std"))
        contribution_rows.append({"name": label, "size": size, "value": size})
    if not contribution_rows:
        contribution_rows = [
            {"name": row["name"], "size": row["value"], "value": row["value"]}
            for row in latest_component_rows
        ]

    charts = {
        "labor_replay_paths": {
            "id": "labor_replay_paths",
            "type": "line",
            "title": "Unemployment Replay Paths",
            "description": "Current unemployment path overlaid against the 2001, 2008, 2020, and post-pandemic windows on a common month axis.",
            "xAxisKey": "month",
            "series": replay_series,
            "data": _replay_records(panel, "UNRATE", current_window),
            "methods_used": [_METHOD],
        },
        "inflation_policy_replay": {
            "id": "inflation_policy_replay",
            "type": "composed",
            "title": "Inflation And Policy Replay",
            "description": "Current CPI inflation and fed funds are compared with the median historical replay path on the same percent scale.",
            "xAxisKey": "month",
            "series": [
                {"dataKey": "current_cpi_yoy", "label": "Current CPI YoY", "color": _PALETTE[3], "type": "line"},
                {"dataKey": "analog_median_cpi_yoy", "label": "Analog median CPI YoY", "color": _PALETTE[1], "type": "line"},
                {"dataKey": "current_fedfunds", "label": "Current fed funds", "color": _PALETTE[0], "type": "bar"},
                {"dataKey": "analog_median_fedfunds", "label": "Analog median fed funds", "color": _PALETTE[4], "type": "line"},
            ],
            "data": inflation_policy_rows,
            "methods_used": [_METHOD],
        },
        "production_consumer_replay": {
            "id": "production_consumer_replay",
            "type": "composed",
            "title": "Production And Consumer Replay",
            "description": "Industrial production and consumer-income growth show whether real activity is tracking old downturn windows.",
            "xAxisKey": "month",
            "series": [
                {"dataKey": "current_indpro_yoy", "label": "Current INDPRO YoY", "color": _PALETTE[2], "type": "line"},
                {"dataKey": "analog_median_indpro_yoy", "label": "Analog median INDPRO YoY", "color": _PALETTE[1], "type": "line"},
                {"dataKey": "current_consumer_yoy", "label": "Current consumer YoY", "color": _PALETTE[0], "type": "bar"},
                {"dataKey": "analog_median_consumer_yoy", "label": "Analog median consumer YoY", "color": _PALETTE[4], "type": "line"},
            ],
            "data": production_consumer_rows,
            "referenceLines": [
                {"axis": "y", "value": 0, "y": 0, "label": "No growth", "color": "#111827", "dashed": True}
            ],
            "methods_used": [_METHOD],
        },
        "analog_distance_bubble": {
            "id": "analog_distance_bubble",
            "type": "scatter",
            "title": "Current Distance From Historical Analogs",
            "description": "Bubble size is z-score distance; gaps show where current labor and inflation differ from each analog.",
            "xKey": "labor_gap",
            "yKey": "inflation_gap",
            "xLabel": "Current minus analog unemployment (pp)",
            "yLabel": "Current minus analog CPI YoY (pp)",
            "sizeKey": "distance_score",
            "colorKey": "analog",
            "color": _PALETTE[0],
            "data": distance_rows,
            "methods_used": [_METHOD, "analog_window_comparison"],
        },
        "normalized_window_profiles": {
            "id": "normalized_window_profiles",
            "type": "radar",
            "title": "Current Profile Versus Closest Analog",
            "description": f"Normalized stress scores compare the current window with {closest}.",
            "angleKey": "metric",
            "series": [
                {"dataKey": "current", "label": "Current", "color": _PALETTE[0]},
                {"dataKey": "closest_analog", "label": closest, "color": _PALETTE[3]},
            ],
            "data": radar_rows,
            "methods_used": [_METHOD],
        },
        "current_signal_scores": {
            "id": "current_signal_scores",
            "type": "radialBar",
            "title": "Latest Current-Window Signal Scores",
            "description": "Positive 0-100 component stress scores summarize the latest labor, inflation, rates, production, and consumer signals.",
            "data": latest_component_rows,
            "methods_used": [_METHOD],
        },
        "replay_difference_contributions": {
            "id": "replay_difference_contributions",
            "type": "treemap",
            "title": "Why The Closest Analog Still Differs",
            "description": f"Largest standardized gaps between the current window and {closest}.",
            "valueKey": "size",
            "data": contribution_rows,
            "methods_used": [_METHOD, "analog_window_comparison"],
        },
    }

    latest_row = panel.loc[panel["date"] == latest_date].tail(1).iloc[0]
    execution_summary = {
        "status": "success",
        "analysis_type": "historical_replay_chart_pack",
        "query": query,
        "latest_snapshot": {
            "date": _date_label(latest_date),
            "unemployment_rate": _round(latest_row.get("UNRATE")),
            "cpi_yoy": _round(latest_row.get("cpi_yoy")),
            "fed_funds": _round(latest_row.get("FEDFUNDS")),
            "indpro_yoy": _round(latest_row.get("indpro_yoy")),
            "consumer_yoy": _round(latest_row.get("consumer_yoy")),
            "claims_pressure_score": _round(latest_row.get("claims_pressure")),
        },
        "top_analog": closest,
        "analog_similarity_ranking": ranking,
        "analog_profiles": analog["analog_profiles"],
        "analogy_breakdown": analog["analogy_breakdown"],
        "comparison_design": {
            **analog["comparison_design"],
            "named_windows": _ANALOG_WINDOWS,
            "current_window": current_window,
        },
        "historical_simulations": [
            {
                "label": window["label"],
                "start": window["start"],
                "end": window["end"],
                "unemployment_rate": _window_mean(panel, "UNRATE", window["start"], window["end"]),
                "cpi_yoy": _window_mean(panel, "cpi_yoy", window["start"], window["end"]),
                "fed_funds": _window_mean(panel, "FEDFUNDS", window["start"], window["end"]),
                "indpro_yoy": _window_mean(panel, "indpro_yoy", window["start"], window["end"]),
                "consumer_yoy": _window_mean(panel, "consumer_yoy", window["start"], window["end"]),
            }
            for window in _ANALOG_WINDOWS
        ],
        "backtest_summary": {
            "method": "descriptive_historical_replay",
            "status": "descriptive_replay",
            "top_analog": closest,
            "distance_metric": "euclidean_z_distance_on_window_means",
            "current_window": current_window,
        },
        "chart_insight_map": {
            "labor_replay_paths": "Shows whether unemployment is following a downturn-style path or remains below prior stress windows.",
            "inflation_policy_replay": "Separates current disinflation and policy restraint from historical analog medians.",
            "production_consumer_replay": "Tests whether real activity is confirming or contradicting the analog ranking.",
            "analog_distance_bubble": "Identifies which analog is closest and which indicators drive distance.",
            "normalized_window_profiles": "Shows whether the current mix is broad stress or concentrated in rates/inflation.",
            "current_signal_scores": "Summarizes the latest component risks for decision triage.",
            "replay_difference_contributions": "Ranks the most important standardized gaps versus the closest analog.",
        },
        "methods_used": [_METHOD, *analog.get("methods_used", [])],
        "statistical_summary": (
            "The replay pack aligns FRED labor, inflation, policy-rate, production, "
            "and consumer-income indicators into monthly windows, compares the "
            "current 30-month window with 2001, 2008, 2020, and post-pandemic "
            "windows using z-score distances, and saves governed chart artifacts "
            "that distinguish current paths from historical analogs."
        ),
        "limitations": [
            "The analog ranking is descriptive and compares window-average conditions, not causal mechanisms.",
            "The current window is the latest 30 months with complete core FRED coverage; optional consumer and claims proxies may have shorter effective histories.",
            "Historical windows are named macro episodes, so the chart pack should be read as evidence triage rather than a forecast.",
        ],
    }
    return save_quant_outputs(
        output_dir,
        charts,
        execution_summary,
        statistical_summary_excerpt=execution_summary["statistical_summary"],
    )

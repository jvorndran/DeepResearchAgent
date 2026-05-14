"""Deterministic CPI/Fed funds chart-pack artifacts for FRED panels."""

from __future__ import annotations

from functools import reduce
from pathlib import Path
from typing import Any

import pandas as pd

from .outputs import save_quant_outputs

_PALETTE = ["#3b82f6", "#f59e0b", "#10b981", "#ef4444", "#8b5cf6"]
_METHOD = "deterministic_inflation_policy_chart_pack"


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
    monthly = frame.set_index("date")[[key]].resample("MS").mean(numeric_only=True).reset_index()
    return monthly.dropna(subset=[key]).reset_index(drop=True)


def _looks_like_yoy_percent(series: pd.Series) -> bool:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return False
    return float(values.abs().quantile(0.95)) <= 25.0 and float(values.abs().max()) <= 50.0


def _cpi_yoy_series(series: pd.Series) -> tuple[pd.Series, str]:
    values = pd.to_numeric(series, errors="coerce")
    if _looks_like_yoy_percent(values):
        return values, "as_reported_percent_change"
    return values.pct_change(12, fill_method=None) * 100.0, "index_pct_change_12m"


def _date_label(value: Any) -> str:
    timestamp = pd.Timestamp(value)
    return f"{timestamp.year:04d}-{timestamp.month:02d}"


def _records(frame: pd.DataFrame, columns: list[str]) -> list[dict[str, Any]]:
    rows = frame[["date", *columns]].dropna(how="all", subset=columns).copy()
    records: list[dict[str, Any]] = []
    for _, row in rows.iterrows():
        record: dict[str, Any] = {"date": _date_label(row["date"])}
        for column in columns:
            value = row.get(column)
            record[column] = None if pd.isna(value) else round(float(value), 3)
        records.append(record)
    return records


def _recession_bands(panel: pd.DataFrame) -> list[dict[str, Any]]:
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
                    "x1": _date_label(start),
                    "x2": _date_label(previous or start),
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
                "x1": _date_label(start),
                "x2": _date_label(previous or start),
                "label": f"{start.year} recession",
                "fill": "#e5e7eb",
                "opacity": 0.35,
            }
        )
    return bands


def _future_recession_flags(panel: pd.DataFrame) -> pd.Series:
    if "USREC" not in panel:
        return pd.Series([0.0] * len(panel), index=panel.index)
    values = pd.to_numeric(panel["USREC"], errors="coerce").fillna(0).to_numpy()
    future: list[float] = []
    for index in range(len(values)):
        window = values[index + 1 : index + 13]
        future.append(float(window.max()) if len(window) else 0.0)
    return pd.Series(future, index=panel.index)


def _lag_streak(condition: pd.Series) -> pd.Series:
    groups = condition.ne(condition.shift(fill_value=False)).cumsum()
    streak = condition.groupby(groups).cumcount() + 1
    return streak.where(condition, 0).astype(float)


def _regime_name(date: Any) -> str:
    timestamp = pd.Timestamp(date)
    if timestamp < pd.Timestamp("2000-03-01"):
        return "1990s expansion"
    if timestamp < pd.Timestamp("2007-12-01"):
        return "Dot-com to housing cycle"
    if timestamp < pd.Timestamp("2020-01-01"):
        return "GFC and ZIRP cycle"
    return "COVID inflation cycle"


def _score(value: float | None, denominator: float) -> float:
    if value is None or pd.isna(value):
        return 1.0
    return round(max(1.0, min(100.0, float(value) / denominator * 100.0)), 1)


def _normalize(value: float, low: float, high: float) -> float:
    if high <= low:
        return 50.0
    return round(max(0.0, min(100.0, (value - low) / (high - low) * 100.0)), 1)


def _regime_rows(panel: pd.DataFrame) -> list[dict[str, Any]]:
    grouped = (
        panel.dropna(subset=["headline_cpi_yoy", "core_cpi_yoy", "fed_funds"])
        .assign(regime=lambda frame: frame["date"].map(_regime_name))
        .groupby("regime", sort=False)
    )
    rows: list[dict[str, Any]] = []
    for regime, group in grouped:
        if group.empty:
            continue
        rows.append(
            {
                "name": regime,
                "avg_headline": round(float(group["headline_cpi_yoy"].mean()), 2),
                "avg_core": round(float(group["core_cpi_yoy"].mean()), 2),
                "avg_fed_funds": round(float(group["fed_funds"].mean()), 2),
                "avg_policy_gap": round(float(group["headline_policy_gap"].mean()), 2),
                "lag_months": int(group["policy_lag_active"].sum()),
            }
        )
    return rows


def _build_sankey(panel: pd.DataFrame) -> dict[str, list[dict[str, Any]]]:
    valid = panel.dropna(subset=["headline_cpi_yoy", "fed_funds"]).copy()
    if valid.empty:
        return {"nodes": [], "links": []}

    nodes: list[dict[str, Any]] = [{"name": "Observed months"}]
    links: list[dict[str, Any]] = []

    def node_index(name: str) -> int:
        for index, node in enumerate(nodes):
            if node["name"] == name:
                return index
        nodes.append({"name": name})
        return len(nodes) - 1

    high = valid["high_inflation"]
    lag = valid["policy_lag_active"]
    future_rec = valid["recession_next_12m"] >= 0.5
    stages = [
        ("Inflation above 3%", int(high.sum()), 0, node_index("Inflation above 3%")),
        ("Inflation at or below 3%", int((~high).sum()), 0, node_index("Inflation at or below 3%")),
    ]
    for _, value, source, target in stages:
        if value > 0:
            links.append({"source": source, "target": target, "value": value})

    high_index = node_index("Inflation above 3%")
    lag_index = node_index("Fed funds below headline CPI")
    caught_up_index = node_index("Fed funds at or above headline CPI")
    lag_count = int((high & lag).sum())
    caught_up_count = int((high & ~lag).sum())
    if lag_count > 0:
        links.append({"source": high_index, "target": lag_index, "value": lag_count})
    if caught_up_count > 0:
        links.append({"source": high_index, "target": caught_up_index, "value": caught_up_count})

    recession_index = node_index("Recession within 12m")
    no_recession_index = node_index("No recession within 12m")
    lag_recession = int((high & lag & future_rec).sum())
    lag_no_recession = int((high & lag & ~future_rec).sum())
    if lag_recession > 0:
        links.append({"source": lag_index, "target": recession_index, "value": lag_recession})
    if lag_no_recession > 0:
        links.append({"source": lag_index, "target": no_recession_index, "value": lag_no_recession})
    return {"nodes": nodes, "links": links}


def build_inflation_policy_chart_pack_outputs(
    data_files: dict[str, str],
    output_dir: str | Path,
    *,
    query: str | None = None,
) -> dict[str, Any]:
    """Build renderable CPI/core CPI/Fed funds chart packs from FRED CSV files."""

    required = {
        "CPIAUCSL": _matching_key(data_files, ("CPIAUCSL",)),
        "CPILFESL": _matching_key(data_files, ("CPILFESL",)),
        "FEDFUNDS": _matching_key(data_files, ("FEDFUNDS",)),
    }
    missing = [name for name, key in required.items() if key is None]
    if missing:
        raise ValueError(
            f"missing required FRED series for inflation policy chart pack: {', '.join(missing)}"
        )

    frames = [
        _read_monthly_series(data_files[source_key], target_key)
        for target_key, source_key in required.items()
        if source_key is not None
    ]
    usrec_key = _matching_key(data_files, ("USREC",))
    if usrec_key:
        frames.append(_read_monthly_series(data_files[usrec_key], "USREC"))
    panel = reduce(lambda left, right: left.merge(right, on="date", how="outer"), frames)
    panel = panel.sort_values("date").reset_index(drop=True)
    panel = panel.loc[panel["date"] >= pd.Timestamp("1990-01-01")].reset_index(drop=True)

    panel["headline_cpi_yoy"], headline_transform = _cpi_yoy_series(panel["CPIAUCSL"])
    panel["core_cpi_yoy"], core_transform = _cpi_yoy_series(panel["CPILFESL"])
    panel["fed_funds"] = panel["FEDFUNDS"]
    panel["headline_policy_gap"] = panel["fed_funds"] - panel["headline_cpi_yoy"]
    panel["core_policy_gap"] = panel["fed_funds"] - panel["core_cpi_yoy"]
    panel["fed_funds_12m_ahead"] = panel["fed_funds"].shift(-12)
    panel["policy_gap_abs"] = panel["headline_policy_gap"].abs() + 0.25
    panel["high_inflation"] = panel["headline_cpi_yoy"] >= 3.0
    panel["policy_lag_active"] = panel["high_inflation"] & (
        panel["fed_funds"] < panel["headline_cpi_yoy"]
    )
    panel["lag_streak_months"] = _lag_streak(panel["policy_lag_active"])
    panel["recession_next_12m"] = _future_recession_flags(panel)

    bands = _recession_bands(panel)
    latest_rows = panel.dropna(subset=["headline_cpi_yoy", "core_cpi_yoy", "fed_funds"])
    latest = latest_rows.tail(1).iloc[0] if not latest_rows.empty else None
    regime_rows = _regime_rows(panel)

    metrics = ["avg_headline", "avg_core", "avg_fed_funds", "avg_policy_gap"]
    metric_ranges = {
        metric: (
            min(float(row[metric]) for row in regime_rows),
            max(float(row[metric]) for row in regime_rows),
        )
        for metric in metrics
        if regime_rows
    }
    current_regime = _regime_name(latest["date"]) if latest is not None else ""
    current_regime_row = next(
        (row for row in regime_rows if row["name"] == current_regime),
        regime_rows[-1] if regime_rows else {},
    )
    radar_rows = [
        {
            "metric": "Headline CPI",
            "current_regime": _normalize(
                float(current_regime_row.get("avg_headline", 0)),
                *metric_ranges.get("avg_headline", (0.0, 1.0)),
            ),
            "full_period_avg": 50,
        },
        {
            "metric": "Core CPI",
            "current_regime": _normalize(
                float(current_regime_row.get("avg_core", 0)),
                *metric_ranges.get("avg_core", (0.0, 1.0)),
            ),
            "full_period_avg": 50,
        },
        {
            "metric": "Fed funds",
            "current_regime": _normalize(
                float(current_regime_row.get("avg_fed_funds", 0)),
                *metric_ranges.get("avg_fed_funds", (0.0, 1.0)),
            ),
            "full_period_avg": 50,
        },
        {
            "metric": "Policy gap",
            "current_regime": _normalize(
                float(current_regime_row.get("avg_policy_gap", 0)),
                *metric_ranges.get("avg_policy_gap", (0.0, 1.0)),
            ),
            "full_period_avg": 50,
        },
    ]

    latest_headline = float(latest["headline_cpi_yoy"]) if latest is not None else None
    latest_core = float(latest["core_cpi_yoy"]) if latest is not None else None
    latest_fed = float(latest["fed_funds"]) if latest is not None else None
    latest_gap = float(latest["headline_policy_gap"]) if latest is not None else None
    radial_rows = [
        {
            "name": "Headline CPI pressure",
            "value": _score(latest_headline, 8),
            "color": _PALETTE[0],
        },
        {"name": "Core CPI pressure", "value": _score(latest_core, 6), "color": _PALETTE[1]},
        {"name": "Policy rate level", "value": _score(latest_fed, 7), "color": _PALETTE[2]},
        {
            "name": "Policy catch-up",
            "value": _score(max(latest_gap or 0.0, 0.0) + 0.25, 5),
            "color": _PALETTE[3],
        },
    ]

    lag_rows = [
        {
            "name": row["name"],
            "size": max(1, int(row["lag_months"])),
            "value": max(1, int(row["lag_months"])),
            "color": _PALETTE[index % len(_PALETTE)],
        }
        for index, row in enumerate(regime_rows)
        if int(row["lag_months"]) > 0
    ]
    if not lag_rows and regime_rows:
        lag_rows = [
            {
                "name": row["name"],
                "size": 1,
                "value": 1,
                "color": _PALETTE[index % len(_PALETTE)],
            }
            for index, row in enumerate(regime_rows)
        ]

    valid = panel.dropna(subset=["headline_cpi_yoy", "fed_funds"])
    high_count = int(valid["high_inflation"].sum())
    lag_count = int(valid["policy_lag_active"].sum())
    persistent_count = int((valid["lag_streak_months"] >= 6).sum())
    recession_after_lag_count = int(
        (valid["policy_lag_active"] & (valid["recession_next_12m"] >= 0.5)).sum()
    )
    funnel_candidates = [
        ("All observed CPI/rate months", len(valid)),
        ("Headline CPI above 3%", high_count),
        ("Fed funds below headline CPI", lag_count),
        ("Lag persisted at least 6 months", persistent_count),
        ("Recession within 12 months", recession_after_lag_count),
    ]
    funnel_rows = [
        {"name": name, "value": value, "color": _PALETTE[index % len(_PALETTE)]}
        for index, (name, value) in enumerate(funnel_candidates)
        if value > 0
    ]

    scatter = (
        panel.dropna(subset=["headline_cpi_yoy", "fed_funds_12m_ahead", "policy_gap_abs"])
        .iloc[::3]
        .copy()
    )
    scatter_rows = []
    for _, row in scatter.iterrows():
        scatter_rows.append(
            {
                "date": _date_label(row["date"]),
                "headline_cpi_yoy": round(float(row["headline_cpi_yoy"]), 3),
                "fed_funds_12m_ahead": round(float(row["fed_funds_12m_ahead"]), 3),
                "policy_gap_abs": round(float(row["policy_gap_abs"]), 3),
                "lagging_policy": "lagging" if bool(row["policy_lag_active"]) else "caught_up",
            }
        )

    charts = {
        "inflation_policy_overlay": {
            "id": "inflation_policy_overlay",
            "type": "composed",
            "title": "Inflation And Policy Rate Since 1990",
            "description": "Headline CPI, core CPI, and effective fed funds rate on the same percent scale.",
            "xAxisKey": "date",
            "series": [
                {
                    "dataKey": "headline_cpi_yoy",
                    "label": "Headline CPI YoY (%)",
                    "color": _PALETTE[0],
                    "type": "line",
                },
                {
                    "dataKey": "core_cpi_yoy",
                    "label": "Core CPI YoY (%)",
                    "color": _PALETTE[1],
                    "type": "line",
                },
                {
                    "dataKey": "fed_funds",
                    "label": "Effective fed funds (%)",
                    "color": _PALETTE[2],
                    "type": "line",
                },
            ],
            "data": _records(panel, ["headline_cpi_yoy", "core_cpi_yoy", "fed_funds"]),
            "referenceAreas": bands,
            "methods_used": [_METHOD],
        },
        "real_policy_gap_cycle": {
            "id": "real_policy_gap_cycle",
            "type": "area",
            "title": "Policy Gap Versus Inflation",
            "description": "Fed funds minus CPI inflation; negative values mark policy rates below inflation.",
            "xAxisKey": "date",
            "series": [
                {
                    "dataKey": "headline_policy_gap",
                    "label": "Fed funds minus headline CPI",
                    "color": _PALETTE[3],
                },
                {
                    "dataKey": "core_policy_gap",
                    "label": "Fed funds minus core CPI",
                    "color": _PALETTE[4],
                },
            ],
            "data": _records(panel, ["headline_policy_gap", "core_policy_gap"]),
            "referenceLines": [
                {
                    "axis": "y",
                    "value": 0,
                    "y": 0,
                    "label": "Rate equals inflation",
                    "color": "#111827",
                    "dashed": True,
                }
            ],
            "referenceAreas": bands,
            "methods_used": [_METHOD],
        },
        "policy_lag_scatter": {
            "id": "policy_lag_scatter",
            "type": "scatter",
            "title": "Inflation Versus Fed Funds Twelve Months Later",
            "description": "Bubble size is the absolute contemporaneous policy gap, highlighting delayed catch-up episodes.",
            "xKey": "headline_cpi_yoy",
            "yKey": "fed_funds_12m_ahead",
            "xLabel": "Headline CPI YoY (%)",
            "yLabel": "Fed funds 12 months later (%)",
            "color": _PALETTE[3],
            "sizeKey": "policy_gap_abs",
            "colorKey": "lagging_policy",
            "data": scatter_rows,
            "methods_used": [_METHOD],
        },
        "regime_policy_profile": {
            "id": "regime_policy_profile",
            "type": "radar",
            "title": "Current Regime Profile Versus History",
            "description": "Normalized current-regime inflation and policy dimensions compared with the full-period midpoint.",
            "angleKey": "metric",
            "series": [
                {
                    "dataKey": "current_regime",
                    "label": current_regime or "Current regime",
                    "color": _PALETTE[0],
                },
                {
                    "dataKey": "full_period_avg",
                    "label": "Full-period midpoint",
                    "color": _PALETTE[4],
                },
            ],
            "data": radar_rows,
            "methods_used": [_METHOD],
        },
        "current_policy_component_scores": {
            "id": "current_policy_component_scores",
            "type": "radialBar",
            "title": "Latest Inflation-Policy Component Scores",
            "description": "Current CPI pressure, policy-rate level, and policy catch-up scaled to positive 0-100 scores.",
            "data": radial_rows,
            "methods_used": [_METHOD],
        },
        "policy_lag_regime_contribution": {
            "id": "policy_lag_regime_contribution",
            "type": "treemap",
            "title": "Policy-Lag Months By Regime",
            "description": "Contribution hierarchy of months when headline CPI exceeded 3% and fed funds remained below headline inflation.",
            "valueKey": "size",
            "data": lag_rows,
            "methods_used": [_METHOD],
        },
        "policy_lag_filter_funnel": {
            "id": "policy_lag_filter_funnel",
            "type": "funnel",
            "title": "Policy-Lag Filter Funnel",
            "description": "Observed months narrowed to high-inflation, lagging-policy, persistent-lag, and recession-follow-through cases.",
            "data": funnel_rows,
            "methods_used": [_METHOD],
        },
        "policy_lag_signal_flow": {
            "id": "policy_lag_signal_flow",
            "type": "sankey",
            "title": "Inflation-Policy Signal Flow",
            "description": "Monthly observations flowing through high inflation, policy lag, and recession-follow-through states.",
            "data": _build_sankey(panel),
            "methods_used": [_METHOD],
        },
    }

    corr_frame = panel[["headline_cpi_yoy", "fed_funds_12m_ahead"]].dropna()
    lag_correlation = (
        round(float(corr_frame["headline_cpi_yoy"].corr(corr_frame["fed_funds_12m_ahead"])), 3)
        if len(corr_frame) >= 3
        else None
    )
    execution_summary = {
        "status": "success",
        "analysis_type": "inflation_policy_chart_pack",
        "query": query,
        "latest_snapshot": (
            {
                "date": _date_label(latest["date"]),
                "headline_cpi_yoy": round(float(latest["headline_cpi_yoy"]), 3),
                "core_cpi_yoy": round(float(latest["core_cpi_yoy"]), 3),
                "fed_funds": round(float(latest["fed_funds"]), 3),
                "headline_policy_gap": round(float(latest["headline_policy_gap"]), 3),
            }
            if latest is not None
            else {}
        ),
        "policy_lag_summary": {
            "observed_months": len(valid),
            "high_inflation_months": high_count,
            "policy_lag_months": lag_count,
            "persistent_lag_months": persistent_count,
            "recession_after_lag_months": recession_after_lag_count,
            "headline_inflation_to_fed_funds_12m_ahead_corr": lag_correlation,
        },
        "regime_summary": regime_rows,
        "cpi_transforms": {
            "headline_cpi_yoy": headline_transform,
            "core_cpi_yoy": core_transform,
        },
        "methods_used": [_METHOD],
        "statistical_summary": (
            "The chart pack compares headline CPI, core CPI, and the effective "
            "fed funds rate since 1990, then reframes the same data as policy "
            "gaps, lagged policy response, current-regime scores, regime "
            "contributions, staged filters, and signal flow."
        ),
        "limitations": [
            "The policy-lag flag is a transparent rule, not a structural monetary-policy model.",
            "Fed funds is compared with trailing 12-month CPI inflation; realized real rates differ from ex ante expectations.",
        ],
    }
    return save_quant_outputs(
        output_dir,
        charts,
        execution_summary,
        statistical_summary_excerpt=execution_summary["statistical_summary"],
    )

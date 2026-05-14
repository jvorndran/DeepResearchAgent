"""Deterministic consumer-stress dashboard artifacts for FRED panels."""

from __future__ import annotations

from functools import reduce
from pathlib import Path
from typing import Any

import pandas as pd

from .outputs import save_quant_outputs

_PALETTE = ["#2563eb", "#f59e0b", "#10b981", "#ef4444", "#7c3aed", "#0891b2"]
_METHOD = "deterministic_consumer_stress_dashboard"
_INCOME_WAGE_KEYS = ("DSPIC96", "LES1252881600Q", "AHETPI", "CES0500000003", "CEU0500000003")
_NOMINAL_WAGE_KEYS = {"AHETPI", "CES0500000003", "CEU0500000003"}
_REAL_CONSUMPTION_KEYS = ("DPCERA3M086SBEA", "PCEC96")
_DELINQUENCY_KEYS = ("DRALACBN", "DRCLACBS", "DRCCLACBS", "DRSFRMACBS")
_AUTO_CREDIT_KEYS = ("DTCOLNVHFNM",)


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


def _series_units(path: str) -> str:
    try:
        metadata = pd.read_csv(path, nrows=1)
    except (OSError, ValueError):
        return ""
    if "units" not in metadata:
        return ""
    values = metadata["units"].dropna()
    return str(values.iloc[0]) if not values.empty else ""


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


def _stress_series(series: pd.Series, *, high_is_stress: bool) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    finite = values.dropna()
    if finite.empty:
        return pd.Series([pd.NA] * len(values), index=values.index, dtype="Float64")
    low = float(finite.quantile(0.10))
    high = float(finite.quantile(0.90))
    if high <= low:
        return pd.Series([50.0] * len(values), index=values.index)
    score = (values - low) / (high - low) * 100.0
    if not high_is_stress:
        score = 100.0 - score
    return score.clip(lower=0.0, upper=100.0)


def _latest_score(panel: pd.DataFrame, column: str) -> float:
    if column not in panel:
        return 50.0
    values = pd.to_numeric(panel[column], errors="coerce").dropna()
    if values.empty:
        return 50.0
    return round(float(values.iloc[-1]), 1)


def _latest_value(panel: pd.DataFrame, column: str) -> float | None:
    if column not in panel:
        return None
    values = pd.to_numeric(panel[column], errors="coerce").dropna()
    if values.empty:
        return None
    return round(float(values.iloc[-1]), 3)


def _period_score(panel: pd.DataFrame, column: str, start: str, end: str) -> float:
    if column not in panel:
        return 50.0
    mask = (panel["date"] >= pd.Timestamp(start)) & (panel["date"] <= pd.Timestamp(end))
    values = pd.to_numeric(panel.loc[mask, column], errors="coerce").dropna()
    if values.empty:
        return 50.0
    return round(float(values.mean()), 1)


def _positive_score(value: float) -> float:
    return round(max(1.0, min(100.0, float(value))), 1)


def _period_label(value: Any) -> str:
    timestamp = pd.Timestamp(value)
    if timestamp < pd.Timestamp("2020-03-01"):
        return "pre_covid"
    if timestamp < pd.Timestamp("2023-01-01"):
        return "pandemic_inflation"
    return "current_cycle"


def build_consumer_stress_dashboard_outputs(
    data_files: dict[str, str],
    output_dir: str | Path,
    *,
    query: str | None = None,
) -> dict[str, Any]:
    """Build renderable consumer-stress dashboard charts from FRED CSV files."""

    required = {
        "PSAVERT": _matching_key(data_files, ("PSAVERT",)),
        "UNRATE": _matching_key(data_files, ("UNRATE",)),
        "CPIAUCSL": _matching_key(data_files, ("CPIAUCSL",)),
        "UMCSENT": _matching_key(data_files, ("UMCSENT",)),
    }
    income_wage_key = _matching_key(data_files, _INCOME_WAGE_KEYS)
    real_consumption_key = _matching_key(data_files, _REAL_CONSUMPTION_KEYS)
    total_credit_key = _matching_key(data_files, ("TOTALSL",))
    delinquency_key = _matching_key(data_files, _DELINQUENCY_KEYS)
    missing = [name for name, key in required.items() if key is None]
    if income_wage_key is None:
        missing.append("DSPIC96/LES1252881600Q/AHETPI/CES0500000003")
    if total_credit_key is None and delinquency_key is None:
        missing.append("TOTALSL/DRALACBN/DRCLACBS/DRCCLACBS/DRSFRMACBS")
    if missing:
        raise ValueError(
            f"missing required FRED series for consumer stress dashboard: {', '.join(missing)}"
        )

    optional = {
        "U6RATE": _matching_key(data_files, ("U6RATE",)),
        "PCEPILFE": _matching_key(data_files, ("PCEPILFE",)),
        "PCE": _matching_key(data_files, ("PCE",)),
        "USREC": _matching_key(data_files, ("USREC",)),
    }
    auto_key = _matching_key(data_files, _AUTO_CREDIT_KEYS)

    frames = [
        _read_monthly_series(data_files[source_key], target_key)
        for target_key, source_key in required.items()
        if source_key is not None
    ]
    assert income_wage_key is not None
    frames.append(_read_monthly_series(data_files[income_wage_key], "income_wage_source"))
    if real_consumption_key is not None:
        frames.append(_read_monthly_series(data_files[real_consumption_key], "real_consumption"))
    for target_key, source_key in optional.items():
        if source_key is not None:
            frames.append(_read_monthly_series(data_files[source_key], target_key))
    if total_credit_key is not None:
        frames.append(_read_monthly_series(data_files[total_credit_key], "TOTALSL"))
    if delinquency_key is not None:
        frames.append(_read_monthly_series(data_files[delinquency_key], "delinquency_rate"))
    if auto_key is not None:
        frames.append(_read_monthly_series(data_files[auto_key], "auto_loan_volume"))

    panel = reduce(lambda left, right: left.merge(right, on="date", how="outer"), frames)
    panel = panel.sort_values("date").reset_index(drop=True)
    latest_date = panel["date"].dropna().max()
    if pd.notna(latest_date):
        start_date = max(
            panel["date"].dropna().min(),
            pd.Timestamp(latest_date) - pd.DateOffset(years=36),
        )
        panel = panel.loc[panel["date"] >= start_date].reset_index(drop=True)

    if "delinquency_rate" in panel:
        panel["delinquency_rate"] = pd.to_numeric(panel["delinquency_rate"], errors="coerce").ffill(
            limit=3
        )
    if "USREC" in panel:
        panel["USREC"] = pd.to_numeric(panel["USREC"], errors="coerce").ffill(limit=2)

    cpi_units = _series_units(data_files[required["CPIAUCSL"] or ""])
    if "percent change from year ago" in cpi_units.lower():
        panel["cpi_yoy"] = pd.to_numeric(panel["CPIAUCSL"], errors="coerce")
    else:
        panel["cpi_yoy"] = pd.to_numeric(panel["CPIAUCSL"], errors="coerce").pct_change(12) * 100
    if "PCEPILFE" in panel:
        panel["core_pce_yoy"] = (
            pd.to_numeric(panel["PCEPILFE"], errors="coerce").pct_change(12) * 100
        )
    income_values = pd.to_numeric(panel["income_wage_source"], errors="coerce")
    if str(income_wage_key).upper() in _NOMINAL_WAGE_KEYS:
        income_values = income_values / pd.to_numeric(panel["CPIAUCSL"], errors="coerce")
    baseline = panel.loc[
        (panel["date"] >= pd.Timestamp("2019-01-01"))
        & (panel["date"] <= pd.Timestamp("2019-12-01")),
        "income_wage_source",
    ].dropna()
    if str(income_wage_key).upper() in _NOMINAL_WAGE_KEYS and not baseline.empty:
        baseline_cpi = pd.to_numeric(panel.loc[baseline.index, "CPIAUCSL"], errors="coerce")
        baseline = baseline / baseline_cpi
    finite_income = income_values.dropna()
    divisor = (
        float(baseline.mean())
        if not baseline.empty
        else float(finite_income.iloc[0])
        if not finite_income.empty
        else 1.0
    )
    panel["income_wage_index"] = income_values / divisor * 100
    if "real_consumption" in panel:
        panel["real_pce_yoy"] = (
            pd.to_numeric(panel["real_consumption"], errors="coerce").pct_change(12) * 100
        )
    if "TOTALSL" in panel:
        panel["total_credit_yoy"] = (
            pd.to_numeric(panel["TOTALSL"], errors="coerce").pct_change(12) * 100
        )
    else:
        panel["total_credit_yoy"] = pd.NA
    if "PCE" in panel:
        panel["nominal_pce_yoy"] = pd.to_numeric(panel["PCE"], errors="coerce").pct_change(12) * 100
    if "U6RATE" in panel:
        panel["u6_gap"] = pd.to_numeric(panel["U6RATE"], errors="coerce") - pd.to_numeric(
            panel["UNRATE"], errors="coerce"
        )
    else:
        panel["u6_gap"] = pd.NA
    if "auto_loan_volume" in panel:
        panel["auto_loan_yoy"] = (
            pd.to_numeric(panel["auto_loan_volume"], errors="coerce").pct_change(12) * 100
        )
    else:
        panel["auto_loan_yoy"] = pd.NA

    panel["savings_stress"] = _stress_series(panel["PSAVERT"], high_is_stress=False)
    panel["income_stress"] = _stress_series(panel["income_wage_index"], high_is_stress=False)
    panel["labor_stress"] = _stress_series(panel["UNRATE"], high_is_stress=True)
    panel["inflation_stress"] = _stress_series(panel["cpi_yoy"], high_is_stress=True)
    panel["sentiment_stress"] = _stress_series(panel["UMCSENT"], high_is_stress=False)
    credit_source = "delinquency_rate" if "delinquency_rate" in panel else "total_credit_yoy"
    panel["credit_stress_score"] = _stress_series(panel[credit_source], high_is_stress=True)
    panel["auto_loan_stress_score"] = _stress_series(panel["auto_loan_yoy"], high_is_stress=True)

    bands = _recession_bands(panel)
    overlay_columns = [
        "savings_stress",
        "income_stress",
        "labor_stress",
        "inflation_stress",
        "sentiment_stress",
        "credit_stress_score",
    ]
    component_labels = [
        ("Savings cushion", "savings_stress"),
        ("Real income/wage squeeze", "income_stress"),
        ("Labor slack", "labor_stress"),
        ("Inflation pressure", "inflation_stress"),
        ("Sentiment weakness", "sentiment_stress"),
        ("Credit stress", "credit_stress_score"),
    ]
    radar_rows = [
        {
            "metric": label,
            "latest_stress": _latest_score(panel, column),
            "pre_pandemic_stress": _period_score(panel, column, "2019-01-01", "2019-12-01"),
        }
        for label, column in component_labels
    ]
    latest_component_rows = [
        {
            "name": label,
            "value": _positive_score(_latest_score(panel, column)),
            "color": _PALETTE[index % len(_PALETTE)],
        }
        for index, (label, column) in enumerate(component_labels)
    ]
    treemap_rows = [
        {
            "name": row["name"],
            "size": row["value"],
            "value": row["value"],
            "color": row["color"],
        }
        for row in latest_component_rows
    ]
    scatter_frame = panel.dropna(subset=["PSAVERT", "UMCSENT"]).iloc[::3].copy()
    scatter_rows = []
    for _, row in scatter_frame.iterrows():
        cpi_yoy = row.get("cpi_yoy")
        scatter_rows.append(
            {
                "date": _date_label(row["date"]),
                "saving_rate": round(float(row["PSAVERT"]), 3),
                "sentiment": round(float(row["UMCSENT"]), 3),
                "inflation_size": _positive_score(
                    abs(float(cpi_yoy)) if not pd.isna(cpi_yoy) else 1.0
                ),
                "period": _period_label(row["date"]),
            }
        )

    credit_columns = ["credit_stress_score"]
    credit_series = [
        {
            "dataKey": "credit_stress_score",
            "label": "Credit stress score",
            "color": _PALETTE[3],
        }
    ]
    if "auto_loan_stress_score" in panel and panel["auto_loan_stress_score"].notna().any():
        credit_columns.append("auto_loan_stress_score")
        credit_series.append(
            {
                "dataKey": "auto_loan_stress_score",
                "label": "Auto-loan growth stress",
                "color": _PALETTE[5],
            }
        )
    labor_columns = ["UNRATE"]
    labor_series = [
        {
            "dataKey": "UNRATE",
            "label": "U3 unemployment",
            "color": _PALETTE[0],
            "stackId": "labor",
        }
    ]
    if "u6_gap" in panel and panel["u6_gap"].notna().any():
        labor_columns.append("u6_gap")
        labor_series.append(
            {
                "dataKey": "u6_gap",
                "label": "U6 less U3",
                "color": _PALETTE[1],
                "stackId": "labor",
            }
        )

    if real_consumption_key is not None:
        buffer_chart_id = "consumption_savings_tradeoff"
        buffer_chart = {
            "id": buffer_chart_id,
            "type": "composed",
            "title": "Real Consumption Growth Versus Saving Rate",
            "description": "Real PCE growth remaining positive while savings stay low is the dashboard's central conflict.",
            "xAxisKey": "date",
            "series": [
                {
                    "dataKey": "PSAVERT",
                    "label": "Personal saving rate (%)",
                    "color": _PALETTE[1],
                    "type": "bar",
                },
                {
                    "dataKey": "real_pce_yoy",
                    "label": "Real PCE YoY (%)",
                    "color": _PALETTE[2],
                    "type": "line",
                },
            ],
            "data": _records(panel, ["PSAVERT", "real_pce_yoy"]),
            "referenceLines": [
                {
                    "axis": "y",
                    "value": 0,
                    "y": 0,
                    "label": "No real PCE growth",
                    "color": "#111827",
                    "dashed": True,
                }
            ],
            "referenceAreas": bands,
            "methods_used": [_METHOD],
        }
        buffer_insight = "Tests whether spending resilience is being financed by thinner buffers."
    else:
        buffer_chart_id = "income_savings_tradeoff"
        buffer_chart = {
            "id": buffer_chart_id,
            "type": "composed",
            "title": "Savings And Income Stress Without Real PCE",
            "description": "When real consumption is unavailable, normalized savings and income stress show whether the cushion is thinning.",
            "xAxisKey": "date",
            "series": [
                {
                    "dataKey": "savings_stress",
                    "label": "Savings stress score",
                    "color": _PALETTE[1],
                    "type": "bar",
                },
                {
                    "dataKey": "income_stress",
                    "label": "Income/wage stress score",
                    "color": _PALETTE[2],
                    "type": "line",
                },
            ],
            "data": _records(panel, ["savings_stress", "income_stress"]),
            "referenceAreas": bands,
            "methods_used": [_METHOD],
        }
        buffer_insight = "Preserves the buffer-vs-income conflict when no real-consumption series was handed off."

    charts = {
        "consumer_stress_overlay": {
            "id": "consumer_stress_overlay",
            "type": "composed",
            "title": "Consumer Stress Components Since 1990",
            "description": "Normalized 0-100 stress scores align savings, wages, labor, inflation, sentiment, and credit on one scale.",
            "xAxisKey": "date",
            "series": [
                {
                    "dataKey": key,
                    "label": label,
                    "color": _PALETTE[index % len(_PALETTE)],
                    "type": "line",
                }
                for index, (label, key) in enumerate(component_labels)
            ],
            "data": _records(panel, overlay_columns),
            "referenceAreas": bands,
            "methods_used": [_METHOD],
        },
        "savings_vs_sentiment": {
            "id": "savings_vs_sentiment",
            "type": "scatter",
            "title": "Savings Cushion Versus Consumer Sentiment",
            "description": "Each point is a monthly observation; bubble size is headline CPI inflation pressure.",
            "xKey": "saving_rate",
            "yKey": "sentiment",
            "xLabel": "Personal saving rate (%)",
            "yLabel": "Michigan consumer sentiment",
            "sizeKey": "inflation_size",
            "colorKey": "period",
            "color": _PALETTE[0],
            "data": scatter_rows,
            "methods_used": [_METHOD],
        },
        "unemployment_depth": {
            "id": "unemployment_depth",
            "type": "area",
            "title": "Headline Unemployment And Hidden Slack",
            "description": "U3 unemployment plus U6-U3 hidden slack when available expose labor depth beyond the headline rate.",
            "xAxisKey": "date",
            "series": labor_series,
            "data": _records(panel, labor_columns),
            "referenceAreas": bands,
            "methods_used": [_METHOD],
        },
        "consumer_profile_radar": {
            "id": "consumer_profile_radar",
            "type": "radar",
            "title": "Latest Stress Profile Versus 2019",
            "description": "Normalized component stress scores compare the latest available readings with the pre-pandemic baseline.",
            "angleKey": "metric",
            "series": [
                {"dataKey": "latest_stress", "label": "Latest stress", "color": _PALETTE[3]},
                {"dataKey": "pre_pandemic_stress", "label": "2019 baseline", "color": _PALETTE[2]},
            ],
            "data": radar_rows,
            "methods_used": [_METHOD],
        },
        buffer_chart_id: buffer_chart,
        "credit_stress": {
            "id": "credit_stress",
            "type": "line",
            "title": "Credit Stress Score",
            "description": "Delinquency and credit-growth stress are normalized to identify whether credit is normalizing or breaking.",
            "xAxisKey": "date",
            "series": credit_series,
            "data": _records(panel, credit_columns),
            "referenceAreas": bands,
            "methods_used": [_METHOD],
        },
        "auto_loan_stress": {
            "id": "auto_loan_stress",
            "type": "radialBar",
            "title": "Latest Component Stress Scores",
            "description": "Positive 0-100 scores highlight current auto-credit, broad-credit, inflation, and labor pressures.",
            "data": latest_component_rows,
            "methods_used": [_METHOD],
        },
        "consumption_sentiment_contributions": {
            "id": "consumption_sentiment_contributions",
            "type": "treemap",
            "title": "Current Stress Contribution Profile",
            "description": "Contribution hierarchy of the latest normalized stress readings used in the consumer decision.",
            "valueKey": "size",
            "data": treemap_rows,
            "methods_used": [_METHOD],
        },
    }

    latest_date_value = panel["date"].dropna().max()
    latest_income_wage_index = _latest_value(panel, "income_wage_index")
    latest_snapshot = {
        "date": _date_label(latest_date_value) if pd.notna(latest_date_value) else None,
        "saving_rate": _latest_score(panel, "PSAVERT"),
        "real_wage_index_2019_100": latest_income_wage_index,
        "income_or_wage_index_2019_100": latest_income_wage_index,
        "unemployment_rate": _latest_score(panel, "UNRATE"),
        "cpi_yoy": _latest_score(panel, "cpi_yoy"),
        "consumer_sentiment": _latest_score(panel, "UMCSENT"),
        "real_pce_yoy": _latest_value(panel, "real_pce_yoy"),
        "total_credit_yoy": _latest_value(panel, "total_credit_yoy"),
        "delinquency_rate": _latest_value(panel, "delinquency_rate"),
    }
    stress_scores = {row["name"]: row["value"] for row in latest_component_rows}
    average_stress = round(sum(stress_scores.values()) / max(len(stress_scores), 1), 1)
    if average_stress >= 70:
        assessment = "high stress"
    elif average_stress >= 45:
        assessment = "moderate stress"
    else:
        assessment = "contained stress"

    execution_summary = {
        "status": "success",
        "analysis_type": "consumer_stress_dashboard",
        "query": query,
        "latest_snapshot": latest_snapshot,
        "stress_assessment": {
            "average_component_stress": average_stress,
            "assessment": assessment,
            "component_scores": stress_scores,
        },
        "income_or_wage_proxy": income_wage_key,
        "consumption_proxy": real_consumption_key,
        "credit_proxy": delinquency_key or total_credit_key,
        "auto_credit_proxy": auto_key,
        "chart_insight_map": {
            "consumer_stress_overlay": "Shows whether stress is broadening across components or isolated in one dimension.",
            "savings_vs_sentiment": "Separates low-savings necessity spending from confidence-led spending.",
            "unemployment_depth": "Shows whether the strong U3 headline hides broader U6 slack.",
            "consumer_profile_radar": "Compares the latest stress mix with the 2019 pre-pandemic baseline.",
            buffer_chart_id: buffer_insight,
            "credit_stress": "Distinguishes orderly delinquency normalization from accelerating credit stress.",
            "auto_loan_stress": "Flags whether auto-credit pressure is concentrated or part of broad stress.",
            "consumption_sentiment_contributions": "Ranks which components drive the current consumer-stress call.",
        },
        "methods_used": [_METHOD],
        "statistical_summary": (
            "The dashboard converts FRED savings, income/wage, labor, inflation, "
            "sentiment, optional consumption, and credit series into comparable stress "
            "scores, then preserves raw-rate views where they clarify conflicts "
            "between spending resilience and household financial buffers."
        ),
        "limitations": [
            "Stress scores use historical percentile normalization, not a structural household balance-sheet model.",
            *(
                [
                    "No real consumption series was supplied; the dashboard uses sentiment plus savings and income proxies instead of real PCE growth."
                ]
                if real_consumption_key is None
                else []
            ),
            *(
                [
                    "Quarterly delinquency data are forward-filled for chart alignment and may lag monthly labor and inflation data."
                ]
                if delinquency_key is not None
                else []
            ),
            *(
                ["DTCOLNVHFNM is an auto-loan volume proxy, not total consumer credit outstanding."]
                if auto_key is not None
                else []
            ),
        ],
    }
    return save_quant_outputs(
        output_dir,
        charts,
        execution_summary,
        statistical_summary_excerpt=execution_summary["statistical_summary"],
    )

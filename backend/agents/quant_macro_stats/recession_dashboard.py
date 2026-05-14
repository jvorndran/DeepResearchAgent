"""Deterministic recession-dashboard chart artifacts for FRED panels."""

from __future__ import annotations

from functools import reduce
from pathlib import Path
from typing import Any

import pandas as pd

from .outputs import save_quant_outputs
from .shared import to_json_safe

_PALETTE = ["#3b82f6", "#f59e0b", "#10b981", "#ef4444", "#8b5cf6"]
_METHOD = "deterministic_recession_dashboard_charts"
_CREDIT_KEYS = (
    "TOTALSL",
    "NONREVSL",
    "CREDIT",
    "TOTCI",
    "DRCCLACBS",
    "DRALACBN",
    "NFCI",
    "ANFCI",
    "STLFSI4",
    "BAA10YM",
    "BAMLH0A0HYM2",
    "DTWEXBGS",
)
_CONSUMER_CREDIT_KEYS = {"TOTALSL", "NONREVSL", "CREDIT"}
_COMPONENT_LABELS = {
    "curve_inverted": "Yield curve inversion lead window",
    "gdp_contracting": "Real GDP contracting",
    "labor_deteriorating": "Labor deterioration",
    "production_contracting": "Output contraction",
    "credit_tightening": "Credit/risk tightening",
}


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


def _binary_signal(condition: pd.Series, source: pd.Series) -> pd.Series:
    numeric_source = pd.to_numeric(source, errors="coerce")
    return condition.astype(float).where(numeric_source.notna(), pd.NA)


def _latest_finite(panel: pd.DataFrame, key: str) -> tuple[float | None, str | None]:
    if key not in panel:
        return None, None
    rows = panel[["date", key]].dropna(subset=[key]).copy()
    if rows.empty:
        return None, None
    row = rows.iloc[-1]
    return round(float(row[key]), 3), _date_label(row["date"])


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


def _inversion_markers(panel: pd.DataFrame) -> list[dict[str, Any]]:
    if "T10Y3M" not in panel:
        return []
    rows = panel[["date", "T10Y3M"]].dropna().copy()
    inverted = rows["T10Y3M"] < 0
    starts = rows.loc[inverted & ~inverted.shift(fill_value=False), "date"]
    markers = []
    for value in starts.tail(6):
        timestamp = pd.Timestamp(value)
        markers.append(
            {
                "axis": "x",
                "value": _date_label(timestamp),
                "x": _date_label(timestamp),
                "label": f"{timestamp.year} inversion",
                "color": "#ef4444",
                "dashed": True,
            }
        )
    return markers


def _latest_snapshot(panel: pd.DataFrame, credit_key: str | None) -> dict[str, Any]:
    keys = [
        "T10Y3M",
        "GDPC1",
        "gdpc1_yoy",
        "UNRATE",
        "unrate_gap_12m",
        "indpro_yoy",
        "risk_score",
    ]
    if credit_key:
        keys.append(credit_key)
    snapshot: dict[str, Any] = {}
    latest_dates: list[pd.Timestamp] = []
    for key in keys:
        value, as_of = _latest_finite(panel, key)
        snapshot[key] = value
        if as_of:
            snapshot[f"{key}_as_of"] = as_of
            latest_dates.append(pd.Timestamp(as_of))
    if not latest_dates:
        return {}
    return {"date": _date_label(max(latest_dates)), **snapshot}


def _signal_component_rows(
    risk_components: pd.DataFrame,
    labels: dict[str, str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    total = max(len(risk_components), 1)
    for key, label in labels.items():
        if key not in risk_components:
            continue
        count = int(pd.to_numeric(risk_components[key], errors="coerce").fillna(0).sum())
        if count <= 0:
            continue
        rows.append(
            {
                "name": label,
                "value": count,
                "size": count,
                "incidence_pct": round(count / total * 100, 1),
                "color": _PALETTE[len(rows) % len(_PALETTE)],
            }
        )
    return rows


def _latest_component_values(
    risk_components: pd.DataFrame,
    panel: pd.DataFrame,
) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for key in risk_components:
        values = pd.to_numeric(risk_components[key], errors="coerce").dropna()
        if values.empty:
            latest[key] = {"value": 0.0, "as_of": None}
            continue
        index = values.index[-1]
        latest[key] = {
            "value": float(values.iloc[-1]),
            "as_of": _date_label(panel.loc[index, "date"]),
        }
    return latest


def _growth_unemployment_scatter_rows(panel: pd.DataFrame) -> list[dict[str, Any]]:
    if "gdpc1_yoy" not in panel:
        return []
    rows = panel.dropna(subset=["gdpc1_yoy", "UNRATE", "unrate_gap_12m"]).iloc[::3].copy()
    records: list[dict[str, Any]] = []
    for _, row in rows.iterrows():
        recession = float(row.get("USREC") or 0) >= 0.5
        records.append(
            {
                "date": _date_label(row["date"]),
                "gdpc1_yoy": round(float(row["gdpc1_yoy"]), 3),
                "unrate_gap_12m": round(float(row["unrate_gap_12m"]), 3),
                "unemployment_rate": round(float(row["UNRATE"]), 3),
                "recession_size": 12 if recession else 4,
                "phase": "Recession" if recession else "Expansion",
            }
        )
    return records


def _spread_unemployment_scatter_rows(panel: pd.DataFrame) -> list[dict[str, Any]]:
    if "T10Y3M" not in panel or "UNRATE" not in panel:
        return []
    rows = panel.dropna(subset=["T10Y3M", "UNRATE"]).iloc[::3].copy()
    records: list[dict[str, Any]] = []
    for _, row in rows.iterrows():
        recession = float(row.get("USREC") or 0) >= 0.5
        inverted = float(row["T10Y3M"]) < 0
        records.append(
            {
                "date": _date_label(row["date"]),
                "yield_spread": round(float(row["T10Y3M"]), 3),
                "unemployment_rate": round(float(row["UNRATE"]), 3),
                "unrate_gap_12m": (
                    None
                    if pd.isna(row.get("unrate_gap_12m"))
                    else round(float(row["unrate_gap_12m"]), 3)
                ),
                "recession_size": 14 if recession else 5,
                "phase": (
                    "Recession"
                    if recession
                    else ("Inverted curve" if inverted else "Expansion")
                ),
                "phase_color": (
                    "#ef4444" if recession else ("#f59e0b" if inverted else "#3b82f6")
                ),
            }
        )
    return records


def build_recession_dashboard_outputs(
    data_files: dict[str, str],
    output_dir: str | Path,
    *,
    query: str | None = None,
) -> dict[str, Any]:
    """Build renderable recession-dashboard charts from FRED CSV files."""

    required = {
        "UNRATE": _matching_key(data_files, ("UNRATE",)),
        "INDPRO": _matching_key(data_files, ("INDPRO",)),
        "USREC": _matching_key(data_files, ("USREC",)),
    }
    missing = [name for name, key in required.items() if key is None]
    if missing:
        raise ValueError(
            f"missing required FRED series for recession dashboard: {', '.join(missing)}"
        )

    curve_key = _matching_key(data_files, ("T10Y3M",))
    gdp_key = _matching_key(data_files, ("GDPC1", "GDP"))
    if curve_key is None and gdp_key is None:
        raise ValueError(
            "missing required FRED series for recession dashboard: T10Y3M or GDPC1"
        )

    credit_key = _matching_key(data_files, _CREDIT_KEYS)
    frames = [
        _read_monthly_series(data_files[source_key], target_key)
        for target_key, source_key in required.items()
        if source_key is not None
    ]
    if curve_key:
        frames.append(_read_monthly_series(data_files[curve_key], "T10Y3M"))
    if gdp_key:
        frames.append(_read_monthly_series(data_files[gdp_key], "GDPC1"))
    if credit_key:
        frames.append(_read_monthly_series(data_files[credit_key], str(credit_key)))
    panel = reduce(lambda left, right: left.merge(right, on="date", how="outer"), frames)
    panel = panel.sort_values("date").reset_index(drop=True)

    panel["unrate_gap_12m"] = panel["UNRATE"] - panel["UNRATE"].rolling(12, min_periods=3).min()
    panel["indpro_yoy"] = panel["INDPRO"].pct_change(12) * 100
    if "GDPC1" in panel:
        panel["GDPC1"] = pd.to_numeric(panel["GDPC1"], errors="coerce").ffill()
        panel["gdpc1_yoy"] = panel["GDPC1"].pct_change(12) * 100
    if credit_key:
        panel["credit_6m_change"] = (
            pd.to_numeric(panel[credit_key], errors="coerce").pct_change(6) * 100
        )
    else:
        panel["credit_6m_change"] = pd.NA

    risk_component_columns: dict[str, Any] = {
        "labor_deteriorating": _binary_signal(
            panel["unrate_gap_12m"] >= 0.5,
            panel["unrate_gap_12m"],
        ),
        "production_contracting": _binary_signal(panel["indpro_yoy"] < 0, panel["indpro_yoy"]),
    }
    if "T10Y3M" in panel:
        curve_lead_window = (
            pd.to_numeric(panel["T10Y3M"], errors="coerce")
            .rolling(24, min_periods=1)
            .min()
            < 0
        )
        risk_component_columns["curve_inverted"] = _binary_signal(
            curve_lead_window,
            panel["T10Y3M"],
        )
    if "gdpc1_yoy" in panel:
        risk_component_columns["gdp_contracting"] = _binary_signal(
            panel["gdpc1_yoy"] < 0,
            panel["gdpc1_yoy"],
        )
    if credit_key:
        credit_series = pd.to_numeric(panel["credit_6m_change"], errors="coerce")
        if credit_key in _CONSUMER_CREDIT_KEYS:
            credit_condition = credit_series < 0
        else:
            credit_condition = credit_series > 5
        risk_component_columns["credit_tightening"] = _binary_signal(
            credit_condition,
            credit_series,
        )
    risk_components = pd.DataFrame(risk_component_columns)
    component_count = max(len(risk_components.columns), 1)
    panel["risk_score"] = risk_components.fillna(0).sum(axis=1) / component_count * 100
    bands = _recession_bands(panel)
    component_labels = {
        key: label for key, label in _COMPONENT_LABELS.items() if key in risk_components
    }
    component_rows = _signal_component_rows(risk_components, component_labels)
    historical_incidence = {row["name"]: row["incidence_pct"] for row in component_rows}
    latest_components = _latest_component_values(risk_components, panel)
    radar_rows = [
        {
            "metric": label,
            "current_risk": round(float(latest_components.get(key, {}).get("value", 0)) * 100, 1),
            "historical_signal_months_pct": historical_incidence.get(label, 0),
            "as_of": latest_components.get(key, {}).get("as_of"),
        }
        for key, label in component_labels.items()
    ]
    sankey_nodes = [
        {"name": "Observed months"},
        *[{"name": row["name"]} for row in component_rows],
        {"name": "Composite signal inputs"},
    ]
    sankey_links = [
        {"source": 0, "target": index + 1, "value": row["value"]}
        for index, row in enumerate(component_rows)
    ] + [
        {"source": index + 1, "target": len(sankey_nodes) - 1, "value": row["value"]}
        for index, row in enumerate(component_rows)
    ]

    credit_label = str(credit_key or "credit_proxy")
    if credit_key == "DTWEXBGS":
        credit_description = (
            "Dollar-index proxy is used only as risk-sentiment context; it is not a direct credit spread."
        )
    elif credit_key:
        credit_description = "Credit/financial-conditions proxy included from the data handoff."
    else:
        credit_description = "No credit or financial-conditions proxy was included in the data handoff."
    has_curve = "T10Y3M" in panel
    if not has_curve:
        panel["T10Y3M"] = pd.NA
    charts = {
        "yield_curve_recession_lead": {
            "id": "yield_curve_recession_lead",
            "type": "line",
            "title": "Yield-Curve Inversions Before Recessions",
            "description": "10Y-3M Treasury spread with recession bands and inversion-start markers.",
            "xAxisKey": "date",
            "series": [{"dataKey": "T10Y3M", "label": "10Y-3M spread (pp)", "color": _PALETTE[0]}],
            "data": _records(panel, ["T10Y3M"]),
            "referenceLines": [
                {
                    "axis": "y",
                    "value": 0,
                    "y": 0,
                    "label": "Inversion threshold",
                    "color": "#111827",
                    "dashed": True,
                },
                *_inversion_markers(panel),
            ],
            "referenceAreas": bands,
            "methods_used": [_METHOD],
        },
        "labor_output_confirmation": {
            "id": "labor_output_confirmation",
            "type": "composed",
            "title": "Labor And Output Confirmation Signals",
            "description": "Unemployment, industrial production, and GDP growth show whether recession stress is entering the real economy.",
            "xAxisKey": "date",
            "series": [
                {
                    "dataKey": "UNRATE",
                    "label": "Unemployment rate (%)",
                    "color": _PALETTE[1],
                    "type": "line",
                },
                {
                    "dataKey": "indpro_yoy",
                    "label": "Industrial production YoY (%)",
                    "color": _PALETTE[2],
                    "type": "bar",
                },
            ],
            "data": _records(panel, ["UNRATE", "indpro_yoy"]),
            "referenceAreas": bands,
            "methods_used": [_METHOD],
        },
        "credit_conditions_trend": {
            "id": "credit_conditions_trend",
            "type": "composed",
            "title": f"{credit_label} Credit Conditions Trend",
            "description": (
                f"{credit_description} Bars show six-month change to reveal "
                "tightening or stress shifts."
            ),
            "xAxisKey": "date",
            "series": [
                {
                    "dataKey": credit_label,
                    "label": credit_label,
                    "color": _PALETTE[3],
                    "type": "line",
                },
                {
                    "dataKey": "credit_6m_change",
                    "label": "Six-month change (%)",
                    "color": _PALETTE[1],
                    "type": "bar",
                },
            ],
            "data": _records(panel, [credit_label, "credit_6m_change"]) if credit_key else [],
            "referenceAreas": bands,
            "methods_used": [_METHOD],
        },
        "recession_signal_stack": {
            "id": "recession_signal_stack",
            "type": "area",
            "title": "Composite Recession Signal Stack",
            "description": "Equal-weighted score from the available recession-cycle signals.",
            "xAxisKey": "date",
            "series": [
                {
                    "dataKey": "risk_score",
                    "label": "Recession signal score (0-100)",
                    "color": _PALETTE[4],
                }
            ],
            "data": _records(panel, ["risk_score"]),
            "referenceLines": [
                {
                    "axis": "y",
                    "value": 50,
                    "y": 50,
                    "label": "Half of signals active",
                    "color": "#f59e0b",
                    "dashed": True,
                },
                {
                    "axis": "y",
                    "value": 75,
                    "y": 75,
                    "label": "Most signals active",
                    "color": "#ef4444",
                    "dashed": True,
                },
            ],
            "referenceAreas": bands,
            "methods_used": [_METHOD],
        },
        "current_recession_risk_profile": {
            "id": "current_recession_risk_profile",
            "type": "radar",
            "title": "Current Recession Risk Profile",
            "description": "Latest available binary recession-risk components with historical signal incidence for renderable context.",
            "angleKey": "metric",
            "series": [
                {
                    "dataKey": "current_risk",
                    "label": "Current risk component",
                    "color": _PALETTE[0],
                },
                {
                    "dataKey": "historical_signal_months_pct",
                    "label": "Historical signal-month incidence (%)",
                    "color": _PALETTE[3],
                }
            ],
            "data": radar_rows,
            "methods_used": [_METHOD],
        },
    }
    if not has_curve:
        charts.pop("yield_curve_recession_lead")
    if "gdpc1_yoy" in panel and (not has_curve or not credit_key):
        charts["real_gdp_growth_cycle"] = {
            "id": "real_gdp_growth_cycle",
            "type": "line",
            "title": "Real GDP Growth Across Recession Cycles",
            "description": "Real GDP year-over-year growth mapped against NBER recession bands.",
            "xAxisKey": "date",
            "series": [
                {
                    "dataKey": "gdpc1_yoy",
                    "label": "Real GDP YoY (%)",
                    "color": _PALETTE[0],
                }
            ],
            "data": _records(panel, ["gdpc1_yoy"]),
            "referenceLines": [
                {
                    "axis": "y",
                    "value": 0,
                    "y": 0,
                    "label": "Zero growth",
                    "color": "#111827",
                    "dashed": True,
                }
            ],
            "referenceAreas": bands,
            "methods_used": [_METHOD],
        }
    if "gdpc1_yoy" in panel:
        charts["labor_output_confirmation"]["series"].append(
            {
                "dataKey": "gdpc1_yoy",
                "label": "Real GDP YoY (%)",
                "color": _PALETTE[0],
                "type": "line",
            }
        )
        charts["labor_output_confirmation"]["data"] = _records(
            panel, ["UNRATE", "indpro_yoy", "gdpc1_yoy"]
        )
    scatter_rows = _growth_unemployment_scatter_rows(panel)
    if scatter_rows and (not credit_key or not has_curve):
        charts["growth_unemployment_scatter"] = {
            "id": "growth_unemployment_scatter",
            "type": "scatter",
            "title": "Growth Versus Labor-Market Deterioration",
            "description": "Each point links real GDP growth to unemployment deterioration; larger points mark recession months.",
            "xKey": "gdpc1_yoy",
            "yKey": "unrate_gap_12m",
            "xLabel": "Real GDP YoY (%)",
            "yLabel": "Unemployment gap versus 12-month low (pp)",
            "sizeKey": "recession_size",
            "colorKey": "phase",
            "color": _PALETTE[0],
            "data": scatter_rows,
            "methods_used": [_METHOD],
        }
    spread_scatter_rows = _spread_unemployment_scatter_rows(panel)
    if spread_scatter_rows and has_curve:
        charts["spread_unemployment_scatter"] = {
            "id": "spread_unemployment_scatter",
            "type": "scatter",
            "title": "Yield Spread Versus Unemployment",
            "description": (
                "Bubble view of 10Y-3M spread against unemployment; recession "
                "months are larger and colored separately."
            ),
            "xKey": "yield_spread",
            "yKey": "unemployment_rate",
            "xLabel": "10Y-3M Treasury spread (pp)",
            "yLabel": "Unemployment rate (%)",
            "sizeKey": "recession_size",
            "colorKey": "phase_color",
            "color": _PALETTE[0],
            "data": spread_scatter_rows,
            "methods_used": [_METHOD],
        }
    if not credit_key:
        charts.pop("credit_conditions_trend")
    if component_rows:
        charts.update(
            {
                "historical_signal_incidence": {
                    "id": "historical_signal_incidence",
                    "type": "radialBar",
                    "title": "Historical Signal Incidence",
                    "description": "Count of months in the panel where each recession-risk component was active.",
                    "data": component_rows,
                    "methods_used": [_METHOD],
                },
                "signal_incidence_treemap": {
                    "id": "signal_incidence_treemap",
                    "type": "treemap",
                    "title": "Signal Incidence Contribution",
                    "description": "Relative contribution of active signal-month counts by component.",
                    "valueKey": "size",
                    "data": component_rows,
                    "methods_used": [_METHOD],
                },
                "signal_flow_decomposition": {
                    "id": "signal_flow_decomposition",
                    "type": "sankey",
                    "title": "Signal Flow Decomposition",
                    "description": "Observed months flowing through active recession-risk components into the composite input stack.",
                    "data": {"nodes": sankey_nodes, "links": sankey_links},
                    "methods_used": [_METHOD],
                },
            }
        )
    if len(charts) > 8 and "spread_unemployment_scatter" in charts:
        charts.pop("historical_signal_incidence", None)

    available_signal_labels = [
        component_labels[key]
        for key in risk_components.columns
        if key in component_labels
    ]
    recession_count = len(bands)
    execution_summary = {
        "status": "success",
        "analysis_type": "recession_dashboard",
        "query": query,
        "latest_snapshot": _latest_snapshot(panel, str(credit_key) if credit_key else None),
        "coverage_start": _date_label(panel["date"].dropna().min()),
        "coverage_end": _date_label(panel["date"].dropna().max()),
        "recession_band_count": len(bands),
        "recession_start_count": recession_count,
        "credit_proxy": credit_key,
        "credit_proxy_caveat": credit_description,
        "available_signal_components": available_signal_labels,
        "methods_used": [_METHOD],
        "statistical_summary": (
            "The dashboard combines the available recession-cycle signals "
            f"({', '.join(available_signal_labels)}) into renderable charts with "
            "NBER recession bands."
        ),
        "limitations": [
            "Composite scores are transparent signal counts, not recession probabilities.",
            "Latest observations can differ by FRED release calendar; charts drop stale empty tails by series.",
        ],
    }
    return save_quant_outputs(
        output_dir,
        to_json_safe(charts),
        execution_summary,
        statistical_summary_excerpt=execution_summary["statistical_summary"],
    )

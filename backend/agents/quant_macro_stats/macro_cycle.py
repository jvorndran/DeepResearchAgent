"""Deterministic broad macro-cycle chart artifacts for FRED panels."""

from __future__ import annotations

from functools import reduce
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .outputs import save_quant_outputs

_PALETTE = ["#2563eb", "#f59e0b", "#10b981", "#ef4444", "#7c3aed", "#0891b2"]
_METHOD = "deterministic_macro_cycle_chart_pack"
_ANALOG_WINDOWS = [
    {"label": "2001 recession", "start": "2000-07-01", "end": "2002-12-01"},
    {"label": "2008 financial crisis", "start": "2007-07-01", "end": "2009-12-01"},
    {"label": "2020 covid shock", "start": "2019-08-01", "end": "2021-12-01"},
    {"label": "post-pandemic inflation", "start": "2021-01-01", "end": "2023-12-01"},
]
_CATEGORY_COLUMNS = [
    ("Rates", "rates_stress"),
    ("Inflation", "inflation_stress"),
    ("Labor", "labor_stress"),
    ("Output", "output_stress"),
    ("Consumer", "consumer_stress"),
]
_RATE_SIGNAL_CANDIDATES = ("DGS10", "GS10", "T10Y2Y", "T10Y3M")
_CURVE_SPREAD_CANDIDATES = ("T10Y2Y", "T10Y3M")
_CORE_INFLATION_CANDIDATES = ("PCEPILFE", "CPILFESL")
_CONSUMER_STRESS_CANDIDATES = (
    "UMCSENT",
    "PSAVERT",
    "DSPIC96",
    "DPCERA3M086SBEA",
    "PCEC96",
)


def _matching_key(data_files: dict[str, str], candidates: tuple[str, ...]) -> str | None:
    normalized = {str(key).upper(): str(key) for key in data_files}
    for candidate in candidates:
        candidate_upper = candidate.upper()
        if candidate_upper in normalized:
            return normalized[candidate_upper]
        for key_upper, original in normalized.items():
            if key_upper.startswith(f"{candidate_upper}_"):
                return original
    return None


def _key_matches(source_key: str | None, candidates: tuple[str, ...]) -> bool:
    if source_key is None:
        return False
    source_upper = str(source_key).upper()
    return any(
        source_upper == candidate or source_upper.startswith(f"{candidate}_")
        for candidate in candidates
    )


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
    return number if np.isfinite(number) else None


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


def _has_values(frame: pd.DataFrame, column: str) -> bool:
    return column in frame and pd.to_numeric(frame[column], errors="coerce").notna().any()


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


def _mean_available(frame: pd.DataFrame, columns: list[str]) -> pd.Series:
    available = [column for column in columns if _has_values(frame, column)]
    if not available:
        return pd.Series([50.0] * len(frame), index=frame.index)
    return frame[available].mean(axis=1, skipna=True).fillna(50.0)


def _latest_valid_row(panel: pd.DataFrame, columns: list[str]) -> pd.Series:
    rows = panel.dropna(how="all", subset=[column for column in columns if column in panel])
    if rows.empty:
        return panel.tail(1).iloc[0]
    return rows.tail(1).iloc[0]


def _row_at_or_before(panel: pd.DataFrame, date: pd.Timestamp) -> pd.Series:
    rows = panel.loc[panel["date"] <= date]
    if rows.empty:
        return panel.head(1).iloc[0]
    return rows.tail(1).iloc[0]


def _value_change(latest: pd.Series, prior: pd.Series, column: str) -> float | None:
    latest_value = _finite(latest.get(column))
    prior_value = _finite(prior.get(column))
    if latest_value is None or prior_value is None:
        return None
    return round(latest_value - prior_value, 3)


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


def _latest_year_band(panel: pd.DataFrame, latest_date: pd.Timestamp) -> dict[str, Any]:
    start = max(panel["date"].min(), latest_date - pd.DateOffset(years=1))
    return {
        "x1": _date_label(start),
        "x2": _date_label(latest_date),
        "label": "Latest year",
        "fill": "#dbeafe",
        "opacity": 0.32,
    }


def _reference_areas(panel: pd.DataFrame, latest_date: pd.Timestamp) -> list[dict[str, Any]]:
    return [*_recession_bands(panel)[-4:], _latest_year_band(panel, latest_date)]


def _window_profile(panel: pd.DataFrame, start: Any, end: Any) -> dict[str, float]:
    mask = (panel["date"] >= pd.Timestamp(start)) & (panel["date"] <= pd.Timestamp(end))
    rows = panel.loc[mask]
    profile: dict[str, float] = {}
    for label, column in _CATEGORY_COLUMNS:
        if column not in rows:
            profile[label] = 50.0
            continue
        values = pd.to_numeric(rows[column], errors="coerce").dropna()
        profile[label] = 50.0 if values.empty else round(float(values.mean()), 2)
    return profile


def _distance(current: dict[str, float], profile: dict[str, float]) -> float:
    diffs = [
        current[label] - profile[label]
        for label, _ in _CATEGORY_COLUMNS
        if _finite(current.get(label)) is not None and _finite(profile.get(label)) is not None
    ]
    if not diffs:
        return 0.0
    return float(np.sqrt(np.mean(np.square(diffs))))


def _positive(value: Any) -> float:
    number = _finite(value)
    if number is None:
        return 1.0
    return round(max(1.0, abs(number)), 3)


def build_macro_cycle_chart_pack_outputs(
    data_files: dict[str, str],
    output_dir: str | Path,
    *,
    query: str | None = None,
) -> dict[str, Any]:
    """Build an eight-chart macro-cycle pack from broad FRED CSV files."""

    required = {
        "FEDFUNDS": _matching_key(data_files, ("FEDFUNDS",)),
        "CPIAUCSL": _matching_key(data_files, ("CPIAUCSL", "PCEPI")),
        "DGS10": _matching_key(data_files, _RATE_SIGNAL_CANDIDATES),
        "UNRATE": _matching_key(data_files, ("UNRATE", "LNS14000000")),
        "PAYEMS": _matching_key(data_files, ("PAYEMS",)),
        "INDPRO": _matching_key(data_files, ("INDPRO",)),
        "GDPC1": _matching_key(data_files, ("GDPC1", "GDP")),
        "USREC": _matching_key(data_files, ("USREC",)),
    }
    missing = [name for name, key in required.items() if key is None]
    consumer_source_key = _matching_key(data_files, _CONSUMER_STRESS_CANDIDATES)
    if consumer_source_key is None:
        missing.append("consumer stress proxy (UMCSENT/PSAVERT/DSPIC96/PCEC96)")
    if missing:
        raise ValueError(
            f"missing required FRED series for macro cycle chart pack: {', '.join(missing)}"
        )
    rate_source_key = required["DGS10"]
    curve_spread_source_key = _matching_key(data_files, _CURVE_SPREAD_CANDIDATES)
    if curve_spread_source_key == rate_source_key:
        curve_spread_source_key = None
    rate_is_curve_spread = _key_matches(rate_source_key, _CURVE_SPREAD_CANDIDATES)
    rate_signal_label = (
        "10Y-2Y yield spread"
        if _key_matches(rate_source_key, ("T10Y2Y",))
        else "10Y-3M yield spread"
        if _key_matches(rate_source_key, ("T10Y3M",))
        else "10Y Treasury yield"
    )
    curve_spread_label = (
        "10Y-2Y yield spread"
        if _key_matches(curve_spread_source_key, ("T10Y2Y",))
        else "10Y-3M yield spread"
        if _key_matches(curve_spread_source_key, ("T10Y3M",))
        else None
    )
    financing_stress_label = (
        "Curve-inversion stress"
        if rate_is_curve_spread
        else "Treasury-rate stress"
    )

    optional = {
        "PSAVERT": _matching_key(data_files, ("PSAVERT",)),
        "UMCSENT": _matching_key(data_files, ("UMCSENT",)),
        "DSPIC96": _matching_key(data_files, ("DSPIC96",)),
        "REAL_CONSUMPTION": _matching_key(data_files, ("DPCERA3M086SBEA", "PCEC96")),
        "T10YIE": _matching_key(data_files, ("T10YIE",)),
        "CIVPART": _matching_key(data_files, ("CIVPART",)),
        "TCU": _matching_key(data_files, ("TCU",)),
        "MORTGAGE30US": _matching_key(data_files, ("MORTGAGE30US",)),
        "CSUSHPISA": _matching_key(data_files, ("CSUSHPISA",)),
        "STLFSI": _matching_key(data_files, ("STLFSI", "STLFSI4")),
        "CORE_INFLATION": _matching_key(data_files, _CORE_INFLATION_CANDIDATES),
        "CURVE_SPREAD": curve_spread_source_key,
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
        for column in required
    ]
    latest_date = min(date for date in core_latest if pd.notna(date))
    panel = panel.loc[panel["date"] <= latest_date].reset_index(drop=True)
    for column in panel.columns:
        if column != "date":
            panel[column] = pd.to_numeric(panel[column], errors="coerce").ffill(limit=3)
    start_date = max(panel["date"].min(), pd.Timestamp(latest_date) - pd.DateOffset(years=40))
    panel = panel.loc[panel["date"] >= start_date].reset_index(drop=True)

    panel["cpi_yoy"] = panel["CPIAUCSL"].pct_change(12) * 100
    if "CORE_INFLATION" in panel:
        panel["core_inflation_yoy"] = panel["CORE_INFLATION"].pct_change(12) * 100
    panel["policy_gap"] = panel["FEDFUNDS"] - panel["cpi_yoy"]
    panel["payroll_yoy"] = panel["PAYEMS"].pct_change(12) * 100
    panel["indpro_yoy"] = panel["INDPRO"].pct_change(12) * 100
    panel["gdpc1_yoy"] = panel["GDPC1"].pct_change(12) * 100
    if "CIVPART" in panel:
        panel["civpart_change_12m"] = panel["CIVPART"].diff(12)
    if "TCU" in panel:
        panel["tcu_gap"] = panel["TCU"] - panel["TCU"].rolling(120, min_periods=24).median()
    if "CSUSHPISA" in panel:
        panel["home_price_yoy"] = panel["CSUSHPISA"].pct_change(12) * 100
    if "DSPIC96" in panel:
        panel["income_yoy"] = panel["DSPIC96"].pct_change(12) * 100
    if "REAL_CONSUMPTION" in panel:
        panel["real_consumption_yoy"] = panel["REAL_CONSUMPTION"].pct_change(12) * 100

    rate_stress_panel = panel.assign(
        fed_gap_stress=_stress_series(panel["policy_gap"], high_is_stress=True),
        rate_signal_stress=_stress_series(
            panel["DGS10"],
            high_is_stress=not rate_is_curve_spread,
        ),
    )
    rate_stress_columns = ["fed_gap_stress", "rate_signal_stress"]
    if _has_values(panel, "CURVE_SPREAD"):
        rate_stress_panel = rate_stress_panel.assign(
            curve_inversion_stress=_stress_series(
                panel["CURVE_SPREAD"],
                high_is_stress=False,
            )
        )
        rate_stress_columns.append("curve_inversion_stress")
    panel["rates_stress"] = _mean_available(rate_stress_panel, rate_stress_columns)
    inflation_stress_panel = panel.assign(
        cpi_stress=_stress_series(panel["cpi_yoy"], high_is_stress=True)
    )
    inflation_stress_columns = ["cpi_stress"]
    if _has_values(panel, "core_inflation_yoy"):
        inflation_stress_panel = inflation_stress_panel.assign(
            core_inflation_stress=_stress_series(
                panel["core_inflation_yoy"],
                high_is_stress=True,
            )
        )
        inflation_stress_columns.append("core_inflation_stress")
    panel["inflation_stress"] = _mean_available(
        inflation_stress_panel,
        inflation_stress_columns,
    )
    panel["labor_stress"] = _mean_available(
        panel.assign(
            unrate_stress=_stress_series(panel["UNRATE"], high_is_stress=True),
            payroll_stress=_stress_series(panel["payroll_yoy"], high_is_stress=False),
        ),
        ["unrate_stress", "payroll_stress"],
    )
    panel["output_stress"] = _mean_available(
        panel.assign(
            indpro_stress=_stress_series(panel["indpro_yoy"], high_is_stress=False),
            gdp_stress=_stress_series(panel["gdpc1_yoy"], high_is_stress=False),
            tcu_stress=_stress_series(panel.get("tcu_gap", panel["indpro_yoy"]), high_is_stress=False),
        ),
        ["indpro_stress", "gdp_stress", "tcu_stress"],
    )
    if _has_values(panel, "PSAVERT"):
        panel["saving_stress"] = _stress_series(panel["PSAVERT"], high_is_stress=False)
    if _has_values(panel, "UMCSENT"):
        panel["sentiment_stress"] = _stress_series(panel["UMCSENT"], high_is_stress=False)
    if _has_values(panel, "income_yoy"):
        panel["income_stress"] = _stress_series(panel["income_yoy"], high_is_stress=False)
    if _has_values(panel, "real_consumption_yoy"):
        panel["consumption_stress"] = _stress_series(
            panel["real_consumption_yoy"],
            high_is_stress=False,
        )
    panel["financing_stress"] = (
        _stress_series(panel["MORTGAGE30US"], high_is_stress=True)
        if "MORTGAGE30US" in panel
        else _stress_series(panel["DGS10"], high_is_stress=not rate_is_curve_spread)
    )
    consumer_stress_inputs = [
        *(["saving_stress"] if _has_values(panel, "saving_stress") else []),
        *(["income_stress"] if _has_values(panel, "income_stress") else []),
        *(["consumption_stress"] if _has_values(panel, "consumption_stress") else []),
        *(["sentiment_stress"] if _has_values(panel, "sentiment_stress") else []),
        "financing_stress",
        "inflation_stress",
    ]
    panel["consumer_stress"] = _mean_available(
        panel,
        consumer_stress_inputs,
    )
    panel["macro_cycle_stress"] = _mean_available(
        panel,
        [column for _, column in _CATEGORY_COLUMNS],
    )

    latest_row = _latest_valid_row(panel, [column for _, column in _CATEGORY_COLUMNS])
    latest_date = pd.Timestamp(latest_row["date"])
    prior_row = _row_at_or_before(panel, latest_date - pd.DateOffset(years=1))
    recent_panel = panel.loc[panel["date"] >= latest_date - pd.DateOffset(years=12)]
    references = _reference_areas(recent_panel, latest_date)

    latest_changes = [
        ("Fed funds", "FEDFUNDS", "pp"),
        ("CPI YoY", "cpi_yoy", "pp"),
        *(
            [("Core inflation YoY", "core_inflation_yoy", "pp")]
            if _has_values(panel, "core_inflation_yoy")
            else []
        ),
        (rate_signal_label, "DGS10", "pp"),
        *(
            [(curve_spread_label or "Yield spread", "CURVE_SPREAD", "pp")]
            if _has_values(panel, "CURVE_SPREAD")
            else []
        ),
        ("Unemployment", "UNRATE", "pp"),
        ("Payroll growth", "payroll_yoy", "pp"),
        ("Industrial production", "indpro_yoy", "pp"),
        ("Real GDP", "gdpc1_yoy", "pp"),
        ("Consumer stress", "consumer_stress", "score"),
    ]
    change_rows = [
        {
            "indicator": label,
            "change": change,
            "unit": unit,
            "latest_value": _round(latest_row.get(column)),
        }
        for label, column, unit in latest_changes
        if (change := _value_change(latest_row, prior_row, column)) is not None
    ]

    current_window = {
        "label": "current",
        "start": _date_label(latest_date - pd.DateOffset(months=23)),
        "end": _date_label(latest_date),
    }
    current_profile = _window_profile(panel, current_window["start"], current_window["end"])
    prior_profile = _window_profile(
        panel,
        latest_date - pd.DateOffset(months=35),
        latest_date - pd.DateOffset(months=12),
    )
    analog_rows: list[dict[str, Any]] = []
    analog_profiles: dict[str, dict[str, float]] = {}
    for window in _ANALOG_WINDOWS:
        profile = _window_profile(panel, window["start"], window["end"])
        distance = _distance(current_profile, profile)
        analog_profiles[window["label"]] = profile
        analog_rows.append(
            {
                "analog": window["label"],
                "labor_gap": round(current_profile["Labor"] - profile["Labor"], 3),
                "inflation_gap": round(
                    current_profile["Inflation"] - profile["Inflation"], 3
                ),
                "distance_score": _positive(distance),
                "rates_gap": round(current_profile["Rates"] - profile["Rates"], 3),
                "consumer_gap": round(current_profile["Consumer"] - profile["Consumer"], 3),
            }
        )
    closest = min(analog_rows, key=lambda row: row["distance_score"])["analog"]
    closest_profile = analog_profiles[closest]
    radar_rows = [
        {
            "metric": label,
            "current": round(current_profile[label], 1),
            "prior_year": round(prior_profile[label], 1),
            "closest_analog": round(closest_profile[label], 1),
        }
        for label, _ in _CATEGORY_COLUMNS
    ]
    category_scores = [
        {
            "name": label,
            "value": _positive(latest_row.get(column)),
            "size": _positive(latest_row.get(column)),
            "color": _PALETTE[index % len(_PALETTE)],
        }
        for index, (label, column) in enumerate(_CATEGORY_COLUMNS)
    ]
    sankey_nodes = [{"name": row["name"]} for row in category_scores] + [
        {"name": "Macro cycle pressure"}
    ]
    sink_index = len(sankey_nodes) - 1
    has_saving_stress = _has_values(recent_panel, "saving_stress")
    has_income_stress = _has_values(recent_panel, "income_stress")
    has_consumption_stress = _has_values(recent_panel, "consumption_stress")
    has_sentiment_stress = _has_values(recent_panel, "sentiment_stress")
    consumer_series = [
        {
            "dataKey": "consumer_stress",
            "label": "Composite consumer stress",
            "color": _PALETTE[3],
            "type": "line",
        },
        *(
            [
                {
                    "dataKey": "saving_stress",
                    "label": "Low-saving stress",
                    "color": _PALETTE[1],
                    "type": "bar",
                }
            ]
            if has_saving_stress
            else []
        ),
        *(
            [
                {
                    "dataKey": "income_stress",
                    "label": "Real-income stress",
                    "color": _PALETTE[2],
                    "type": "line",
                }
            ]
            if has_income_stress
            else []
        ),
        *(
            [
                {
                    "dataKey": "consumption_stress",
                    "label": "Real-consumption stress",
                    "color": _PALETTE[0],
                    "type": "line",
                }
            ]
            if has_consumption_stress
            else []
        ),
        *(
            [
                {
                    "dataKey": "sentiment_stress",
                    "label": "Sentiment stress",
                    "color": _PALETTE[4],
                    "type": "line",
                }
            ]
            if has_sentiment_stress
            else []
        ),
        {
            "dataKey": "financing_stress",
            "label": financing_stress_label,
            "color": _PALETTE[5],
            "type": "line",
        },
    ]
    consumer_columns = [str(series["dataKey"]) for series in consumer_series]

    charts = {
        "rates_inflation_overlay": {
            "id": "rates_inflation_overlay",
            "type": "composed",
            "title": "Rates And Inflation: Latest-Year Pivot",
            "description": (
                f"Fed funds, {rate_signal_label}"
                + (f", {curve_spread_label}" if curve_spread_label else "")
                + ", and headline"
                + (" plus core" if _has_values(recent_panel, "core_inflation_yoy") else "")
                + " inflation show whether policy restraint is easing or still tight."
            ),
            "xAxisKey": "date",
            "series": [
                {"dataKey": "FEDFUNDS", "label": "Fed funds", "color": _PALETTE[0], "type": "line"},
                {"dataKey": "DGS10", "label": rate_signal_label, "color": _PALETTE[1], "type": "line"},
                *(
                    [
                        {
                            "dataKey": "CURVE_SPREAD",
                            "label": curve_spread_label or "Yield spread",
                            "color": _PALETTE[5],
                            "type": "line",
                        }
                    ]
                    if _has_values(recent_panel, "CURVE_SPREAD")
                    else []
                ),
                {"dataKey": "cpi_yoy", "label": "CPI YoY", "color": _PALETTE[3], "type": "bar"},
                *(
                    [
                        {
                            "dataKey": "core_inflation_yoy",
                            "label": "Core inflation YoY",
                            "color": _PALETTE[4],
                            "type": "line",
                        }
                    ]
                    if _has_values(recent_panel, "core_inflation_yoy")
                    else []
                ),
                *(
                    [{"dataKey": "T10YIE", "label": "10Y breakeven", "color": "#0f766e", "type": "line"}]
                    if _has_values(recent_panel, "T10YIE")
                    else []
                ),
            ],
            "data": _records(
                recent_panel,
                ["FEDFUNDS", "DGS10"]
                + (["CURVE_SPREAD"] if _has_values(recent_panel, "CURVE_SPREAD") else [])
                + ["cpi_yoy"]
                + (
                    ["core_inflation_yoy"]
                    if _has_values(recent_panel, "core_inflation_yoy")
                    else []
                )
                + (["T10YIE"] if _has_values(recent_panel, "T10YIE") else []),
            ),
            "referenceAreas": references,
            "methods_used": [_METHOD],
        },
        "labor_cycle_breadth": {
            "id": "labor_cycle_breadth",
            "type": "composed",
            "title": "Labor Breadth: Unemployment Versus Payroll Momentum",
            "description": "Unemployment and payroll growth separate a true labor-cycle turn from a noisy monthly headline.",
            "xAxisKey": "date",
            "series": [
                {"dataKey": "UNRATE", "label": "Unemployment rate", "color": _PALETTE[0], "type": "line"},
                {"dataKey": "payroll_yoy", "label": "Payrolls YoY", "color": _PALETTE[2], "type": "bar"},
                *(
                    [{"dataKey": "civpart_change_12m", "label": "Participation 12m change", "color": _PALETTE[4], "type": "line"}]
                    if _has_values(recent_panel, "civpart_change_12m")
                    else []
                ),
            ],
            "data": _records(
                recent_panel,
                ["UNRATE", "payroll_yoy"]
                + (
                    ["civpart_change_12m"]
                    if _has_values(recent_panel, "civpart_change_12m")
                    else []
                ),
            ),
            "referenceAreas": references,
            "methods_used": [_METHOD],
        },
        "output_production_momentum": {
            "id": "output_production_momentum",
            "type": "area",
            "title": "Output Momentum: GDP And Industrial Production",
            "description": "Real GDP and industrial production growth test whether the cycle is cooling through real activity, not only sentiment.",
            "xAxisKey": "date",
            "series": [
                {"dataKey": "gdpc1_yoy", "label": "Real GDP YoY", "color": _PALETTE[2]},
                {"dataKey": "indpro_yoy", "label": "Industrial production YoY", "color": _PALETTE[0]},
                *(
                    [{"dataKey": "tcu_gap", "label": "Capacity-utilization gap", "color": _PALETTE[1]}]
                    if _has_values(recent_panel, "tcu_gap")
                    else []
                ),
            ],
            "data": _records(
                recent_panel,
                ["gdpc1_yoy", "indpro_yoy"]
                + (["tcu_gap"] if _has_values(recent_panel, "tcu_gap") else []),
            ),
            "referenceAreas": references,
            "methods_used": [_METHOD],
        },
        "consumer_stress_pressure": {
            "id": "consumer_stress_pressure",
            "type": "composed",
            "title": (
                "Consumer Stress: Savings, Income, Sentiment, And Financing Cost"
                if has_saving_stress
                else "Consumer Stress: Income, Sentiment, And Financing Cost"
                if has_income_stress or has_sentiment_stress
                else "Consumer Stress: Inflation And Financing Cost"
            ),
            "description": (
                "Normalized stress scores show whether consumer pressure is broadening "
                "or still concentrated in rates, inflation, and sentiment."
            ),
            "xAxisKey": "date",
            "series": consumer_series,
            "data": _records(recent_panel, consumer_columns),
            "referenceAreas": references,
            "methods_used": [_METHOD],
        },
        "latest_year_change_bridge": {
            "id": "latest_year_change_bridge",
            "type": "bar",
            "title": "What Changed In The Latest Year",
            "description": "One-year changes identify which macro-cycle inputs moved enough to alter the committee view.",
            "xAxisKey": "indicator",
            "series": [{"dataKey": "change", "label": "One-year change", "color": _PALETTE[0]}],
            "data": change_rows,
            "referenceLines": [
                {"axis": "y", "value": 0, "y": 0, "label": "No change", "color": "#111827", "dashed": True}
            ],
            "methods_used": [_METHOD],
        },
        "historical_analog_distance": {
            "id": "historical_analog_distance",
            "type": "scatter",
            "title": "Current Cycle Distance From Historical Analogs",
            "description": "Bubble size is total stress-profile distance; x/y positions show labor and inflation gaps versus each analog window.",
            "xKey": "labor_gap",
            "yKey": "inflation_gap",
            "xLabel": "Current minus analog labor stress",
            "yLabel": "Current minus analog inflation stress",
            "sizeKey": "distance_score",
            "colorKey": "analog",
            "color": _PALETTE[0],
            "data": analog_rows,
            "methods_used": [_METHOD, "analog_window_comparison"],
        },
        "macro_cycle_profile": {
            "id": "macro_cycle_profile",
            "type": "radar",
            "title": "Current Macro Profile Versus Prior Year And Closest Analog",
            "description": f"Normalized 0-100 stress scores compare the current cycle with the prior year and {closest}.",
            "angleKey": "metric",
            "series": [
                {"dataKey": "current", "label": "Current", "color": _PALETTE[0]},
                {"dataKey": "prior_year", "label": "Prior year", "color": _PALETTE[2]},
                {"dataKey": "closest_analog", "label": closest, "color": _PALETTE[3]},
            ],
            "data": radar_rows,
            "methods_used": [_METHOD],
        },
        "cycle_pressure_flow": {
            "id": "cycle_pressure_flow",
            "type": "sankey",
            "title": "Synthesis: Component Pressure Flow",
            "description": "The latest component stress scores flow into the macro-cycle pressure view used for decision triage.",
            "data": {
                "nodes": sankey_nodes,
                "links": [
                    {"source": index, "target": sink_index, "value": row["value"]}
                    for index, row in enumerate(category_scores)
                ],
            },
            "methods_used": [_METHOD],
        },
    }

    latest_snapshot = {
        "date": _date_label(latest_date),
        "fed_funds": _round(latest_row.get("FEDFUNDS")),
        "rate_signal_label": rate_signal_label,
        "rate_signal": _round(latest_row.get("DGS10")),
        "curve_spread_label": curve_spread_label,
        "curve_spread": _round(latest_row.get("CURVE_SPREAD")),
        "cpi_yoy": _round(latest_row.get("cpi_yoy")),
        "core_inflation_yoy": _round(latest_row.get("core_inflation_yoy")),
        "unemployment_rate": _round(latest_row.get("UNRATE")),
        "payroll_yoy": _round(latest_row.get("payroll_yoy")),
        "industrial_production_yoy": _round(latest_row.get("indpro_yoy")),
        "real_gdp_yoy": _round(latest_row.get("gdpc1_yoy")),
        "consumer_stress": _round(latest_row.get("consumer_stress")),
        "macro_cycle_stress": _round(latest_row.get("macro_cycle_stress")),
    }
    consumer_component_labels = [
        *(["savings"] if _has_values(panel, "saving_stress") else []),
        *(["real-income"] if _has_values(panel, "income_stress") else []),
        *(["real-consumption"] if _has_values(panel, "consumption_stress") else []),
        *(["sentiment"] if _has_values(panel, "sentiment_stress") else []),
        (
            "mortgage-rate"
            if _has_values(panel, "MORTGAGE30US")
            else "yield-curve/rate"
        ),
        "inflation-pressure",
    ]
    limitations = [
        "The analog comparison is descriptive and compares normalized indicator stress, not causal mechanisms.",
        "Quarterly GDP is forward-filled to monthly dates for chart alignment; use the original FRED release cadence for event studies.",
        "Consumer stress combines available "
        + ", ".join(consumer_component_labels)
        + " inputs because the prompt requested no-key public coverage.",
    ]
    if not _has_values(panel, "PSAVERT"):
        limitations.append(
            "Personal saving rate was not in the data handoff, so consumer stress uses the available non-savings components listed above."
        )
    if not _has_values(panel, "UMCSENT"):
        limitations.append(
            "Consumer sentiment was not in the data handoff, so consumer stress uses the available non-sentiment components listed above."
        )
    if rate_is_curve_spread:
        limitations.append(
            f"The rate signal uses {rate_signal_label} because a 10-year yield level was not in the data handoff; lower spreads are treated as higher curve-inversion stress."
        )

    execution_summary = {
        "status": "success",
        "analysis_type": "macro_cycle_chart_pack",
        "query": query,
        "latest_snapshot": latest_snapshot,
        "latest_year_changes": change_rows,
        "category_scores": category_scores,
        "current_window": current_window,
        "closest_historical_analog": closest,
        "analog_similarity_ranking": sorted(
            analog_rows, key=lambda row: row["distance_score"]
        ),
        "analog_profiles": analog_profiles,
        "chart_insight_map": {
            "rates_inflation_overlay": "Answers whether disinflation and rate relief changed the policy backdrop in the latest year.",
            "labor_cycle_breadth": "Tests whether labor cooling is visible in both unemployment and payroll momentum.",
            "output_production_momentum": "Checks whether real activity confirms or contradicts the labor and rate signals.",
            "consumer_stress_pressure": "Shows whether consumer pressure is broad or concentrated in savings, sentiment, or financing cost.",
            "latest_year_change_bridge": "Ranks the one-year changes that most changed the committee's starting point.",
            "historical_analog_distance": "Shows which historical episodes are closest and what gaps still separate them.",
            "macro_cycle_profile": "Synthesizes normalized current stress against both last year and the closest analog.",
            "cycle_pressure_flow": "Connects component scores to the final macro-cycle pressure view.",
        },
        "methods_used": [_METHOD, "analog_window_comparison"],
        "statistical_summary": (
            "The deterministic macro-cycle chart pack aligns FRED rates, inflation, "
            "labor, output, consumer-stress, and recession indicators to a monthly "
            f"panel through {_date_label(latest_date)}, compares the current "
            f"24-month profile with named historical windows, and identifies "
            f"{closest} as the closest analog by normalized stress distance."
        ),
        "limitations": limitations,
        "source_series": sorted(str(key) for key in data_files),
    }
    return save_quant_outputs(
        output_dir,
        charts,
        execution_summary,
        statistical_summary_excerpt=execution_summary["statistical_summary"],
    )

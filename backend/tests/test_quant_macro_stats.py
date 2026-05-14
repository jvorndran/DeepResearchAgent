import math
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from agents import quant_macro_stats as qms
from agents.quantitative_developer import tools as quant_tools


def _write_fred_csv(path, dates, values, *, title="Test series"):
    pd.DataFrame(
        {
            "date": dates,
            "value": values,
            "series_id": path.stem,
            "title": title,
        }
    ).to_csv(path, index=False)


def test_build_recession_dashboard_outputs_creates_renderable_chart_pack(tmp_path):
    dates = pd.date_range("1988-01-01", periods=72, freq="MS")
    data_files = {}
    series_values = {
        "T10Y3M": [1.2] * 12 + [-0.4] * 10 + [0.8] * 20 + [-0.2] * 8 + [1.1] * 22,
        "UNRATE": [5.0] * 18 + [5.7, 6.1, 6.5, 6.8] + [6.0] * 20 + [4.0] * 30,
        "INDPRO": list(np.linspace(90, 102, 72)),
        "USREC": [0] * 24 + [1] * 6 + [0] * 42,
        "TOTCI": [1.0] * 20 + [1.4] * 8 + [1.1] * 44,
    }
    for key, values in series_values.items():
        path = tmp_path / f"{key}.csv"
        _write_fred_csv(path, dates, values)
        data_files[key] = str(path)

    handoff = qms.build_recession_dashboard_outputs(
        data_files,
        tmp_path / "out",
        query="Create a recession-dashboard report with charts.",
    )

    assert set(handoff["chart_ids"]) >= {
        "yield_curve_recession_lead",
        "labor_output_confirmation",
        "credit_conditions_trend",
        "spread_unemployment_scatter",
        "recession_signal_stack",
        "current_recession_risk_profile",
        "signal_incidence_treemap",
        "signal_flow_decomposition",
    }
    assert 6 <= len(handoff["chart_ids"]) <= 8
    charts = json.loads((tmp_path / "out" / "charts.json").read_text())
    assert charts["yield_curve_recession_lead"]["referenceAreas"]
    assert {charts[chart_id]["type"] for chart_id in handoff["chart_ids"]} >= {
        "line",
        "composed",
        "area",
        "scatter",
        "radar",
        "treemap",
        "sankey",
    }
    assert "historical_signal_incidence" not in handoff["chart_ids"]
    assert charts["credit_conditions_trend"]["series"][0]["dataKey"] == "TOTCI"
    assert charts["credit_conditions_trend"]["series"][1]["dataKey"] == "credit_6m_change"
    assert charts["spread_unemployment_scatter"]["xKey"] == "yield_spread"
    assert charts["spread_unemployment_scatter"]["yKey"] == "unemployment_rate"
    assert charts["spread_unemployment_scatter"]["sizeKey"] == "recession_size"
    for chart_id in handoff["chart_ids"]:
        chart = charts[chart_id]
        assert chart["data"]
        if chart["type"] in {"line", "bar", "area", "composed"}:
            assert all(row.get(chart["xAxisKey"]) for row in chart["data"])
            for series in chart["series"]:
                assert any(row.get(series["dataKey"]) is not None for row in chart["data"])
    summary = json.loads((tmp_path / "out" / "execution_summary.json").read_text())
    assert summary["latest_snapshot"]["date"] == "1993-12"
    assert summary["credit_proxy"] == "TOTCI"
    assert "deterministic_recession_dashboard_charts" in summary["methods_used"]


def test_recession_dashboard_prefers_consumer_credit_and_latest_finite_components(tmp_path):
    monthly_dates = pd.date_range("2023-01-01", periods=36, freq="MS")
    curve_dates = pd.date_range("2023-01-01", periods=38, freq="MS")
    data_files = {}
    series_values = {
        "UNRATE": [4.0] * 24 + [4.7] * 12,
        "INDPRO": [100.0] * 12 + list(np.linspace(101.0, 95.0, 24)),
        "USREC": [0] * 10 + [1] * 4 + [0] * 22,
        "TOTALSL": [100.0] * 24 + list(np.linspace(99.0, 90.0, 12)),
    }
    for key, values in series_values.items():
        path = tmp_path / f"{key}.csv"
        _write_fred_csv(path, monthly_dates, values)
        data_files[key] = str(path)
    curve_path = tmp_path / "T10Y3M.csv"
    _write_fred_csv(curve_path, curve_dates, [-0.4] * 12 + [0.6] * 26)
    data_files["T10Y3M"] = str(curve_path)
    dollar_path = tmp_path / "DTWEXBGS.csv"
    _write_fred_csv(dollar_path, curve_dates, [100.0] * 38)
    data_files["DTWEXBGS"] = str(dollar_path)

    handoff = qms.build_recession_dashboard_outputs(
        data_files,
        tmp_path / "out",
        query="Create a recession-dashboard report with credit conditions charts.",
    )

    charts = json.loads((tmp_path / "out" / "charts.json").read_text())
    summary = json.loads((tmp_path / "out" / "execution_summary.json").read_text())
    radar = charts["current_recession_risk_profile"]

    assert "current_recession_risk_profile" in handoff["chart_ids"]
    assert summary["credit_proxy"] == "TOTALSL"
    assert charts["credit_conditions_trend"]["series"][0]["dataKey"] == "TOTALSL"
    assert "spread_unemployment_scatter" in handoff["chart_ids"]
    assert summary["latest_snapshot"]["date"] == "2026-02"
    assert summary["latest_snapshot"]["UNRATE"] == 4.7
    assert summary["latest_snapshot"]["UNRATE_as_of"] == "2025-12"
    assert summary["latest_snapshot"]["indpro_yoy"] is not None
    assert any(
        series["dataKey"] == "historical_signal_months_pct"
        for series in radar["series"]
    )
    assert any(row["historical_signal_months_pct"] > 0 for row in radar["data"])
    assert any(row["current_risk"] > 0 for row in radar["data"])


def test_build_recession_dashboard_outputs_supports_gdp_cycle_chart_pack(tmp_path):
    monthly_dates = pd.date_range("2012-01-01", periods=132, freq="MS")
    quarterly_dates = pd.date_range("2012-01-01", periods=44, freq="QS")
    data_files = {}
    monthly_series = {
        "UNRATE": [4.6] * 48 + [5.2, 5.8, 6.4, 6.8, 6.5, 6.1] + [5.2] * 30 + [4.1] * 48,
        "INDPRO": list(np.linspace(96, 110, 60))
        + list(np.linspace(109, 99, 18))
        + list(np.linspace(100, 116, 54)),
        "USREC": [0] * 52 + [1] * 8 + [0] * 72,
    }
    for key, values in monthly_series.items():
        path = tmp_path / f"{key}.csv"
        _write_fred_csv(path, monthly_dates, values)
        data_files[key] = str(path)
    gdp_values = (
        list(np.linspace(100, 114, 18))
        + [112, 109, 107, 108, 110, 112]
        + list(np.linspace(113, 132, 20))
    )
    gdp_path = tmp_path / "GDPC1.csv"
    _write_fred_csv(gdp_path, quarterly_dates, gdp_values)
    data_files["GDPC1"] = str(gdp_path)

    handoff = qms.build_recession_dashboard_outputs(
        data_files,
        tmp_path / "out",
        query="Compare real GDP growth, unemployment, recession periods, and industrial production since 1980. Produce 6-8 governed renderable charts.",
    )

    assert set(handoff["chart_ids"]) == {
        "labor_output_confirmation",
        "recession_signal_stack",
        "current_recession_risk_profile",
        "real_gdp_growth_cycle",
        "growth_unemployment_scatter",
        "historical_signal_incidence",
        "signal_incidence_treemap",
        "signal_flow_decomposition",
    }
    charts = json.loads((tmp_path / "out" / "charts.json").read_text())
    assert {charts[chart_id]["type"] for chart_id in handoff["chart_ids"]} >= {
        "line",
        "composed",
        "area",
        "scatter",
        "radar",
        "radialBar",
        "treemap",
        "sankey",
    }
    assert "yield_curve_recession_lead" not in charts
    assert charts["real_gdp_growth_cycle"]["referenceAreas"]
    assert charts["growth_unemployment_scatter"]["sizeKey"] == "recession_size"
    for chart_id in handoff["chart_ids"]:
        chart = charts[chart_id]
        assert chart["data"]
        if chart["type"] in {"line", "bar", "area", "composed"}:
            assert all(row.get(chart["xAxisKey"]) for row in chart["data"])
            for series in chart["series"]:
                assert any(row.get(series["dataKey"]) is not None for row in chart["data"])

    summary = json.loads((tmp_path / "out" / "execution_summary.json").read_text())
    assert summary["credit_proxy"] is None
    assert summary["latest_snapshot"]["gdpc1_yoy"] is not None
    assert "deterministic_recession_dashboard_charts" in summary["methods_used"]


def test_recession_dashboard_preserves_full_fetched_recession_history(tmp_path):
    monthly_dates = pd.date_range("1980-01-01", "2025-12-01", freq="MS")
    quarterly_dates = pd.date_range("1980-01-01", "2025-10-01", freq="QS")
    recession_windows = [
        ("1980-01-01", "1980-07-01"),
        ("1981-07-01", "1982-11-01"),
        ("1990-07-01", "1991-03-01"),
        ("2001-03-01", "2001-11-01"),
        ("2007-12-01", "2009-06-01"),
        ("2020-02-01", "2020-04-01"),
    ]
    usrec = []
    for date in monthly_dates:
        in_recession = any(
            pd.Timestamp(start) <= date <= pd.Timestamp(end)
            for start, end in recession_windows
        )
        usrec.append(1 if in_recession else 0)

    data_files = {}
    unrate_values = []
    indpro_values = []
    for index, date in enumerate(monthly_dates):
        in_recession = usrec[index] == 1
        unrate_values.append(5.0 + 0.001 * index + (1.2 if in_recession else 0.0))
        indpro_values.append(100.0 + 0.03 * index - (8.0 if in_recession else 0.0))
    monthly_series = {
        "UNRATE": unrate_values,
        "INDPRO": indpro_values,
        "USREC": usrec,
    }
    for key, values in monthly_series.items():
        path = tmp_path / f"{key}.csv"
        _write_fred_csv(path, monthly_dates, values)
        data_files[key] = str(path)
    gdp_path = tmp_path / "GDPC1.csv"
    gdp_values = []
    for index, date in enumerate(quarterly_dates):
        in_recession = any(
            pd.Timestamp(start) <= date <= pd.Timestamp(end)
            for start, end in recession_windows
        )
        gdp_values.append(100.0 + 0.7 * index - (9.0 if in_recession else 0.0))
    _write_fred_csv(
        gdp_path,
        quarterly_dates,
        gdp_values,
    )
    data_files["GDPC1"] = str(gdp_path)

    handoff = qms.build_recession_dashboard_outputs(
        data_files,
        tmp_path / "out",
        query="",
    )

    charts = json.loads((tmp_path / "out" / "charts.json").read_text())
    summary = json.loads((tmp_path / "out" / "execution_summary.json").read_text())
    first_labor_row = charts["labor_output_confirmation"]["data"][0]
    first_band = charts["labor_output_confirmation"]["referenceAreas"][0]

    assert first_labor_row["date"] == "1980-01"
    assert first_band["x1"] == "1980-01"
    assert "historical_signal_incidence" in handoff["chart_ids"]
    assert 6 <= len(handoff["chart_ids"]) <= 8
    assert summary["coverage_start"] == "1980-01"
    assert summary["recession_band_count"] == 6
    assert summary["recession_start_count"] == 6
    assert "Yield curve inversion lead window" not in summary["available_signal_components"]
    assert "credit/risk context" not in summary["statistical_summary"].lower()
    assert handoff["dropped_chart_ids"] == []


def test_recession_dashboard_tool_writes_reproducible_analysis_script(tmp_path, monkeypatch):
    dates = pd.date_range("2006-01-01", periods=36, freq="MS")
    data_files = {}
    for key, values in {
        "T10Y3M": [1.0] * 12 + [-0.5] * 12 + [0.4] * 12,
        "UNRATE": [4.0] * 18 + [4.8] * 18,
        "INDPRO": list(np.linspace(95, 100, 36)),
        "USREC": [0] * 20 + [1] * 4 + [0] * 12,
        "DTWEXBGS": [100] * 18 + [108] * 18,
    }.items():
        path = tmp_path / f"{key}.csv"
        _write_fred_csv(path, dates, values)
        data_files[key] = str(path)

    output_base = tmp_path / "outputs"
    monkeypatch.setattr(quant_tools, "OUTPUT_BASE_DIR", str(output_base))

    result = quant_tools.build_recession_dashboard_artifacts.invoke(
        {
            "job_id": "job-tool-check",
            "data_files": data_files,
            "query": "Create a recession dashboard with charts.",
        }
    )

    handoff = json.loads(result)
    output_dir = output_base / "job-tool-check"
    assert (output_dir / "code" / "analysis.py").exists()
    assert Path(handoff["charts_json"]).exists()
    assert handoff["chart_ids"]


def _cpi_index_from_annual_rates(rates):
    value = 100.0
    values = []
    for annual_rate in rates:
        value *= 1 + (annual_rate / 100.0) / 12.0
        values.append(value)
    return values


def test_build_inflation_policy_chart_pack_outputs_creates_renderable_chart_pack(tmp_path):
    dates = pd.date_range("1990-01-01", periods=204, freq="MS")
    headline_rates = [4.8] * 36 + [2.4] * 72 + [2.0] * 36 + [6.5] * 36 + [3.4] * 24
    core_rates = [4.0] * 36 + [2.2] * 72 + [1.8] * 36 + [5.2] * 36 + [3.1] * 24
    fed_funds = [6.0] * 36 + [4.0] * 48 + [1.0] * 60 + [0.25] * 30 + [5.0] * 30
    usrec = [0] * 72 + [1] * 8 + [0] * 82 + [1] * 6 + [0] * 36
    data_files = {}
    for key, values in {
        "CPIAUCSL": _cpi_index_from_annual_rates(headline_rates),
        "CPILFESL": _cpi_index_from_annual_rates(core_rates),
        "FEDFUNDS": fed_funds,
        "USREC": usrec,
    }.items():
        path = tmp_path / f"{key}.csv"
        _write_fred_csv(path, dates, values)
        data_files[key] = str(path)

    handoff = qms.build_inflation_policy_chart_pack_outputs(
        data_files,
        tmp_path / "out",
        query="Build a chart-heavy CPI/core CPI/Fed funds report.",
    )

    expected_chart_ids = {
        "inflation_policy_overlay",
        "real_policy_gap_cycle",
        "policy_lag_scatter",
        "regime_policy_profile",
        "current_policy_component_scores",
        "policy_lag_regime_contribution",
        "policy_lag_filter_funnel",
        "policy_lag_signal_flow",
    }
    assert set(handoff["chart_ids"]) == expected_chart_ids
    charts = json.loads((tmp_path / "out" / "charts.json").read_text())
    assert {charts[chart_id]["type"] for chart_id in handoff["chart_ids"]} >= {
        "composed",
        "area",
        "scatter",
        "radar",
        "radialBar",
        "treemap",
        "funnel",
        "sankey",
    }
    assert charts["inflation_policy_overlay"]["referenceAreas"]
    assert charts["policy_lag_scatter"]["sizeKey"] == "policy_gap_abs"
    for chart_id in handoff["chart_ids"]:
        chart = charts[chart_id]
        assert chart["data"]
        if chart["type"] in {"line", "bar", "area", "composed"}:
            assert all(row.get(chart["xAxisKey"]) for row in chart["data"])
            for series in chart["series"]:
                assert any(row.get(series["dataKey"]) is not None for row in chart["data"])

    summary = json.loads((tmp_path / "out" / "execution_summary.json").read_text())
    assert summary["policy_lag_summary"]["policy_lag_months"] > 0
    assert summary["cpi_transforms"] == {
        "headline_cpi_yoy": "index_pct_change_12m",
        "core_cpi_yoy": "index_pct_change_12m",
    }
    assert "deterministic_inflation_policy_chart_pack" in summary["methods_used"]


def test_build_inflation_policy_chart_pack_outputs_accepts_pretransformed_cpi_rates(
    tmp_path,
):
    dates = pd.date_range("1990-01-01", periods=48, freq="MS")
    data_files = {}
    for key, values in {
        "CPIAUCSL": [5.0] * 12 + [6.2] * 12 + [3.8] * 12 + [2.7] * 12,
        "CPILFESL": [4.3] * 12 + [4.8] * 12 + [3.5] * 12 + [2.9] * 12,
        "FEDFUNDS": [4.0] * 24 + [5.25] * 24,
        "USREC": [0] * 6 + [1] * 6 + [0] * 36,
    }.items():
        path = tmp_path / f"{key}.csv"
        _write_fred_csv(path, dates, values)
        data_files[key] = str(path)

    qms.build_inflation_policy_chart_pack_outputs(
        data_files,
        tmp_path / "out",
        query="Build a chart-heavy CPI/core CPI/Fed funds report.",
    )

    charts = json.loads((tmp_path / "out" / "charts.json").read_text())
    overlay_rows = charts["inflation_policy_overlay"]["data"]
    gap_rows = charts["real_policy_gap_cycle"]["data"]
    assert overlay_rows[0]["date"] == "1990-01"
    assert overlay_rows[0]["headline_cpi_yoy"] == 5.0
    assert overlay_rows[-1]["headline_cpi_yoy"] == 2.7
    assert gap_rows[0]["headline_policy_gap"] == -1.0
    assert max(abs(row["headline_cpi_yoy"]) for row in overlay_rows) < 10

    summary = json.loads((tmp_path / "out" / "execution_summary.json").read_text())
    assert summary["latest_snapshot"]["headline_cpi_yoy"] == 2.7
    assert summary["latest_snapshot"]["core_cpi_yoy"] == 2.9
    assert summary["cpi_transforms"] == {
        "headline_cpi_yoy": "as_reported_percent_change",
        "core_cpi_yoy": "as_reported_percent_change",
    }


def test_inflation_policy_chart_pack_tool_writes_reproducible_analysis_script(
    tmp_path, monkeypatch
):
    dates = pd.date_range("2020-01-01", periods=48, freq="MS")
    data_files = {}
    for key, values in {
        "CPIAUCSL": _cpi_index_from_annual_rates([6.0] * 48),
        "CPILFESL": _cpi_index_from_annual_rates([5.0] * 48),
        "FEDFUNDS": [0.25] * 24 + [5.0] * 24,
        "USREC": [0] * 18 + [1] * 3 + [0] * 27,
    }.items():
        path = tmp_path / f"{key}.csv"
        _write_fred_csv(path, dates, values)
        data_files[key] = str(path)

    output_base = tmp_path / "outputs"
    monkeypatch.setattr(quant_tools, "OUTPUT_BASE_DIR", str(output_base))

    result = quant_tools.build_inflation_policy_chart_pack_artifacts.invoke(
        {
            "job_id": "job-inflation-tool-check",
            "data_files": data_files,
            "query": "Create a chart-heavy CPI policy report.",
        }
    )

    handoff = json.loads(result)
    output_dir = output_base / "job-inflation-tool-check"
    assert (output_dir / "code" / "analysis.py").exists()
    assert Path(handoff["charts_json"]).exists()
    assert len(handoff["chart_ids"]) >= 6


def test_build_consumer_stress_dashboard_outputs_creates_renderable_chart_pack(tmp_path):
    dates = pd.date_range("2018-01-01", periods=96, freq="MS")
    cpi = _cpi_index_from_annual_rates([2.0] * 24 + [6.5] * 24 + [4.0] * 24 + [2.8] * 24)
    core_pce = _cpi_index_from_annual_rates([1.8] * 24 + [5.0] * 24 + [3.5] * 24 + [2.7] * 24)
    unrate = [3.8] * 24 + [13.0, 14.5, 11.0, 8.0] + [6.0] * 20 + [3.6] * 24 + [4.2] * 24
    u6rate = [value + 3.2 for value in unrate]
    data_files = {}
    for key, values in {
        "PSAVERT": [7.5] * 24 + [32.0, 24.0, 18.0, 14.0] + [8.0] * 20 + [4.2] * 48,
        "UNRATE": unrate,
        "U6RATE": u6rate,
        "CPIAUCSL": cpi,
        "PCEPILFE": core_pce,
        "AHETPI": list(np.linspace(24.0, 32.0, 96)),
        "UMCSENT": [98.0] * 24 + [75.0] * 12 + [55.0] * 24 + [68.0] * 36,
        "DPCERA3M086SBEA": list(np.linspace(100.0, 121.0, 96)),
        "PCE": list(np.linspace(15000.0, 21000.0, 96)),
        "TOTALSL": list(np.linspace(3900.0, 5200.0, 96)),
        "DTCOLNVHFNM": list(np.linspace(90000.0, 132000.0, 96)),
        "DRALACBN": [2.1] * 24 + [1.5] * 24 + [2.0] * 24 + [2.8] * 24,
        "USREC": [0] * 27 + [1] * 4 + [0] * 65,
    }.items():
        path = tmp_path / f"{key}.csv"
        _write_fred_csv(path, dates, values)
        data_files[key] = str(path)

    handoff = qms.build_consumer_stress_dashboard_outputs(
        data_files,
        tmp_path / "out",
        query="Analyze consumer stress with a 6-8 chart dashboard.",
    )

    expected_chart_ids = {
        "consumer_stress_overlay",
        "savings_vs_sentiment",
        "unemployment_depth",
        "consumer_profile_radar",
        "consumption_savings_tradeoff",
        "credit_stress",
        "auto_loan_stress",
        "consumption_sentiment_contributions",
    }
    assert set(handoff["chart_ids"]) == expected_chart_ids
    charts = json.loads((tmp_path / "out" / "charts.json").read_text())
    assert {charts[chart_id]["type"] for chart_id in handoff["chart_ids"]} >= {
        "composed",
        "scatter",
        "area",
        "radar",
        "line",
        "radialBar",
        "treemap",
    }
    assert charts["consumer_stress_overlay"]["referenceAreas"]
    assert charts["savings_vs_sentiment"]["sizeKey"] == "inflation_size"
    for chart_id in handoff["chart_ids"]:
        chart = charts[chart_id]
        assert chart["data"]
        if chart["type"] in {"line", "bar", "area", "composed"}:
            assert all(row.get(chart["xAxisKey"]) for row in chart["data"])
            for series in chart["series"]:
                assert any(row.get(series["dataKey"]) is not None for row in chart["data"])
    summary = json.loads((tmp_path / "out" / "execution_summary.json").read_text())
    assert summary["analysis_type"] == "consumer_stress_dashboard"
    assert summary["credit_proxy"] == "DRALACBN"
    assert "deterministic_consumer_stress_dashboard" in summary["methods_used"]


def test_consumer_stress_dashboard_accepts_income_and_credit_substitutes(tmp_path):
    dates = pd.date_range("2018-01-01", periods=96, freq="MS")
    data_files = {}
    for key, values in {
        "PSAVERT": [7.0] * 24 + [18.0] * 6 + [5.0] * 66,
        "UNRATE": [3.8] * 24 + [12.0, 14.0, 10.0, 8.0] + [5.5] * 20 + [4.0] * 48,
        "CPIAUCSL": _cpi_index_from_annual_rates([2.0] * 24 + [7.0] * 24 + [4.0] * 24 + [3.0] * 24),
        "DSPIC96": list(np.linspace(15000.0, 17400.0, 96)),
        "CES0500000003": list(np.linspace(27.0, 35.0, 96)),
        "UMCSENT": [98.0] * 24 + [70.0] * 24 + [55.0] * 24 + [67.0] * 24,
        "PCEC96": list(np.linspace(13000.0, 15400.0, 96)),
        "DRCCLACBS": [2.4] * 24 + [1.6] * 24 + [2.2] * 24 + [3.1] * 24,
        "USREC": [0] * 27 + [1] * 4 + [0] * 65,
    }.items():
        path = tmp_path / f"{key}.csv"
        _write_fred_csv(path, dates, values)
        data_files[key] = str(path)

    handoff = qms.build_consumer_stress_dashboard_outputs(
        data_files,
        tmp_path / "out",
        query="Analyze whether the US consumer is under stress with a 6-8 chart dashboard.",
    )

    assert len(handoff["chart_ids"]) == 8
    charts = json.loads((tmp_path / "out" / "charts.json").read_text())
    assert charts["credit_stress"]["data"]
    assert any(
        row.get("credit_stress_score") is not None for row in charts["credit_stress"]["data"]
    )
    summary = json.loads((tmp_path / "out" / "execution_summary.json").read_text())
    assert summary["income_or_wage_proxy"] == "DSPIC96"
    assert summary["consumption_proxy"] == "PCEC96"
    assert summary["credit_proxy"] == "DRCCLACBS"
    assert summary["latest_snapshot"]["total_credit_yoy"] is None
    assert summary["latest_snapshot"]["delinquency_rate"] == 3.1


def test_consumer_stress_dashboard_accepts_missing_consumption_when_sentiment_exists(
    tmp_path,
):
    dates = pd.date_range("2018-01-01", periods=96, freq="MS")
    data_files = {}
    for key, values in {
        "PSAVERT": [7.0] * 24 + [18.0] * 6 + [5.0] * 66,
        "UNRATE": [3.8] * 24 + [12.0, 14.0, 10.0, 8.0] + [5.5] * 20 + [4.0] * 48,
        "CPIAUCSL": _cpi_index_from_annual_rates([2.0] * 24 + [7.0] * 24 + [4.0] * 24 + [3.0] * 24),
        "PCEPILFE": _cpi_index_from_annual_rates([1.8] * 24 + [5.0] * 24 + [3.4] * 24 + [2.7] * 24),
        "DSPIC96": list(np.linspace(15000.0, 17400.0, 96)),
        "UMCSENT": [98.0] * 24 + [70.0] * 24 + [55.0] * 24 + [67.0] * 24,
        "TOTALSL": list(np.linspace(3900.0, 5200.0, 96)),
        "USREC": [0] * 27 + [1] * 4 + [0] * 65,
    }.items():
        path = tmp_path / f"{key}.csv"
        _write_fred_csv(path, dates, values)
        data_files[key] = str(path)

    handoff = qms.build_consumer_stress_dashboard_outputs(
        data_files,
        tmp_path / "out",
        query="Analyze consumer stress with sentiment but no real consumption file.",
    )

    assert len(handoff["chart_ids"]) == 8
    assert "income_savings_tradeoff" in handoff["chart_ids"]
    assert "consumption_savings_tradeoff" not in handoff["chart_ids"]
    charts = json.loads((tmp_path / "out" / "charts.json").read_text())
    assert charts["income_savings_tradeoff"]["data"]
    assert {series["dataKey"] for series in charts["income_savings_tradeoff"]["series"]} == {
        "savings_stress",
        "income_stress",
    }
    summary = json.loads((tmp_path / "out" / "execution_summary.json").read_text())
    assert summary["consumption_proxy"] is None
    assert summary["latest_snapshot"]["real_pce_yoy"] is None
    assert any("No real consumption series" in item for item in summary["limitations"])


def test_consumer_stress_dashboard_tool_writes_reproducible_analysis_script(tmp_path, monkeypatch):
    dates = pd.date_range("2019-01-01", periods=60, freq="MS")
    data_files = {}
    for key, values in {
        "PSAVERT": [7.0] * 12 + [20.0] * 6 + [5.0] * 42,
        "UNRATE": [3.7] * 18 + [8.0] * 6 + [4.0] * 36,
        "CPIAUCSL": _cpi_index_from_annual_rates([2.0] * 18 + [6.0] * 24 + [3.0] * 18),
        "AHETPI": list(np.linspace(25.0, 31.0, 60)),
        "UMCSENT": [95.0] * 18 + [60.0] * 24 + [70.0] * 18,
        "DPCERA3M086SBEA": list(np.linspace(100.0, 112.0, 60)),
        "TOTALSL": list(np.linspace(4000.0, 4700.0, 60)),
    }.items():
        path = tmp_path / f"{key}.csv"
        _write_fred_csv(path, dates, values)
        data_files[key] = str(path)

    output_base = tmp_path / "outputs"
    monkeypatch.setattr(quant_tools, "OUTPUT_BASE_DIR", str(output_base))

    result = quant_tools.build_consumer_stress_dashboard_artifacts.invoke(
        {
            "job_id": "job-consumer-tool-check",
            "data_files": data_files,
            "query": "Create a consumer stress dashboard with charts.",
        }
    )

    handoff = json.loads(result)
    output_dir = output_base / "job-consumer-tool-check"
    assert (output_dir / "code" / "analysis.py").exists()
    assert Path(handoff["charts_json"]).exists()
    assert len(handoff["chart_ids"]) == 8


def test_build_historical_replay_chart_pack_outputs_creates_renderable_pack(tmp_path):
    dates = pd.date_range("1999-01-01", "2025-12-01", freq="MS")

    def values(default, *spans):
        result = []
        for date in dates:
            value = default
            for start, end, span_value in spans:
                if pd.Timestamp(start) <= date <= pd.Timestamp(end):
                    value = span_value(date) if callable(span_value) else span_value
            result.append(value)
        return result

    cpi_rates = values(
        2.3,
        ("2000-07-01", "2002-12-01", 2.8),
        ("2007-07-01", "2009-12-01", 1.8),
        ("2019-08-01", "2021-12-01", 4.8),
        ("2021-01-01", "2023-12-01", 6.2),
        ("2023-07-01", "2025-12-01", 3.1),
    )
    data_files = {}
    for key, series_values in {
        "UNRATE": values(
            4.2,
            ("2000-07-01", "2002-12-01", 5.6),
            ("2007-07-01", "2009-12-01", 7.8),
            ("2019-08-01", "2021-12-01", 8.5),
            ("2023-07-01", "2025-12-01", 4.1),
        ),
        "CPIAUCSL": _cpi_index_from_annual_rates(cpi_rates),
        "FEDFUNDS": values(
            3.5,
            ("2000-07-01", "2002-12-01", 3.0),
            ("2007-07-01", "2009-12-01", 1.7),
            ("2019-08-01", "2021-12-01", 0.5),
            ("2021-01-01", "2023-12-01", 3.6),
            ("2023-07-01", "2025-12-01", 5.1),
        ),
        "INDPRO": values(
            100.0,
            ("2000-07-01", "2002-12-01", lambda date: 100.0 - (date.year - 2000) * 1.0),
            ("2007-07-01", "2009-12-01", lambda date: 105.0 - (date.year - 2007) * 2.5),
            ("2019-08-01", "2021-12-01", lambda date: 108.0 - (date.year - 2019) * 3.0),
            ("2023-07-01", "2025-12-01", lambda date: 111.0 + (date.year - 2023) * 0.6),
        ),
        "USREC": values(
            0,
            ("2001-03-01", "2001-11-01", 1),
            ("2007-12-01", "2009-06-01", 1),
            ("2020-02-01", "2020-04-01", 1),
        ),
        "ICSA": values(
            230000,
            ("2007-07-01", "2009-12-01", 430000),
            ("2019-08-01", "2021-12-01", 650000),
            ("2023-07-01", "2025-12-01", 220000),
        ),
        "DSPIC96": list(np.linspace(10000.0, 13200.0, len(dates))),
        "PCE": list(np.linspace(7000.0, 18000.0, len(dates))),
    }.items():
        path = tmp_path / f"{key}.csv"
        _write_fred_csv(path, dates, series_values)
        data_files[key] = str(path)

    handoff = qms.build_historical_replay_chart_pack_outputs(
        data_files,
        tmp_path / "out",
        query="Make a historical replay report with 6-8 charts.",
    )

    expected_chart_ids = {
        "labor_replay_paths",
        "inflation_policy_replay",
        "production_consumer_replay",
        "analog_distance_bubble",
        "normalized_window_profiles",
        "current_signal_scores",
        "replay_difference_contributions",
    }
    assert set(handoff["chart_ids"]) == expected_chart_ids
    charts = json.loads((tmp_path / "out" / "charts.json").read_text())
    assert {charts[chart_id]["type"] for chart_id in handoff["chart_ids"]} >= {
        "line",
        "composed",
        "scatter",
        "radar",
        "radialBar",
        "treemap",
    }
    for chart_id in handoff["chart_ids"]:
        chart = charts[chart_id]
        assert chart["data"]
        if chart["type"] in {"line", "bar", "area", "composed"}:
            assert all(row.get(chart["xAxisKey"]) is not None for row in chart["data"])
            for series in chart["series"]:
                assert any(row.get(series["dataKey"]) is not None for row in chart["data"])
    summary = json.loads((tmp_path / "out" / "execution_summary.json").read_text())
    assert summary["analysis_type"] == "historical_replay_chart_pack"
    assert summary["top_analog"]
    assert len(summary["historical_simulations"]) == 4
    assert "deterministic_historical_replay_chart_pack" in summary["methods_used"]


def test_historical_replay_chart_pack_tool_writes_reproducible_analysis_script(
    tmp_path, monkeypatch
):
    dates = pd.date_range("1999-01-01", "2025-12-01", freq="MS")
    data_files = {}
    for key, series_values in {
        "UNRATE": [4.0] * len(dates),
        "CPIAUCSL": _cpi_index_from_annual_rates([2.5] * len(dates)),
        "FEDFUNDS": [3.0] * len(dates),
        "INDPRO": list(np.linspace(90.0, 115.0, len(dates))),
        "USREC": [0] * len(dates),
        "DSPIC96": list(np.linspace(10000.0, 13000.0, len(dates))),
    }.items():
        path = tmp_path / f"{key}.csv"
        _write_fred_csv(path, dates, series_values)
        data_files[key] = str(path)

    output_base = tmp_path / "outputs"
    monkeypatch.setattr(quant_tools, "OUTPUT_BASE_DIR", str(output_base))

    result = quant_tools.build_historical_replay_chart_pack_artifacts.invoke(
        {
            "job_id": "job-historical-replay-tool-check",
            "data_files": data_files,
            "query": "Create a chart-heavy historical replay report.",
        }
    )

    handoff = json.loads(result)
    output_dir = output_base / "job-historical-replay-tool-check"
    assert (output_dir / "code" / "analysis.py").exists()
    assert Path(handoff["charts_json"]).exists()
    assert 6 <= len(handoff["chart_ids"]) <= 8


def test_historical_replay_chart_pack_accepts_quarterly_real_consumption_substitute(
    tmp_path,
):
    dates = pd.date_range("1999-01-01", "2025-12-01", freq="MS")
    data_files = {}
    for key, series_values in {
        "UNRATE": [4.0] * len(dates),
        "CPIAUCSL": _cpi_index_from_annual_rates([2.5] * len(dates)),
        "FEDFUNDS": [3.0] * len(dates),
        "INDPRO": list(np.linspace(90.0, 115.0, len(dates))),
        "USREC": [0] * len(dates),
        "DPCERA3Q086SBEA": list(np.linspace(100.0, 160.0, len(dates))),
    }.items():
        path = tmp_path / f"{key}.csv"
        _write_fred_csv(path, dates, series_values)
        data_files[key] = str(path)

    handoff = qms.build_historical_replay_chart_pack_outputs(
        data_files,
        tmp_path / "out",
        query="Make a historical replay report with consumer stress charts.",
    )

    summary = json.loads((tmp_path / "out" / "execution_summary.json").read_text())
    assert 6 <= len(handoff["chart_ids"]) <= 8
    assert summary["latest_snapshot"]["consumer_yoy"] > 0


def test_build_unemployment_forecast_chart_pack_outputs_creates_renderable_pack(tmp_path):
    dates = pd.date_range("2000-01-01", periods=180, freq="MS")
    cycle = np.sin(np.linspace(0, 8 * np.pi, len(dates)))
    unrate = 5.2 + 0.7 * cycle + np.linspace(0.0, -0.4, len(dates))
    claims = 260000 + 45000 * cycle + np.linspace(0, 12000, len(dates))
    payrolls = 130000 + np.cumsum(80 - 18 * cycle)
    cpi = _cpi_index_from_annual_rates(2.4 + 0.8 * cycle)
    gdpc1 = 15000 + np.cumsum(12 - 2 * cycle)
    data_files = {}
    for key, series_values in {
        "UNRATE_FRED": unrate,
        "PAYEMS_FRED": payrolls,
        "ICSA_FRED": claims,
        "CPIAUCSL_FRED": cpi,
        "GDPC1_FRED": gdpc1,
    }.items():
        path = tmp_path / f"{key}.csv"
        _write_fred_csv(path, dates, series_values)
        data_files[key] = str(path)

    handoff = qms.build_unemployment_forecast_chart_pack_outputs(
        data_files,
        tmp_path / "out",
        query="Build an unemployment forecast-overlay report with 6-8 charts.",
    )

    expected_chart_ids = {
        "unemployment_forecast_band",
        "actual_vs_fitted_backtest",
        "backtest_error_by_horizon",
        "fitted_vs_actual_scatter",
        "predictor_contribution_radar",
        "current_signal_scores",
        "uncertainty_signal_flow",
        "forecast_uncertainty_hierarchy",
    }
    assert set(handoff["chart_ids"]) == expected_chart_ids
    charts = json.loads((tmp_path / "out" / "charts.json").read_text())
    assert {charts[chart_id]["type"] for chart_id in handoff["chart_ids"]} >= {
        "composed",
        "line",
        "bar",
        "scatter",
        "radar",
        "radialBar",
        "sankey",
        "sunburst",
    }
    assert charts["unemployment_forecast_band"]["referenceLines"]
    assert charts["fitted_vs_actual_scatter"]["sizeKey"] == "abs_error"
    for chart_id in handoff["chart_ids"]:
        chart = charts[chart_id]
        assert chart["data"]
        if chart["type"] in {"line", "bar", "area", "composed"}:
            assert all(row.get(chart["xAxisKey"]) for row in chart["data"])
            for series in chart["series"]:
                assert any(row.get(series["dataKey"]) is not None for row in chart["data"])
    summary = json.loads((tmp_path / "out" / "execution_summary.json").read_text())
    assert summary["analysis_type"] == "unemployment_forecast_chart_pack"
    assert summary["forecast_result"]["forecast_table"]
    assert summary["backtest_summary"]["six_month"]["status"] == "ok"
    assert "deterministic_unemployment_forecast_chart_pack" in summary["methods_used"]


def test_unemployment_forecast_chart_pack_uses_alternate_predictors_without_claims(
    tmp_path,
):
    dates = pd.date_range("2005-01-01", periods=210, freq="MS")
    cycle = np.sin(np.linspace(0, 7 * np.pi, len(dates)))
    data_files = {}
    for key, series_values in {
        "UNRATE_FRED": 5.0 + 0.6 * cycle,
        "PAYEMS_FRED": 132000 + np.cumsum(70 - 16 * cycle),
        "U6RATE_FRED": 8.5 + 1.0 * cycle,
        "DGS10_FRED": 3.2 + 0.8 * cycle,
        "FEDFUNDS_FRED": 2.1 + 0.9 * np.roll(cycle, 3),
        "NROU_FRED": 4.7 + 0.1 * np.cos(np.linspace(0, 2 * np.pi, len(dates))),
    }.items():
        path = tmp_path / f"{key}.csv"
        _write_fred_csv(path, dates, series_values)
        data_files[key] = str(path)

    handoff = qms.build_unemployment_forecast_chart_pack_outputs(
        data_files,
        tmp_path / "out",
        query="Build an unemployment forecast-overlay report with 6-8 charts.",
    )

    assert len(handoff["chart_ids"]) == 8
    charts = json.loads((tmp_path / "out" / "charts.json").read_text())
    radar_rows = charts["predictor_contribution_radar"]["data"]
    assert {row["metric"] for row in radar_rows} >= {
        "U-6 underemployment",
        "Rate-spread pressure",
        "Natural-rate gap",
    }
    assert all(row["model_importance"] > 0 for row in radar_rows)
    summary = json.loads((tmp_path / "out" / "execution_summary.json").read_text())
    assert summary["latest_snapshot"]["initial_claims"] is None
    assert summary["forecast_result"]["forecast_table"]
    assert "deterministic_unemployment_forecast_chart_pack" in summary["methods_used"]


def test_unemployment_forecast_chart_pack_tool_writes_reproducible_analysis_script(
    tmp_path, monkeypatch
):
    dates = pd.date_range("2010-01-01", periods=132, freq="MS")
    cycle = np.cos(np.linspace(0, 6 * np.pi, len(dates)))
    data_files = {}
    for key, values in {
        "UNRATE_FRED": 4.8 + 0.5 * cycle,
        "PAYEMS_FRED": 135000 + np.cumsum(90 - 12 * cycle),
        "ICSA_FRED": 240000 + 35000 * cycle,
        "CPIAUCSL_FRED": _cpi_index_from_annual_rates(2.3 + 0.5 * cycle),
        "GDPC1_FRED": 16000 + np.cumsum(10 - cycle),
    }.items():
        path = tmp_path / f"{key}.csv"
        _write_fred_csv(path, dates, values)
        data_files[key] = str(path)

    output_base = tmp_path / "outputs"
    monkeypatch.setattr(quant_tools, "OUTPUT_BASE_DIR", str(output_base))

    result = quant_tools.build_unemployment_forecast_chart_pack_artifacts.invoke(
        {
            "job_id": "job-unemployment-forecast-tool-check",
            "data_files": data_files,
            "query": "Create a chart-heavy unemployment forecast report.",
        }
    )

    handoff = json.loads(result)
    output_dir = output_base / "job-unemployment-forecast-tool-check"
    assert (output_dir / "code" / "analysis.py").exists()
    assert Path(handoff["charts_json"]).exists()
    assert len(handoff["chart_ids"]) == 8


def _macro_cycle_fixture(tmp_path):
    dates = pd.date_range("1998-01-01", periods=336, freq="MS")
    qdates = pd.date_range("1998-01-01", periods=112, freq="QS")
    cycle = np.sin(np.linspace(0, 10 * np.pi, len(dates)))
    qcycle = np.sin(np.linspace(0, 10 * np.pi, len(qdates)))
    recession = [
        1
        if (
            pd.Timestamp("2001-03-01") <= date <= pd.Timestamp("2001-11-01")
            or pd.Timestamp("2008-01-01") <= date <= pd.Timestamp("2009-06-01")
            or pd.Timestamp("2020-03-01") <= date <= pd.Timestamp("2020-05-01")
        )
        else 0
        for date in dates
    ]
    monthly = {
        "FEDFUNDS": 2.8 + 1.6 * cycle + np.linspace(0.0, 0.7, len(dates)),
        "CPIAUCSL": _cpi_index_from_annual_rates(2.5 + 1.1 * cycle),
        "PCEPILFE": _cpi_index_from_annual_rates(2.2 + 0.7 * cycle),
        "DGS10": 3.7 + 0.9 * cycle,
        "T10Y2Y": 0.7 - 1.2 * cycle,
        "UNRATE": 5.2 + 1.0 * cycle,
        "PAYEMS": 125000 + np.cumsum(95 - 18 * cycle),
        "INDPRO": 88 + np.cumsum(0.08 - 0.03 * cycle),
        "PSAVERT": 7.2 - 1.4 * cycle,
        "UMCSENT": 82 - 13 * cycle,
        "USREC": recession,
        "T10YIE": 2.1 + 0.35 * cycle,
        "CIVPART": 62.5 + 0.4 * np.cos(np.linspace(0, 5 * np.pi, len(dates))),
        "TCU": 76 + 3.5 * cycle,
        "MORTGAGE30US": 5.0 + 1.2 * cycle,
        "CSUSHPISA": 140 + np.cumsum(0.45 + 0.08 * cycle),
        "STLFSI": -0.2 + 0.6 * cycle,
    }
    data_files = {}
    for key, values in monthly.items():
        path = tmp_path / f"{key}.csv"
        _write_fred_csv(path, dates, values)
        data_files[key] = str(path)
    gdp_path = tmp_path / "GDPC1.csv"
    _write_fred_csv(gdp_path, qdates, 14500 + np.cumsum(45 - 9 * qcycle))
    data_files["GDPC1"] = str(gdp_path)
    return data_files


def test_build_macro_cycle_chart_pack_outputs_creates_renderable_pack(tmp_path):
    data_files = _macro_cycle_fixture(tmp_path)

    handoff = qms.build_macro_cycle_chart_pack_outputs(
        data_files,
        tmp_path / "out",
        query="Create a macro cycle chart pack for an investment committee with 6-8 governed charts.",
    )

    expected_chart_ids = {
        "rates_inflation_overlay",
        "labor_cycle_breadth",
        "output_production_momentum",
        "consumer_stress_pressure",
        "latest_year_change_bridge",
        "historical_analog_distance",
        "macro_cycle_profile",
        "cycle_pressure_flow",
    }
    assert set(handoff["chart_ids"]) == expected_chart_ids
    charts = json.loads((tmp_path / "out" / "charts.json").read_text())
    assert {charts[chart_id]["type"] for chart_id in handoff["chart_ids"]} >= {
        "composed",
        "area",
        "bar",
        "scatter",
        "radar",
        "sankey",
    }
    rates_chart = charts["rates_inflation_overlay"]
    rate_series = {series["dataKey"] for series in rates_chart["series"]}
    assert {"FEDFUNDS", "DGS10", "CURVE_SPREAD", "cpi_yoy", "core_inflation_yoy"} <= rate_series
    assert any(series["label"] == "10Y-2Y yield spread" for series in rates_chart["series"])
    assert rates_chart["referenceAreas"]
    assert charts["historical_analog_distance"]["sizeKey"] == "distance_score"
    for chart_id in handoff["chart_ids"]:
        chart = charts[chart_id]
        if chart["type"] == "sankey":
            assert chart["data"]["nodes"]
            assert chart["data"]["links"]
            assert all(link["value"] > 0 for link in chart["data"]["links"])
            continue
        assert chart["data"]
        if chart["type"] in {"line", "bar", "area", "composed"}:
            assert all(row.get(chart["xAxisKey"]) for row in chart["data"])
            for series in chart["series"]:
                assert any(row.get(series["dataKey"]) is not None for row in chart["data"])

    summary = json.loads((tmp_path / "out" / "execution_summary.json").read_text())
    assert summary["analysis_type"] == "macro_cycle_chart_pack"
    assert summary["latest_year_changes"]
    assert summary["latest_snapshot"]["curve_spread_label"] == "10Y-2Y yield spread"
    assert summary["latest_snapshot"]["curve_spread"] is not None
    assert summary["latest_snapshot"]["core_inflation_yoy"] is not None
    assert summary["closest_historical_analog"]
    assert "deterministic_macro_cycle_chart_pack" in summary["methods_used"]


def test_build_macro_cycle_chart_pack_outputs_allows_missing_saving_rate(tmp_path):
    data_files = _macro_cycle_fixture(tmp_path)
    data_files.pop("PSAVERT")

    handoff = qms.build_macro_cycle_chart_pack_outputs(
        data_files,
        tmp_path / "out",
        query=(
            "Test whether current macro conditions look like a soft landing, "
            "delayed recession, or reacceleration with 6-8 governed charts."
        ),
    )

    assert len(handoff["chart_ids"]) == 8
    charts = json.loads((tmp_path / "out" / "charts.json").read_text())
    consumer_chart = charts["consumer_stress_pressure"]
    consumer_keys = {series["dataKey"] for series in consumer_chart["series"]}
    assert "consumer_stress" in consumer_keys
    assert "saving_stress" not in consumer_keys
    assert consumer_chart["data"]

    summary = json.loads((tmp_path / "out" / "execution_summary.json").read_text())
    assert any("Personal saving rate" in item for item in summary["limitations"])


def test_build_macro_cycle_chart_pack_outputs_accepts_curve_and_savings_proxies(tmp_path):
    data_files = _macro_cycle_fixture(tmp_path)
    data_files["T10Y2Y"] = data_files.pop("DGS10")
    data_files.pop("UMCSENT")

    handoff = qms.build_macro_cycle_chart_pack_outputs(
        data_files,
        tmp_path / "out",
        query=(
            "Create a macro cycle chart pack for an investment committee "
            "covering rates, inflation, labor, output, consumer stress, "
            "historical analogs, and synthesis."
        ),
    )

    assert len(handoff["chart_ids"]) == 8
    charts = json.loads((tmp_path / "out" / "charts.json").read_text())
    rates_chart = charts["rates_inflation_overlay"]
    assert any(
        series["label"] == "10Y-2Y yield spread"
        for series in rates_chart["series"]
    )
    consumer_chart = charts["consumer_stress_pressure"]
    consumer_keys = {series["dataKey"] for series in consumer_chart["series"]}
    assert {"consumer_stress", "saving_stress", "financing_stress"} <= consumer_keys
    assert "sentiment_stress" not in consumer_keys

    summary = json.loads((tmp_path / "out" / "execution_summary.json").read_text())
    assert summary["analysis_type"] == "macro_cycle_chart_pack"
    assert summary["latest_snapshot"]["rate_signal_label"] == "10Y-2Y yield spread"
    assert any("yield spread" in item for item in summary["limitations"])
    assert any("Consumer sentiment" in item for item in summary["limitations"])


def test_macro_cycle_chart_pack_tool_writes_reproducible_analysis_script(tmp_path, monkeypatch):
    data_files = _macro_cycle_fixture(tmp_path)
    output_base = tmp_path / "outputs"
    monkeypatch.setattr(quant_tools, "OUTPUT_BASE_DIR", str(output_base))

    result = quant_tools.build_macro_cycle_chart_pack_artifacts.invoke(
        {
            "job_id": "job-macro-cycle-tool-check",
            "data_files": data_files,
            "query": "Create a macro cycle chart pack for an investment committee.",
        }
    )

    handoff = json.loads(result)
    output_dir = output_base / "job-macro-cycle-tool-check"
    assert (output_dir / "code" / "analysis.py").exists()
    assert Path(handoff["charts_json"]).exists()
    assert len(handoff["chart_ids"]) == 8


def test_known_input_rolling_correlation():
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2020-01-31", periods=5, freq="ME"),
            "spread": [1, 2, 3, 4, 5],
            "unemployment": [2, 4, 6, 8, 10],
        }
    )

    result = qms.rolling_correlation(frame, "spread", "unemployment", window=3)

    assert result["method"].dropna().unique().tolist() == [qms.METHOD_ROLLING_CORRELATION]
    assert result["correlation"].iloc[:2].isna().all()
    assert result["correlation"].iloc[2:].round(10).tolist() == [1.0, 1.0, 1.0]
    assert result["observations"].tolist() == [0, 0, 3, 3, 3]


def test_rolling_correlation_missing_data_does_not_impute_pairs():
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2020-01-31", periods=5, freq="ME"),
            "spread": [1, 2, None, 4, 5],
            "industrial_production": [10, 20, 30, 40, 50],
        }
    )

    result = qms.rolling_correlation(
        frame,
        "spread",
        "industrial_production",
        window=3,
        min_periods=2,
    )

    assert result["observations"].tolist() == [0, 0, 2, 2, 2]
    assert math.isnan(result["correlation"].iloc[0])
    assert result["correlation"].iloc[2:].round(10).tolist() == [1.0, 1.0, 1.0]


def test_lead_lag_selects_known_predictor_lead():
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2021-01-31", periods=8, freq="ME"),
            "spread": [1, 2, 3, 4, 5, 6, 7, 8],
            "unemployment": [100, 100, 1, 2, 3, 4, 5, 6],
        }
    )

    result = qms.lead_lag_correlations(
        frame,
        "spread",
        "unemployment",
        lags=[0, 1, 2],
        min_observations=4,
    )

    assert result["selected_lag"] == 2
    assert result["selected_result"]["correlation"] == pytest.approx(1.0)
    assert result["methods_used"] == [qms.METHOD_LEAD_LAG_CORRELATION]
    assert "not proof of causality" in result["method_caveats"][1]


def test_lead_lag_reports_insufficient_observations_without_raising():
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2021-01-31", periods=4, freq="ME"),
            "spread": [1, None, 3, 4],
            "unemployment": [2, 3, None, 5],
        }
    )

    result = qms.lead_lag_correlations(
        frame,
        "spread",
        "unemployment",
        lags=[0, 1],
        min_observations=3,
    )

    assert result["selected_lag"] is None
    assert [item["status"] for item in result["lag_results"]] == [
        "insufficient_observations",
        "insufficient_observations",
    ]


def test_compare_analog_windows_returns_nonzero_ranked_distances_and_divergences():
    frame = pd.DataFrame(
        {
            "date": pd.date_range("1995-01-01", periods=8, freq="YS"),
            "gdp_yoy": [3.0, 3.2, 1.0, 0.5, -2.0, 5.5, 2.5, 2.6],
            "unemployment": [5.5, 5.4, 4.4, 5.0, 7.2, 9.0, 4.1, 4.0],
            "sentiment": [95, 96, 100, 88, 70, 80, 64, 63],
            "constant": [1, 1, 1, 1, 1, 1, 1, 1],
        }
    )

    result = qms.compare_analog_windows(
        frame,
        date_col="date",
        value_cols=["gdp_yoy", "unemployment", "sentiment", "constant"],
        windows=[
            {"label": "1995_soft_landing", "start": "1995-01-01", "end": "1996-12-31"},
            {"label": "2001_dotcom", "start": "1997-01-01", "end": "1998-12-31"},
            {"label": "2020_covid", "start": "1999-01-01", "end": "2000-12-31"},
        ],
        current_window={"start": "2001-01-01", "end": "2002-12-31"},
    )

    ranking = result["analog_similarity_ranking"]
    assert result["methods_used"] == [qms.METHOD_ANALOG_WINDOW_COMPARISON]
    assert [item["analog"] for item in ranking] == [
        "2001_dotcom",
        "1995_soft_landing",
        "2020_covid",
    ]
    assert all(item["distance"] > 0 for item in ranking)
    assert all("constant" not in item["common_variables"] for item in ranking)
    assert ranking[0]["top_divergences"]
    assert result["analogy_breakdown"]["1995_soft_landing"]["common_variable_count"] == 3


def test_recession_window_summary_and_method_labels():
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2020-01-31", periods=6, freq="ME"),
            "recession": [0, 1, 1, 0, 1, 1],
            "spread": [1.0, -0.5, -1.0, 0.2, -0.2, -0.1],
            "unemployment": [3.5, 4.1, 5.0, 4.7, 5.2, 5.4],
        }
    )

    summary = qms.recession_window_summary(frame, ["spread", "unemployment"])
    charts = qms.attach_methods_used(
        {
            "rolling_corr": {
                "id": "rolling_corr",
                "type": "line",
                "title": "Rolling Correlation",
                "description": "Known input.",
                "xAxisKey": "date",
                "series": [],
                "data": [],
            }
        },
        [qms.METHOD_ROLLING_CORRELATION, qms.METHOD_RECESSION_WINDOW_SUMMARY],
    )
    execution_summary = qms.attach_summary_methods(
        {"statistical_summary": "Computed lead-lag statistics."},
        [qms.METHOD_ROLLING_CORRELATION, qms.METHOD_RECESSION_WINDOW_SUMMARY],
    )

    assert len(summary["windows"]) == 2
    assert summary["windows"][0]["spread"]["mean"] == -0.75
    assert summary["windows"][0]["spread"]["at_start"] == -0.5
    assert summary["windows"][0]["spread"]["exact_lookbacks"] == {
        "6_periods_before": None,
        "12_periods_before": None,
    }
    assert summary["methods_used"] == [qms.METHOD_RECESSION_WINDOW_SUMMARY]
    assert charts["rolling_corr"]["methods_used"] == [
        qms.METHOD_ROLLING_CORRELATION,
        qms.METHOD_RECESSION_WINDOW_SUMMARY,
    ]
    assert execution_summary["methods_used"] == [
        qms.METHOD_ROLLING_CORRELATION,
        qms.METHOD_RECESSION_WINDOW_SUMMARY,
    ]


def test_recession_window_summary_uses_exact_pre_start_lookbacks_without_lookahead():
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2020-01-31", periods=10, freq="ME"),
            "recession": [0, 0, 1, 1, 0, 0, 0, 1, 1, 0],
            "spread": [10.0, 11.0, 99.0, 98.0, 20.0, 21.0, 22.0, 77.0, 76.0, 30.0],
        }
    )

    summary = qms.recession_window_summary(frame, ["spread"], lookback_periods=[1, 2])

    first, second = summary["windows"]
    assert first["spread"]["at_start"] == 99.0
    assert first["spread"]["exact_lookbacks"] == {
        "1_periods_before": 11.0,
        "2_periods_before": 10.0,
    }
    assert first["spread"]["prior_windows"]["prior_2_periods"] == {
        "observations": 2,
        "mean": 10.5,
        "min": 10.0,
        "max": 11.0,
    }

    assert second["spread"]["at_start"] == 77.0
    assert second["spread"]["exact_lookbacks"] == {
        "1_periods_before": 22.0,
        "2_periods_before": 21.0,
    }
    assert second["spread"]["prior_windows"]["prior_2_periods"]["mean"] == 21.5
    assert summary["method_notes"][1].startswith("Exact lookbacks use ordered rows before")


def test_recession_window_summary_accepts_generated_call_shapes():
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2020-01-31", periods=5, freq="ME"),
            "USREC": [0, 1, 1, 0, 0],
            "UNRATE": [3.7, 4.2, 5.0, 4.8, 4.5],
            "INDPRO": [102.0, 99.0, 97.0, 98.0, 100.0],
        }
    )

    by_alias = qms.recession_window_summary(
        frame,
        recession_col="USREC",
        variables=["UNRATE", "INDPRO"],
        date_col="date",
    )
    inferred = qms.recession_window_summary(
        frame,
        recession_col="USREC",
        date_col="date",
    )
    by_target_col = qms.recession_window_summary(
        frame,
        target_col="UNRATE",
        recession_col="USREC",
        date_col="date",
        windows=[1, 2],
    )
    by_target = qms.recession_window_summary(
        frame,
        target="INDPRO",
        recession_col="USREC",
        date_col="date",
        windows=[1],
    )

    assert by_alias["windows"][0]["UNRATE"]["at_start"] == 4.2
    assert by_alias["windows"][0]["INDPRO"]["at_start"] == 99.0
    assert set(inferred["windows"][0]) >= {"UNRATE", "INDPRO"}
    assert "USREC" not in inferred["windows"][0]
    assert by_target_col["windows"][0]["UNRATE"]["exact_lookbacks"] == {
        "1_periods_before": 3.7,
        "2_periods_before": None,
    }
    assert set(by_target["windows"][0]) >= {"start", "end", "periods", "INDPRO"}
    assert "UNRATE" not in by_target["windows"][0]


def test_attach_methods_used_accepts_single_chart_and_string_method():
    chart = {
        "id": "inflation",
        "type": "line",
        "title": "Inflation",
        "description": "Annual inflation.",
        "xAxisKey": "year",
        "series": [],
        "data": [],
        "methods_used": ["world_bank_annual_extraction"],
    }

    annotated = qms.attach_methods_used(chart, "cross_country_comparison")

    assert annotated["methods_used"] == [
        "world_bank_annual_extraction",
        "cross_country_comparison",
    ]
    assert chart["methods_used"] == ["world_bank_annual_extraction"]


def test_attach_summary_methods_treats_string_as_one_method_label():
    summary = qms.attach_summary_methods(
        {"statistical_summary": "Computed annual indicators."},
        "world_bank_annual_extraction",
    )

    assert summary["methods_used"] == ["world_bank_annual_extraction"]


def test_save_quant_outputs_sanitizes_json_and_derives_chart_ids(tmp_path):
    charts = {
        "macro_signal": {
            "type": "line",
            "title": "Macro Signal",
            "description": "JSON-safe payload.",
            "xAxisKey": "date",
            "series": [{"dataKey": "value", "label": "Value", "color": "#3b82f6"}],
            "data": [
                {
                    "date": pd.Timestamp("2026-04-30"),
                    "value": np.float64(1.25),
                    "missing_value": np.float64("nan"),
                    "period": pd.Period("2026-04", freq="M"),
                }
            ],
        }
    }
    summary = {
        "statistical_summary": "Computed current-cycle metrics.",
        "latest": np.float64(1.25),
        "missing": pd.NA,
    }

    handoff = qms.save_quant_outputs(tmp_path, charts, summary)

    assert handoff["chart_ids"] == ["macro_signal"]
    saved_charts = json.loads((tmp_path / "charts.json").read_text(encoding="utf-8"))
    saved_summary = json.loads((tmp_path / "execution_summary.json").read_text(encoding="utf-8"))
    assert saved_charts["macro_signal"]["id"] == "macro_signal"
    assert saved_charts["macro_signal"]["data"][0] == {
        "date": "2026-04-30T00:00:00",
        "value": 1.25,
        "missing_value": None,
        "period": "2026-04",
    }
    assert saved_summary["missing"] is None
    assert saved_summary["chart_ids"] == ["macro_signal"]
    assert saved_summary["charts_json"] == str(tmp_path / "charts.json")
    assert saved_summary["execution_summary_json"] == str(tmp_path / "execution_summary.json")


def test_save_quant_outputs_canonicalizes_dual_axis_config_chart(tmp_path):
    charts = {
        "labor_replay": {
            "type": "dual_axis",
            "title": "Labor Replay",
            "data": [
                {"date": "2026-01-01", "UNRATE": 4.0, "PAYEMS_mil": 158.0},
                {"date": "2026-02-01", "UNRATE": 4.1, "PAYEMS_mil": 158.2},
            ],
            "config": {
                "xAxis": {"dataKey": "date"},
                "yAxis": [
                    {"dataKey": "UNRATE", "label": "Unemployment (%)"},
                    {"dataKey": "PAYEMS_mil", "label": "Payrolls (M)"},
                ],
                "colors": ["#2563eb", "#dc2626"],
            },
        }
    }

    handoff = qms.save_quant_outputs(
        tmp_path,
        charts,
        {"statistical_summary": "Computed labor replay chart data."},
    )

    saved_charts = json.loads((tmp_path / "charts.json").read_text(encoding="utf-8"))
    chart = saved_charts["labor_replay"]
    assert handoff["chart_ids"] == ["labor_replay"]
    assert chart["type"] == "composed"
    assert chart["xAxisKey"] == "date"
    assert [series["dataKey"] for series in chart["series"]] == ["UNRATE", "PAYEMS_mil"]
    assert chart["series"][0]["yAxisId"] == "left"
    assert chart["series"][1]["yAxisId"] == "right"


def test_save_quant_outputs_collapses_same_scale_dual_axis_chart(tmp_path):
    charts = {
        "growth_composite": {
            "type": "composed",
            "title": "GDP and Industrial Production Growth",
            "xAxisKey": "date",
            "data": [
                {"date": "2025-01-01", "GDP_YoY": 2.0, "INDPRO_YoY": 1.0},
                {"date": "2025-04-01", "GDP_YoY": 4.0, "INDPRO_YoY": 4.0},
            ],
            "series": [
                {
                    "dataKey": "GDP_YoY",
                    "label": "GDP YoY (%)",
                    "color": "#2563eb",
                    "type": "line",
                    "yAxisId": "left",
                },
                {
                    "dataKey": "INDPRO_YoY",
                    "label": "INDPRO YoY (%)",
                    "color": "#16a34a",
                    "type": "line",
                    "yAxisId": "right",
                },
            ],
        }
    }

    qms.save_quant_outputs(
        tmp_path,
        charts,
        {"statistical_summary": "Computed growth composite chart data."},
    )

    saved_charts = json.loads((tmp_path / "charts.json").read_text(encoding="utf-8"))
    chart = saved_charts["growth_composite"]
    assert [series["yAxisId"] for series in chart["series"]] == ["left", "left"]


def test_save_quant_outputs_normalizes_legacy_scenarios(tmp_path):
    charts = {
        "scenario_chart": {
            "type": "bar",
            "title": "Scenario Chart",
            "description": "Scenario handoff.",
            "xAxisKey": "scenario",
            "series": [{"dataKey": "value", "label": "Value", "color": "#3b82f6"}],
            "data": [{"scenario": "base", "value": 1}],
        }
    }
    summary = {
        "statistical_summary": "Computed scenario cases.",
        "scenarios": {
            "base": {
                "scenario": "base",
                "assumptions": "Soft landing holds.",
                "indicator_triggers": "Labor remains resilient.",
                "confidence": "medium",
                "uncertainty_notes": "Data are revised.",
            },
            "upside": {
                "scenario": "bull",
                "assumptions": "Growth reaccelerates.",
                "indicator_triggers": "Production and payrolls improve.",
                "confidence": "low",
                "uncertainty_notes": "Policy lags remain uncertain.",
            },
            "downside": {
                "scenario": "bear",
                "assumptions": "Credit stress broadens.",
                "indicator_triggers": "Unemployment and delinquencies rise.",
                "confidence": "medium",
                "uncertainty_notes": "Timing cannot be pinned down.",
            },
        },
    }

    qms.save_quant_outputs(tmp_path, charts, summary)

    saved_summary = json.loads((tmp_path / "execution_summary.json").read_text(encoding="utf-8"))
    assert [row["scenario"] for row in saved_summary["scenario_table"]] == [
        "base",
        "bull",
        "bear",
    ]
    assert saved_summary["scenario_table"][0]["assumptions"] == ["Soft landing holds."]
    assert qms.METHOD_SCENARIO_STRESS_TEST in saved_summary["methods_used"]


def test_save_quant_outputs_drops_empty_chart_definitions(tmp_path):
    charts = {
        "valid_chart": {
            "type": "bar",
            "title": "Valid Chart",
            "xAxisKey": "period",
            "series": [{"dataKey": "value", "label": "Value", "color": "#3b82f6"}],
            "data": [{"period": "FY2026", "value": 1.0}],
        },
        "empty_chart": {
            "type": "bar",
            "title": "Empty Chart",
            "xAxisKey": "period",
            "series": [{"dataKey": "value", "label": "Value", "color": "#ef4444"}],
            "data": [],
        },
    }

    handoff = qms.save_quant_outputs(
        tmp_path,
        charts,
        {"statistical_summary": "Computed available chart data."},
    )

    saved_charts = json.loads((tmp_path / "charts.json").read_text(encoding="utf-8"))
    saved_summary = json.loads((tmp_path / "execution_summary.json").read_text(encoding="utf-8"))
    assert handoff["chart_ids"] == ["valid_chart"]
    assert handoff["dropped_chart_ids"] == ["empty_chart"]
    assert list(saved_charts) == ["valid_chart"]
    assert saved_summary["chart_ids"] == ["valid_chart"]
    assert saved_summary["dropped_chart_ids"] == ["empty_chart"]


def test_save_quant_outputs_preserves_new_governed_chart_families(tmp_path):
    charts = {
        "risk_profile": {
            "type": "radar",
            "title": "Risk Profile",
            "angleKey": "metric",
            "series": [{"dataKey": "score", "label": "Score", "color": "#3b82f6"}],
            "data": [{"metric": "Labor", "score": 0.0}, {"metric": "Credit", "score": 70.0}],
        },
        "component_incidence": {
            "type": "radial_bar",
            "title": "Component Incidence",
            "data": [{"name": "Labor", "value": 12.0}],
        },
        "signal_funnel": {
            "type": "funnelchart",
            "title": "Signal Funnel",
            "data": [{"name": "All", "value": 120.0}, {"name": "Triggered", "value": 18.0}],
        },
        "contribution_tree": {
            "type": "treemap",
            "title": "Contribution Tree",
            "data": [{"name": "Labor", "size": 40.0}],
        },
        "signal_flow": {
            "type": "sankeychart",
            "title": "Signal Flow",
            "data": {
                "nodes": [{"name": "Inputs"}, {"name": "Labor"}],
                "links": [{"source": 0, "target": 1, "value": 12.0}],
            },
        },
        "contribution_hierarchy": {
            "type": "sunburstchart",
            "title": "Contribution Hierarchy",
            "data": {"name": "Total", "children": [{"name": "Labor", "value": 40.0}]},
        },
    }

    handoff = qms.save_quant_outputs(
        tmp_path,
        charts,
        {"statistical_summary": "Computed broad chart family payloads."},
    )

    saved_charts = json.loads((tmp_path / "charts.json").read_text(encoding="utf-8"))
    assert handoff["dropped_chart_ids"] == []
    assert set(handoff["chart_ids"]) == set(charts)
    assert saved_charts["component_incidence"]["type"] == "radialBar"
    assert saved_charts["signal_flow"]["type"] == "sankey"
    assert saved_charts["contribution_hierarchy"]["type"] == "sunburst"


def test_save_quant_outputs_drops_invalid_new_chart_family_values(tmp_path):
    charts = {
        "valid_chart": {
            "type": "radar",
            "title": "Valid Radar",
            "angleKey": "metric",
            "series": [{"dataKey": "score", "label": "Score", "color": "#3b82f6"}],
            "data": [{"metric": "Labor", "score": 0.0}],
        },
        "broken_sankey": {
            "type": "sankey",
            "title": "Broken Sankey",
            "data": {
                "nodes": [{"name": "Inputs"}],
                "links": [{"source": 0, "target": 2, "value": 12.0}],
            },
        },
        "broken_sunburst": {
            "type": "sunburst",
            "title": "Broken Sunburst",
            "data": {"name": "Total", "children": []},
        },
    }

    handoff = qms.save_quant_outputs(
        tmp_path,
        charts,
        {"statistical_summary": "Computed broad chart family payloads."},
    )

    saved_charts = json.loads((tmp_path / "charts.json").read_text(encoding="utf-8"))
    assert handoff["chart_ids"] == ["valid_chart"]
    assert handoff["dropped_chart_ids"] == ["broken_sankey", "broken_sunburst"]
    assert list(saved_charts) == ["valid_chart"]


def test_save_quant_outputs_preserves_legacy_layout_y_keys_chart(tmp_path):
    charts = {
        "legacy_layout_chart": {
            "chart_type": "line",
            "title": "Legacy Layout Chart",
            "data": [
                {"date": "2026-01-01", "FEDFUNDS": 3.64, "DGS10": 4.25},
                {"date": "2026-02-01", "FEDFUNDS": 3.64, "DGS10": 4.30},
            ],
            "layout": {
                "x_key": "date",
                "y_keys": ["FEDFUNDS", "DGS10"],
                "show_legend": True,
            },
        }
    }

    handoff = qms.save_quant_outputs(
        tmp_path,
        charts,
        {"statistical_summary": "Computed legacy-layout chart data."},
    )

    saved_charts = json.loads((tmp_path / "charts.json").read_text(encoding="utf-8"))
    saved_summary = json.loads((tmp_path / "execution_summary.json").read_text(encoding="utf-8"))
    assert handoff["chart_ids"] == ["legacy_layout_chart"]
    assert handoff["dropped_chart_ids"] == []
    assert list(saved_charts) == ["legacy_layout_chart"]
    assert saved_summary["chart_ids"] == ["legacy_layout_chart"]
    assert "dropped_chart_ids" not in saved_summary


def test_save_quant_outputs_preserves_layout_x_key_y_keys_dict_chart(tmp_path):
    charts = {
        "signal_chart": {
            "chart_type": "line",
            "title": "Signal Chart",
            "data": [
                {"date": "2026-01-01", "composite": 2, "usrec": 0},
                {"date": "2026-02-01", "composite": 3, "usrec": 1},
            ],
            "layout": {
                "xKey": "date",
                "yKeys": [
                    {"key": "composite", "label": "Composite", "color": "#3b82f6"},
                    {"key": "usrec", "label": "NBER recession", "color": "#ef4444"},
                ],
            },
        }
    }

    handoff = qms.save_quant_outputs(
        tmp_path,
        charts,
        {"statistical_summary": "Computed signal chart data."},
    )

    saved_charts = json.loads((tmp_path / "charts.json").read_text(encoding="utf-8"))
    saved_summary = json.loads((tmp_path / "execution_summary.json").read_text(encoding="utf-8"))
    assert handoff["chart_ids"] == ["signal_chart"]
    assert handoff["dropped_chart_ids"] == []
    assert list(saved_charts) == ["signal_chart"]
    assert saved_summary["chart_ids"] == ["signal_chart"]
    assert "dropped_chart_ids" not in saved_summary


def test_save_quant_outputs_drops_non_renderable_axis_chart(tmp_path):
    charts = {
        "valid_chart": {
            "type": "line",
            "title": "Valid Chart",
            "xAxisKey": "date",
            "series": [{"dataKey": "risk", "label": "Risk", "color": "#3b82f6"}],
            "data": [{"date": "2026-01-01", "risk": 42.0}],
        },
        "broken_chart": {
            "type": "composed",
            "title": "Broken Chart",
            "xAxisKey": "date",
            "series": [
                {"dataKey": "spread", "label": "Spread", "color": "#8b5cf6"},
                {"dataKey": "risk", "label": "Risk", "color": "#ef4444"},
            ],
            "data": [
                {"date": "2026-01-01", "spread": 0.5, "risk": None},
                {"date": "2026-02-01", "spread": 0.6, "risk": None},
            ],
        },
    }

    handoff = qms.save_quant_outputs(
        tmp_path,
        charts,
        {"statistical_summary": "Computed available chart data."},
    )

    saved_charts = json.loads((tmp_path / "charts.json").read_text(encoding="utf-8"))
    saved_summary = json.loads((tmp_path / "execution_summary.json").read_text(encoding="utf-8"))
    assert handoff["chart_ids"] == ["valid_chart"]
    assert handoff["dropped_chart_ids"] == ["broken_chart"]
    assert list(saved_charts) == ["valid_chart"]
    assert saved_summary["chart_ids"] == ["valid_chart"]
    assert saved_summary["dropped_chart_ids"] == ["broken_chart"]


def test_save_quant_outputs_drops_axis_chart_with_blank_x_axis_values(tmp_path):
    charts = {
        "valid_chart": {
            "type": "bar",
            "title": "Valid Chart",
            "xAxisKey": "scenario",
            "series": [{"dataKey": "risk", "label": "Risk", "color": "#3b82f6"}],
            "data": [{"scenario": "base", "risk": 0.4}],
        },
        "blank_axis_chart": {
            "type": "bar",
            "title": "Blank Axis Chart",
            "xAxisKey": "window",
            "series": [{"dataKey": "score", "label": "Score", "color": "#3b82f6"}],
            "data": [
                {"window": "", "score": 0.2},
                {"window": "", "score": 0.3},
            ],
        },
    }

    handoff = qms.save_quant_outputs(
        tmp_path,
        charts,
        {"statistical_summary": "Computed available chart data."},
    )

    saved_charts = json.loads((tmp_path / "charts.json").read_text(encoding="utf-8"))
    saved_summary = json.loads((tmp_path / "execution_summary.json").read_text(encoding="utf-8"))
    assert handoff["chart_ids"] == ["valid_chart"]
    assert handoff["dropped_chart_ids"] == ["blank_axis_chart"]
    assert list(saved_charts) == ["valid_chart"]
    assert saved_summary["dropped_chart_ids"] == ["blank_axis_chart"]


def test_save_quant_outputs_repairs_common_x_axis_aliases(tmp_path):
    charts = {
        "analog_similarity": {
            "type": "bar",
            "title": "Analog Similarity",
            "xAxisKey": "window",
            "series": [{"dataKey": "score", "label": "Score", "color": "#3b82f6"}],
            "data": [
                {"analog": "2008", "score": 0.82},
                {"analog": "2001", "score": 0.75},
            ],
        }
    }

    handoff = qms.save_quant_outputs(
        tmp_path,
        charts,
        {"statistical_summary": "Computed analog chart data."},
    )

    saved_charts = json.loads((tmp_path / "charts.json").read_text(encoding="utf-8"))
    assert handoff["chart_ids"] == ["analog_similarity"]
    assert handoff["dropped_chart_ids"] == []
    assert saved_charts["analog_similarity"]["data"] == [
        {"analog": "2008", "score": 0.82, "window": "2008"},
        {"analog": "2001", "score": 0.75, "window": "2001"},
    ]


def test_save_quant_outputs_trims_empty_date_history_and_reference_areas(tmp_path):
    charts = {
        "macro_vs_stress": {
            "type": "line",
            "title": "Macro vs Stress",
            "xAxisKey": "date",
            "series": [
                {"dataKey": "GDP", "label": "GDP", "color": "#3b82f6"},
                {"dataKey": "sentiment", "label": "Sentiment", "color": "#ef4444"},
            ],
            "referenceAreas": [
                {"x1": "1857-01-01", "x2": "1858-01-01"},
                {"x1": "2008-01-01", "x2": "2009-06-01"},
                {"x1": "2020-03-01", "x2": "2020-04-01"},
            ],
            "data": [
                {"date": "1857-01-01", "USREC": 1, "GDP": None, "sentiment": None},
                {"date": "1947-01-01", "USREC": 0, "GDP": 100.0, "sentiment": None},
                {"date": "1947-02-01", "USREC": 0, "GDP": 101.0, "sentiment": 95.0},
                {"date": "2026-01-01", "USREC": 0, "GDP": None, "sentiment": None},
            ],
        }
    }
    summary = {
        "statistical_summary": {
            "recession_periods_since_2000": [
                {"x1": "1857-01-01", "x2": "1858-01-01"},
                {"x1": "2008-01-01", "x2": "2009-06-01"},
                {"x1": "2020-03-01", "x2": "2020-04-01"},
            ]
        }
    }

    qms.save_quant_outputs(tmp_path, charts, summary)

    saved_charts = json.loads((tmp_path / "charts.json").read_text(encoding="utf-8"))
    saved_summary = json.loads((tmp_path / "execution_summary.json").read_text(encoding="utf-8"))
    saved_chart = saved_charts["macro_vs_stress"]
    assert [row["date"] for row in saved_chart["data"]] == ["1947-01-01", "1947-02-01"]
    assert saved_chart["referenceAreas"] == []
    assert saved_summary["statistical_summary"]["recession_periods_since_2000"] == [
        {"x1": "2008-01-01", "x2": "2009-06-01"},
        {"x1": "2020-03-01", "x2": "2020-04-01"},
    ]


def test_save_quant_outputs_canonicalizes_legacy_axis_chart_layout(tmp_path):
    charts = {
        "unemployment_forecast": {
            "id": "unemployment_forecast",
            "chart_type": "LineChart",
            "title": "Unemployment Forecast",
            "layout": {
                "x_data_key": "date",
                "lines": [
                    {
                        "data_key": "UNRATE",
                        "label": "Unemployment Rate",
                        "color": "#3b82f6",
                        "y_axis_id": "left",
                    },
                    {
                        "data_key": "forecast",
                        "label": "Forecast",
                        "color": "#ef4444",
                        "stroke_dasharray": "5 5",
                        "y_axis_id": "left",
                    },
                ],
            },
            "data": [
                {"date": "2026-04-01", "UNRATE": 4.3, "forecast": None},
                {"date": "2026-05-01", "UNRATE": None, "forecast": 4.35},
            ],
        }
    }

    handoff = qms.save_quant_outputs(
        tmp_path,
        charts,
        {"statistical_summary": "Computed forecast chart."},
    )

    saved_charts = json.loads((tmp_path / "charts.json").read_text(encoding="utf-8"))
    saved_chart = saved_charts["unemployment_forecast"]
    assert handoff["chart_ids"] == ["unemployment_forecast"]
    assert handoff["dropped_chart_ids"] == []
    assert saved_chart["type"] == "line"
    assert saved_chart["xAxisKey"] == "date"
    assert saved_chart["series"] == [
        {
            "dataKey": "UNRATE",
            "label": "Unemployment Rate",
            "color": "#3b82f6",
            "yAxisId": "left",
        },
        {
            "dataKey": "forecast",
            "label": "Forecast",
            "color": "#ef4444",
            "yAxisId": "left",
            "strokeDasharray": "5 5",
        },
    ]


def test_save_quant_outputs_preserves_existing_charts_on_supplemental_empty_save(tmp_path):
    original_charts = {
        "macro_climate": {
            "id": "macro_climate",
            "type": "line",
            "title": "Macro Climate",
            "xAxisKey": "date",
            "series": [{"dataKey": "risk", "label": "Risk", "color": "#3b82f6"}],
            "data": [{"date": "2026-04-01", "risk": 0.42}],
        }
    }
    qms.save_quant_outputs(
        tmp_path,
        original_charts,
        {"statistical_summary": "Initial charted analysis."},
    )

    handoff = qms.save_quant_outputs(
        tmp_path,
        {},
        {"backtest_summary": {"method": "supplemental exact-value repair"}},
    )

    saved_charts = json.loads((tmp_path / "charts.json").read_text(encoding="utf-8"))
    saved_summary = json.loads((tmp_path / "execution_summary.json").read_text(encoding="utf-8"))
    assert list(saved_charts) == ["macro_climate"]
    assert saved_charts["macro_climate"]["data"] == [{"date": "2026-04-01", "risk": 0.42}]
    assert handoff["chart_ids"] == ["macro_climate"]
    assert handoff["preserved_prior_charts"] is True
    assert saved_summary["chart_ids"] == ["macro_climate"]
    assert saved_summary["preserved_prior_charts"] is True


def test_save_quant_outputs_promotes_nested_validation_artifacts(tmp_path):
    charts = {
        "forecast_chart": {
            "type": "line",
            "title": "Forecast Chart",
            "xAxisKey": "date",
            "series": [{"dataKey": "forecast", "label": "Forecast", "color": "#3b82f6"}],
            "data": [{"date": "2026-01-01", "forecast": 4.5}],
        }
    }
    backtest_summary = {
        "status": "ok",
        "metrics": {"rmse": 0.7},
        "methods_used": [qms.METHOD_WALK_FORWARD_OLS_BACKTEST],
    }
    model_comparison = [
        {"model": "direct_ols", "mae": 0.2},
        {"model": "baseline_last_value", "mae": 0.3},
    ]
    historical_simulations = [
        {
            "label": "2001 downturn",
            "status": "ok",
            "subsequent_outcome": {"periods": 6, "end": 5.8},
        }
    ]

    qms.save_quant_outputs(
        tmp_path,
        charts,
        {
            "forecast_diagnostics": {
                "backtest_summary": backtest_summary,
                "model_comparison": model_comparison,
            },
            "historical_replay": {"historical_simulations": historical_simulations},
        },
    )

    saved_summary = json.loads((tmp_path / "execution_summary.json").read_text(encoding="utf-8"))
    assert saved_summary["backtest_summary"] == backtest_summary
    assert saved_summary["model_comparison"] == model_comparison
    assert saved_summary["historical_simulations"] == historical_simulations
    assert qms.METHOD_WALK_FORWARD_OLS_BACKTEST in saved_summary["methods_used"]


def test_save_quant_outputs_promotes_common_nested_validation_artifacts(tmp_path):
    charts = {
        "forecast_chart": {
            "type": "line",
            "title": "Forecast Chart",
            "xAxisKey": "date",
            "series": [{"dataKey": "forecast", "label": "Forecast", "color": "#3b82f6"}],
            "data": [{"date": "2026-01-01", "forecast": 4.5}],
        }
    }
    summary = {
        "statistical_summary": "Nested validation artifacts are real helper outputs.",
        "unemployment_forecast": {
            "backtest_summary": {"status": "ok", "metrics": {"rmse": 0.5}},
            "model_comparison": [{"model": "direct_ols", "rmse": 0.5}],
        },
        "regime_classification": {
            "historical_analogs": [{"date": "2008-02-01", "label": "recession", "distance": 0.06}]
        },
        "recession_risk": {"backtest": {"status": "ok", "metrics": {"precision": 0.25}}},
    }

    qms.save_quant_outputs(tmp_path, charts, summary)

    saved_summary = json.loads((tmp_path / "execution_summary.json").read_text(encoding="utf-8"))
    assert saved_summary["backtest_summary"] == {
        "status": "ok",
        "metrics": {"rmse": 0.5},
    }
    assert saved_summary["model_comparison"] == [{"model": "direct_ols", "rmse": 0.5}]
    assert saved_summary["historical_simulations"] == [
        {"date": "2008-02-01", "label": "recession", "distance": 0.06}
    ]


def test_save_quant_outputs_promotes_composite_event_and_replay_validation(tmp_path):
    charts = {
        "risk_chart": {
            "type": "bar",
            "title": "Risk Chart",
            "xAxisKey": "threshold",
            "series": [{"dataKey": "precision", "label": "Precision", "color": "#3b82f6"}],
            "data": [{"threshold": "3+", "precision": 0.75}],
        }
    }
    summary = {
        "composite_predictive_indicator": {
            "backtest_summary": {"status": "ok", "metrics": {"precision": 0.75}},
            "methods_used": [qms.METHOD_COMPOSITE_PREDICTIVE_INDICATOR],
        },
        "event_signal_backtest": {
            "false_positive_analysis": {"false_positive_count": 2},
            "backtest_summary": {"status": "ok", "metrics": {"false_positive": 2}},
            "methods_used": [qms.METHOD_EVENT_SIGNAL_BACKTEST],
        },
        "historical_scenario_replay": {
            "historical_simulations": [{"label": "2001 downturn", "status": "ok", "max_signal": 4}],
            "methods_used": [qms.METHOD_HISTORICAL_SCENARIO_REPLAY],
        },
    }

    qms.save_quant_outputs(tmp_path, charts, summary)

    saved_summary = json.loads((tmp_path / "execution_summary.json").read_text(encoding="utf-8"))
    assert saved_summary["backtest_summary"] == {
        "status": "ok",
        "metrics": {"precision": 0.75},
    }
    assert saved_summary["historical_simulations"] == [
        {"label": "2001 downturn", "status": "ok", "max_signal": 4}
    ]
    assert qms.METHOD_COMPOSITE_PREDICTIVE_INDICATOR in saved_summary["methods_used"]
    assert qms.METHOD_EVENT_SIGNAL_BACKTEST in saved_summary["methods_used"]
    assert qms.METHOD_HISTORICAL_SCENARIO_REPLAY in saved_summary["methods_used"]


def test_save_quant_outputs_promotes_top_level_helper_aliases(tmp_path):
    charts = {
        "risk_chart": {
            "type": "bar",
            "title": "Risk Chart",
            "xAxisKey": "scenario",
            "series": [{"dataKey": "risk", "label": "Risk", "color": "#3b82f6"}],
            "data": [{"scenario": "base", "risk": 2}],
        }
    }
    backtest_summary = {
        "status": "ok",
        "metrics": {"precision": 0.46, "false_positive": 42},
        "methods_used": [qms.METHOD_COMPOSITE_PREDICTIVE_INDICATOR],
    }
    historical_simulations = {
        "signal_framework_backtest": {
            "status": "ok",
            "threshold": 3,
            "false_alarms": 7,
        }
    }

    qms.save_quant_outputs(
        tmp_path,
        charts,
        {
            "composite": {
                "backtest_summary": backtest_summary,
                "methods_used": [qms.METHOD_COMPOSITE_PREDICTIVE_INDICATOR],
            },
            "signal_backtest": {
                "historical_simulations": historical_simulations,
                "methods_used": [qms.METHOD_SIGNAL_FRAMEWORK_BACKTEST],
            },
            "scenario": {
                "scenario_table": [
                    {
                        "scenario": "base",
                        "assumptions": ["Soft landing."],
                        "indicator_triggers": ["Composite stays below 3."],
                        "confidence": "medium",
                        "uncertainty_notes": "Labor revisions matter.",
                    },
                    {
                        "scenario": "upside",
                        "assumptions": ["Reacceleration."],
                        "indicator_triggers": ["Composite falls to 0-1."],
                        "confidence": "low",
                        "uncertainty_notes": "Policy lags remain uncertain.",
                    },
                    {
                        "scenario": "downside",
                        "assumptions": ["Hard landing."],
                        "indicator_triggers": ["Composite rises to 4-5."],
                        "confidence": "low",
                        "uncertainty_notes": "Timing is uncertain.",
                    },
                ],
                "methods_used": [qms.METHOD_SCENARIO_STRESS_TEST],
            },
        },
    )

    saved_summary = json.loads((tmp_path / "execution_summary.json").read_text(encoding="utf-8"))
    assert saved_summary["backtest_summary"] == backtest_summary
    assert saved_summary["historical_simulations"] == historical_simulations
    assert [row["scenario"] for row in saved_summary["scenario_table"]] == [
        "base",
        "bull",
        "bear",
    ]
    assert qms.METHOD_COMPOSITE_PREDICTIVE_INDICATOR in saved_summary["methods_used"]
    assert qms.METHOD_SIGNAL_FRAMEWORK_BACKTEST in saved_summary["methods_used"]
    assert qms.METHOD_SCENARIO_STRESS_TEST in saved_summary["methods_used"]


def test_save_quant_outputs_promotes_signal_framework_summary_and_scenarios_alias(tmp_path):
    qms.save_quant_outputs(
        tmp_path,
        {},
        {
            "composite_indicator": {
                "backtest_summary": {
                    "precision": 0.02,
                    "false_positive": 52,
                    "methods_used": [qms.METHOD_COMPOSITE_PREDICTIVE_INDICATOR],
                }
            },
            "signal_backtest": {
                "historical_simulations": {
                    "signal_framework_backtest": {
                        "status": "ok",
                        "total_observations": 532,
                        "recession_count": 5,
                        "recession_calls_correct": 3,
                        "false_alarms": 9,
                        "true_positive_rate": 0.6,
                        "threshold": 2,
                        "lookback_periods": 12,
                        "false_alarm_lookahead_periods": 12,
                        "current_signal": {
                            "score": 1,
                            "interpretation": "yellow",
                            "components_triggered": ["sentiment"],
                            "date": "2026-04-01",
                        },
                        "pre_recession_scores": {"2008_recession_12m_before": {"score": 2}},
                        "false_alarm_episodes": [{"period": "2022-2023"}],
                    }
                },
                "methods_used": [qms.METHOD_SIGNAL_FRAMEWORK_BACKTEST],
            },
            "scenarios": {
                "scenario_table": [
                    {
                        "scenario": "base",
                        "assumptions": ["Current readings persist."],
                        "indicator_triggers": ["Composite score remains 1."],
                        "confidence": "medium",
                        "uncertainty_notes": "Revision risk.",
                    },
                    {
                        "scenario": "upside",
                        "assumptions": ["Sentiment recovers."],
                        "indicator_triggers": ["Composite score falls to 0."],
                        "confidence": "low",
                        "uncertainty_notes": "Policy lags.",
                    },
                    {
                        "scenario": "downside",
                        "assumptions": ["Claims rise and spreads widen."],
                        "indicator_triggers": ["Composite score rises above 2."],
                        "confidence": "medium",
                        "uncertainty_notes": "Timing risk.",
                    },
                ]
            },
        },
    )

    saved_summary = json.loads((tmp_path / "execution_summary.json").read_text(encoding="utf-8"))
    assert saved_summary["backtest_summary"]["false_positive"] == 52
    assert saved_summary["signal_framework_summary"]["false_alarms"] == 9
    assert saved_summary["signal_framework_summary"]["precision"] == pytest.approx(0.25)
    assert saved_summary["signal_framework_summary"]["current_signal"]["score"] == 1.0
    assert [row["scenario"] for row in saved_summary["scenario_table"]] == [
        "base",
        "bull",
        "bear",
    ]
    assert saved_summary["scenario_analysis"]["scenario_table"] == saved_summary["scenario_table"]


def test_save_quant_outputs_promotes_signal_framework_key_replay(tmp_path):
    qms.save_quant_outputs(
        tmp_path,
        {},
        {
            "signal_framework": {
                "status": "ok",
                "historical_simulations": {
                    "signal_framework_backtest": {
                        "status": "ok",
                        "total_observations": 599,
                        "recession_count": 6,
                        "recession_calls_correct": 6,
                        "false_alarms": 28,
                        "true_positive_rate": 1.0,
                        "threshold": 2,
                        "lookback_periods": 12,
                        "false_alarm_lookahead_periods": 12,
                        "current_signal": {
                            "score": 2,
                            "interpretation": "warning",
                            "components_triggered": ["curve", "payrolls"],
                            "date": "2026-04-30",
                        },
                        "pre_recession_scores": {"2008_recession_12m_before": {"score": 2}},
                        "false_alarm_episodes": [{"period": "1995"}],
                    }
                },
                "methods_used": [qms.METHOD_SIGNAL_FRAMEWORK_BACKTEST],
            }
        },
    )

    saved_summary = json.loads((tmp_path / "execution_summary.json").read_text(encoding="utf-8"))
    assert saved_summary["historical_simulations"] == {
        "signal_framework_backtest": {
            "status": "ok",
            "total_observations": 599,
            "recession_count": 6,
            "recession_calls_correct": 6,
            "false_alarms": 28,
            "true_positive_rate": 1.0,
            "threshold": 2,
            "lookback_periods": 12,
            "false_alarm_lookahead_periods": 12,
            "current_signal": {
                "score": 2,
                "interpretation": "warning",
                "components_triggered": ["curve", "payrolls"],
                "date": "2026-04-30",
            },
            "pre_recession_scores": {"2008_recession_12m_before": {"score": 2}},
            "false_alarm_episodes": [{"period": "1995"}],
        }
    }
    assert saved_summary["signal_framework_summary"]["false_alarms"] == 28
    assert saved_summary["signal_framework_summary"]["precision"] == pytest.approx(6 / 34)
    assert qms.METHOD_SIGNAL_FRAMEWORK_BACKTEST in saved_summary["methods_used"]


def test_save_quant_outputs_promotes_deep_nested_scenario_and_score_replay(tmp_path):
    charts = {
        "risk_chart": {
            "type": "line",
            "title": "Risk Chart",
            "xAxisKey": "date",
            "series": [{"dataKey": "score", "label": "Score", "color": "#3b82f6"}],
            "data": [{"date": "2026-01-01", "score": 75}],
        }
    }

    qms.save_quant_outputs(
        tmp_path,
        charts,
        {
            "statistical_summary": {
                "composite_recession_risk": {
                    "thresholds": {"high": 0.5},
                    "score_history": [
                        {
                            "date": "2001-01-01",
                            "composite_index": 0.7,
                            "composite_percentile_0_100": 88,
                            "target_value": 0,
                            "target_future": 1,
                            "target_event": True,
                        },
                        {
                            "date": "2019-01-01",
                            "composite_index": 0.8,
                            "composite_percentile_0_100": 92,
                            "target_value": 0,
                            "target_future": 0,
                            "target_event": False,
                        },
                    ],
                    "methods_used": [qms.METHOD_COMPOSITE_PREDICTIVE_INDICATOR],
                },
                "scenario_stress_test": {
                    "scenario_table": [
                        {
                            "name": "base",
                            "assumptions": "Soft landing.",
                            "indicator_triggers": "Labor remains stable.",
                            "confidence": "medium",
                            "uncertainty_notes": "Revisions matter.",
                        },
                        {
                            "name": "bull",
                            "assumptions": "Renewed acceleration.",
                            "indicator_triggers": "Production improves.",
                            "confidence": "low",
                            "uncertainty_notes": "Policy lags are uncertain.",
                        },
                        {
                            "name": "bear",
                            "assumptions": "Delayed recession.",
                            "indicator_triggers": "Claims rise.",
                            "confidence": "medium",
                            "uncertainty_notes": "Timing is uncertain.",
                        },
                    ],
                    "methods_used": [qms.METHOD_SCENARIO_STRESS_TEST],
                },
            }
        },
    )

    saved_summary = json.loads((tmp_path / "execution_summary.json").read_text(encoding="utf-8"))
    assert [row["scenario"] for row in saved_summary["scenario_table"]] == [
        "base",
        "bull",
        "bear",
    ]
    assert saved_summary["historical_simulations"] == [
        {
            "date": "2001-01-01",
            "status": "ok",
            "classification": "hit",
            "signal_percentile_0_100": 88.0,
            "composite_index": 0.7,
            "target_value": 0.0,
            "target_future": 1.0,
        },
        {
            "date": "2019-01-01",
            "status": "ok",
            "classification": "false_positive",
            "signal_percentile_0_100": 92.0,
            "composite_index": 0.8,
            "target_value": 0.0,
            "target_future": 0.0,
        },
    ]


def test_save_quant_outputs_does_not_fabricate_validation_artifacts(tmp_path):
    charts = {
        "forecast_chart": {
            "type": "line",
            "title": "Forecast Chart",
            "xAxisKey": "date",
            "series": [{"dataKey": "forecast", "label": "Forecast", "color": "#3b82f6"}],
            "data": [{"date": "2026-01-01", "forecast": 4.5}],
        }
    }

    qms.save_quant_outputs(
        tmp_path,
        charts,
        {"forecast_diagnostics": {"model_spec": "UNRATE(t+6) ~ predictors"}},
    )

    saved_summary = json.loads((tmp_path / "execution_summary.json").read_text(encoding="utf-8"))
    assert "backtest_summary" not in saved_summary
    assert "model_comparison" not in saved_summary
    assert "historical_simulations" not in saved_summary


def test_save_quant_outputs_promotes_signal_stack_metrics_and_replay(tmp_path):
    charts = {
        "signal_chart": {
            "type": "bar",
            "title": "Signal Chart",
            "xAxisKey": "date",
            "series": [{"dataKey": "score", "label": "Score", "color": "#3b82f6"}],
            "data": [{"date": "2001-01-01", "score": 3}],
        }
    }

    qms.save_quant_outputs(
        tmp_path,
        charts,
        {
            "composite_precision": 0.617,
            "composite_recall": 0.48,
            "composite_fpr": 0.057,
            "composite_accuracy": 0.87,
            "false_positive_count": 18,
            "true_positive_count": 29,
            "false_negative_count": 31,
            "recession_lead_signals": {
                "2001_12m": ["YC", "IC"],
                "2001_6m": ["YC"],
                "2008_3m": ["LM", "IC"],
            },
        },
    )

    saved_summary = json.loads((tmp_path / "execution_summary.json").read_text(encoding="utf-8"))
    assert saved_summary["backtest_summary"]["method"] == qms.METHOD_EVENT_SIGNAL_BACKTEST
    assert saved_summary["backtest_summary"]["metrics"]["composite_precision"] == 0.617
    assert saved_summary["backtest_summary"]["metrics"]["false_positive_count"] == 18
    assert saved_summary["historical_simulations"][0] == {
        "event": "2001",
        "lead_horizon": "12m",
        "signals_flashing": ["YC", "IC"],
        "signal_count": 2,
    }
    assert qms.METHOD_EVENT_SIGNAL_BACKTEST in saved_summary["methods_used"]
    assert qms.METHOD_HISTORICAL_SCENARIO_REPLAY in saved_summary["methods_used"]


def test_save_quant_outputs_promotes_macro_regime_comparison_validation(tmp_path):
    charts = {
        "regime_chart": {
            "type": "bar",
            "title": "Regime Chart",
            "xAxisKey": "indicator",
            "series": [{"dataKey": "current", "label": "Current", "color": "#3b82f6"}],
            "data": [{"indicator": "UNRATE", "current": 4.3}],
        }
    }

    qms.save_quant_outputs(
        tmp_path,
        charts,
        {
            "macro_regime_comparison": {
                "current": {"UNRATE": 4.3, "FEDFUNDS": 4.0},
                "pre_recession_avg": {"UNRATE": 5.1, "FEDFUNDS": 3.5},
            }
        },
    )

    saved_summary = json.loads((tmp_path / "execution_summary.json").read_text(encoding="utf-8"))
    assert saved_summary["backtest_summary"]["method"] == ("current_vs_historical_regime_replay")
    assert saved_summary["backtest_summary"]["current_values"] == {
        "FEDFUNDS": 4.0,
        "UNRATE": 4.3,
    }
    assert saved_summary["historical_simulations"]["comparison_period"] == ("pre_recession_avg")


def test_save_quant_outputs_promotes_recession_window_replay_validation(tmp_path):
    charts = {
        "cycle_chart": {
            "type": "bar",
            "title": "Cycle Chart",
            "xAxisKey": "window",
            "series": [{"dataKey": "unrate_chg", "label": "UNRATE", "color": "#3b82f6"}],
            "data": [{"window": "2008-01-01", "unrate_chg": 2.3}],
        }
    }

    qms.save_quant_outputs(
        tmp_path,
        charts,
        {
            "pre_recession_windows": {
                "2008-01-01": {"UNRATE": 4.6, "T10Y2Y": 0.31},
                "2020-03-01": {"UNRATE": 3.6, "T10Y2Y": 0.18},
            },
            "forward_outcomes": {
                "2008-01-01": {"UNRATE_chg": 2.3, "INDPRO_YOY_chg": -13.7},
                "2020-03-01": {"UNRATE_chg": 1.8, "INDPRO_YOY_chg": -0.4},
            },
        },
    )

    saved_summary = json.loads((tmp_path / "execution_summary.json").read_text(encoding="utf-8"))
    assert saved_summary["backtest_summary"]["method"] == ("historical_recession_window_replay")
    assert saved_summary["backtest_summary"]["status"] == "descriptive_replay"
    assert saved_summary["backtest_summary"]["window_count"] == 2
    assert saved_summary["historical_simulations"][0] == {
        "window_start": "2008-01-01",
        "pre_window_values": {"UNRATE": 4.6, "T10Y2Y": 0.31},
        "subsequent_outcomes": {"UNRATE_chg": 2.3, "INDPRO_YOY_chg": -13.7},
    }
    assert qms.METHOD_HISTORICAL_SCENARIO_REPLAY in saved_summary["methods_used"]


def test_build_scenario_stress_test_accepts_upside_downside_aliases_and_legacy_topic():
    result = qms.build_scenario_stress_test(
        [
            {
                "scenario": "baseline",
                "assumptions": "Soft landing holds.",
                "indicator_triggers": "Labor remains resilient.",
                "confidence": "medium",
                "uncertainty_notes": "Data are revised.",
            },
            {
                "scenario": "upside",
                "assumptions": "Growth reaccelerates.",
                "indicator_triggers": "Production and payrolls improve.",
                "confidence": "low",
                "uncertainty_notes": "Policy lags remain uncertain.",
            },
            {
                "scenario": "downside",
                "assumptions": "Credit stress broadens.",
                "indicator_triggers": "Unemployment and delinquencies rise.",
                "confidence": "medium",
                "uncertainty_notes": "Timing cannot be pinned down.",
            },
        ],
        "investment_committee_macro",
    )

    assert result["topic"] == "investment_committee_macro"
    assert [row["scenario"] for row in result["scenario_table"]] == [
        "base",
        "bull",
        "bear",
    ]
    assert qms.METHOD_SCENARIO_STRESS_TEST in result["methods_used"]


def test_build_scenario_stress_test_accepts_panel_plus_legacy_rows():
    panel = pd.DataFrame(
        {
            "date": pd.date_range("2026-01-31", periods=2, freq="ME"),
            "composite": [0.2, 0.4],
        }
    )
    rows = [
        {
            "scenario": "base",
            "assumptions": "Composite remains contained.",
            "indicator_triggers": "Composite remains below stress threshold.",
            "confidence": "medium",
            "uncertainty_notes": "Data are revised.",
        },
        {
            "scenario": "upside",
            "assumptions": "Composite improves.",
            "indicator_triggers": "Labor and production firm.",
            "confidence": "low",
            "uncertainty_notes": "Policy timing is uncertain.",
        },
        {
            "scenario": "downside",
            "assumptions": "Composite deteriorates.",
            "indicator_triggers": "Credit and labor stress broaden.",
            "confidence": "medium",
            "uncertainty_notes": "Recession timing cannot be concluded.",
        },
    ]

    result = qms.build_scenario_stress_test(panel, rows, target_col="USREC")

    assert [row["scenario"] for row in result["scenario_table"]] == [
        "base",
        "bull",
        "bear",
    ]
    assert "Legacy scenario helper arguments were ignored" in result["limitations"][-1]


def test_save_quant_outputs_rejects_mismatched_chart_id(tmp_path):
    with pytest.raises(ValueError, match="does not match chart id"):
        qms.save_quant_outputs(
            tmp_path,
            {"expected_id": {"id": "different_id", "type": "line"}},
            {"statistical_summary": "x"},
        )


def test_lead_lag_degrades_when_scipy_is_unavailable(monkeypatch):
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2021-01-31", periods=5, freq="ME"),
            "spread": [1, 2, 3, 4, 5],
            "unemployment": [2, 4, 6, 8, 10],
        }
    )
    monkeypatch.setattr(qms, "_scipy_stats", None)

    result = qms.lead_lag_correlations(
        frame, "spread", "unemployment", lags=[0], min_observations=3
    )

    assert result["selected_lag"] == 0
    assert result["selected_result"]["correlation"] == pytest.approx(1.0)
    assert result["selected_result"]["p_value"] is None


def test_ols_regression_recovers_synthetic_coefficients():
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2020-01-31", periods=20, freq="ME"),
            "claims": np.arange(20, dtype=float),
            "yield_curve": np.arange(20, dtype=float) * 2,
        }
    )
    frame["unemployment"] = 2.0 + 3.0 * frame["claims"] - 0.5 * frame["yield_curve"]

    result = qms.ols_regression(
        frame,
        "unemployment",
        ["claims", "yield_curve"],
        min_observations=8,
    )

    estimates = {item["term"]: item["estimate"] for item in result["coefficients"]}
    assert estimates["const"] == pytest.approx(2.0)
    assert estimates["claims"] + 2 * estimates["yield_curve"] == pytest.approx(2.0)
    assert result["model_spec"] == "unemployment ~ const + claims + yield_curve"
    assert result["target_variable"] == "unemployment"
    assert result["features"] == ["claims", "yield_curve"]
    assert qms.METHOD_OLS_REGRESSION in result["methods_used"]
    assert "_prediction_model" not in json.dumps(result)


def test_ols_regression_falls_back_without_statsmodels(monkeypatch):
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2020-01-31", periods=12, freq="ME"),
            "claims": np.arange(12, dtype=float),
            "unemployment": 1.0 + 2.0 * np.arange(12, dtype=float),
        }
    )
    monkeypatch.setattr(qms, "_statsmodels_api", None)
    monkeypatch.setattr(qms, "_adfuller", None)

    result = qms.ols_regression(frame, "unemployment", ["claims"], min_observations=8)

    estimates = {item["term"]: item["estimate"] for item in result["coefficients"]}
    assert estimates["const"] == pytest.approx(1.0)
    assert estimates["claims"] == pytest.approx(2.0)
    assert any("statsmodels_unavailable" in note for note in result["method_notes"])
    assert all(check["p_value"] is None for check in result["diagnostics"]["stationarity"])


def test_direct_ols_forecast_output_schema_and_json_safety():
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2018-01-31", periods=36, freq="ME"),
            "yield_curve": np.linspace(1.5, -0.5, 36),
            "claims": np.linspace(200_000, 260_000, 36),
            "payrolls": np.linspace(150, 80, 36),
            "industrial_production": np.linspace(100, 104, 36),
        }
    )
    frame["unemployment"] = (
        4.0
        - 0.2 * frame["yield_curve"]
        + 0.00001 * frame["claims"]
        - 0.003 * frame["payrolls"]
        - 0.01 * frame["industrial_production"]
    )

    result = qms.direct_ols_forecast(
        frame,
        "unemployment",
        ["yield_curve", "claims", "payrolls", "industrial_production"],
        horizon=6,
        min_observations=12,
    )

    assert set(result) >= {
        "model_spec",
        "estimation_window",
        "target_variable",
        "features",
        "diagnostics",
        "forecast_table",
        "caveats",
    }
    assert result["target_variable"] == "unemployment"
    assert result["features"] == [
        "unemployment",
        "yield_curve",
        "claims",
        "payrolls",
        "industrial_production",
    ]
    assert len(result["forecast_table"]) == 6
    assert result["forecast_table"][0]["horizon"] == 1
    assert result["forecast_table"][0]["date"] == result["forecast_table"][0]["forecast_period"]
    assert result["forecast_table"][-1]["horizon"] == 6
    assert result["diagnostics"]["selected_horizon"] == 6
    assert result["diagnostics"]["selected_horizon_model"]["horizon"] == 6
    assert result["diagnostics"]["r_squared"] == pytest.approx(
        result["diagnostics"]["selected_horizon_model"]["r_squared"]
    )
    assert result["diagnostics"]["r_squared"] is not None
    assert result["backtest_summary"]["status"] == "ok"
    assert result["model_comparison"]
    assert qms.METHOD_WALK_FORWARD_OLS_BACKTEST in result["methods_used"]
    assert "not evidence" in result["caveats"][0]
    json.dumps(result)


def test_direct_ols_forecast_can_skip_nested_backtests(monkeypatch):
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2018-01-31", periods=36, freq="ME"),
            "claims": np.linspace(200_000, 260_000, 36),
        }
    )
    frame["unemployment"] = 3.0 + 0.00001 * frame["claims"]

    def fail_backtest(*args, **kwargs):
        raise AssertionError("nested walk-forward backtest should not run")

    monkeypatch.setattr(qms, "walk_forward_ols_backtest", fail_backtest)

    result = qms.direct_ols_forecast(
        frame,
        "unemployment",
        ["claims"],
        horizon=6,
        min_observations=12,
        run_backtests=False,
    )

    assert len(result["forecast_table"]) == 6
    assert result["backtest_summary"] == {"status": "not_run", "horizon_results": []}
    assert result["model_comparison"] == []
    assert qms.METHOD_WALK_FORWARD_OLS_BACKTEST not in result["methods_used"]


def test_direct_ols_forecast_dedupes_target_when_lag_is_requested():
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2018-01-31", periods=36, freq="ME"),
            "claims": np.linspace(200_000, 260_000, 36),
        }
    )
    frame["unemployment"] = 3.0 + 0.00001 * frame["claims"]

    result = qms.direct_ols_forecast(
        frame,
        "unemployment",
        ["unemployment", "claims", "claims"],
        horizon=2,
        min_observations=12,
        run_backtests=False,
    )

    assert result["features"] == ["unemployment", "claims"]
    assert "unemployment + unemployment" not in result["model_spec"]
    assert all(row["status"] == "ok" for row in result["forecast_table"])


def test_walk_forward_ols_backtest_compares_against_baselines():
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2015-01-31", periods=48, freq="ME"),
            "claims": np.linspace(200_000, 300_000, 48),
        }
    )
    frame["unemployment"] = 3.0 + 0.00002 * frame["claims"]

    result = qms.walk_forward_ols_backtest(
        frame,
        "unemployment",
        ["claims"],
        horizon=2,
        min_observations=12,
    )

    assert result["status"] == "ok"
    assert result["prediction_horizon"] == 2
    assert result["validation_window"]["start"] <= result["validation_window"]["end"]
    assert {row["model"] for row in result["model_comparison"]} == {
        "direct_ols",
        "baseline_last_value",
        "baseline_train_mean",
    }
    assert result["baseline_comparison"]["last_value"]["mae"] is not None
    assert result["backtest_table"][-1]["target_date"] == result["validation_window"]["end"]
    json.dumps(result)


def test_event_signal_backtest_reports_false_positives_and_lead_times():
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2020-01-31", periods=18, freq="ME"),
            "signal": [
                0.1,
                0.2,
                0.8,
                0.9,
                0.2,
                0.1,
                0.7,
                0.8,
                0.1,
                0.2,
                0.1,
                0.8,
                0.1,
                0.2,
                0.1,
                0.1,
                0.1,
                0.1,
            ],
            "event": [0, 0, 0, 0, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 0, 0],
        }
    )

    result = qms.event_signal_backtest(
        frame,
        signal_col="signal",
        target_col="event",
        threshold=0.7,
        prediction_horizon=2,
        min_observations=8,
    )

    assert result["status"] == "ok"
    assert result["metrics"]["false_positive"] >= 1
    assert result["backtest_summary"]["metrics"]["false_positive"] >= 1
    assert "average_lead_periods" in result["false_positive_analysis"]
    assert result["methods_used"] == [qms.METHOD_EVENT_SIGNAL_BACKTEST]
    json.dumps(result)


def test_signal_framework_backtest_reports_recession_scores_and_false_alarms():
    dates = pd.date_range("1999-01-31", periods=36, freq="ME")
    frame = pd.DataFrame(
        {
            "date": dates,
            "curve": [0] * 36,
            "claims": [0] * 36,
            "sentiment": [0] * 36,
            "USREC": [0] * 36,
        }
    )
    frame.loc[6:8, ["curve", "claims", "sentiment"]] = 1
    frame.loc[18:19, "USREC"] = 1
    frame.loc[15:17, ["curve", "claims", "sentiment"]] = 1

    result = qms.signal_framework_backtest(
        frame,
        component_cols=["curve", "claims", "sentiment"],
        recession_col="USREC",
        threshold=3,
        lookback_periods=6,
        false_alarm_lookahead_periods=3,
        component_labels={"curve": "yield_inversion", "claims": "claims_rising"},
        min_observations=12,
    )

    payload = result["historical_simulations"]["signal_framework_backtest"]
    assert result["status"] == "ok"
    assert result["methods_used"] == [qms.METHOD_SIGNAL_FRAMEWORK_BACKTEST]
    assert payload["recession_calls_correct"] == 1
    assert payload["true_positive_rate"] == pytest.approx(1.0)
    assert payload["false_alarms"] == 1
    assert payload["false_alarm_episodes"][0]["period"] == "1999"
    assert payload["pre_recession_scores"]["2000_recession_6m_before"]["score"] == 3.0
    assert (
        "yield_inversion"
        in payload["pre_recession_scores"]["2000_recession_6m_before"]["components_triggered"]
    )
    json.dumps(result)


def test_signal_framework_backtest_rejects_continuous_recession_column():
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2020-01-31", periods=30, freq="ME"),
            "curve": [0, 1] * 15,
            "claims": [1, 0] * 15,
            "UNRATE": np.linspace(3.5, 5.2, 30),
        }
    )

    with pytest.raises(ValueError, match="binary 0/1 recession indicator"):
        qms.signal_framework_backtest(
            frame,
            component_cols=["curve", "claims"],
            recession_col="UNRATE",
            threshold=2,
            min_observations=12,
        )


def test_historical_scenario_replay_summarizes_named_windows():
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2000-01-31", periods=36, freq="ME"),
            "spread": np.linspace(1.0, -1.0, 36),
            "claims": np.linspace(200_000, 280_000, 36),
            "unemployment": np.linspace(4.0, 6.0, 36),
        }
    )

    result = qms.historical_scenario_replay(
        frame,
        signal_cols=["spread", "claims"],
        outcome_col="unemployment",
        windows=[{"label": "synthetic slowdown", "start": "2000-06-01", "end": "2001-03-31"}],
        lookahead_periods=3,
    )

    row = result["historical_simulations"][0]
    assert row["label"] == "synthetic slowdown"
    assert row["status"] == "ok"
    assert set(row["signal_path"]) == {"spread", "claims"}
    assert row["subsequent_outcome"]["periods"] == 3
    assert result["methods_used"] == [qms.METHOD_HISTORICAL_SCENARIO_REPLAY]
    json.dumps(result)


def test_historical_scenario_replay_accepts_target_scenario_event_windows():
    frame = pd.DataFrame(
        {
            "date": pd.date_range("1999-01-31", periods=48, freq="ME"),
            "USREC": [0] * 12 + [1] * 6 + [0] * 18 + [1] * 4 + [0] * 8,
            "UNRATE": np.linspace(4.0, 7.0, 48),
        }
    )

    result = qms.historical_scenario_replay(
        frame,
        target_col="UNRATE",
        scenario_col="USREC",
        date_col="date",
        pre_periods=3,
        post_periods=6,
        analog_count=2,
    )

    assert result["methods_used"] == [qms.METHOD_HISTORICAL_SCENARIO_REPLAY]
    assert result["simulation_design"]["event_definition"] == "USREC > 0 transition"
    assert len(result["analog_windows"]) == 2
    first = result["analog_windows"][0]
    assert first["status"] == "ok"
    assert first["event_start_date"] == "2000-01-31"
    assert first["target_change"] == pytest.approx(6 * (3.0 / 47))
    assert result["historical_simulations"] == result["analog_windows"]
    json.dumps(result)


def test_direct_ols_forecast_adds_interval_specific_bounds():
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2018-01-31", periods=36, freq="ME"),
            "claims": np.linspace(200_000, 260_000, 36),
        }
    )
    frame["unemployment"] = 3.0 + 0.00001 * frame["claims"]

    result = qms.direct_ols_forecast(
        frame,
        "unemployment",
        ["claims"],
        horizon=2,
        min_observations=12,
        prediction_interval=0.80,
    )

    first_row = result["forecast_table"][0]
    assert first_row["prediction_interval"] == pytest.approx(0.80)
    assert first_row["lower_80"] == first_row["lower"]
    assert first_row["upper_80"] == first_row["upper"]


def test_stationarity_warning_for_trending_levels_without_statsmodels(monkeypatch):
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2020-01-31", periods=24, freq="ME"),
            "claims": np.arange(24, dtype=float),
            "unemployment": np.arange(24, dtype=float) * 2,
        }
    )
    monkeypatch.setattr(qms, "_statsmodels_api", None)
    monkeypatch.setattr(qms, "_adfuller", None)

    result = qms.ols_regression(frame, "unemployment", ["claims"], min_observations=8)

    assert result["diagnostics"]["warnings"]
    assert "statsmodels_unavailable" in result["diagnostics"]["warnings"][0]


def test_econometrics_helpers_do_not_return_raw_model_objects():
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2020-01-31", periods=18, freq="ME"),
            "claims": np.arange(18, dtype=float),
            "unemployment": 3.0 + np.arange(18, dtype=float) * 0.1,
        }
    )

    regression = qms.ols_regression(frame, "unemployment", ["claims"], min_observations=8)
    forecast = qms.direct_ols_forecast(
        frame,
        "unemployment",
        ["claims"],
        horizon=3,
        min_observations=8,
    )

    encoded = json.dumps({"regression": regression, "forecast": forecast})
    assert "RegressionResults" not in encoded
    assert "_prediction_model" not in encoded


def test_align_period_features_handles_mixed_frequency_month_keys():
    daily_rates = pd.DataFrame(
        {
            "date": pd.to_datetime(["2020-01-02", "2020-01-31", "2020-02-03", "2020-02-28"]),
            "value": [1.0, 3.0, 5.0, 7.0],
        }
    )
    monthly_labor = pd.DataFrame(
        {
            "date": pd.to_datetime(["2020-01-01", "2020-02-01"]),
            "value": [4.0, 4.2],
        }
    )

    result = qms.align_period_features(
        {"rates": daily_rates, "labor": monthly_labor},
        frequency="M",
        how="inner",
    )

    assert result["date"].dt.strftime("%Y-%m-%d").tolist() == ["2020-01-01", "2020-02-01"]
    assert result["rates"].tolist() == [2.0, 6.0]
    assert result["labor"].tolist() == [4.0, 4.2]


def test_align_period_features_can_emit_period_end_dates():
    daily_rates = pd.DataFrame(
        {
            "date": pd.to_datetime(["2020-01-02", "2020-01-31", "2020-02-03", "2020-02-28"]),
            "value": [1.0, 3.0, 5.0, 7.0],
        }
    )
    monthly_labor = pd.DataFrame(
        {
            "date": pd.to_datetime(["2020-01-01", "2020-02-01"]),
            "value": [4.0, 4.2],
        }
    )

    result = qms.align_period_features(
        {"rates": daily_rates, "labor": monthly_labor},
        frequency="M",
        how="inner",
        timestamp_position="end",
    )

    assert result["date"].dt.strftime("%Y-%m-%d").tolist() == ["2020-01-31", "2020-02-29"]
    assert result["rates"].tolist() == [2.0, 6.0]
    assert result["labor"].tolist() == [4.0, 4.2]


def test_align_period_features_can_forward_fill_quarterly_into_monthly_panel():
    monthly_inflation = pd.DataFrame(
        {
            "date": pd.to_datetime(["2020-01-01", "2020-02-01", "2020-03-01", "2020-04-01"]),
            "value": [100.0, 101.0, 102.0, 103.0],
        }
    )
    quarterly_gdp = pd.DataFrame(
        {
            "date": pd.to_datetime(["2020-01-01", "2020-04-01"]),
            "value": [20_000.0, 20_100.0],
        }
    )

    result = qms.align_period_features(
        {"CPIAUCSL": monthly_inflation, "GDPC1": quarterly_gdp},
        frequency="M",
        how="outer",
        fill_method="ffill",
        fill_limit=2,
    )

    assert result["date"].dt.strftime("%Y-%m-%d").tolist() == [
        "2020-01-01",
        "2020-02-01",
        "2020-03-01",
        "2020-04-01",
    ]
    assert result["CPIAUCSL"].tolist() == [100.0, 101.0, 102.0, 103.0]
    assert result["GDPC1"].tolist() == [20_000.0, 20_000.0, 20_000.0, 20_100.0]
    assert result["date"].is_unique


def test_align_period_features_drops_future_projection_dates_by_default():
    today = pd.Timestamp.today().normalize()
    recent_month = (today - pd.DateOffset(months=1)).replace(day=1)
    future_quarter = (today + pd.DateOffset(months=3)).replace(day=1)
    monthly_macro = pd.DataFrame(
        {
            "date": [recent_month],
            "value": [4.1],
        }
    )
    projection_series = pd.DataFrame(
        {
            "date": [recent_month, future_quarter],
            "value": [4.0, 4.5],
        }
    )

    result = qms.align_period_features(
        {"UNRATE": monthly_macro, "NROU": projection_series},
        frequency="M",
        how="outer",
        fill_method="ffill",
        fill_limit=2,
    )

    assert result["date"].max() <= today
    assert future_quarter not in set(result["date"])


def test_align_period_features_allows_future_dates_when_requested():
    today = pd.Timestamp.today().normalize()
    future_month = (today + pd.DateOffset(months=2)).replace(day=1)
    projection_series = pd.DataFrame(
        {
            "date": [future_month],
            "value": [4.5],
        }
    )

    result = qms.align_period_features(
        {"NROU": projection_series},
        frequency="M",
        max_date=None,
    )

    assert future_month in set(result["date"])


def test_align_period_features_rejects_unknown_timestamp_position():
    with pytest.raises(ValueError, match="timestamp_position"):
        qms.align_period_features(
            {"x": pd.DataFrame({"date": pd.to_datetime(["2020-01-01"]), "value": [1.0]})},
            timestamp_position="middle",
        )


def test_composite_indicator_uses_lagged_predictors_without_lookahead():
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2020-01-31", periods=24, freq="ME"),
            "target": [0] * 10 + [1] * 14,
            "predictor": list(range(24)),
        }
    )

    lagged = qms.build_composite_predictive_indicator(
        frame,
        target_col="target",
        feature_cols=["predictor"],
        prediction_horizon=1,
        feature_lags={"predictor": 2},
        train_fraction=0.6,
        min_observations=8,
    )
    unlagged = qms.build_composite_predictive_indicator(
        frame,
        target_col="target",
        feature_cols=["predictor"],
        prediction_horizon=1,
        train_fraction=0.6,
        min_observations=8,
    )

    assert lagged["feature_transforms"]["predictor"]["lag_periods"] == 2
    assert lagged["latest_feature_values"]["predictor"] == 21.0
    assert unlagged["latest_feature_values"]["predictor"] == 23.0


def test_composite_indicator_reports_missing_features_and_keeps_usable_ones():
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2020-01-31", periods=24, freq="ME"),
            "target": [0, 1] * 12,
            "usable": np.linspace(0, 10, 24),
            "missing": [None] * 24,
        }
    )

    result = qms.build_composite_predictive_indicator(
        frame,
        target_col="target",
        feature_cols=["usable", "missing"],
        prediction_horizon=1,
        train_fraction=0.7,
        min_observations=8,
    )

    assert result["input_features"] == ["usable"]
    assert result["dropped_features"] == [
        {"feature": "missing", "reason": "all_missing_after_transform_or_lag"}
    ]


def test_composite_indicator_preserves_history_with_late_starting_feature():
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2020-01-31", periods=36, freq="ME"),
            "target": [0] * 18 + [1] * 18,
            "rates": np.linspace(2, -2, 36),
            "labor": np.linspace(-1, 3, 36),
            "late_credit": [None] * 10 + list(np.linspace(1, 4, 26)),
        }
    )

    result = qms.build_composite_predictive_indicator(
        frame,
        target_col="target",
        feature_cols=["rates", "labor", "late_credit"],
        feature_directions={"rates": -1, "labor": 1, "late_credit": 1},
        prediction_horizon=3,
        train_fraction=0.65,
        min_observations=8,
    )

    coverage = result["feature_coverage"]
    assert coverage["minimum_features_per_scored_row"] == 2
    assert coverage["scored_observations"] > coverage["full_feature_observations"]
    assert result["backtest_summary"]["status"] == "ok"
    assert result["latest_feature_values"]["late_credit"] == 4.0
    assert result["score_history"]
    assert (
        result["latest_percentile_0_100"]
        == result["score_history"][-1]["composite_percentile_0_100"]
    )
    assert all(
        0 <= row["composite_percentile_0_100"] <= 100
        for row in result["score_history"]
        if row["composite_percentile_0_100"] is not None
    )


def test_composite_indicator_rejects_impossible_feature_coverage():
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2020-01-31", periods=24, freq="ME"),
            "target": [0, 1] * 12,
            "usable": np.linspace(0, 10, 24),
        }
    )

    with pytest.raises(ValueError, match="min_feature_coverage cannot exceed"):
        qms.build_composite_predictive_indicator(
            frame,
            target_col="target",
            feature_cols=["usable"],
            min_feature_coverage=2,
        )


def test_composite_indicator_default_weights_are_deterministic_and_directional():
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2020-01-31", periods=30, freq="ME"),
            "target": [0] * 15 + [1] * 15,
            "rates": np.linspace(5, 1, 30),
            "credit": np.linspace(1, 5, 30),
        }
    )

    result_one = qms.build_composite_predictive_indicator(
        frame,
        target_col="target",
        feature_cols=["rates", "credit"],
        feature_directions={"rates": -1, "credit": 1},
        prediction_horizon=2,
        train_fraction=0.7,
        min_observations=8,
    )
    result_two = qms.build_composite_predictive_indicator(
        frame,
        target_col="target",
        feature_cols=["rates", "credit"],
        feature_directions={"rates": -1, "credit": 1},
        prediction_horizon=2,
        train_fraction=0.7,
        min_observations=8,
    )

    assert result_one["weights_or_model"] == result_two["weights_or_model"]
    assert result_one["weights_or_model"]["weights"] == {"rates": -0.5, "credit": 0.5}
    assert result_one["latest_signal"] == "high"


def test_composite_indicator_accepts_string_feature_directions():
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2020-01-31", periods=30, freq="ME"),
            "target": [0] * 15 + [1] * 15,
            "yield_spread": np.linspace(5, 1, 30),
            "claims": np.linspace(1, 5, 30),
        }
    )

    result = qms.build_composite_predictive_indicator(
        frame,
        target_col="target",
        feature_cols=["yield_spread", "claims"],
        feature_directions={"yield_spread": "low", "claims": "high"},
        prediction_horizon=2,
        train_fraction=0.7,
        min_observations=8,
    )

    assert result["weights_or_model"]["weights"] == {
        "yield_spread": -0.5,
        "claims": 0.5,
    }
    assert result["feature_transforms"]["yield_spread"]["direction"] == -1.0
    assert result["feature_transforms"]["claims"]["direction"] == 1.0


def test_composite_indicator_threshold_classification_and_backtest_schema():
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2020-01-31", periods=36, freq="ME"),
            "target": [0] * 18 + [1] * 18,
            "labor_stress": np.linspace(-2, 3, 36),
            "credit_stress": np.linspace(-1, 4, 36),
        }
    )

    result = qms.build_composite_predictive_indicator(
        frame,
        target_col="target",
        target="recession_risk",
        feature_cols=["labor_stress", "credit_stress"],
        prediction_horizon=3,
        train_fraction=0.65,
        min_observations=8,
    )

    assert set(result) >= {
        "target",
        "prediction_horizon",
        "input_features",
        "feature_transforms",
        "normalization_method",
        "weights_or_model",
        "backtest_summary",
        "latest_index_value",
        "thresholds",
        "limitations",
    }
    assert result["latest_signal"] in {"low", "medium", "high"}
    assert result["thresholds"]["low"] < result["thresholds"]["high"]
    assert result["backtest_summary"]["status"] == "ok"
    assert set(result["backtest_summary"]["metrics"]) >= {
        "accuracy",
        "precision",
        "recall",
        "true_positive",
        "false_positive",
        "true_negative",
        "false_negative",
    }
    assert "predictive indicator" in result["limitations"][0]
    json.dumps(result)


def test_scenario_stress_test_validates_base_bull_bear_schema():
    result = qms.build_scenario_stress_test(
        [
            {
                "scenario": "base",
                "assumptions": ["Growth slows but stays positive"],
                "indicator_triggers": ["Unemployment rises less than 0.5pp"],
                "confidence": "medium",
                "uncertainty_notes": "Data revisions could change the labor signal.",
            },
            {
                "scenario": "bull",
                "assumptions": ["Inflation cools without a hiring break"],
                "indicator_triggers": ["Credit spreads remain contained"],
                "confidence": "low",
                "uncertainty_notes": "Soft-landing paths are sensitive to policy lags.",
            },
            {
                "scenario": "bear",
                "assumptions": ["Credit and labor stress reinforce each other"],
                "indicator_triggers": ["Claims and spreads breach stress thresholds"],
                "confidence": "medium",
                "uncertainty_notes": "Trigger timing is uncertain.",
            },
        ],
        topic="recession_risk",
    )

    assert result["topic"] == "recession_risk"
    assert [row["scenario"] for row in result["scenario_table"]] == ["base", "bull", "bear"]
    assert result["methods_used"] == [qms.METHOD_SCENARIO_STRESS_TEST]
    assert "not probabilities" in result["limitations"][0]
    json.dumps(result)


def test_scenario_stress_test_normalizes_uncertainty_note_lists():
    result = qms.build_scenario_stress_test(
        [
            {
                "scenario": "base",
                "assumptions": ["Growth slows but stays positive"],
                "indicator_triggers": ["Unemployment rises less than 0.5pp"],
                "confidence": "medium",
                "uncertainty_notes": ["Data revisions", "Policy lags"],
            },
            {
                "scenario": "upside",
                "assumptions": ["Inflation cools without a hiring break"],
                "indicator_triggers": ["Credit spreads remain contained"],
                "confidence": "low",
                "uncertainty_notes": ["Productivity timing is uncertain"],
            },
            {
                "scenario": "downside",
                "assumptions": ["Credit and labor stress reinforce each other"],
                "indicator_triggers": ["Claims and spreads breach stress thresholds"],
                "confidence": "medium",
                "uncertainty_notes": ["Trigger timing is uncertain"],
            },
        ],
        topic="recession_risk",
    )

    assert result["scenario_table"][0]["uncertainty_notes"] == "Data revisions; Policy lags"
    assert [row["scenario"] for row in result["scenario_table"]] == ["base", "bull", "bear"]


def test_scenario_stress_test_normalizes_generated_confidence_shapes():
    result = qms.build_scenario_stress_test(
        [
            {
                "scenario": "base",
                "assumptions": ["Growth slows but stays positive"],
                "indicator_triggers": ["Unemployment remains near 4.5%"],
                "confidence": "moderate",
                "uncertainty_notes": "Data revisions could change the signal.",
            },
            {
                "scenario": "upside",
                "assumptions": ["Productivity offsets labor cooling"],
                "indicator_triggers": ["Payrolls reaccelerate"],
                "confidence": "medium-high",
                "uncertainty_notes": "AI capex timing is uncertain.",
            },
            {
                "scenario": "downside",
                "assumptions": ["Credit and labor stress reinforce each other"],
                "indicator_triggers": ["Claims and delinquencies rise together"],
                "probability": "20%",
                "uncertainty_notes": "Trigger timing is uncertain.",
            },
        ],
        topic="recession_risk",
    )

    assert [row["confidence"] for row in result["scenario_table"]] == [
        "medium",
        "medium",
        "low",
    ]


def test_scenario_stress_test_accepts_legacy_panel_call_shape():
    panel = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-01", "2024-02-01"]),
            "UNRATE": [3.8, 3.9],
            "COMP_SCORE": [0.15, -0.05],
        }
    )

    result = qms.build_scenario_stress_test(
        panel,
        target_col="UNRATE",
        base_forecast=[{"date": "2024-03-01", "forecast": 4.0}],
        scenario_vars={"recession_shock": "COMP_SCORE"},
    )

    assert [row["scenario"] for row in result["scenario_table"]] == [
        "base",
        "bull",
        "bear",
    ]
    assert "UNRATE=3.9" in result["scenario_table"][0]["assumptions"][0]
    assert "Legacy scenario helper arguments were ignored" in result["limitations"][-1]
    json.dumps(result)


def test_scenario_stress_test_rejects_missing_required_rows():
    with pytest.raises(ValueError, match="missing required row"):
        qms.validate_scenario_table(
            [
                {
                    "scenario": "base",
                    "assumptions": ["Current trend persists"],
                    "indicator_triggers": ["No trigger"],
                    "confidence": "medium",
                    "uncertainty_notes": "Uncertain.",
                }
            ]
        )


def _regime_frame(previous, latest, *, recession_latest=0):
    values = [previous] * 4 + [latest]
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2020-01-31", periods=5, freq="ME"),
            "usrec": [0, 0, 0, 0, recession_latest],
        }
    )
    for category in qms.DEFAULT_REGIME_CATEGORIES:
        frame[category] = [row[category] for row in values]
    return frame


@pytest.mark.parametrize(
    ("previous", "latest", "expected"),
    [
        (
            {"rates": 0.7, "labor": 0.8, "inflation": 0.5, "credit": 0.7, "output": 0.8},
            {"rates": 0.7, "labor": 0.8, "inflation": 0.5, "credit": 0.7, "output": 0.8},
            "expansion",
        ),
        (
            {"rates": 0.7, "labor": 0.7, "inflation": 0.6, "credit": 0.6, "output": 0.7},
            {"rates": -0.2, "labor": -0.2, "inflation": 0.0, "credit": -0.3, "output": 0.0},
            "slowdown",
        ),
        (
            {"rates": -0.8, "labor": -0.7, "inflation": -0.6, "credit": -0.8, "output": -0.7},
            {"rates": -0.8, "labor": -0.7, "inflation": -0.6, "credit": -0.8, "output": -0.7},
            "recession",
        ),
        (
            {"rates": -0.8, "labor": -0.7, "inflation": -0.6, "credit": -0.8, "output": -0.7},
            {"rates": -0.2, "labor": -0.1, "inflation": 0.1, "credit": 0.0, "output": 0.1},
            "recovery",
        ),
        (
            {"rates": 0.0, "labor": 0.1, "inflation": 0.0, "credit": 0.1, "output": 0.0},
            {"rates": 0.5, "labor": 0.6, "inflation": 0.5, "credit": 0.5, "output": 0.6},
            "reacceleration",
        ),
    ],
)
def test_recession_regime_classifier_synthetic_regimes(previous, latest, expected):
    result = qms.classify_recession_regime(_regime_frame(previous, latest), recession_col="usrec")

    assert result["status"] == "ok"
    assert result["regime_label"] == expected
    assert result["methods_used"] == [qms.METHOD_RECESSION_REGIME_CLASSIFIER]
    assert len(result["evidence_table"]) == 5
    assert set(result["category_scores"]) == set(qms.DEFAULT_REGIME_CATEGORIES)
    assert "False positives can occur" in result["false_positive_caveat"]
    json.dumps(result)


def test_recession_regime_classifier_uses_recession_indicator_when_available():
    frame = _regime_frame(
        {"rates": 0.6, "labor": 0.6, "inflation": 0.6, "credit": 0.6, "output": 0.6},
        {"rates": 0.3, "labor": 0.2, "inflation": 0.2, "credit": 0.2, "output": 0.2},
        recession_latest=1,
    )

    result = qms.classify_recession_regime(frame, recession_col="usrec")

    assert result["regime_label"] == "recession"
    assert result["recession_indicator"] == "usrec"
    assert result["recession_indicator_active"] is True


def test_recession_regime_classifier_missing_series_fallback():
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2020-01-31", periods=2, freq="ME"),
            "rates": [0.5, 0.4],
            "labor": [0.3, 0.2],
        }
    )

    result = qms.classify_recession_regime(frame)

    assert result["status"] == "insufficient_categories"
    assert result["regime_label"] == "unclassified"
    assert result["available_categories"] == ["labor", "rates"]
    assert {item["category"] for item in result["missing_indicators"]} == {
        "inflation",
        "credit",
        "output",
    }
    assert "insufficient_categories" in result["fallback_behavior"]


def test_recession_regime_classifier_uses_latest_complete_row_before_partial_tail():
    frame = _regime_frame(
        {"rates": 0.1, "labor": 0.1, "inflation": 0.1, "credit": 0.1, "output": 0.1},
        {"rates": 0.7, "labor": 0.8, "inflation": 0.6, "credit": 0.7, "output": 0.8},
    )
    partial_tail = {
        "date": pd.Timestamp("2020-06-30"),
        "usrec": np.nan,
        "rates": 0.6,
        "labor": np.nan,
        "inflation": np.nan,
        "credit": np.nan,
        "output": np.nan,
    }
    frame = pd.concat([frame, pd.DataFrame([partial_tail])], ignore_index=True)

    result = qms.classify_recession_regime(frame, recession_col="usrec")

    assert result["status"] == "ok"
    assert result["date"] == "2020-05-31"
    assert result["regime_label"] == "reacceleration"
    assert set(result["category_scores"]) == set(qms.DEFAULT_REGIME_CATEGORIES)


def test_recession_regime_classifier_score_explanation_with_threshold_specs():
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2020-01-31", periods=6, freq="ME"),
            "unemployment_change": [0.8, 0.7, 0.4, 0.1, -0.1, -0.2],
            "credit_spread": [4.0, 3.5, 2.5, 1.8, 1.2, 1.0],
            "output_growth": [-2.0, -1.0, 0.0, 1.0, 2.0, 2.5],
        }
    )
    specs = [
        {
            "name": "labor_turn",
            "column": "unemployment_change",
            "category": "labor",
            "favorable_when": "low",
            "weak_threshold": -0.2,
            "strong_threshold": 0.8,
            "rationale": "Lower unemployment change is better.",
        },
        {
            "name": "credit_spread",
            "column": "credit_spread",
            "category": "credit",
            "favorable_when": "low",
            "weak_threshold": 1.0,
            "strong_threshold": 4.0,
        },
        {
            "name": "output_growth",
            "column": "output_growth",
            "category": "output",
            "favorable_when": "high",
            "weak_threshold": -1.0,
            "strong_threshold": 2.0,
        },
    ]

    result = qms.classify_recession_regime(
        frame,
        indicator_specs=specs,
        min_categories=3,
        momentum_periods=2,
    )

    assert result["status"] == "ok"
    assert result["regime_label"] in {
        "expansion",
        "slowdown",
        "recession",
        "recovery",
        "reacceleration",
    }
    assert {row["indicator"] for row in result["evidence_table"]} == {
        "labor_turn",
        "credit_spread",
        "output_growth",
    }
    assert all(-1.0 <= row["score"] <= 1.0 for row in result["evidence_table"])
    assert result["historical_analogs"]
    assert "deterministic score" in result["false_positive_caveat"]
    assert result["category_weights"] == {
        "credit": pytest.approx(0.2 / 0.65),
        "labor": pytest.approx(0.25 / 0.65),
        "output": pytest.approx(0.2 / 0.65),
    }
    json.dumps(result)


def test_recession_regime_classifier_normalizes_reversed_threshold_specs():
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2020-01-31", periods=6, freq="ME"),
            "yield_spread": [-0.8, -0.5, -0.2, 0.1, 0.3, 0.5],
            "sentiment": [55, 58, 62, 66, 70, 74],
            "credit_stress": [4.0, 3.5, 3.0, 2.4, 2.0, 1.5],
        }
    )
    specs = [
        {
            "name": "yield_curve",
            "column": "yield_spread",
            "category": "rates",
            "favorable_when": "high",
            "weak_threshold": 0.0,
            "strong_threshold": -0.5,
        },
        {
            "name": "sentiment",
            "column": "sentiment",
            "category": "consumer",
            "favorable_when": "high",
            "weak_threshold": 70,
            "strong_threshold": 60,
        },
        {
            "name": "credit_stress",
            "column": "credit_stress",
            "category": "credit",
            "favorable_when": "low",
            "weak_threshold": 1.0,
            "strong_threshold": 4.0,
        },
    ]

    result = qms.classify_recession_regime(
        frame,
        indicator_specs=specs,
        min_categories=3,
        momentum_periods=2,
    )

    assert result["status"] == "ok"
    assert result["regime_label"] in {
        "expansion",
        "slowdown",
        "recession",
        "recovery",
        "reacceleration",
    }
    assert {row["indicator"] for row in result["evidence_table"]} == {
        "yield_curve",
        "sentiment",
        "credit_stress",
    }
    assert all(-1.0 <= row["score"] <= 1.0 for row in result["evidence_table"])


def test_summarize_sec_company_facts_uses_named_columns_not_numeric_position():
    frame = pd.DataFrame(
        {
            "fiscal_year": [2021, 2025],
            "revenue": [100_000_000_000, 150_000_000_000],
            "net_income": [20_000_000_000, 30_000_000_000],
            "operating_cash_flow": [25_000_000_000, 35_000_000_000],
            "capital_expenditures": [5_000_000_000, 7_000_000_000],
            "research_and_development": [8_000_000_000, 12_000_000_000],
            "selling_general_and_admin": [6_000_000_000, 9_000_000_000],
            "diluted_eps": [1.25, 2.5],
            "assets": [250_000_000_000, 300_000_000_000],
            "long_term_debt": [50_000_000_000, 60_000_000_000],
            "shares": [16_000_000_000, 14_000_000_000],
        }
    )

    result = qms.summarize_sec_company_facts(frame)

    assert result["fiscal_year_latest"] == 2025
    assert result["revenue_latest"] == pytest.approx(150.0)
    assert result["net_income_latest"] == pytest.approx(30.0)
    assert result["revenue_growth_pct"] == pytest.approx(50.0)
    assert result["revenue_cagr_pct"] == pytest.approx(10.668, abs=0.001)
    assert result["net_margin_pct"] == pytest.approx(20.0)
    assert result["operating_cash_flow_latest"] == pytest.approx(35.0)
    assert result["capital_expenditures_latest"] == pytest.approx(7.0)
    assert result["free_cash_flow_latest"] == pytest.approx(28.0)
    assert result["research_and_development_latest"] == pytest.approx(12.0)
    assert result["selling_general_and_admin_latest"] == pytest.approx(9.0)
    assert result["diluted_eps_latest"] == pytest.approx(2.5)
    assert result["research_and_development_pct_revenue"] == pytest.approx(8.0)
    assert result["selling_general_and_admin_pct_revenue"] == pytest.approx(6.0)
    assert result["debt_to_assets_pct"] == pytest.approx(20.0)
    assert result["methods_used"] == [qms.METHOD_SEC_COMPANY_FACTS_SUMMARY]

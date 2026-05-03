import json
from types import SimpleNamespace

from langchain.agents.middleware.types import ModelResponse
from langchain_core.messages import AIMessage, ToolMessage

from agents.technical_writer.subagent import (
    TECHNICAL_WRITER_SUBAGENT,
    TechnicalWriterToolBoundaryMiddleware,
)
from agents.technical_writer.tools import plan_report_structure
from agents.technical_writer.tools import validate_research_report_file
from agents.technical_writer.tools import write_research_report


class _Runtime:
    context = SimpleNamespace(output_dir="")


class _Request:
    def __init__(self, tools, messages=None):
        self.tools = tools
        self.messages = messages or []

    def override(self, **kwargs):
        return _Request(
            kwargs.get("tools", self.tools),
            messages=kwargs.get("messages", self.messages),
        )


def test_plan_report_structure_infers_macro_for_fred_consumer_query(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text('{"consumer_sentiment": {"id": "consumer_sentiment"}}')

    result = json.loads(
        plan_report_structure.func(
            query_type="custom",
            charts_json_path=str(charts_path),
            execution_summary="{}",
            original_query=(
                "Are consumers under stress? Use FRED macro data to build "
                "a concise evidence-based answer."
            ),
            runtime=_Runtime(),
        )
    )

    assert result["query_type"] == "custom"
    assert result["chart_ids"] == ["consumer_sentiment"]
    assert "Macro Report" in result["general_rules"]
    assert "Equity Report" not in result["general_rules"]


def test_plan_report_structure_reads_chart_id_list_shape(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text(
        json.dumps(
            [
                {
                    "chart_id": "yield_curve_vs_recessions",
                    "chart_type": "Line",
                    "title": "Yield Curve",
                    "data": [{"date": "2020-01-31", "spread": -0.2}],
                }
            ]
        ),
        encoding="utf-8",
    )

    result = json.loads(
        plan_report_structure.func(
            query_type="macro_indicator",
            charts_json_path=str(charts_path),
            execution_summary="{}",
            original_query="Analyze recession signals using FRED.",
            runtime=_Runtime(),
        )
    )

    assert result["chart_ids"] == ["yield_curve_vs_recessions"]


def test_plan_report_structure_treats_prose_artifact_paths_as_missing(tmp_path):
    long_prose = (
        "Quantitative model output artifacts charts.json and execution_summary.json "
        "were not produced because the quant analysis did not complete successfully. "
        "The report will be written using only source metadata and explicit caveats. "
        "This is prose, not a filesystem path."
    )
    runtime = SimpleNamespace(context=SimpleNamespace(output_dir=str(tmp_path)))

    result = json.loads(
        plan_report_structure.func(
            query_type="macro_indicator",
            charts_json_path=long_prose,
            execution_summary=long_prose,
            original_query="Build base, upside, and downside scenarios.",
            runtime=runtime,
        )
    )

    assert result["chart_ids"] == []
    assert result["charts_json_path"] == str(tmp_path / "charts.json")
    assert result["execution_summary_for_draft"].startswith(
        "Quantitative model output artifacts"
    )


def test_plan_report_structure_reads_charts_object_list_shape(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text(
        json.dumps(
            {
                "charts": [
                    {
                        "id": "chart_1_unemployment_rate",
                        "type": "line",
                        "title": "Unemployment Rate",
                        "data": [{"date": "2026 Q1", "value": 4.1}],
                    },
                    {
                        "id": "chart_2_payroll_change",
                        "type": "bar",
                        "title": "Payroll Change",
                        "data": [{"date": "2026 Q1", "value": 125}],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    result = json.loads(
        plan_report_structure.func(
            query_type="macro_indicator",
            charts_json_path=str(charts_path),
            execution_summary="{}",
            original_query="Is the US labor market weakening? Use FRED.",
            runtime=_Runtime(),
        )
    )

    assert result["chart_ids"] == [
        "chart_1_unemployment_rate",
        "chart_2_payroll_change",
    ]


def test_plan_report_structure_surfaces_acceptance_headline_metrics(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text('{"chart_yield_curve": {"id": "chart_yield_curve"}}', encoding="utf-8")
    summary = {
        "statistical_summary": {
            "latest_unrate": 4.3,
            "latest_cpi_yoy": 3.12,
            "latest_yield_curve_bps": 52.1,
            "latest_composite_risk": 30.8,
            "current_regime": "Normal Expansion",
            "unrate_forecast_6m": 4.69,
            "aapl_revenue_cagr_2021_2025": 0.0328,
            "msft_revenue_cagr_2021_2025": 0.1378,
        }
    }

    result = json.loads(
        plan_report_structure.func(
            query_type="macro_indicator",
            charts_json_path=str(charts_path),
            execution_summary=json.dumps(summary),
            original_query="Assess recession risk, scenarios, Apple, and Microsoft.",
            runtime=_Runtime(),
        )
    )

    draft = result["execution_summary_for_draft"]
    assert "latest_unrate: 4.3" in draft
    assert "latest_cpi_yoy: 3.12" in draft
    assert "latest_yield_curve_bps: 52.1" in draft
    assert "latest_composite_risk: 30.8" in draft
    assert "unrate_forecast_6m: 4.69" in draft
    assert "aapl_revenue_cagr_2021_2025: 0.0328" in draft
    assert "Use ONLY those exact chart IDs" in result["general_rules"]


def test_plan_report_structure_preserves_nested_quant_acceptance_metrics(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text('{"recession_probability": {"id": "recession_probability"}}', encoding="utf-8")
    summary_path = tmp_path / "execution_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "statistical_summary": {
                    "latest_unemployment_rate": 4.3,
                    "latest_cpi_yoy": 3.1,
                    "latest_core_pce_yoy": 3.0,
                    "latest_yield_spread": 0.62,
                    "latest_fed_funds_rate": 3.64,
                    "recession_probability_current": 97.0,
                    "current_regime": "expansion",
                    "composite_indicator": {
                        "latest_index_value": 0.41,
                        "latest_percentile_0_100": 63.2,
                        "latest_signal": "elevated but below recession threshold",
                    },
                    "forecast_result": {
                        "model_spec": "ARX unemployment bridge",
                        "forecast_table": [
                            {"month": "2026-04", "forecast": 4.35, "lower_ci": 4.1, "upper_ci": 4.6},
                            {"month": "2026-05", "forecast": 4.39, "lower_ci": 4.1, "upper_ci": 4.7},
                        ],
                    },
                    "regime_result": {
                        "regime_label": "soft landing",
                        "regime_score": 0.58,
                        "score_momentum": -0.03,
                        "category_scores": {"labor": 0.2, "inflation": 0.6},
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    runtime = SimpleNamespace(context=SimpleNamespace(output_dir=str(tmp_path)))

    result = json.loads(
        plan_report_structure.func(
            query_type="macro_indicator",
            charts_json_path=str(charts_path),
            execution_summary=str(summary_path),
            original_query="Assess recession risk, unemployment, scenarios, and regime.",
            runtime=runtime,
        )
    )

    draft = result["execution_summary_for_draft"]
    assert "latest_unemployment_rate: 4.3" in draft
    assert "latest_yield_spread: 0.62" in draft
    assert "latest_fed_funds_rate: 3.64" in draft
    assert "recession_probability_current: 97" in draft
    assert "current_regime: expansion" in draft
    assert "latest_signal: elevated but below recession threshold" in draft
    assert "month=2026-04; forecast=4.35; lower_ci=4.1; upper_ci=4.6" in draft
    assert "regime: soft landing" in draft
    assert "regime_score: 0.58" in draft


def test_plan_report_structure_reads_job_local_execution_summary_path(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text('{"labor_chart": {"id": "labor_chart"}}', encoding="utf-8")
    summary_path = tmp_path / "execution_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "statistical_summary": (
                    "UNRATE averaged 4.8% in tight quarters and real wages rose "
                    "in 71% of those quarters, so gains were common but not consistent."
                )
            }
        ),
        encoding="utf-8",
    )
    runtime = SimpleNamespace(context=SimpleNamespace(output_dir=str(tmp_path)))

    result = json.loads(
        plan_report_structure.func(
            query_type="macro_indicator",
            charts_json_path=str(charts_path),
            execution_summary=str(summary_path),
            original_query="Analyze labor market tightness using FRED.",
            runtime=runtime,
        )
    )

    assert result["chart_ids"] == ["labor_chart"]
    assert "real wages rose in 71%" in result["execution_summary_for_draft"]


def test_plan_report_structure_exposes_nested_backtest_rows_and_errors(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text('{"macro_climate": {"id": "macro_climate"}}', encoding="utf-8")
    summary_path = tmp_path / "execution_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "backtest_summary": {
                    "method": "Rolling 12-quarter validation",
                    "aapl_macro_model": {"error": "Could not extract AAPL revenue"},
                    "aapl_naive_momentum": {"error": "Could not extract AAPL revenue"},
                    "recession_backtest": {
                        "2001": {
                            "unrate_change_pp": 1.2,
                            "indpro_change_pct": -3.45,
                            "real_pce_change_pct": 1.97,
                            "sentiment_decline_pts": -7.6,
                        },
                        "2020": {
                            "unrate_change_pp": 11.3,
                            "indpro_change_pct": -16.84,
                            "real_pce_change_pct": -9.89,
                            "sentiment_decline_pts": -11.8,
                        },
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    runtime = SimpleNamespace(context=SimpleNamespace(output_dir=str(tmp_path)))

    result = json.loads(
        plan_report_structure.func(
            query_type="macro_indicator",
            charts_json_path=str(charts_path),
            execution_summary=str(summary_path),
            original_query=(
                "Compare current macro conditions with prior cycles and naive models."
            ),
            runtime=runtime,
        )
    )

    draft = result["execution_summary_for_draft"]
    assert "do not fabricate RMSE" in draft
    assert "aapl_macro_model: error=Could not extract AAPL revenue" in draft
    assert "aapl_naive_momentum: error=Could not extract AAPL revenue" in draft
    assert "2001: unrate_change_pp=1.2" in draft
    assert "sentiment_decline_pts=-7.6" in draft
    assert "2020: unrate_change_pp=11.3" in draft
    assert "indpro_change_pct=-16.84" in draft


def test_plan_report_structure_preserves_regional_state_context(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text('{"composite_risk": {"id": "composite_risk"}}', encoding="utf-8")
    summary_path = tmp_path / "execution_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "regional_top10": [
                    {"state": "California", "pop": 39242785, "med_inc": 96334, "pct_nat": 128.0},
                    {"state": "Texas", "pop": 29640343, "med_inc": 76292, "pct_nat": 101.4},
                    {"state": "Illinois", "pop": 12692653, "med_inc": 81702, "pct_nat": 108.5},
                ],
                "statistical_summary": "Composite score 43.9/100.",
            }
        ),
        encoding="utf-8",
    )
    runtime = SimpleNamespace(context=SimpleNamespace(output_dir=str(tmp_path)))

    result = json.loads(
        plan_report_structure.func(
            query_type="macro_indicator",
            charts_json_path=str(charts_path),
            execution_summary=str(summary_path),
            original_query="Assess recession risk and regional consumer conditions.",
            runtime=runtime,
        )
    )

    draft = result["execution_summary_for_draft"]
    assert "Exact regional state consumer context from execution_summary.json" in draft
    assert "California: population=39242785, median_income=96334, pct_of_national_median=128.0%" in draft
    assert "Texas: population=29640343, median_income=76292, pct_of_national_median=101.4%" in draft
    assert "Illinois: population=12692653, median_income=81702, pct_of_national_median=108.5%" in draft
    assert "do not estimate or round them differently" in draft


def test_plan_report_structure_summarizes_source_context_files(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text('{"macro_chart": {"id": "macro_chart"}}', encoding="utf-8")

    data_dir = tmp_path / "source_data"
    data_dir.mkdir(parents=True)
    worldbank_path = data_dir / "worldbank_ny_gdp_mktp_kd_zg_usa_can_deu_improver.csv"
    worldbank_path.write_text(
        "\n".join(
            [
                "country_code,country_name,indicator_id,indicator_name,year,value,units,frequency,source",
                "USA,United States,NY.GDP.MKTP.KD.ZG,GDP growth (annual %),2023,2.9,annual percent change,annual,World Bank Indicators API",
                "USA,United States,NY.GDP.MKTP.KD.ZG,GDP growth (annual %),2024,2.5,annual percent change,annual,World Bank Indicators API",
                "DEU,Germany,NY.GDP.MKTP.KD.ZG,GDP growth (annual %),2024,-0.2,annual percent change,annual,World Bank Indicators API",
            ]
        ),
        encoding="utf-8",
    )
    census_path = data_dir / "census_2023_acs_acs5_profile_state_improver.csv"
    census_path.write_text(
        "\n".join(
            [
                "NAME,DP05_0001E,DP03_0062E,DP04_0001E,DP04_0089E,state",
                "California,39242785,96334,14532683,695400,06",
                "Texas,30503301,76728,12100000,302200,48",
                "Ohio,11800000,69000,5000000,230000,39",
            ]
        ),
        encoding="utf-8",
    )
    sec_path = data_dir / "AAPL_sec_edgar_company_facts_improver.csv"
    sec_path.write_text(
        "\n".join(
            [
                "fiscal_year,revenue,net_income,assets,liabilities,shares",
                "2024,391035000000,93736000000,364980000000,308030000000,15408095000",
                "2025,416161000000,112010000000,359241000000,285508000000,15004697000",
            ]
        ),
        encoding="utf-8",
    )
    summary_path = tmp_path / "execution_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "statistical_summary": "Macro model completed.",
                "source_context_files": [
                    str(worldbank_path),
                    str(census_path),
                    str(sec_path),
                ],
            }
        ),
        encoding="utf-8",
    )
    runtime = SimpleNamespace(context=SimpleNamespace(output_dir=str(tmp_path)))

    result = json.loads(
        plan_report_structure.func(
            query_type="macro_indicator",
            charts_json_path=str(charts_path),
            execution_summary=str(summary_path),
            original_query=(
                "Compare US peers, regional consumer conditions, and Apple earnings risk."
            ),
            runtime=runtime,
        )
    )

    draft = result["execution_summary_for_draft"]
    assert "Exact supplemental source-context values from saved public-data CSVs" in draft
    assert "World Bank GDP growth (annual %): USA 2024=2.5; DEU 2024=-0.2" in draft
    assert "Census ACS California: population=39242785, median_income=96334" in draft
    assert "Census ACS Texas: population=30503301, median_income=76728" in draft
    assert "SEC EDGAR AAPL latest: fiscal_year=2025, revenue=416161000000" in draft


def test_plan_report_structure_surfaces_full_research_acceptance_metrics(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text('{"recession-risk": {"id": "recession-risk"}}', encoding="utf-8")
    summary_path = tmp_path / "execution_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "recession_risk_index": {
                    "current_score": 1.7898878189766174,
                    "current_classification": "High",
                    "composite_full": {
                        "latest_percentile_0_100": 100.0,
                        "latest_signal": "high",
                        "latest_feature_values": {
                            "UMCSENT": 53.3,
                            "INDPRO_chg_pct": 0.6545176949190212,
                        },
                        "backtest_summary": {
                            "metrics": {"precision": 0.1441860465, "recall": 1.0}
                        },
                    },
                },
                "unemployment_forecast": {
                    "current_unemployment": 4.3,
                    "forecast_months": [
                        {
                            "date": "2026-10-01",
                            "value": 4.36,
                            "lower_ci": 4.09,
                            "upper_ci": 4.64,
                        }
                    ],
                },
                "regime_classification": {
                    "regime": "expansion",
                    "category_scores": {"labor": 1.0, "consumption": -1.0},
                    "evidence_table": [
                        {
                            "category": "financial",
                            "indicator": "Yield Curve",
                            "value": 0.52,
                            "score": 1.0,
                            "signal": "supportive",
                        }
                    ],
                },
                "consumer_stress": {
                    "real_ahe_yoy_pct": 0.03,
                    "saving_rate": 3.6,
                    "delinquency_rate": 2.62,
                    "regional_context": {
                        "weighted_national_median": 79504.0,
                        "top_states": [
                            {
                                "state": "California",
                                "population": 39242785,
                                "median_income": 96334,
                            }
                        ],
                    },
                },
                "international_comparison": {
                    "latest_year": 2024,
                    "table": [
                        {"country": "USA", "gdp_growth": 2.79, "inflation": 2.95},
                        {"country": "DEU", "gdp_growth": -0.5, "inflation": 2.26},
                    ],
                },
                "apple_msft_earnings": {
                    "AAPL": [
                        {
                            "fiscal_year": 2025,
                            "revenue_growth_pct": 6.4,
                            "net_income_growth_pct": 19.5,
                            "margin_pct": 26.9,
                        }
                    ],
                    "MSFT": [
                        {
                            "fiscal_year": 2025,
                            "revenue_growth_pct": 14.9,
                            "net_income_growth_pct": 15.5,
                            "margin_pct": 36.1,
                        }
                    ],
                },
                "statistical_summary": {
                    "all_values": {
                        "UNRATE": {"latest": 4.3, "latest_date": "2026-04-01"},
                        "FEDFUNDS": {"latest": 3.64, "latest_date": "2026-04-01"},
                    },
                    "key_ratios": {"core_cpi": 2.4, "spread": 0.52},
                },
            }
        ),
        encoding="utf-8",
    )
    runtime = SimpleNamespace(context=SimpleNamespace(output_dir=str(tmp_path)))

    result = json.loads(
        plan_report_structure.func(
            query_type="macro_indicator",
            charts_json_path=str(charts_path),
            execution_summary=str(summary_path),
            original_query="Assess recession risk, scenarios, Apple, Microsoft, and peers.",
            runtime=runtime,
        )
    )

    draft = result["execution_summary_for_draft"]
    assert "Exact recession-risk framework values" in draft
    assert "current_score: 1.79" in draft
    assert "UMCSENT=53.3" in draft
    assert "forecast_months: date=2026-10-01; value=4.36" in draft
    assert "regime: expansion" in draft
    assert "real_ahe_yoy_pct: 0.03" in draft
    assert "California: population=39242785, median_income=96334" in draft
    assert "DEU: gdp_growth=-0.5, inflation=2.26" in draft
    assert "AAPL latest: fiscal_year=2025, revenue_growth_pct=6.4" in draft
    assert "MSFT latest: fiscal_year=2025, revenue_growth_pct=14.9" in draft
    assert "UNRATE.latest: 4.3 (2026-04-01)" in draft
    assert "FEDFUNDS.latest: 3.64 (2026-04-01)" in draft


def test_plan_report_structure_preserves_sec_fundamental_endpoints(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text('{"apple_revenue": {"id": "apple_revenue"}}', encoding="utf-8")
    summary_path = tmp_path / "execution_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "apple_financials_by_year": {
                    "2016": {
                        "fiscal_year": 2016,
                        "revenue": 215.639,
                        "net_income": 45.687,
                        "total_assets": 321.686,
                        "total_liabilities": 193.437,
                        "shares_outstanding": 5.5003,
                    },
                    "2025": {
                        "fiscal_year": 2025,
                        "revenue": 416.161,
                        "net_income": 112.01,
                        "total_assets": 359.241,
                        "total_liabilities": 285.508,
                        "shares_outstanding": 15.0047,
                    },
                },
                "summary_stats": {
                    "revenue_billions": {
                        "mean": 319.58,
                        "max": 416.16,
                        "min": 215.64,
                        "latest": 416.16,
                        "count": 10,
                    }
                },
                "correlations": {
                    "revenue_vs_cpi": {
                        "pearson_r": 0.6499,
                        "p_value": 0.041954,
                        "n": 10,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    runtime = SimpleNamespace(context=SimpleNamespace(output_dir=str(tmp_path)))

    result = json.loads(
        plan_report_structure.func(
            query_type="correlation_analysis",
            charts_json_path=str(charts_path),
            execution_summary=str(summary_path),
            original_query=(
                "Compare Apple's revenue, net income, assets, liabilities, and "
                "share count trend from SEC filings against inflation."
            ),
            runtime=runtime,
        )
    )

    draft = result["execution_summary_for_draft"]
    assert "Exact annual series endpoints from execution_summary.json" in draft
    assert "Revenue: 2016=215.6, 2025=416.2, change=200.5, CAGR=7.58%" in draft
    assert "Total Assets: 2016=321.7, 2025=359.2, change=37.56" in draft
    assert "Shares Outstanding: 2016=5.5, 2025=15, change=9.504" in draft
    assert "revenue_billions: mean=319.6, max=416.2" in draft
    assert "revenue_vs_cpi: pearson_r=0.6499, p_value=0.04195" in draft


def test_plan_report_structure_caveats_correlation_tables_without_diagnostics(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text('{"macro_sensitivity": {"id": "macro_sensitivity"}}', encoding="utf-8")
    summary_path = tmp_path / "execution_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "statistical_summary": {
                    "revenue_trend": {
                        "peak_fy": 2025,
                        "peak_revenue_b": 130.497,
                    },
                    "macro_correlation": {
                        "dgs10_r": 0.597,
                        "fedfunds_r": 0.432,
                        "unrate_r": -0.495,
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    runtime = SimpleNamespace(context=SimpleNamespace(output_dir=str(tmp_path)))

    result = json.loads(
        plan_report_structure.func(
            query_type="earnings_analysis",
            charts_json_path=str(charts_path),
            execution_summary=str(summary_path),
            original_query=(
                "Prepare a stock-specific report on NVIDIA and macro sensitivity "
                "using SEC filings and public macro data."
            ),
            runtime=runtime,
        )
    )

    draft = result["execution_summary_for_draft"]
    assert "macro_correlation: dgs10_r=0.597" in draft
    assert "fedfunds_r=0.432" in draft
    assert "evidence_caveat=exploratory correlation only" in draft
    assert "sample size and p-values were not reported" in draft


def test_plan_report_structure_prioritizes_exact_lead_lag_metrics(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text(
        '{"cross_corr_indpro": {"id": "cross_corr_indpro"}}',
        encoding="utf-8",
    )
    summary_path = tmp_path / "execution_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "lead_lag_analysis": {
                    "unemployment": {
                        "best_lag": -20,
                        "best_correlation": 0.4237,
                        "best_p_value": 0.0,
                        "best_nobs": 395,
                        "significant_lags_count": 41,
                    },
                    "industrial_production": {
                        "best_lag": -19,
                        "best_correlation": -0.3159,
                        "best_p_value": 0.0,
                        "best_nobs": 396,
                        "significant_lags_count": 43,
                    },
                },
                "statistical_summary": (
                    "Use lag tests, rolling correlations, and recession-window "
                    "summaries to answer the macro lead-lag question."
                ),
                "methods_used": [
                    "rolling_pearson_correlation",
                    "lead_lag_pearson_correlation",
                    "recession_window_summary",
                ],
            }
        ),
        encoding="utf-8",
    )
    runtime = SimpleNamespace(context=SimpleNamespace(output_dir=str(tmp_path)))

    result = json.loads(
        plan_report_structure.func(
            query_type="macro_indicator",
            charts_json_path=str(charts_path),
            execution_summary=str(summary_path),
            original_query=(
                "Analyze whether the 10-year minus 3-month yield spread leads "
                "unemployment and industrial production."
            ),
            runtime=runtime,
        )
    )

    draft = result["execution_summary_for_draft"]
    assert draft.startswith("Exact lead-lag metrics from execution_summary.json")
    assert "negative best_lag_months means the predictor leads the target" in draft
    assert "unemployment: best_lag_months=-20, best_correlation=0.4237" in draft
    assert (
        "industrial_production: best_lag_months=-19, best_correlation=-0.3159"
        in draft
    )
    assert "lead_lag_pearson_correlation" in draft


def test_plan_report_structure_preserves_nested_macro_lead_lag_findings(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text(
        '{"cross_corr_lags": {"id": "cross_corr_lags"}}',
        encoding="utf-8",
    )
    summary_path = tmp_path / "execution_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "statistical_summary": {
                    "descriptive_stats": {
                        "T10Y3M": {"mean": 1.536, "latest": 0.53},
                        "UNRATE": {"mean": 5.866, "latest": 4.3},
                    },
                    "lead_correlations": {
                        "spread_to_unr_chg_12m_lead": {
                            "r": -0.2202,
                            "p_value": 0.000001,
                        },
                        "spread_to_indpro_yoy_12m_lead": {
                            "r": 0.23,
                            "p_value": 0.0,
                        },
                    },
                    "cross_correlation_peak_lags": {
                        "UNRATE_chg": {"peak_lag_months": -21, "peak_r": 0.3816},
                        "INDPRO_yoy": {"peak_lag_months": -22, "peak_r": -0.2861},
                    },
                    "rolling_correlations_latest": {
                        "roll_corr_unr_12": -0.4206,
                        "roll_corr_ind_12": 0.2158,
                    },
                    "recession_summaries": [
                        {
                            "recession_start": "2008-01-01",
                            "recession_end": "2009-06-01",
                            "duration_months": 18,
                            "lead_time_months_from_first_inversion": 12,
                            "unr_change_during_recession": 4.5,
                            "indpro_yoy_avg_during": -7.08,
                        }
                    ],
                },
                "methods_used": [
                    "Cross-correlation analysis across lags -24 to +24 months",
                    "Recession window analysis",
                ],
                "caveats": [
                    "Correlation vs. causation.",
                    "Forward leads reduce effective sample size.",
                ],
            }
        ),
        encoding="utf-8",
    )
    runtime = SimpleNamespace(context=SimpleNamespace(output_dir=str(tmp_path)))

    result = json.loads(
        plan_report_structure.func(
            query_type="macro_indicator",
            charts_json_path=str(charts_path),
            execution_summary=str(summary_path),
            original_query=(
                "Analyze whether the 10-year minus 3-month yield spread leads "
                "unemployment and industrial production."
            ),
            runtime=runtime,
        )
    )

    draft = result["execution_summary_for_draft"]
    assert "Exact cross-correlation peak lags from execution_summary.json" in draft
    assert "UNRATE_chg: peak_lag_months=-21, peak_r=0.3816" in draft
    assert "INDPRO_yoy: peak_lag_months=-22, peak_r=-0.2861" in draft
    assert "spread_to_unr_chg_12m_lead: r=-0.2202" in draft
    assert "roll_corr_unr_12: -0.4206" in draft
    assert "2008-01-01 to 2009-06-01" in draft
    assert "lead_time_months_from_first_inversion=12" in draft
    assert "Cross-correlation analysis across lags -24 to +24 months" in draft
    assert "Forward leads reduce effective sample size." in draft


def test_plan_report_structure_preserves_general_local_analysis_findings(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text(
        '{"consumer-stress-macro": {"id": "consumer-stress-macro"}}',
        encoding="utf-8",
    )
    summary_path = tmp_path / "execution_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "macro_series_stats": [
                    {
                        "series": "DRCCLACBS (%)",
                        "latest": 2.94,
                        "mean": 3.43,
                        "stress_signal": "low",
                    }
                ],
                "state_housing_affordability": {
                    "top5_most_stressed_low_income_to_value": [
                        {
                            "state_name": "Hawaii",
                            "income_to_value_ratio": 0.1216,
                        }
                    ],
                    "national_median_value_to_income_multiple": 3.717,
                },
                "correlation_matrix": {
                    "notable_correlations": [
                        "UNRATE vs DRCCLACBS: r=0.350",
                    ]
                },
                "real_income_contractions": {
                    "count": 34,
                    "note": "Periods where real disposable income YoY growth was negative.",
                },
                "key_narrative_points": [
                    "Latest DRCCLACBS: 2.94% vs historical mean 3.43%",
                    "Most stressed state (lowest income-to-value): Hawaii (0.1216)",
                ],
                "methods_used": ["Pearson correlation on monthly-aligned panel"],
            }
        ),
        encoding="utf-8",
    )
    runtime = SimpleNamespace(context=SimpleNamespace(output_dir=str(tmp_path)))

    result = json.loads(
        plan_report_structure.func(
            query_type="macro_indicator",
            charts_json_path=str(charts_path),
            execution_summary=str(summary_path),
            original_query="Are US consumers under stress regionally?",
            runtime=runtime,
        )
    )

    draft = result["execution_summary_for_draft"]
    assert "Key computed findings from execution_summary.json" in draft
    assert "Latest DRCCLACBS: 2.94% vs historical mean 3.43%" in draft
    assert "DRCCLACBS (%): latest=2.94, mean=3.43, signal=low" in draft
    assert "Most stressed states: Hawaii income/value=0.1216" in draft
    assert "national median value/income: 3.717" in draft
    assert "UNRATE vs DRCCLACBS: r=0.350" in draft
    assert "count: 34" in draft


def test_plan_report_structure_accepts_large_inline_execution_summary_json(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text('{"macro_chart": {"id": "macro_chart"}}', encoding="utf-8")
    summary_text = "Soft landing evidence: inflation cooled while output stayed positive. " * 80
    runtime = SimpleNamespace(context=SimpleNamespace(output_dir=str(tmp_path)))

    result = json.loads(
        plan_report_structure.func(
            query_type="macro_indicator",
            charts_json_path=str(charts_path),
            execution_summary=json.dumps(
                {
                    "analysis_goal": "Classify the US landing pattern",
                    "statistical_summary": summary_text,
                    "nested": {"labor": {"series": "UNRATE"}},
                }
            ),
            original_query="Investigate soft landing versus hard landing using FRED.",
            runtime=runtime,
        )
    )

    assert result["chart_ids"] == ["macro_chart"]
    assert result["execution_summary_for_draft"].startswith("Soft landing evidence")
    assert len(result["execution_summary_for_draft"]) == 4000


def test_plan_report_structure_preserves_top_level_composite_backtest_diagnostics(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text('{"recession_risk": {"id": "recession_risk"}}', encoding="utf-8")
    summary_path = tmp_path / "execution_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "composite_predictive_indicator": {
                    "latest_index_value": -3.22,
                    "latest_percentile_0_100": 0.0,
                    "latest_signal": "low",
                    "backtest_summary": {
                        "status": "ok",
                        "test_window": {"start": "1974-11-01", "end": "2026-03-01"},
                        "metrics": {
                            "accuracy": 0.8898,
                            "precision": 0.25,
                            "recall": 0.0484,
                            "false_negative": 59,
                        },
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    runtime = SimpleNamespace(context=SimpleNamespace(output_dir=str(tmp_path)))

    result = json.loads(
        plan_report_structure.func(
            query_type="macro_indicator",
            charts_json_path=str(charts_path),
            execution_summary=str(summary_path),
            original_query="Assess recession risk and explain uncertainty.",
            runtime=runtime,
        )
    )

    draft = result["execution_summary_for_draft"]
    assert "Exact recession-risk framework values" in draft
    assert "latest_index_value: -3.22" in draft
    assert "backtest_window: 1974-11-01 to 2026-03-01" in draft
    assert "precision=0.25" in draft
    assert "recall=0.0484" in draft
    assert "false_negative=59" in draft


def test_plan_report_structure_requires_scenario_section_for_scenario_query(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text("{}", encoding="utf-8")

    result = json.loads(
        plan_report_structure.func(
            query_type="macro_indicator",
            charts_json_path=str(charts_path),
            execution_summary=json.dumps(
                {
                    "scenario_table": [
                        {
                            "scenario": "base",
                            "assumptions": ["Slower growth"],
                            "indicator_triggers": ["Claims stable"],
                            "confidence": "medium",
                            "uncertainty_notes": "Revision risk.",
                        },
                        {
                            "scenario": "bull",
                            "assumptions": ["Inflation cools"],
                            "indicator_triggers": ["Spreads narrow"],
                            "confidence": "low",
                            "uncertainty_notes": "Policy lags.",
                        },
                        {
                            "scenario": "bear",
                            "assumptions": ["Labor cracks"],
                            "indicator_triggers": ["Claims jump"],
                            "confidence": "medium",
                            "uncertainty_notes": "Timing risk.",
                        },
                    ]
                }
            ),
            original_query="Build a recession risk dashboard with base, bull, and bear scenarios.",
            runtime=_Runtime(),
        )
    )

    assert "MUST include a `## Scenario Table` section" in result["general_rules"]
    assert "| Scenario | Assumptions | Indicator Triggers | Confidence | Uncertainty Notes |" in result["general_rules"]
    assert "`| base |`, `| bull |`, and `| bear |`" in result["general_rules"]
    assert "Required scenario table from execution_summary.json" in result["execution_summary_for_draft"]
    assert "- bear:" in result["execution_summary_for_draft"]


def test_plan_report_structure_prioritizes_signal_framework_backtest_values(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text("{}", encoding="utf-8")

    result = json.loads(
        plan_report_structure.func(
            query_type="macro_indicator",
            charts_json_path=str(charts_path),
            execution_summary=json.dumps(
                {
                    "composite_indicator": {
                        "latest_index_value": 0.06182,
                        "latest_percentile_0_100": 83.29,
                        "latest_signal": "high",
                        "backtest_summary": {
                            "metrics": {
                                "precision": 0.01887,
                                "recall": 0.5,
                                "false_positive": 52,
                            }
                        },
                    },
                    "signal_framework_summary": {
                        "observations": 532,
                        "recession_count": 5,
                        "recession_calls_correct": 3,
                        "false_alarms": 9,
                        "true_positive_rate": 0.6,
                        "precision": 0.25,
                        "threshold": 2,
                        "current_signal": {
                            "score": 1,
                            "interpretation": "yellow",
                            "components_triggered": ["SIG_UM"],
                        },
                        "pre_recession_scores": {
                            "2008_recession_12m_before": {
                                "score": 2,
                                "components_triggered": ["SIG_T10", "SIG_IC"],
                                "max_score_date": "2007-01-01",
                            }
                        },
                        "false_alarm_episodes": [
                            {
                                "period": "2022-2023",
                                "max_score": 2,
                                "components_at_peak": ["SIG_T10", "SIG_UM"],
                            }
                        ],
                    },
                }
            ),
            original_query=(
                "Build a recession-risk report showing what a simple signal stack "
                "said before downturns and how often it cried wolf."
            ),
            runtime=_Runtime(),
        )
    )

    draft = result["execution_summary_for_draft"]
    assert "Controlling signal-framework backtest values" in draft
    assert "use these values instead of unrelated composite-index percentile" in draft
    assert "recession_calls_correct=3" in draft
    assert "false_alarms=9" in draft
    assert "precision=0.25" in draft
    assert "current_signal: score=1" in draft
    assert "2022-2023: max_score=2" in draft


def test_plan_report_structure_derives_scenario_table_from_scenario_results(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text("{}", encoding="utf-8")

    result = json.loads(
        plan_report_structure.func(
            query_type="macro_indicator",
            charts_json_path=str(charts_path),
            execution_summary=json.dumps(
                {
                    "scenario_results": {
                        "base": "NONE",
                        "upside": "NONE",
                        "downside": "MEDIUM",
                        "detail": {
                            "base": {"level": "NONE", "sum": 0, "YC": 0, "LR": 0, "FS": 0},
                            "upside": {"level": "NONE", "sum": 0, "YC": 0, "LR": 0, "FS": 0},
                            "downside": {"level": "MEDIUM", "sum": 2, "YC": 0, "LR": 1, "FS": 1},
                        },
                    }
                }
            ),
            original_query=(
                "Build a recession-risk report showing how the conclusion changes "
                "under base, upside, and downside cases."
            ),
            runtime=_Runtime(),
        )
    )

    draft = result["execution_summary_for_draft"]
    assert "Required scenario table from execution_summary.json" in draft
    assert "- base:" in draft
    assert "- bull:" in draft
    assert "- bear:" in draft
    assert "Level: MEDIUM" in draft
    assert "Lr: 1" in draft


def test_plan_report_structure_preserves_all_signal_framework_recession_rows(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text("{}", encoding="utf-8")
    pre_scores = {
        f"{year}_recession_12m_before": {
            "score": 1 if year == 2020 else 0,
            "components_triggered": ["YC_inv"] if year == 2020 else [],
            "max_score_date": "2019-08-31" if year == 2020 else f"{year}-01-31",
        }
        for year in (1960, 1970, 1973, 1980, 1981, 1990, 2001, 2008, 2020)
    }

    result = json.loads(
        plan_report_structure.func(
            query_type="macro_indicator",
            charts_json_path=str(charts_path),
            execution_summary=json.dumps(
                {
                    "signal_framework_summary": {
                        "observations": 233278,
                        "recession_count": 9,
                        "recession_calls_correct": 2,
                        "false_alarms": 7,
                        "precision": 0.2222222222,
                        "threshold": 2,
                        "pre_recession_scores": pre_scores,
                    }
                }
            ),
            original_query=(
                "Build a recession-risk report showing what a simple signal stack "
                "said before earlier downturns and how often it cried wolf."
            ),
            runtime=_Runtime(),
        )
    )

    draft = result["execution_summary_for_draft"]
    assert "`recession_count` is the total number of recessions tested" in draft
    assert "`recession_calls_correct` is the number that reached the alert threshold" in draft
    assert "recession_count=9" in draft
    assert "recession_calls_correct=2" in draft
    assert "2020_recession_12m_before: score=1" in draft
    assert "components_triggered=['YC_inv']" in draft


def test_plan_report_structure_preserves_regime_classifier_fields(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text("{}", encoding="utf-8")

    result = json.loads(
        plan_report_structure.func(
            query_type="macro_indicator",
            charts_json_path=str(charts_path),
            execution_summary=json.dumps(
                {
                    "regime_label": "slowdown",
                    "regime_score": -0.31,
                    "category_scores": {"rates": -0.6, "labor": -0.2, "output": 0.1},
                    "evidence_table": [
                        {
                            "category": "rates",
                            "indicator": "yield_curve",
                            "value": -0.4,
                            "score": -0.8,
                            "rationale": "Curve inversion is a slowdown signal.",
                        }
                    ],
                    "historical_analogs": [
                        {"date": "2001-02-28", "label": "slowdown", "regime_score": -0.29}
                    ],
                    "missing_indicators": [],
                    "false_positive_caveat": "False positives can occur around noisy data revisions.",
                    "methods_used": ["recession_regime_classifier"],
                }
            ),
            original_query="Classify the current US macro regime as expansion, slowdown, recession, recovery, or reacceleration.",
            runtime=_Runtime(),
        )
    )

    draft = result["execution_summary_for_draft"]
    assert "Required regime-classifier fields" in draft
    assert "regime_label: slowdown" in draft
    assert "evidence_table" in draft
    assert "historical_analogs" in draft
    assert "false_positive_caveat" in draft


def test_plan_report_structure_preserves_econometric_validation_and_simulations(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text("{}", encoding="utf-8")

    result = json.loads(
        plan_report_structure.func(
            query_type="macro_indicator",
            charts_json_path=str(charts_path),
            execution_summary=json.dumps(
                {
                    "backtest_summary": {
                        "status": "ok",
                        "horizon_results": [
                            {
                                "prediction_horizon": 1,
                                "test_observations": 18,
                                "metrics": {"mae": 0.12, "rmse": 0.18},
                                "baseline_comparison": {
                                    "last_value": {"mae": 0.2},
                                    "train_mean": {"mae": 0.5},
                                },
                                "best_model_by_mae": "direct_ols",
                            }
                        ],
                    },
                    "model_comparison": [
                        {"horizon": 1, "model": "direct_ols", "mae": 0.12},
                        {"horizon": 1, "model": "baseline_last_value", "mae": 0.2},
                    ],
                    "historical_simulations": [
                        {
                            "label": "global financial crisis",
                            "start": "2007-12-01",
                            "end": "2009-06-01",
                            "status": "ok",
                            "outcome_during_window": {"max": 10.0},
                            "subsequent_outcome": {"periods": 6, "max": 9.5},
                        }
                    ],
                    "methods_used": ["direct_ols_forecast", "walk_forward_ols_backtest"],
                }
            ),
            original_query=(
                "Build an econometric forecast with backtesting and historical simulations."
            ),
            runtime=_Runtime(),
        )
    )

    draft = result["execution_summary_for_draft"]
    assert "Required econometric validation" in draft
    assert "last_value_mae=0.2" in draft
    assert "Exact model comparison rows" in draft
    assert "Required historical simulation/replay rows" in draft
    assert "global financial crisis" in draft


def test_plan_report_structure_surfaces_nested_what_happened_next_replay_limits(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text("{}", encoding="utf-8")

    result = json.loads(
        plan_report_structure.func(
            query_type="macro_indicator",
            charts_json_path=str(charts_path),
            execution_summary=json.dumps(
                {
                    "what_happened_next": {
                        "simulation_design": {
                            "outcome_variable": "USREC",
                            "signal_variables": ["yield_slope", "BAA10Y_spread"],
                            "lookahead_periods": 12,
                        },
                        "historical_simulations": [
                            {
                                "label": "global financial crisis",
                                "start": "2007-12-01",
                                "end": "2009-06-01",
                                "status": "ok",
                                "outcome_during_window": {"max": 1.0, "mean": 0.95},
                                "subsequent_outcome": {"periods": 12, "max": 0.0},
                            }
                        ],
                    }
                }
            ),
            original_query="Explain what happened next in prior cycle windows.",
            runtime=_Runtime(),
        )
    )

    draft = result["execution_summary_for_draft"]
    assert "Exact what-happened-next replay design" in draft
    assert "outcome_variable=USREC" in draft
    assert "Do not invent S&P 500" in draft
    assert "USREC_during_max=1.0" in draft
    assert "USREC_subsequent_periods=12" in draft


def test_plan_report_structure_preserves_dict_backtest_model_and_simulation_metrics(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text("{}", encoding="utf-8")

    result = json.loads(
        plan_report_structure.func(
            query_type="macro_indicator",
            charts_json_path=str(charts_path),
            execution_summary=json.dumps(
                {
                    "backtest_summary": {
                        "years": {
                            "2020": {"auc": 0.2, "brier_score": 0.417},
                            "2024": {"auc": 0.5, "brier_score": 0.0023},
                        },
                        "average_auc": 0.478,
                        "average_brier_score": 0.0664,
                        "calibration": {
                            "mean_predicted_prob": 0.1022,
                            "actual_recession_freq": 0.0933,
                        },
                        "method": "Rolling OOS logistic regression",
                    },
                    "model_comparison": {
                        "logistic_regression": {
                            "accuracy": 0.9432,
                            "precision": 0.7857,
                            "recall": 0.569,
                            "f1_score": 0.66,
                            "auc": 0.3685,
                        },
                        "yield_curve_benchmark": {
                            "accuracy": 0.7746,
                            "precision": 0.1111,
                            "recall": 0.1897,
                            "f1_score": 0.1401,
                            "auc": 0.3685,
                        },
                    },
                    "historical_simulations": {
                        "analog_count": 10,
                        "analog_dates": ["2003-10-01", "1981-09-01"],
                        "forward_horizons": {
                            "3m": {
                                "mean_unrate_change": 0.22,
                                "pct_recession": 40,
                            },
                            "12m": {
                                "mean_unrate_change": 1.42,
                                "pct_recession": 50,
                            },
                        },
                        "method": "Top-10 nearest neighbors on 4 features",
                    },
                }
            ),
            original_query=(
                "Compare today's macro mix to prior cycle windows with diagnostics, "
                "backtest evidence, and historical simulation evidence."
            ),
            runtime=_Runtime(),
        )
    )

    draft = result["execution_summary_for_draft"]
    assert "average_auc=0.478" in draft
    assert "average_brier_score=0.0664" in draft
    assert "2020: auc=0.2, brier_score=0.417" in draft
    assert "model=logistic_regression" in draft
    assert "accuracy=0.9432" in draft
    assert "model=yield_curve_benchmark" in draft
    assert "f1_score=0.1401" in draft
    assert "analog_count: 10" in draft
    assert "analog_dates: 2003-10-01; 1981-09-01" in draft
    assert "horizon=12m, mean_unrate_change=1.42, pct_recession=50" in draft


def test_plan_report_structure_preserves_backtest_z_score_tables(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text("{}", encoding="utf-8")

    result = json.loads(
        plan_report_structure.func(
            query_type="macro_indicator",
            charts_json_path=str(charts_path),
            execution_summary=json.dumps(
                {
                    "backtest_summary": {
                        "method": "euclidean_z_distance",
                        "current_z_scores": {
                            "UNRATE": -0.8627,
                            "FEDFUNDS": -0.1479,
                            "CPIAUCSL": None,
                        },
                        "pre_recession_avg_z_scores": {
                            "UNRATE": -1.0098,
                            "FEDFUNDS": -0.0235,
                            "CPIAUCSL": None,
                        },
                    },
                    "historical_simulations": {
                        "method": "current_vs_historical_regime_replay",
                        "current_values": {"UNRATE": 4.3333, "FEDFUNDS": 3.9825},
                        "pre_recession_values": {"UNRATE": 4.0833, "FEDFUNDS": 4.4178},
                    },
                }
            ),
            original_query="Use historical replay and be explicit about backtest limits.",
            runtime=_Runtime(),
        )
    )

    draft = result["execution_summary_for_draft"]
    assert "current_z_scores: UNRATE=-0.8627; FEDFUNDS=-0.1479; CPIAUCSL=null" in draft
    assert "pre_recession_avg_z_scores: UNRATE=-1.0098; FEDFUNDS=-0.0235" in draft
    assert "simulation_current_values: UNRATE=4.3333; FEDFUNDS=3.9825" in draft
    assert "simulation_pre_recession_values: UNRATE=4.0833; FEDFUNDS=4.4178" in draft


def test_plan_report_structure_surfaces_headline_scalar_metrics_first(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text("{}", encoding="utf-8")

    result = json.loads(
        plan_report_structure.func(
            query_type="macro_indicator",
            charts_json_path=str(charts_path),
            execution_summary=json.dumps(
                {
                    "statistical_summary": {
                        "unemployment_current": 4.3,
                        "cpi_yoy": 3.32,
                        "yield_curve_10y3m": 0.62,
                    },
                    "regime_classification": "Late Cycle",
                    "rri_current_value": 40.4,
                    "sahm_triggered": False,
                    "real_fed_funds_rate": 0.32,
                    "taylor_rule_implied_rate": 4.91,
                    "key_narrative_points": ["Soft landing remains the base case."],
                }
            ),
            original_query="Build an investment committee recession-risk report with scenarios.",
            runtime=_Runtime(),
        )
    )

    draft = result["execution_summary_for_draft"]
    assert draft.startswith("Exact headline metrics from execution_summary.json")
    assert "- unemployment_current: 4.3" in draft
    assert "- cpi_yoy: 3.32" in draft
    assert "- yield_curve_10y3m: 0.62" in draft
    assert "- real_fed_funds_rate: 0.32" in draft
    assert "- taylor_rule_implied_rate: 4.91" in draft
    assert "- sahm_triggered: false" in draft


def test_plan_report_structure_preserves_consumer_state_peer_and_sec_summary_values(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text("{}", encoding="utf-8")

    result = json.loads(
        plan_report_structure.func(
            query_type="macro_indicator",
            charts_json_path=str(charts_path),
            execution_summary=json.dumps(
                {
                    "statistical_summary": {
                        "consumer_sentiment_latest": 53.3,
                        "consumer_sentiment_percentile_vs_history": 0.9,
                        "state_ur_ranked": [
                            {"state": "CA", "current_rate": 5.4, "vs_national_diff": 1.1},
                            {"state": "FL", "current_rate": 4.6, "vs_national_diff": 0.3},
                        ],
                        "peer_inflation_ranked": [
                            {"country": "United States", "latest_value": 2.95},
                            {"country": "Mexico", "latest_value": 4.72},
                        ],
                        "aapl_revenue_latest_fy": 416.16,
                        "msft_revenue_latest_fy": 281.72,
                        "aapl_net_margin_latest": 26.92,
                        "msft_net_margin_latest": 36.15,
                        "macro_risk_assessment": {
                            "consumer_stress_level": "medium",
                            "recession_probability_indication": "low",
                            "key_divergences": ["Sentiment at 0.9th percentile vs history"],
                        },
                    }
                }
            ),
            original_query="Assess consumer stress, large states, peers, and tech earnings sensitivity.",
            runtime=_Runtime(),
        )
    )

    draft = result["execution_summary_for_draft"]
    assert "- consumer_sentiment_latest: 53.3" in draft
    assert "- aapl_revenue_latest_fy: 416.2" in draft
    assert "- msft_net_margin_latest: 36.15" in draft
    assert "Exact statistical_summary values from execution_summary.json" in draft
    assert "state=CA; current_rate=5.4; vs_national_diff=1.1" in draft
    assert "country=Mexico; latest_value=4.72" in draft
    assert "consumer_stress_level=medium" in draft


def test_plan_report_structure_surfaces_top_level_state_and_tech_values(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text("{}", encoding="utf-8")

    result = json.loads(
        plan_report_structure.func(
            query_type="macro_indicator",
            charts_json_path=str(charts_path),
            execution_summary=json.dumps(
                {
                    "latest_UMCSENT": 53.3,
                    "latest_PSAVERT": 3.6,
                    "state_comparison": [
                        {"state": "California", "pop": 39242785, "income": 96334},
                        {"state": "Texas", "pop": 29640343, "income": 76292},
                    ],
                    "tech_earnings": {
                        "AAPL_rev_b": 365.82,
                        "AAPL_nm_pct": 25.9,
                        "MSFT_rev_b": 168.09,
                        "MSFT_nm_pct": 36.5,
                    },
                }
            ),
            original_query="Compare consumer stress in large states and tech earnings sensitivity.",
            runtime=_Runtime(),
        )
    )

    draft = result["execution_summary_for_draft"]
    assert "- latest_UMCSENT: 53.3" in draft
    assert "- latest_PSAVERT: 3.6" in draft
    assert "Exact state comparison values from execution_summary.json" in draft
    assert "- California: pop=39242785, income=96334" in draft
    assert "- Texas: pop=29640343, income=76292" in draft
    assert "Exact large-cap technology earnings values from execution_summary.json" in draft
    assert "- AAPL_rev_b: 365.8" in draft
    assert "- MSFT_nm_pct: 36.5" in draft


def test_plan_report_structure_preserves_combined_consumer_acceptance_schema(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text("{}", encoding="utf-8")

    result = json.loads(
        plan_report_structure.func(
            query_type="macro_indicator",
            charts_json_path=str(charts_path),
            execution_summary=json.dumps(
                {
                    "latest_yoy": {
                        "PCE_yoy": 5.326,
                        "DPIC96_yoy": None,
                        "PSAVERT_yoy": -26.531,
                        "PAYEMS_yoy": 0.088,
                        "cpi_yoy": 3.017,
                        "real_earn_yoy": -0.222,
                    },
                    "scenarios_active": {
                        "soft_landing": False,
                        "consumer_squeeze": False,
                        "recession_risk": False,
                    },
                    "composite_indicator": {
                        "latest_index_value": 1.8556,
                        "latest_percentile_0_100": 100.0,
                        "latest_signal": "high",
                        "latest_feature_values": {
                            "UNRATE": 4.3,
                            "PAYEMS_yoy": 0.0877,
                            "PSAVERT": 3.6,
                            "UMCSENT": 53.3,
                        },
                        "backtest_summary": {
                            "status": "ok",
                            "metrics": {
                                "precision": 0.0987,
                                "recall": 0.9836,
                                "false_positive": 548,
                                "false_negative": 1,
                            },
                        },
                    },
                    "state_comparison": [
                        {
                            "name": "California",
                            "pop": 39242785,
                            "med_inc": 96334,
                            "med_home": 783300,
                        }
                    ],
                    "worldbank_peers": {
                        "year": 2024,
                        "data": {
                            "United States": {"gdp_growth": 2.79, "cpi": 2.95},
                            "Germany": {"gdp_growth": -0.5, "cpi": 2.26},
                        },
                    },
                    "apple_summary": {
                        "fiscal_year_start": 2021,
                        "fiscal_year_latest": 2025,
                        "revenue_cagr_pct": 3.276,
                        "revenue_growth_pct": 13.762,
                        "net_margin_pct": 26.915,
                    },
                    "msft_summary": {
                        "fiscal_year_start": 2021,
                        "fiscal_year_latest": 2025,
                        "revenue_cagr_pct": 13.782,
                        "revenue_growth_pct": 67.605,
                        "net_margin_pct": 36.146,
                    },
                    "scenario_table": [
                        {
                            "scenario": "base",
                            "assumptions": ["Growth moderates, labor resilient"],
                            "indicator_triggers": ["UNRATE 4.0-5.0, PSAVERT 4-6"],
                            "confidence": "medium",
                            "uncertainty_notes": "Fiscal wildcards",
                        },
                        {
                            "scenario": "bull",
                            "assumptions": ["Soft landing, consumer rebounds"],
                            "indicator_triggers": ["UNRATE<4.5, PSAVERT>4, UMCSENT>70"],
                            "confidence": "low",
                            "uncertainty_notes": "Inflation resurgence risk",
                        },
                        {
                            "scenario": "bear",
                            "assumptions": ["Consumer squeeze deepens"],
                            "indicator_triggers": ["Real earn<0, PSAVERT<4, DRCCLACBS>5"],
                            "confidence": "medium",
                            "uncertainty_notes": "Labor divergence",
                        },
                    ],
                }
            ),
            original_query="Assess consumer stress, large states, peers, tech earnings, and scenarios.",
            runtime=_Runtime(),
        )
    )

    draft = result["execution_summary_for_draft"]
    assert "Exact latest consumer, labor, inflation, and income values" in draft
    assert "PCE_yoy=5.326" in draft
    assert "real_earn_yoy=-0.222" in draft
    assert "Exact current scenario trigger status" in draft
    assert "soft_landing=false" in draft
    assert "These are boolean trigger states, not probabilities" in draft
    assert "Exact recession-risk framework values" in draft
    assert "latest_index_value: 1.856" in draft
    assert "backtest_metrics: precision=0.0987; recall=0.9836" in draft
    assert "- California: pop=39242785, med_inc=96334, med_home=783300" in draft
    assert "Exact World Bank peer comparison" in draft
    assert "- Germany: gdp_growth=-0.5, cpi=2.26" in draft
    assert "Exact SEC EDGAR Apple/Microsoft summary values" in draft
    assert "- AAPL: fiscal_year_start=2021, fiscal_year_latest=2025" in draft
    assert "revenue_growth_pct=67.61" in draft
    assert "do not add segment mix, installed-base, or sensitivity percentages" in draft
    assert "Required scenario table from execution_summary.json" in draft
    assert "confidence=medium" in draft


def test_plan_report_structure_compacts_current_regime_before_long_history(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text("{}", encoding="utf-8")
    history = [
        {"date": f"2005-{month:02d}", "composite_score": 0.1, "regime_label": "expansion"}
        for month in range(1, 13)
    ] * 60

    result = json.loads(
        plan_report_structure.func(
            query_type="macro_indicator",
            charts_json_path=str(charts_path),
            execution_summary=json.dumps(
                {
                    "current_regime": "reacceleration",
                    "composite_score": 0.7,
                    "domain_scores": {
                        "rates": 1,
                        "labor": 0,
                        "inflation": 0,
                        "credit": 2,
                        "output": 1,
                    },
                    "composite_score_history": history,
                    "evidence_table": [
                        {
                            "domain": "Inflation",
                            "weight": 0.2,
                            "sub_indicators_used": ["CPI_YOY", "CPIC_YOY"],
                            "raw_values_latest": {"CPI_YOY": 0.0329, "CPIC_YOY": 0.026},
                            "domain_total_score": 0,
                            "contribution_to_composite": 0.0,
                        }
                    ],
                    "historical_analogs": [
                        {
                            "date": "2007-04",
                            "regime_label": "reacceleration",
                            "distance": 1.4151,
                            "domain_scores": {"composite": 0.75, "rates_score": 1},
                        }
                    ],
                    "false_positive_caveats": [
                        "Borderline: composite 0.70 within 0.2 of threshold."
                    ],
                    "classification_boundary_margin": 0.0,
                    "current_month": "2026-03",
                    "statistical_summary": {
                        "latest_unemployment_rate": 4.3,
                        "latest_cpi_yoy_pct": 3.29,
                        "latest_core_cpi_yoy_pct": 2.6,
                    },
                }
            ),
            original_query="Classify the current US macro regime using rates, labor, inflation, credit, and output indicators.",
            runtime=_Runtime(),
        )
    )

    draft = result["execution_summary_for_draft"]
    assert draft.startswith("Required regime-classifier fields")
    assert "regime_label: reacceleration" in draft
    assert "regime_score: 0.7" in draft
    assert "category_scores: rates=1; labor=0; inflation=0; credit=2; output=1" in draft
    assert "raw_values_latest=CPI_YOY=0.0329;CPIC_YOY=0.026" in draft
    assert "latest_unemployment_rate=4.3" in draft
    assert "false_positive_caveats: Borderline: composite 0.70" in draft
    assert "composite_score_history" not in draft


def test_write_research_report_embeds_chart_id_list_shape(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text(
        json.dumps(
            [
                {
                    "chart_id": "yield_curve_vs_recessions",
                    "chart_type": "Line",
                    "title": "Yield Curve",
                    "data": [{"date": "2020-01-31", "spread": -0.2}],
                }
            ]
        ),
        encoding="utf-8",
    )
    runtime = SimpleNamespace(context=SimpleNamespace(job_id="job-1", output_dir=str(tmp_path)))

    result = json.loads(
        write_research_report.func(
            runtime=runtime,
            markdown=(
                "## Executive Summary\nSpecific recession signal summary.\n\n"
                "The yield curve inverted.\n\n<!-- CHART:yield_curve_vs_recessions -->\n\n"
                "## Research Query\nAnalyze recession signals using FRED."
            ),
            charts_json_path=str(charts_path),
            original_query="Analyze recession signals using FRED.",
            title="Recession Signals",
            executive_summary="Specific recession signal summary.",
            analysis_type="macro_indicator",
        )
    )

    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))

    assert result["validation_issues"] == []
    assert report["metadata"]["chart_count"] == 1
    assert list(report["charts"].keys()) == ["yield_curve_vs_recessions"]
    chart = report["charts"]["yield_curve_vs_recessions"]
    assert chart["id"] == "yield_curve_vs_recessions"
    assert chart["type"] == "line"
    assert chart["xAxisKey"] == "date"
    assert chart["series"][0]["dataKey"] == "spread"


def test_write_research_report_recovers_original_query_from_markdown_section(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text(
        json.dumps(
            {
                "risk_score": {
                    "id": "risk_score",
                    "type": "line",
                    "title": "Recession Risk",
                    "data": [{"date": "2026-01", "score": 35}],
                    "xAxisKey": "date",
                    "series": [{"dataKey": "score", "label": "Risk", "color": "#ef4444"}],
                }
            }
        ),
        encoding="utf-8",
    )
    runtime = SimpleNamespace(context=SimpleNamespace(job_id="job-1", output_dir=str(tmp_path)))
    query = "Build a recession risk dashboard with base, bull, and bear scenarios."

    result = json.loads(
        write_research_report.func(
            runtime=runtime,
            markdown=(
                "## Executive Summary\nSpecific recession risk summary.\n\n"
                "Risk remains contained.\n\n<!-- CHART:risk_score -->\n\n"
                "## Scenario Table\n"
                "| Scenario | Assumptions | Indicator Triggers | Confidence | Uncertainty Notes |\n"
                "| base | Soft landing | Stable labor | Medium | Data revisions |\n"
                "| bull | Reacceleration | Payrolls improve | Low | Inflation risk |\n"
                "| bear | Recession | Labor cracks | Medium | Credit lag |\n\n"
                f"## Research Query\n{query}\n\n"
                "## Sources\n- FRED"
            ),
            charts_json_path=str(charts_path),
            title="Recession Risk",
            executive_summary="Specific recession risk summary.",
            analysis_type="macro_indicator",
        )
    )

    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))

    assert "status" not in result
    assert report["query"] == query
    assert report["scenario_table"] is not None


def test_write_research_report_preserves_legacy_dual_axis_line_bar_charts(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text(
        json.dumps(
            {
                "chart_1": {
                    "chart_type": "dual_axis_line_bar",
                    "title": "Apple Revenue and CPI",
                    "description": "Apple revenue and net income against CPI inflation.",
                    "x_key": "fiscal_year",
                    "series_config": {
                        "left_axis": [
                            {"key": "Revenue", "name": "Revenue", "color": "#3b82f6"},
                            {"key": "Net Income", "name": "Net Income", "color": "#10b981"},
                        ],
                        "right_axis": [
                            {"key": "CPI Inflation", "name": "CPI Inflation", "color": "#ef4444"}
                        ],
                    },
                    "data": [
                        {
                            "fiscal_year": "2025",
                            "Revenue": 416.16,
                            "Net Income": 112.01,
                            "CPI Inflation": 2.65,
                        }
                    ],
                },
                "chart_2": {
                    "chart_type": "dual_axis_line_bar",
                    "title": "Apple Balance Sheet and Fed Funds",
                    "description": "Assets and liabilities against the fed funds rate.",
                    "x_key": "fiscal_year",
                    "series_config": {
                        "left_axis": [
                            {"key": "Total Assets", "name": "Total Assets", "color": "#3b82f6"},
                            {
                                "key": "Total Liabilities",
                                "name": "Total Liabilities",
                                "color": "#f59e0b",
                            },
                        ],
                        "right_axis": [
                            {"key": "Fed Funds Rate", "name": "Fed Funds Rate", "color": "#ef4444"}
                        ],
                    },
                    "data": [
                        {
                            "fiscal_year": "2025",
                            "Total Assets": 359.24,
                            "Total Liabilities": 285.51,
                            "Fed Funds Rate": 4.21,
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    runtime = SimpleNamespace(context=SimpleNamespace(job_id="job-1", output_dir=str(tmp_path)))

    result = json.loads(
        write_research_report.func(
            runtime=runtime,
            markdown=(
                "## Executive Summary\nApple expanded through a tighter macro backdrop.\n\n"
                "Revenue and earnings held up as CPI cooled.\n\n<!-- CHART:chart_1 -->\n\n"
                "The balance sheet remained resilient as policy rates rose.\n\n"
                "<!-- CHART:chart_2 -->\n\n"
                "## Research Query\nCompare Apple fundamentals against inflation and fed funds."
            ),
            charts_json_path=str(charts_path),
            original_query="Compare Apple fundamentals against inflation and fed funds.",
            title="Apple Fundamentals and Macro Backdrop",
            executive_summary="Apple expanded through a tighter macro backdrop.",
            analysis_type="macro_indicator",
        )
    )

    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))

    assert result["validation_issues"] == []
    assert report["metadata"]["chart_count"] == 2
    assert list(report["charts"].keys()) == ["chart_1", "chart_2"]
    assert report["charts"]["chart_1"]["type"] == "composed"
    assert report["charts"]["chart_1"]["xAxisKey"] == "fiscal_year"
    assert [series["dataKey"] for series in report["charts"]["chart_1"]["series"]] == [
        "Revenue",
        "Net Income",
        "CPI Inflation",
    ]
    assert report["charts"]["chart_1"]["series"][-1]["yAxisId"] == "right"


def test_write_research_report_embeds_scenario_table_and_gate_passes(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text("{}", encoding="utf-8")
    summary_path = tmp_path / "execution_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "scenario_table": [
                    {
                        "scenario": "base",
                        "assumptions": ["Growth slows but avoids contraction"],
                        "indicator_triggers": ["Initial claims stay below stress threshold"],
                        "confidence": "medium",
                        "uncertainty_notes": "Labor data revisions can alter the signal.",
                    },
                    {
                        "scenario": "bull",
                        "assumptions": ["Inflation cools while payrolls remain positive"],
                        "indicator_triggers": ["Credit spreads narrow"],
                        "confidence": "low",
                        "uncertainty_notes": "Requires benign policy lag effects.",
                    },
                    {
                        "scenario": "bear",
                        "assumptions": ["Credit stress and layoffs rise together"],
                        "indicator_triggers": ["Claims and spreads breach stress thresholds"],
                        "confidence": "medium",
                        "uncertainty_notes": "Trigger timing is uncertain.",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    runtime = SimpleNamespace(context=SimpleNamespace(job_id="job-1", output_dir=str(tmp_path)))
    markdown = (
        "## Executive Summary\nRecession risk is scenario-dependent.\n\n"
        "## Scenario Table\n\n"
        "| Scenario | Assumptions | Indicator Triggers | Confidence | Uncertainty Notes |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| Base | Growth slows but avoids contraction | Initial claims stay below stress threshold | Medium | Labor data revisions can alter the signal. |\n"
        "| Bull | Inflation cools while payrolls remain positive | Credit spreads narrow | Low | Requires benign policy lag effects. |\n"
        "| Bear | Credit stress and layoffs rise together | Claims and spreads breach stress thresholds | Medium | Trigger timing is uncertain. |\n\n"
        "## Research Query\nBuild a recession risk dashboard with base, bull, and bear scenarios."
    )

    result = json.loads(
        write_research_report.func(
            runtime=runtime,
            markdown=markdown,
            charts_json_path=str(charts_path),
            original_query="Build a recession risk dashboard with base, bull, and bear scenarios.",
            title="Recession Risk Scenario Dashboard",
            executive_summary="Recession risk is scenario-dependent.",
            analysis_type="macro_indicator",
            execution_summary=str(summary_path),
        )
    )
    gate = json.loads(
        validate_research_report_file.func(
            runtime=runtime,
            report_json_path=result["report_path"],
        )
    )
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))

    assert result["validation_issues"] == []
    assert [row["scenario"] for row in report["scenario_table"]] == ["base", "bull", "bear"]
    assert gate["passes_gate"] is True
    assert gate["scenarios"]["valid"] is True


def test_write_research_report_recovers_original_query_from_prior_plan(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text(
        json.dumps(
            {
                "risk_score": {
                    "id": "risk_score",
                    "type": "line",
                    "title": "Recession Risk",
                    "data": [{"date": "2026-01", "score": 35}],
                    "xAxisKey": "date",
                    "series": [{"dataKey": "score", "label": "Risk", "color": "#ef4444"}],
                }
            }
        ),
        encoding="utf-8",
    )
    runtime = SimpleNamespace(context=SimpleNamespace(job_id="job-1", output_dir=str(tmp_path)))
    query = "Build a recession risk dashboard with base, bull, and bear scenarios."

    plan = json.loads(
        plan_report_structure.func(
            runtime=runtime,
            query_type="macro_indicator",
            charts_json_path=str(charts_path),
            execution_summary="{}",
            original_query=query,
        )
    )
    result = json.loads(
        write_research_report.func(
            runtime=runtime,
            markdown=(
                "## Executive Summary\nSpecific recession risk summary.\n\n"
                "Risk remains contained.\n\n<!-- CHART:risk_score -->\n\n"
                "## Scenario Table\n"
                "| Scenario | Assumptions | Indicator Triggers | Confidence | Uncertainty Notes |\n"
                "| base | Soft landing | Stable labor | Medium | Data revisions |\n"
                "| bull | Reacceleration | Payrolls improve | Low | Inflation risk |\n"
                "| bear | Recession | Labor cracks | Medium | Credit lag |\n\n"
                "## Sources\n- FRED"
            ),
            charts_json_path=plan["charts_json_path"],
            title="Recession Risk",
            executive_summary="Specific recession risk summary.",
            analysis_type="macro_indicator",
        )
    )
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))

    assert "status" not in result
    assert result["validation_issues"] == []
    assert report["query"] == query
    assert [row["scenario"] for row in report["scenario_table"]] == ["base", "bull", "bear"]


def test_write_research_report_loads_job_execution_summary_when_omitted(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text("{}", encoding="utf-8")
    (tmp_path / "execution_summary.json").write_text(
        json.dumps(
            {
                "scenario_table": [
                    {
                        "scenario": "base",
                        "assumptions": ["Growth slows but avoids contraction"],
                        "indicator_triggers": ["Initial claims stay contained"],
                        "confidence": "medium",
                        "uncertainty_notes": "Labor data revisions can alter the signal.",
                    },
                    {
                        "scenario": "bull",
                        "assumptions": ["Inflation cools while payrolls remain positive"],
                        "indicator_triggers": ["Credit spreads narrow"],
                        "confidence": "low",
                        "uncertainty_notes": "Requires benign policy lag effects.",
                    },
                    {
                        "scenario": "bear",
                        "assumptions": ["Credit stress and layoffs rise together"],
                        "indicator_triggers": ["Claims and spreads breach stress thresholds"],
                        "confidence": "medium",
                        "uncertainty_notes": "Trigger timing is uncertain.",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    runtime = SimpleNamespace(context=SimpleNamespace(job_id="job-1", output_dir=str(tmp_path)))
    markdown = (
        "## Executive Summary\nRecession risk is scenario-dependent.\n\n"
        "## Scenario Table\n\n"
        "| Scenario | Assumptions | Indicator Triggers | Confidence | Uncertainty Notes |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| Base | Growth slows but avoids contraction | Initial claims stay contained | Medium | Labor data revisions can alter the signal. |\n"
        "| Bull | Inflation cools while payrolls remain positive | Credit spreads narrow | Low | Requires benign policy lag effects. |\n"
        "| Bear | Credit stress and layoffs rise together | Claims and spreads breach stress thresholds | Medium | Trigger timing is uncertain. |\n\n"
        "## Research Query\nBuild a recession risk dashboard with base, bull, and bear scenarios."
    )

    result = json.loads(
        write_research_report.func(
            runtime=runtime,
            markdown=markdown,
            charts_json_path=str(charts_path),
            original_query="Build a recession risk dashboard with base, bull, and bear scenarios.",
            title="Recession Risk Scenario Dashboard",
            executive_summary="Recession risk is scenario-dependent.",
            analysis_type="macro_indicator",
        )
    )
    gate = json.loads(
        validate_research_report_file.func(
            runtime=runtime,
            report_json_path=result["report_path"],
        )
    )
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))

    assert [row["scenario"] for row in report["scenario_table"]] == ["base", "bull", "bear"]
    assert gate["passes_gate"] is True
    assert gate["scenarios"]["valid"] is True


def test_write_research_report_loads_nested_scenario_analysis_table(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text("{}", encoding="utf-8")
    (tmp_path / "execution_summary.json").write_text(
        json.dumps(
            {
                "scenario_analysis": {
                    "scenario_table": [
                        {
                            "scenario": "base",
                            "assumptions": ["Soft landing continues"],
                            "indicator_triggers": ["Payroll growth remains positive"],
                            "confidence": "medium",
                            "uncertainty_notes": "Inflation data can revise.",
                        },
                        {
                            "scenario": "bull",
                            "assumptions": ["Growth reaccelerates"],
                            "indicator_triggers": ["Real income improves"],
                            "confidence": "low",
                            "uncertainty_notes": "Productivity impulse is uncertain.",
                        },
                        {
                            "scenario": "bear",
                            "assumptions": ["Credit stress tightens"],
                            "indicator_triggers": ["Unemployment rises"],
                            "confidence": "low",
                            "uncertainty_notes": "Timing remains uncertain.",
                        },
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    runtime = SimpleNamespace(context=SimpleNamespace(job_id="job-1", output_dir=str(tmp_path)))
    markdown = (
        "## Executive Summary\nRecession risk is scenario-dependent.\n\n"
        "## Scenario Table\n\n"
        "| Scenario | Assumptions | Indicator Triggers | Confidence | Uncertainty Notes |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| base | Soft landing continues | Payroll growth remains positive | medium | Inflation data can revise. |\n"
        "| bull | Growth reaccelerates | Real income improves | low | Productivity impulse is uncertain. |\n"
        "| bear | Credit stress tightens | Unemployment rises | low | Timing remains uncertain. |\n\n"
        "## Research Query\nBuild base/upside/downside scenarios for recession risk."
    )

    result = json.loads(
        write_research_report.func(
            runtime=runtime,
            markdown=markdown,
            charts_json_path=str(charts_path),
            original_query="Build base/upside/downside scenarios for recession risk.",
            title="Recession Risk Scenario Dashboard",
            executive_summary="Recession risk is scenario-dependent.",
            analysis_type="macro_indicator",
        )
    )
    gate = json.loads(
        validate_research_report_file.func(
            runtime=runtime,
            report_json_path=result["report_path"],
        )
    )
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))

    assert [row["scenario"] for row in report["scenario_table"]] == ["base", "bull", "bear"]
    assert report["scenario_table"][0]["assumptions"] == ["Soft landing continues"]
    assert gate["passes_gate"] is True
    assert gate["scenarios"]["valid"] is True


def test_write_research_report_normalizes_title_cased_compact_scenarios(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text("{}", encoding="utf-8")
    (tmp_path / "execution_summary.json").write_text(
        json.dumps(
            {
                "scenarios": [
                    {
                        "Scenario": "Base (Soft Landing)",
                        "Prob": "55%",
                        "Equities": "S&P +5-10%",
                        "Tech": "+8-12%",
                    },
                    {
                        "Scenario": "Upside",
                        "Prob": "20%",
                        "Equities": "S&P +15-20%",
                        "Tech": "+15-20%",
                    },
                    {
                        "Scenario": "Downside",
                        "Prob": "25%",
                        "Equities": "S&P -15-20%",
                        "Tech": "0-3%",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    runtime = SimpleNamespace(context=SimpleNamespace(job_id="job-1", output_dir=str(tmp_path)))
    markdown = (
        "## Executive Summary\nRecession risk is scenario-dependent.\n\n"
        "## Scenario Table\n\n"
        "| Scenario | Assumptions | Indicator Triggers | Confidence | Uncertainty Notes |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| Base (Soft Landing) | Growth slows but avoids contraction | Claims stay contained | Medium | Data revisions can alter signals. |\n"
        "| Upside | Real income and productivity improve | Production reaccelerates | Low | Requires benign policy lag effects. |\n"
        "| Downside | Credit stress and layoffs rise together | Claims and spreads breach thresholds | Low | Trigger timing is uncertain. |\n\n"
        "## Research Query\nProvide base, upside, and downside scenarios."
    )

    result = json.loads(
        write_research_report.func(
            runtime=runtime,
            markdown=markdown,
            charts_json_path=str(charts_path),
            original_query="Provide base, upside, and downside scenarios.",
            title="Scenario Dashboard",
            executive_summary="Recession risk is scenario-dependent.",
            analysis_type="macro_indicator",
        )
    )
    gate = json.loads(
        validate_research_report_file.func(
            runtime=runtime,
            report_json_path=result["report_path"],
        )
    )
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))

    assert [row["scenario"] for row in report["scenario_table"]] == ["base", "bull", "bear"]
    assert "Equities: S&P +5-10%" in report["scenario_table"][0]["assumptions"]
    assert gate["passes_gate"] is True
    assert gate["scenarios"]["valid"] is True


def test_write_research_report_normalizes_parenthesized_compact_scenarios(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text("{}", encoding="utf-8")
    (tmp_path / "execution_summary.json").write_text(
        json.dumps(
            {
                "scenario_table": [
                    {
                        "scenario": "Base(Soft Landing)",
                        "unrate": "~4.3%",
                        "gdp": "~1.8%",
                        "earnings": "Apple/MSFT stable margins",
                    },
                    {
                        "scenario": "Upside(Reaccel)",
                        "unrate": "~3.8%",
                        "gdp": ">2.5%",
                        "earnings": "Pricing power",
                    },
                    {
                        "scenario": "Downside(Recession)",
                        "unrate": ">5.0%",
                        "gdp": "<0.5%",
                        "earnings": "Revenue flat/negative",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    runtime = SimpleNamespace(context=SimpleNamespace(job_id="job-1", output_dir=str(tmp_path)))
    markdown = (
        "## Executive Summary\nRecession risk is scenario-dependent.\n\n"
        "## Scenario Table\n\n"
        "| Scenario | Probability | GDP Growth | Unemployment (6M) | EPS Impact |\n"
        "|---|---|---|---|---|\n"
        "| base | 55% | 1.5-2.0% | 4.2-4.5% | Stable margins |\n"
        "| bull | 20% | 2.5-3.0% | 3.8-4.1% | Pricing power |\n"
        "| bear | 25% | -1.0 to 0.0% | 5.0-5.5% | Revenue pressure |\n\n"
        "## Research Query\nProvide base, upside, and downside scenarios."
    )

    result = json.loads(
        write_research_report.func(
            runtime=runtime,
            markdown=markdown,
            charts_json_path=str(charts_path),
            original_query="Provide base, upside, and downside scenarios.",
            title="Scenario Dashboard",
            executive_summary="Recession risk is scenario-dependent.",
            analysis_type="macro_indicator",
        )
    )
    gate = json.loads(
        validate_research_report_file.func(
            runtime=runtime,
            report_json_path=result["report_path"],
        )
    )
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))

    assert [row["scenario"] for row in report["scenario_table"]] == ["base", "bull", "bear"]
    assert "Gdp: ~1.8%" in report["scenario_table"][0]["assumptions"]
    assert gate["passes_gate"] is True
    assert gate["scenarios"]["valid"] is True


def test_write_research_report_recovers_scenario_table_from_markdown(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text("{}", encoding="utf-8")
    (tmp_path / "execution_summary.json").write_text(
        json.dumps({"statistical_summary": "Soft landing base case with scenario risks."}),
        encoding="utf-8",
    )
    runtime = SimpleNamespace(context=SimpleNamespace(job_id="job-1", output_dir=str(tmp_path)))
    markdown = (
        "## Executive Summary\nRecession risk is scenario-dependent.\n\n"
        "## Scenario Table\n\n"
        "| Scenario | Assumptions | Indicator Triggers | Confidence | Uncertainty Notes |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| Base / Soft Landing | Growth slows but avoids contraction; inflation cools gradually | Claims stay contained; credit spreads remain orderly | Medium | Data revisions can alter labor and inflation signals. |\n"
        "| Bull / Reacceleration | Productivity and real income improve | Payrolls and production reaccelerate | Low | Requires benign policy lag effects. |\n"
        "| Bear / Recession | Credit stress and layoffs rise together | Claims and delinquencies breach stress thresholds | Medium | Trigger timing is uncertain. |\n\n"
        "## Research Query\nProvide base, upside, and downside scenarios."
    )

    result = json.loads(
        write_research_report.func(
            runtime=runtime,
            markdown=markdown,
            charts_json_path=str(charts_path),
            original_query="Provide base, upside, and downside scenarios.",
            title="Scenario Dashboard",
            executive_summary="Recession risk is scenario-dependent.",
            analysis_type="macro_indicator",
        )
    )
    gate = json.loads(
        validate_research_report_file.func(
            runtime=runtime,
            report_json_path=result["report_path"],
        )
    )
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))

    assert [row["scenario"] for row in report["scenario_table"]] == ["base", "bull", "bear"]
    assert "Growth slows" in report["scenario_table"][0]["assumptions"][0]
    assert gate["passes_gate"] is True
    assert gate["scenarios"]["valid"] is True


def test_write_research_report_recovers_probability_confidence_scenario_table(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text("{}", encoding="utf-8")
    runtime = SimpleNamespace(context=SimpleNamespace(job_id="job-1", output_dir=str(tmp_path)))
    markdown = (
        "## Executive Summary\nScenario risk is balanced but recession risk remains material.\n\n"
        "## Scenario Table\n\n"
        "| Scenario | Assumptions | Indicator Triggers | Confidence | Uncertainty Notes |\n"
        "| base | Soft landing continues; GDP near 2%; unemployment rises only modestly | Claims below 250k; credit stabilizes | 50% | Data revisions can change the signal. |\n"
        "| bull | Reacceleration from productivity and easier policy | Payrolls above 200k; production improves | ~20% | AI capex payoff is uncertain. |\n"
        "| bear | Recession begins as credit and labor weaken together | Claims above 300k; delinquencies rise | 0.30 | Shock timing is uncertain. |\n\n"
        "## Research Query\nBuild base, upside, and downside scenarios."
    )

    result = json.loads(
        write_research_report.func(
            runtime=runtime,
            markdown=markdown,
            charts_json_path=str(charts_path),
            original_query="Build base, upside, and downside scenarios.",
            title="Scenario Dashboard",
            executive_summary="Scenario risk is balanced but recession risk remains material.",
            analysis_type="macro_indicator",
        )
    )
    gate = json.loads(
        validate_research_report_file.func(
            runtime=runtime,
            report_json_path=result["report_path"],
        )
    )
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))

    assert [row["scenario"] for row in report["scenario_table"]] == ["base", "bull", "bear"]
    assert [row["confidence"] for row in report["scenario_table"]] == [
        "medium",
        "low",
        "medium",
    ]
    assert gate["passes_gate"] is True
    assert gate["scenarios"]["valid"] is True


def test_write_research_report_recovers_labeled_probability_confidence_table(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text("{}", encoding="utf-8")
    runtime = SimpleNamespace(context=SimpleNamespace(job_id="job-1", output_dir=str(tmp_path)))
    markdown = (
        "## Executive Summary\nThe regime is a soft landing with downside tail risk.\n\n"
        "## Scenario Table\n\n"
        "| Scenario | Assumptions | Indicator Triggers | Confidence | Uncertainty Notes |\n"
        "| base | GDP +1.5-2.0%; unemployment peaks 4.5% | Payrolls stabilize; core PCE cools | Moderate (45%) | Sticky services inflation could delay easing. |\n"
        "| bull | GDP +2.5-3.0%; productivity accelerates | Payrolls +200k; sentiment improves | Low (20%) | Reacceleration could reignite inflation. |\n"
        "| bear | GDP -1.0-1.5%; credit crunch | Sahm triggers; payrolls negative | Elevated (35%) | Timing is the main uncertainty. |\n\n"
        "## Research Query\nBuild base, upside, and downside scenarios."
    )

    result = json.loads(
        write_research_report.func(
            runtime=runtime,
            markdown=markdown,
            charts_json_path=str(charts_path),
            original_query="Build base, upside, and downside scenarios.",
            title="Scenario Dashboard",
            executive_summary="The regime is a soft landing with downside tail risk.",
            analysis_type="macro_indicator",
        )
    )
    gate = json.loads(
        validate_research_report_file.func(
            runtime=runtime,
            report_json_path=result["report_path"],
        )
    )
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))

    assert [row["scenario"] for row in report["scenario_table"]] == ["base", "bull", "bear"]
    assert [row["confidence"] for row in report["scenario_table"]] == [
        "medium",
        "low",
        "medium",
    ]
    assert gate["passes_gate"] is True
    assert gate["scenarios"]["valid"] is True


def test_write_research_report_recovers_investment_committee_scenario_table(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text("{}", encoding="utf-8")
    (tmp_path / "execution_summary.json").write_text(
        json.dumps({"statistical_summary": "Scenario rows are rendered in markdown."}),
        encoding="utf-8",
    )
    runtime = SimpleNamespace(context=SimpleNamespace(job_id="job-1", output_dir=str(tmp_path)))
    markdown = (
        "## Executive Summary\nScenario risk is skewed but not recessionary.\n\n"
        "## Scenario Table\n\n"
        "| Scenario | Probability | Key Triggers | Unemployment Path | Yield Curve | AAPL Revenue Impact | MSFT Revenue Impact |\n"
        "|---|---|---|---|---|---|---|\n"
        "| base | ~50% | Steady payrolls and Fed easing | 4.4 to 4.6% peak | Steepens slowly | -1% to -3% | +2% to +5% |\n"
        "| bull | ~20% | AI productivity boom and housing recovery | Falls below 4.0% | Normalizes | +3% to +6% | +8% to +15% |\n"
        "| bear | ~30% | Sahm triggers and credit crunch | Rises to 5.5 to 6.0% | Steepens abruptly | -8% to -12% | -5% to -8% |\n\n"
        "## Research Query\nBuild base, upside, and downside scenarios."
    )

    result = json.loads(
        write_research_report.func(
            runtime=runtime,
            markdown=markdown,
            charts_json_path=str(charts_path),
            original_query="Build base, upside, and downside scenarios.",
            title="Scenario Dashboard",
            executive_summary="Scenario risk is skewed but not recessionary.",
            analysis_type="macro_indicator",
        )
    )
    gate = json.loads(
        validate_research_report_file.func(
            runtime=runtime,
            report_json_path=result["report_path"],
        )
    )
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))

    assert [row["scenario"] for row in report["scenario_table"]] == ["base", "bull", "bear"]
    assert "Probability: ~50%" in report["scenario_table"][0]["assumptions"]
    assert "Unemployment Path: 4.4 to 4.6% peak" in report["scenario_table"][0]["assumptions"]
    assert "Steady payrolls" in report["scenario_table"][0]["indicator_triggers"][0]
    assert gate["passes_gate"] is True
    assert gate["scenarios"]["valid"] is True


def test_write_research_report_falls_back_when_execution_summary_is_compact_prose(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text("{}", encoding="utf-8")
    (tmp_path / "execution_summary.json").write_text(
        json.dumps(
            {
                "scenarios": {
                    "base": {
                        "pct": 50,
                        "gdp_f": 1.8,
                        "drivers": "Gradual easing and labor resilience",
                    },
                    "upside": {
                        "pct": 25,
                        "gdp_f": 2.6,
                        "drivers": "Rate cuts and productivity upside",
                    },
                    "downside": {
                        "pct": 25,
                        "gdp_f": 0.5,
                        "drivers": "Credit stress and consumer weakness",
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    runtime = SimpleNamespace(context=SimpleNamespace(job_id="job-1", output_dir=str(tmp_path)))
    markdown = (
        "## Executive Summary\nRecession risk is scenario-dependent.\n\n"
        "## Scenario Table\n\n"
        "| Scenario | Assumptions | Indicator Triggers | Confidence | Uncertainty Notes |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| base | Growth slows but avoids contraction | Claims stay contained | medium | Revisions can alter the signal. |\n"
        "| bull | Inflation cools without labor-market damage | Sentiment improves | low | Requires benign policy lag effects. |\n"
        "| bear | Credit stress and layoffs rise together | Claims rise | medium | Timing is uncertain. |\n\n"
        "## Research Query\nProvide base, upside, and downside scenarios."
    )

    result = json.loads(
        write_research_report.func(
            runtime=runtime,
            markdown=markdown,
            charts_json_path=str(charts_path),
            original_query="Provide base, upside, and downside scenarios.",
            title="Recession Risk Scenario Dashboard",
            executive_summary="Recession risk is scenario-dependent.",
            analysis_type="macro_indicator",
            execution_summary=(
                "Required scenario table from execution_summary.json. Render it as a "
                "markdown table with Scenario, Assumptions, Indicator Triggers, "
                "Confidence, and Uncertainty Notes columns:\n"
                "- base: assumptions=Growth slows; triggers=Claims; confidence=medium"
            ),
        )
    )
    gate = json.loads(
        validate_research_report_file.func(
            runtime=runtime,
            report_json_path=result["report_path"],
        )
    )
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))

    assert [row["scenario"] for row in report["scenario_table"]] == ["base", "bull", "bear"]
    assert gate["passes_gate"] is True
    assert gate["scenarios"]["valid"] is True


def test_write_research_report_normalizes_compact_scenario_mapping(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text("{}", encoding="utf-8")
    (tmp_path / "execution_summary.json").write_text(
        json.dumps(
            {
                "scenarios": {
                    "base": {
                        "gdp_growth": 2.0,
                        "unemployment": 4.2,
                        "cpi": 2.6,
                        "narrative": "Soft landing",
                    },
                    "upside": {
                        "gdp_growth": 3.2,
                        "unemployment": 3.8,
                        "cpi": 3.5,
                        "narrative": "Reacceleration",
                    },
                    "downside": {
                        "gdp_growth": -0.5,
                        "unemployment": 6.0,
                        "cpi": 1.5,
                        "narrative": "Recession",
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    runtime = SimpleNamespace(context=SimpleNamespace(job_id="job-1", output_dir=str(tmp_path)))
    markdown = (
        "## Executive Summary\nRecession risk is scenario-dependent.\n\n"
        "## Scenario Table\n\n"
        "| Scenario | Assumptions | Indicator Triggers | Confidence | Uncertainty Notes |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| Base | Soft landing | Incoming data remain mixed | Medium | Monitor data revisions. |\n"
        "| Bull | Reacceleration | Growth firms | Medium | Inflation could reheat. |\n"
        "| Bear | Recession | Labor weakens | Medium | Trigger timing is uncertain. |\n\n"
        "## Research Query\nProvide base, upside, and downside scenarios."
    )

    result = json.loads(
        write_research_report.func(
            runtime=runtime,
            markdown=markdown,
            charts_json_path=str(charts_path),
            original_query="Provide base, upside, and downside scenarios.",
            title="Scenario Dashboard",
            executive_summary="Recession risk is scenario-dependent.",
            analysis_type="macro_indicator",
        )
    )
    gate = json.loads(
        validate_research_report_file.func(
            runtime=runtime,
            report_json_path=result["report_path"],
        )
    )
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))

    assert [row["scenario"] for row in report["scenario_table"]] == ["base", "bull", "bear"]
    assert "Gdp Growth: 2.0" in report["scenario_table"][0]["assumptions"]
    assert gate["passes_gate"] is True
    assert gate["scenarios"]["valid"] is True


def test_write_research_report_normalizes_nested_statistical_scenarios(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text("{}", encoding="utf-8")
    (tmp_path / "execution_summary.json").write_text(
        json.dumps(
            {
                "statistical_summary": {
                    "scenarios": [
                        {
                            "scenario_name": "Base",
                            "key_assumptions": ["Growth slows but avoids contraction"],
                            "trigger_indicators": ["Initial claims stay contained"],
                            "confidence": "Medium - labor data remain mixed",
                            "uncertainty_notes": "Data revisions can alter the signal.",
                        },
                        {
                            "scenario_name": "Bull",
                            "key_assumptions": ["Inflation cools while payrolls remain positive"],
                            "trigger_indicators": ["Credit spreads narrow"],
                            "confidence": "Low-to-Medium",
                            "uncertainty_notes": "Requires benign policy lag effects.",
                        },
                        {
                            "scenario_name": "Bear",
                            "key_assumptions": ["Credit stress and layoffs rise together"],
                            "trigger_indicators": ["Claims and spreads breach stress thresholds"],
                            "confidence": "Medium",
                            "uncertainty_notes": "Trigger timing is uncertain.",
                        },
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    runtime = SimpleNamespace(context=SimpleNamespace(job_id="job-1", output_dir=str(tmp_path)))
    markdown = (
        "## Executive Summary\nRecession risk is scenario-dependent.\n\n"
        "## Scenario Table\n\n"
        "| Scenario | Assumptions | Indicator Triggers | Confidence | Uncertainty Notes |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| Base | Growth slows but avoids contraction | Initial claims stay contained | Medium | Data revisions can alter the signal. |\n"
        "| Bull | Inflation cools while payrolls remain positive | Credit spreads narrow | Low | Requires benign policy lag effects. |\n"
        "| Bear | Credit stress and layoffs rise together | Claims and spreads breach stress thresholds | Medium | Trigger timing is uncertain. |\n\n"
        "## Research Query\nBuild a recession risk dashboard with base, bull, and bear scenarios."
    )

    result = json.loads(
        write_research_report.func(
            runtime=runtime,
            markdown=markdown,
            charts_json_path=str(charts_path),
            original_query="Build a recession risk dashboard with base, bull, and bear scenarios.",
            title="Recession Risk Scenario Dashboard",
            executive_summary="Recession risk is scenario-dependent.",
            analysis_type="macro_indicator",
        )
    )
    gate = json.loads(
        validate_research_report_file.func(
            runtime=runtime,
            report_json_path=result["report_path"],
        )
    )
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))

    assert [row["scenario"] for row in report["scenario_table"]] == ["base", "bull", "bear"]
    assert [row["confidence"] for row in report["scenario_table"]] == [
        "medium",
        "medium",
        "medium",
    ]
    assert gate["passes_gate"] is True
    assert gate["scenarios"]["valid"] is True


def test_write_research_report_normalizes_top_level_scenarios_from_quant_handoff(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text("{}", encoding="utf-8")
    summary_path = tmp_path / "execution_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "scenarios": [
                    {
                        "scenario_name": "Base - Soft Landing",
                        "probability_assignment": 50,
                        "key_assumptions": ["Payroll growth moderates but remains positive"],
                        "trigger_indicators": [
                            {
                                "indicator_name": "Yield Curve Slope",
                                "current_value": 0.53,
                                "threshold": -0.2,
                                "status": "normal",
                            }
                        ],
                        "confidence_notes": ["Labor data revisions can alter the signal."],
                    },
                    {
                        "scenario_name": "Bull - Reacceleration",
                        "probability_assignment": 20,
                        "key_assumptions": ["Inflation cools without labor-market damage"],
                        "trigger_indicators": [
                            {
                                "indicator_name": "Consumer Sentiment",
                                "current_value": 53.3,
                                "threshold": 60.0,
                                "status": "positive",
                            }
                        ],
                        "confidence_notes": ["Requires a positive productivity shock."],
                    },
                    {
                        "scenario_name": "Bear - Hard Landing",
                        "probability_assignment": 30,
                        "key_assumptions": ["Payrolls contract and unemployment rises"],
                        "trigger_indicators": [
                            {
                                "indicator_name": "Unemployment Rate",
                                "current_value": 4.3,
                                "threshold": 5.5,
                                "status": "critical",
                            }
                        ],
                        "confidence_notes": ["Yield-curve lead times vary materially."],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    runtime = SimpleNamespace(context=SimpleNamespace(job_id="job-1", output_dir=str(tmp_path)))
    markdown = (
        "## Executive Summary\nRecession risk is scenario-dependent.\n\n"
        "## Scenario Table\n\n"
        "| Scenario | Assumptions | Indicator Triggers | Confidence | Uncertainty Notes |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| Base | Payroll growth moderates but remains positive | Yield curve normal | Medium | Labor data revisions can alter the signal. |\n"
        "| Bull | Inflation cools without labor-market damage | Sentiment improves | Low | Requires a positive productivity shock. |\n"
        "| Bear | Payrolls contract and unemployment rises | Unemployment worsens | Medium | Yield-curve lead times vary materially. |\n\n"
        "## Research Query\nBuild a recession risk dashboard with base, bull, and bear scenarios."
    )

    result = json.loads(
        write_research_report.func(
            runtime=runtime,
            markdown=markdown,
            charts_json_path=str(charts_path),
            original_query="Build a recession risk dashboard with base, bull, and bear scenarios.",
            title="Recession Risk Scenario Dashboard",
            executive_summary="Recession risk is scenario-dependent.",
            analysis_type="macro_indicator",
            execution_summary=str(summary_path),
        )
    )
    gate = json.loads(
        validate_research_report_file.func(
            runtime=runtime,
            report_json_path=result["report_path"],
        )
    )
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))

    assert [row["scenario"] for row in report["scenario_table"]] == ["base", "bull", "bear"]
    assert [row["confidence"] for row in report["scenario_table"]] == [
        "medium",
        "low",
        "medium",
    ]
    assert "Yield Curve Slope" in report["scenario_table"][0]["indicator_triggers"][0]
    assert gate["passes_gate"] is True
    assert gate["scenarios"]["valid"] is True


def test_validate_research_report_file_rejects_missing_scenario_table_for_scenario_query(tmp_path):
    report_path = tmp_path / "report.json"
    report_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "job_id": "job-1",
                "created_at": "2026-04-29T00:00:00+00:00",
                "query": "Build a recession risk dashboard with base, bull, and bear scenarios.",
                "title": "Recession Risk Scenario Dashboard",
                "executive_summary": "Scenario summary.",
                "markdown": "## Executive Summary\nScenario summary.\n\n## Research Query\nBuild a recession risk dashboard with base, bull, and bear scenarios.",
                "charts": {},
                "data_sources": [],
                "metadata": {"analysis_type": "macro_indicator", "chart_count": 0, "word_count": 12},
            }
        ),
        encoding="utf-8",
    )
    runtime = SimpleNamespace(context=SimpleNamespace(job_id="job-1", output_dir=str(tmp_path)))

    gate = json.loads(
        validate_research_report_file.func(
            runtime=runtime,
            report_json_path=str(report_path),
            auto_patch=False,
        )
    )

    assert gate["passes_gate"] is False
    assert "missing required scenario_table rows" in gate["blockers"][0]
    assert gate["scenarios"]["missing_required_rows"] == ["base", "bull", "bear"]


def test_validate_research_report_file_rejects_unreferenced_chart_definitions(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text(
        json.dumps(
            {
                "chart_labor_market": {
                    "id": "chart_labor_market",
                    "type": "line",
                    "title": "Labor Market",
                    "description": "Recent unemployment rate.",
                    "xAxisKey": "date",
                    "series": [{"dataKey": "unrate", "label": "UNRATE", "color": "#2563eb"}],
                    "data": [{"date": "2026-03-01", "unrate": 4.3}],
                },
                "chart_gdp_gap": {
                    "id": "chart_gdp_gap",
                    "type": "line",
                    "title": "GDP Gap",
                    "description": "Real GDP relative to potential.",
                    "xAxisKey": "date",
                    "series": [{"dataKey": "gap", "label": "GDP Gap", "color": "#16a34a"}],
                    "data": [{"date": "2025-10-01", "gap": 0.46}],
                },
            }
        ),
        encoding="utf-8",
    )
    runtime = SimpleNamespace(context=SimpleNamespace(job_id="job-1", output_dir=str(tmp_path)))

    result = json.loads(
        write_research_report.func(
            runtime=runtime,
            markdown=(
                "## Executive Summary\nThe macro regime is slowing but not recessionary.\n\n"
                "Labor conditions remain firm.\n\n<!-- CHART:chart_labor_market -->\n\n"
                "## Research Query\nClassify the current US macro regime."
            ),
            charts_json_path=str(charts_path),
            original_query="Classify the current US macro regime.",
            title="US Macro Regime Classification",
            executive_summary="The macro regime is slowing but not recessionary.",
            analysis_type="macro_indicator",
        )
    )
    gate = json.loads(
        validate_research_report_file.func(
            runtime=runtime,
            report_json_path=result["report_path"],
            auto_patch=False,
        )
    )

    assert result["validation_issues"] == [
        "Chart ID 'chart_gdp_gap' is defined in charts.json but missing a matching "
        "<!-- CHART:chart_gdp_gap --> marker in markdown"
    ]
    assert gate["passes_gate"] is False
    assert gate["charts"]["unreferenced_charts"] == ["chart_gdp_gap"]
    assert "charts defined in charts.json but not referenced" in gate["blockers"][0]


def test_validate_research_report_file_rejects_frontend_non_renderable_chart(tmp_path):
    report_path = tmp_path / "report.json"
    report_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "job_id": "job-1",
                "created_at": "2026-04-28T00:00:00+00:00",
                "query": "Show a chart of recession risk.",
                "title": "Recession Risk",
                "executive_summary": "Risk rose.",
                "markdown": (
                    "## Executive Summary\nRisk rose.\n\n"
                    "<!-- CHART:chart_risk -->\n\n"
                    "## Research Query\nShow a chart of recession risk."
                ),
                "charts": {
                    "chart_risk": {
                        "id": "chart_risk",
                        "type": "line",
                        "title": "Recession Risk",
                        "description": "Broken chart with mismatched series key.",
                        "xAxisKey": "date",
                        "series": [
                            {
                                "dataKey": "missing_score",
                                "label": "Risk",
                                "color": "#3b82f6",
                            }
                        ],
                        "data": [{"date": "2026-03-01", "risk_score": 0.42}],
                    }
                },
                "data_sources": [],
                "metadata": {"analysis_type": "macro_indicator", "chart_count": 1, "word_count": 12},
            }
        ),
        encoding="utf-8",
    )
    runtime = SimpleNamespace(context=SimpleNamespace(job_id="job-1", output_dir=str(tmp_path)))

    gate = json.loads(
        validate_research_report_file.func(
            runtime=runtime,
            report_json_path=str(report_path),
            auto_patch=False,
        )
    )

    assert gate["passes_gate"] is False
    assert gate["chart_render"]["valid"] is False
    assert gate["chart_render"]["issues"]["chart_risk"] == [
        "series missing_score has no finite numeric values"
    ]
    assert "frontend Recharts render contract" in gate["blockers"][0]


def test_write_research_report_embeds_charts_object_list_shape(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text(
        json.dumps(
            {
                "charts": [
                    {
                        "id": "chart_1_unemployment_rate",
                        "type": "line",
                        "title": "Unemployment Rate",
                        "description": "Recent unemployment rate.",
                        "data": [{"date": "2026 Q1", "value": 4.1}],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    runtime = SimpleNamespace(context=SimpleNamespace(job_id="job-1", output_dir=str(tmp_path)))

    result = json.loads(
        write_research_report.func(
            runtime=runtime,
            markdown=(
                "## Executive Summary\nLabor market softening summary with specific numbers.\n\n"
                "The unemployment rate moved higher.\n\n<!-- CHART:chart_1_unemployment_rate -->\n\n"
                "## Research Query\nIs the US labor market weakening? Use FRED."
            ),
            charts_json_path=str(charts_path),
            original_query="Is the US labor market weakening? Use FRED.",
            title="Labor Market Softening",
            executive_summary="Labor market softening summary with specific numbers.",
            analysis_type="macro_indicator",
        )
    )

    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))

    assert result["validation_issues"] == []
    assert list(report["charts"].keys()) == ["chart_1_unemployment_rate"]
    assert report["charts"]["chart_1_unemployment_rate"]["type"] == "line"


def test_validate_research_report_file_directory_path_resolves_report_json(tmp_path):
    runtime = SimpleNamespace(context=SimpleNamespace(job_id="job-1", output_dir=str(tmp_path)))

    result = json.loads(
        validate_research_report_file.func(
            runtime=runtime,
            report_json_path=str(tmp_path),
        )
    )

    assert result["passes_gate"] is False
    assert result["load_error"] == f"File not found: {tmp_path / 'report.json'}"


def test_write_research_report_normalizes_top_level_legacy_axis_shape(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text(
        json.dumps(
            {
                "chart_inflation_all": {
                    "id": "chart_inflation_all",
                    "chartType": "line",
                    "title": "YoY CPI Inflation",
                    "xKey": "date",
                    "yKeys": [
                        {
                            "key": "inflation_yoy",
                            "label": "YoY CPI Inflation (%)",
                            "color": "#3b82f6",
                            "axis": "left",
                        }
                    ],
                    "data": [{"date": "2024-01-31", "inflation_yoy": 3.1}],
                }
            }
        ),
        encoding="utf-8",
    )
    runtime = SimpleNamespace(context=SimpleNamespace(job_id="job-1", output_dir=str(tmp_path)))

    result = json.loads(
        write_research_report.func(
            runtime=runtime,
            markdown=(
                "## Executive Summary\nInflation summary with specific numbers.\n\n"
                "Inflation eased.\n\n<!-- CHART:chart_inflation_all -->\n\n"
                "## Research Query\nCompare inflation regimes using FRED."
            ),
            charts_json_path=str(charts_path),
            original_query="Compare inflation regimes using FRED.",
            title="Inflation Regimes",
            executive_summary="Inflation summary with specific numbers.",
            analysis_type="macro_indicator",
        )
    )

    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    chart = report["charts"]["chart_inflation_all"]

    assert result["validation_issues"] == []
    assert chart["type"] == "line"
    assert chart["xAxisKey"] == "date"
    assert chart["series"][0]["dataKey"] == "inflation_yoy"
    assert chart["series"][0]["label"] == "YoY CPI Inflation (%)"
    assert chart["series"][0]["color"] == "#3b82f6"
    assert chart["series"][0]["yAxisId"] == "left"


def test_write_research_report_normalizes_quant_keyed_series_config(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text(
        json.dumps(
            {
                "chart_consumer_stress": {
                    "chart_id": "chart_consumer_stress",
                    "chart_type": "composed",
                    "title": "Consumer Stress",
                    "x_key": "date",
                    "y_keys": ["UMCSENT", "PSAVERT"],
                    "series_config": {
                        "UMCSENT": {
                            "label": "Sentiment",
                            "color": "#3b82f6",
                            "yAxisId": "left",
                        },
                        "PSAVERT": {
                            "label": "Saving Rate %",
                            "color": "#f59e0b",
                            "yAxisId": "right",
                        },
                    },
                    "reference_areas": [
                        {
                            "x1": "2020-03-01",
                            "x2": "2020-04-01",
                            "fill": "#fee2e2",
                        }
                    ],
                    "data": [{"date": "2026-03-01", "UMCSENT": 57.9, "PSAVERT": 3.9}],
                }
            }
        ),
        encoding="utf-8",
    )
    runtime = SimpleNamespace(context=SimpleNamespace(job_id="job-1", output_dir=str(tmp_path)))

    result = json.loads(
        write_research_report.func(
            runtime=runtime,
            markdown=(
                "## Executive Summary\nConsumer stress summary with specific numbers.\n\n"
                "Sentiment and savings show pressure.\n\n"
                "<!-- CHART:chart_consumer_stress -->\n\n"
                "## Research Query\nAssess consumer stress and recession risk."
            ),
            charts_json_path=str(charts_path),
            original_query="Assess consumer stress and recession risk.",
            title="Consumer Stress",
            executive_summary="Consumer stress summary with specific numbers.",
            analysis_type="macro_indicator",
        )
    )

    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    chart = report["charts"]["chart_consumer_stress"]

    assert result["validation_issues"] == []
    assert chart["type"] == "composed"
    assert chart["xAxisKey"] == "date"
    assert [series["dataKey"] for series in chart["series"]] == ["UMCSENT", "PSAVERT"]
    assert chart["series"][1]["yAxisId"] == "right"
    assert chart["referenceAreas"][0]["x1"] == "2020-03-01"


def test_write_research_report_preserves_quant_combo_chart_type(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text(
        json.dumps(
            {
                "rates_composite": {
                    "chart_id": "rates_composite",
                    "title": "Policy Rate vs Real Yield vs Spread",
                    "chart_type": "combo",
                    "data": [
                        {
                            "date": "2026-04-01",
                            "FEDFUNDS": 3.64,
                            "DFII10": 1.94,
                            "T10Y2Y": 0.52,
                        }
                    ],
                    "x_key": "date",
                    "y_keys": ["FEDFUNDS", "DFII10", "T10Y2Y"],
                    "y_labels": {
                        "FEDFUNDS": "Fed Funds",
                        "DFII10": "10Y Real Yield",
                        "T10Y2Y": "10Y-2Y Spread",
                    },
                    "colors": {
                        "FEDFUNDS": "#ef4444",
                        "DFII10": "#3b82f6",
                        "T10Y2Y": "#f59e0b",
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    runtime = SimpleNamespace(context=SimpleNamespace(job_id="job-1", output_dir=str(tmp_path)))

    result = json.loads(
        write_research_report.func(
            runtime=runtime,
            markdown=(
                "## Executive Summary\nRates remain restrictive while growth weakens.\n\n"
                "Policy rates, real yields, and the curve frame the tradeoff.\n\n"
                "<!-- CHART:rates_composite -->\n\n"
                "## Research Query\nCompare higher-for-longer policy and growth weakness."
            ),
            charts_json_path=str(charts_path),
            original_query="Compare higher-for-longer policy and growth weakness.",
            title="Macro Risk Memo",
            executive_summary="Rates remain restrictive while growth weakens.",
            analysis_type="macro_indicator",
        )
    )

    gate = json.loads(
        validate_research_report_file.func(
            runtime=runtime,
            report_json_path=str(tmp_path / "report.json"),
        )
    )
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    chart = report["charts"]["rates_composite"]

    assert result["validation_issues"] == []
    assert gate["passes_gate"] is True
    assert gate["charts"]["defined_charts"] == ["rates_composite"]
    assert gate["chart_render"]["checked_charts"] == ["rates_composite"]
    assert chart["type"] == "composed"
    assert chart["xAxisKey"] == "date"
    assert [series["dataKey"] for series in chart["series"]] == [
        "FEDFUNDS",
        "DFII10",
        "T10Y2Y",
    ]


def test_technical_writer_middleware_hides_filesystem_tools():
    middleware = next(
        item
        for item in TECHNICAL_WRITER_SUBAGENT["middleware"]
        if isinstance(item, TechnicalWriterToolBoundaryMiddleware)
    )
    request = _Request(
        [
            SimpleNamespace(name="read_file"),
            SimpleNamespace(name="execute"),
            SimpleNamespace(name="plan_report_structure"),
            SimpleNamespace(name="write_research_report"),
            SimpleNamespace(name="validate_research_report_file"),
        ]
    )

    response = middleware.wrap_model_call(request, lambda req: req)

    assert [tool.name for tool in response.tools] == [
        "plan_report_structure",
        "write_research_report",
        "validate_research_report_file",
    ]


def test_technical_writer_middleware_stops_after_successful_validation():
    middleware = next(
        item
        for item in TECHNICAL_WRITER_SUBAGENT["middleware"]
        if isinstance(item, TechnicalWriterToolBoundaryMiddleware)
    )
    request = _Request(
        [
            SimpleNamespace(name="write_research_report"),
            SimpleNamespace(name="validate_research_report_file"),
        ],
        messages=[
            ToolMessage(
                content=json.dumps(
                    {
                        "report_path": "/tmp/outputs/job-1/report.json",
                        "chart_count": 1,
                        "validation_issues": [],
                    }
                ),
                name="write_research_report",
                tool_call_id="call-write",
            ),
            ToolMessage(
                content=json.dumps(
                    {
                        "passes_gate": True,
                        "charts": {"defined_charts": ["macro_signal"]},
                    }
                ),
                name="validate_research_report_file",
                tool_call_id="call-validate",
            ),
        ],
    )

    response = middleware.wrap_model_call(
        request,
        lambda req: ModelResponse(result=[AIMessage(content="should not run")]),
    )

    handoff = json.loads(response.result[0].content)
    assert handoff == {
        "status": "success",
        "report_json": "/tmp/outputs/job-1/report.json",
        "chart_ids": ["macro_signal"],
    }


def test_technical_writer_middleware_blocks_inherited_filesystem_tool_calls():
    middleware = next(
        item
        for item in TECHNICAL_WRITER_SUBAGENT["middleware"]
        if isinstance(item, TechnicalWriterToolBoundaryMiddleware)
    )
    request = SimpleNamespace(
        tool_call={"name": "read_file", "id": "call-1", "args": {"path": "charts.json"}}
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )

    assert response.tool_call_id == "call-1"
    assert response.status == "error"
    assert "Blocked tool `read_file`" in response.content
    assert "plan_report_structure already reads charts.json" in response.content

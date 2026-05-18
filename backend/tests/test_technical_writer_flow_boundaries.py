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


def test_plan_report_structure_surfaces_generic_company_helper_evidence(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text(
        json.dumps(
            {
                "company_income_statement_history": {
                    "id": "company_income_statement_history",
                    "type": "composed",
                    "title": "Company Revenue and Profit History",
                    "xAxisKey": "period",
                    "series": [{"dataKey": "revenue_b", "label": "Revenue"}],
                    "data": [{"period": "NVDA FY2026", "revenue_b": 215.938}],
                }
            }
        ),
        encoding="utf-8",
    )
    execution_summary = {
        "latest_fundamentals": {
            "NVDA": {
                "fiscal_year": 2026,
                "revenue_b": 215.938,
                "net_margin_pct": 55.6,
                "cash_and_securities_b": 10.605,
                "diluted_eps": 4.9,
            }
        },
        "company_macro_sensitivity": [
            {
                "ticker": "NVDA",
                "latest_fiscal_year": 2026,
                "latest_avg_fedfunds_pct": None,
                "latest_recession_months": None,
            }
        ],
        "source_coverage": {
            "sec_company_facts": {"status": "covered"},
            "valuation_market_data": {"status": "not_available"},
        },
        "numeric_facts": [
            {
                "id": "sec_company_facts.NVDA.revenue_b",
                "display_value": "$215.938B",
                "raw_value": 215.938,
                "tolerance": 0.005,
                "source_key": "sec_company_facts.latest_fundamentals.NVDA.revenue_b",
                "subject": "NVDA",
                "metric": "revenue_b",
            }
        ],
    }

    result = json.loads(
        plan_report_structure.func(
            query_type="earnings_analysis",
            charts_json_path=str(charts_path),
            execution_summary=json.dumps(execution_summary),
            original_query="Prepare a stock-specific NVIDIA fundamentals report.",
            runtime=_Runtime(),
        )
    )

    assert result["helper_evidence_for_draft"]["tables"]["latest_fundamentals"]["NVDA"][
        "revenue_b"
    ] == 215.938
    assert "Generic helper-produced evidence" in result["execution_summary_for_draft"]
    assert "$215.938B" in result["execution_summary_for_draft"]
    assert "company_macro_sensitivity" in result["execution_summary_for_draft"]
    assert "valuation_market_data" in result["execution_summary_for_draft"]


def test_plan_report_structure_surfaces_chart_facts_for_draft(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text(
        json.dumps(
            {
                "rates_inflation_overlay": {
                    "id": "rates_inflation_overlay",
                    "type": "composed",
                    "title": "Rates And Inflation",
                    "description": "Policy rates and inflation.",
                    "xAxisKey": "date",
                    "series": [
                        {"dataKey": "FEDFUNDS", "label": "Fed funds", "type": "line"},
                        {"dataKey": "CURVE_SPREAD", "label": "10Y-2Y yield spread", "type": "line"},
                        {"dataKey": "cpi_yoy", "label": "CPI YoY", "type": "bar"},
                    ],
                    "data": [
                        {
                            "date": "2026-01",
                            "FEDFUNDS": 3.64,
                            "CURVE_SPREAD": -0.35,
                            "cpi_yoy": 2.4,
                        }
                    ],
                    "referenceAreas": [{"label": "Latest year", "x1": "2025-01", "x2": "2026-01"}],
                }
            }
        ),
        encoding="utf-8",
    )

    result = json.loads(
        plan_report_structure.func(
            query_type="macro_indicator",
            charts_json_path=str(charts_path),
            execution_summary=json.dumps({"statistical_summary": "Computed macro facts."}),
            original_query="Assess soft landing versus delayed recession with charts.",
            runtime=_Runtime(),
        )
    )

    chart_facts = result["chart_facts_for_draft"]
    draft = result["execution_summary_for_draft"]
    assert "Chart facts from charts.json" in chart_facts
    assert "rates_inflation_overlay: type=composed" in chart_facts
    assert "Fed funds (FEDFUNDS, line)" in chart_facts
    assert "10Y-2Y yield spread (CURVE_SPREAD, line)" in chart_facts
    assert "referenceAreas=Latest year" in chart_facts
    assert draft.startswith("Chart facts from charts.json")
    assert "Computed macro facts." in draft
    assert "chart_facts_for_draft" in result["general_rules"]


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
            "latest_unemployment_rate": 4.3,
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
    assert "latest_unemployment_rate: 4.3" in draft
    assert "latest_cpi_yoy: 3.12" in draft
    assert "latest_yield_curve_bps: 52.1" in draft
    assert "latest_composite_risk: 30.8" in draft
    assert "unrate_forecast_6m: 4.69" in draft
    assert "aapl_revenue_cagr_2021_2025: 0.0328" in draft
    assert "Use ONLY those exact chart IDs" in result["general_rules"]


def test_plan_report_structure_preserves_generic_quant_acceptance_metrics(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text('{"recession_probability": {"id": "recession_probability"}}', encoding="utf-8")
    summary_path = tmp_path / "execution_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "forecast_origin": {
                    "target_variable": "UNRATE",
                    "model_spec": "ARX unemployment bridge",
                },
                "forecast_table": [
                    {"date": "2026-04", "forecast": 4.35, "lower": 4.1, "upper": 4.6},
                    {"date": "2026-05", "forecast": 4.39, "lower": 4.1, "upper": 4.7},
                ],
                "statistical_summary": {
                    "latest_unemployment_rate": 4.3,
                    "latest_cpi_yoy": 3.1,
                    "latest_core_pce_yoy": 3.0,
                    "latest_yield_spread": 0.62,
                    "latest_fed_funds_rate": 3.64,
                    "recession_probability_current": 97.0,
                },
                "composite_current_row": {
                    "date": "2026-03-01",
                    "composite_index": 0.41,
                    "composite_percentile_0_100": 63.2,
                    "classification": "elevated but below recession threshold",
                },
                "current_regime_row": {
                    "regime": "soft landing",
                    "regime_score": 0.58,
                    "score_momentum": -0.03,
                    "category_scores": {"labor": 0.2, "inflation": 0.6},
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
            original_query="Assess recession risk, unemployment, scenarios, and regime.",
            runtime=runtime,
        )
    )

    draft = result["execution_summary_for_draft"]
    assert "latest_unemployment_rate: 4.3" in draft
    assert "latest_yield_spread: 0.62" in draft
    assert "latest_fed_funds_rate: 3.64" in draft
    assert "recession_probability_current: 97" in draft
    assert "regime=soft landing" in draft
    assert "classification=elevated but below recession threshold" in draft
    assert "forecast_table: 2026-04: date=2026-04; forecast=4.35" in draft
    assert "regime_score=0.58" in draft


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
                "model_validation_rows": [
                    {"model": "aapl_macro_model", "error": "Could not extract AAPL revenue"},
                    {"model": "aapl_naive_momentum", "error": "Could not extract AAPL revenue"},
                ],
                "replay_rows": [
                    {
                        "label": "2001",
                        "unrate_change_pp": 1.2,
                        "indpro_change_pct": -3.45,
                        "real_pce_change_pct": 1.97,
                        "sentiment_decline_pts": -7.6,
                    },
                    {
                        "label": "2020",
                        "unrate_change_pp": 11.3,
                        "indpro_change_pct": -16.84,
                        "real_pce_change_pct": -9.89,
                        "sentiment_decline_pts": -11.8,
                    },
                ],
                "limitations": ["Do not fabricate RMSE when validation rows contain errors."],
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
    assert "Do not fabricate RMSE" in draft
    assert "model=aapl_macro_model; error=Could not extract AAPL revenue" in draft
    assert "model=aapl_naive_momentum; error=Could not extract AAPL revenue" in draft
    assert "replay_rows: 2001: unrate_change_pp=1.2" in draft
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
                "composite_current_row": {
                    "date": "2026-03-01",
                    "composite_index": 1.7898878189766174,
                    "composite_percentile_0_100": 100.0,
                    "classification": "high",
                    "feature_values": {
                        "UMCSENT": 53.3,
                        "INDPRO_chg_pct": 0.6545176949190212,
                    },
                },
                "composite_validation_metrics": {
                    "status": "ok",
                    "metrics": {"precision": 0.1441860465, "recall": 1.0},
                },
                "forecast_origin": {
                    "target_variable": "UNRATE",
                    "current_value": 4.3,
                    "model_spec": "UNRATE(t+6) ~ const + payroll_momentum",
                },
                "forecast_table": [
                    {
                        "date": "2026-10-01",
                        "forecast": 4.36,
                        "lower": 4.09,
                        "upper": 4.64,
                    }
                ],
                "current_regime_row": {
                    "regime": "expansion",
                    "category_scores": {"labor": 1.0, "consumption": -1.0},
                },
                "regime_evidence_rows": [
                    {
                        "category": "financial",
                        "indicator": "Yield Curve",
                        "value": 0.52,
                        "score": 1.0,
                        "signal": "supportive",
                    }
                ],
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
                "latest_fundamentals": {
                    "AAPL": {
                        "fiscal_year": 2025,
                        "revenue_growth_pct": 6.4,
                        "net_income_growth_pct": 19.5,
                        "net_margin_pct": 26.9,
                    },
                    "MSFT": {
                        "fiscal_year": 2025,
                        "revenue_growth_pct": 14.9,
                        "net_income_growth_pct": 15.5,
                        "net_margin_pct": 36.1,
                    },
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
    assert "Generic helper-produced evidence" in draft
    assert "composite_current_row" in draft
    assert "composite_index=1.79" in draft
    assert "UMCSENT" in draft
    assert "forecast_table: 2026-10-01: date=2026-10-01; forecast=4.36" in draft
    assert "regime=expansion" in draft
    assert "real_ahe_yoy_pct: 0.03" in draft
    assert "California: population=39242785, median_income=96334" in draft
    assert "DEU: gdp_growth=-0.5, inflation=2.26" in draft
    assert "latest_fundamentals.AAPL: fiscal_year=2025" in draft
    assert "revenue_growth_pct=6.4" in draft
    assert "latest_fundamentals.MSFT: fiscal_year=2025" in draft
    assert "revenue_growth_pct=14.9" in draft
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
    assert "Exact lead-lag metrics from execution_summary.json" in draft
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
    assert "Soft landing evidence" in result["execution_summary_for_draft"]
    assert len(result["execution_summary_for_draft"]) == 4000


def test_plan_report_structure_preserves_top_level_composite_validation_diagnostics(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text('{"recession_risk": {"id": "recession_risk"}}', encoding="utf-8")
    summary_path = tmp_path / "execution_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "composite_current_row": {
                    "date": "2026-03-01",
                    "composite_index": -3.22,
                    "composite_percentile_0_100": 0.0,
                    "classification": "low",
                },
                "composite_validation_metrics": {
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
    assert "Generic helper-produced evidence" in draft
    assert "composite_current_row" in draft
    assert "composite_index=-3.22" in draft
    assert "composite_validation_metrics" in draft
    assert "precision=0.25" in draft
    assert "recall=0.0484" in draft
    assert "false_negative=59" in draft


def test_plan_report_structure_surfaces_generic_scenario_score_evidence(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text("{}", encoding="utf-8")

    result = json.loads(
        plan_report_structure.func(
            query_type="macro_indicator",
            charts_json_path=str(charts_path),
            execution_summary=json.dumps(
                {
                    "scenario_score_rows": [
                        {
                            "scenario": "base",
                            "score": 0.0,
                            "delta_vs_current": 0.0,
                            "note": "Slower growth with claims stable.",
                            "direction": "neutral",
                            "threshold": 0.0,
                        },
                        {
                            "scenario": "bull",
                            "score": 1.2,
                            "delta_vs_current": 1.2,
                            "note": "Inflation cools and spreads narrow.",
                            "direction": "upside",
                            "threshold": 1.0,
                        },
                        {
                            "scenario": "bear",
                            "score": -1.7,
                            "delta_vs_current": -1.7,
                            "note": "Labor cracks and claims jump.",
                            "direction": "downside",
                            "threshold": -1.0,
                        },
                    ],
                    "numeric_facts": [
                        {
                            "id": "scenario_score_rows.bear.score",
                            "source_key": "scenario_score_rows[bear].score",
                            "display_value": "-1.70",
                            "raw_value": -1.7,
                            "tolerance": 0.01,
                            "subject": "bear",
                            "metric": "scenario_score",
                        }
                    ],
                }
            ),
            original_query="Build a recession risk dashboard with base, bull, and bear scenarios.",
            runtime=_Runtime(),
        )
    )

    draft = result["execution_summary_for_draft"]
    assert "Generic helper-produced evidence" in draft
    assert "scenario_score_rows: base" in draft
    assert "bear: score=-1.7" in draft
    assert "scenario_score_rows.bear.score=-1.70" in draft
    assert result["helper_evidence_for_draft"]["tables"]["scenario_score_rows"][2]["scenario"] == "bear"
    assert result["helper_evidence_for_draft"]["tables"]["scenario_score_rows"]

def test_plan_report_structure_prioritizes_generic_backtest_values(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text("{}", encoding="utf-8")

    result = json.loads(
        plan_report_structure.func(
            query_type="macro_indicator",
            charts_json_path=str(charts_path),
            execution_summary=json.dumps(
                {
                    "composite_current_row": {
                        "date": "2026-03-01",
                        "composite_index": 0.06182,
                        "composite_percentile_0_100": 83.29,
                        "classification": "high",
                    },
                    "composite_validation_metrics": {
                        "metrics": {
                            "precision": 0.01887,
                            "recall": 0.5,
                            "false_positive": 52,
                        },
                    },
                    "signal_validation_metrics": {
                        "observations": 532,
                        "event_count": 5,
                        "events_met_threshold": 3,
                        "false_positive_windows": 9,
                        "true_positive_rate": 0.6,
                        "precision": 0.25,
                        "threshold": 2,
                    },
                    "latest_signal_observation": {
                        "score": 1,
                        "threshold": 2,
                        "above_threshold": False,
                        "components_triggered": ["labor deterioration"],
                    },
                    "signal_event_rows": [
                        {
                            "event_label": "2008 recession 12m before",
                            "score": 2,
                            "met_threshold": True,
                            "max_score_date": "2007-01-01",
                        }
                    ],
                    "signal_false_positive_windows": [
                        {
                            "window_label": "2022-2023",
                            "max_score": 2,
                            "components_at_peak": ["yield curve", "labor"],
                        }
                    ],
                    "scenario_score_rows": [
                        {
                            "scenario": "bear",
                            "score": 3,
                            "delta_vs_current": 2,
                            "note": "red",
                        },
                    ],
                }
            ),
            original_query=(
                "Build a recession-risk report showing what a simple helper backtest "
                "said before downturns and how often it cried wolf."
            ),
            runtime=_Runtime(),
        )
    )

    draft = result["execution_summary_for_draft"]
    assert "Generic helper-produced evidence" in draft
    assert "events_met_threshold=3" in draft
    assert "false_positive_windows=9" in draft
    assert "precision=0.25" in draft
    assert "latest_signal_observation: score=1" in draft
    assert "2008 recession 12m before: score=2" in draft
    assert "2022-2023: max_score=2" in draft


def test_plan_report_structure_preserves_generic_replay_rows(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text("{}", encoding="utf-8")

    replay_rows = [
        {
            "event_label": f"{year} recession 12m before",
            "score": 1 if year == 2020 else 0,
            "met_threshold": year == 2020,
            "max_score_date": "2019-08-31" if year == 2020 else f"{year}-01-31",
        }
        for year in (1960, 1970, 1973, 1980, 1981, 1990, 2001, 2008, 2020)
    ]

    result = json.loads(
        plan_report_structure.func(
            query_type="macro_indicator",
            charts_json_path=str(charts_path),
            execution_summary=json.dumps(
                {
                    "signal_validation_metrics": {
                        "observations": 233278,
                        "event_count": 9,
                        "events_met_threshold": 2,
                        "false_positive_windows": 7,
                        "precision": 0.2222222222,
                        "threshold": 2,
                    },
                    "signal_event_rows": replay_rows,
                }
            ),
            original_query=(
                "Build a recession-risk report showing what a simple helper backtest "
                "said before earlier downturns and how often it cried wolf."
            ),
            runtime=_Runtime(),
        )
    )

    draft = result["execution_summary_for_draft"]
    assert "Generic helper-produced evidence" in draft
    assert "event_count=9" in draft
    assert "events_met_threshold=2" in draft
    assert "2020 recession 12m before: score=1; met_threshold=True" in draft


def test_plan_report_structure_surfaces_generic_signal_helper_evidence(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text("{}", encoding="utf-8")

    helper_evidence = {
        "signal_validation_metrics": {
            "event_count": 5,
            "events_met_threshold": 3,
            "events_below_threshold": 2,
            "false_positive_windows": 4,
            "precision": 0.428571,
            "threshold": 2,
        },
        "latest_signal_observation": {
            "date": "2026-03-01",
            "score": 1,
            "threshold": 2,
            "max_score": 3,
            "above_threshold": False,
            "confirming_signals": ["Yield curve inversion lead window"],
            "contradicting_signals": ["Labor deterioration"],
        },
        "signal_event_rows": [
            {
                "event_label": "2008 recession 12m before",
                "score": 2,
                "met_threshold": True,
                "max_score_date": "2007-03-01",
                "components_triggered": ["Yield curve inversion lead window", "Credit tightening"],
            }
        ],
        "signal_false_positive_windows": [
            {
                "window_label": "2022-2023",
                "max_score": 2,
                "components_at_peak": ["Yield curve inversion lead window", "Credit tightening"],
            }
        ],
        "scenario_score_rows": [
            {"scenario": "base", "score": 1, "delta_vs_current": 0, "note": "yellow"},
            {"scenario": "bull", "score": 0, "delta_vs_current": -1, "note": "green"},
            {"scenario": "bear", "score": 3, "delta_vs_current": 2, "note": "red"},
        ],
    }

    result = json.loads(
        plan_report_structure.func(
            query_type="macro_indicator",
            charts_json_path=str(charts_path),
            execution_summary=json.dumps(helper_evidence),
            original_query=(
                "Build a recession-risk report showing signal stack false positives "
                "and base, upside, and downside cases."
            ),
            runtime=_Runtime(),
        )
    )

    draft = result["execution_summary_for_draft"]
    assert "Generic helper-produced evidence" in draft
    assert "events_met_threshold=3" in draft
    assert "false_positive_windows=4" in draft
    assert "latest_signal_observation: date=2026-03-01" in draft
    assert "2008 recession 12m before: score=2" in draft
    assert "2022-2023: max_score=2" in draft
    assert "bear: score=3" in draft
    assert (
        result["helper_evidence_for_draft"]["diagnostics"]["signal_validation_metrics"][
            "false_positive_windows"
        ]
        == 4
    )


def test_plan_report_structure_preserves_generic_regime_rows(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text("{}", encoding="utf-8")

    result = json.loads(
        plan_report_structure.func(
            query_type="macro_indicator",
            charts_json_path=str(charts_path),
            execution_summary=json.dumps(
                {
                    "current_regime_row": {
                        "date": "2026-03-31",
                        "status": "ok",
                        "regime": "slowdown",
                        "regime_score": -0.31,
                        "category_scores": {"rates": -0.6, "labor": -0.2, "output": 0.1},
                    },
                    "regime_evidence_rows": [
                        {
                            "category": "rates",
                            "indicator": "yield_curve",
                            "value": -0.4,
                            "score": -0.8,
                            "rationale": "Curve inversion is a slowdown signal.",
                        }
                    ],
                    "regime_analog_rows": [
                        {"date": "2001-02-28", "regime": "slowdown", "regime_score": -0.29}
                    ],
                    "missing_indicator_rows": [],
                    "regime_design": {
                        "method": "recession_regime_classifier",
                        "min_categories": 3,
                    },
                    "methods_used": ["recession_regime_classifier"],
                }
            ),
            original_query="Classify the current US macro regime as expansion, slowdown, recession, recovery, or reacceleration.",
            runtime=_Runtime(),
        )
    )

    draft = result["execution_summary_for_draft"]
    assert "Generic helper-produced evidence" in draft
    assert "current_regime_row" in draft
    assert "regime=slowdown" in draft
    assert "regime_evidence_rows" in draft
    assert "yield_curve" in draft
    assert "regime_analog_rows" in draft
    assert "false_positive_caveat" not in draft


def test_plan_report_structure_surfaces_generic_econometric_validation_rows(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text("{}", encoding="utf-8")

    result = json.loads(
        plan_report_structure.func(
            query_type="macro_indicator",
            charts_json_path=str(charts_path),
            execution_summary=json.dumps(
                {
                    "walk_forward_backtest_rows": [
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
                    "model_comparison_by_horizon": [
                        {
                            "horizon": 1,
                            "direct_ols_mae": 0.12,
                            "last_value_mae": 0.2,
                        },
                    ],
                    "diagnostics": {"forecast_validation": {"status": "ok", "rmse": 0.18}},
                    "replay_rows": [
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
    assert "Reusable validation and simulation evidence" in draft
    assert "walk_forward_backtest_rows" in draft
    assert "model_comparison_by_horizon: 1: horizon=1; direct_ols_mae=0.12" in draft
    assert "Generic helper-produced evidence" in draft
    assert "replay_rows: global financial crisis" in draft


def test_plan_report_structure_surfaces_generic_forecast_rows(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text("{}", encoding="utf-8")

    summary = {
        "forecast_origin": {
            "as_of_date": "2026-01",
            "target_variable": "UNRATE",
            "target_unit": "percent",
            "model_spec": "UNRATE(t+6) ~ const + UNRATE + payroll",
        },
        "forecast_table": [
            {
                "horizon": 6,
                "date": "2026-07-01",
                "forecast": 4.64,
                "lower": 4.1,
                "upper": 5.2,
                "last_value_baseline": 4.3,
            }
        ],
        "model_comparison_by_horizon": [
            {
                "horizon": 6,
                "direct_ols_mae": 0.712,
                "last_value_mae": 0.635,
                "train_mean_mae": 2.373,
                "winner_by_mae": "last_value",
            }
        ],
        "historical_failure_episodes": [
            {
                "target_date": "2020-10-01",
                "prediction_date": "2020-04-01",
                "classification": "large_overprediction",
                "actual": 6.9,
                "forecast": 22.758,
                "absolute_error": 15.858,
                "baseline_last_value": 14.8,
            }
        ],
        "event_backtest_metrics": {
            "false_positive_count": 140,
            "miss_count": 107,
            "precision": 0.278,
            "recall": 0.335,
        },
        "signal_false_positive_windows": [
            {
                "period": "2021",
                "peak_date": "2021-06-01",
                "max_signal": 66.2,
                "threshold": 65,
            }
        ],
    }

    result = json.loads(
        plan_report_structure.func(
            query_type="macro_indicator",
            charts_json_path=str(charts_path),
            execution_summary=json.dumps(summary),
            original_query="Review the unemployment forecast, baselines, historical failures, and false alarms.",
            runtime=_Runtime(),
        )
    )

    draft = result["execution_summary_for_draft"]
    assert "Generic helper-produced evidence" in draft
    assert "forecast_table: 2026-07-01: horizon=6; date=2026-07-01; forecast=4.64" in draft
    assert "model_comparison_by_horizon: 6: horizon=6; direct_ols_mae=0.712" in draft
    assert "historical_failure_episodes: 2020-10-01:" in draft
    assert "signal_false_positive_windows: period=2021" in draft
    assert "event_backtest_metrics: false_positive_count=140" in draft


def test_plan_report_structure_keeps_non_rate_forecast_rows_unit_neutral(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text("{}", encoding="utf-8")

    summary = {
        "forecast_origin": {
            "as_of_date": "2026-01",
            "target_variable": "PAYEMS",
            "model_spec": "PAYEMS(t+1) ~ const + payroll_momentum",
        },
        "forecast_table": [
            {
                "horizon": 1,
                "date": "2026-02-01",
                "forecast": 155250,
                "lower": 154800,
                "upper": 155900,
                "last_value_baseline": 155000,
            }
        ],
        "model_comparison_by_horizon": [
            {"horizon": 1, "direct_ols_mae": 120.5, "last_value_mae": 150.25}
        ],
    }

    result = json.loads(
        plan_report_structure.func(
            query_type="macro_indicator",
            charts_json_path=str(charts_path),
            execution_summary=json.dumps(summary),
            original_query="Forecast payroll employment with reusable evidence rows.",
            runtime=_Runtime(),
        )
    )

    draft = result["execution_summary_for_draft"]
    assert "forecast_table: 2026-02-01: horizon=1; date=2026-02-01; forecast=155250" in draft
    assert "155250%" not in draft


def test_write_research_report_accepts_reusable_forecast_rows_without_exact_gate(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text("{}", encoding="utf-8")
    summary = {
        "forecast_table": [
            {"horizon": 6, "date": "2026-07-01", "forecast": 4.64, "lower": 4.1, "upper": 5.2}
        ],
        "model_comparison_by_horizon": [
            {"horizon": 6, "direct_ols_mae": 0.712, "last_value_mae": 0.635, "train_mean_mae": 2.373}
        ],
    }

    result = json.loads(
        write_research_report.func(
            markdown=(
                "## Executive Summary\n"
                "The unemployment forecast reaches 4.0% by mid-2025 with a 3.8% to 4.4% interval.\n\n"
                "## Research Query\nReview unemployment forecast."
            ),
            charts_json_path=str(charts_path),
            original_query="Review unemployment forecast.",
            execution_summary=json.dumps(summary),
            runtime=SimpleNamespace(context=SimpleNamespace(job_id="job-forecast-review", output_dir=str(tmp_path))),
        )
    )

    assert result["report_path"].endswith("report.json")
    assert result["validation_issues"] == []


def test_write_research_report_rejects_company_fundamental_numeric_drift(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text("{}", encoding="utf-8")
    summary = {
        "latest_fundamentals": {
            "NVDA": {
                "revenue_b": 215.938,
                "cash_and_securities_b": 10.605,
            }
        },
        "numeric_facts": [
            {
                "id": "sec_company_facts.NVDA.revenue_b",
                "display_value": "$215.938B",
                "raw_value": 215.938,
                "tolerance": 0.005,
                "source_key": "sec_company_facts.latest_fundamentals.NVDA.revenue_b",
                "subject": "NVDA",
                "metric": "revenue_b",
            },
            {
                "id": "sec_company_facts.NVDA.cash_and_securities_b",
                "display_value": "$10.605B",
                "raw_value": 10.605,
                "tolerance": 0.005,
                "source_key": "sec_company_facts.latest_fundamentals.NVDA.cash_and_securities_b",
                "subject": "NVDA",
                "metric": "cash_and_securities_b",
            },
        ],
    }

    result = json.loads(
        write_research_report.func(
            markdown=(
                "## Executive Summary\n"
                "NVDA revenue was about $130B and cash was more than $40B.\n\n"
                "## Research Query\nReview NVIDIA revenue and balance sheet."
            ),
            charts_json_path=str(charts_path),
            original_query="Review NVIDIA revenue and balance sheet.",
            execution_summary=json.dumps(summary),
            runtime=SimpleNamespace(
                context=SimpleNamespace(job_id="job-company-fundamentals", output_dir=str(tmp_path))
            ),
        )
    )

    assert result["status"] == "error"
    assert result["failure_category"] == "numeric_fact_mismatch"
    assert "NVDA revenue_b" in result["message"]
    assert "NVDA cash_and_securities_b" in result["message"]


def test_plan_report_structure_preserves_dict_backtest_model_and_simulation_metrics(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text("{}", encoding="utf-8")

    result = json.loads(
        plan_report_structure.func(
            query_type="macro_indicator",
            charts_json_path=str(charts_path),
            execution_summary=json.dumps(
                {
                    "validation_diagnostics": {
                        "average_auc": 0.478,
                        "average_brier_score": 0.0664,
                        "calibration": {
                            "mean_predicted_prob": 0.1022,
                            "actual_recession_freq": 0.0933,
                        },
                        "method": "Rolling OOS logistic regression",
                    },
                    "model_validation_rows": [
                        {
                            "model": "logistic_regression",
                            "accuracy": 0.9432,
                            "precision": 0.7857,
                            "recall": 0.569,
                            "f1_score": 0.66,
                            "auc": 0.3685,
                        },
                        {
                            "model": "yield_curve_benchmark",
                            "accuracy": 0.7746,
                            "precision": 0.1111,
                            "recall": 0.1897,
                            "f1_score": 0.1401,
                            "auc": 0.3685,
                        },
                    ],
                    "replay_rows": [
                        {"label": "2020", "auc": 0.2, "brier_score": 0.417},
                    ],
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
    assert "replay_rows: 2020: auc=0.2; brier_score=0.417" in draft
    assert "model=logistic_regression" in draft
    assert "accuracy=0.9432" in draft
    assert "model=yield_curve_benchmark" in draft
    assert "f1_score=0.1401" in draft


def test_plan_report_structure_preserves_backtest_z_score_tables(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text("{}", encoding="utf-8")

    result = json.loads(
        plan_report_structure.func(
            query_type="macro_indicator",
            charts_json_path=str(charts_path),
            execution_summary=json.dumps(
                {
                    "validation_diagnostics": {
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
                }
            ),
            original_query="Use historical replay and be explicit about backtest limits.",
            runtime=_Runtime(),
        )
    )

    draft = result["execution_summary_for_draft"]
    assert "current_z_scores: UNRATE=-0.8627; FEDFUNDS=-0.1479; CPIAUCSL=null" in draft
    assert "pre_recession_avg_z_scores: UNRATE=-1.01; FEDFUNDS=-0.0235" in draft


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


def test_plan_report_structure_surfaces_top_level_state_and_generic_company_values(tmp_path):
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
                    "latest_fundamentals": {
                        "AAPL": {
                            "fiscal_year": 2025,
                            "revenue_b": 365.82,
                            "net_margin_pct": 25.9,
                        },
                        "MSFT": {
                            "fiscal_year": 2025,
                            "revenue_b": 168.09,
                            "net_margin_pct": 36.5,
                        },
                    },
                    "numeric_facts": [
                        {
                            "id": "sec_company_facts.AAPL.revenue_b",
                            "display_value": "$365.82B",
                            "raw_value": 365.82,
                            "tolerance": 0.005,
                            "subject": "AAPL",
                            "metric": "revenue_b",
                            "source_key": "latest_fundamentals.AAPL.revenue_b",
                        }
                    ],
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
    assert "Generic helper-produced evidence" in draft
    assert "latest_fundamentals.AAPL: fiscal_year=2025" in draft
    assert "net_margin_pct=36.5" in draft
    assert "sec_company_facts.AAPL.revenue_b=$365.82B" in draft


def test_plan_report_structure_compacts_top_level_helper_evidence(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text("{}", encoding="utf-8")

    summary = {
        "methods_used": ["analog_window_comparison"],
        "chart_ids": ["analog_similarity"],
        "historical_window_coverage": [
            {
                "label": "1995 soft landing",
                "status": "covered",
                "requested": True,
                "requested_years": ["1995"],
                "observed_months": 30,
                "expected_months": 30,
            }
        ],
        "analog_similarity_ranking": [
            {
                "label": "2001 recession",
                "raw_distance": 19.831,
                "normalized_similarity": 4.801,
                "status": "ok",
            }
        ],
        "analog_profiles": {
            "2001 recession": {"unemployment": 5.5, "inflation": 2.7},
            "current": {"unemployment": 4.1, "inflation": 3.1},
        },
        "source_coverage": {
            "sec_company_facts": {"status": "covered"},
            "valuation_market_data": {"status": "not_available"},
        },
        "limitations": ["Analog windows compare observed history, not causal mechanisms."],
        "international_comparison": {
            "latest_year": 2024,
            "table": [
                {
                    "country": "United States",
                    "gdp_growth": 2.79,
                    "inflation": 3.1,
                }
            ],
        },
        "scenario_score_rows": [
            {"scenario": "base", "score": 0.0, "note": "steady baseline"},
            {"scenario": "bull", "score": 1.0, "note": "upside case"},
            {"scenario": "bear", "score": -1.0, "note": "downside case"},
        ],
        "numeric_facts": [
            {
                "id": "state_comparison.CA.per_capita_personal_income",
                "label": "California per-capita personal income",
                "raw_value": 91116,
                "display_value": "$91,120",
                "unit": "usd_per_person",
                "precision": -1,
                "tolerance": 5,
                "source_key": "state_comparison[CA].income",
                "as_of_date": "2025-01",
            }
        ],
        "latest_snapshot": {"unemployment_rate": 4.3},
    }

    result = json.loads(
        plan_report_structure.func(
            query_type="macro_indicator",
            charts_json_path=str(charts_path),
            execution_summary=json.dumps(summary),
            original_query="Build a macro cycle report with unemployment outlook and tech earnings.",
            runtime=_Runtime(),
        )
    )

    draft = result["execution_summary_for_draft"]
    assert "Structured evidence from execution_summary.json" not in draft
    assert "Display-ready numeric facts from execution_summary.json" in draft
    assert "state_comparison.CA.per_capita_personal_income=$91,120" in draft
    assert "source_key=state_comparison[CA].income" in draft
    assert "sec_company_facts: status=covered" in draft
    assert "valuation_market_data: status=not_available" in draft
    assert "Exact international peer comparison from execution_summary.json" in draft
    assert "Generic helper-produced evidence" in draft
    assert "historical_window_coverage: 1995 soft landing" in draft
    assert "analog_similarity_ranking: 2001 recession" in draft
    assert result["helper_evidence_for_draft"]["tables"]["analog_similarity_ranking"][0]["label"] == "2001 recession"


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
                    "composite_current_row": {
                        "date": "2026-03-01",
                        "composite_index": 1.8556,
                        "composite_percentile_0_100": 100.0,
                        "classification": "high",
                        "feature_values": {
                            "UNRATE": 4.3,
                            "PAYEMS_yoy": 0.0877,
                            "PSAVERT": 3.6,
                            "UMCSENT": 53.3,
                        },
                    },
                    "composite_validation_metrics": {
                        "status": "ok",
                        "metrics": {
                            "precision": 0.0987,
                            "recall": 0.9836,
                            "false_positive": 548,
                            "false_negative": 1,
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
                    "latest_fundamentals": {
                        "AAPL": {
                            "fiscal_year": 2025,
                            "revenue_cagr_pct": 3.276,
                            "revenue_growth_pct": 13.762,
                            "net_margin_pct": 26.915,
                        },
                        "MSFT": {
                            "fiscal_year": 2025,
                            "revenue_cagr_pct": 13.782,
                            "revenue_growth_pct": 67.605,
                            "net_margin_pct": 36.146,
                        },
                    },
                    "numeric_facts": [
                        {
                            "id": "sec_company_facts.MSFT.revenue_growth_pct",
                            "display_value": "67.61%",
                            "raw_value": 67.605,
                            "tolerance": 0.005,
                            "subject": "MSFT",
                            "metric": "revenue_growth_pct",
                            "source_key": "latest_fundamentals.MSFT.revenue_growth_pct",
                        }
                    ],
                    "scenario_score_rows": [
                        {
                            "scenario": "base",
                            "score": 0.0,
                            "drivers": ["Growth moderates, labor resilient"],
                            "direction": "neutral",
                            "threshold": 0.0,
                            "note": "UNRATE 4.0-5.0, PSAVERT 4-6",
                        },
                        {
                            "scenario": "bull",
                            "score": 1.0,
                            "drivers": ["Soft landing, consumer rebounds"],
                            "direction": "upside",
                            "threshold": 1.0,
                            "note": "UNRATE<4.5, PSAVERT>4, UMCSENT>70",
                        },
                        {
                            "scenario": "bear",
                            "score": -1.0,
                            "drivers": ["Consumer squeeze deepens"],
                            "direction": "downside",
                            "threshold": -1.0,
                            "note": "Real earn<0, PSAVERT<4, DRCCLACBS>5",
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
    assert "Generic helper-produced evidence" in draft
    assert "composite_current_row" in draft
    assert "composite_index=1.856" in draft
    assert "composite_validation_metrics" in draft
    assert "precision=0.0987" in draft
    assert "recall=0.9836" in draft
    assert "- California: pop=39242785, med_inc=96334, med_home=783300" in draft
    assert "Exact World Bank peer comparison" in draft
    assert "- Germany: gdp_growth=-0.5, cpi=2.26" in draft
    assert "Generic helper-produced evidence" in draft
    assert "latest_fundamentals.AAPL: fiscal_year=2025" in draft
    assert "revenue_growth_pct=67.61" in draft
    assert "sec_company_facts.MSFT.revenue_growth_pct=67.61%" in draft
    assert "scenario_score_rows: base" in draft
    assert "confidence=medium" not in draft


def test_plan_report_structure_compacts_generic_current_regime_before_long_history(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text("{}", encoding="utf-8")
    history = [
        {"date": f"2005-{month:02d}", "regime_score": 0.1, "regime": "expansion"}
        for month in range(1, 13)
    ] * 60

    result = json.loads(
        plan_report_structure.func(
            query_type="macro_indicator",
            charts_json_path=str(charts_path),
            execution_summary=json.dumps(
                {
                    "current_regime_row": {
                        "date": "2026-03",
                        "status": "ok",
                        "regime": "reacceleration",
                        "regime_score": 0.7,
                        "category_scores": {
                            "rates": 1,
                            "labor": 0,
                            "inflation": 0,
                            "credit": 2,
                            "output": 1,
                        },
                    },
                    "regime_history_rows": history,
                    "regime_evidence_rows": [
                        {
                            "category": "Inflation",
                            "indicator": "CPI_YOY",
                            "weight": 0.2,
                            "sub_indicators_used": ["CPI_YOY", "CPIC_YOY"],
                            "raw_values_latest": {"CPI_YOY": 0.0329, "CPIC_YOY": 0.026},
                            "domain_total_score": 0,
                            "contribution_to_composite": 0.0,
                        }
                    ],
                    "regime_analog_rows": [
                        {
                            "date": "2007-04",
                            "regime": "reacceleration",
                            "distance": 1.4151,
                            "domain_scores": {"composite": 0.75, "rates_score": 1},
                        }
                    ],
                    "regime_design": {
                        "method": "recession_regime_classifier",
                        "min_categories": 3,
                    },
                    "limitations": ["Borderline: composite 0.70 within 0.2 of threshold."],
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
    assert draft.startswith("Generic helper-produced evidence")
    assert "current_regime_row" in draft
    assert "regime=reacceleration" in draft
    assert "regime_score=0.7" in draft
    assert "category_scores={'rates': 1, 'labor': 0, 'inflation': 0, 'credit': 2, 'output': 1}" in draft
    assert "raw_values_latest={'CPI_YOY': 0.0329, 'CPIC_YOY': 0.026}" in draft
    assert "latest_unemployment_rate: 4.3" in draft
    assert "limitations: Borderline: composite 0.70" in draft
    assert "regime_history_rows" in draft


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


def test_write_research_report_normalizes_legacy_dual_axis_config_charts(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text(
        json.dumps(
            [
                {
                    "chart_id": "labor_replay",
                    "title": "Labor Market",
                    "type": "dual_axis",
                    "data": [
                        {"date": "2025-01-01", "UNRATE": 4.0, "PAYEMS_mil": 158.0},
                        {"date": "2025-02-01", "UNRATE": 4.1, "PAYEMS_mil": 158.2},
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
            ]
        ),
        encoding="utf-8",
    )
    runtime = SimpleNamespace(context=SimpleNamespace(job_id="job-1", output_dir=str(tmp_path)))

    result = json.loads(
        write_research_report.func(
            runtime=runtime,
            markdown=(
                "## Executive Summary\nLabor remains firm.\n\n"
                "The labor replay compares unemployment against payroll levels.\n\n"
                "<!-- CHART:labor_replay -->\n\n"
                "## Research Query\nUse charts to compare current labor with prior cycles."
            ),
            charts_json_path=str(charts_path),
            original_query="Use charts to compare current labor with prior cycles.",
            title="Labor Replay",
            executive_summary="Labor remains firm.",
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

    assert result["validation_issues"] == []
    assert gate["passes_gate"] is True
    assert list(report["charts"].keys()) == ["labor_replay"]
    assert report["charts"]["labor_replay"]["type"] == "composed"
    assert report["charts"]["labor_replay"]["xAxisKey"] == "date"
    assert [series["dataKey"] for series in report["charts"]["labor_replay"]["series"]] == [
        "UNRATE",
        "PAYEMS_mil",
    ]
    assert report["charts"]["labor_replay"]["series"][0]["yAxisId"] == "left"
    assert report["charts"]["labor_replay"]["series"][1]["yAxisId"] == "right"


def test_write_research_report_keeps_scenario_scores_in_execution_summary_only(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text("{}", encoding="utf-8")
    summary_path = tmp_path / "execution_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "scenario_score_rows": [
                    {"scenario": "base", "score": 0.0, "note": "Growth slows."},
                    {"scenario": "bull", "score": 1.0, "note": "Inflation cools."},
                    {"scenario": "bear", "score": -1.0, "note": "Credit stress rises."},
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
    assert "scenario_score_rows" not in report
    assert gate["passes_gate"] is True
    assert gate["scenarios"]["row_count"] == 0


def test_write_research_report_allows_generic_scenario_markdown_prewrite(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text("{}", encoding="utf-8")
    summary_path = tmp_path / "execution_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "scenario_score_rows": [
                    {
                        "scenario": "bear",
                        "score": -1.4,
                        "value": 44.0,
                        "threshold": 65.0,
                        "direction": "at_or_above",
                        "note": "Labor stress remains below the bear threshold.",
                    },
                ],
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
        "| base | Growth slows but avoids contraction | Unemployment above 5.0% | medium | Labor data revisions can alter the signal. |\n"
        "| bull | Inflation cools while payrolls remain positive | Credit spreads narrow | low | Requires benign policy lag effects. |\n"
        "| bear | Credit stress and layoffs rise together | Labor stress >= 65.00 | medium | Trigger timing is uncertain. |\n\n"
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

    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))

    assert "report_path" in result
    assert "scenario_score_rows" not in report
    assert "status" not in result


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


def test_write_research_report_loads_job_execution_summary_when_omitted(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text("{}", encoding="utf-8")
    (tmp_path / "execution_summary.json").write_text(
        json.dumps(
            {
                "scenario_score_rows": [
                    {"scenario": "base", "score": 0.0, "note": "Growth slows."},
                    {"scenario": "bull", "score": 1.0, "note": "Inflation cools."},
                    {"scenario": "bear", "score": -1.0, "note": "Credit stress rises."},
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

    assert "scenario_score_rows" not in report
    assert gate["passes_gate"] is True
    assert gate["scenarios"]["row_count"] == 0


def test_validate_research_report_file_allows_generic_scenario_markdown_value_drift(tmp_path):
    report_path = tmp_path / "report.json"
    (tmp_path / "execution_summary.json").write_text(
        json.dumps(
            {
                "scenario_score_rows": [
                    {
                        "scenario": "bear",
                        "indicator": "Labor stress",
                        "source_key": "category_scores.Labor",
                        "value": 44.0,
                        "score": -1.2,
                        "direction": "at_or_above",
                        "threshold": 65.0,
                        "basis": "75th percentile of labor stress history",
                        "confidence": "medium",
                        "note": "Data revisions.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    report_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "job_id": "job-1",
                "created_at": "2026-05-14T00:00:00+00:00",
                "query": "Build a recession risk dashboard with base, bull, and bear scenarios.",
                "title": "Scenario Dashboard",
                "executive_summary": "Scenario risk is balanced.",
                "markdown": (
                    "## Executive Summary\nScenario risk is balanced.\n\n"
                    "## Scenario Table\n\n"
                    "| Scenario | Assumptions | Indicator Triggers | Confidence | Uncertainty Notes |\n"
                    "| --- | --- | --- | --- | --- |\n"
                    "| base | Growth slows but avoids contraction | Unemployment above 5.0% | medium | Revision risk. |\n"
                    "| bull | Inflation cools | Spreads narrow | low | Policy lags. |\n"
                    "| bear | Labor cracks | Labor stress >= 65.00 | medium | Timing risk. |\n\n"
                    "## Research Query\nBuild a recession risk dashboard with base, bull, and bear scenarios."
                ),
                "charts": {},
                "data_sources": [],
                "metadata": {
                    "analysis_type": "macro_indicator",
                    "chart_count": 0,
                    "word_count": 50,
                },
            }
        ),
        encoding="utf-8",
    )
    runtime = SimpleNamespace(context=SimpleNamespace(job_id="job-1", output_dir=str(tmp_path)))

    gate = json.loads(
        validate_research_report_file.func(
            runtime=runtime,
            report_json_path=str(report_path),
        )
    )

    assert gate["passes_gate"] is True
    assert gate["blockers"] == []


def test_validate_research_report_file_rejects_zero_charts_for_chart_query(tmp_path):
    report_path = tmp_path / "report.json"
    report_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "job_id": "job-1",
                "created_at": "2026-04-29T00:00:00+00:00",
                "query": "Build a compact dashboard with charts showing consumer stress.",
                "title": "Consumer Stress Dashboard",
                "executive_summary": "No chart artifacts were produced.",
                "markdown": (
                    "## Executive Summary\nNo chart artifacts were produced.\n\n"
                    "## Research Query\nBuild a compact dashboard with charts showing consumer stress."
                ),
                "charts": {},
                "data_sources": [],
                "metadata": {
                    "analysis_type": "macro_indicator",
                    "chart_count": 0,
                    "word_count": 12,
                },
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
    assert gate["blockers"] == [
        "query requested charts but report.json contains zero chart definitions"
    ]


def test_validate_research_report_file_does_not_strip_broken_chart_markers_for_chart_query(
    tmp_path,
):
    report_path = tmp_path / "report.json"
    report_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "job_id": "job-1",
                "created_at": "2026-04-29T00:00:00+00:00",
                "query": "Show charts for inflation and labor stress.",
                "title": "Macro Chart Report",
                "executive_summary": "Inflation and labor were reviewed.",
                "markdown": (
                    "## Executive Summary\nInflation and labor were reviewed.\n\n"
                    "<!-- CHART:inflation_replay -->\n\n"
                    "<!-- CHART:labor_replay -->\n\n"
                    "## Research Query\nShow charts for inflation and labor stress."
                ),
                "charts": {
                    "inflation_replay": {
                        "id": "inflation_replay",
                        "type": "line",
                        "title": "Inflation",
                        "description": "Inflation over time.",
                        "xAxisKey": "date",
                        "series": [
                            {"dataKey": "cpi", "label": "CPI", "color": "#2563eb"}
                        ],
                        "data": [{"date": "2026-01-01", "cpi": 3.0}],
                    }
                },
                "data_sources": [],
                "metadata": {
                    "analysis_type": "macro_indicator",
                    "chart_count": 2,
                    "word_count": 12,
                },
            }
        ),
        encoding="utf-8",
    )
    runtime = SimpleNamespace(context=SimpleNamespace(job_id="job-1", output_dir=str(tmp_path)))

    gate = json.loads(
        validate_research_report_file.func(
            runtime=runtime,
            report_json_path=str(report_path),
        )
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert gate["passes_gate"] is False
    assert gate["charts"]["broken_references"] == ["labor_replay"]
    assert "broken chart references" in gate["blockers"][0]
    assert "<!-- CHART:labor_replay -->" in report["markdown"]


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


def test_validate_research_report_file_rejects_duplicate_chart_markers(tmp_path):
    report_path = tmp_path / "report.json"
    report_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "job_id": "job-1",
                "created_at": "2026-04-28T00:00:00+00:00",
                "query": "Build a chart report.",
                "title": "Chart Report",
                "executive_summary": "Forecast was charted.",
                "markdown": (
                    "## Executive Summary\nForecast was charted.\n\n"
                    "<!-- CHART:forecast_band -->\n"
                    "<!-- CHART:forecast_band -->\n\n"
                    "## Research Query\nBuild a chart report."
                ),
                "charts": {
                    "forecast_band": {
                        "id": "forecast_band",
                        "type": "line",
                        "title": "Forecast Band",
                        "description": "Forecast path.",
                        "xAxisKey": "date",
                        "series": [
                            {
                                "dataKey": "forecast",
                                "label": "Forecast",
                                "color": "#2563eb",
                            }
                        ],
                        "data": [{"date": "2026-01", "forecast": 4.1}],
                    }
                },
                "data_sources": [],
                "metadata": {
                    "analysis_type": "macro_indicator",
                    "chart_count": 2,
                    "word_count": 12,
                },
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
    assert gate["charts"]["duplicate_markers"] == ["forecast_band"]
    assert "duplicate chart markers" in gate["blockers"][0]


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


def test_validate_research_report_file_rejects_duplicate_chart_axis_rows(tmp_path):
    report_path = tmp_path / "report.json"
    report_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "job_id": "job-1",
                "created_at": "2026-04-28T00:00:00+00:00",
                "query": "Show a chart of the yield spread.",
                "title": "Yield Spread",
                "executive_summary": "The curve remains inverted.",
                "markdown": (
                    "## Executive Summary\nThe curve remains inverted.\n\n"
                    "<!-- CHART:yield_spread -->\n\n"
                    "## Research Query\nShow a chart of the yield spread."
                ),
                "charts": {
                    "yield_spread": {
                        "id": "yield_spread",
                        "type": "line",
                        "title": "Yield Spread",
                        "description": "Monthly yield spread.",
                        "xAxisKey": "date",
                        "series": [
                            {
                                "dataKey": "spread",
                                "label": "10Y-3M",
                                "color": "#3b82f6",
                            }
                        ],
                        "data": [
                            {"date": "2026-01-01", "spread": -1.1},
                            {"date": "2026-01-01", "spread": -1.0},
                            {"date": "2026-02-01", "spread": -0.9},
                        ],
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
    assert gate["chart_semantics"]["blockers"]["yield_spread"] == [
        "1 duplicate x-axis rows may render ambiguously"
    ]
    assert "chart data semantics audit" in gate["blockers"][0]


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


def test_technical_writer_middleware_returns_quant_failure_for_zero_chart_gate():
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
                        "chart_count": 0,
                        "validation_issues": [],
                    }
                ),
                name="write_research_report",
                tool_call_id="call-write",
            ),
            ToolMessage(
                content=json.dumps(
                    {
                        "passes_gate": False,
                        "charts": {"defined_charts": []},
                        "blockers": [
                            "query requested charts but report.json contains zero chart definitions"
                        ],
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
    assert handoff["status"] == "failed"
    assert handoff["report_json"] == "/tmp/outputs/job-1/report.json"
    assert handoff["required_upstream"] == "quant-developer"
    assert handoff["chart_ids"] == []
    assert "zero chart definitions" in handoff["reason"]


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

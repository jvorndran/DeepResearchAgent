from agents.technical_writer.tools import _normalize_chart_definitions
from core.report_schema import ResearchReport


def test_normalizes_quant_legacy_axis_chart_keys_for_report_schema():
    charts = {
        "chart_1": {
            "chart_id": "chart_1",
            "chart_type": "composed",
            "title": "Inflation vs Policy Rate",
            "description": "Headline CPI, core CPI, and fed funds rate.",
            "x_axis": {"data_key": "date", "label": "Date"},
            "series": [
                {
                    "dataKey": "headline_yoy",
                    "label": "Headline CPI YoY",
                    "color": "#3b82f6",
                    "type": "line",
                    "yAxisId": "left",
                }
            ],
            "data": [{"date": "2026-03", "headline_yoy": 3.26}],
        }
    }

    normalized = _normalize_chart_definitions(charts)

    assert normalized["chart_1"]["type"] == "composed"
    assert normalized["chart_1"]["xAxisKey"] == "date"

    # Regression check: the normalized shape must satisfy the report schema
    # before the writer tries to persist report.json.
    ResearchReport(
        schema_version=1,
        job_id="job-test",
        created_at="2026-04-28T00:00:00+00:00",
        query="Compare inflation and policy rates.",
        title="Inflation vs Policy Rate",
        executive_summary="Headline CPI and policy rates were compared.",
        markdown="## Executive Summary\nSummary.\n\n<!-- CHART:chart_1 -->\n\n## Research Query\nQuery.",
        charts=normalized,
        data_sources=[],
        metadata={"analysis_type": "correlation_analysis", "chart_count": 1, "word_count": 8},
    )


def test_normalizes_panel_axis_data_dict_for_report_schema():
    charts = {
        "consumer_stress_dashboard": {
            "id": "consumer_stress_dashboard",
            "type": "composed",
            "title": "Consumer Stress Dashboard",
            "description": "Panel chart for savings, sentiment, and wages.",
            "xAxisKey": "date",
            "series": [
                {
                    "dataKey": "psavert",
                    "label": "Personal Saving Rate",
                    "color": "#3b82f6",
                    "type": "line",
                },
                {
                    "dataKey": "umcsent",
                    "label": "Consumer Sentiment",
                    "color": "#f59e0b",
                    "type": "line",
                },
            ],
            "data": {
                "saving_panel": {
                    "data": [
                        {"date": "2026-01-01", "psavert": 4.5},
                        {"date": "2026-02-01", "psavert": 4.0},
                    ]
                },
                "sentiment_panel": {
                    "data": [
                        {"date": "2026-01-01", "umcsent": 56.4},
                        {"date": "2026-02-01", "umcsent": 56.6},
                    ]
                },
            },
        }
    }

    normalized = _normalize_chart_definitions(charts)
    chart = normalized["consumer_stress_dashboard"]

    assert chart["data"] == [
        {"date": "2026-01-01", "psavert": 4.5, "umcsent": 56.4},
        {"date": "2026-02-01", "psavert": 4.0, "umcsent": 56.6},
    ]

    ResearchReport(
        schema_version=1,
        job_id="job-test",
        created_at="2026-04-28T00:00:00+00:00",
        query="Are consumers under stress?",
        title="Consumer Stress Dashboard",
        executive_summary="Savings and sentiment were compared.",
        markdown=(
            "## Executive Summary\nSummary.\n\n"
            "<!-- CHART:consumer_stress_dashboard -->\n\n"
            "## Research Query\nQuery."
        ),
        charts=normalized,
        data_sources=[],
        metadata={"analysis_type": "macro_indicator", "chart_count": 1, "word_count": 8},
    )


def test_normalizes_quant_layout_axis_chart_for_report_schema():
    charts = {
        "all_three_series": {
            "chart_id": "all_three_series",
            "chart_type": "line",
            "data": [
                {
                    "date": "2026-03-01",
                    "headline_cpi_yoy_pct": 3.29,
                    "core_cpi_yoy_pct": 2.60,
                    "fed_funds_rate_pct": 3.64,
                }
            ],
            "layout": {
                "title": "Headline CPI, Core CPI, and Fed Funds Rate",
                "description": "Monthly YoY inflation and effective federal funds rate.",
                "xAxisKey": "date",
                "series": [
                    {
                        "dataKey": "headline_cpi_yoy_pct",
                        "label": "Headline CPI YoY %",
                        "color": "#f59e0b",
                    },
                    {
                        "dataKey": "core_cpi_yoy_pct",
                        "label": "Core CPI YoY %",
                        "color": "#10b981",
                    },
                    {
                        "dataKey": "fed_funds_rate_pct",
                        "label": "Fed Funds Rate %",
                        "color": "#3b82f6",
                    },
                ],
            },
        }
    }

    normalized = _normalize_chart_definitions(charts)
    chart = normalized["all_three_series"]

    assert chart["type"] == "line"
    assert chart["title"] == "Headline CPI, Core CPI, and Fed Funds Rate"
    assert chart["description"] == "Monthly YoY inflation and effective federal funds rate."
    assert chart["xAxisKey"] == "date"
    assert [series["dataKey"] for series in chart["series"]] == [
        "headline_cpi_yoy_pct",
        "core_cpi_yoy_pct",
        "fed_funds_rate_pct",
    ]

    ResearchReport(
        schema_version=1,
        job_id="job-test",
        created_at="2026-04-28T00:00:00+00:00",
        query="Compare inflation and policy rates.",
        title="Inflation vs Policy Rate",
        executive_summary="Headline CPI, core CPI, and policy rates were compared.",
        markdown=(
            "## Executive Summary\nSummary.\n\n"
            "<!-- CHART:all_three_series -->\n\n"
            "## Research Query\nQuery."
        ),
        charts=normalized,
        data_sources=[],
        metadata={"analysis_type": "macro_indicator", "chart_count": 1, "word_count": 8},
    )


def test_normalizes_pascal_case_recharts_axis_shape_for_report_schema():
    charts = {
        "yield_curve_spread": {
            "id": "yield_curve_spread",
            "type": "LineChart",
            "title": "Yield Curve Spread",
            "description": "Daily 10-year minus 2-year Treasury yield spread.",
            "data": [{"date": "2026-04-28", "spread": 0.71}],
            "xAxis": {"dataKey": "date"},
            "yAxis": {"label": "Percent"},
            "series": [
                {
                    "dataKey": "spread",
                    "name": "10Y-2Y Spread",
                    "color": "#3b82f6",
                }
            ],
        },
        "dashboard_summary": {
            "id": "dashboard_summary",
            "type": "BarChart",
            "title": "Dashboard Summary",
            "description": "Composite recession-risk scores.",
            "data": [{"indicator": "Composite", "score": 15.72}],
            "xAxis": {"dataKey": "indicator"},
            "series": [
                {
                    "dataKey": "score",
                    "name": "Risk Score",
                    "color": "#f59e0b",
                }
            ],
        },
    }

    normalized = _normalize_chart_definitions(charts)

    assert normalized["yield_curve_spread"]["type"] == "line"
    assert normalized["yield_curve_spread"]["xAxisKey"] == "date"
    assert normalized["yield_curve_spread"]["series"] == [
        {
            "dataKey": "spread",
            "name": "10Y-2Y Spread",
            "color": "#3b82f6",
            "label": "10Y-2Y Spread",
        }
    ]
    assert normalized["dashboard_summary"]["type"] == "bar"
    assert normalized["dashboard_summary"]["xAxisKey"] == "indicator"
    assert normalized["dashboard_summary"]["series"][0]["label"] == "Risk Score"

    ResearchReport(
        schema_version=1,
        job_id="job-test",
        created_at="2026-04-28T00:00:00+00:00",
        query="Build a recession risk dashboard.",
        title="Recession Risk Dashboard",
        executive_summary="Recession risk indicators were compared.",
        markdown=(
            "## Executive Summary\nSummary.\n\n"
            "<!-- CHART:yield_curve_spread -->\n"
            "<!-- CHART:dashboard_summary -->\n\n"
            "## Research Query\nQuery."
        ),
        charts=normalized,
        data_sources=[],
        metadata={"analysis_type": "macro_indicator", "chart_count": 2, "word_count": 8},
    )


def test_normalizes_legacy_composite_chart_type_to_composed_for_report_schema():
    charts = {
        "yield_curve_fed_funds": {
            "id": "yield_curve_fed_funds",
            "title": "Yield Curve Spread (10Y-2Y) & Fed Funds Rate",
            "description": "10-year minus 2-year Treasury spread versus fed funds.",
            "chart_type": "Composite",
            "data": [
                {"date": "2026-02-28", "t10y2y": 0.42, "fedfunds": 4.33},
                {"date": "2026-03-31", "t10y2y": 0.51, "fedfunds": 3.64},
            ],
            "xAxis": {"dataKey": "date"},
            "series": [
                {
                    "dataKey": "t10y2y",
                    "label": "10Y-2Y Spread",
                    "color": "#f59e0b",
                    "yAxisId": "left",
                },
                {
                    "dataKey": "fedfunds",
                    "label": "Fed Funds Rate",
                    "color": "#ef4444",
                    "yAxisId": "right",
                },
            ],
        }
    }

    normalized = _normalize_chart_definitions(charts)
    chart = normalized["yield_curve_fed_funds"]

    assert chart["type"] == "composed"
    assert chart["xAxisKey"] == "date"

    ResearchReport(
        schema_version=1,
        job_id="job-test",
        created_at="2026-04-28T00:00:00+00:00",
        query="Build a recession risk dashboard.",
        title="Recession Risk Dashboard",
        executive_summary="Recession risk indicators were compared.",
        markdown=(
            "## Executive Summary\nSummary.\n\n"
            "<!-- CHART:yield_curve_fed_funds -->\n\n"
            "## Research Query\nQuery."
        ),
        charts=normalized,
        data_sources=[],
        metadata={"analysis_type": "macro_indicator", "chart_count": 1, "word_count": 8},
    )


def test_normalizes_quant_multiline_and_linewithzones_chart_types_for_report_schema():
    charts = {
        "chart1": {
            "chart_id": "chart1",
            "chart_type": "MultiLine",
            "title": "Macro Stress Indicators",
            "description": "Normalized consumer stress indicators over time.",
            "data": [
                {
                    "date": "2026-01",
                    "unemployment_norm": 44.2,
                    "sentiment_norm": 72.1,
                }
            ],
        },
        "chart2": {
            "chart_id": "chart2",
            "chart_type": "LineWithZones",
            "title": "Consumer Stress Index",
            "description": "Composite stress index with regime zones.",
            "data": [{"date": "2026-01", "stress_index": 0.51}],
            "series": [
                {
                    "dataKey": "stress_index",
                    "label": "Stress Index",
                    "color": "#ef4444",
                }
            ],
            "referenceAreas": [
                {"y1": 0.4, "y2": 1.0, "label": "High stress", "fill": "#fee2e2"}
            ],
        },
    }

    normalized = _normalize_chart_definitions(charts)

    assert normalized["chart1"]["type"] == "line"
    assert normalized["chart1"]["xAxisKey"] == "date"
    assert [item["dataKey"] for item in normalized["chart1"]["series"]] == [
        "unemployment_norm",
        "sentiment_norm",
    ]
    assert normalized["chart2"]["type"] == "line"
    assert normalized["chart2"]["xAxisKey"] == "date"
    assert normalized["chart2"]["referenceAreas"][0]["label"] == "High stress"

    ResearchReport(
        schema_version=1,
        job_id="job-test",
        created_at="2026-04-28T00:00:00+00:00",
        query="Are US consumers under stress regionally?",
        title="Regional Consumer Stress",
        executive_summary="Consumer stress indicators were compared.",
        markdown=(
            "## Executive Summary\nSummary.\n\n"
            "<!-- CHART:chart1 -->\n"
            "<!-- CHART:chart2 -->\n\n"
            "## Research Query\nQuery."
        ),
        charts=normalized,
        data_sources=[],
        metadata={"analysis_type": "macro_indicator", "chart_count": 2, "word_count": 8},
    )


def test_normalizes_recharts_children_axis_shape_for_report_schema():
    charts = {
        "yield_curve_inversions": {
            "chart_type": "LineChart",
            "data": [{"date": "1986-01-31", "T10Y3M": 1.89}],
            "children": [
                {"type": "XAxis", "props": {"dataKey": "date"}},
                {"type": "YAxis"},
                {"type": "Tooltip"},
                {"type": "Legend"},
                {
                    "type": "Line",
                    "props": {
                        "dataKey": "T10Y3M",
                        "stroke": "#3b82f6",
                        "dot": False,
                        "name": "10Y-3M Spread",
                    },
                },
            ],
        },
        "lead_times_table": {
            "chart_type": "BarChart",
            "data": [{"recession": "1990-1991", "T10Y3M Lead": 13}],
            "children": [
                {"type": "XAxis", "props": {"dataKey": "recession"}},
                {"type": "YAxis"},
                {"type": "Tooltip"},
                {"type": "Legend"},
                {
                    "type": "Bar",
                    "props": {
                        "dataKey": "T10Y3M Lead",
                        "fill": "#3b82f6",
                    },
                },
            ],
        },
    }

    normalized = _normalize_chart_definitions(charts)

    assert normalized["yield_curve_inversions"]["type"] == "line"
    assert normalized["yield_curve_inversions"]["title"] == "Yield Curve Inversions"
    assert normalized["yield_curve_inversions"]["xAxisKey"] == "date"
    assert normalized["yield_curve_inversions"]["series"] == [
        {
            "dataKey": "T10Y3M",
            "label": "10Y-3M Spread",
            "color": "#3b82f6",
            "type": "line",
        }
    ]
    assert normalized["lead_times_table"]["type"] == "bar"
    assert normalized["lead_times_table"]["xAxisKey"] == "recession"
    assert normalized["lead_times_table"]["series"][0]["label"] == "T10Y3M Lead"

    ResearchReport(
        schema_version=1,
        job_id="job-test",
        created_at="2026-04-28T00:00:00+00:00",
        query="Analyze leading recession indicators.",
        title="Leading Recession Indicators",
        executive_summary="Yield spread lead times were compared.",
        markdown=(
            "## Executive Summary\nSummary.\n\n"
            "<!-- CHART:yield_curve_inversions -->\n"
            "<!-- CHART:lead_times_table -->\n\n"
            "## Research Query\nQuery."
        ),
        charts=normalized,
        data_sources=[],
        metadata={"analysis_type": "macro_indicator", "chart_count": 2, "word_count": 8},
    )


def test_preserves_supported_radar_chart_for_report_schema():
    charts = {
        "period_comparison_radar": {
            "chart_type": "radar",
            "title": "Period Comparison - Key Indicators",
            "description": "Radar chart comparing average macro indicators across periods.",
            "data": [
                {
                    "period": "1970s",
                    "CPI_YoY": 7.77,
                    "Unemployment": 6.67,
                    "Fed_Funds_Rate": 8.69,
                },
                {
                    "period": "Post-Pandemic Cycle",
                    "CPI_YoY": 4.49,
                    "Unemployment": 3.88,
                    "Fed_Funds_Rate": 4.02,
                },
            ],
        }
    }

    normalized = _normalize_chart_definitions(charts)
    chart = normalized["period_comparison_radar"]

    assert chart["type"] == "radar"
    assert chart["angleKey"] == "period"
    assert [series["dataKey"] for series in chart["series"]] == [
        "CPI_YoY",
        "Unemployment",
        "Fed_Funds_Rate",
    ]

    ResearchReport(
        schema_version=1,
        job_id="job-test",
        created_at="2026-04-28T00:00:00+00:00",
        query="Compare macro regimes.",
        title="Macro Regime Comparison",
        executive_summary="Macro regimes were compared.",
        markdown=(
            "## Executive Summary\nSummary.\n\n"
            "<!-- CHART:period_comparison_radar -->\n\n"
            "## Research Query\nQuery."
        ),
        charts=normalized,
        data_sources=[],
        metadata={"analysis_type": "macro_indicator", "chart_count": 1, "word_count": 8},
    )


def test_drops_table_artifacts_from_report_chart_definitions():
    charts = {
        "inflation_trend": {
            "type": "line",
            "title": "Inflation Trend",
            "description": "Annual inflation by country.",
            "xAxisKey": "year",
            "series": [
                {"dataKey": "usa", "label": "United States", "color": "#3b82f6"},
            ],
            "data": [{"year": "2024", "usa": 2.9}],
        },
        "avg_table": {
            "type": "table",
            "title": "Average Inflation and Growth",
            "columns": ["country", "inflation", "growth"],
            "data": [{"country": "United States", "inflation": 2.6, "growth": 2.4}],
        },
    }

    normalized = _normalize_chart_definitions(charts)

    assert list(normalized) == ["inflation_trend"]

    ResearchReport(
        schema_version=1,
        job_id="job-test",
        created_at="2026-04-28T00:00:00+00:00",
        query="Compare annual inflation and growth.",
        title="Inflation and Growth",
        executive_summary="Annual inflation and growth were compared.",
        markdown=(
            "## Executive Summary\nSummary.\n\n"
            "<!-- CHART:inflation_trend -->\n\n"
            "## Research Query\nQuery."
        ),
        charts=normalized,
        data_sources=[],
        metadata={"analysis_type": "macro_indicator", "chart_count": 1, "word_count": 8},
    )


def test_normalizes_legacy_pie_size_to_value_for_report_schema():
    charts = {
        "composite_verdict": {
            "id": "composite_verdict",
            "type": "pie",
            "title": "Composite Assessment by Dimension",
            "description": "Overall verdict: soft landing.",
            "data": [
                {"name": "Labor: Hard Landing", "size": 1},
                {"name": "Inflation: Soft Landing", "size": 1, "color": "#10b981"},
            ],
        }
    }

    normalized = _normalize_chart_definitions(charts)

    assert normalized["composite_verdict"]["data"] == [
        {"name": "Labor: Hard Landing", "size": 1, "value": 1},
        {"name": "Inflation: Soft Landing", "size": 1, "color": "#10b981", "value": 1},
    ]

    ResearchReport(
        schema_version=1,
        job_id="job-test",
        created_at="2026-04-28T00:00:00+00:00",
        query="Classify the macro regime.",
        title="Macro Regime Assessment",
        executive_summary="The regime was classified across dimensions.",
        markdown=(
            "## Executive Summary\nSummary.\n\n"
            "<!-- CHART:composite_verdict -->\n\n"
            "## Research Query\nQuery."
        ),
        charts=normalized,
        data_sources=[],
        metadata={"analysis_type": "macro_indicator", "chart_count": 1, "word_count": 8},
    )


def test_normalizes_new_chart_type_aliases_for_report_schema():
    charts = {
        "radial_components": {
            "chart_type": "radial_bar",
            "title": "Radial Components",
            "description": "Component counts.",
            "data": [{"name": "Labor", "size": 12}],
        },
        "signal_flow": {
            "chart_type": "sankeychart",
            "title": "Signal Flow",
            "description": "Flow decomposition.",
            "data": {
                "nodes": [{"name": "Inputs"}, {"name": "Labor"}],
                "links": [{"source": 0, "target": 1, "value": 12}],
            },
        },
        "hierarchy": {
            "chart_type": "sunburstchart",
            "title": "Hierarchy",
            "description": "Nested contributions.",
            "data": {"name": "Total", "children": [{"name": "Labor", "value": 40}]},
        },
    }

    normalized = _normalize_chart_definitions(charts)

    assert normalized["radial_components"]["type"] == "radialBar"
    assert normalized["radial_components"]["data"][0]["value"] == 12
    assert normalized["signal_flow"]["type"] == "sankey"
    assert normalized["hierarchy"]["type"] == "sunburst"

    ResearchReport(
        schema_version=1,
        job_id="job-test",
        created_at="2026-04-28T00:00:00+00:00",
        query="Show macro components.",
        title="Macro Components",
        executive_summary="Macro components were charted.",
        markdown=(
            "## Executive Summary\nSummary.\n\n"
            "<!-- CHART:radial_components -->\n"
            "<!-- CHART:signal_flow -->\n"
            "<!-- CHART:hierarchy -->\n\n"
            "## Research Query\nQuery."
        ),
        charts=normalized,
        data_sources=[],
        metadata={"analysis_type": "macro_indicator", "chart_count": 3, "word_count": 8},
    )

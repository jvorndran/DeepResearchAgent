import json

from agents.technical_writer.chart_audit import run_report_chart_audit


def _write_report(
    tmp_path,
    chart,
    *,
    analysis_type="macro_indicator",
    data_sources=None,
):
    report_path = tmp_path / "report.json"
    report_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "job_id": "job-chart-audit",
                "created_at": "2026-05-01T00:00:00+00:00",
                "query": "Build a macro chart report.",
                "title": "Macro Chart Report",
                "executive_summary": "Macro indicators were charted.",
                "markdown": (
                    "## Executive Summary\nMacro indicators were charted.\n\n"
                    f"<!-- CHART:{chart['id']} -->\n\n"
                    "## Research Query\nBuild a macro chart report."
                ),
                "charts": {chart["id"]: chart},
                "data_sources": data_sources or [],
                "metadata": {
                    "analysis_type": analysis_type,
                    "chart_count": 1,
                    "word_count": 12,
                },
            }
        ),
        encoding="utf-8",
    )
    return report_path


def test_report_chart_audit_accepts_renderable_axis_chart(tmp_path):
    report_path = _write_report(
        tmp_path,
        {
            "id": "policy_inflation",
            "type": "composed",
            "title": "Policy And Inflation",
            "description": "Fed funds and inflation over time.",
            "xAxisKey": "date",
            "series": [
                {
                    "dataKey": "fed_funds",
                    "label": "Fed Funds",
                    "color": "#2563eb",
                    "type": "line",
                    "yAxisId": "left",
                },
                {
                    "dataKey": "headline_cpi",
                    "label": "Headline CPI",
                    "color": "#f59e0b",
                    "type": "bar",
                    "yAxisId": "right",
                },
            ],
            "data": [
                {"date": "2025-01-01", "fed_funds": 4.33, "headline_cpi": 2.9},
                {"date": "2025-02-01", "fed_funds": 4.33, "headline_cpi": 3.0},
            ],
        },
    )

    audit = json.loads(run_report_chart_audit(str(report_path)))

    assert audit["passes_audit"] is True
    assert audit["chart_render"]["valid"] is True
    assert audit["chart_semantics"]["valid"] is True


def test_report_chart_audit_warns_when_macro_chart_lacks_provenance(tmp_path):
    report_path = _write_report(
        tmp_path,
        {
            "id": "policy_inflation",
            "type": "composed",
            "title": "Policy And Inflation",
            "description": "Fed funds and inflation over time.",
            "xAxisKey": "date",
            "series": [
                {"dataKey": "fed_funds", "label": "Fed Funds", "color": "#2563eb"},
            ],
            "data": [{"date": "2025-01", "fed_funds": 4.33}],
        },
    )

    audit = json.loads(run_report_chart_audit(str(report_path)))

    assert audit["passes_audit"] is True
    assert audit["chart_semantics"]["warnings"]["policy_inflation"] == [
        "macro chart lacks provenance metadata"
    ]


def test_report_chart_audit_warns_when_custom_macro_source_chart_lacks_provenance(
    tmp_path,
):
    report_path = _write_report(
        tmp_path,
        {
            "id": "policy_inflation",
            "type": "composed",
            "title": "Policy And Inflation",
            "description": "Fed funds and inflation over time.",
            "xAxisKey": "date",
            "series": [
                {"dataKey": "fed_funds", "label": "Fed Funds", "color": "#2563eb"},
            ],
            "data": [{"date": "2025-01", "fed_funds": 4.33}],
        },
        analysis_type="custom",
        data_sources=[
            {
                "provider": "FRED",
                "description": "Federal Reserve Economic Data time series.",
                "series_ids": ["FEDFUNDS"],
            }
        ],
    )

    audit = json.loads(run_report_chart_audit(str(report_path)))

    assert audit["passes_audit"] is True
    assert audit["chart_semantics"]["warnings"]["policy_inflation"] == [
        "macro chart lacks provenance metadata"
    ]


def test_report_chart_audit_rejects_display_window_provenance_mismatch(tmp_path):
    report_path = _write_report(
        tmp_path,
        {
            "id": "yield_spread",
            "type": "line",
            "title": "Yield Spread",
            "description": "Monthly yield spread.",
            "xAxisKey": "date",
            "series": [{"dataKey": "spread", "label": "10Y-2Y", "color": "#2563eb"}],
            "data": [
                {"date": "2026-01", "spread": -0.1},
                {"date": "2026-02", "spread": 0.2},
            ],
            "provenance": {
                "source_series": ["T10Y2Y"],
                "raw_latest_observation": {"T10Y2Y": "2026-02-15"},
                "displayed_window": {"start": "2026-01", "end": "2026-03"},
                "displayed_latest_label": "2026-03",
                "resampling": "daily observations shown as monthly labels",
            },
        },
    )

    audit = json.loads(run_report_chart_audit(str(report_path)))

    assert audit["passes_audit"] is False
    assert audit["chart_semantics"]["blockers"]["yield_spread"] == [
        "displayed_window.end=2026-03 does not match last x-axis value 2026-02",
        "displayed_latest_label=2026-03 does not match last x-axis value 2026-02",
    ]


def test_report_chart_audit_rejects_raw_latest_provenance_outpaced_by_display_label(
    tmp_path,
):
    report_path = _write_report(
        tmp_path,
        {
            "id": "yield_spread",
            "type": "line",
            "title": "Yield Spread",
            "description": "Monthly yield spread.",
            "xAxisKey": "date",
            "series": [{"dataKey": "spread", "label": "10Y-2Y", "color": "#2563eb"}],
            "data": [
                {"date": "2026-04-30", "spread": 0.3},
                {"date": "2026-05-31", "spread": 0.5},
            ],
            "provenance": {
                "source_series": ["T10Y2Y"],
                "raw_latest_observation": {"T10Y2Y": "2026-05-15"},
                "displayed_window": {"start": "2026-04-30", "end": "2026-05-31"},
                "displayed_latest_label": "2026-05-31",
                "resampling": "daily observations shown as monthly labels",
            },
        },
    )

    audit = json.loads(run_report_chart_audit(str(report_path)))

    assert audit["passes_audit"] is False
    assert audit["chart_semantics"]["blockers"]["yield_spread"] == [
        "displayed_latest_label=2026-05-31 outpaces "
        "raw_latest_observation.T10Y2Y=2026-05-15"
    ]


def test_report_chart_audit_accepts_per_series_latest_labels_with_staggered_endpoints(
    tmp_path,
):
    report_path = _write_report(
        tmp_path,
        {
            "id": "sentiment_labor",
            "type": "line",
            "title": "Sentiment And Labor",
            "description": "Sentiment and payrolls with staggered latest dates.",
            "xAxisKey": "date",
            "series": [
                {"dataKey": "payrolls", "label": "Payrolls", "color": "#2563eb"},
                {"dataKey": "sentiment", "label": "Sentiment", "color": "#f59e0b"},
            ],
            "data": [
                {"date": "2026-01", "payrolls": 151.1, "sentiment": 72.0},
                {"date": "2026-02", "payrolls": 151.3, "sentiment": 74.0},
                {"date": "2026-03", "payrolls": None, "sentiment": 76.0},
            ],
            "provenance": {
                "source_series": {
                    "payrolls": "PAYEMS",
                    "sentiment": "UMCSENT",
                },
                "raw_latest_observation": {
                    "PAYEMS": "2026-02-06",
                    "UMCSENT": "2026-03-15",
                },
                "displayed_window": {"start": "2026-01", "end": "2026-03"},
                "displayed_latest_label": {
                    "PAYEMS": "2026-02",
                    "UMCSENT": "2026-03",
                },
                "resampling": "monthly labels preserve each source series endpoint",
            },
        },
    )

    audit = json.loads(run_report_chart_audit(str(report_path)))

    assert audit["passes_audit"] is True
    assert "sentiment_labor" not in audit["chart_semantics"]["blockers"]


def test_report_chart_audit_accepts_broad_governed_chart_families(tmp_path):
    charts = {
        "radar_profile": {
            "id": "radar_profile",
            "type": "radar",
            "title": "Risk Profile",
            "description": "Normalized risk dimensions.",
            "angleKey": "metric",
            "series": [{"dataKey": "score", "label": "Score", "color": "#2563eb"}],
            "data": [{"metric": "Labor", "score": 70}, {"metric": "Credit", "score": 45}],
        },
        "radial_components": {
            "id": "radial_components",
            "type": "radialBar",
            "title": "Component Incidence",
            "description": "Positive component counts.",
            "data": [{"name": "Labor", "value": 12, "color": "#2563eb"}],
        },
        "filter_funnel": {
            "id": "filter_funnel",
            "type": "funnel",
            "title": "Filter Funnel",
            "description": "Positive staged counts.",
            "data": [{"name": "All observations", "value": 120, "color": "#2563eb"}],
        },
        "contribution_treemap": {
            "id": "contribution_treemap",
            "type": "treemap",
            "title": "Contribution Treemap",
            "description": "Contribution hierarchy.",
            "data": [{"name": "Labor", "size": 40, "color": "#2563eb"}],
        },
        "signal_flow": {
            "id": "signal_flow",
            "type": "sankey",
            "title": "Signal Flow",
            "description": "Signal flow decomposition.",
            "data": {
                "nodes": [{"name": "Inputs"}, {"name": "Labor"}],
                "links": [{"source": 0, "target": 1, "value": 12}],
            },
        },
        "contribution_sunburst": {
            "id": "contribution_sunburst",
            "type": "sunburst",
            "title": "Contribution Sunburst",
            "description": "Nested contributions.",
            "data": {"name": "Total", "children": [{"name": "Labor", "value": 40}]},
        },
    }
    report_path = tmp_path / "report.json"
    markers = "\n".join(f"<!-- CHART:{chart_id} -->" for chart_id in charts)
    report_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "job_id": "job-chart-audit",
                "created_at": "2026-05-01T00:00:00+00:00",
                "query": "Build a macro chart report.",
                "title": "Macro Chart Report",
                "executive_summary": "Macro indicators were charted.",
                "markdown": f"## Executive Summary\nSummary.\n\n{markers}\n\n## Research Query\nQuery.",
                "charts": charts,
                "data_sources": [],
                "metadata": {
                    "analysis_type": "macro_indicator",
                    "chart_count": len(charts),
                    "word_count": 12,
                },
            }
        ),
        encoding="utf-8",
    )

    audit = json.loads(run_report_chart_audit(str(report_path)))

    assert audit["passes_audit"] is True
    assert audit["chart_render"]["valid"] is True
    assert audit["chart_semantics"]["valid"] is True


def test_report_chart_audit_rejects_all_zero_radar_as_invisible(tmp_path):
    report_path = _write_report(
        tmp_path,
        {
            "id": "current_risk_profile",
            "type": "radar",
            "title": "Current Risk Profile",
            "description": "All components are currently zero.",
            "angleKey": "metric",
            "series": [{"dataKey": "score", "label": "Score", "color": "#2563eb"}],
            "data": [
                {"metric": "Curve", "score": 0},
                {"metric": "Labor", "score": 0},
            ],
        },
    )

    audit = json.loads(run_report_chart_audit(str(report_path)))

    assert audit["passes_audit"] is False
    assert audit["chart_render"]["issues"]["current_risk_profile"] == [
        "radar chart has no positive finite values and may render invisible"
    ]


def test_report_chart_audit_rejects_invalid_sankey_indexes(tmp_path):
    report_path = _write_report(
        tmp_path,
        {
            "id": "signal_flow",
            "type": "sankey",
            "title": "Signal Flow",
            "description": "Broken signal flow.",
            "data": {
                "nodes": [{"name": "Inputs"}],
                "links": [{"source": 0, "target": 2, "value": 12}],
            },
        },
    )

    audit = json.loads(run_report_chart_audit(str(report_path)))

    assert audit["passes_audit"] is False
    assert audit["chart_render"]["issues"]["signal_flow"] == [
        "sankey link 0 target index is invalid"
    ]


def test_report_chart_audit_rejects_metadata_chart_count_mismatch(tmp_path):
    report_path = _write_report(
        tmp_path,
        {
            "id": "inflation_replay",
            "type": "line",
            "title": "Inflation Replay",
            "description": "Inflation over time.",
            "xAxisKey": "date",
            "series": [
                {"dataKey": "cpi", "label": "CPI", "color": "#2563eb"},
            ],
            "data": [{"date": "2026-01-01", "cpi": 3.0}],
        },
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["metadata"]["chart_count"] = 3
    report_path.write_text(json.dumps(report), encoding="utf-8")

    audit = json.loads(run_report_chart_audit(str(report_path)))

    assert audit["passes_audit"] is False
    assert audit["chart_markers"]["chart_count_mismatch"] is True
    assert "metadata chart_count does not match" in audit["blockers"][0]


def test_report_chart_audit_rejects_duplicate_chart_markers(tmp_path):
    report_path = _write_report(
        tmp_path,
        {
            "id": "forecast_band",
            "type": "line",
            "title": "Forecast Band",
            "description": "Forecast path.",
            "xAxisKey": "date",
            "series": [{"dataKey": "forecast", "label": "Forecast", "color": "#2563eb"}],
            "data": [{"date": "2026-01", "forecast": 4.1}],
        },
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["markdown"] = report["markdown"].replace(
        "<!-- CHART:forecast_band -->",
        "<!-- CHART:forecast_band -->\n<!-- CHART:forecast_band -->",
    )
    report["metadata"]["chart_count"] = 2
    report_path.write_text(json.dumps(report), encoding="utf-8")

    audit = json.loads(run_report_chart_audit(str(report_path)))

    assert audit["passes_audit"] is False
    assert audit["chart_markers"]["duplicate_markers"] == ["forecast_band"]
    assert "duplicate chart markers" in audit["blockers"][0]


def test_report_chart_audit_rejects_stale_empty_tail_rows(tmp_path):
    report_path = _write_report(
        tmp_path,
        {
            "id": "unemployment_forecast",
            "type": "line",
            "title": "Unemployment Forecast",
            "description": "Actual unemployment with forecast overlay.",
            "xAxisKey": "date",
            "series": [{"dataKey": "unrate", "label": "UNRATE", "color": "#2563eb"}],
            "data": [
                {"date": "2026-01-01", "unrate": 4.1},
                {"date": "2026-02-01", "unrate": 4.2},
                {"date": "2026-03-01", "unrate": None},
            ],
        },
    )

    audit = json.loads(run_report_chart_audit(str(report_path)))

    assert audit["passes_audit"] is False
    assert audit["chart_semantics"]["blockers"]["unemployment_forecast"] == [
        "1 stale tail rows contain no finite series values"
    ]


def test_report_chart_audit_rejects_duplicate_axis_rows(tmp_path):
    report_path = _write_report(
        tmp_path,
        {
            "id": "yield_spread",
            "type": "line",
            "title": "Yield Spread",
            "description": "Monthly yield spread.",
            "xAxisKey": "date",
            "series": [{"dataKey": "spread", "label": "10Y-3M", "color": "#2563eb"}],
            "data": [
                {"date": "2026-01-01", "spread": -1.1},
                {"date": "2026-01-01", "spread": -1.0},
                {"date": "2026-02-01", "spread": -0.9},
            ],
        },
    )

    audit = json.loads(run_report_chart_audit(str(report_path)))

    assert audit["passes_audit"] is False
    assert audit["chart_semantics"]["blockers"]["yield_spread"] == [
        "1 duplicate x-axis rows may render ambiguously"
    ]


def test_report_chart_audit_rejects_reference_bands_outside_plotted_dates(tmp_path):
    report_path = _write_report(
        tmp_path,
        {
            "id": "recession_bands",
            "type": "line",
            "title": "Recession Bands",
            "description": "Output with recession shading.",
            "xAxisKey": "date",
            "series": [{"dataKey": "indpro", "label": "Industrial Production", "color": "#2563eb"}],
            "referenceAreas": [
                {
                    "x1": "2008-01-01",
                    "x2": "2009-06-01",
                    "label": "Great Recession",
                    "fill": "#e5e7eb",
                }
            ],
            "data": [
                {"date": "2024-01-01", "indpro": 102.1},
                {"date": "2024-02-01", "indpro": 102.3},
            ],
        },
    )

    audit = json.loads(run_report_chart_audit(str(report_path)))

    assert audit["passes_audit"] is False
    assert audit["chart_semantics"]["blockers"]["recession_bands"] == [
        "Great Recession is outside plotted x-axis range"
    ]


def test_report_chart_audit_rejects_missing_charts_when_query_requests_charts(tmp_path):
    report_path = tmp_path / "report.json"
    report_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "job_id": "job-chart-audit",
                "created_at": "2026-05-01T00:00:00+00:00",
                "query": "Build a report with charts for the macro cycle.",
                "title": "Macro Chart Report",
                "executive_summary": "No charts were produced.",
                "markdown": "## Executive Summary\nNo charts were produced.",
                "charts": {},
                "data_sources": [],
                "metadata": {
                    "analysis_type": "macro_indicator",
                    "chart_count": 0,
                    "word_count": 8,
                },
            }
        ),
        encoding="utf-8",
    )

    audit = json.loads(run_report_chart_audit(str(report_path)))

    assert audit["passes_audit"] is False
    assert audit["blockers"] == [
        "query requested charts but report.json contains zero chart definitions"
    ]


def test_report_chart_audit_rejects_missing_charts_when_dashboard_query_requests_charts(
    tmp_path,
):
    report_path = tmp_path / "report.json"
    report_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "job_id": "job-chart-audit",
                "created_at": "2026-05-01T00:00:00+00:00",
                "query": "Create a recession-dashboard report using FRED time series.",
                "title": "Recession Dashboard",
                "executive_summary": "No charts were produced.",
                "markdown": "## Executive Summary\nNo charts were produced.",
                "charts": {},
                "data_sources": [],
                "metadata": {
                    "analysis_type": "macro_indicator",
                    "chart_count": 0,
                    "word_count": 8,
                },
            }
        ),
        encoding="utf-8",
    )

    audit = json.loads(run_report_chart_audit(str(report_path)))

    assert audit["passes_audit"] is False
    assert audit["blockers"] == [
        "query requested charts but report.json contains zero chart definitions"
    ]

import json
from types import SimpleNamespace

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
    def __init__(self, tools):
        self.tools = tools

    def override(self, **kwargs):
        return _Request(kwargs["tools"])


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

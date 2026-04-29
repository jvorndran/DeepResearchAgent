import json

from agents.quality_analyst import (
    QUALITY_ANALYST_SUBAGENT,
    QUALITY_ANALYST_SYSTEM_PROMPT,
    load_report_for_review,
)


def test_quality_analyst_is_compiled_without_deepagents_filesystem_tools():
    assert QUALITY_ANALYST_SUBAGENT["name"] == "quality-analyst"
    assert "runnable" in QUALITY_ANALYST_SUBAGENT
    assert "tools" not in QUALITY_ANALYST_SUBAGENT
    assert "system_prompt" not in QUALITY_ANALYST_SUBAGENT


def test_quality_analyst_prompt_rejects_inconsistent_consistency_claims():
    assert "Consistency claims" in QUALITY_ANALYST_SYSTEM_PROMPT
    assert 'answer "yes" or "consistent"' in QUALITY_ANALYST_SYSTEM_PROMPT
    assert "near-zero or negative period/regime outcomes" in QUALITY_ANALYST_SYSTEM_PROMPT


def test_quality_analyst_prompt_rejects_unexplained_date_range_drift():
    assert "Date/range fidelity" in QUALITY_ANALYST_SYSTEM_PROMPT
    assert "since 2000" in QUALITY_ANALYST_SYSTEM_PROMPT
    assert "derived metric such as YoY growth after lookback loss" in QUALITY_ANALYST_SYSTEM_PROMPT


def test_load_report_for_review_returns_compact_review_packet(tmp_path):
    report_path = tmp_path / "report.json"
    (tmp_path / "execution_summary.json").write_text(
        json.dumps(
            {
                "statistical_summary": {"yield_leads": [13, 8, 16, 9]},
                "brief_analysis_summary": "Yield curve led the last four NBER recessions.",
                "chart_ids": ["chart_unrate"],
            }
        ),
        encoding="utf-8",
    )
    report_path.write_text(
        json.dumps(
            {
                "query": "Is labor weakening?",
                "title": "Labor Market Review",
                "executive_summary": "Mixed but not collapsing.",
                "markdown": "Summary\n\n<!-- CHART:chart_unrate -->\n\nDetails",
                "charts": [{"id": "chart_unrate"}],
                "data_sources": [{"series_id": "UNRATE"}],
                "metadata": {"word_count": 5},
            }
        ),
        encoding="utf-8",
    )

    payload = json.loads(load_report_for_review.invoke({"report_path": str(report_path)}))

    assert payload["status"] == "success"
    assert payload["title"] == "Labor Market Review"
    assert payload["chart_markers"] == ["chart_unrate"]
    assert payload["chart_ids"] == ["chart_unrate"]
    assert payload["data_sources"] == [{"series_id": "UNRATE"}]
    assert payload["execution_summary"]["status"] == "success"
    assert payload["execution_summary"]["path"].endswith("execution_summary.json")
    assert "yield_leads" in payload["execution_summary"]["statistical_summary"]
    assert payload["execution_summary"]["chart_ids"] == ["chart_unrate"]


def test_quality_analyst_prompt_uses_embedded_execution_summary_packet():
    assert "execution_summary` packet" in QUALITY_ANALYST_SYSTEM_PROMPT
    assert "includes the sibling execution summary review packet" in QUALITY_ANALYST_SYSTEM_PROMPT


def test_quality_analyst_prompt_keeps_terminal_decision_compact():
    assert "Silent review" in QUALITY_ANALYST_SYSTEM_PROMPT
    assert "Do not narrate your review" in QUALITY_ANALYST_SYSTEM_PROMPT
    assert "After `submit_quality_decision` returns" in QUALITY_ANALYST_SYSTEM_PROMPT
    assert "Never include markdown tables" in QUALITY_ANALYST_SYSTEM_PROMPT


def test_load_report_for_review_reads_chart_ids_from_report_dict(tmp_path):
    report_path = tmp_path / "report.json"
    report_path.write_text(
        json.dumps(
            {
                "query": "Is labor weakening?",
                "title": "Labor Market Review",
                "executive_summary": "Mixed but not collapsing.",
                "markdown": "Summary\n\n<!-- CHART:chart_unrate -->\n\nDetails",
                "charts": {"chart_unrate": {"id": "chart_unrate"}},
                "data_sources": [],
                "metadata": {"word_count": 5},
            }
        ),
        encoding="utf-8",
    )

    payload = json.loads(load_report_for_review.invoke({"report_path": str(report_path)}))

    assert payload["status"] == "success"
    assert payload["chart_markers"] == ["chart_unrate"]
    assert payload["chart_ids"] == ["chart_unrate"]


def test_load_report_for_review_rejects_non_report_artifacts(tmp_path):
    charts_path = tmp_path / "charts.json"
    charts_path.write_text(json.dumps({"chart_1": {}}), encoding="utf-8")

    payload = json.loads(load_report_for_review.invoke({"report_path": str(charts_path)}))

    assert payload["status"] == "error"
    assert "Expected the final report.json artifact" in payload["error"]


def test_load_report_for_review_rejects_directory_path(tmp_path):
    report_dir = tmp_path / "report.json"
    report_dir.mkdir()

    payload = json.loads(load_report_for_review.invoke({"report_path": str(report_dir)}))

    assert payload["status"] == "error"
    assert "received a directory" in payload["error"]


def test_load_report_for_review_rejects_output_directory_path(tmp_path):
    payload = json.loads(load_report_for_review.invoke({"report_path": str(tmp_path)}))

    assert payload["status"] == "error"
    assert "Expected the final report.json artifact" in payload["error"]

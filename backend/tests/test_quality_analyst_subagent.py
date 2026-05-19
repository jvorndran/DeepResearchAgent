import json

from langchain_core.messages import AIMessage, ToolMessage

from agents.quality_analyst import (
    QUALITY_ANALYST_SUBAGENT,
    QUALITY_ANALYST_SYSTEM_PROMPT,
    _normalize_terminal_quality_decision,
    load_report_for_review,
    submit_quality_decision,
)
from agents.quant_macro_stats.artifacts.artifact_fingerprints import (
    build_artifact_fingerprints,
    finalize_evidence_bundle_fingerprint_bytes,
    json_artifact_bytes,
)
from agents.quant_macro_stats.artifacts.evidence_bundle import EvidenceBundle


def _compact_text(text: str) -> str:
    return " ".join(text.split())


def _write_valid_evidence_bundle(tmp_path, chart_ids, *, artifacts=None, facts=None):
    table_ids = [f"chart_data:{chart_id}" for chart_id in chart_ids]
    payload = {
        "schema_version": 1,
        "bundle_type": "quant_evidence_bundle",
        "charts": [
            {
                "chart_id": chart_id,
                "source_table_ids": [table_id],
                "transform_ids": ["unit_test_projection"],
            }
            for chart_id, table_id in zip(chart_ids, table_ids)
        ],
        "normalized_tables": [
            {"table_id": table_id, "kind": "normalized"}
            for table_id in table_ids
        ],
        "transforms": [
            {
                "transform_id": "unit_test_projection",
                "operation": "projection",
                "source_table_ids": [table_id],
                "chart_ids": [chart_id],
            }
            for chart_id, table_id in zip(chart_ids, table_ids)
        ],
        "validation": {"valid": True, "diagnostics": []},
        "artifacts": artifacts
        or {
            "charts_json": str(tmp_path / "charts.json"),
            "execution_summary_json": str(tmp_path / "execution_summary.json"),
            "evidence_bundle_json": str(tmp_path / "evidence_bundle.json"),
        },
    }
    if facts is not None:
        payload["facts"] = facts
        payload["sources"] = [
            {"source_id": source_id}
            for source_id in dict.fromkeys(
                str(fact.get("source_key") or "").strip()
                for fact in facts
                if isinstance(fact, dict)
            )
            if source_id
        ]
    (tmp_path / "evidence_bundle.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )


def _write_fingerprinted_evidence_artifacts(
    tmp_path,
    chart_ids,
    *,
    source_files=None,
):
    charts = {
        chart_id: {"id": chart_id, "data": [{"x": 1}]}
        for chart_id in chart_ids
    }
    summary = {
        "status": "success",
        "chart_ids": chart_ids,
        "evidence_bundle_json": str(tmp_path / "evidence_bundle.json"),
    }
    charts_bytes = json_artifact_bytes(charts)
    summary_bytes = json_artifact_bytes(summary)
    (tmp_path / "charts.json").write_bytes(charts_bytes)
    (tmp_path / "execution_summary.json").write_bytes(summary_bytes)

    table_ids = [f"chart_data:{chart_id}" for chart_id in chart_ids]
    bundle = EvidenceBundle.model_validate(
        {
            "schema_version": 1,
            "bundle_type": "quant_evidence_bundle",
            "charts": [
                {
                    "chart_id": chart_id,
                    "source_table_ids": [table_id],
                    "transform_ids": [f"{chart_id}_projection"],
                }
                for chart_id, table_id in zip(chart_ids, table_ids)
            ],
            "normalized_tables": [
                {"table_id": table_id, "kind": "normalized"}
                for table_id in table_ids
            ],
            "transforms": [
                {
                    "transform_id": f"{chart_id}_projection",
                    "operation": "projection",
                    "source_table_ids": [table_id],
                    "chart_ids": [chart_id],
                }
                for chart_id, table_id in zip(chart_ids, table_ids)
            ],
            "validation": {"valid": True, "diagnostics": []},
            "artifacts": {
                "charts_json": str(tmp_path / "charts.json"),
                "execution_summary_json": str(tmp_path / "execution_summary.json"),
                "evidence_bundle_json": str(tmp_path / "evidence_bundle.json"),
                "source_files": source_files or {},
            },
        }
    )
    bundle.artifacts.fingerprints = build_artifact_fingerprints(
        charts_path=tmp_path / "charts.json",
        execution_summary_path=tmp_path / "execution_summary.json",
        evidence_bundle_path=tmp_path / "evidence_bundle.json",
        charts_bytes=charts_bytes,
        execution_summary_bytes=summary_bytes,
        source_files=bundle.artifacts.source_files,
        data_files=bundle.artifacts.data_files,
        base_dir=tmp_path,
    )
    (tmp_path / "evidence_bundle.json").write_bytes(
        finalize_evidence_bundle_fingerprint_bytes(bundle)
    )


def _write_simple_report(tmp_path, chart_id="chart_unrate"):
    report_path = tmp_path / "report.json"
    report_path.write_text(
        json.dumps(
            {
                "query": "Is labor weakening?",
                "title": "Labor Market Review",
                "executive_summary": "Mixed but not collapsing.",
                "markdown": f"Summary\n\n<!-- CHART:{chart_id} -->",
                "charts": [{"id": chart_id}],
            }
        ),
        encoding="utf-8",
    )
    return report_path


def test_quality_analyst_is_compiled_without_deepagents_filesystem_tools():
    assert QUALITY_ANALYST_SUBAGENT["name"] == "quality-analyst"
    assert "runnable" in QUALITY_ANALYST_SUBAGENT
    assert "tools" not in QUALITY_ANALYST_SUBAGENT
    assert "system_prompt" not in QUALITY_ANALYST_SUBAGENT


def test_quality_analyst_prompt_is_compact_resident_contract():
    prompt = _compact_text(QUALITY_ANALYST_SYSTEM_PROMPT)

    assert len(QUALITY_ANALYST_SYSTEM_PROMPT) < 2_350
    assert "RESIDENT CONTRACT" in prompt
    assert "Decide only from `load_report_for_review(report.json)`" in prompt
    assert "`submit_quality_decision` is terminal" in prompt
    assert "Conditional fidelity detail belongs in the review packet" in prompt
    assert "not resident prompt text" in prompt
    assert '"consistent", "always", or "guaranteed" claims' in prompt
    assert "unexplained date/range drift" in prompt
    assert "missing validation/replay" in prompt

    migrated_details = [
        "top analog, similarity scores, risk score, or issuer metrics",
        "near-zero or negative period/regime outcomes",
        "since 2000",
        "derived metric such as YoY growth after lookback loss",
        "backtest_summary",
        "assumptions, indicator triggers, and confidence/uncertainty notes",
    ]
    for detail in migrated_details:
        assert detail not in prompt


def test_load_report_for_review_returns_compact_review_packet(tmp_path):
    report_path = tmp_path / "report.json"
    (tmp_path / "execution_summary.json").write_text(
        json.dumps(
            {
                "statistical_summary": {"yield_leads": [13, 8, 16, 9]},
                "brief_analysis_summary": "Yield curve led the last four NBER recessions.",
                "chart_ids": ["chart_unrate"],
                "evidence_bundle_json": str(tmp_path / "evidence_bundle.json"),
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "evidence_bundle.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "bundle_type": "quant_evidence_bundle",
                "facts": [
                    {
                        "fact_id": "unrate_latest",
                        "label": "Latest unemployment rate",
                        "raw_value": 4.2,
                        "display_value": "4.2%",
                        "unit": "percent",
                        "precision": 1,
                        "tolerance": 0.1,
                        "source_key": "FRED",
                    }
                ],
                "charts": [
                    {
                        "chart_id": "chart_unrate",
                        "source_table_ids": ["FRED"],
                        "transform_ids": ["yield_curve_lead_lag"],
                    }
                ],
                "sources": [{"source_id": "FRED"}],
                "raw_tables": [
                    {
                        "table_id": "FRED",
                        "kind": "raw",
                        "source_id": "FRED",
                    }
                ],
                "transforms": [
                    {
                        "transform_id": "yield_curve_lead_lag",
                        "operation": "projection",
                        "source_table_ids": ["FRED"],
                        "chart_ids": ["chart_unrate"],
                    }
                ],
                "methods": ["yield curve lead-lag"],
                "limitations": ["latest release can revise"],
                "validation": {"valid": True, "diagnostics": []},
                "artifacts": {
                    "charts_json": str(tmp_path / "charts.json"),
                    "execution_summary_json": str(
                        tmp_path / "execution_summary.json"
                    ),
                    "evidence_bundle_json": str(tmp_path / "evidence_bundle.json"),
                },
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
                "data_sources": [
                    {
                        "series_id": "UNRATE",
                        "date_range": {"start": "2000-01-01", "end": "2026-03-01"},
                    }
                ],
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
    assert payload["data_sources"] == [
        {
            "series_id": "UNRATE",
            "date_range": {"start": "2000-01-01", "end": "2026-03-01"},
        }
    ]
    assert payload["execution_summary"]["status"] == "success"
    assert payload["execution_summary"]["path"].endswith("execution_summary.json")
    assert payload["execution_summary"]["evidence_bundle_json"].endswith(
        "evidence_bundle.json"
    )
    assert "yield_leads" in payload["execution_summary"]["statistical_summary"]
    assert payload["execution_summary"]["chart_ids"] == ["chart_unrate"]
    assert payload["evidence_bundle"]["status"] == "success"
    assert payload["evidence_bundle"]["fact_ids"] == ["unrate_latest"]
    assert payload["evidence_bundle"]["chart_ids"] == ["chart_unrate"]
    assert payload["evidence_bundle"]["source_ids"] == ["FRED"]
    assert payload["evidence_bundle"]["validation"]["valid"] is True


def test_load_report_for_review_reports_invalid_evidence_bundle(tmp_path):
    report_path = tmp_path / "report.json"
    (tmp_path / "evidence_bundle.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "bundle_type": "quant_evidence_bundle",
                "facts": [{"fact_id": "unrate_latest"}],
                "charts": [{"chart_id": "chart_unrate"}],
                "sources": [{"source_id": "FRED"}],
                "validation": {"valid": True, "diagnostics": []},
                "artifacts": {
                    "charts_json": str(tmp_path / "charts.json"),
                    "execution_summary_json": str(
                        tmp_path / "execution_summary.json"
                    ),
                    "evidence_bundle_json": str(tmp_path / "evidence_bundle.json"),
                },
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
                "markdown": "Summary",
                "charts": [{"id": "chart_unrate"}],
            }
        ),
        encoding="utf-8",
    )

    payload = json.loads(load_report_for_review.invoke({"report_path": str(report_path)}))

    assert payload["status"] == "success"
    assert payload["evidence_bundle"]["status"] == "error"
    assert payload["evidence_bundle"]["path"].endswith("evidence_bundle.json")
    assert "Invalid evidence_bundle.json" in payload["evidence_bundle"]["error"]
    assert "Field required" in payload["evidence_bundle"]["error"]


def test_submit_quality_decision_rejects_invalid_evidence_bundle(tmp_path):
    report_path = tmp_path / "report.json"
    (tmp_path / "execution_summary.json").write_text(
        json.dumps(
            {
                "status": "success",
                "chart_ids": ["chart_unrate"],
                "evidence_bundle_json": str(tmp_path / "evidence_bundle.json"),
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "evidence_bundle.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "bundle_type": "quant_evidence_bundle",
                "facts": [{"fact_id": "unrate_latest"}],
                "charts": [{"chart_id": "chart_unrate"}],
                "sources": [{"source_id": "FRED"}],
                "validation": {"valid": True, "diagnostics": []},
                "artifacts": {
                    "charts_json": str(tmp_path / "charts.json"),
                    "execution_summary_json": str(
                        tmp_path / "execution_summary.json"
                    ),
                    "evidence_bundle_json": str(tmp_path / "evidence_bundle.json"),
                },
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
                "markdown": "Summary\n\n<!-- CHART:chart_unrate -->",
                "charts": [{"id": "chart_unrate"}],
            }
        ),
        encoding="utf-8",
    )

    payload = json.loads(
        submit_quality_decision.invoke(
            {
                "decision": "approve",
                "report_path": str(report_path),
                "notes": "Looks acceptable.",
            }
        )
    )

    assert payload["status"] == "rejected"
    assert payload["ready_for_upload"] is False
    assert "Invalid evidence_bundle.json sibling artifact" in payload["reason"]
    assert payload["failure_category"] == "evidence_bundle_invalid"
    assert payload["required_upstream"] == "quant-developer"


def test_submit_quality_decision_rejects_missing_expected_evidence_bundle(tmp_path):
    report_path = tmp_path / "report.json"
    (tmp_path / "execution_summary.json").write_text(
        json.dumps(
            {
                "status": "success",
                "chart_ids": ["chart_unrate"],
                "evidence_bundle_json": str(tmp_path / "evidence_bundle.json"),
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
                "markdown": "Summary\n\n<!-- CHART:chart_unrate -->",
                "charts": [{"id": "chart_unrate"}],
            }
        ),
        encoding="utf-8",
    )

    payload = json.loads(
        submit_quality_decision.invoke(
            {
                "decision": "approve",
                "report_path": str(report_path),
                "notes": "Looks acceptable.",
            }
        )
    )

    assert payload["status"] == "rejected"
    assert "Missing evidence_bundle.json sibling artifact" in payload["reason"]
    assert payload["failure_category"] == "evidence_bundle_invalid"
    assert payload["required_upstream"] == "quant-developer"


def test_submit_quality_decision_rejects_stale_evidence_bundle_artifact_paths(tmp_path):
    report_path = tmp_path / "report.json"
    (tmp_path / "charts.json").write_text(
        json.dumps({"chart_unrate": {"id": "chart_unrate", "data": [{"x": 1}]}}),
        encoding="utf-8",
    )
    (tmp_path / "execution_summary.json").write_text(
        json.dumps(
            {
                "status": "success",
                "chart_ids": ["chart_unrate"],
                "evidence_bundle_json": str(tmp_path / "evidence_bundle.json"),
            }
        ),
        encoding="utf-8",
    )
    _write_valid_evidence_bundle(
        tmp_path,
        ["chart_unrate"],
        artifacts={
            "charts_json": str(tmp_path / "charts.json"),
            "execution_summary_json": str(tmp_path / "stale_execution_summary.json"),
            "evidence_bundle_json": str(tmp_path / "evidence_bundle.json"),
        },
    )
    report_path.write_text(
        json.dumps(
            {
                "query": "Is labor weakening?",
                "title": "Labor Market Review",
                "executive_summary": "Mixed but not collapsing.",
                "markdown": "Summary\n\n<!-- CHART:chart_unrate -->",
                "charts": [{"id": "chart_unrate"}],
            }
        ),
        encoding="utf-8",
    )

    payload = json.loads(
        submit_quality_decision.invoke(
            {
                "decision": "approve",
                "report_path": str(report_path),
                "notes": "Looks acceptable.",
            }
        )
    )

    assert payload["status"] == "rejected"
    assert "artifact paths do not match sibling quant artifacts" in payload["reason"]
    assert payload["failure_category"] == "evidence_bundle_invalid"
    assert payload["required_upstream"] == "quant-developer"


def test_submit_quality_decision_rejects_mutated_artifact_fingerprint(tmp_path):
    _write_fingerprinted_evidence_artifacts(tmp_path, ["chart_unrate"])
    (tmp_path / "charts.json").write_text(
        json.dumps({"chart_unrate": {"id": "chart_unrate", "data": [{"x": 2}]}}),
        encoding="utf-8",
    )
    report_path = _write_simple_report(tmp_path)

    payload = json.loads(
        submit_quality_decision.invoke(
            {
                "decision": "approve",
                "report_path": str(report_path),
                "notes": "Looks acceptable.",
            }
        )
    )

    assert payload["status"] == "rejected"
    assert "artifact fingerprints do not match current files" in payload["reason"]
    assert "charts_json sha256 changed" in payload["reason"]
    assert payload["failure_category"] == "evidence_bundle_invalid"
    assert payload["required_upstream"] == "quant-developer"


def test_submit_quality_decision_rejects_missing_artifact_fingerprint_file(tmp_path):
    source_path = tmp_path / "source.csv"
    source_path.write_text("date,value\n2024-01,1.0\n", encoding="utf-8")
    _write_fingerprinted_evidence_artifacts(
        tmp_path,
        ["chart_unrate"],
        source_files={"FRED": str(source_path)},
    )
    source_path.unlink()
    report_path = _write_simple_report(tmp_path)

    payload = json.loads(
        submit_quality_decision.invoke(
            {
                "decision": "approve",
                "report_path": str(report_path),
                "notes": "Looks acceptable.",
            }
        )
    )

    assert payload["status"] == "rejected"
    assert "artifact fingerprints do not match current files" in payload["reason"]
    assert "source_files:FRED missing or unreadable" in payload["reason"]
    assert payload["failure_category"] == "evidence_bundle_invalid"
    assert payload["required_upstream"] == "quant-developer"


def test_submit_quality_decision_rejects_stale_evidence_bundle_chart_ids(tmp_path):
    report_path = tmp_path / "report.json"
    (tmp_path / "charts.json").write_text(
        json.dumps({"chart_unrate": {"id": "chart_unrate", "data": [{"x": 1}]}}),
        encoding="utf-8",
    )
    (tmp_path / "execution_summary.json").write_text(
        json.dumps(
            {
                "status": "success",
                "chart_ids": ["chart_unrate"],
                "evidence_bundle_json": str(tmp_path / "evidence_bundle.json"),
            }
        ),
        encoding="utf-8",
    )
    _write_valid_evidence_bundle(tmp_path, ["stale_chart"])
    report_path.write_text(
        json.dumps(
            {
                "query": "Is labor weakening?",
                "title": "Labor Market Review",
                "executive_summary": "Mixed but not collapsing.",
                "markdown": "Summary\n\n<!-- CHART:chart_unrate -->",
                "charts": [{"id": "chart_unrate"}],
            }
        ),
        encoding="utf-8",
    )

    payload = json.loads(
        submit_quality_decision.invoke(
            {
                "decision": "approve",
                "report_path": str(report_path),
                "notes": "Looks acceptable.",
            }
        )
    )

    assert payload["status"] == "rejected"
    assert "chart_ids do not match execution_summary.json chart_ids" in payload["reason"]
    assert payload["failure_category"] == "evidence_bundle_invalid"
    assert payload["required_upstream"] == "quant-developer"


def test_submit_quality_decision_rejects_stale_evidence_bundle_facts(tmp_path):
    report_path = tmp_path / "report.json"
    (tmp_path / "charts.json").write_text(
        json.dumps({"chart_unrate": {"id": "chart_unrate", "data": [{"x": 1}]}}),
        encoding="utf-8",
    )
    summary_fact = {
        "id": "unrate_latest",
        "label": "Latest unemployment rate",
        "raw_value": 4.2,
        "display_value": "4.2%",
        "unit": "percent",
        "precision": 1,
        "tolerance": 0.1,
        "source_key": "FRED",
    }
    bundle_fact = {
        "fact_id": "unrate_latest",
        "label": "Latest unemployment rate",
        "raw_value": 5.9,
        "display_value": "5.9%",
        "unit": "percent",
        "precision": 1,
        "tolerance": 0.1,
        "source_key": "FRED",
    }
    (tmp_path / "execution_summary.json").write_text(
        json.dumps(
            {
                "status": "success",
                "chart_ids": ["chart_unrate"],
                "numeric_facts": [summary_fact],
                "evidence_bundle_json": str(tmp_path / "evidence_bundle.json"),
            }
        ),
        encoding="utf-8",
    )
    _write_valid_evidence_bundle(
        tmp_path,
        ["chart_unrate"],
        facts=[bundle_fact],
    )
    report_path.write_text(
        json.dumps(
            {
                "query": "Is labor weakening?",
                "title": "Labor Market Review",
                "executive_summary": "Mixed but not collapsing.",
                "markdown": "Summary\n\n<!-- CHART:chart_unrate -->",
                "charts": [{"id": "chart_unrate"}],
            }
        ),
        encoding="utf-8",
    )

    payload = json.loads(
        submit_quality_decision.invoke(
            {
                "decision": "approve",
                "report_path": str(report_path),
                "notes": "Looks acceptable.",
            }
        )
    )

    assert payload["status"] == "rejected"
    assert "facts do not match execution_summary.json numeric_facts" in payload["reason"]
    assert "unrate_latest" in payload["reason"]
    assert payload["failure_category"] == "evidence_bundle_invalid"
    assert payload["required_upstream"] == "quant-developer"


def test_load_report_for_review_keeps_missing_execution_summary_minimal(tmp_path):
    report_path = tmp_path / "report.json"
    report_path.write_text(
        json.dumps(
            {
                "query": "Is labor weakening?",
                "title": "Labor Market Review",
                "executive_summary": "Mixed but not collapsing.",
                "markdown": "Summary",
                "charts": [],
                "data_sources": [],
                "metadata": {"word_count": 5},
            }
        ),
        encoding="utf-8",
    )

    payload = json.loads(load_report_for_review.invoke({"report_path": str(report_path)}))
    summary = payload["execution_summary"]

    assert summary == {
        "status": "missing",
        "path": str(report_path.with_name("execution_summary.json")),
        "note": "No sibling execution_summary.json was found.",
    }
    assert "backtest_summary" not in summary
    assert "similarity_scores" not in summary


def test_load_report_for_review_preserves_failed_quant_summary(tmp_path):
    report_path = tmp_path / "report.json"
    (tmp_path / "execution_summary.json").write_text(
        json.dumps(
            {
                "status": "failed",
                "failure_stage": "quant_initial_script_write",
                "error": "quant-developer exceeded the pre-write guardrail retry budget",
                "methods_used": ["quant_prewrite_retry_budget_guard"],
                "limitations": ["No quantitative charts were produced."],
                "chart_ids": [],
            }
        ),
        encoding="utf-8",
    )
    report_path.write_text(
        json.dumps(
            {
                "query": "Build a quantitative recession risk report with charts.",
                "title": "Recession Risk Report",
                "executive_summary": "Quant artifacts failed.",
                "markdown": "## Executive Summary\nNo charts.",
                "charts": [],
                "data_sources": [],
                "metadata": {"word_count": 5},
            }
        ),
        encoding="utf-8",
    )

    payload = json.loads(load_report_for_review.invoke({"report_path": str(report_path)}))

    assert payload["execution_summary"]["status"] == "failed"
    assert payload["execution_summary"]["failure_stage"] == "quant_initial_script_write"
    assert "pre-write guardrail" in payload["execution_summary"]["error"]
    assert payload["execution_summary"]["methods_used"] == [
        "quant_prewrite_retry_budget_guard"
    ]


def test_load_report_for_review_preserves_normal_length_full_markdown(tmp_path):
    report_path = tmp_path / "report.json"
    long_markdown = (
        "## Executive Summary\nComplete report.\n"
        + ("Apple and Microsoft earnings risk analysis. " * 700)
        + "\n## Sources\nAll sections present."
    )
    report_path.write_text(
        json.dumps(
            {
                "query": "Assess macro cycle, Apple, and Microsoft.",
                "title": "Macro Cycle Report",
                "executive_summary": "Complete report.",
                "markdown": long_markdown,
                "charts": [],
                "data_sources": [],
                "metadata": {"word_count": 4200},
            }
        ),
        encoding="utf-8",
    )

    payload = json.loads(load_report_for_review.invoke({"report_path": str(report_path)}))

    assert payload["status"] == "success"
    assert payload["markdown"] == long_markdown
    assert payload["markdown_full_length"] == len(long_markdown)
    assert payload["markdown_truncated_for_context"] is False
    assert "[truncated for review]" not in payload["markdown"]


def test_load_report_for_review_preserves_conditional_fidelity_fields(tmp_path):
    report_path = tmp_path / "report.json"
    (tmp_path / "execution_summary.json").write_text(
        json.dumps(
            {
                "status": "success",
                "analog_similarity_ranking": [
                    {"label": "1995", "normalized_similarity": 17.4, "status": "included"},
                    {"label": "2008", "normalized_similarity": 23.7, "status": "included"},
                ],
                "composite_recession_risk": {"current": 91.3},
                "diagnostics": {"validation_metrics": {"precision": 0.058}},
                "model_comparison_by_horizon": [{"horizon": 1, "naive_rmse": 1.2}],
                "replay_rows": [{"label": "2008", "status": "ok"}],
                "numeric_facts": [
                    {
                        "id": "sec_company_facts.AAPL.revenue_b",
                        "display_value": "$365.82B",
                        "raw_value": 365.82,
                        "source_key": "sec_company_facts.latest_fundamentals.AAPL.revenue_b",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    report_path.write_text(
        json.dumps(
            {
                "query": "Compare current recession risk with prior cycles.",
                "title": "Cycle Analog Report",
                "executive_summary": "Risk summary.",
                "markdown": "## Executive Summary\nRisk summary.",
                "charts": [],
                "data_sources": [],
                "metadata": {"word_count": 5},
            }
        ),
        encoding="utf-8",
    )

    payload = json.loads(load_report_for_review.invoke({"report_path": str(report_path)}))
    summary = payload["execution_summary"]

    assert "2008" in summary["analog_similarity_ranking"]
    assert "23.7" in summary["analog_similarity_ranking"]
    assert "91.3" in summary["composite_recession_risk"]
    assert "precision" in summary["diagnostics"]
    assert "naive_rmse" in summary["model_comparison_by_horizon"]
    assert "2008" in summary["replay_rows"]
    assert "$365.82B" in summary["numeric_facts"]


def test_quality_analyst_prompt_uses_embedded_execution_summary_packet():
    prompt = _compact_text(QUALITY_ANALYST_SYSTEM_PROMPT)

    assert "any sibling `execution_summary` packet" in prompt
    assert "Treat that packet as controlling context" in prompt
    assert "do not inspect sibling files directly" in prompt
    assert "deterministic artifact/fidelity blockers" in prompt


def test_quality_analyst_prompt_keeps_terminal_decision_compact():
    prompt = _compact_text(QUALITY_ANALYST_SYSTEM_PROMPT)

    assert "OUTPUT RULES" in prompt
    assert "Do not narrate review reasoning" in prompt
    assert "After the terminal tool result" in prompt
    assert "emit exactly one compact JSON object" in prompt
    assert "Never emit only `Approved.` or `Rejected.`" in prompt
    assert "markdown tables" in prompt


def test_submit_quality_decision_rejection_preserves_required_fixes():
    payload = json.loads(
        submit_quality_decision.invoke(
            {
                "decision": "reject",
                "report_path": "/tmp/report.json",
                "reason": "Incorrect revenue per share calculation.",
                "required_fixes": json.dumps(
                    [
                        "Correct FY2025 revenue per share.",
                        "Regenerate prose using the corrected metric.",
                    ]
                ),
            }
        )
    )

    assert payload == {
        "status": "rejected",
        "report_path": "/tmp/report.json",
        "reason": "Incorrect revenue per share calculation.",
        "required_fixes": [
            "Correct FY2025 revenue per share.",
            "Regenerate prose using the corrected metric.",
        ],
        "ready_for_upload": False,
    }


def test_submit_quality_decision_rejects_approval_when_required_quant_failed(tmp_path):
    report_path = tmp_path / "report.json"
    (tmp_path / "execution_summary.json").write_text(
        json.dumps(
            {
                "status": "failed",
                "failure_stage": "quant_initial_script_write",
                "error": "quant-developer exceeded the pre-write guardrail retry budget",
                "chart_ids": [],
            }
        ),
        encoding="utf-8",
    )
    report_path.write_text(
        json.dumps(
            {
                "query": "Include a quantitative recession-risk framework and charts.",
                "title": "Recession Risk Report",
                "executive_summary": "Caveated report.",
                "markdown": "## Executive Summary\nNo computed charts.",
                "charts": [],
                "data_sources": [],
                "metadata": {"word_count": 5},
            }
        ),
        encoding="utf-8",
    )

    payload = json.loads(
        submit_quality_decision.invoke(
            {
                "decision": "approve",
                "report_path": str(report_path),
                "notes": "Looks acceptable despite missing charts.",
            }
        )
    )

    assert payload["status"] == "rejected"
    assert payload["ready_for_upload"] is False
    assert "quantitative artifacts" in payload["reason"]
    assert any("zero chart" in fix for fix in payload["required_fixes"])


def test_submit_quality_decision_rejects_failed_quant_even_if_report_query_drifted(tmp_path):
    report_path = tmp_path / "report.json"
    (tmp_path / "execution_summary.json").write_text(
        json.dumps(
            {
                "status": "failed",
                "failure_stage": "quant_initial_script_write",
                "error": "quant-developer exceeded the pre-write guardrail retry budget",
                "chart_ids": [],
            }
        ),
        encoding="utf-8",
    )
    report_path.write_text(
        json.dumps(
            {
                "query": "Assess the likelihood of a US recession using macro indicators.",
                "title": "US Recession Risk Assessment",
                "executive_summary": "Caveated prose-only report.",
                "markdown": "## Executive Summary\nNo computed charts.",
                "charts": {},
                "data_sources": [],
                "metadata": {"word_count": 5},
            }
        ),
        encoding="utf-8",
    )

    payload = json.loads(
        submit_quality_decision.invoke(
            {
                "decision": "approve",
                "report_path": str(report_path),
                "notes": "Looks acceptable despite missing charts.",
            }
        )
    )

    assert payload["status"] == "rejected"
    assert payload["ready_for_upload"] is False
    assert "quantitative artifacts" in payload["reason"]
    assert any("execution_summary.json reports a failed" in fix for fix in payload["required_fixes"])


def test_submit_quality_decision_rejects_stale_analog_prose_vs_execution_summary(tmp_path):
    report_path = tmp_path / "report.json"
    (tmp_path / "execution_summary.json").write_text(
        json.dumps(
            {
                "analog_similarity_ranking": [
                    {"label": "2008", "normalized_similarity": 23.7, "status": "included"},
                    {"label": "2020", "normalized_similarity": 19.7, "status": "included"},
                    {"label": "2001", "normalized_similarity": 18.7, "status": "included"},
                    {"label": "1995", "normalized_similarity": 17.4, "status": "included"},
                ],
                "composite_recession_risk": {"current": 91.3},
                "chart_ids": ["cycle_analog"],
            }
        ),
        encoding="utf-8",
    )
    report_path.write_text(
        json.dumps(
            {
                "query": "Test whether the current cycle looks like 1995, 2001, 2008, or 2020 and include charts.",
                "title": "Cycle Analog Report",
                "executive_summary": "Closest analog is 1995.",
                "markdown": (
                    "## Executive Summary\n"
                    "The current cycle has the closest resemblance to the 1995 soft landing, "
                    "with a similarity score of 72/100 and a composite recession-risk score of 68.3."
                ),
                "charts": [{"id": "cycle_analog"}],
                "data_sources": [],
                "metadata": {"word_count": 30},
            }
        ),
        encoding="utf-8",
    )

    payload = json.loads(
        submit_quality_decision.invoke(
            {
                "decision": "approve",
                "report_path": str(report_path),
                "notes": "Looks aligned.",
            }
        )
    )

    assert payload["status"] == "rejected"
    assert "analog_similarity_ranking is led by 2008" in payload["reason"]
    assert any("current value from execution_summary.json (91.3)" in fix for fix in payload["required_fixes"])


def test_submit_quality_decision_accepts_year_shorthand_for_ranked_analog(tmp_path):
    report_path = tmp_path / "report.json"
    (tmp_path / "execution_summary.json").write_text(
        json.dumps(
            {
                "status": "success",
                "analog_similarity_ranking": [
                    {
                        "label": "2001 recession",
                        "normalized_similarity": 23.7,
                        "status": "included",
                    },
                    {
                        "label": "2008 financial crisis",
                        "normalized_similarity": 12.1,
                        "status": "included",
                    },
                ],
                "comparison_design": {
                    "named_windows": [
                        {"label": "2001 recession"},
                        {"label": "2008 financial crisis"},
                    ]
                },
                "chart_ids": ["cycle_analog"],
            }
        ),
        encoding="utf-8",
    )
    report_path.write_text(
        json.dumps(
            {
                "query": "Which analog is closest, 2001 or 2008? Include charts.",
                "title": "Cycle Analog Report",
                "executive_summary": "Closest analog is 2001.",
                "markdown": (
                    "## Executive Summary\n"
                    "The closest historical analog is 2001, with a similarity score of 23.7."
                ),
                "charts": [{"id": "cycle_analog"}],
                "data_sources": [],
                "metadata": {"word_count": 18},
            }
        ),
        encoding="utf-8",
    )

    payload = json.loads(
        submit_quality_decision.invoke(
            {
                "decision": "approve",
                "report_path": str(report_path),
                "notes": "Looks aligned.",
            }
        )
    )

    assert payload["status"] == "approved"


def test_submit_quality_decision_accepts_ranked_analog_not_phrase(tmp_path):
    report_path = tmp_path / "report.json"
    (tmp_path / "execution_summary.json").write_text(
        json.dumps(
            {
                "status": "success",
                "analog_similarity_ranking": [
                    {
                        "label": "2001 recession",
                        "normalized_similarity": 19.8,
                        "status": "included",
                    },
                    {
                        "label": "2008 financial crisis",
                        "normalized_similarity": 12.1,
                        "status": "included",
                    },
                ],
                "comparison_design": {
                    "named_windows": [
                        {"label": "2001 recession"},
                        {"label": "2008 financial crisis"},
                    ]
                },
                "chart_ids": ["cycle_analog"],
            }
        ),
        encoding="utf-8",
    )
    report_path.write_text(
        json.dumps(
            {
                "query": "Compare the current cycle with prior downturns and include charts.",
                "title": "Cycle Analog Report",
                "executive_summary": "Closest analog is 2001, not 2008.",
                "markdown": (
                    "## Executive Summary\n"
                    "The closest historical analog is 2001, not the 2008 financial crisis, "
                    "with a similarity score of 19.8."
                ),
                "charts": [{"id": "cycle_analog"}],
                "data_sources": [],
                "metadata": {"word_count": 24},
            }
        ),
        encoding="utf-8",
    )

    payload = json.loads(
        submit_quality_decision.invoke(
            {
                "decision": "approve",
                "report_path": str(report_path),
                "notes": "Structured analog evidence is aligned.",
            }
        )
    )

    assert payload["status"] == "approved"


def test_submit_quality_decision_accepts_requested_analog_evidence_rows(tmp_path):
    report_path = tmp_path / "report.json"
    (tmp_path / "execution_summary.json").write_text(
        json.dumps(
            {
                "status": "success",
                "chart_ids": ["analog_similarity"],
                "historical_window_coverage": [
                    {"label": "1995 soft landing", "status": "covered", "requested": True},
                    {"label": "2001 recession", "status": "covered", "requested": True},
                    {
                        "label": "2008 financial crisis",
                        "status": "covered",
                        "requested": True,
                    },
                    {"label": "2020 covid shock", "status": "covered", "requested": True},
                ],
                "analog_similarity_ranking": [
                    {
                        "label": "1995 soft landing",
                        "raw_distance": 1.2,
                        "normalized_similarity": 45.5,
                        "status": "ok",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    report_path.write_text(
        json.dumps(
            {
                "query": (
                    "Test whether the current cycle looks more like 1995, 2001, "
                    "2008, 2020, or something different. Include charts."
                ),
                "title": "Cycle Analog Report",
                "executive_summary": "Closest analog is 1995.",
                "markdown": (
                    "## Executive Summary\n"
                    "The closest historical analog is 1995 with a similarity score of 45.5; "
                    "2001, 2008, and 2020 are also covered requested windows.\n"
                    "<!-- CHART:analog_similarity -->"
                ),
                "charts": [{"id": "analog_similarity"}],
                "data_sources": [],
                "metadata": {"word_count": 28},
            }
        ),
        encoding="utf-8",
    )

    payload = json.loads(
        submit_quality_decision.invoke(
            {
                "decision": "approve",
                "report_path": str(report_path),
                "notes": "Structured analog evidence is complete.",
            }
        )
    )

    assert payload["status"] == "approved"


def test_submit_quality_decision_rejects_claimed_analog_window_without_evidence(tmp_path):
    report_path = tmp_path / "report.json"
    (tmp_path / "execution_summary.json").write_text(
        json.dumps(
            {
                "status": "success",
                "analog_similarity_ranking": [
                    {"label": "2001 recession", "status": "included"},
                    {"label": "2008 financial crisis", "status": "included"},
                    {"label": "2020 covid shock", "status": "included"},
                ],
                "comparison_design": {
                    "named_windows": [
                        {"label": "2001 recession"},
                        {"label": "2008 financial crisis"},
                        {"label": "2020 covid shock"},
                    ]
                },
                "analog_profile_rows": [
                    {"label": "2001 recession"},
                    {"label": "2008 financial crisis"},
                    {"label": "2020 covid shock"},
                ],
                "chart_ids": ["cycle_analog"],
            }
        ),
        encoding="utf-8",
    )
    report_path.write_text(
        json.dumps(
            {
                "query": "Compare the current cycle with prior downturns. Include charts.",
                "title": "Cycle Analog Report",
                "executive_summary": "The closest historical analog is 1995.",
                "markdown": (
                    "## Executive Summary\n"
                    "The closest historical analog is 1995, with a softer landing "
                    "profile than 2001."
                ),
                "charts": [{"id": "cycle_analog"}],
                "data_sources": [],
                "metadata": {"word_count": 24},
            }
        ),
        encoding="utf-8",
    )

    payload = json.loads(
        submit_quality_decision.invoke(
            {
                "decision": "approve",
                "report_path": str(report_path),
                "notes": "Looks aligned.",
            }
        )
    )

    assert payload["status"] == "rejected"
    assert "historical analog evidence" in payload["reason"]
    assert "missing from execution_summary.json" in payload["reason"]
    assert "1995" in payload["reason"]
    assert payload["failure_category"] == "unsupported_historical_analog_claim"
    assert payload["required_upstream"] == "technical-writer"
    assert any("computed analog windows" in fix for fix in payload["required_fixes"])


def test_submit_quality_decision_allows_historical_coverage_year_language(tmp_path):
    report_path = tmp_path / "report.json"
    (tmp_path / "execution_summary.json").write_text(
        json.dumps(
            {
                "status": "success",
                "methods_used": ["rate-cut event study"],
                "limitations": ["FRED S&P 500 observations begin in 2016."],
            }
        ),
        encoding="utf-8",
    )
    report_path.write_text(
        json.dumps(
            {
                "query": "Test whether the first Fed cut is bullish for stocks.",
                "title": "Fed Cut Event Study",
                "executive_summary": "Recent data are supportive but limited.",
                "markdown": (
                    "## Caveats\n"
                    "Historical analog coverage is limited to FRED data from 2016 onward.\n"
                    "The 1995 and 2001 easing cycles are not covered by this dataset."
                ),
                "charts": [],
                "data_sources": [],
                "metadata": {"word_count": 24},
            }
        ),
        encoding="utf-8",
    )

    payload = json.loads(
        submit_quality_decision.invoke(
            {
                "decision": "approve",
                "report_path": str(report_path),
                "notes": "Coverage caveats are stated.",
            }
        )
    )

    assert payload["status"] == "approved"


def test_submit_quality_decision_allows_event_study_cycle_years(tmp_path):
    report_path = tmp_path / "report.json"
    (tmp_path / "execution_summary.json").write_text(
        json.dumps(
            {
                "status": "success",
                "cycles_analyzed": [
                    {"first_cut_year": 2019, "horizon_months": 6},
                    {"first_cut_year": 2020, "horizon_months": 6},
                    {"first_cut_year": 2024, "horizon_months": 6},
                ],
                "aggregate_summary": {"cycle_count": 3},
            }
        ),
        encoding="utf-8",
    )
    report_path.write_text(
        json.dumps(
            {
                "query": "Test whether the first Fed cut is bullish for stocks.",
                "title": "Fed Cut Event Study",
                "executive_summary": "The recent event-study sample is small.",
                "markdown": (
                    "## Evidence\n"
                    "The event-study sample includes the 2019, 2020, and 2024 "
                    "rate-cut cycles."
                ),
                "charts": [],
                "data_sources": [],
                "metadata": {"word_count": 18},
            }
        ),
        encoding="utf-8",
    )

    payload = json.loads(
        submit_quality_decision.invoke(
            {
                "decision": "approve",
                "report_path": str(report_path),
                "notes": "Cycle years describe the event-study sample.",
            }
        )
    )

    assert payload["status"] == "approved"


def test_submit_quality_decision_counts_ranking_rows_as_window_coverage(tmp_path):
    report_path = tmp_path / "report.json"
    (tmp_path / "execution_summary.json").write_text(
        json.dumps(
            {
                "status": "success",
                "analog_similarity_ranking": [
                    {
                        "label": "2020 (COVID)",
                        "normalized_similarity": 0.39,
                        "status": "included",
                    },
                    {
                        "label": "1995 (soft-landing)",
                        "normalized_similarity": 0.25,
                        "status": "included",
                    },
                    {
                        "label": "2001 (dot-com bust)",
                        "normalized_similarity": 0.22,
                        "status": "included",
                    },
                    {
                        "label": "2008 (GFC)",
                        "normalized_similarity": 0.18,
                        "status": "included",
                    },
                ],
                "chart_ids": ["cycle_analog"],
            }
        ),
        encoding="utf-8",
    )
    report_path.write_text(
        json.dumps(
            {
                "query": (
                    "Test whether the current cycle looks more like 1995, 2001, "
                    "2008, 2020, or something different. Include charts."
                ),
                "title": "Cycle Analog Report",
                "executive_summary": "Closest analog is 2020.",
                "markdown": (
                    "## Executive Summary\n"
                    "The closest historical analog is 2020, with computed scores "
                    "for 1995, 2001, 2008, and 2020."
                ),
                "charts": [{"id": "cycle_analog"}],
                "data_sources": [],
                "metadata": {"word_count": 22},
            }
        ),
        encoding="utf-8",
    )

    payload = json.loads(
        submit_quality_decision.invoke(
            {
                "decision": "approve",
                "report_path": str(report_path),
                "notes": "Structured analog coverage is present.",
            }
        )
    )

    assert payload["status"] == "approved"


def test_quality_decision_normalizer_makes_tool_rejection_authoritative():
    tool_payload = {
        "status": "rejected",
        "report_path": "/tmp/report.json",
        "reason": "Required quantitative artifacts are missing or failed.",
        "required_fixes": ["Rerun quant-developer."],
        "ready_for_upload": False,
    }
    result = {
        "messages": [
            ToolMessage(
                content=json.dumps(tool_payload),
                name="submit_quality_decision",
                tool_call_id="qa-decision",
            ),
            AIMessage(
                content='{"status":"approved","report_path":"/tmp/report.json"}',
                name="quality-analyst",
            ),
        ]
    }

    normalized = _normalize_terminal_quality_decision(result)
    final_payload = json.loads(normalized["messages"][-1].content)

    assert final_payload["status"] == "rejected"
    assert final_payload["report_path"] == "/tmp/report.json"
    assert final_payload["ready_for_upload"] is False
    assert "required quantitative artifacts" in final_payload["reason"].lower()
    assert len(normalized["messages"]) == 2


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


def test_load_report_for_review_omits_report_level_scenario_payload(tmp_path):
    report_path = tmp_path / "report.json"
    report_path.write_text(
        json.dumps(
            {
                "query": "Show how the conclusion changes under base, upside, and downside cases.",
                "title": "Recession Risk Scenario Dashboard",
                "executive_summary": "Scenario summary.",
                "markdown": "## Executive Summary\nScenario summary.",
                "charts": {},
                "data_sources": [],
                "metadata": {"word_count": 5},
            }
        ),
        encoding="utf-8",
    )

    payload = json.loads(load_report_for_review.invoke({"report_path": str(report_path)}))

    assert "scenario_score_rows" not in payload
    assert "scenario_requirement" not in payload


def test_quality_analyst_prompt_uses_generic_evidence_validation():
    prompt = _compact_text(QUALITY_ANALYST_SYSTEM_PROMPT)

    assert "`scenario_requirement`" not in prompt
    assert "missing requested evidence coverage" in prompt
    assert "assumptions, indicator triggers, and confidence/uncertainty notes" not in (
        prompt
    )


def test_submit_quality_decision_rejects_econometric_report_without_validation(tmp_path):
    report_path = tmp_path / "report.json"
    (tmp_path / "execution_summary.json").write_text(
        json.dumps(
            {
                "status": "success",
                "chart_ids": ["forecast_chart"],
                "forecast_table": [{"horizon": 1, "forecast": 4.2}],
            }
        ),
        encoding="utf-8",
    )
    report_path.write_text(
        json.dumps(
            {
                "query": (
                    "Build an econometric unemployment forecast with backtesting and "
                    "historical simulations."
                ),
                "title": "Forecast Report",
                "executive_summary": "Forecast only.",
                "markdown": "## Executive Summary\nForecast only.",
                "charts": [{"id": "forecast_chart"}],
                "data_sources": [],
                "metadata": {"word_count": 5},
            }
        ),
        encoding="utf-8",
    )

    payload = json.loads(
        submit_quality_decision.invoke(
            {
                "decision": "approve",
                "report_path": str(report_path),
                "notes": "Looks acceptable.",
            }
        )
    )

    assert payload["status"] == "rejected"
    assert "generic helper validation evidence" in payload["reason"]
    assert any("replay rows" in fix for fix in payload["required_fixes"])


def test_submit_quality_decision_rejects_earlier_downturn_report_without_replay(tmp_path):
    report_path = tmp_path / "report.json"
    (tmp_path / "execution_summary.json").write_text(
        json.dumps({"status": "success", "chart_ids": ["risk_chart"]}),
        encoding="utf-8",
    )
    report_path.write_text(
        json.dumps(
            {
                "query": "Explain what a simple signal stack would have said before earlier downturns and how often it cried wolf.",
                "title": "Recession Risk Report",
                "executive_summary": "Signal stack summary.",
                "markdown": "## Executive Summary\nSignal stack summary.",
                "charts": [{"id": "risk_chart"}],
                "data_sources": [],
                "metadata": {"word_count": 5},
            }
        ),
        encoding="utf-8",
    )

    payload = json.loads(
        submit_quality_decision.invoke(
            {
                "decision": "approve",
                "report_path": str(report_path),
                "notes": "Looks acceptable.",
            }
        )
    )

    assert payload["status"] == "rejected"
    assert "generic helper validation evidence" in payload["reason"]
    assert any("replay rows" in fix for fix in payload["required_fixes"])


def test_submit_quality_decision_accepts_generic_helper_replay(tmp_path):
    report_path = tmp_path / "report.json"
    (tmp_path / "execution_summary.json").write_text(
        json.dumps(
            {
                "status": "success",
                "chart_ids": ["risk_chart"],
                "signal_validation_metrics": {
                    "status": "ok",
                    "event_count": 5,
                    "events_met_threshold": 3,
                    "events_below_threshold": 2,
                    "false_positive_windows": 4,
                    "true_positive_rate": 0.6,
                    "precision": 0.428571,
                    "threshold": 2,
                },
                "signal_event_rows": [
                    {"event_label": "1990 recession", "met_threshold": True},
                    {"event_label": "2001 recession", "met_threshold": False},
                    {"event_label": "2008 recession", "met_threshold": True},
                    {"event_label": "2020 recession", "met_threshold": False},
                    {"event_label": "2022 slowdown", "met_threshold": True},
                ],
                "signal_false_positive_windows": [
                    {"window_label": "1995"},
                    {"window_label": "1998"},
                    {"window_label": "2011"},
                    {"window_label": "2018"},
                ],
                "replay_rows": [
                    {"label": "2008", "status": "ok", "classification": "hit"}
                ],
                "scenario_score_rows": [
                    {"scenario": "base", "score": 1},
                    {"scenario": "bull", "score": 0},
                    {"scenario": "bear", "score": 3},
                ],
            }
        ),
        encoding="utf-8",
    )
    report_path.write_text(
        json.dumps(
            {
                "query": "Explain what a simple signal stack would have said before earlier downturns and how often it cried wolf.",
                "title": "Recession Risk Report",
                "executive_summary": "Backtest found 3 hits and 4 false alarms.",
                "markdown": (
                    "## Executive Summary\n"
                    "The signal-stack backtest found 3 hits, 2 misses, and 4 false alarms.\n"
                    "<!-- CHART:risk_chart -->\n"
                ),
                "charts": [{"id": "risk_chart"}],
                "data_sources": [],
                "metadata": {"word_count": 20},
            }
        ),
        encoding="utf-8",
    )

    payload = json.loads(
        submit_quality_decision.invoke(
            {
                "decision": "approve",
                "report_path": str(report_path),
                "notes": "Structured signal-stack replay is present.",
            }
        )
    )

    assert payload["status"] == "approved"


def test_submit_quality_decision_rejects_signal_validation_metric_row_mismatch(tmp_path):
    report_path = tmp_path / "report.json"
    (tmp_path / "execution_summary.json").write_text(
        json.dumps(
            {
                "status": "success",
                "chart_ids": ["risk_chart"],
                "signal_validation_metrics": {
                    "status": "ok",
                    "event_count": 5,
                    "events_met_threshold": 5,
                    "events_below_threshold": 0,
                    "false_positive_windows": 0,
                    "true_positive_rate": 1.0,
                    "precision": 1.0,
                    "threshold": 2,
                },
                "signal_event_rows": [
                    {"event_label": "1990 recession", "met_threshold": True},
                    {"event_label": "2001 recession", "met_threshold": False},
                    {"event_label": "2008 recession", "met_threshold": True},
                    {"event_label": "2020 recession", "met_threshold": False},
                    {"event_label": "2022 slowdown", "met_threshold": True},
                ],
                "signal_false_positive_windows": [
                    {"window_label": "1995"},
                    {"window_label": "1998"},
                    {"window_label": "2011"},
                    {"window_label": "2018"},
                ],
                "scenario_score_rows": [
                    {"scenario": "base", "score": 1},
                    {"scenario": "bull", "score": 0},
                    {"scenario": "bear", "score": 3},
                ],
            }
        ),
        encoding="utf-8",
    )
    report_path.write_text(
        json.dumps(
            {
                "query": "Explain what a simple signal stack would have said before earlier downturns and how often it cried wolf.",
                "title": "Recession Risk Report",
                "executive_summary": "Backtest found no false alarms.",
                "markdown": "## Executive Summary\nBacktest found no false alarms.\n<!-- CHART:risk_chart -->\n",
                "charts": [{"id": "risk_chart"}],
                "data_sources": [],
                "metadata": {"word_count": 15},
            }
        ),
        encoding="utf-8",
    )

    payload = json.loads(
        submit_quality_decision.invoke(
            {
                "decision": "approve",
                "report_path": str(report_path),
                "notes": "Looks acceptable.",
            }
        )
    )

    assert payload["status"] == "rejected"
    assert payload["failure_category"] == "helper_diagnostic_mismatch"
    assert payload["required_upstream"] == "quantitative-developer"
    assert "signal_validation_metrics contradict reusable signal evidence rows" in payload["reason"]


def test_submit_quality_decision_rejects_forecast_claim_without_reusable_evidence(
    tmp_path,
):
    report_path = tmp_path / "report.json"
    (tmp_path / "execution_summary.json").write_text(
        json.dumps(
            {
                "status": "success",
                "chart_ids": ["labor_cycle_breadth"],
                "latest_snapshot": {"unemployment_rate": 4.3},
            }
        ),
        encoding="utf-8",
    )
    report_path.write_text(
        json.dumps(
            {
                "query": "Include a short-term unemployment outlook and charts.",
                "title": "Unemployment Outlook",
                "executive_summary": "The OLS model projects unemployment at 4.5%.",
                "markdown": (
                    "## Executive Summary\n"
                    "The OLS model projects the unemployment rate rising to 4.5% over six months, "
                    "with a low band of 4.0% and high band of 5.0%.\n"
                    "| Scenario | Assumptions | Indicator Triggers | Confidence | Uncertainty Notes |\n"
                    "|---|---|---|---|---|\n"
                    "| base | Cooling | Payrolls slow | medium | Revisions |\n"
                    "| bull | Reacceleration | Inflation slows | low | Data lag |\n"
                    "| bear | Recession | Payrolls contract | medium | Shock risk |\n"
                    "<!-- CHART:labor_cycle_breadth -->"
                ),
                "charts": [{"id": "labor_cycle_breadth"}],
                "data_sources": [],
                "metadata": {"word_count": 90},
            }
        ),
        encoding="utf-8",
    )

    payload = json.loads(
        submit_quality_decision.invoke(
            {
                "decision": "approve",
                "report_path": str(report_path),
                "notes": "Looks acceptable.",
            }
        )
    )

    assert payload["status"] == "rejected"
    assert "Report makes model, projection, or forecast claims" in payload["reason"]
    assert any("generic helper evidence" in fix for fix in payload["required_fixes"])
    assert payload["failure_category"] == "missing_helper_evidence"
    assert payload["required_upstream"] == "quantitative-developer"


def test_submit_quality_decision_allows_supported_forecast_and_current_production_language(tmp_path):
    report_path = tmp_path / "report.json"
    (tmp_path / "execution_summary.json").write_text(
        json.dumps(
            {
                "status": "success",
                "chart_ids": ["risk_chart", "unemployment_forecast"],
                "diagnostics": {"walk_forward_backtest": {"status": "ok", "rmse": 0.4}},
                "model_comparison_by_horizon": [
                    {"horizon": 6, "last_value_rmse": 0.6}
                ],
                "forecast_table": [
                    {"horizon": 6, "forecast": 4.64, "lower_95": 2.58, "upper_95": 6.70}
                ],
                "replay_rows": [
                    {"label": "2008", "status": "ok", "outcome_during_window": {"max": 1.0}}
                ],
            }
        ),
        encoding="utf-8",
    )
    report_path.write_text(
        json.dumps(
            {
                "query": (
                    "Compare the current cycle with prior downturns, include an "
                    "unemployment outlook, scenarios, charts, and backtesting."
                ),
                "title": "Macro Cycle Report",
                "executive_summary": (
                    "The conditional OLS model projects UNRATE at 4.64% over "
                    "the next six months."
                ),
                "markdown": (
                    "## Executive Summary\n"
                    "The conditional OLS model projects UNRATE at 4.64% over "
                    "the next six months, with backtest RMSE disclosed. "
                    "Industrial production growth is currently positive.\n\n"
                    "## Historical Replay\n"
                    "Replay rows only use USREC as the forward outcome. "
                    "No forward UNRATE or INDPRO outcomes were available.\n\n"
                    "| Scenario | Assumptions | Indicator Triggers | Confidence | Uncertainty Notes |\n"
                    "|---|---|---|---|---|\n"
                    "| base | Soft landing | Claims stable | medium | Data revisions |\n"
                    "| bull | Reacceleration | Productivity improves | low | Inflation risk |\n"
                    "| bear | Recession | Claims rise | medium | Shock risk |\n"
                    "<!-- CHART:risk_chart -->\n<!-- CHART:unemployment_forecast -->\n"
                ),
                "charts": [{"id": "risk_chart"}, {"id": "unemployment_forecast"}],
                "data_sources": [],
                "metadata": {"word_count": 120},
            }
        ),
        encoding="utf-8",
    )

    payload = json.loads(
        submit_quality_decision.invoke(
            {
                "decision": "approve",
                "report_path": str(report_path),
                "notes": "Forecasts are supported and caveated.",
            }
        )
    )

    assert payload["status"] == "approved"


def test_submit_quality_decision_accepts_reusable_forecast_rows_replay(tmp_path):
    report_path = tmp_path / "report.json"
    forecast_rows = {
        "status": "covered",
        "forecast_table": [
            {"horizon": 6, "date": "2026-07-01", "forecast": 4.64, "lower": 4.1, "upper": 5.2}
        ],
        "model_comparison_by_horizon": [
            {
                "horizon": 6,
                "direct_ols_mae": 0.712,
                "last_value_mae": 0.635,
                "train_mean_mae": 2.373,
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
            }
        ],
    }
    (tmp_path / "execution_summary.json").write_text(
        json.dumps(
            {
                "status": "success",
                "chart_ids": ["forecast_chart"],
                **forecast_rows,
            }
        ),
        encoding="utf-8",
    )
    report_path.write_text(
        json.dumps(
            {
                "query": (
                    "Give a skeptical unemployment forecast review, where it failed "
                    "historically, and whether it beats baselines."
                ),
                "title": "Forecast Review",
                "executive_summary": "The forecast reaches 4.64% in 2026-07.",
                "markdown": (
                    "## Executive Summary\n"
                    "The unemployment forecast reaches 4.64% in 2026-07, with a 4.1% "
                    "to 5.2% interval.\n\n"
                    "| Horizon | OLS MAE | Last-Value MAE | Train-Mean MAE |\n"
                    "|---|---|---|---|\n"
                    "| H6 | 0.712 | 0.635 | 2.373 |\n\n"
                    "## Historical Failures\n"
                    "The typed replay includes 2020-10 as a large overprediction episode.\n"
                    "<!-- CHART:forecast_chart -->\n"
                ),
                "charts": [{"id": "forecast_chart"}],
                "data_sources": [],
                "metadata": {"word_count": 80},
            }
        ),
        encoding="utf-8",
    )

    payload = json.loads(
        submit_quality_decision.invoke(
            {
                "decision": "approve",
                "report_path": str(report_path),
                "notes": "Reusable forecast evidence is present.",
            }
        )
    )

    assert payload["status"] == "approved"


def test_submit_quality_decision_accepts_forecast_rows_without_exact_value_gate(tmp_path):
    report_path = tmp_path / "report.json"
    (tmp_path / "execution_summary.json").write_text(
        json.dumps(
            {
                "status": "success",
                "chart_ids": ["forecast_chart"],
                "forecast_table": [
                    {"horizon": 6, "date": "2026-07-01", "forecast": 4.64, "lower": 4.1, "upper": 5.2}
                ],
                "model_comparison_by_horizon": [
                    {
                        "horizon": 6,
                        "direct_ols_mae": 0.712,
                        "last_value_mae": 0.635,
                        "train_mean_mae": 2.373,
                    }
                ],
                "historical_failure_episodes": [{"target_date": "2020-10-01"}],
            }
        ),
        encoding="utf-8",
    )
    report_path.write_text(
        json.dumps(
            {
                "query": "Give a skeptical unemployment forecast review.",
                "title": "Forecast Review",
                "executive_summary": "The forecast reaches 4.0% in mid-2025.",
                "markdown": (
                    "## Executive Summary\n"
                    "The unemployment forecast reaches 4.0% in mid-2025, with a 3.8% "
                    "to 4.4% interval.\n"
                    "<!-- CHART:forecast_chart -->\n"
                ),
                "charts": [{"id": "forecast_chart"}],
                "data_sources": [],
                "metadata": {"word_count": 40},
            }
        ),
        encoding="utf-8",
    )

    payload = json.loads(
        submit_quality_decision.invoke(
            {
                "decision": "approve",
                "report_path": str(report_path),
                "notes": "Looks acceptable.",
            }
        )
    )

    assert payload["status"] == "approved"


def test_submit_quality_decision_rejects_stale_current_helper_evidence(tmp_path):
    report_path = tmp_path / "report.json"
    (tmp_path / "execution_summary.json").write_text(
        json.dumps(
            {
                "status": "success",
                "chart_ids": ["risk_chart"],
                "composite_current_row": {
                    "date": "2024-12-01",
                    "composite_percentile_0_100": 42.0,
                    "classification": "moderate",
                },
                "composite_validation_metrics": {"status": "ok", "event_count": 4},
            }
        ),
        encoding="utf-8",
    )
    report_path.write_text(
        json.dumps(
            {
                "created_at": "2026-05-02T17:00:00+00:00",
                "query": "Assess macro signals with charts.",
                "title": "Macro Signal Report",
                "executive_summary": "Signal summary.",
                "markdown": "## Executive Summary\nSignal summary with backtest.",
                "charts": [{"id": "risk_chart"}],
                "data_sources": [],
                "metadata": {"word_count": 7},
            }
        ),
        encoding="utf-8",
    )

    payload = json.loads(
        submit_quality_decision.invoke(
            {
                "decision": "approve",
                "report_path": str(report_path),
                "notes": "Looks acceptable.",
            }
        )
    )

    assert payload["status"] == "rejected"
    assert "stale current helper evidence" in payload["reason"]
    assert "2024-12-01" in payload["reason"]


def test_submit_quality_decision_rejects_state_comparison_numeric_drift(tmp_path):
    report_path = tmp_path / "report.json"
    (tmp_path / "execution_summary.json").write_text(
        json.dumps(
            {
                "status": "success",
                "chart_ids": ["state_income"],
                "state_comparison": [
                    {"state": "California", "income": 96334},
                    {"state": "Texas", "income": 76292},
                    {"state": "Florida", "income": 71711},
                ],
            }
        ),
        encoding="utf-8",
    )
    report_path.write_text(
        json.dumps(
            {
                "query": "Compare consumer stress across large states with charts.",
                "title": "State Consumer Stress",
                "executive_summary": "Large states diverge.",
                "markdown": (
                    "## Executive Summary\n"
                    "California income is $91,905, Texas is $67,321, and "
                    "Florida is $67,917 in the state comparison.\n"
                    "<!-- CHART:state_income -->"
                ),
                "charts": [{"id": "state_income"}],
                "data_sources": [],
                "metadata": {"word_count": 24},
            }
        ),
        encoding="utf-8",
    )

    payload = json.loads(
        submit_quality_decision.invoke(
            {
                "decision": "approve",
                "report_path": str(report_path),
                "notes": "Looks acceptable.",
            }
        )
    )

    assert payload["status"] == "rejected"
    assert "state_comparison" in payload["reason"]
    assert "California" in payload["reason"]


def test_submit_quality_decision_accepts_state_income_display_values_with_tolerance(tmp_path):
    report_path = tmp_path / "report.json"
    numeric_facts = [
        {
            "id": "state_comparison.CA.per_capita_personal_income",
            "label": "California per-capita personal income",
            "subject": "California",
            "metric": "per_capita_personal_income",
            "raw_value": 91116,
            "display_value": "$91,120",
            "unit": "usd_per_person",
            "precision": -1,
            "tolerance": 5,
            "source_key": "state_comparison[CA].income",
            "as_of_date": "2025-01",
        },
        {
            "id": "state_comparison.NY.per_capita_personal_income",
            "label": "New York per-capita personal income",
            "subject": "New York",
            "metric": "per_capita_personal_income",
            "raw_value": 88847,
            "display_value": "$88,850",
            "unit": "usd_per_person",
            "precision": -1,
            "tolerance": 5,
            "source_key": "state_comparison[NY].income",
            "as_of_date": "2025-01",
        },
        {
            "id": "state_comparison.TX.per_capita_personal_income",
            "label": "Texas per-capita personal income",
            "subject": "Texas",
            "metric": "per_capita_personal_income",
            "raw_value": 72364,
            "display_value": "$72,360",
            "unit": "usd_per_person",
            "precision": -1,
            "tolerance": 5,
            "source_key": "state_comparison[TX].income",
            "as_of_date": "2025-01",
        },
    ]
    (tmp_path / "execution_summary.json").write_text(
        json.dumps(
            {
                "status": "success",
                "chart_ids": ["state_income"],
                "state_comparison": [
                    {"state": "California", "state_code": "CA", "income": 91116},
                    {"state": "New York", "state_code": "NY", "income": 88847},
                    {"state": "Texas", "state_code": "TX", "income": 72364},
                ],
                "numeric_facts": numeric_facts,
            }
        ),
        encoding="utf-8",
    )
    report_path.write_text(
        json.dumps(
            {
                "query": "Compare consumer stress across large states with charts.",
                "title": "State Consumer Stress",
                "executive_summary": "Large states diverge.",
                "markdown": (
                    "## Executive Summary\n"
                    "California per-capita personal income is $91,120, "
                    "New York is $88,850, and Texas is $72,360.\n"
                    "<!-- CHART:state_income -->"
                ),
                "charts": [{"id": "state_income"}],
                "data_sources": [],
                "metadata": {"word_count": 32},
            }
        ),
        encoding="utf-8",
    )

    payload = json.loads(
        submit_quality_decision.invoke(
            {
                "decision": "approve",
                "report_path": str(report_path),
                "notes": "Looks acceptable.",
            }
        )
    )

    assert payload["status"] == "approved"


def test_submit_quality_decision_rejects_uncovered_historical_analog_claim(tmp_path):
    report_path = tmp_path / "report.json"
    (tmp_path / "execution_summary.json").write_text(
        json.dumps(
            {
                "status": "success",
                "chart_ids": ["historical_analog_distance"],
                "analog_similarity_ranking": [
                    {"label": "2020 covid shock", "status": "included"}
                ],
                "historical_window_coverage": [
                    {
                        "label": "2001 recession",
                        "status": "not_available",
                        "observed_months": 0,
                        "expected_months": 30,
                    },
                    {
                        "label": "2020 covid shock",
                        "status": "covered",
                        "observed_months": 29,
                        "expected_months": 29,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    report_path.write_text(
        json.dumps(
            {
                "query": "Build a historical analog comparison with charts.",
                "title": "Macro Analogs",
                "executive_summary": "Analog evidence.",
                "markdown": (
                    "## Historical Analog\n"
                    "The 2001 recession is the closest historical analog by distance score.\n"
                    "<!-- CHART:historical_analog_distance -->"
                ),
                "charts": [{"id": "historical_analog_distance"}],
                "data_sources": [],
                "metadata": {"word_count": 20},
            }
        ),
        encoding="utf-8",
    )

    payload = json.loads(
        submit_quality_decision.invoke(
            {
                "decision": "approve",
                "report_path": str(report_path),
                "notes": "Looks acceptable.",
            }
        )
    )

    assert payload["status"] == "rejected"
    assert "without covered source history" in payload["reason"]
    assert "2001 recession" in payload["reason"]


def test_submit_quality_decision_allows_generic_scenario_score_rows(tmp_path):
    report_path = tmp_path / "report.json"
    scenario_score_rows = [
        {"scenario": "base", "score": 0.0, "note": "Soft landing continues"},
        {"scenario": "bull", "score": 1.0, "note": "Inflation cools"},
        {"scenario": "bear", "score": -1.0, "note": "Consumer stress broadens"},
    ]
    (tmp_path / "execution_summary.json").write_text(
        json.dumps(
            {
                "status": "success",
                "chart_ids": ["scenario_flow"],
                "scenario_score_rows": scenario_score_rows,
            }
        ),
        encoding="utf-8",
    )
    report_path.write_text(
        json.dumps(
            {
                "query": "Include scenario triggers and charts.",
                "title": "Scenarios",
                "executive_summary": "Scenario triggers.",
                "markdown": (
                    "## Scenario Table\n"
                    "| Scenario | Assumptions | Indicator Triggers | Confidence | Uncertainty Notes |\n"
                    "|---|---|---|---|---|\n"
                    "| base | Soft landing continues | Unemployment 4.3-4.5%; CPI 2.3-2.7% | medium | Data revisions |\n"
                    "| bull | Inflation cools | Consumer stress below 60 | low | Policy lag |\n"
                    "| bear | Consumer stress broadens | Unemployment above 5.0% | medium | Timing risk |\n"
                    "<!-- CHART:scenario_flow -->"
                ),
                "charts": [{"id": "scenario_flow"}],
                "data_sources": [],
                "metadata": {"word_count": 58},
            }
        ),
        encoding="utf-8",
    )

    payload = json.loads(
        submit_quality_decision.invoke(
            {
                "decision": "approve",
                "report_path": str(report_path),
                "notes": "Looks acceptable.",
            }
        )
    )

    assert payload["status"] == "approved"
    assert payload["ready_for_upload"] is True
    assert "failure_category" not in payload


def test_submit_quality_decision_rejects_generic_numeric_fact_drift(tmp_path):
    report_path = tmp_path / "report.json"
    (tmp_path / "execution_summary.json").write_text(
        json.dumps(
            {
                "status": "success",
                "chart_ids": ["company_metrics"],
                "numeric_facts": [
                    {
                        "id": "sec_company_facts.AAPL.revenue_b",
                        "label": "AAPL latest revenue",
                        "display_value": "$365.82B",
                        "raw_value": 365.82,
                        "tolerance": 0.005,
                        "source_key": "sec_company_facts.latest_fundamentals.AAPL.revenue_b",
                        "subject": "AAPL",
                        "metric": "revenue_b",
                    },
                    {
                        "id": "sec_company_facts.MSFT.revenue_b",
                        "label": "MSFT latest revenue",
                        "display_value": "$168.09B",
                        "raw_value": 168.09,
                        "tolerance": 0.005,
                        "source_key": "sec_company_facts.latest_fundamentals.MSFT.revenue_b",
                        "subject": "MSFT",
                        "metric": "revenue_b",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    report_path.write_text(
        json.dumps(
            {
                "query": "Explain Apple and Microsoft earnings sensitivity with charts.",
                "title": "Tech Earnings Sensitivity",
                "executive_summary": "Apple is more consumer exposed.",
                "markdown": (
                    "## Executive Summary\n"
                    "AAPL revenue is about $391B and MSFT revenue is about $227B. "
                    "<!-- CHART:company_metrics -->"
                ),
                "charts": [{"id": "company_metrics"}],
                "data_sources": [],
                "metadata": {"word_count": 25},
            }
        ),
        encoding="utf-8",
    )

    payload = json.loads(
        submit_quality_decision.invoke(
            {
                "decision": "approve",
                "report_path": str(report_path),
                "notes": "Looks acceptable.",
            }
        )
    )

    assert payload["status"] == "rejected"
    assert payload["failure_category"] == "numeric_fact_mismatch"
    assert "AAPL revenue_b" in payload["reason"]
    assert "MSFT revenue_b" in payload["reason"]


def test_submit_quality_decision_rejects_missing_helper_evidence_after_sec_fetch(tmp_path):
    report_path = tmp_path / "report.json"
    (tmp_path / "execution_summary.json").write_text(
        json.dumps(
            {
                "status": "success",
                "chart_ids": [],
                "quant_input_manifest": {
                    "data_files": {
                        "NVDA_SEC": str(tmp_path / "NVDA_sec_edgar_company_facts.csv"),
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    report_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "job_id": "qa-missing-company-fundamentals",
                "created_at": "2026-05-14T12:00:00Z",
                "query": (
                    "Prepare a stock-specific research report on NVIDIA revenue, "
                    "margin, cash-flow, balance-sheet trends, and scenarios."
                ),
                "title": "NVIDIA Fundamentals",
                "executive_summary": "NVIDIA growth is discussed.",
                "markdown": "## Executive Summary\nNVDA revenue and margin trends are discussed.",
                "charts": {},
                "data_sources": [],
                "metadata": {"analysis_type": "earnings", "chart_count": 0, "word_count": 8},
            }
        ),
        encoding="utf-8",
    )

    payload = json.loads(
        submit_quality_decision.invoke(
            {
                "decision": "approve",
                "report_path": str(report_path),
                "notes": "Looks acceptable.",
            }
        )
    )

    assert payload["status"] == "rejected"
    assert payload["failure_category"] == "missing_helper_evidence"
    assert payload["required_upstream"] == "quantitative-developer"
    assert "numeric_facts" in payload["reason"]
    assert "source_coverage" in payload["reason"]


def test_submit_quality_decision_rejects_unsupported_valuation_claim(tmp_path):
    report_path = tmp_path / "report.json"
    (tmp_path / "execution_summary.json").write_text(
        json.dumps(
            {
                "status": "success",
                "chart_ids": [],
                "latest_fundamentals": {"NVDA": {"revenue_b": 215.938}},
                "source_coverage": {
                    "sec_company_facts": {"status": "covered"},
                    "valuation_market_data": {
                        "status": "not_available",
                        "limitation": "Market valuation data is unavailable.",
                        "capability_list": ["price", "market_cap", "valuation_multiples"],
                    },
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
                        "literal_required": False,
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
                "job_id": "qa-unsupported-valuation",
                "created_at": "2026-05-14T12:00:00Z",
                "query": "Prepare a stock-specific NVIDIA fundamentals and valuation report.",
                "title": "NVIDIA Valuation",
                "executive_summary": "NVIDIA has attractive valuation upside.",
                "markdown": (
                    "## Executive Summary\n"
                    "NVDA has a $2.5T market cap and trades at an attractive multiple."
                ),
                "charts": {},
                "data_sources": [],
                "metadata": {"analysis_type": "earnings", "chart_count": 0, "word_count": 15},
            }
        ),
        encoding="utf-8",
    )

    payload = json.loads(
        submit_quality_decision.invoke(
            {
                "decision": "approve",
                "report_path": str(report_path),
                "notes": "Looks acceptable.",
            }
        )
    )

    assert payload["status"] == "rejected"
    assert payload["failure_category"] == "unsupported_valuation_claim"
    assert payload["required_upstream"] == "technical-writer"
    assert "valuation_market_data.status=not_available" in payload["reason"]


def test_submit_quality_decision_rejects_manual_sec_facts_from_source_files(tmp_path):
    report_path = tmp_path / "report.json"
    (tmp_path / "execution_summary.json").write_text(
        json.dumps(
            {
                "status": "success",
                "chart_ids": [],
                "source_files": {
                    "sec_company_facts": str(tmp_path / "NVDA_sec_edgar_company_facts.csv"),
                },
                "numeric_facts": [
                    {
                        "id": "latest_revenue",
                        "display_value": "215,938,000,000",
                        "raw_value": 215_938_000_000,
                        "tolerance": 0.1,
                        "source_key": "sec_company_facts",
                        "subject": "NVDA",
                        "metric": "revenue",
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
                "job_id": "qa-manual-sec-facts",
                "created_at": "2026-05-14T12:00:00Z",
                "query": "Prepare a stock-specific research report on NVIDIA fundamentals.",
                "title": "NVIDIA Fundamentals",
                "executive_summary": "NVIDIA fundamentals are discussed.",
                "markdown": "## Executive Summary\nNVDA revenue and balance-sheet strength are discussed.",
                "charts": {},
                "data_sources": [],
                "metadata": {"analysis_type": "earnings", "chart_count": 0, "word_count": 9},
            }
        ),
        encoding="utf-8",
    )

    payload = json.loads(
        submit_quality_decision.invoke(
            {
                "decision": "approve",
                "report_path": str(report_path),
                "notes": "Looks acceptable.",
            }
        )
    )

    assert payload["status"] == "rejected"
    assert payload["failure_category"] == "missing_helper_evidence"
    assert "sec_company_facts.* numeric_facts" in payload["reason"]


def test_submit_quality_decision_rejects_missing_helper_evidence_from_data_files_used(tmp_path):
    report_path = tmp_path / "report.json"
    (tmp_path / "execution_summary.json").write_text(
        json.dumps(
            {
                "status": "success",
                "chart_ids": [],
                "data_files_used": ["sec_facts"],
            }
        ),
        encoding="utf-8",
    )
    report_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "job_id": "qa-missing-company-fundamentals-data-files-used",
                "created_at": "2026-05-14T12:00:00Z",
                "query": (
                    "Prepare a stock-specific research report on NVIDIA revenue, "
                    "margin, cash-flow, balance-sheet trends, and scenarios."
                ),
                "title": "NVIDIA Fundamentals",
                "executive_summary": "NVIDIA growth is discussed.",
                "markdown": "## Executive Summary\nNVDA revenue and margin trends are discussed.",
                "charts": {},
                "data_sources": [],
                "metadata": {"analysis_type": "earnings", "chart_count": 0, "word_count": 8},
            }
        ),
        encoding="utf-8",
    )

    payload = json.loads(
        submit_quality_decision.invoke(
            {
                "decision": "approve",
                "report_path": str(report_path),
                "notes": "Looks acceptable.",
            }
        )
    )

    assert payload["status"] == "rejected"
    assert payload["failure_category"] == "missing_helper_evidence"
    assert payload["required_upstream"] == "quantitative-developer"
    assert "SEC company-facts files are present" in payload["reason"]


def test_submit_quality_decision_rejects_company_fundamental_numeric_drift(tmp_path):
    report_path = tmp_path / "report.json"
    (tmp_path / "execution_summary.json").write_text(
        json.dumps(
            {
                "status": "success",
                "chart_ids": [],
                "latest_fundamentals": {
                    "NVDA": {
                        "revenue_b": 215.938,
                        "cash_and_securities_b": 10.605,
                        "diluted_eps": 4.9,
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
                        "literal_required": False,
                    },
                    {
                        "id": "sec_company_facts.NVDA.cash_and_securities_b",
                        "display_value": "$10.605B",
                        "raw_value": 10.605,
                        "tolerance": 0.005,
                        "source_key": "sec_company_facts.latest_fundamentals.NVDA.cash_and_securities_b",
                        "subject": "NVDA",
                        "metric": "cash_and_securities_b",
                        "literal_required": False,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    report_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "job_id": "qa-company-fundamental-drift",
                "created_at": "2026-05-14T12:00:00Z",
                "query": "Review NVIDIA revenue and balance sheet.",
                "title": "NVIDIA Fundamentals",
                "executive_summary": "NVIDIA revenue and balance sheet are discussed.",
                "markdown": "## Executive Summary\nNVDA revenue was about $130B and cash exceeded $40B.",
                "charts": {},
                "data_sources": [],
                "metadata": {"analysis_type": "earnings", "chart_count": 0, "word_count": 10},
            }
        ),
        encoding="utf-8",
    )

    payload = json.loads(
        submit_quality_decision.invoke(
            {
                "decision": "approve",
                "report_path": str(report_path),
                "notes": "Looks acceptable.",
            }
        )
    )

    assert payload["status"] == "rejected"
    assert payload["failure_category"] == "numeric_fact_mismatch"
    assert payload["required_upstream"] == "technical-writer"
    assert "NVDA revenue_b" in payload["reason"]
    assert "NVDA cash_and_securities_b" in payload["reason"]


def test_submit_quality_decision_rejects_helper_complete_cash_and_debt_drift(tmp_path):
    report_path = tmp_path / "report.json"
    (tmp_path / "execution_summary.json").write_text(
        json.dumps(
            {
                "status": "success",
                "chart_ids": [],
                "source_files": {
                    "sec_company_facts": str(tmp_path / "NVDA_sec_edgar_company_facts.csv"),
                },
                "source_coverage": {"sec_company_facts": {"status": "covered"}},
                "latest_fundamentals": {
                    "NVDA": {
                        "revenue_b": 215.938,
                        "cash_and_securities_b": 10.605,
                        "long_term_debt_b": 7.469,
                    }
                },
                "numeric_facts": [
                    {
                        "id": "sec_company_facts.NVDA.cash_and_securities_b",
                        "display_value": "$10.605B",
                        "raw_value": 10.605,
                        "tolerance": 0.005,
                        "source_key": "sec_company_facts.latest_fundamentals.NVDA.cash_and_securities_b",
                        "subject": "NVDA",
                        "metric": "cash_and_securities_b",
                    },
                    {
                        "id": "sec_company_facts.NVDA.long_term_debt_b",
                        "display_value": "$7.469B",
                        "raw_value": 7.469,
                        "tolerance": 0.005,
                        "source_key": "sec_company_facts.latest_fundamentals.NVDA.long_term_debt_b",
                        "subject": "NVDA",
                        "metric": "long_term_debt_b",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    report_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "job_id": "qa-helper-complete-company-drift",
                "created_at": "2026-05-14T12:00:00Z",
                "query": "Review NVIDIA balance sheet quality.",
                "title": "NVIDIA Balance Sheet",
                "executive_summary": "NVIDIA cash and debt are discussed.",
                "markdown": "## Executive Summary\nNVDA has more than $40B cash and essentially zero debt.",
                "charts": {},
                "data_sources": [],
                "metadata": {"analysis_type": "earnings", "chart_count": 0, "word_count": 11},
            }
        ),
        encoding="utf-8",
    )

    payload = json.loads(
        submit_quality_decision.invoke(
            {
                "decision": "approve",
                "report_path": str(report_path),
                "notes": "Looks acceptable.",
            }
        )
    )

    assert payload["status"] == "rejected"
    assert payload["failure_category"] == "numeric_fact_mismatch"
    assert "NVDA cash_and_securities_b" in payload["reason"]
    assert "NVDA long_term_debt_b" in payload["reason"]


def test_submit_quality_decision_accepts_zero_duration_current_state_prose(tmp_path):
    report_path = tmp_path / "report.json"
    (tmp_path / "execution_summary.json").write_text(
        json.dumps(
            {
                "status": "success",
                "numeric_facts": [
                    {
                        "id": "inversion",
                        "label": "Inversion Months",
                        "value": 0,
                        "unit": "months",
                        "precision": 0,
                        "literal_required": True,
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
                "job_id": "qa-zero-duration-good",
                "created_at": "2026-05-14T12:00:00Z",
                "query": "Review whether the yield curve is currently inverted.",
                "title": "Yield Curve State",
                "executive_summary": "The yield curve is not currently inverted.",
                "markdown": (
                    "## Executive Summary\n"
                    "The yield curve is not currently inverted after a prolonged inversion "
                    "that ended earlier in 2025."
                ),
                "charts": {},
                "data_sources": [],
                "metadata": {"analysis_type": "macro", "chart_count": 0, "word_count": 18},
            }
        ),
        encoding="utf-8",
    )

    payload = json.loads(
        submit_quality_decision.invoke(
            {
                "decision": "approve",
                "report_path": str(report_path),
                "notes": "Looks acceptable.",
            }
        )
    )

    assert payload["status"] == "approved"


def test_submit_quality_decision_rejects_zero_duration_as_historical_duration(tmp_path):
    report_path = tmp_path / "report.json"
    (tmp_path / "execution_summary.json").write_text(
        json.dumps(
            {
                "status": "success",
                "numeric_facts": [
                    {
                        "id": "inversion",
                        "label": "Inversion Months",
                        "value": 0,
                        "unit": "months",
                        "precision": 0,
                        "literal_required": True,
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
                "job_id": "qa-zero-duration-bad",
                "created_at": "2026-05-14T12:00:00Z",
                "query": "Review whether the yield curve is currently inverted.",
                "title": "Yield Curve State",
                "executive_summary": "The curve normalized after 0 months.",
                "markdown": (
                    "## Executive Summary\n"
                    "The yield curve has normalized after 0 months of inversion."
                ),
                "charts": {},
                "data_sources": [],
                "metadata": {"analysis_type": "macro", "chart_count": 0, "word_count": 11},
            }
        ),
        encoding="utf-8",
    )

    payload = json.loads(
        submit_quality_decision.invoke(
            {
                "decision": "approve",
                "report_path": str(report_path),
                "notes": "Looks acceptable.",
            }
        )
    )

    assert payload["status"] == "rejected"
    assert payload["failure_category"] == "numeric_fact_mismatch"
    assert payload["required_upstream"] == "technical-writer"
    assert "zero-duration" in payload["reason"]


def test_submit_quality_decision_rejects_static_chart_semantics_blockers(tmp_path):
    report_path = tmp_path / "report.json"
    (tmp_path / "execution_summary.json").write_text(
        json.dumps({"status": "success", "chart_ids": ["duplicate_axis"]}),
        encoding="utf-8",
    )
    chart = {
        "id": "duplicate_axis",
        "type": "line",
        "title": "Duplicate Axis",
        "description": "Duplicate x-axis rows should block QA approval.",
        "xAxisKey": "date",
        "series": [{"dataKey": "value", "label": "Value", "color": "#2563eb"}],
        "data": [
            {"date": "2026-01", "value": 1.0},
            {"date": "2026-01", "value": 2.0},
        ],
    }
    report_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "job_id": "qa-chart-semantics",
                "created_at": "2026-05-14T12:00:00Z",
                "query": "Include charts in the macro report.",
                "title": "Chart Semantics",
                "executive_summary": "Chart data is invalid.",
                "markdown": "## Executive Summary\nChart follows.\n<!-- CHART:duplicate_axis -->",
                "charts": {"duplicate_axis": chart},
                "data_sources": [],
                "metadata": {"analysis_type": "macro", "chart_count": 1, "word_count": 6},
            }
        ),
        encoding="utf-8",
    )

    payload = json.loads(
        submit_quality_decision.invoke(
            {
                "decision": "approve",
                "report_path": str(report_path),
                "notes": "Looks acceptable.",
            }
        )
    )

    assert payload["status"] == "rejected"
    assert payload["failure_category"] == "chart_semantics_mismatch"
    assert payload["required_upstream"] == "quantitative-developer"
    assert "duplicate x-axis rows" in payload["reason"]


def test_submit_quality_decision_rejects_mixed_hourly_weekly_wage_gap(tmp_path):
    hourly_path = tmp_path / "CES0500000003.csv"
    weekly_path = tmp_path / "CES0500000030.csv"
    hourly_path.write_text(
        "date,value,series_id,units\n2025-12-01,37.02,CES0500000003,dollars per hour\n",
        encoding="utf-8",
    )
    weekly_path.write_text(
        "date,value,series_id\n2025-12-01,1072.67,CES0500000030\n",
        encoding="utf-8",
    )
    report_path = tmp_path / "report.json"
    (tmp_path / "execution_summary.json").write_text(
        json.dumps(
            {
                "status": "success",
                "source_files": {
                    "all_hourly": str(hourly_path),
                    "prod_weekly": str(weekly_path),
                },
                "statistical_summary": {"wage_divergence_latest": -802.27},
            }
        ),
        encoding="utf-8",
    )
    report_path.write_text(
        json.dumps(
            {
                "query": "Assess whether the consumer is fine using wage evidence.",
                "title": "Consumer Wage Stress",
                "executive_summary": "The wage gap is widening.",
                "markdown": (
                    "## Executive Summary\n"
                    "A widening real wage gap between all employees and production workers "
                    "shows hidden stress."
                ),
                "charts": [],
                "data_sources": [],
                "metadata": {"word_count": 18},
            }
        ),
        encoding="utf-8",
    )

    payload = json.loads(
        submit_quality_decision.invoke(
            {
                "decision": "approve",
                "report_path": str(report_path),
                "notes": "Looks acceptable.",
            }
        )
    )

    assert payload["status"] == "rejected"
    assert payload["failure_category"] == "source_unit_mismatch"
    assert payload["required_upstream"] == "quantitative-developer"
    assert "incompatible unit bases" in payload["reason"]
    assert "dollars per hour" in payload["reason"]
    assert "dollars per week" in payload["reason"]


def test_submit_quality_decision_rejects_missing_handoff_chart_ids(tmp_path):
    report_path = tmp_path / "report.json"
    (tmp_path / "execution_summary.json").write_text(
        json.dumps(
            {
                "status": "success",
                "chart_ids": ["consumer_stress_dashboard", "savings_credit_stress"],
            }
        ),
        encoding="utf-8",
    )
    chart = {
        "id": "consumer_stress_dashboard",
        "type": "line",
        "title": "Consumer Stress",
        "description": "Consumer stress over time.",
        "xAxisKey": "date",
        "series": [{"dataKey": "value", "label": "Value", "color": "#2563eb"}],
        "data": [{"date": "2026-01", "value": 1.0}],
    }
    report_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "job_id": "qa-chart-handoff",
                "created_at": "2026-05-14T12:00:00Z",
                "query": "Include charts in the macro report.",
                "title": "Chart Handoff",
                "executive_summary": "One chart survived.",
                "markdown": (
                    "## Executive Summary\nOne chart survived.\n"
                    "<!-- CHART:consumer_stress_dashboard -->"
                ),
                "charts": {"consumer_stress_dashboard": chart},
                "data_sources": [],
                "metadata": {"analysis_type": "macro", "chart_count": 1, "word_count": 6},
            }
        ),
        encoding="utf-8",
    )

    payload = json.loads(
        submit_quality_decision.invoke(
            {
                "decision": "approve",
                "report_path": str(report_path),
                "notes": "Looks acceptable.",
            }
        )
    )

    assert payload["status"] == "rejected"
    assert payload["failure_category"] == "chart_handoff_mismatch"
    assert payload["required_upstream"] == "quant-developer"
    assert "missing_report_chart_ids=['savings_credit_stress']" in payload["reason"]


def test_submit_quality_decision_rejects_mixed_hourly_weekly_wage_chart_overlay(tmp_path):
    hourly_path = tmp_path / "CES0500000003.csv"
    weekly_path = tmp_path / "CES0500000030.csv"
    hourly_path.write_text(
        "date,value,series_id,units\n2025-12-01,37.02,CES0500000003,dollars per hour\n",
        encoding="utf-8",
    )
    weekly_path.write_text(
        "date,value,series_id\n2025-12-01,1072.67,CES0500000030\n",
        encoding="utf-8",
    )
    report_path = tmp_path / "report.json"
    (tmp_path / "execution_summary.json").write_text(
        json.dumps(
            {
                "status": "success",
                "source_files": {
                    "all_hourly": str(hourly_path),
                    "prod_weekly": str(weekly_path),
                },
                "statistical_summary": {"latest_all": 37.02, "latest_prod": 1072.67},
            }
        ),
        encoding="utf-8",
    )
    report_path.write_text(
        json.dumps(
            {
                "query": "Assess earnings levels for consumer stress.",
                "title": "Consumer Earnings Stress",
                "executive_summary": "The labor signal is mixed.",
                "markdown": "## Executive Summary\nThe labor signal is mixed.",
                "charts": {
                    "earnings_levels": {
                        "id": "earnings_levels",
                        "type": "line",
                        "title": "Hourly Earnings Levels",
                        "description": "All employees and production workers.",
                        "xAxisKey": "date",
                        "series": [
                            {"dataKey": "all_hourly", "label": "All employees"},
                            {"dataKey": "prod_weekly", "label": "Production workers"},
                        ],
                        "data": [
                            {
                                "date": "2025-12-01",
                                "all_hourly": 37.02,
                                "prod_weekly": 1072.67,
                            }
                        ],
                    }
                },
                "data_sources": [],
                "metadata": {"word_count": 8},
            }
        ),
        encoding="utf-8",
    )

    payload = json.loads(
        submit_quality_decision.invoke(
            {
                "decision": "approve",
                "report_path": str(report_path),
                "notes": "Looks acceptable.",
            }
        )
    )

    assert payload["status"] == "rejected"
    assert payload["failure_category"] == "source_unit_mismatch"
    assert "direct wage chart overlays" in payload["reason"]
    assert "earnings_levels" in payload["reason"]


def test_submit_quality_decision_allows_same_unit_wage_gap_contract(tmp_path):
    report_path = tmp_path / "report.json"
    (tmp_path / "execution_summary.json").write_text(
        json.dumps(
            {
                "status": "success",
                "source_unit_metadata": [
                    {
                        "source_key": "all_hourly",
                        "series_id": "CES0500000003",
                        "units": "dollars per hour",
                        "unit_family": "currency_per_time",
                        "unit_basis": "hour",
                        "measure": "wage",
                    },
                    {
                        "source_key": "prod_hourly",
                        "series_id": "CES0500000008",
                        "units": "dollars per hour",
                        "unit_family": "currency_per_time",
                        "unit_basis": "hour",
                        "measure": "wage",
                    },
                ],
                "unit_comparisons": [
                    {
                        "id": "hourly_wage_gap",
                        "status": "passed",
                        "compatible": True,
                        "sources": [
                            {
                                "source_key": "all_hourly",
                                "units": "dollars per hour",
                                "unit_family": "currency_per_time",
                                "unit_basis": "hour",
                                "measure": "wage",
                            },
                            {
                                "source_key": "prod_hourly",
                                "units": "dollars per hour",
                                "unit_family": "currency_per_time",
                                "unit_basis": "hour",
                                "measure": "wage",
                            },
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    report_path.write_text(
        json.dumps(
            {
                "query": "Assess the hourly wage gap.",
                "title": "Hourly Wage Gap",
                "executive_summary": "Same-unit wage comparison.",
                "markdown": "## Executive Summary\nThe hourly wage gap is computed from hourly series.",
                "charts": [],
                "data_sources": [],
                "metadata": {"word_count": 10},
            }
        ),
        encoding="utf-8",
    )

    payload = json.loads(
        submit_quality_decision.invoke(
            {
                "decision": "approve",
                "report_path": str(report_path),
                "notes": "Looks acceptable.",
            }
        )
    )

    assert payload["status"] == "approved"


def test_submit_quality_decision_rejects_artifact_fact_mismatch(tmp_path):
    report_path = tmp_path / "report.json"
    chart = {
        "id": "macro_correlation_heatmap",
        "type": "bar",
        "title": "Macro Correlations",
        "description": "Correlation facts by pair.",
        "xAxisKey": "pair",
        "series": [
            {"dataKey": "correlation", "label": "Correlation", "color": "#2563eb"}
        ],
        "data": [
            {
                "pair": "(UNRATE, CPIAUCSL)",
                "var1": "UNRATE",
                "var2": "CPIAUCSL",
                "correlation": 0.024,
            }
        ],
    }
    (tmp_path / "execution_summary.json").write_text(
        json.dumps(
            {
                "status": "success",
                "chart_ids": ["macro_correlation_heatmap"],
                "scenario_stress": {
                    "corr": {
                        "UNRATE": {"UNRATE": 1.0, "CPIAUCSL": 0.908},
                        "CPIAUCSL": {"UNRATE": 0.908, "CPIAUCSL": 1.0},
                    }
                },
                "numeric_facts": [
                    {
                        "id": "corr_UNRATE_CPIAUCSL",
                        "label": "Correlation(UNRATE, CPIAUCSL)",
                        "value": 0.024,
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
                "job_id": "qa-artifact-fact",
                "created_at": "2026-05-14T12:00:00Z",
                "query": "Include charts in the macro report.",
                "title": "Artifact Fact Mismatch",
                "executive_summary": "Macro correlations were charted.",
                "markdown": (
                    "## Executive Summary\n"
                    "The UNRATE/CPIAUCSL correlation was 0.024.\n"
                    "<!-- CHART:macro_correlation_heatmap -->"
                ),
                "charts": {"macro_correlation_heatmap": chart},
                "data_sources": [],
                "metadata": {"analysis_type": "macro", "chart_count": 1, "word_count": 8},
            }
        ),
        encoding="utf-8",
    )

    payload = json.loads(
        submit_quality_decision.invoke(
            {
                "decision": "approve",
                "report_path": str(report_path),
                "notes": "Looks acceptable.",
            }
        )
    )

    assert payload["status"] == "rejected"
    assert payload["failure_category"] == "artifact_fact_mismatch"
    assert payload["required_upstream"] == "quant-developer"
    assert "UNRATE/CPIAUCSL" in payload["reason"]


def test_submit_quality_decision_rejects_recession_probability_without_composite_diagnostics(tmp_path):
    report_path = tmp_path / "report.json"
    (tmp_path / "execution_summary.json").write_text(
        json.dumps(
            {
                "status": "success",
                "chart_ids": ["recession_risk"],
                "composite_current_row": {
                    "classification": "low",
                    "composite_percentile_0_100": 0.0,
                },
                "composite_validation_metrics": {
                    "status": "ok",
                    "metrics": {
                        "precision": 0.25,
                        "recall": 0.0484,
                        "false_negative": 59,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    report_path.write_text(
        json.dumps(
            {
                "query": "Assess whether recession risk is rising.",
                "title": "Recession Risk Report",
                "executive_summary": "Recession risk is low.",
                "markdown": (
                    "## Executive Summary\n"
                    "The recession risk score implies roughly 8% probability in the near term."
                ),
                "charts": [{"id": "recession_risk"}],
                "data_sources": [],
                "metadata": {"word_count": 12},
            }
        ),
        encoding="utf-8",
    )

    payload = json.loads(
        submit_quality_decision.invoke(
            {
                "decision": "approve",
                "report_path": str(report_path),
                "notes": "Looks acceptable.",
            }
        )
    )

    assert payload["status"] == "rejected"
    assert "validation diagnostics" in payload["reason"]
    assert any("precision" in fix and "recall" in fix for fix in payload["required_fixes"])


def test_quality_analyst_prompt_requires_econometric_validation():
    prompt = _compact_text(QUALITY_ANALYST_SYSTEM_PROMPT)

    assert "missing validation/replay" in prompt
    assert "predictive or historical-comparison work" in prompt
    assert "backtest_summary" not in prompt


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

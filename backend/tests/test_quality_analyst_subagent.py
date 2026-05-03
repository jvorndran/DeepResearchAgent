import json

from langchain_core.messages import AIMessage, ToolMessage

from agents.quality_analyst import (
    QUALITY_ANALYST_SUBAGENT,
    QUALITY_ANALYST_SYSTEM_PROMPT,
    _normalize_terminal_quality_decision,
    load_report_for_review,
    submit_quality_decision,
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


def test_quality_analyst_prompt_uses_embedded_execution_summary_packet():
    assert "execution_summary` packet" in QUALITY_ANALYST_SYSTEM_PROMPT
    assert "includes the sibling execution summary review packet" in QUALITY_ANALYST_SYSTEM_PROMPT
    assert "Execution-summary fidelity" in QUALITY_ANALYST_SYSTEM_PROMPT
    assert "top analog, similarity scores, risk score, or issuer metrics" in (
        QUALITY_ANALYST_SYSTEM_PROMPT
    )


def test_quality_analyst_prompt_keeps_terminal_decision_compact():
    assert "Silent review" in QUALITY_ANALYST_SYSTEM_PROMPT
    assert "Do not narrate your review" in QUALITY_ANALYST_SYSTEM_PROMPT
    assert "After `submit_quality_decision` returns" in QUALITY_ANALYST_SYSTEM_PROMPT
    assert "emit exactly one compact JSON object" in QUALITY_ANALYST_SYSTEM_PROMPT
    assert "Never emit only `Approved.` or `Rejected.`" in QUALITY_ANALYST_SYSTEM_PROMPT
    assert "Never include markdown tables" in QUALITY_ANALYST_SYSTEM_PROMPT


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
                "top_analog": "2008",
                "similarity_scores": {
                    "1995": 17.4,
                    "2001": 18.7,
                    "2008": 23.7,
                    "2020": 19.7,
                },
                "composite_recession_risk": {"current": 91.3},
                "backtest_summary": {"metrics": {"precision": 0.058}},
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
    assert "top_analog is 2008" in payload["reason"]
    assert any("current value from execution_summary.json (91.3)" in fix for fix in payload["required_fixes"])


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


def test_load_report_for_review_flags_missing_scenario_table_for_scenario_query(tmp_path):
    report_path = tmp_path / "report.json"
    report_path.write_text(
        json.dumps(
            {
                "query": "Build a recession risk dashboard with base, bull, and bear scenarios.",
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

    assert payload["status"] == "success"
    assert payload["scenario_requirement"]["required"] is True
    assert payload["scenario_requirement"]["valid"] is False
    assert payload["scenario_requirement"]["missing_required_rows"] == ["base", "bull", "bear"]


def test_load_report_for_review_flags_missing_upside_downside_scenario_table(tmp_path):
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

    assert payload["scenario_requirement"]["required"] is True
    assert payload["scenario_requirement"]["valid"] is False
    assert payload["scenario_requirement"]["missing_required_rows"] == [
        "base",
        "upside",
        "downside",
    ]


def test_load_report_for_review_accepts_canonical_bull_bear_for_upside_downside_query(tmp_path):
    report_path = tmp_path / "report.json"
    report_path.write_text(
        json.dumps(
            {
                "query": "Show how the conclusion changes under base, upside, and downside cases.",
                "title": "Recession Risk Scenario Dashboard",
                "executive_summary": "Scenario summary.",
                "markdown": "## Executive Summary\nScenario summary.",
                "charts": {},
                "scenario_table": [
                    {"scenario": "base"},
                    {"scenario": "bull"},
                    {"scenario": "bear"},
                ],
                "data_sources": [],
                "metadata": {"word_count": 5},
            }
        ),
        encoding="utf-8",
    )

    payload = json.loads(load_report_for_review.invoke({"report_path": str(report_path)}))

    assert payload["scenario_requirement"]["required"] is True
    assert payload["scenario_requirement"]["valid"] is True
    assert payload["scenario_requirement"]["scenarios"] == ["base", "bull", "bear"]
    assert payload["scenario_requirement"]["missing_required_rows"] == []


def test_submit_quality_decision_rejects_missing_upside_downside_scenario_table(tmp_path):
    report_path = tmp_path / "report.json"
    (tmp_path / "execution_summary.json").write_text(
        json.dumps(
            {
                "status": "success",
                "chart_ids": ["scenario_chart"],
                "backtest_summary": {"precision": 0.5},
            }
        ),
        encoding="utf-8",
    )
    report_path.write_text(
        json.dumps(
            {
                "query": "Show how recession risk changes under base, upside, and downside cases.",
                "title": "Scenario Report",
                "executive_summary": "Scenario summary.",
                "markdown": "## Executive Summary\nScenario summary with backtest.",
                "charts": [{"id": "scenario_chart"}],
                "data_sources": [],
                "metadata": {"word_count": 6},
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
    assert "scenario_table" in payload["reason"]
    assert "upside" in payload["reason"]


def test_quality_analyst_prompt_rejects_missing_required_scenario_table():
    assert "Scenario/stress requests" in QUALITY_ANALYST_SYSTEM_PROMPT
    assert "scenario_requirement.valid" in QUALITY_ANALYST_SYSTEM_PROMPT
    assert "assumptions, indicator triggers, and confidence/uncertainty notes" in QUALITY_ANALYST_SYSTEM_PROMPT


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
    assert "out-of-sample validation" in payload["reason"]
    assert any("historical_simulations" in fix for fix in payload["required_fixes"])


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
    assert "out-of-sample validation" in payload["reason"]
    assert any("historical_simulations" in fix for fix in payload["required_fixes"])


def test_submit_quality_decision_rejects_unsupported_forward_outcome_claims(tmp_path):
    report_path = tmp_path / "report.json"
    (tmp_path / "execution_summary.json").write_text(
        json.dumps(
            {
                "status": "success",
                "chart_ids": ["risk_chart"],
                "backtest_summary": {"status": "ok", "metrics": {"accuracy": 0.7}},
                "historical_simulations": [
                    {"label": "2008", "status": "ok", "outcome_during_window": {"max": 1.0}}
                ],
                "what_happened_next": {
                    "simulation_design": {
                        "outcome_variable": "USREC",
                        "signal_variables": ["yield_slope"],
                        "lookahead_periods": 12,
                    },
                    "historical_simulations": [
                        {
                            "label": "global financial crisis",
                            "status": "ok",
                            "outcome_during_window": {"max": 1.0},
                            "subsequent_outcome": {"periods": 12, "max": 0.0},
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    report_path.write_text(
        json.dumps(
            {
                "query": "Compare prior cycle windows and explain what happened next.",
                "title": "Cycle Replay",
                "executive_summary": "Replay with unsupported market outcomes.",
                "markdown": (
                    "## Executive Summary\nBacktest included.\n\n"
                    "## What Happened Next\n"
                    "| Analog | 12m Forward S&P 500 Return | 12m Forward UNRATE Delta |\n"
                    "|---|---:|---:|\n"
                    "| 2008 | -38.5% | +3.5 pp |\n"
                ),
                "charts": [{"id": "risk_chart"}],
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
                "notes": "Looks acceptable.",
            }
        )
    )

    assert payload["status"] == "rejected"
    assert "forward what-happened-next outcomes" in payload["reason"]
    assert "SP500" in payload["reason"]
    assert "UNRATE" in payload["reason"]


def test_submit_quality_decision_allows_supported_forecast_and_current_production_language(tmp_path):
    report_path = tmp_path / "report.json"
    (tmp_path / "execution_summary.json").write_text(
        json.dumps(
            {
                "status": "success",
                "chart_ids": ["risk_chart", "unemployment_forecast"],
                "backtest_summary": {"status": "ok", "metrics": {"rmse": 0.4}},
                "model_comparison": {"naive_last_value": {"rmse": 0.6}},
                "forecast_table": [
                    {"horizon": 6, "forecast": 4.64, "lower_95": 2.58, "upper_95": 6.70}
                ],
                "historical_simulations": [
                    {"label": "2008", "status": "ok", "outcome_during_window": {"max": 1.0}}
                ],
                "historical_replay": {
                    "simulation_design": {
                        "outcome_variable": "USREC",
                        "signal_variables": ["composite_index"],
                        "lookahead_periods": 12,
                    },
                    "historical_simulations": [
                        {
                            "label": "global financial crisis",
                            "status": "ok",
                            "outcome_during_window": {"max": 1.0},
                            "subsequent_outcome": {"periods": 12, "max": 0.0},
                        }
                    ],
                },
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
                "scenario_table": [
                    {
                        "scenario": "base",
                        "assumptions": ["Soft landing"],
                        "indicator_triggers": ["Claims stable"],
                        "confidence": "medium",
                        "uncertainty_notes": "Data revisions",
                    },
                    {
                        "scenario": "bull",
                        "assumptions": ["Reacceleration"],
                        "indicator_triggers": ["Productivity improves"],
                        "confidence": "low",
                        "uncertainty_notes": "Inflation risk",
                    },
                    {
                        "scenario": "bear",
                        "assumptions": ["Recession"],
                        "indicator_triggers": ["Claims rise"],
                        "confidence": "medium",
                        "uncertainty_notes": "Shock risk",
                    },
                ],
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


def test_submit_quality_decision_rejects_stale_current_signal_stack(tmp_path):
    report_path = tmp_path / "report.json"
    (tmp_path / "execution_summary.json").write_text(
        json.dumps(
            {
                "status": "success",
                "chart_ids": ["risk_chart"],
                "statistical_summary": {
                    "current_signal_stack": {
                        "as_of_date": "2024-12-01",
                        "composite_score": 0,
                    }
                },
                "backtest_summary": {"precision": 1.0},
            }
        ),
        encoding="utf-8",
    )
    report_path.write_text(
        json.dumps(
            {
                "created_at": "2026-05-02T17:00:00+00:00",
                "query": "Which current signals confirm or contradict recession risk?",
                "title": "Current Recession Risk Report",
                "executive_summary": "Current signal summary.",
                "markdown": "## Executive Summary\nCurrent signal summary with backtest.",
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
    assert "stale quantitative" in payload["reason"]
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


def test_submit_quality_decision_rejects_tech_earnings_numeric_drift(tmp_path):
    report_path = tmp_path / "report.json"
    (tmp_path / "execution_summary.json").write_text(
        json.dumps(
            {
                "status": "success",
                "chart_ids": ["tech_earnings"],
                "tech_earnings": {
                    "AAPL_rev_b": 365.82,
                    "AAPL_nm_pct": 25.9,
                    "MSFT_rev_b": 168.09,
                    "MSFT_nm_pct": 36.5,
                },
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
                    "Apple revenue is about $391B and Microsoft revenue is about $227B. "
                    "AAPL net margin is 25.9% and MSFT net margin is 36.5%.\n"
                    "<!-- CHART:tech_earnings -->"
                ),
                "charts": [{"id": "tech_earnings"}],
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
    assert "tech_earnings" in payload["reason"]
    assert "AAPL revenue" in payload["reason"]
    assert "MSFT revenue" in payload["reason"]


def test_submit_quality_decision_rejects_recession_probability_without_composite_diagnostics(tmp_path):
    report_path = tmp_path / "report.json"
    (tmp_path / "execution_summary.json").write_text(
        json.dumps(
            {
                "status": "success",
                "chart_ids": ["recession_risk"],
                "composite_predictive_indicator": {
                    "latest_signal": "low",
                    "latest_percentile_0_100": 0.0,
                    "backtest_summary": {
                        "status": "ok",
                        "metrics": {
                            "precision": 0.25,
                            "recall": 0.0484,
                            "false_negative": 59,
                        },
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
    assert "backtest diagnostics" in payload["reason"]
    assert any("precision" in fix and "recall" in fix for fix in payload["required_fixes"])


def test_quality_analyst_prompt_requires_econometric_validation():
    assert "Econometric validation" in QUALITY_ANALYST_SYSTEM_PROMPT
    assert "backtest_summary" in QUALITY_ANALYST_SYSTEM_PROMPT
    assert "historical_simulations" in QUALITY_ANALYST_SYSTEM_PROMPT


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

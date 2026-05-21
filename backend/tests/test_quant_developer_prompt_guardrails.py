import json
import shlex
from pathlib import Path
from types import SimpleNamespace

from langchain.agents.middleware.types import ModelResponse
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage

import agents.quantitative_developer as quant_dev
from agents.quantitative_developer import (
    QUANT_DEVELOPER_SUBAGENT,
    QUANT_DEVELOPER_SYSTEM_PROMPT,
    QuantDeveloperToolBoundaryMiddleware,
)


class _Request:
    def __init__(self, tools, messages=None, runtime=None):
        self.tools = tools
        self.messages = messages or []
        self.runtime = runtime

    def override(self, **kwargs):
        return _Request(
            kwargs.get("tools", self.tools),
            messages=kwargs.get("messages", self.messages),
            runtime=kwargs.get("runtime", self.runtime),
        )


def test_quant_prompt_requires_analysis_script_not_prebuilt_report_tools():
    assert "first analysis tool call MUST be `write_file`" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "Compose the report artifacts from reusable helpers" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "prebuilt report generators" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "numeric_facts" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "source coverage" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "# HELPER SELECTION CATALOG" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "direct_ols_forecast(data, target_col, feature_cols" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "sahm_rule_signal(data, *, unemployment_col='UNRATE'" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "current_signal_facts" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "chart_provenance(source_series=..." in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "latest_numeric_fact(panel, key" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "raw_value" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "display_value" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "current/latest/window headline scalar" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "statistical_summary`" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "qualitative `assessment` prose" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "Correlation, growth-rate, spread, and normalized-index" in (
        QUANT_DEVELOPER_SYSTEM_PROMPT
    )
    assert "transform_descriptors" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "save_quant_outputs(output_dir, charts, execution_summary)" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert '"evidence_bundle_json": "outputs/{job_id}/evidence_bundle.json"' in (
        QUANT_DEVELOPER_SYSTEM_PROMPT
    )

    removed_surfaces = [
        "build_recession_dashboard_artifacts",
        "build_company_fundamental_artifacts",
        "build_macro_cycle_chart_pack_artifacts",
        "build_scenario_stress_test",
        "build_unemployment_forecast_contract",
        "build_company_facts_contract",
        "deterministic_artifact",
        "company_fundamental_contract",
        "signal_stack_contract",
        "forecast_contract",
        "unemployment_forecast_contract",
        "earnings_stress_rows",
        "forecast_baseline_verdicts",
        "baseline_verdicts",
        "false_alarm_backtest",
        "forecast_backtest_summary",
        "preserve_report_aligned_charts",
        "supplemental_validation_only",
        "merge_quant_validation_summary",
    ]
    for surface in removed_surfaces:
        assert surface not in QUANT_DEVELOPER_SYSTEM_PROMPT


def test_quant_subagent_registers_boundary_middleware_without_custom_report_tools():
    assert QUANT_DEVELOPER_SUBAGENT["tools"] == []
    assert any(
        isinstance(item, QuantDeveloperToolBoundaryMiddleware)
        for item in QUANT_DEVELOPER_SUBAGENT["middleware"]
    )


def test_quant_guardrail_blocks_helper_package_source_reads():
    helper_path = (
        Path(__file__).resolve().parents[1]
        / "agents"
        / "quant_macro_stats"
        / "forecasting.py"
    )
    script_path = (
        Path(quant_dev.OUTPUT_BASE_DIR) / "job-guardrail" / "code" / "analysis.py"
    )
    request = SimpleNamespace(
        tool_call={
            "name": "read_file",
            "id": "call-read",
            "args": {"file_path": str(helper_path)},
        },
        state={
            "messages": [
                ToolMessage(
                    content=f"Created file {script_path}",
                    name="write_file",
                    tool_call_id="call-write",
                )
            ]
        },
    )
    middleware = QuantDeveloperToolBoundaryMiddleware()

    response = middleware.wrap_tool_call(
        request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )

    assert response.status == "error"
    assert "Blocked helper-source inspection" in response.content
    assert "`agents/quant_macro_stats/**`" in response.content
    assert "direct_ols_forecast(data, target_col, feature_cols" in response.content
    assert "save_quant_outputs(output_dir, charts, execution_summary)" in response.content


def test_model_call_filters_to_initial_write_file_before_analysis_script():
    middleware = QuantDeveloperToolBoundaryMiddleware()
    request = _Request(
        [
            SimpleNamespace(name="write_file"),
            SimpleNamespace(name="read_file"),
            SimpleNamespace(name="execute"),
            SimpleNamespace(name="load_skill"),
        ],
        messages=[SystemMessage(content="job_id: job_123")],
    )
    seen_tools = []

    def handler(filtered_request):
        seen_tools.extend(tool.name for tool in filtered_request.tools)
        return ModelResponse(result=[AIMessage(content="")])

    middleware.wrap_model_call(request, handler)

    assert seen_tools == ["write_file", "read_file", "load_skill"]


def test_successful_execute_handoff_stops_future_tool_use():
    middleware = QuantDeveloperToolBoundaryMiddleware()
    handoff = (
        '{"charts_json":"outputs/job_123/charts.json",'
        '"execution_summary_json":"outputs/job_123/execution_summary.json",'
        '"evidence_bundle_json":"outputs/job_123/evidence_bundle.json",'
        '"chart_ids":["trend"]}'
    )
    request = _Request(
        [SimpleNamespace(name="write_file"), SimpleNamespace(name="execute")],
        messages=[ToolMessage(content=handoff, name="execute", tool_call_id="call_1")],
    )
    seen_tools = []

    def handler(filtered_request):
        seen_tools.extend(tool.name for tool in filtered_request.tools)
        return ModelResponse(result=[AIMessage(content="")])

    response = middleware.wrap_model_call(request, handler)

    assert seen_tools == []
    assert response.result[0].content == handoff


def test_model_call_forces_execute_after_written_script_without_tool_call(tmp_path):
    middleware = QuantDeveloperToolBoundaryMiddleware()
    script_path = tmp_path / "outputs" / "job-execute" / "code" / "analysis.py"
    request = _Request(
        [SimpleNamespace(name="execute"), SimpleNamespace(name="read_file")],
        messages=[
            ToolMessage(
                content=f"Updated file {script_path}",
                name="write_file",
                tool_call_id="call-write",
            )
        ],
    )

    response = middleware.wrap_model_call(
        request,
        lambda req: ModelResponse(
            result=[
                AIMessage(
                    content=(
                        "Failed to call tool due to error: Tool write_file failed. "
                        "This is a system error - please try sending this function again."
                    )
                )
            ]
        ),
    )

    tool_call = response.result[0].tool_calls[0]
    expected_command = (
        f"{shlex.quote(quant_dev.PYTHON_EXECUTABLE)} "
        f"{shlex.quote(str(script_path))}"
    )
    assert tool_call["name"] == "execute"
    assert tool_call["args"] == {"command": expected_command}


def test_model_call_does_not_repeat_execute_after_latest_write_failure(tmp_path):
    middleware = QuantDeveloperToolBoundaryMiddleware()
    script_path = tmp_path / "outputs" / "job-execute" / "code" / "analysis.py"
    request = _Request(
        [SimpleNamespace(name="execute"), SimpleNamespace(name="read_file")],
        messages=[
            ToolMessage(
                content=f"Updated file {script_path}",
                name="write_file",
                tool_call_id="call-write",
            ),
            ToolMessage(
                content="Command failed with traceback",
                name="execute",
                tool_call_id="call-execute",
                status="error",
            ),
        ],
    )

    response = middleware.wrap_model_call(
        request,
        lambda req: ModelResponse(result=[AIMessage(content="I need to inspect stderr.")]),
    )

    assert response.result[0].content == "I need to inspect stderr."
    assert response.result[0].tool_calls == []


def test_existing_analysis_script_redirects_to_first_unused_fallback(tmp_path):
    middleware = QuantDeveloperToolBoundaryMiddleware()
    code_dir = tmp_path / "outputs" / "job-fallback" / "code"
    code_dir.mkdir(parents=True)
    script_path = code_dir / "analysis.py"
    occupied_fallback_path = code_dir / "analysis_v2.py"
    replacement_path = code_dir / "analysis_v3.py"
    script_path.write_text("print('prior')\n", encoding="utf-8")
    occupied_fallback_path.write_text("print('prior fallback')\n", encoding="utf-8")
    request = SimpleNamespace(
        tool_call={
            "name": "write_file",
            "id": "call-write",
            "args": {"file_path": str(script_path), "content": "print('new')\n"},
        },
        state={"messages": []},
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )

    assert response.status == "error"
    assert f"already exists at `{script_path}`" in response.content
    assert f"replacement script to `{replacement_path}`" in response.content


def test_existing_fallback_script_redirects_to_next_unused_sibling(tmp_path):
    middleware = QuantDeveloperToolBoundaryMiddleware()
    code_dir = tmp_path / "outputs" / "job-fallback" / "code"
    code_dir.mkdir(parents=True)
    script_path = code_dir / "analysis.py"
    occupied_fallback_path = code_dir / "analysis_v2.py"
    replacement_path = code_dir / "analysis_v3.py"
    script_path.write_text("print('prior')\n", encoding="utf-8")
    occupied_fallback_path.write_text("print('prior fallback')\n", encoding="utf-8")
    request = SimpleNamespace(
        tool_call={
            "name": "write_file",
            "id": "call-write",
            "args": {
                "file_path": str(occupied_fallback_path),
                "content": "print('new')\n",
            },
        },
        state={"messages": []},
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )

    assert response.status == "error"
    assert f"already exists at `{occupied_fallback_path}`" in response.content
    assert f"replacement script to `{replacement_path}`" in response.content


def test_model_call_forces_execute_after_fallback_script_write(tmp_path):
    middleware = QuantDeveloperToolBoundaryMiddleware()
    script_path = tmp_path / "outputs" / "job-execute" / "code" / "analysis_v3.py"
    request = _Request(
        [SimpleNamespace(name="execute"), SimpleNamespace(name="read_file")],
        messages=[
            ToolMessage(
                content=f"Created file {script_path}",
                name="write_file",
                tool_call_id="call-write",
            )
        ],
    )

    response = middleware.wrap_model_call(
        request,
        lambda req: ModelResponse(result=[AIMessage(content="No more tools needed.")]),
    )

    tool_call = response.result[0].tool_calls[0]
    expected_command = f"{shlex.quote(quant_dev.PYTHON_EXECUTABLE)} {shlex.quote(str(script_path))}"
    assert tool_call["name"] == "execute"
    assert tool_call["args"] == {"command": expected_command}


def test_prewrite_failure_handoff_overwrites_prior_quant_artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr(quant_dev, "OUTPUT_BASE_DIR", str(tmp_path))
    output_dir = tmp_path / "job-stale"
    output_dir.mkdir()
    (output_dir / "charts.json").write_text(
        json.dumps({"stale_chart": {"id": "stale_chart"}}),
        encoding="utf-8",
    )
    (output_dir / "execution_summary.json").write_text(
        json.dumps({"status": "ok", "chart_ids": ["stale_chart"]}),
        encoding="utf-8",
    )
    (output_dir / "evidence_bundle.json").write_text(
        json.dumps({"bundle_type": "stale", "charts": [{"chart_id": "stale_chart"}]}),
        encoding="utf-8",
    )
    messages = [
        ToolMessage(
            content=f"Blocked invalid prewrite attempt {index}",
            name="write_file",
            tool_call_id=f"call-write-{index}",
            status="error",
        )
        for index in range(4)
    ]
    request = _Request(
        [SimpleNamespace(name="write_file")],
        messages=messages,
        runtime=SimpleNamespace(context=SimpleNamespace(job_id="job-stale")),
    )
    middleware = QuantDeveloperToolBoundaryMiddleware()

    response = middleware.wrap_model_call(
        request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )

    handoff = json.loads(response.result[0].content)
    saved_charts = json.loads((output_dir / "charts.json").read_text(encoding="utf-8"))
    saved_summary = json.loads(
        (output_dir / "execution_summary.json").read_text(encoding="utf-8")
    )
    saved_bundle = json.loads(
        (output_dir / "evidence_bundle.json").read_text(encoding="utf-8")
    )
    assert handoff["status"] == "failed"
    assert handoff["chart_ids"] == []
    assert handoff["evidence_bundle_json"] == str(output_dir / "evidence_bundle.json")
    assert "preserved_prior_artifacts" not in handoff
    assert saved_charts == []
    assert saved_summary["status"] == "failed"
    assert saved_summary["chart_ids"] == []
    assert saved_summary["evidence_bundle_json"] == str(
        output_dir / "evidence_bundle.json"
    )
    assert saved_bundle["bundle_type"] == "quant_evidence_bundle"
    assert saved_bundle["charts"] == []
    assert saved_bundle["validation"]["valid"] is False
    assert saved_bundle["validation"]["diagnostics"][0]["code"] == (
        "quant_prewrite_failure"
    )
    assert saved_bundle["artifacts"]["evidence_bundle_json"] == str(
        output_dir / "evidence_bundle.json"
    )
    assert "preserved_prior_artifacts" not in saved_summary


def _blocked_write_response(tmp_path, content):
    script_path = tmp_path / "outputs" / "job-guardrail" / "code" / "analysis.py"
    request = SimpleNamespace(
        tool_call={
            "name": "write_file",
            "id": "call-write",
            "args": {"file_path": str(script_path), "content": content},
        },
        state={"messages": []},
    )
    middleware = QuantDeveloperToolBoundaryMiddleware()

    return middleware.wrap_tool_call(
        request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )


def _allowed_write_response(tmp_path, content):
    script_path = tmp_path / "outputs" / "job-guardrail" / "code" / "analysis.py"
    request = SimpleNamespace(
        tool_call={
            "name": "write_file",
            "id": "call-write",
            "args": {"file_path": str(script_path), "content": content},
        },
        state={"messages": []},
    )
    middleware = QuantDeveloperToolBoundaryMiddleware()

    return middleware.wrap_tool_call(
        request,
        lambda req: ToolMessage(
            content="write allowed",
            name="write_file",
            tool_call_id="call-write",
            status="success",
        ),
    )


def test_quant_guardrail_blocks_derived_methods_without_transform_basis(tmp_path):
    content = '''
from agents.quant_macro_stats import chart_provenance, save_quant_outputs

output_dir = "/tmp/out"
charts = {
    "sentiment_gap": {
        "type": "line",
        "xAxisKey": "date",
        "data": [{"date": "2026 Q1", "gap": 0.2}],
        "series": [{"dataKey": "gap", "label": "Gap"}],
        "provenance": chart_provenance(source_series=["UMCSENT", "UNRATE"]),
    }
}
execution_summary = {
    "chart_ids": ["sentiment_gap"],
    "methods_used": ["pearson_correlation", "yoy_growth"],
}
handoff = save_quant_outputs(output_dir, charts, execution_summary)
'''

    response = _blocked_write_response(tmp_path, content)

    assert response.status == "error"
    assert "Blocked derived transform metadata" in response.content
    assert "`pearson_correlation`" in response.content
    assert "`yoy_growth`" in response.content
    assert "`transform_basis`" in response.content
    assert "transform_descriptors" in response.content


def test_quant_guardrail_blocks_z_score_normalization_without_basis(tmp_path):
    content = '''
from agents.quant_macro_stats import chart_provenance, save_quant_outputs

output_dir = "/tmp/out"
charts = {
    "normalized_overlay": {
        "type": "line",
        "xAxisKey": "date",
        "data": [{"date": "2026 Q1", "sentiment_z": 0.4}],
        "series": [{"dataKey": "sentiment_z", "label": "Sentiment z-score"}],
        "provenance": chart_provenance(source_series=["UMCSENT"]),
    }
}
execution_summary = {
    "chart_ids": ["normalized_overlay"],
    "methods_used": ["z_score_normalization"],
}
handoff = save_quant_outputs(output_dir, charts, execution_summary)
'''

    response = _blocked_write_response(tmp_path, content)

    assert response.status == "error"
    assert "Blocked derived transform metadata" in response.content
    assert "`z_score_normalization`" in response.content
    assert "`normalized_overlay`" in response.content
    assert "`transform_basis`" in response.content


def test_quant_guardrail_allows_declared_transform_basis_for_methods(tmp_path):
    content = '''
from agents.quant_macro_stats import chart_provenance, save_quant_outputs

output_dir = "/tmp/out"
charts = {
    "sentiment_gap": {
        "type": "line",
        "xAxisKey": "date",
        "data": [{"date": "2026 Q1", "gap": 0.2}],
        "series": [{"dataKey": "gap", "label": "Gap"}],
        "provenance": chart_provenance(source_series=["UMCSENT", "UNRATE"]),
    }
}
execution_summary = {
    "chart_ids": ["sentiment_gap"],
    "methods_used": ["pearson_correlation"],
    "transforms": [
        {
            "transform_id": "pearson_correlation",
            "operation": "correlation",
            "transform_basis": "Pearson r on quarterly UMCSENT and UNRATE levels",
            "source_ids": ["UMCSENT", "UNRATE"],
        }
    ],
}
handoff = save_quant_outputs(output_dir, charts, execution_summary)
'''

    response = _allowed_write_response(tmp_path, content)

    assert response.status == "success"
    assert response.content == "write allowed"


def test_quant_guardrail_blocks_attach_methods_used_without_transform_basis(tmp_path):
    content = '''
from agents.quant_macro_stats import attach_methods_used, chart_provenance, save_quant_outputs

output_dir = "/tmp/out"
base_charts = {
    "sentiment_gap": {
        "type": "line",
        "xAxisKey": "date",
        "data": [{"date": "2026 Q1", "gap": 0.2}],
        "series": [{"dataKey": "gap", "label": "Gap"}],
        "provenance": chart_provenance(source_series=["UMCSENT", "UNRATE"]),
    }
}
methods = ["pearson_correlation"]
charts = attach_methods_used(base_charts, methods)
execution_summary = {"chart_ids": ["sentiment_gap"]}
handoff = save_quant_outputs(output_dir, charts, execution_summary)
'''

    response = _blocked_write_response(tmp_path, content)

    assert response.status == "error"
    assert "Blocked derived transform metadata" in response.content
    assert "`pearson_correlation`" in response.content


def test_quant_guardrail_blocks_sec_company_facts_without_helper_evidence(tmp_path):
    sec_path = tmp_path / "NVDA_sec_edgar_company_facts.csv"
    sec_path.write_text("fiscal_year,revenue\n2025,130000\n", encoding="utf-8")
    content = f'''
from agents.quant_macro_stats import save_quant_outputs

DATA_FILES = {{"sec_facts": {str(sec_path)!r}}}
charts = {{}}
execution_summary = {{"data_files_used": ["sec_facts"]}}
handoff = save_quant_outputs(output_dir, charts, execution_summary)
'''

    response = _blocked_write_response(tmp_path, content)

    assert response.status == "error"
    assert "does not call `sec_company_facts_evidence(...)`" in response.content
    assert "`numeric_facts`" in response.content
    assert "summary passed to `save_quant_outputs`" in response.content


def test_quant_guardrail_blocks_sec_helper_not_merged_into_summary(tmp_path):
    sec_path = tmp_path / "NVDA_sec_edgar_company_facts.csv"
    sec_path.write_text("fiscal_year,revenue\n2025,130000\n", encoding="utf-8")
    content = f'''
from agents.quant_macro_stats import sec_company_facts_evidence, save_quant_outputs

DATA_FILES = {{"sec_facts": {str(sec_path)!r}}}
company_evidence = sec_company_facts_evidence(DATA_FILES, query="NVDA fundamentals")
charts = {{}}
execution_summary = {{"methods_used": ["sec_company_facts_evidence"]}}
handoff = save_quant_outputs(output_dir, charts, execution_summary)
'''

    response = _blocked_write_response(tmp_path, content)

    assert response.status == "error"
    assert "`sec_company_facts_evidence(...)` is not merged" in response.content
    assert "`latest_fundamentals`" in response.content
    assert "`source_coverage`" in response.content


def test_quant_guardrail_ignores_uncalled_sec_evidence_handoff_function(tmp_path):
    sec_path = tmp_path / "NVDA_sec_edgar_company_facts.csv"
    sec_path.write_text("fiscal_year,revenue\n2025,130000\n", encoding="utf-8")
    content = f'''
from agents.quant_macro_stats import sec_company_facts_evidence, save_quant_outputs

DATA_FILES = {{"sec_facts": {str(sec_path)!r}}}
charts = {{}}

def unused_sec_handoff():
    company_evidence = sec_company_facts_evidence(DATA_FILES, query="NVDA fundamentals")
    execution_summary = {{"methods_used": ["sec_company_facts_evidence"]}}
    execution_summary.update(company_evidence)
    return save_quant_outputs(output_dir, charts, execution_summary)

execution_summary = {{"methods_used": ["manual summary"]}}
handoff = save_quant_outputs(output_dir, charts, execution_summary)
'''

    response = _blocked_write_response(tmp_path, content)

    assert response.status == "error"
    assert "`sec_company_facts_evidence(...)` is not merged" in response.content


def test_quant_guardrail_blocks_sec_helper_merged_after_save(tmp_path):
    sec_path = tmp_path / "NVDA_sec_edgar_company_facts.csv"
    sec_path.write_text("fiscal_year,revenue\n2025,130000\n", encoding="utf-8")
    content = f'''
from agents.quant_macro_stats import sec_company_facts_evidence, save_quant_outputs

DATA_FILES = {{"sec_facts": {str(sec_path)!r}}}
company_evidence = sec_company_facts_evidence(DATA_FILES, query="NVDA fundamentals")
charts = {{}}
execution_summary = {{"custom_stress_rows": []}}
handoff = save_quant_outputs(output_dir, charts, execution_summary)
execution_summary.update(company_evidence)
'''

    response = _blocked_write_response(tmp_path, content)

    assert response.status == "error"
    assert "`sec_company_facts_evidence(...)` is not merged" in response.content


def test_quant_guardrail_blocks_sec_helper_overwritten_after_merge(tmp_path):
    sec_path = tmp_path / "NVDA_sec_edgar_company_facts.csv"
    sec_path.write_text("fiscal_year,revenue\n2025,130000\n", encoding="utf-8")
    content = f'''
from agents.quant_macro_stats import sec_company_facts_evidence, save_quant_outputs

DATA_FILES = {{"sec_facts": {str(sec_path)!r}}}
company_evidence = sec_company_facts_evidence(DATA_FILES, query="NVDA fundamentals")
charts = {{}}
execution_summary = {{"custom_stress_rows": []}}
execution_summary.update(company_evidence)
execution_summary = {{"methods_used": ["manual override"]}}
handoff = save_quant_outputs(output_dir, charts, execution_summary)
'''

    response = _blocked_write_response(tmp_path, content)

    assert response.status == "error"
    assert "`sec_company_facts_evidence(...)` is not merged" in response.content


def test_quant_guardrail_allows_sec_helper_evidence_with_custom_rows(tmp_path):
    sec_path = tmp_path / "NVDA_sec_edgar_company_facts.csv"
    sec_path.write_text("fiscal_year,revenue\n2025,130000\n", encoding="utf-8")
    content = f'''
from agents.quant_macro_stats import sec_company_facts_evidence, save_quant_outputs

DATA_FILES = {{"sec_facts": {str(sec_path)!r}}}
company_evidence = sec_company_facts_evidence(DATA_FILES, query="NVDA fundamentals")
charts = {{}}
stress_rows = [{{"scenario": "ai_spending_cools", "revenue_change_pct": -30}}]
execution_summary = {{"custom_stress_rows": stress_rows}}
execution_summary.update(company_evidence)
handoff = save_quant_outputs(output_dir, charts, execution_summary)
'''

    response = _allowed_write_response(tmp_path, content)

    assert response.content == "write allowed"


def test_macro_guardrail_does_not_route_forecast_false_alarm_from_query_text(tmp_path):
    usrec_path = tmp_path / "usrec.csv"
    usrec_path.write_text("date,USREC\n2020-01-01,0\n", encoding="utf-8")
    content = f'''
DATA_FILES = {{"USREC": {str(usrec_path)!r}}}
original_query = "Review the unemployment forecast and false_alarm history."
execution_summary = {{"notes": original_query}}
'''

    response = _blocked_write_response(tmp_path, content)

    assert response.status == "error"
    assert "signal framework hit/miss evidence requires `signal_framework_backtest`" in response.content
    assert "already composes reusable forecast evidence rows" not in response.content
    assert "For a forecast with false-alarm or prior-miss analysis" not in response.content


def test_macro_guardrail_adds_forecast_recovery_from_script_evidence(tmp_path):
    usrec_path = tmp_path / "usrec.csv"
    unrate_path = tmp_path / "unrate.csv"
    usrec_path.write_text("date,USREC\n2020-01-01,0\n", encoding="utf-8")
    unrate_path.write_text("date,UNRATE\n2020-01-01,4.0\n", encoding="utf-8")
    content = f'''
from agents.quant_macro_stats import direct_ols_forecast

DATA_FILES = {{"USREC": {str(usrec_path)!r}, "UNRATE": {str(unrate_path)!r}}}
forecast = direct_ols_forecast(panel, target_col="UNRATE", feature_cols=[], date_col="date")
false_alarm_rows = []
execution_summary = {{"forecast_table": [], "signal_false_positive_windows": false_alarm_rows}}
'''

    response = _blocked_write_response(tmp_path, content)

    assert response.status == "error"
    assert "signal framework hit/miss evidence requires `signal_framework_backtest`" in response.content
    assert "already composes reusable forecast evidence rows" in response.content


def test_period_alignment_guardrail_blocks_claims_and_jolts_without_helper(tmp_path):
    claims_path = tmp_path / "icsa.csv"
    jolts_path = tmp_path / "jtsjol.csv"
    claims_path.write_text("date,value\n2026-05-09,240000\n", encoding="utf-8")
    jolts_path.write_text("date,value\n2026-03-01,6900\n", encoding="utf-8")
    content = f'''
DATA_FILES = {{"ICSA": {str(claims_path)!r}, "JTSJOL": {str(jolts_path)!r}}}
panel = {{}}
'''

    response = _blocked_write_response(tmp_path, content)

    assert response.status == "error"
    assert "Blocked mixed-frequency FRED analysis script" in response.content
    assert 'fill_scope="lower_frequency"' in response.content
    assert "monthly/JOLTS tails missing" in response.content


def test_period_alignment_guardrail_blocks_treasury_and_jolts_without_helper(tmp_path):
    t5yie_path = tmp_path / "t5yie.csv"
    jolts_path = tmp_path / "jtsjol.csv"
    t5yie_path.write_text("date,value\n2026-05-15,2.35\n", encoding="utf-8")
    jolts_path.write_text("date,value\n2026-03-01,6900\n", encoding="utf-8")
    content = f'''
DATA_FILES = {{"T5YIE": {str(t5yie_path)!r}, "JTSJOL": {str(jolts_path)!r}}}
panel = {{}}
'''

    response = _blocked_write_response(tmp_path, content)

    assert response.status == "error"
    assert "Blocked mixed-frequency FRED analysis script" in response.content
    assert 'fill_scope="lower_frequency"' in response.content
    assert "monthly/JOLTS tails missing" in response.content


def test_macro_guardrail_blocks_removed_output_preservation_surfaces(tmp_path):
    content = '''
from agents.quant_macro_stats import merge_quant_validation_summary, save_quant_outputs

execution_summary = {
    "preserve_report_aligned_charts": True,
    "supplemental_validation_only": True,
}
handoff = save_quant_outputs(output_dir, charts, execution_summary)
'''

    response = _blocked_write_response(tmp_path, content)

    assert response.status == "error"
    assert "stale quant-output preservation surface" in response.content
    assert "`merge_quant_validation_summary`" in response.content
    assert "`preserve_report_aligned_charts`" in response.content
    assert "`supplemental_validation_only`" in response.content

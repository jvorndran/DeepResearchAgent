from types import SimpleNamespace

from langchain.agents.middleware.types import ModelResponse
from langchain_core.messages import AIMessage

from agents.orchestrator import (
    OrchestratorToolBoundaryMiddleware,
    StripToolCallContentMiddleware,
)


class _Request:
    def __init__(self, tools):
        self.tools = tools

    def override(self, **kwargs):
        return _Request(kwargs.get("tools", self.tools))


def test_orchestrator_tool_boundary_exposes_only_status_and_task_tools():
    middleware = OrchestratorToolBoundaryMiddleware()
    request = _Request(
        [
            SimpleNamespace(name="emit_chat_message"),
            SimpleNamespace(name="task"),
            SimpleNamespace(name="read_file"),
            SimpleNamespace(name="glob"),
            SimpleNamespace(name="execute"),
            SimpleNamespace(name="write_todos"),
        ]
    )

    response = middleware.wrap_model_call(request, lambda req: req)

    assert [tool.name for tool in response.tools] == ["emit_chat_message", "task"]


def test_orchestrator_tool_boundary_blocks_general_purpose_pipeline_tasks():
    middleware = OrchestratorToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={
            "name": "task",
            "id": "call-1",
            "args": {
                "subagent_type": "general-purpose",
                "description": "Read execution_summary.json after QA rejection.",
            },
        }
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )

    assert response.tool_call_id == "call-1"
    assert response.status == "error"
    assert "Blocked task delegation to `general-purpose`" in response.content
    assert "Do not use general-purpose to inspect artifacts" in response.content


def test_orchestrator_tool_boundary_blocks_approval_emit_after_quality_rejection():
    middleware = OrchestratorToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={
            "name": "emit_chat_message",
            "id": "call-bad-approval",
            "args": {"markdown": "Report approved: outputs/improver-123/report.json"},
        },
        state={
            "messages": [
                AIMessage(
                    content=(
                        '{"status":"rejected",'
                        '"report_path":"/tmp/outputs/improver-123/report.json",'
                        '"reason":"Required quantitative artifacts are missing.",'
                        '"required_fixes":["Rerun quant-developer."]}'
                    )
                )
            ]
        },
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )

    assert response.tool_call_id == "call-bad-approval"
    assert response.status == "error"
    assert "latest structured quality-analyst decision is rejected" in response.content
    assert "Do not tell the user the report is approved" in response.content


def test_orchestrator_tool_boundary_allows_approval_emit_after_quality_approval():
    middleware = OrchestratorToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={
            "name": "emit_chat_message",
            "id": "call-good-approval",
            "args": {"markdown": "Report approved: outputs/improver-123/report.json"},
        },
        state={
            "messages": [
                AIMessage(
                    content=(
                        '{"status":"approved",'
                        '"report_path":"/tmp/outputs/improver-123/report.json"}'
                    )
                )
            ]
        },
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: SimpleNamespace(content="Message recorded for the chat UI."),
    )

    assert response.content == "Message recorded for the chat UI."


def test_orchestrator_tool_boundary_allows_specialist_pipeline_tasks():
    middleware = OrchestratorToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={
            "name": "task",
            "id": "call-2",
            "args": {
                "subagent_type": "technical-writer",
                "description": "Revise report using QA required_fixes.",
            },
        }
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: SimpleNamespace(content="delegated", status="success"),
    )

    assert response.content == "delegated"


def test_orchestrator_tool_boundary_blocks_filesystem_tool_calls():
    middleware = OrchestratorToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={
            "name": "execute",
            "id": "call-execute",
            "args": {"command": "python outputs/job/code/analysis.py"},
        }
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )

    assert response.tool_call_id == "call-execute"
    assert response.status == "error"
    assert "Blocked orchestrator tool `execute`" in response.content
    assert "may only call `emit_chat_message` and `task`" in response.content


def test_orchestrator_tool_boundary_blocks_repeat_quant_after_guardrail_failure():
    middleware = OrchestratorToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={
            "name": "task",
            "id": "call-repeat-quant",
            "args": {
                "subagent_type": "quant-developer",
                "description": "Try the same quantitative analysis again.",
            },
        },
        state={
            "messages": [
                AIMessage(
                    content=(
                        '{"status":"failed",'
                        '"execution_summary_json":"/tmp/outputs/job/execution_summary.json",'
                        '"charts_json":"/tmp/outputs/job/charts.json",'
                        '"error":"quant-developer exceeded the pre-write guardrail retry budget"}'
                    )
                )
            ]
        },
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )

    assert response.tool_call_id == "call-repeat-quant"
    assert response.status == "error"
    assert "Blocked repeat quant-developer delegation" in response.content
    assert "Proceed to technical-writer" in response.content
    assert "QA-driven quant-developer recovery" in response.content


def test_orchestrator_tool_boundary_allows_qa_requested_quant_fix_after_failed_handoff():
    middleware = OrchestratorToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={
            "name": "task",
            "id": "call-qa-failed-quant-fix",
            "args": {
                "subagent_type": "quant-developer",
                "description": (
                    "QA rejected the report because computed artifacts are missing. "
                    "Apply required_fixes with a compact helper-driven script."
                ),
            },
        },
        state={
            "messages": [
                AIMessage(
                    content=(
                        '{"status":"failed",'
                        '"execution_summary_json":"/tmp/outputs/job/execution_summary.json",'
                        '"charts_json":"/tmp/outputs/job/charts.json",'
                        '"error":"quant-developer exceeded the pre-write guardrail retry budget"}'
                    )
                )
            ]
        },
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: SimpleNamespace(content="delegated", status="success"),
    )

    assert response.content == "delegated"


def test_orchestrator_tool_boundary_blocks_repeat_quant_after_successful_handoff(tmp_path):
    middleware = OrchestratorToolBoundaryMiddleware()
    summary_path = tmp_path / "execution_summary.json"
    charts_path = tmp_path / "charts.json"
    summary_path.write_text("{}", encoding="utf-8")
    charts_path.write_text('{"charts":[]}', encoding="utf-8")
    request = SimpleNamespace(
        tool_call={
            "name": "task",
            "id": "call-repeat-success",
            "args": {
                "subagent_type": "quant-developer",
                "description": "Verify the existing charts.json and execution_summary.json.",
            },
        },
        state={
            "messages": [
                AIMessage(
                    content=(
                        f'{{"execution_summary_json":"{summary_path}",'
                        f'"charts_json":"{charts_path}",'
                        '"chart_ids":["recession_risk","labor_market"]}'
                    )
                )
            ]
        },
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )

    assert response.tool_call_id == "call-repeat-success"
    assert response.status == "error"
    assert "Blocked repeat quant-developer delegation" in response.content
    assert "A prior quant-developer task already returned a usable artifact handoff" in response.content
    assert "Proceed to technical-writer" in response.content


def test_orchestrator_tool_boundary_allows_quant_when_handoff_paths_are_missing():
    middleware = OrchestratorToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={
            "name": "task",
            "id": "call-missing-handoff-paths",
            "args": {
                "subagent_type": "quant-developer",
                "description": "Regenerate the missing quantitative artifacts.",
            },
        },
        state={
            "messages": [
                AIMessage(
                    content=(
                        '{"execution_summary_json":"/tmp/does-not-exist/job/execution_summary.json",'
                        '"charts_json":"/tmp/does-not-exist/job/charts.json",'
                        '"chart_ids":["recession_risk","labor_market"]}'
                    )
                )
            ]
        },
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: SimpleNamespace(content="delegated", status="success"),
    )

    assert response.content == "delegated"


def test_orchestrator_tool_boundary_does_not_treat_empty_chart_ids_as_success():
    middleware = OrchestratorToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={
            "name": "task",
            "id": "call-empty-charts",
            "args": {
                "subagent_type": "quant-developer",
                "description": "Regenerate analysis and charts properly.",
            },
        },
        state={
            "messages": [
                AIMessage(
                    content=(
                        '{"execution_summary_json":"/tmp/outputs/job/execution_summary.json",'
                        '"charts_json":"/tmp/outputs/job/charts.json",'
                        '"chart_ids":[]}'
                    )
                )
            ]
        },
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: SimpleNamespace(content="delegated", status="success"),
    )

    assert response.content == "delegated"


def test_orchestrator_tool_boundary_does_not_treat_prompt_field_names_as_success():
    middleware = OrchestratorToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={
            "name": "task",
            "id": "call-prompt-field-names",
            "args": {
                "subagent_type": "quant-developer",
                "description": "Regenerate the missing quantitative artifacts.",
            },
        },
        state={
            "messages": [
                AIMessage(
                    content=(
                        "If quant-developer returns execution_summary_json, charts_json, "
                        "and chart_ids, pass those paths to technical-writer."
                    )
                )
            ]
        },
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: SimpleNamespace(content="delegated", status="success"),
    )

    assert response.content == "delegated"


def test_orchestrator_tool_boundary_does_not_treat_missing_json_paths_as_success():
    middleware = OrchestratorToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={
            "name": "task",
            "id": "call-missing-json-paths",
            "args": {
                "subagent_type": "quant-developer",
                "description": "Regenerate analysis after QA rejected missing quant artifacts.",
            },
        },
        state={
            "messages": [
                AIMessage(
                    content=(
                        'The original quant-developer returned "status":"success" '
                        'with a charts_json path, execution_summary_json path, '
                        'and chart_ids ["recession_composite_index"].'
                    )
                )
            ]
        },
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: SimpleNamespace(content="delegated", status="success"),
    )

    assert response.content == "delegated"


def test_orchestrator_tool_boundary_allows_qa_requested_quant_fix_after_handoff(tmp_path):
    middleware = OrchestratorToolBoundaryMiddleware()
    summary_path = tmp_path / "execution_summary.json"
    charts_path = tmp_path / "charts.json"
    summary_path.write_text("{}", encoding="utf-8")
    charts_path.write_text('{"charts":[]}', encoding="utf-8")
    request = SimpleNamespace(
        tool_call={
            "name": "task",
            "id": "call-qa-quant-fix",
            "args": {
                "subagent_type": "quant-developer",
                "description": "QA rejected the report. Apply required_fixes for stale charts.",
            },
        },
        state={
            "messages": [
                AIMessage(
                    content=(
                        f'{{"execution_summary_json":"{summary_path}",'
                        f'"charts_json":"{charts_path}",'
                        '"chart_ids":["recession_risk"]}'
                    )
                )
            ]
        },
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: SimpleNamespace(content="delegated", status="success"),
    )

    assert response.content == "delegated"


def test_orchestrator_tool_boundary_allows_qa_quant_fix_for_missing_summary_enrichment(tmp_path):
    middleware = OrchestratorToolBoundaryMiddleware()
    summary_path = tmp_path / "execution_summary.json"
    charts_path = tmp_path / "charts.json"
    summary_path.write_text("{}", encoding="utf-8")
    charts_path.write_text('{"charts":[]}', encoding="utf-8")
    request = SimpleNamespace(
        tool_call={
            "name": "task",
            "id": "call-qa-summary-enrichment",
            "args": {
                "subagent_type": "quant-developer",
                "description": (
                    "QA rejection: execution_summary.json lacks structured "
                    "backtest_summary, model_comparison, and historical_simulations "
                    "enrichment keys required for this forecast/backtest report."
                ),
            },
        },
        state={
            "messages": [
                AIMessage(
                    content=(
                        f'{{"execution_summary_json":"{summary_path}",'
                        f'"charts_json":"{charts_path}",'
                        '"chart_ids":["composite_signal_history","unemployment_forecast"]}'
                    )
                )
            ]
        },
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: SimpleNamespace(content="delegated", status="success"),
    )

    assert response.content == "delegated"


def test_orchestrator_tool_boundary_allows_qa_quant_fix_for_non_finite_chart_data(tmp_path):
    middleware = OrchestratorToolBoundaryMiddleware()
    summary_path = tmp_path / "execution_summary.json"
    charts_path = tmp_path / "charts.json"
    summary_path.write_text("{}", encoding="utf-8")
    charts_path.write_text('{"charts":[]}', encoding="utf-8")
    request = SimpleNamespace(
        tool_call={
            "name": "task",
            "id": "call-qa-chart-render",
            "args": {
                "subagent_type": "quant-developer",
                "description": (
                    "QA rejected the report because charts.json still has non-finite "
                    "values: unemployment_forecast and cycle_comparison have no "
                    "finite numeric values in their series data."
                ),
            },
        },
        state={
            "messages": [
                AIMessage(
                    content=(
                        f'{{"execution_summary_json":"{summary_path}",'
                        f'"charts_json":"{charts_path}",'
                        '"chart_ids":["unemployment_forecast","cycle_comparison"]}'
                    )
                )
            ]
        },
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: SimpleNamespace(content="delegated", status="success"),
    )

    assert response.content == "delegated"


def test_orchestrator_tool_boundary_blocks_non_qa_chart_count_retry_after_handoff(tmp_path):
    middleware = OrchestratorToolBoundaryMiddleware()
    summary_path = tmp_path / "execution_summary.json"
    charts_path = tmp_path / "charts.json"
    summary_path.write_text("{}", encoding="utf-8")
    charts_path.write_text('{"charts":[]}', encoding="utf-8")
    request = SimpleNamespace(
        tool_call={
            "name": "task",
            "id": "call-chart-count-retry",
            "args": {
                "subagent_type": "quant-developer",
                "description": (
                    "The quant-developer only produced 4 chart IDs but we need 12. "
                    "Complete the missing charts and enrich the execution summary."
                ),
            },
        },
        state={
            "messages": [
                AIMessage(
                    content=(
                        f'{{"execution_summary_json":"{summary_path}",'
                        f'"charts_json":"{charts_path}",'
                        '"chart_ids":["risk-index","labor-dashboard",'
                        '"unemployment-forecast","inflation-crosscheck"]}'
                    )
                )
            ]
        },
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )

    assert response.tool_call_id == "call-chart-count-retry"
    assert response.status == "error"
    assert "usable artifact handoff" in response.content
    assert "Proceed to technical-writer" in response.content


def test_orchestrator_tool_boundary_blocks_qa_report_fidelity_retry_to_quant(tmp_path):
    middleware = OrchestratorToolBoundaryMiddleware()
    summary_path = tmp_path / "execution_summary.json"
    charts_path = tmp_path / "charts.json"
    summary_path.write_text("{}", encoding="utf-8")
    charts_path.write_text('{"charts":[]}', encoding="utf-8")
    request = SimpleNamespace(
        tool_call={
            "name": "task",
            "id": "call-qa-report-fidelity",
            "args": {
                "subagent_type": "quant-developer",
                "description": (
                    "QA rejected the report. Apply required_fixes for numerical "
                    "discrepancies between report prose and execution_summary, "
                    "including recession-risk wording and unemployment values."
                ),
            },
        },
        state={
            "messages": [
                AIMessage(
                    content=(
                        f'{{"execution_summary_json":"{summary_path}",'
                        f'"charts_json":"{charts_path}",'
                        '"chart_ids":["recession_risk","yield_curve","inflation"]}'
                    )
                )
            ]
        },
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )

    assert response.tool_call_id == "call-qa-report-fidelity"
    assert response.status == "error"
    assert "Blocked repeat quant-developer delegation" in response.content
    assert "usable artifact handoff" in response.content
    assert "Proceed to technical-writer" in response.content


def test_orchestrator_tool_boundary_blocks_report_summary_contradiction_recompute_to_quant(tmp_path):
    middleware = OrchestratorToolBoundaryMiddleware()
    summary_path = tmp_path / "execution_summary.json"
    charts_path = tmp_path / "charts.json"
    summary_path.write_text("{}", encoding="utf-8")
    charts_path.write_text('{"charts":[]}', encoding="utf-8")
    request = SimpleNamespace(
        tool_call={
            "name": "task",
            "id": "call-qa-summary-contradiction",
            "args": {
                "subagent_type": "quant-developer",
                "description": (
                    "QA rejected the report because the report's composite recession-risk "
                    "score fundamentally disagrees with the execution_summary. The report "
                    "writer used its own recalculated values, so re-delegate to quant-developer "
                    "to recompute everything cleanly and consistently."
                ),
            },
        },
        state={
            "messages": [
                AIMessage(
                    content=(
                        f'{{"execution_summary_json":"{summary_path}",'
                        f'"charts_json":"{charts_path}",'
                        '"chart_ids":["macro_dashboard","recession_probability"]}'
                    )
                )
            ]
        },
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )

    assert response.tool_call_id == "call-qa-summary-contradiction"
    assert response.status == "error"
    assert "Blocked repeat quant-developer delegation" in response.content
    assert "technical-writer" in response.content
    assert "report-vs-execution_summary contradiction" in response.content


def test_orchestrator_tool_boundary_allows_qa_worded_quant_artifact_fix(tmp_path):
    middleware = OrchestratorToolBoundaryMiddleware()
    summary_path = tmp_path / "execution_summary.json"
    charts_path = tmp_path / "charts.json"
    summary_path.write_text("{}", encoding="utf-8")
    charts_path.write_text('{"charts":[]}', encoding="utf-8")
    request = SimpleNamespace(
        tool_call={
            "name": "task",
            "id": "call-qa-artifact-fix",
            "args": {
                "subagent_type": "quant-developer",
                "description": (
                    "QA says execution_summary.json lacks backtest_summary and "
                    "historical_simulations. Required fixes: add structured replay "
                    "rows and preserve the computed false-positive metrics."
                ),
            },
        },
        state={
            "messages": [
                AIMessage(
                    content=(
                        f'{{"execution_summary_json":"{summary_path}",'
                        f'"charts_json":"{charts_path}",'
                        '"chart_ids":["signal_stack"]}'
                    )
                )
            ]
        },
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: SimpleNamespace(
            content="delegated", tool_call_id=req.tool_call["id"], status="success"
        ),
    )

    assert response.tool_call_id == "call-qa-artifact-fix"
    assert response.status == "success"


def test_strip_tool_call_content_middleware_preserves_tool_calls():
    middleware = StripToolCallContentMiddleware()
    tool_message = AIMessage(
        content="Let me call a tool.",
        tool_calls=[{"name": "task", "args": {"subagent_type": "data-engineer"}, "id": "1"}],
    )
    final_message = AIMessage(content="Final response.")

    response = middleware.wrap_model_call(
        request=None,
        handler=lambda _: ModelResponse(result=[tool_message, final_message]),
    )

    assert response.result[0].content == ""
    assert response.result[0].tool_calls == tool_message.tool_calls
    assert response.result[1].content == "Final response."


def test_strip_tool_call_content_middleware_suppresses_post_approval_prose():
    middleware = StripToolCallContentMiddleware()
    terminal_tool_message = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "emit_chat_message",
                "args": {"markdown": "Report approved: outputs/improver-123/report.json"},
                "id": "1",
            }
        ],
    )
    request = SimpleNamespace(messages=[terminal_tool_message])
    final_message = AIMessage(content="The research pipeline is complete.")

    response = middleware.wrap_model_call(
        request=request,
        handler=lambda _: ModelResponse(result=[final_message]),
    )

    assert response.result[0].content == ""


def test_strip_tool_call_content_middleware_short_circuits_after_terminal_emit():
    middleware = StripToolCallContentMiddleware()
    terminal_tool_message = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "emit_chat_message",
                "args": {"markdown": "Report approved: outputs/improver-123/report.json"},
                "id": "1",
            }
        ],
    )
    request = SimpleNamespace(messages=[terminal_tool_message])
    handler_called = False

    def handler(_):
        nonlocal handler_called
        handler_called = True
        return ModelResponse(result=[AIMessage(content="The research pipeline is complete.")])

    response = middleware.wrap_model_call(request=request, handler=handler)

    assert handler_called is False
    assert response.result[0].content == ""


def test_strip_tool_call_content_middleware_detects_provider_tool_call_shape():
    middleware = StripToolCallContentMiddleware()
    terminal_tool_message = AIMessage(
        content="",
        additional_kwargs={
            "tool_calls": [
                {
                    "function": {
                        "name": "emit_chat_message",
                        "arguments": '{"markdown":"Report approved: outputs/improver-123/report.json"}',
                    }
                }
            ]
        },
    )
    request = SimpleNamespace(messages=[terminal_tool_message])
    final_message = AIMessage(content="Key findings: ...")

    response = middleware.wrap_model_call(
        request=request,
        handler=lambda _: ModelResponse(result=[final_message]),
    )

    assert response.result[0].content == ""


def test_strip_tool_call_content_middleware_suppresses_after_quality_approval_result():
    middleware = StripToolCallContentMiddleware()
    quality_task_result = AIMessage(content="Approved.")
    request = SimpleNamespace(messages=[quality_task_result])
    terminal_message = AIMessage(
        content="The pipeline is complete.",
        tool_calls=[
            {
                "name": "emit_chat_message",
                "args": {"markdown": "Report approved: outputs/improver-123/report.json"},
                "id": "1",
            }
        ],
    )

    response = middleware.wrap_model_call(
        request=request,
        handler=lambda _: ModelResponse(result=[terminal_message]),
    )

    assert response.result[0].content == ""
    assert response.result[0].tool_calls == terminal_message.tool_calls


def test_strip_tool_call_content_middleware_suppresses_after_structured_quality_approval():
    middleware = StripToolCallContentMiddleware()
    quality_tool_result = AIMessage(
        content=(
            '{"status":"approved",'
            '"report_path":"/home/vorndranj/projects/DeepResearchAgent/backend/outputs/improver-123/report.json"}'
        )
    )
    request = SimpleNamespace(messages=[quality_tool_result])
    final_message = AIMessage(content="The final report is saved.")

    response = middleware.wrap_model_call(
        request=request,
        handler=lambda _: ModelResponse(result=[final_message]),
    )

    assert response.result[0].content == ""
    assert response.result[0].tool_calls[0]["name"] == "emit_chat_message"
    assert response.result[0].tool_calls[0]["args"] == {
        "markdown": "Report approved: outputs/improver-123/report.json"
    }
    assert response.result[0].tool_calls[0]["id"] == "terminal-approval-emit"


def test_strip_tool_call_content_middleware_replaces_post_approval_task_with_terminal_emit():
    middleware = StripToolCallContentMiddleware()
    quality_tool_result = AIMessage(
        content=(
            '{"status":"approved",'
            '"report_path":"/home/vorndranj/projects/DeepResearchAgent/backend/outputs/improver-456/report.json"}'
        )
    )
    request = SimpleNamespace(messages=[quality_tool_result])
    bad_followup = AIMessage(
        content="QA flagged another issue, so I will re-run quant.",
        tool_calls=[
            {
                "name": "task",
                "args": {
                    "subagent_type": "quant-developer",
                    "description": "Speculative post-approval repair.",
                },
                "id": "bad-post-approval-task",
            }
        ],
    )

    response = middleware.wrap_model_call(
        request=request,
        handler=lambda _: ModelResponse(result=[bad_followup]),
    )

    assert response.result[0].content == ""
    assert response.result[0].tool_calls[0]["name"] == "emit_chat_message"
    assert response.result[0].tool_calls[0]["args"] == {
        "markdown": "Report approved: outputs/improver-456/report.json"
    }
    assert response.result[0].tool_calls[0]["id"] == "terminal-approval-emit"

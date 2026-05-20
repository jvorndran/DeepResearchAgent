import json
from types import SimpleNamespace

from langchain.agents.middleware.types import ModelResponse
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.types import Command

import agents.quantitative_developer as quant_dev
from agents.orchestrator import (
    OrchestratorToolBoundaryMiddleware,
    StripToolCallContentMiddleware,
)


class _Request:
    def __init__(self, tools):
        self.tools = tools

    def override(self, **kwargs):
        return _Request(kwargs.get("tools", self.tools))


def _write_valid_evidence_bundle(evidence_bundle_path, chart_ids):
    table_ids = [f"chart_data:{chart_id}" for chart_id in chart_ids]
    evidence_bundle_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "bundle_type": "quant_evidence_bundle",
                "charts": [
                    {
                        "chart_id": chart_id,
                        "source_table_ids": [table_id],
                        "transform_ids": [f"unit_test_projection:{chart_id}"],
                    }
                    for chart_id, table_id in zip(chart_ids, table_ids)
                ],
                "normalized_tables": [
                    {"table_id": table_id, "kind": "normalized"}
                    for table_id in table_ids
                ],
                "transforms": [
                    {
                        "transform_id": f"unit_test_projection:{chart_id}",
                        "operation": "projection",
                        "source_table_ids": [table_id],
                        "chart_ids": [chart_id],
                    }
                    for chart_id, table_id in zip(chart_ids, table_ids)
                ],
                "validation": {"valid": True, "diagnostics": []},
                "artifacts": {
                    "charts_json": str(evidence_bundle_path.with_name("charts.json")),
                    "execution_summary_json": str(
                        evidence_bundle_path.with_name("execution_summary.json")
                    ),
                    "evidence_bundle_json": str(evidence_bundle_path),
                },
            }
        ),
        encoding="utf-8",
    )


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


def test_orchestrator_tool_boundary_blocks_approval_emit_after_failed_report_gate():
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
                        '{"status":"failed",'
                        '"report_json":"/tmp/outputs/improver-123/report.json",'
                        '"required_upstream":"quant-developer",'
                        '"reason":"query requested charts but report.json contains zero chart definitions",'
                        '"required_fixes":["Regenerate quant artifacts."]}'
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
    assert "report gate failed" in response.content
    assert "Do not tell the user the report is approved" in response.content


def test_orchestrator_tool_boundary_routes_qa_repair_by_required_upstream(tmp_path):
    middleware = OrchestratorToolBoundaryMiddleware()
    report_path = tmp_path / "report.json"
    report_path.write_text("{}", encoding="utf-8")
    messages = [
        AIMessage(
            content=json.dumps(
                {
                    "status": "rejected",
                    "report_path": str(report_path),
                    "reason": "Report numeric claims do not match execution_summary.json numeric_facts.",
                    "required_fixes": [
                        "Revise the markdown so numeric claims use helper-produced numeric_facts."
                    ],
                    "failure_category": "numeric_fact_mismatch",
                    "required_upstream": "technical-writer",
                }
            )
        )
    ]
    wrong_request = SimpleNamespace(
        tool_call={
            "name": "task",
            "id": "wrong-owner",
            "args": {
                "subagent_type": "data-engineer",
                "description": "Inspect scenario evidence after QA rejection.",
            },
        },
        state={"messages": messages},
    )

    blocked = middleware.wrap_tool_call(
        wrong_request,
        lambda req: SimpleNamespace(content="delegated", status="success"),
    )

    assert "Blocked QA recovery delegation to `data-engineer`" in blocked.content
    assert "required_upstream=`technical-writer`" in blocked.content

    qa_request = SimpleNamespace(
        tool_call={
            "name": "task",
            "id": "qa-owner",
            "args": {
                "subagent_type": "quality-analyst",
                "description": "Review the repaired report after the writer fix.",
            },
        },
        state={"messages": messages},
    )
    qa_allowed = middleware.wrap_tool_call(
        qa_request,
        lambda req: SimpleNamespace(content="delegated", status="success"),
    )

    assert qa_allowed.content == "delegated"

    writer_request = SimpleNamespace(
        tool_call={
            "name": "task",
            "id": "right-owner",
            "args": {
                "subagent_type": "technical-writer",
                "description": "Repair the report from the QA numeric fact rejection.",
            },
        },
        state={"messages": messages},
    )
    allowed = middleware.wrap_tool_call(
        writer_request,
        lambda req: SimpleNamespace(content="delegated", status="success"),
    )

    assert allowed.content == "delegated"


def test_orchestrator_tool_boundary_routes_chart_handoff_repair_to_quant(tmp_path):
    middleware = OrchestratorToolBoundaryMiddleware()
    report_path = tmp_path / "report.json"
    report_path.write_text("{}", encoding="utf-8")
    messages = [
        AIMessage(
            content=json.dumps(
                {
                    "status": "rejected",
                    "report_path": str(report_path),
                    "reason": (
                        "chart_handoff_mismatch: final report did not preserve "
                        "non-dropped execution_summary.chart_ids "
                        "(missing_report_chart_ids=['savings_credit_stress'])"
                    ),
                    "required_fixes": [
                        "Regenerate quant artifacts so all non-dropped chart IDs are present."
                    ],
                    "failure_category": "chart_handoff_mismatch",
                    "required_upstream": "quant-developer",
                }
            )
        )
    ]
    writer_request = SimpleNamespace(
        tool_call={
            "name": "task",
            "id": "wrong-chart-owner",
            "args": {
                "subagent_type": "technical-writer",
                "description": "Repair chart handoff after QA rejection.",
            },
        },
        state={"messages": messages},
    )

    blocked = middleware.wrap_tool_call(
        writer_request,
        lambda req: SimpleNamespace(content="delegated", status="success"),
    )

    assert "Blocked QA recovery delegation to `technical-writer`" in blocked.content
    assert "required_upstream=`quant-developer`" in blocked.content

    quant_request = SimpleNamespace(
        tool_call={
            "name": "task",
            "id": "right-chart-owner",
            "args": {
                "subagent_type": "quant-developer",
                "description": "Regenerate missing chart definitions after QA rejection.",
            },
        },
        state={"messages": messages},
    )
    allowed = middleware.wrap_tool_call(
        quant_request,
        lambda req: SimpleNamespace(content="delegated", status="success"),
    )

    assert allowed.content == "delegated"


def test_orchestrator_tool_boundary_routes_artifact_fact_repair_to_quant(tmp_path):
    middleware = OrchestratorToolBoundaryMiddleware()
    report_path = tmp_path / "report.json"
    report_path.write_text("{}", encoding="utf-8")
    messages = [
        AIMessage(
            content=json.dumps(
                {
                    "status": "failed",
                    "report_json": str(report_path),
                    "reason": (
                        "artifact_fact_mismatch: conflicting correlation values "
                        "for UNRATE/CPIAUCSL"
                    ),
                    "required_fixes": [
                        "Regenerate quant artifacts so execution_summary.json, "
                        "numeric_facts, and chart data use one consistent fact basis."
                    ],
                    "failure_category": "artifact_fact_mismatch",
                    "required_upstream": "quant-developer",
                }
            )
        )
    ]
    writer_request = SimpleNamespace(
        tool_call={
            "name": "task",
            "id": "wrong-artifact-owner",
            "args": {
                "subagent_type": "technical-writer",
                "description": "Repair report prose after the artifact fact mismatch.",
            },
        },
        state={"messages": messages},
    )

    blocked = middleware.wrap_tool_call(
        writer_request,
        lambda req: SimpleNamespace(content="delegated", status="success"),
    )

    assert "Blocked QA recovery delegation to `technical-writer`" in blocked.content
    assert "required_upstream=`quant-developer`" in blocked.content

    quant_request = SimpleNamespace(
        tool_call={
            "name": "task",
            "id": "right-artifact-owner",
            "args": {
                "subagent_type": "quant-developer",
                "description": "Regenerate inconsistent quant artifacts after QA rejection.",
            },
        },
        state={"messages": messages},
    )
    allowed = middleware.wrap_tool_call(
        quant_request,
        lambda req: SimpleNamespace(content="delegated", status="success"),
    )

    assert allowed.content == "delegated"


def test_orchestrator_tool_boundary_routes_evidence_bundle_alias_to_quant(tmp_path):
    middleware = OrchestratorToolBoundaryMiddleware()
    report_path = tmp_path / "report.json"
    report_path.write_text("{}", encoding="utf-8")
    messages = [
        AIMessage(
            content=json.dumps(
                {
                    "status": "rejected",
                    "report_path": str(report_path),
                    "reason": (
                        "evidence_bundle_invalid: fact IDs in evidence_bundle.json "
                        "do not match execution_summary.json numeric_facts."
                    ),
                    "required_fixes": [
                        "Regenerate the canonical evidence bundle from current artifacts."
                    ],
                    "failure_category": "evidence_bundle_invalid",
                    "required_upstream": "quantitative-developer",
                }
            )
        )
    ]
    writer_request = SimpleNamespace(
        tool_call={
            "name": "task",
            "id": "wrong-bundle-owner",
            "args": {
                "subagent_type": "technical-writer",
                "description": "Revise report wording after the bundle rejection.",
            },
        },
        state={"messages": messages},
    )

    blocked = middleware.wrap_tool_call(
        writer_request,
        lambda req: SimpleNamespace(content="delegated", status="success"),
    )

    assert "Blocked QA recovery delegation to `technical-writer`" in blocked.content
    assert "required_upstream=`quant-developer`" in blocked.content

    quant_request = SimpleNamespace(
        tool_call={
            "name": "task",
            "id": "right-bundle-owner",
            "args": {
                "subagent_type": "quant-developer",
                "description": (
                    "Regenerate the canonical evidence bundle after QA rejection."
                ),
            },
        },
        state={"messages": messages},
    )
    allowed = middleware.wrap_tool_call(
        quant_request,
        lambda req: SimpleNamespace(content="delegated", status="success"),
    )

    assert allowed.content == "delegated"


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


def test_orchestrator_tool_boundary_blocks_writer_after_failed_quant_handoff(tmp_path):
    middleware = OrchestratorToolBoundaryMiddleware()
    summary_path = tmp_path / "execution_summary.json"
    charts_path = tmp_path / "charts.json"
    evidence_bundle_path = tmp_path / "evidence_bundle.json"
    summary_path.write_text(
        json.dumps(
            {
                "status": "failed",
                "failure_stage": "quant_invalid_task_handoff",
                "error": "quant-developer task returned no valid artifact handoff",
                "chart_ids": [],
            }
        ),
        encoding="utf-8",
    )
    charts_path.write_text("[]", encoding="utf-8")
    evidence_bundle_path.write_text("{}", encoding="utf-8")
    request = SimpleNamespace(
        tool_call={
            "name": "task",
            "id": "call-writer-failed-quant",
            "args": {
                "subagent_type": "technical-writer",
                "description": "Draft from the latest quant artifacts.",
            },
        },
        state={
            "messages": [
                AIMessage(
                    content=json.dumps(
                        {
                            "status": "failed",
                            "charts_json": str(charts_path),
                            "execution_summary_json": str(summary_path),
                            "evidence_bundle_json": str(evidence_bundle_path),
                            "chart_ids": [],
                        }
                    )
                )
            ]
        },
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )

    blocked = json.loads(response.content)
    assert response.tool_call_id == "call-writer-failed-quant"
    assert response.status == "error"
    assert blocked["status"] == "failed"
    assert blocked["failure_category"] == "quant_artifact_handoff_failed"
    assert blocked["required_upstream"] == "quant-developer"
    assert blocked["charts_json"] == str(charts_path)
    assert blocked["execution_summary_json"] == str(summary_path)
    assert blocked["evidence_bundle_json"] == str(evidence_bundle_path)
    assert blocked["chart_ids"] == []


def test_orchestrator_tool_boundary_blocks_writer_when_payload_status_failed_with_valid_artifacts(
    tmp_path,
):
    middleware = OrchestratorToolBoundaryMiddleware()
    summary_path = tmp_path / "execution_summary.json"
    charts_path = tmp_path / "charts.json"
    evidence_bundle_path = tmp_path / "evidence_bundle.json"
    charts_path.write_text(
        json.dumps({"macro_signal": {"id": "macro_signal", "data": [{"x": 1}]}}),
        encoding="utf-8",
    )
    summary_path.write_text(
        json.dumps({"status": "success", "chart_ids": ["macro_signal"]}),
        encoding="utf-8",
    )
    _write_valid_evidence_bundle(evidence_bundle_path, ["macro_signal"])
    request = SimpleNamespace(
        tool_call={
            "name": "task",
            "id": "call-writer-failed-status-valid-artifacts",
            "args": {
                "subagent_type": "technical-writer",
                "description": "Draft from the latest quant artifacts.",
            },
        },
        state={
            "messages": [
                AIMessage(
                    content=json.dumps(
                        {
                            "status": "failed",
                            "charts_json": str(charts_path),
                            "execution_summary_json": str(summary_path),
                            "evidence_bundle_json": str(evidence_bundle_path),
                            "chart_ids": ["macro_signal"],
                        }
                    )
                )
            ]
        },
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )

    blocked = json.loads(response.content)
    assert response.tool_call_id == "call-writer-failed-status-valid-artifacts"
    assert response.status == "error"
    assert blocked["status"] == "failed"
    assert blocked["blocked_subagent"] == "technical-writer"
    assert blocked["failure_category"] == "quant_artifact_handoff_failed"
    assert blocked["required_upstream"] == "quant-developer"
    assert blocked["chart_ids"] == ["macro_signal"]


def test_orchestrator_tool_boundary_blocks_writer_when_payload_chart_ids_empty_with_valid_artifacts(
    tmp_path,
):
    middleware = OrchestratorToolBoundaryMiddleware()
    summary_path = tmp_path / "execution_summary.json"
    charts_path = tmp_path / "charts.json"
    evidence_bundle_path = tmp_path / "evidence_bundle.json"
    charts_path.write_text(
        json.dumps({"macro_signal": {"id": "macro_signal", "data": [{"x": 1}]}}),
        encoding="utf-8",
    )
    summary_path.write_text(
        json.dumps({"status": "success", "chart_ids": ["macro_signal"]}),
        encoding="utf-8",
    )
    _write_valid_evidence_bundle(evidence_bundle_path, ["macro_signal"])
    request = SimpleNamespace(
        tool_call={
            "name": "task",
            "id": "call-writer-empty-payload-chart-ids",
            "args": {
                "subagent_type": "technical-writer",
                "description": "Draft from the latest quant artifacts.",
            },
        },
        state={
            "messages": [
                AIMessage(
                    content=json.dumps(
                        {
                            "charts_json": str(charts_path),
                            "execution_summary_json": str(summary_path),
                            "evidence_bundle_json": str(evidence_bundle_path),
                            "chart_ids": [],
                        }
                    )
                )
            ]
        },
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )

    blocked = json.loads(response.content)
    assert response.tool_call_id == "call-writer-empty-payload-chart-ids"
    assert response.status == "error"
    assert blocked["status"] == "failed"
    assert blocked["blocked_subagent"] == "technical-writer"
    assert blocked["failure_category"] == "quant_artifact_handoff_invalid"
    assert blocked["required_upstream"] == "quant-developer"
    assert blocked["chart_ids"] == []


def test_orchestrator_tool_boundary_allows_quant_repair_after_writer_quant_block(
    tmp_path,
):
    middleware = OrchestratorToolBoundaryMiddleware()
    summary_path = tmp_path / "execution_summary.json"
    charts_path = tmp_path / "charts.json"
    evidence_bundle_path = tmp_path / "evidence_bundle.json"
    summary_path.write_text(
        json.dumps(
            {
                "status": "failed",
                "failure_stage": "quant_invalid_task_handoff",
                "error": "quant-developer task returned no valid artifact handoff",
                "chart_ids": [],
            }
        ),
        encoding="utf-8",
    )
    charts_path.write_text("[]", encoding="utf-8")
    evidence_bundle_path.write_text("{}", encoding="utf-8")
    messages = [
        AIMessage(
            content=json.dumps(
                {
                    "status": "failed",
                    "charts_json": str(charts_path),
                    "execution_summary_json": str(summary_path),
                    "evidence_bundle_json": str(evidence_bundle_path),
                    "chart_ids": [],
                }
            )
        )
    ]
    writer_request = SimpleNamespace(
        tool_call={
            "name": "task",
            "id": "call-writer-failed-quant",
            "args": {
                "subagent_type": "technical-writer",
                "description": "Draft from the latest quant artifacts.",
            },
        },
        state={"messages": messages},
    )

    writer_response = middleware.wrap_tool_call(
        writer_request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )
    blocked_payload = json.loads(writer_response.content)
    messages.append(AIMessage(content=writer_response.content))

    assert blocked_payload["required_upstream"] == "quant-developer"
    assert blocked_payload["failure_category"] == "quant_artifact_handoff_failed"

    wrong_owner_request = SimpleNamespace(
        tool_call={
            "name": "task",
            "id": "call-wrong-owner-after-writer-block",
            "args": {
                "subagent_type": "data-engineer",
                "description": "Repair the failed quant artifact handoff.",
            },
        },
        state={"messages": messages},
    )
    wrong_owner_response = middleware.wrap_tool_call(
        wrong_owner_request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )

    assert "Blocked QA recovery delegation to `data-engineer`" in wrong_owner_response.content
    assert "required_upstream=`quant-developer`" in wrong_owner_response.content

    qa_request = SimpleNamespace(
        tool_call={
            "name": "task",
            "id": "call-qa-after-writer-block",
            "args": {
                "subagent_type": "quality-analyst",
                "description": "Review the failed quant artifact handoff.",
            },
        },
        state={"messages": messages},
    )
    qa_response = middleware.wrap_tool_call(
        qa_request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )
    qa_blocked = json.loads(qa_response.content)

    assert qa_response.tool_call_id == "call-qa-after-writer-block"
    assert qa_response.status == "error"
    assert qa_blocked["blocked_subagent"] == "quality-analyst"
    assert qa_blocked["failure_category"] == "quant_artifact_handoff_failed"
    assert qa_blocked["required_upstream"] == "quant-developer"

    quant_repair_request = SimpleNamespace(
        tool_call={
            "name": "task",
            "id": "call-quant-repair-after-writer-block",
            "args": {
                "subagent_type": "quant-developer",
                "description": "Repair the failed handoff using the listed fields.",
            },
        },
        state={"messages": messages},
    )
    quant_response = middleware.wrap_tool_call(
        quant_repair_request,
        lambda req: SimpleNamespace(content="delegated", status="success"),
    )

    assert quant_response.content == "delegated"


def test_orchestrator_tool_boundary_blocks_writer_after_invalid_latest_evidence_bundle(
    tmp_path,
):
    middleware = OrchestratorToolBoundaryMiddleware()
    summary_path = tmp_path / "execution_summary.json"
    charts_path = tmp_path / "charts.json"
    evidence_bundle_path = tmp_path / "evidence_bundle.json"
    charts_path.write_text(
        json.dumps({"macro_signal": {"id": "macro_signal", "data": [{"x": 1}]}}),
        encoding="utf-8",
    )
    summary_path.write_text(
        json.dumps({"chart_ids": ["macro_signal"]}),
        encoding="utf-8",
    )
    evidence_bundle_path.write_text(
        json.dumps({"bundle_type": "quant_evidence_bundle"}),
        encoding="utf-8",
    )
    request = SimpleNamespace(
        tool_call={
            "name": "task",
            "id": "call-writer-invalid-bundle",
            "args": {
                "subagent_type": "technical-writer",
                "description": "Draft from the latest quant artifacts.",
            },
        },
        state={
            "messages": [
                AIMessage(
                    content=json.dumps(
                        {
                            "charts_json": str(charts_path),
                            "execution_summary_json": str(summary_path),
                            "evidence_bundle_json": str(evidence_bundle_path),
                            "chart_ids": ["macro_signal"],
                        }
                    )
                )
            ]
        },
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )

    blocked = json.loads(response.content)
    assert response.tool_call_id == "call-writer-invalid-bundle"
    assert response.status == "error"
    assert blocked["failure_category"] == "quant_artifact_handoff_invalid"
    assert blocked["required_upstream"] == "quant-developer"
    assert blocked["chart_ids"] == ["macro_signal"]
    assert "structurally invalid" in blocked["reason"]


def test_orchestrator_tool_boundary_allows_writer_after_later_valid_quant_handoff(
    tmp_path,
):
    middleware = OrchestratorToolBoundaryMiddleware()
    stale_summary_path = tmp_path / "stale_execution_summary.json"
    stale_charts_path = tmp_path / "stale_charts.json"
    stale_evidence_bundle_path = tmp_path / "stale_evidence_bundle.json"
    stale_summary_path.write_text('{"status":"failed","chart_ids":[]}', encoding="utf-8")
    stale_charts_path.write_text("[]", encoding="utf-8")
    stale_evidence_bundle_path.write_text("{}", encoding="utf-8")

    output_dir = tmp_path / "valid"
    output_dir.mkdir()
    summary_path = output_dir / "execution_summary.json"
    charts_path = output_dir / "charts.json"
    evidence_bundle_path = output_dir / "evidence_bundle.json"
    charts_path.write_text(
        json.dumps({"macro_signal": {"id": "macro_signal", "data": [{"x": 1}]}}),
        encoding="utf-8",
    )
    summary_path.write_text(
        json.dumps({"chart_ids": ["macro_signal"]}),
        encoding="utf-8",
    )
    _write_valid_evidence_bundle(evidence_bundle_path, ["macro_signal"])
    request = SimpleNamespace(
        tool_call={
            "name": "task",
            "id": "call-writer-after-valid-quant",
            "args": {
                "subagent_type": "technical-writer",
                "description": "Draft from the repaired quant artifacts.",
            },
        },
        state={
            "messages": [
                AIMessage(
                    content=json.dumps(
                        {
                            "status": "failed",
                            "charts_json": str(stale_charts_path),
                            "execution_summary_json": str(stale_summary_path),
                            "evidence_bundle_json": str(stale_evidence_bundle_path),
                            "chart_ids": [],
                        }
                    )
                ),
                AIMessage(
                    content=json.dumps(
                        {
                            "charts_json": str(charts_path),
                            "execution_summary_json": str(summary_path),
                            "evidence_bundle_json": str(evidence_bundle_path),
                            "chart_ids": ["macro_signal"],
                        }
                    )
                ),
            ]
        },
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: SimpleNamespace(content="delegated", status="success"),
    )

    assert response.content == "delegated"


def test_orchestrator_tool_boundary_allows_writer_after_quant_satisfies_qa_repair(
    tmp_path,
):
    middleware = OrchestratorToolBoundaryMiddleware()
    report_path = tmp_path / "report.json"
    report_path.write_text("{}", encoding="utf-8")
    output_dir = tmp_path / "valid"
    output_dir.mkdir()
    summary_path = output_dir / "execution_summary.json"
    charts_path = output_dir / "charts.json"
    evidence_bundle_path = output_dir / "evidence_bundle.json"
    charts_path.write_text(
        json.dumps({"macro_signal": {"id": "macro_signal", "data": [{"x": 1}]}}),
        encoding="utf-8",
    )
    summary_path.write_text(
        json.dumps({"status": "success", "chart_ids": ["macro_signal"]}),
        encoding="utf-8",
    )
    _write_valid_evidence_bundle(evidence_bundle_path, ["macro_signal"])
    messages = [
        AIMessage(
            content=json.dumps(
                {
                    "status": "rejected",
                    "report_path": str(report_path),
                    "reason": "Report is missing the repaired quant chart handoff.",
                    "required_fixes": [
                        "Regenerate quant artifacts and preserve chart_ids."
                    ],
                    "failure_category": "chart_handoff_mismatch",
                    "required_upstream": "quant-developer",
                }
            )
        ),
        AIMessage(
            content=json.dumps(
                {
                    "charts_json": str(charts_path),
                    "execution_summary_json": str(summary_path),
                    "evidence_bundle_json": str(evidence_bundle_path),
                    "chart_ids": ["macro_signal"],
                }
            )
        ),
    ]
    request = SimpleNamespace(
        tool_call={
            "name": "task",
            "id": "call-writer-after-qa-quant-repair",
            "args": {
                "subagent_type": "technical-writer",
                "description": "Draft from the repaired quant artifacts.",
            },
        },
        state={"messages": messages},
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: SimpleNamespace(content="delegated", status="success"),
    )

    assert response.content == "delegated"


def test_orchestrator_tool_boundary_keeps_qa_quant_repair_active_after_invalid_handoff(
    tmp_path,
):
    middleware = OrchestratorToolBoundaryMiddleware()
    report_path = tmp_path / "report.json"
    report_path.write_text("{}", encoding="utf-8")
    summary_path = tmp_path / "execution_summary.json"
    charts_path = tmp_path / "charts.json"
    evidence_bundle_path = tmp_path / "evidence_bundle.json"
    charts_path.write_text("[]", encoding="utf-8")
    summary_path.write_text(
        json.dumps(
            {
                "status": "failed",
                "failure_stage": "quant_invalid_task_handoff",
                "chart_ids": [],
            }
        ),
        encoding="utf-8",
    )
    evidence_bundle_path.write_text("{}", encoding="utf-8")
    messages = [
        AIMessage(
            content=json.dumps(
                {
                    "status": "rejected",
                    "report_path": str(report_path),
                    "reason": "Report is missing required chart artifacts.",
                    "required_fixes": ["Regenerate a valid quant handoff."],
                    "failure_category": "chart_handoff_mismatch",
                    "required_upstream": "quant-developer",
                }
            )
        ),
        AIMessage(
            content=json.dumps(
                {
                    "status": "failed",
                    "charts_json": str(charts_path),
                    "execution_summary_json": str(summary_path),
                    "evidence_bundle_json": str(evidence_bundle_path),
                    "chart_ids": [],
                }
            )
        ),
    ]
    request = SimpleNamespace(
        tool_call={
            "name": "task",
            "id": "call-writer-after-invalid-qa-quant-repair",
            "args": {
                "subagent_type": "technical-writer",
                "description": "Draft from the latest quant artifacts.",
            },
        },
        state={"messages": messages},
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )

    assert response.tool_call_id == "call-writer-after-invalid-qa-quant-repair"
    assert response.status == "error"
    assert "Blocked QA recovery delegation to `technical-writer`" in response.content
    assert "required_upstream=`quant-developer`" in response.content


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
    assert "Do not delegate technical-writer" in response.content
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


def test_orchestrator_tool_boundary_normalizes_invalid_quant_task_result(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(quant_dev, "OUTPUT_BASE_DIR", str(tmp_path))
    middleware = OrchestratorToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={
            "name": "task",
            "id": "call-invalid-quant-result",
            "args": {
                "subagent_type": "quant-developer",
                "description": (
                    "Write and run /home/vorndranj/projects/DeepResearchAgent/"
                    "backend/outputs/improver-test/code/analysis.py, then return "
                    "charts_json, execution_summary_json, and chart_ids."
                ),
            },
        },
        state={"messages": []},
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: ToolMessage(
            content="1\t--- 2\tname: quant-script-workflow",
            name="task",
            tool_call_id=req.tool_call["id"],
            status="success",
        ),
    )

    handoff = json.loads(response.content)
    output_dir = tmp_path / "improver-test"
    assert response.tool_call_id == "call-invalid-quant-result"
    assert response.status == "success"
    assert handoff["status"] == "failed"
    assert handoff["failure_stage"] == "quant_invalid_task_handoff"
    assert handoff["methods_used"] == ["orchestrator_quant_task_result_guard"]
    assert handoff["charts_json"] == str(output_dir / "charts.json")
    assert handoff["execution_summary_json"] == str(output_dir / "execution_summary.json")
    assert handoff["evidence_bundle_json"] == str(output_dir / "evidence_bundle.json")
    assert json.loads((output_dir / "charts.json").read_text(encoding="utf-8")) == []
    summary = json.loads((output_dir / "execution_summary.json").read_text())
    assert summary["failure_stage"] == "quant_invalid_task_handoff"


def test_orchestrator_tool_boundary_recovers_quant_task_result_from_saved_artifacts(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(quant_dev, "OUTPUT_BASE_DIR", str(tmp_path))
    output_dir = tmp_path / "improver-artifacts"
    output_dir.mkdir()
    (output_dir / "charts.json").write_text(
        json.dumps(
            {
                "macro_signal": {
                    "id": "macro_signal",
                    "type": "line",
                    "xAxisKey": "date",
                    "series": [{"dataKey": "risk"}],
                    "data": [{"date": "2026-04-01", "risk": 0.42}],
                }
            }
        ),
        encoding="utf-8",
    )
    (output_dir / "execution_summary.json").write_text(
        json.dumps(
            {
                "chart_ids": ["macro_signal"],
                "evidence_bundle_json": str(output_dir / "evidence_bundle.json"),
                "statistical_summary": "Computed macro signal chart data.",
            }
        ),
        encoding="utf-8",
    )
    _write_valid_evidence_bundle(output_dir / "evidence_bundle.json", ["macro_signal"])
    middleware = OrchestratorToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={
            "name": "task",
            "id": "call-artifact-quant-result",
            "args": {
                "subagent_type": "quant-developer",
                "description": "Run the current job and return compact quant artifacts.",
            },
        },
        state={"messages": []},
        runtime=SimpleNamespace(context=SimpleNamespace(job_id="improver-artifacts")),
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: ToolMessage(
            content="Completed analysis and wrote artifacts, but omitted compact JSON.",
            name="task",
            tool_call_id=req.tool_call["id"],
            status="success",
        ),
    )

    handoff = json.loads(response.content)
    assert response.tool_call_id == "call-artifact-quant-result"
    assert response.status == "success"
    assert handoff == {
        "chart_ids": ["macro_signal"],
        "charts_json": str(output_dir / "charts.json"),
        "execution_summary_json": str(output_dir / "execution_summary.json"),
        "evidence_bundle_json": str(output_dir / "evidence_bundle.json"),
        "statistical_summary_excerpt": "Computed macro signal chart data.",
    }
    assert not (output_dir / "quant_failure_summary.json").exists()


def test_orchestrator_quant_artifact_recovery_requires_valid_matching_charts_json(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(quant_dev, "OUTPUT_BASE_DIR", str(tmp_path))
    middleware = OrchestratorToolBoundaryMiddleware()
    cases = {
        "missing-charts": None,
        "bad-charts": "{not valid json",
        "mismatched-charts": json.dumps(
            {
                "other_signal": {
                    "id": "other_signal",
                    "type": "line",
                    "xAxisKey": "date",
                    "series": [{"dataKey": "risk"}],
                    "data": [{"date": "2026-04-01", "risk": 0.42}],
                }
            }
        ),
    }
    for job_id, charts_content in cases.items():
        output_dir = tmp_path / job_id
        output_dir.mkdir()
        if charts_content is not None:
            (output_dir / "charts.json").write_text(charts_content, encoding="utf-8")
        (output_dir / "execution_summary.json").write_text(
            json.dumps(
                {
                    "chart_ids": ["macro_signal"],
                    "statistical_summary": "Computed macro signal chart data.",
                }
            ),
            encoding="utf-8",
        )
        _write_valid_evidence_bundle(
            output_dir / "evidence_bundle.json",
            ["macro_signal"],
        )
        request = SimpleNamespace(
            tool_call={
                "name": "task",
                "id": f"call-{job_id}",
                "args": {
                    "subagent_type": "quant-developer",
                    "description": "Run the current job and return compact quant artifacts.",
                },
            },
            state={"messages": []},
            runtime=SimpleNamespace(context=SimpleNamespace(job_id=job_id)),
        )

        assert (
            middleware._quant_artifact_handoff_from_files(
                request,
                "Completed analysis and wrote artifacts, but omitted compact JSON.",
            )
            is None
        )


def test_orchestrator_quant_artifact_recovery_requires_evidence_bundle_json(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(quant_dev, "OUTPUT_BASE_DIR", str(tmp_path))
    middleware = OrchestratorToolBoundaryMiddleware()
    output_dir = tmp_path / "missing-bundle"
    output_dir.mkdir()
    (output_dir / "charts.json").write_text(
        json.dumps(
            {
                "macro_signal": {
                    "id": "macro_signal",
                    "type": "line",
                    "data": [{"date": "2026-04-01", "risk": 0.42}],
                }
            }
        ),
        encoding="utf-8",
    )
    (output_dir / "execution_summary.json").write_text(
        json.dumps({"chart_ids": ["macro_signal"]}),
        encoding="utf-8",
    )
    request = SimpleNamespace(
        tool_call={
            "name": "task",
            "id": "call-missing-bundle",
            "args": {
                "subagent_type": "quant-developer",
                "description": "Run the current job and return compact quant artifacts.",
            },
        },
        state={"messages": []},
        runtime=SimpleNamespace(context=SimpleNamespace(job_id="missing-bundle")),
    )

    assert (
        middleware._quant_artifact_handoff_from_files(
            request,
            "Completed analysis and wrote artifacts, but omitted compact JSON.",
        )
        is None
    )


def test_orchestrator_quant_artifact_recovery_requires_valid_evidence_bundle_json(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(quant_dev, "OUTPUT_BASE_DIR", str(tmp_path))
    middleware = OrchestratorToolBoundaryMiddleware()
    output_dir = tmp_path / "invalid-bundle"
    output_dir.mkdir()
    (output_dir / "charts.json").write_text(
        json.dumps(
            {
                "macro_signal": {
                    "id": "macro_signal",
                    "type": "line",
                    "data": [{"date": "2026-04-01", "risk": 0.42}],
                }
            }
        ),
        encoding="utf-8",
    )
    (output_dir / "execution_summary.json").write_text(
        json.dumps({"chart_ids": ["macro_signal"]}),
        encoding="utf-8",
    )
    (output_dir / "evidence_bundle.json").write_text(
        json.dumps({"bundle_type": "quant_evidence_bundle"}),
        encoding="utf-8",
    )
    request = SimpleNamespace(
        tool_call={
            "name": "task",
            "id": "call-invalid-bundle",
            "args": {
                "subagent_type": "quant-developer",
                "description": "Run the current job and return compact quant artifacts.",
            },
        },
        state={"messages": []},
        runtime=SimpleNamespace(context=SimpleNamespace(job_id="invalid-bundle")),
    )

    assert (
        middleware._quant_artifact_handoff_from_files(
            request,
            "Completed analysis and wrote artifacts, but omitted compact JSON.",
        )
        is None
    )


def test_orchestrator_tool_boundary_normalizes_fenced_quant_task_handoff(tmp_path):
    middleware = OrchestratorToolBoundaryMiddleware()
    output_dir = tmp_path / "job"
    output_dir.mkdir()
    (output_dir / "charts.json").write_text(
        json.dumps({"macro_signal": {"id": "macro_signal", "data": [{"x": 1}]}}),
        encoding="utf-8",
    )
    (output_dir / "execution_summary.json").write_text(
        json.dumps(
            {
                "chart_ids": ["macro_signal"],
                "evidence_bundle_json": str(output_dir / "evidence_bundle.json"),
            }
        ),
        encoding="utf-8",
    )
    _write_valid_evidence_bundle(output_dir / "evidence_bundle.json", ["macro_signal"])
    payload = {
        "chart_ids": ["macro_signal"],
        "charts_json": str(output_dir / "charts.json"),
        "execution_summary_json": str(output_dir / "execution_summary.json"),
        "evidence_bundle_json": str(output_dir / "evidence_bundle.json"),
    }
    request = SimpleNamespace(
        tool_call={
            "name": "task",
            "id": "call-fenced-quant-result",
            "args": {
                "subagent_type": "quant-developer",
                "description": "Run the current job and return compact quant artifacts.",
            },
        },
        state={"messages": []},
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: ToolMessage(
            content=f"```json\n{json.dumps(payload)}\n```",
            name="task",
            tool_call_id=req.tool_call["id"],
            status="success",
        ),
    )

    assert json.loads(response.content) == payload


def test_orchestrator_tool_boundary_rejects_direct_handoff_missing_evidence_bundle(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(quant_dev, "OUTPUT_BASE_DIR", str(tmp_path))
    middleware = OrchestratorToolBoundaryMiddleware()
    output_dir = tmp_path / "direct-missing-bundle"
    output_dir.mkdir()
    (output_dir / "charts.json").write_text(
        json.dumps({"macro_signal": {"id": "macro_signal", "data": [{"x": 1}]}}),
        encoding="utf-8",
    )
    (output_dir / "execution_summary.json").write_text(
        json.dumps(
            {
                "chart_ids": ["macro_signal"],
                "evidence_bundle_json": str(output_dir / "evidence_bundle.json"),
            }
        ),
        encoding="utf-8",
    )
    payload = {
        "chart_ids": ["macro_signal"],
        "charts_json": str(output_dir / "charts.json"),
        "execution_summary_json": str(output_dir / "execution_summary.json"),
        "evidence_bundle_json": str(output_dir / "evidence_bundle.json"),
    }
    request = SimpleNamespace(
        tool_call={
            "name": "task",
            "id": "call-direct-missing-bundle",
            "args": {
                "subagent_type": "quant-developer",
                "description": "Run the current job and return compact quant artifacts.",
            },
        },
        state={"messages": []},
        runtime=SimpleNamespace(context=SimpleNamespace(job_id="direct-missing-bundle")),
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: ToolMessage(
            content=json.dumps(payload),
            name="task",
            tool_call_id=req.tool_call["id"],
            status="success",
        ),
    )

    handoff = json.loads(response.content)
    assert handoff["status"] == "failed"
    assert handoff["failure_stage"] == "quant_invalid_task_handoff"
    assert handoff["chart_ids"] == []


def test_orchestrator_quant_failure_handoff_uses_runtime_job_id_over_prompt_examples(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(quant_dev, "OUTPUT_BASE_DIR", str(tmp_path))
    middleware = OrchestratorToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={
            "name": "task",
            "id": "call-invalid-current-job",
            "args": {
                "subagent_type": "quant-developer",
                "description": "Run the current job and return compact quant artifacts.",
            },
        },
        state={
            "messages": [
                AIMessage(
                    content=(
                        "Instruction example: copy paths like "
                        "/app/outputs/job_a61b3825/charts.json exactly."
                    )
                )
            ]
        },
        runtime=SimpleNamespace(context=SimpleNamespace(job_id="job_6299bc0b")),
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: ToolMessage(
            content="The quant task ended without a compact handoff.",
            name="task",
            tool_call_id=req.tool_call["id"],
            status="success",
        ),
    )

    handoff = json.loads(response.content)
    output_dir = tmp_path / "job_6299bc0b"
    assert handoff["charts_json"] == str(output_dir / "charts.json")
    assert handoff["execution_summary_json"] == str(output_dir / "execution_summary.json")
    assert (output_dir / "execution_summary.json").is_file()
    assert not (tmp_path / "job_a61b3825").exists()


def test_orchestrator_tool_boundary_normalizes_invalid_quant_command_result(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(quant_dev, "OUTPUT_BASE_DIR", str(tmp_path))
    middleware = OrchestratorToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={
            "name": "task",
            "id": "call-invalid-quant-command",
            "args": {
                "subagent_type": "quant-developer",
                "description": (
                    "Write and run /home/vorndranj/projects/DeepResearchAgent/"
                    "backend/outputs/improver-command/code/analysis.py, then return "
                    "compact JSON with charts_json, execution_summary_json, and chart_ids."
                ),
            },
        },
        state={"messages": []},
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: Command(
            update={
                "messages": [
                    ToolMessage(
                        content=(
                            "A successful script stdout that includes `charts_json`, "
                            "`execution_summary_json`, and `chart_ids` is already a "
                            "validation signal, but I did not create artifacts."
                        ),
                        name="task",
                        tool_call_id=req.tool_call["id"],
                        status="success",
                    )
                ]
            }
        ),
    )

    assert isinstance(response, Command)
    normalized = response.update["messages"][0]
    handoff = json.loads(normalized.content)
    output_dir = tmp_path / "improver-command"
    assert normalized.tool_call_id == "call-invalid-quant-command"
    assert normalized.status == "success"
    assert handoff["status"] == "failed"
    assert handoff["failure_stage"] == "quant_invalid_task_handoff"
    assert handoff["methods_used"] == ["orchestrator_quant_task_result_guard"]
    assert handoff["charts_json"] == str(output_dir / "charts.json")
    assert handoff["execution_summary_json"] == str(output_dir / "execution_summary.json")
    assert handoff["evidence_bundle_json"] == str(output_dir / "evidence_bundle.json")
    assert json.loads((output_dir / "charts.json").read_text(encoding="utf-8")) == []


def test_orchestrator_tool_boundary_blocks_repeat_quant_after_malformed_handoff():
    middleware = OrchestratorToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={
            "name": "task",
            "id": "call-repeat-malformed-quant",
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
                        '"failure_stage":"quant_malformed_tool_call",'
                        '"methods_used":["quant_malformed_tool_call_guard"],'
                        '"execution_summary_json":"/tmp/outputs/job/execution_summary.json",'
                        '"charts_json":"/tmp/outputs/job/charts.json",'
                        '"chart_ids":[]}'
                    )
                )
            ]
        },
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )

    assert response.tool_call_id == "call-repeat-malformed-quant"
    assert response.status == "error"
    assert "Blocked repeat quant-developer delegation" in response.content


def test_orchestrator_tool_boundary_blocks_repeat_quant_after_successful_handoff(tmp_path):
    middleware = OrchestratorToolBoundaryMiddleware()
    summary_path = tmp_path / "execution_summary.json"
    charts_path = tmp_path / "charts.json"
    evidence_bundle_path = tmp_path / "evidence_bundle.json"
    summary_path.write_text("{}", encoding="utf-8")
    charts_path.write_text('{"charts":[]}', encoding="utf-8")
    _write_valid_evidence_bundle(
        evidence_bundle_path,
        ["recession_risk", "labor_market"],
    )
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
                        f'"evidence_bundle_json":"{evidence_bundle_path}",'
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


def test_orchestrator_tool_boundary_allows_quant_when_evidence_bundle_is_invalid(tmp_path):
    middleware = OrchestratorToolBoundaryMiddleware()
    summary_path = tmp_path / "execution_summary.json"
    charts_path = tmp_path / "charts.json"
    evidence_bundle_path = tmp_path / "evidence_bundle.json"
    summary_path.write_text("{}", encoding="utf-8")
    charts_path.write_text('{"charts":[]}', encoding="utf-8")
    evidence_bundle_path.write_text(
        json.dumps({"bundle_type": "quant_evidence_bundle"}),
        encoding="utf-8",
    )
    request = SimpleNamespace(
        tool_call={
            "name": "task",
            "id": "call-invalid-prior-bundle",
            "args": {
                "subagent_type": "quant-developer",
                "description": "Regenerate the invalid quantitative evidence bundle.",
            },
        },
        state={
            "messages": [
                AIMessage(
                    content=(
                        f'{{"execution_summary_json":"{summary_path}",'
                        f'"charts_json":"{charts_path}",'
                        f'"evidence_bundle_json":"{evidence_bundle_path}",'
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
    evidence_bundle_path = tmp_path / "evidence_bundle.json"
    summary_path.write_text("{}", encoding="utf-8")
    charts_path.write_text('{"charts":[]}', encoding="utf-8")
    _write_valid_evidence_bundle(evidence_bundle_path, ["recession_risk"])
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
                        f'"evidence_bundle_json":"{evidence_bundle_path}",'
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


def test_orchestrator_tool_boundary_uses_structured_qa_fixes_for_quant_repair(tmp_path):
    middleware = OrchestratorToolBoundaryMiddleware()
    summary_path = tmp_path / "execution_summary.json"
    charts_path = tmp_path / "charts.json"
    report_path = tmp_path / "report.json"
    summary_path.write_text("{}", encoding="utf-8")
    charts_path.write_text('{"charts":[]}', encoding="utf-8")
    report_path.write_text("{}", encoding="utf-8")
    request = SimpleNamespace(
        tool_call={
            "name": "task",
            "id": "call-structured-qa-quant-fix",
            "args": {
                "subagent_type": "quant-developer",
                "description": "Add the 1995 comparison window and refresh the handoff.",
            },
        },
        state={
            "messages": [
                AIMessage(
                    content=(
                        f'{{"execution_summary_json":"{summary_path}",'
                        f'"charts_json":"{charts_path}",'
                        '"chart_ids":["analog_distance_bubble"]}'
                    )
                ),
                AIMessage(
                    content=json.dumps(
                        {
                            "status": "rejected",
                            "report_path": str(report_path),
                            "reason": (
                                "execution_summary.json lacks requested historical "
                                "analog window(s) for 1995."
                            ),
                            "required_fixes": [
                                "Rerun quant-developer to add computed analog window coverage for 1995."
                            ],
                        }
                    )
                ),
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
    evidence_bundle_path = tmp_path / "evidence_bundle.json"
    summary_path.write_text("{}", encoding="utf-8")
    charts_path.write_text('{"charts":[]}', encoding="utf-8")
    _write_valid_evidence_bundle(
        evidence_bundle_path,
        ["composite_signal_history", "unemployment_forecast"],
    )
    request = SimpleNamespace(
        tool_call={
            "name": "task",
            "id": "call-qa-summary-enrichment",
            "args": {
                "subagent_type": "quant-developer",
                "description": (
                    "QA rejection: execution_summary.json lacks structured "
                    "validation diagnostics, model_validation_rows, and replay_rows "
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


def test_orchestrator_tool_boundary_allows_qa_quant_fix_for_missing_chart_family(tmp_path):
    middleware = OrchestratorToolBoundaryMiddleware()
    summary_path = tmp_path / "execution_summary.json"
    charts_path = tmp_path / "charts.json"
    summary_path.write_text("{}", encoding="utf-8")
    charts_path.write_text('{"yield_curve_recession_lead":{}}', encoding="utf-8")
    request = SimpleNamespace(
        tool_call={
            "name": "task",
            "id": "call-qa-missing-chart-family",
            "args": {
                "subagent_type": "quant-developer",
                "description": (
                    "QA rejected the report because the scatter/bubble chart family "
                    "is missing. Add the missing chart definition to charts.json "
                    "from the existing FRED data files."
                ),
            },
        },
        state={
            "messages": [
                AIMessage(
                    content=(
                        f'{{"execution_summary_json":"{summary_path}",'
                        f'"charts_json":"{charts_path}",'
                        '"chart_ids":["yield_curve_recession_lead"]}'
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
    evidence_bundle_path = tmp_path / "evidence_bundle.json"
    summary_path.write_text("{}", encoding="utf-8")
    charts_path.write_text('{"charts":[]}', encoding="utf-8")
    _write_valid_evidence_bundle(
        evidence_bundle_path,
        [
            "risk-index",
            "labor-dashboard",
            "unemployment-forecast",
            "inflation-crosscheck",
        ],
    )
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
                        f'"evidence_bundle_json":"{evidence_bundle_path}",'
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
    evidence_bundle_path = tmp_path / "evidence_bundle.json"
    summary_path.write_text("{}", encoding="utf-8")
    charts_path.write_text('{"charts":[]}', encoding="utf-8")
    _write_valid_evidence_bundle(
        evidence_bundle_path,
        ["recession_risk", "yield_curve", "inflation"],
    )
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
                        f'"evidence_bundle_json":"{evidence_bundle_path}",'
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
    evidence_bundle_path = tmp_path / "evidence_bundle.json"
    summary_path.write_text("{}", encoding="utf-8")
    charts_path.write_text('{"charts":[]}', encoding="utf-8")
    _write_valid_evidence_bundle(
        evidence_bundle_path,
        ["macro_dashboard", "recession_probability"],
    )
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
                        f'"evidence_bundle_json":"{evidence_bundle_path}",'
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
                    "QA says execution_summary.json lacks generic validation diagnostics and "
                    "replay_rows. Required fixes: add structured replay "
                    "rows and preserve the computed signal metrics."
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


def test_orchestrator_tool_boundary_blocks_after_qa_repair_budget_exhausted(tmp_path):
    middleware = OrchestratorToolBoundaryMiddleware()
    report_path = tmp_path / "report.json"
    report_path.write_text("{}", encoding="utf-8")
    rejected = {
        "status": "rejected",
        "report_path": str(report_path),
        "reason": "execution_summary.json lacks requested historical analog window(s).",
        "required_fixes": ["Rerun quant-developer to add computed analog windows."],
    }
    request = SimpleNamespace(
        tool_call={
            "name": "task",
            "id": "call-budget-exhausted",
            "args": {
                "subagent_type": "technical-writer",
                "description": "Try one more rewrite after QA rejection.",
            },
        },
        state={"messages": [AIMessage(content=json.dumps(rejected)) for _ in range(3)]},
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )

    assert response.tool_call_id == "call-budget-exhausted"
    assert response.status == "error"
    assert "QA repair budget is exhausted" in response.content


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


def test_strip_tool_call_content_middleware_forces_failure_after_qa_budget_exhausted(
    tmp_path,
):
    middleware = StripToolCallContentMiddleware()
    report_path = tmp_path / "report.json"
    report_path.write_text("{}", encoding="utf-8")
    rejected = {
        "status": "rejected",
        "report_path": str(report_path),
        "reason": "Report contradicts execution_summary signal-framework results.",
        "required_fixes": [
            "Rewrite the report from execution_summary.json; do not approve it."
        ],
        "required_upstream": "technical-writer",
    }
    request = SimpleNamespace(
        messages=[AIMessage(content=json.dumps(rejected)) for _ in range(3)]
    )

    response = middleware.wrap_model_call(
        request=request,
        handler=lambda _: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )

    payload = json.loads(response.result[0].content)
    assert payload == {
        "ready_for_upload": False,
        "reason": "Report contradicts execution_summary signal-framework results.",
        "report_path": str(report_path),
        "required_fixes": [
            "Rewrite the report from execution_summary.json; do not approve it."
        ],
        "required_upstream": "technical-writer",
        "status": "rejected",
    }
    assert response.result[0].tool_calls == []


def test_strip_tool_call_content_middleware_does_not_force_stale_approval_after_rejection(
    tmp_path,
):
    middleware = StripToolCallContentMiddleware()
    report_path = tmp_path / "report.json"
    report_path.write_text("{}", encoding="utf-8")
    approved = {
        "status": "approved",
        "report_path": str(report_path),
    }
    rejected = {
        "status": "rejected",
        "report_path": str(report_path),
        "reason": "Latest QA result rejected the report.",
        "required_fixes": ["Do not upload."],
    }
    request = SimpleNamespace(
        messages=[
            AIMessage(content=json.dumps(approved)),
            AIMessage(content=json.dumps(rejected)),
            AIMessage(content=json.dumps(rejected)),
            AIMessage(content=json.dumps(rejected)),
        ]
    )

    response = middleware.wrap_model_call(
        request=request,
        handler=lambda _: ModelResponse(
            result=[AIMessage(content="Report approved: outputs/job/report.json")]
        ),
    )

    payload = json.loads(response.result[0].content)
    assert payload["status"] == "rejected"
    assert payload["reason"] == "Latest QA result rejected the report."
    assert not response.result[0].tool_calls

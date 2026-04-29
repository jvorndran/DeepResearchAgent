import pytest
from langchain_core.messages import ToolMessage

from agents import orchestrator
from agents.orchestrator import EXECUTION_SYSTEM_PROMPT


def test_execution_prompt_forbids_startup_prose_and_filesystem_inspection():
    assert "These execution rules override generic Deep Agent guidance" in EXECUTION_SYSTEM_PROMPT
    assert "NO ASSISTANT PROSE DURING EXECUTION" in EXECUTION_SYSTEM_PROMPT
    assert "assistant message content must be empty" in EXECUTION_SYSTEM_PROMPT
    assert "delivered-summary tables" in EXECUTION_SYSTEM_PROMPT
    assert "make exactly two tool calls and no assistant text" in EXECUTION_SYSTEM_PROMPT
    assert "NO STARTUP FILESYSTEM INSPECTION" in EXECUTION_SYSTEM_PROMPT
    assert "TERMINAL APPROVAL RESPONSE" in EXECUTION_SYSTEM_PROMPT
    assert "Report approved: outputs/{job_id}/report.json" in EXECUTION_SYSTEM_PROMPT
    assert "Do not add any assistant content after that tool call" in EXECUTION_SYSTEM_PROMPT
    assert "TECHNICAL-WRITER TOOL CONTRACT" in EXECUTION_SYSTEM_PROMPT
    assert "call `plan_report_structure` first" in EXECUTION_SYSTEM_PROMPT
    assert "If `plan_report_structure` returns truncated-looking text" in EXECUTION_SYSTEM_PROMPT
    assert "Do not demand exact data filenames" in EXECUTION_SYSTEM_PROMPT
    assert "backend/data/_auto/" in EXECUTION_SYSTEM_PROMPT
    assert "DATA → QUANT HANDOFF" in EXECUTION_SYSTEM_PROMPT
    assert "compact JSON `data_files` map" in EXECUTION_SYSTEM_PROMPT
    assert "not call `glob`, `ls`, or `read_file`" in EXECUTION_SYSTEM_PROMPT
    assert "REAL WAGE SOURCE FIDELITY" in EXECUTION_SYSTEM_PROMPT
    assert "Never let a nominal average-hourly-earnings series stand in" in EXECUTION_SYSTEM_PROMPT
    assert "skills/orchestrator" not in EXECUTION_SYSTEM_PROMPT
    for tool_name in ("ls", "glob", "grep", "read_file", "execute", "write_todos"):
        assert f"`{tool_name}`" in EXECUTION_SYSTEM_PROMPT


@pytest.mark.asyncio
async def test_execution_agent_hides_todo_tool_from_pipeline_agents(monkeypatch):
    captured = {}

    async def fake_get_data_engineer_subagent(**_kwargs):
        return {
            "name": "data-engineer",
            "description": "Fetch data.",
            "system_prompt": "Fetch data.",
            "tools": [],
            "model": "deepseek:deepseek-chat",
        }

    def fake_create_deep_agent(**kwargs):
        captured.update(kwargs)

        async def fake_execute(state):
            return state

        return fake_execute

    monkeypatch.setattr(orchestrator, "get_data_engineer_subagent", fake_get_data_engineer_subagent)
    monkeypatch.setattr(orchestrator, "create_deep_agent", fake_create_deep_agent)

    await orchestrator._create_execution_agent()

    assert any(
        isinstance(middleware, orchestrator.HideTodoToolMiddleware)
        for middleware in captured["middleware"]
    )
    for subagent in captured["subagents"]:
        assert any(
            isinstance(middleware, orchestrator.HideTodoToolMiddleware)
            for middleware in subagent["middleware"]
        ), subagent["name"]


def test_complete_intake_approval_message_is_frontend_visible():
    result = orchestrator.emit_approval_message_node({})

    messages = result["messages"]
    assert isinstance(messages[-1], ToolMessage)
    assert messages[-1].content == "Message recorded for the chat UI."
    assert messages[0].tool_calls[0]["name"] == "emit_chat_message"
    assert "Commence Deep Research" in messages[0].tool_calls[0]["args"]["markdown"]


def test_incomplete_intake_routes_to_intake_chat():
    assert orchestrator.route_after_evaluate({"research_summary": ""}) == "needs_more"
    assert (
        orchestrator.route_after_evaluate(
            {"research_summary": "Analyze inflation and rates."}
        )
        == "complete"
    )

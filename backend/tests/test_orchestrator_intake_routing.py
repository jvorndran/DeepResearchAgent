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
    assert "paste that `data_files` JSON object into `analysis.py` as a dictionary" in EXECUTION_SYSTEM_PROMPT
    assert "not by retyping long auto-saved filenames" in EXECUTION_SYSTEM_PROMPT
    assert "not call `glob`, `ls`, or `read_file`" in EXECUTION_SYSTEM_PROMPT
    assert "six-month unemployment forecasts" in EXECUTION_SYSTEM_PROMPT
    assert "call `direct_ols_forecast(...)` from `agents.quant_macro_stats`" in EXECUTION_SYSTEM_PROMPT
    assert "do not import `statsmodels` directly or hand-roll OLS" in EXECUTION_SYSTEM_PROMPT
    assert "REAL WAGE SOURCE FIDELITY" in EXECUTION_SYSTEM_PROMPT
    assert "Never let a nominal average-hourly-earnings series stand in" in EXECUTION_SYSTEM_PROMPT
    assert "QA REJECTION HANDOFF" in EXECUTION_SYSTEM_PROMPT
    assert "do not re-run QA and do not inspect artifacts yourself" in EXECUTION_SYSTEM_PROMPT
    assert "Do not use `general-purpose` to read `execution_summary.json`" in EXECUTION_SYSTEM_PROMPT
    assert "Treat \"data fidelity failures\"" in EXECUTION_SYSTEM_PROMPT
    assert "The writer already has tools that load the execution summary safely" in EXECUTION_SYSTEM_PROMPT
    assert "sign/direction wording" in EXECUTION_SYSTEM_PROMPT
    assert "report-vs-execution_summary contradiction fixes to `technical-writer`" in EXECUTION_SYSTEM_PROMPT
    assert "only when QA explicitly says computed artifacts are missing" in EXECUTION_SYSTEM_PROMPT
    assert "send the first recovery pass to `technical-writer`" in EXECUTION_SYSTEM_PROMPT
    assert "Do not ask `quant-developer` to patch narrative wording" in EXECUTION_SYSTEM_PROMPT
    assert "passing the exact `reason` and `required_fixes`" in EXECUTION_SYSTEM_PROMPT
    assert "REGIONAL CONSUMER-STRESS BUDGET" in EXECUTION_SYSTEM_PROMPT
    assert "exactly one batched `census_get_table` state table" in EXECUTION_SYSTEM_PROMPT
    assert "small national FRED macro set (at most 6 series" in EXECUTION_SYSTEM_PROMPT
    assert "forbid broad state-level FRED sweeps" in EXECUTION_SYSTEM_PROMPT
    assert "RECESSION WINDOW SOURCE" in EXECUTION_SYSTEM_PROMPT
    assert "FRED `USREC`" in EXECUTION_SYSTEM_PROMPT
    assert "quant-developer must not fetch recession dates itself" in EXECUTION_SYSTEM_PROMPT
    assert "FEATURE-AWARE DATA ROUTING" in EXECUTION_SYSTEM_PROMPT
    assert "World Bank `worldbank_get_indicator`" in EXECUTION_SYSTEM_PROMPT
    assert "SEC EDGAR `sec_fetch_company_facts` for AAPL and MSFT" in EXECUTION_SYSTEM_PROMPT
    assert "not to replace it with broad guessed FRED sweeps" in EXECUTION_SYSTEM_PROMPT
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


def test_execution_kickoff_message_forces_first_delegate_after_approval():
    message = orchestrator._build_execution_kickoff_message(
        {"research_summary": "Build a recession-risk indicator."}
    )

    assert "Research is approved" in message.content
    assert "make exactly two tool calls" in message.content
    assert "`emit_chat_message`" in message.content
    assert "`task`" in message.content
    assert 'subagent_type="data-engineer"' in message.content
    assert "Build a recession-risk indicator." in message.content


def test_execution_kickoff_preserves_full_user_request_for_writer_original_query():
    full_query = (
        "Assess whether the US economy is entering recession. Include base, "
        "upside, and downside scenarios with a clear regime classification."
    )
    message = orchestrator._build_execution_kickoff_message(
        {
            "research_summary": "Assess whether the US economy is entering recession.",
            "messages": [
                orchestrator.HumanMessage(
                    content=f"Job ID: job-1\n\nResearch Query: {full_query}"
                )
            ],
        }
    )

    assert "Full approved user request for `original_query`" in message.content
    assert full_query in message.content
    assert "base, upside, and downside scenarios" in message.content


def test_incomplete_intake_routes_to_intake_chat():
    assert orchestrator.route_after_evaluate({"research_summary": ""}) == "needs_more"
    assert (
        orchestrator.route_after_evaluate(
            {"research_summary": "Analyze inflation and rates."}
        )
        == "complete"
    )

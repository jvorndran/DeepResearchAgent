from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.messages import ToolMessage

from agents import orchestrator
from agents.graph_input import resolve_graph_input
from core.context import ResearchContext
from agents.orchestrator import EXECUTION_SYSTEM_PROMPT


_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_ORCHESTRATOR_SKILL_DIR = _BACKEND_ROOT / "skills" / "orchestrator"


def _orchestrator_skill(name: str) -> str:
    return (_ORCHESTRATOR_SKILL_DIR / name / "SKILL.md").read_text(encoding="utf-8")


def test_execution_prompt_forbids_startup_prose_and_filesystem_inspection():
    assert "These execution rules override generic Deep Agent guidance" in EXECUTION_SYSTEM_PROMPT
    assert "NO ASSISTANT PROSE DURING EXECUTION" in EXECUTION_SYSTEM_PROMPT
    assert "assistant message content must be empty" in EXECUTION_SYSTEM_PROMPT
    assert "delivered-summary tables" in EXECUTION_SYSTEM_PROMPT
    assert "If no workflow skill applies, make exactly two tool calls" in EXECUTION_SYSTEM_PROMPT
    assert "NO STARTUP FILESYSTEM INSPECTION" in EXECUTION_SYSTEM_PROMPT
    assert "Skill `SKILL.md` reads are allowed only" in EXECUTION_SYSTEM_PROMPT
    assert "TERMINAL APPROVAL RESPONSE" in EXECUTION_SYSTEM_PROMPT
    assert "Report approved: outputs/{job_id}/report.json" in EXECUTION_SYSTEM_PROMPT
    assert "Do not add assistant content after that tool call" in EXECUTION_SYSTEM_PROMPT
    assert "SKILL ROUTER" in EXECUTION_SYSTEM_PROMPT
    assert "technical-writer-handoff" in EXECUTION_SYSTEM_PROMPT
    assert "data-to-quant-handoff" in EXECUTION_SYSTEM_PROMPT
    assert "quality-analyst-handoff" in EXECUTION_SYSTEM_PROMPT
    assert "qa-rejection-recovery" in EXECUTION_SYSTEM_PROMPT
    assert "FMP remains disabled and unavailable" in EXECUTION_SYSTEM_PROMPT
    assert len(EXECUTION_SYSTEM_PROMPT) < 4_900
    assert "skills/orchestrator" not in EXECUTION_SYSTEM_PROMPT
    for tool_name in ("ls", "glob", "grep", "read_file", "execute", "write_todos"):
        assert f"`{tool_name}`" in EXECUTION_SYSTEM_PROMPT


def test_migrated_orchestrator_details_live_in_skills_not_resident_prompt():
    prompt = EXECUTION_SYSTEM_PROMPT
    migrated = [
        "call `plan_report_structure` first",
        "If `plan_report_structure` returns truncated-looking text",
        "Do not demand exact data filenames",
        "backend/data/_auto/",
        "compact JSON `data_files` map",
        "paste the `data_files` JSON object into `analysis.py`",
        "call `direct_ols_forecast(...)` from `agents.quant_macro_stats`",
        "Never let a nominal average-hourly-earnings series stand in",
        "Do not use `general-purpose` to read `execution_summary.json`",
        "exactly one batched `census_get_table` state table",
        "World Bank `worldbank_get_indicator`",
        "SEC EDGAR `sec_fetch_company_facts` for AAPL and MSFT",
        "`quality-analyst` must return compact JSON",
        "when rejected, `reason` and `required_fixes`",
        "If quant-developer returns `execution_summary_json`",
        "recession-window, regime, correlation, scenario, or forecast requests",
        "broad macro cycle briefs spanning macro, peers, regions, and company earnings risk",
    ]
    for detail in migrated:
        assert detail not in prompt

    assert "call `plan_report_structure` first" in _orchestrator_skill(
        "technical-writer-handoff"
    )
    assert "If `plan_report_structure` returns truncated-looking text" in _orchestrator_skill(
        "technical-writer-handoff"
    )
    assert "Do not demand exact data filenames" in _orchestrator_skill(
        "paths-artifacts-and-sources"
    )
    assert "backend/data/_auto/" in _orchestrator_skill("paths-artifacts-and-sources")
    assert "compact JSON `data_files` map" in _orchestrator_skill("data-to-quant-handoff")
    assert (
        "paste the `data_files` JSON object into `analysis.py`"
        in _orchestrator_skill("data-to-quant-handoff")
    )
    assert (
        "call `direct_ols_forecast(...)` from `agents.quant_macro_stats`"
        in _orchestrator_skill("data-to-quant-handoff")
    )
    assert "Never let a nominal average-hourly-earnings series stand in" in _orchestrator_skill(
        "labor-real-wage-workflow"
    )
    assert "Do not use `general-purpose` to read `execution_summary.json`" in _orchestrator_skill(
        "qa-rejection-recovery"
    )
    assert "exactly one batched `census_get_table` state table" in _orchestrator_skill(
        "regional-consumer-stress-workflow"
    )
    assert "World Bank `worldbank_get_indicator`" in _orchestrator_skill(
        "broad-investment-committee-workflow"
    )
    assert "SEC EDGAR `sec_fetch_company_facts` for AAPL and MSFT" in _orchestrator_skill(
        "broad-investment-committee-workflow"
    )
    assert "quality-analyst` delegation" in _orchestrator_skill("quality-analyst-handoff")
    assert "compact JSON with" in _orchestrator_skill("quality-analyst-handoff")
    assert "when rejected, `reason` and `required_fixes`" in _orchestrator_skill(
        "quality-analyst-handoff"
    )
    assert "If quant-developer returns `execution_summary_json`" in _orchestrator_skill(
        "technical-writer-handoff"
    )


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

    assert captured["skills"] == [str(_ORCHESTRATOR_SKILL_DIR)]
    assert any(
        isinstance(middleware, orchestrator.HideTodoToolMiddleware)
        for middleware in captured["middleware"]
    )
    for subagent in captured["subagents"]:
        assert any(
            isinstance(middleware, orchestrator.HideTodoToolMiddleware)
            for middleware in subagent["middleware"]
        ), subagent["name"]


def test_execution_skill_boundary_allows_only_orchestrator_skill_reads():
    import agents.orchestrator.factory as factory

    class Request:
        def __init__(self, tools):
            self.tools = tools

        def override(self, **kwargs):
            return Request(kwargs.get("tools", self.tools))

    middleware = factory.OrchestratorSkillBoundaryMiddleware()
    model_request = Request(
        [
            SimpleNamespace(name="emit_chat_message"),
            SimpleNamespace(name="task"),
            SimpleNamespace(name="read_file"),
            SimpleNamespace(name="execute"),
            SimpleNamespace(name="glob"),
        ]
    )

    filtered = middleware.wrap_model_call(model_request, lambda req: req)

    assert [tool.name for tool in filtered.tools] == [
        "emit_chat_message",
        "task",
        "read_file",
    ]

    allowed = SimpleNamespace(
        tool_call={
            "name": "read_file",
            "id": "call-skill-read",
            "args": {
                "file_path": str(
                    _ORCHESTRATOR_SKILL_DIR / "data-to-quant-handoff" / "SKILL.md"
                )
            },
        }
    )
    allowed_response = middleware.wrap_tool_call(
        allowed,
        lambda _req: SimpleNamespace(content="skill loaded", status="success"),
    )
    assert allowed_response.content == "skill loaded"

    blocked = SimpleNamespace(
        tool_call={
            "name": "read_file",
            "id": "call-artifact-read",
            "args": {
                "file_path": (
                    "/home/vorndranj/projects/DeepResearchAgent/backend/outputs/"
                    "job-1/report.json"
                )
            },
        }
    )
    blocked_response = middleware.wrap_tool_call(
        blocked,
        lambda _req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )
    assert blocked_response.tool_call_id == "call-artifact-read"
    assert blocked_response.status == "error"
    assert "may read only orchestrator skill `SKILL.md` files" in blocked_response.content


def test_complete_intake_approval_message_is_frontend_visible():
    result = orchestrator.emit_approval_message_node({})

    messages = result["messages"]
    assert isinstance(messages[-1], ToolMessage)
    assert messages[-1].content == "Message recorded for the chat UI."
    assert messages[0].tool_calls[0]["name"] == "emit_chat_message"
    assert "Commence Deep Research" in messages[0].tool_calls[0]["args"]["markdown"]


def test_execution_kickoff_message_forces_first_delegate_after_approval():
    message = orchestrator._build_execution_kickoff_message(
        {
            "research_summary": "Build a recession-risk indicator.",
            "data_toolbox": {
                "providers": ["fred"],
                "confidence": 0.9,
                "rationale": "macro route",
                "unavailable_needs": [],
                "fallback": False,
            },
        }
    )

    assert "Research is approved" in message.content
    assert "make exactly two tool calls" in message.content
    assert "`emit_chat_message`" in message.content
    assert "`task`" in message.content
    assert 'subagent_type="data-engineer"' in message.content
    assert "Build a recession-risk indicator." in message.content
    assert "Selected data providers for `data-engineer`: FRED (`fred`)." in message.content


def test_execution_kickoff_preserves_full_user_request_for_writer_original_query():
    full_query = (
        "Assess whether the US economy is entering recession. Include base, "
        "upside, and downside scenarios with a clear regime classification."
    )
    message = orchestrator._build_execution_kickoff_message(
        {
            "research_summary": "Assess whether the US economy is entering recession.",
            "data_toolbox": {
                "providers": ["fred"],
                "confidence": 0.9,
                "rationale": "macro route",
                "unavailable_needs": [],
                "fallback": False,
            },
            "messages": [
                orchestrator.HumanMessage(content=f"Job ID: job-1\n\nResearch Query: {full_query}")
            ],
        }
    )

    assert "Full approved user request for `original_query`" in message.content
    assert full_query in message.content
    assert "base, upside, and downside scenarios" in message.content


def test_incomplete_intake_routes_to_intake_chat():
    assert orchestrator.route_after_evaluate({"research_summary": ""}) == "needs_more"
    assert (
        orchestrator.route_after_evaluate({"research_summary": "Analyze inflation and rates."})
        == "complete"
    )


def test_prepare_execution_copies_data_toolbox_to_runtime_preferences():
    ctx = ResearchContext(job_id="job-prepare", preferences={})
    runtime = type("Runtime", (), {"context": ctx})()

    orchestrator.prepare_execution_node(
        {
            "data_toolbox": {
                "providers": ["sec"],
                "confidence": 0.94,
                "rationale": "company fundamentals",
                "unavailable_needs": [],
                "fallback": False,
            }
        },
        runtime=runtime,
    )

    assert ctx.preferences["data_toolbox"]["providers"] == ["sec"]
    assert ctx.preferences["data_toolbox"]["fallback"] is False


@pytest.mark.asyncio
async def test_orchestrator_graph_inserts_toolbox_and_prepare_nodes(monkeypatch):
    import agents.orchestrator.factory as factory

    async def fake_execution_agent(_state, *, runtime=None):
        return {}

    async def fake_create_execution_agent(**_kwargs):
        return fake_execution_agent

    monkeypatch.setattr(factory, "_create_execution_agent", fake_create_execution_agent)

    graph = await factory.create_orchestrator()
    graph_shape = graph.get_graph()
    node_names = set(graph_shape.nodes)
    edge_pairs = {(edge.source, edge.target) for edge in graph_shape.edges}

    assert "route_toolbox" in node_names
    assert "prepare_execution" in node_names
    assert ("route_toolbox", "emit_approval_message") in edge_pairs
    assert ("prepare_execution", "execute") in edge_pairs


@pytest.mark.asyncio
async def test_manual_approval_override_preserves_checkpointed_toolbox_line():
    class FakeState:
        next = ()
        values = {
            "messages": [
                orchestrator.HumanMessage(
                    content="Job ID: job-manual\n\nResearch Query: Analyze MSFT fundamentals"
                )
            ],
            "research_summary": "Analyze Microsoft fundamentals.",
            "data_toolbox": {
                "providers": ["sec"],
                "confidence": 0.9,
                "rationale": "company fundamentals",
                "unavailable_needs": [],
                "fallback": False,
            },
        }

    class FakeAgent:
        async def aget_state(self, _config):
            return FakeState()

    graph_input = await resolve_graph_input(
        FakeAgent(),
        {"configurable": {"thread_id": "job-manual"}},
        [
            {
                "role": "user",
                "content": "Commence Deep Research",
                "metadata": {"action": "commence_research"},
            }
        ],
    )

    assert graph_input["phase"] == "executing"
    assert "Selected data providers for `data-engineer`: SEC EDGAR (`sec`)." in (
        graph_input["messages"][0]["content"]
    )

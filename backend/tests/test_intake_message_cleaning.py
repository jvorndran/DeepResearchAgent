import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

import agents.intake as intake
from agents.intake import (
    _actionable_fred_macro_summary,
    _actionable_macro_scenario_summary,
    _clean_messages_for_eval,
    evaluate_intake_node,
    _is_actionable_fred_macro_request,
    _is_actionable_macro_scenario_request,
)


def test_clean_messages_for_eval_removes_assistant_tool_calls():
    cleaned = _clean_messages_for_eval(
        [
            HumanMessage(content="Analyze high yield spreads against bank stocks."),
            AIMessage(
                content="I can proceed with that analysis.",
                tool_calls=[
                    {
                        "name": "emit_chat_message",
                        "args": {"markdown": "I can proceed with that analysis."},
                        "id": "call_123",
                    }
                ],
            ),
            ToolMessage(content="Message recorded for the chat UI.", tool_call_id="call_123"),
        ]
    )

    assert len(cleaned) == 2
    assert isinstance(cleaned[0], HumanMessage)
    assert isinstance(cleaned[1], AIMessage)
    assert cleaned[1].content == "I can proceed with that analysis."
    assert cleaned[1].tool_calls == []


def test_clean_messages_for_eval_skips_pure_tool_call_wrappers():
    cleaned = _clean_messages_for_eval(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "emit_chat_message",
                        "args": {"markdown": "Question?"},
                        "id": "call_456",
                    }
                ],
            ),
            ToolMessage(content="Message recorded for the chat UI.", tool_call_id="call_456"),
            HumanMessage(content=[{"type": "text", "text": "Use the last 10 years."}]),
        ]
    )

    assert cleaned == [HumanMessage(content="Use the last 10 years.")]


def test_fred_macro_request_is_actionable_without_indicator_clarification():
    text = (
        "Job ID: improver-test\n\n"
        "Research Query: Are consumers under stress? Use FRED macro data to build "
        "a concise evidence-based answer."
    )

    assert _is_actionable_fred_macro_request(text)

    summary = _actionable_fred_macro_summary(text)
    assert "selecting appropriate economic indicators" in summary
    assert "Are consumers under stress?" in summary


def test_fred_shortcut_does_not_apply_to_non_fred_requests():
    assert not _is_actionable_fred_macro_request("Are consumers under stress?")


def test_macro_scenario_dashboard_request_is_actionable_without_clarification():
    text = (
        "Job ID: improver-test\n\n"
        "Research Query: Build a recession risk dashboard with base, bull, and "
        "bear scenarios. Include assumptions, trigger indicators, and "
        "confidence/uncertainty notes."
    )

    assert _is_actionable_macro_scenario_request(text)

    summary = _actionable_macro_scenario_summary(text)
    assert "available free/local data" in summary
    assert "base, bull, and bear scenario rows" in summary
    assert "confidence/uncertainty notes" in summary


def test_macro_scenario_shortcut_requires_base_bull_and_bear():
    assert not _is_actionable_macro_scenario_request(
        "Build a recession risk dashboard with scenarios."
    )


@pytest.mark.asyncio
async def test_evaluate_intake_accepts_macro_scenario_dashboard_without_model(monkeypatch):
    def fail_init_chat_model(*_args, **_kwargs):
        raise AssertionError("macro scenario shortcut should avoid evaluator model")

    monkeypatch.setattr(intake, "init_chat_model", fail_init_chat_model)

    result = await evaluate_intake_node(
        {
            "messages": [
                HumanMessage(
                    content=(
                        "Research Query: Build a recession risk dashboard with "
                        "base, bull, and bear scenarios. Include assumptions, "
                        "trigger indicators, and confidence/uncertainty notes."
                    )
                )
            ]
        }
    )

    assert "research_summary" in result
    assert "base, bull, and bear scenario rows" in result["research_summary"]

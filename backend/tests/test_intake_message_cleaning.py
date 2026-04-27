from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agents.intake import _clean_messages_for_eval


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

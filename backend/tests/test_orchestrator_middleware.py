from types import SimpleNamespace

from langchain.agents.middleware.types import ModelResponse
from langchain_core.messages import AIMessage

from agents.orchestrator import StripToolCallContentMiddleware


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

from services.stream_errors import (
    build_exception_error_event,
    client_safe_error_text,
    client_safe_tool_result_summary,
    ensure_client_safe_error_event,
    normalize_stream_error,
)

RAW_PROVIDER_ERROR = (
    "Error calling model 'gemini-3.1-pro-preview' (Too Many Requests): 429 Too Many "
    "Requests. {'message': 'Your project has exceeded its monthly spending cap. "
    "Please go to AI Studio at https://ai.studio/spend to manage your project spend cap.'}"
)


def test_exception_error_event_hides_provider_details():
    event = build_exception_error_event(
        "job_1",
        "background_research",
        RuntimeError(RAW_PROVIDER_ERROR),
    )

    assert event["type"] == "error"
    assert event["errorType"] == "rate_limit"
    assert event["retryable"] is True
    assert event["errorText"] == "The upstream provider rate-limited this request."
    assert "gemini" not in event["errorText"]
    assert "ai.studio" not in event["errorText"]
    assert "spending cap" not in event["errorText"]
    assert "job_id=" not in event["errorText"]


def test_normalize_stream_error_hides_raw_dict_message():
    event = normalize_stream_error(
        "job_1",
        "qa_stream",
        {"type": "mcp_timeout", "message": "MCP timeout: token abc123"},
    )

    assert event["errorType"] == "mcp_timeout"
    assert event["errorText"] == "A tool or data provider timed out while processing your request."
    assert "abc123" not in event["errorText"]


def test_existing_error_event_is_resanitized():
    event = ensure_client_safe_error_event(
        "job_1",
        "background_research",
        {
            "type": "error",
            "job_id": "job_1",
            "stage": "background_research",
            "errorType": "rate_limit",
            "retryable": True,
            "errorText": f"The upstream provider rate-limited this request. Upstream detail: {RAW_PROVIDER_ERROR}",
        },
    )

    assert event["errorText"] == "The upstream provider rate-limited this request."
    assert "Upstream detail" not in event["errorText"]


def test_client_safe_error_text_preserves_already_safe_detail():
    safe_detail = "The upstream provider rate-limited this request."

    assert client_safe_error_text(raw_detail=safe_detail) == safe_detail


def test_tool_result_error_summary_is_sanitized():
    summary = client_safe_tool_result_summary(
        '{"status": "error", "error": "Error calling model '
        "'gemini-3.1-pro-preview': 429 Too Many Requests. "
        'Your project has exceeded its monthly spending cap. https://ai.studio/spend"}'
    )

    assert summary == "The upstream provider rate-limited this request."
    assert "gemini" not in summary
    assert "ai.studio" not in summary


def test_successful_tool_result_summary_is_preserved():
    summary = client_safe_tool_result_summary('{"status": "success", "row_count": 42}')

    assert summary == '{"status": "success", "row_count": 42}'

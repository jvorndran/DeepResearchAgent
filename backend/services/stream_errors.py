"""Map exceptions and stream errors to client-facing SSE error payloads."""

import asyncio
import json
from typing import Any

import google.genai.errors

SAFE_DETAILS_BY_TYPE = {
    "data_provider_bad_request": (
        "The upstream data provider rejected a generated request. Retrying may succeed."
    ),
    "llm_internal": "The model provider returned an internal error while processing your request.",
    "llm_unavailable": "The model provider is temporarily unavailable.",
    "rate_limit": "The upstream provider rate-limited this request.",
    "mcp_request_failed": (
        "A tool or data provider request failed, and the agent may retry with a corrected request."
    ),
    "mcp_timeout": "A tool or data provider timed out while processing your request.",
    "timeout": "The request timed out while waiting for a response.",
    "report_not_saved": "Research finished but the report was not saved.",
    "internal_error": "The server hit an unexpected error while processing your request.",
}

RETRYABLE_ERROR_TYPES = {
    "data_provider_bad_request",
    "mcp_request_failed",
    "mcp_timeout",
    "timeout",
    "llm_internal",
    "llm_unavailable",
    "rate_limit",
}


def classify_error_message(message: str, exc: BaseException | None = None) -> tuple[str, bool, str]:
    lowered = message.lower()

    if ("fred api error (400)" in lowered and "the series does not exist" in lowered) or (
        "failed to retrieve series data" in lowered and "series does not exist" in lowered
    ):
        return (
            "data_provider_bad_request",
            True,
            SAFE_DETAILS_BY_TYPE["data_provider_bad_request"],
        )
    if isinstance(exc, google.genai.errors.ServerError) or "500 internal" in lowered:
        return (
            "llm_internal",
            True,
            SAFE_DETAILS_BY_TYPE["llm_internal"],
        )
    if "503 service unavailable" in lowered:
        return (
            "llm_unavailable",
            True,
            SAFE_DETAILS_BY_TYPE["llm_unavailable"],
        )
    if "rate limit" in lowered or "429" in lowered:
        return (
            "rate_limit",
            True,
            SAFE_DETAILS_BY_TYPE["rate_limit"],
        )
    if "mcp request '" in lowered and "failed:" in lowered:
        return (
            "mcp_request_failed",
            True,
            SAFE_DETAILS_BY_TYPE["mcp_request_failed"],
        )
    if "mcp timeout" in lowered:
        return (
            "mcp_timeout",
            True,
            SAFE_DETAILS_BY_TYPE["mcp_timeout"],
        )
    if "mcp request '" in lowered and "timeout" in lowered:
        return (
            "mcp_timeout",
            True,
            SAFE_DETAILS_BY_TYPE["mcp_timeout"],
        )
    if isinstance(exc, asyncio.TimeoutError) or "timeout" in lowered:
        return (
            "timeout",
            True,
            SAFE_DETAILS_BY_TYPE["timeout"],
        )
    return (
        "internal_error",
        False,
        SAFE_DETAILS_BY_TYPE["internal_error"],
    )


def classify_exception(exc: BaseException) -> tuple[str, bool, str]:
    return classify_error_message(str(exc), exc)


def build_error_event(
    *,
    job_id: str,
    detail: str,
    error_type: str,
    retryable: bool,
    stage: str,
) -> dict[str, Any]:
    return {
        "type": "error",
        "job_id": job_id,
        "errorType": error_type,
        "retryable": retryable,
        "stage": stage,
        "errorText": detail,
    }


def client_safe_error_text(error_type: str | None = None, raw_detail: str | None = None) -> str:
    if error_type in SAFE_DETAILS_BY_TYPE:
        return SAFE_DETAILS_BY_TYPE[error_type]
    if raw_detail in SAFE_DETAILS_BY_TYPE.values():
        return raw_detail
    return classify_error_message(raw_detail or "")[2]


def client_safe_tool_result_summary(raw_summary: Any) -> str:
    summary = str(raw_summary)
    parsed = _parse_jsonish(summary)
    if _is_error_payload(parsed):
        raw_detail = _error_payload_detail(parsed) or summary
        return client_safe_error_text(raw_detail=raw_detail)

    classified_type, _retryable, detail = classify_error_message(summary)
    if classified_type != "internal_error":
        return detail

    lowered = summary.lower()
    if any(marker in lowered for marker in ("traceback", "exception", "error calling model")):
        return SAFE_DETAILS_BY_TYPE["internal_error"]
    return summary


def _parse_jsonish(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def _is_error_payload(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    status = str(value.get("status") or value.get("type") or "").lower()
    if status == "error":
        return True
    if "error" in value and status not in {"success", "ok", "completed"}:
        return True
    return False


def _error_payload_detail(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    for key in ("message", "detail", "error"):
        detail = value.get(key)
        if detail:
            return str(detail)
    return None


def build_exception_error_event(job_id: str, stage: str, exc: BaseException) -> dict[str, Any]:
    error_type, retryable, detail = classify_exception(exc)
    return build_error_event(
        job_id=job_id,
        detail=detail,
        error_type=error_type,
        retryable=retryable,
        stage=stage,
    )


def ensure_client_safe_error_event(job_id: str, stage: str, error: Any) -> dict[str, Any]:
    if not isinstance(error, dict) or error.get("type") != "error":
        return normalize_stream_error(job_id, stage, error)

    raw_detail = str(error.get("errorText") or error.get("message") or error.get("detail") or "")
    error_type = str(error.get("errorType") or error.get("type") or "stream_error")
    classified_type, classified_retryable, classified_detail = classify_error_message(raw_detail)
    if error_type in SAFE_DETAILS_BY_TYPE:
        detail = SAFE_DETAILS_BY_TYPE[error_type]
    else:
        error_type = classified_type
        detail = classified_detail

    return build_error_event(
        job_id=str(error.get("job_id") or job_id),
        detail=detail,
        error_type=error_type,
        retryable=bool(
            error.get("retryable", classified_retryable or error_type in RETRYABLE_ERROR_TYPES)
        ),
        stage=str(error.get("stage") or stage),
    )


def normalize_stream_error(job_id: str, stage: str, error: Any) -> dict[str, Any]:
    if isinstance(error, dict):
        raw_detail = str(error.get("message") or error.get("detail") or error)
        error_type = str(error.get("type") or "stream_error")
    else:
        raw_detail = str(error)
        error_type = "stream_error"

    classified_type, classified_retryable, classified_detail = classify_error_message(raw_detail)
    if error_type in SAFE_DETAILS_BY_TYPE:
        detail = SAFE_DETAILS_BY_TYPE[error_type]
    else:
        detail = classified_detail
    if error_type == "stream_error":
        error_type = classified_type
    retryable = classified_retryable or error_type in RETRYABLE_ERROR_TYPES
    return build_error_event(
        job_id=job_id,
        detail=detail,
        error_type=error_type,
        retryable=retryable,
        stage=stage,
    )

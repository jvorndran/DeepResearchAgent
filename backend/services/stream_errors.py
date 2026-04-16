"""Map exceptions and stream errors to client-facing SSE error payloads."""

import asyncio
from typing import Any

import google.genai.errors


def classify_exception(exc: BaseException) -> tuple[str, bool, str]:
    message = str(exc)
    lowered = message.lower()

    if ("fred api error (400)" in lowered and "the series does not exist" in lowered) or (
        "failed to retrieve series data" in lowered and "series does not exist" in lowered
    ):
        return (
            "data_provider_bad_request",
            True,
            "The upstream data provider rejected a generated request. Retrying may succeed.",
        )
    if isinstance(exc, google.genai.errors.ServerError) or "500 internal" in lowered:
        return (
            "llm_internal",
            True,
            "The model provider returned an internal error while processing your request.",
        )
    if "503 service unavailable" in lowered:
        return (
            "llm_unavailable",
            True,
            "The model provider is temporarily unavailable.",
        )
    if "rate limit" in lowered or "429" in lowered:
        return (
            "rate_limit",
            True,
            "The upstream provider rate-limited this request.",
        )
    if "mcp request '" in lowered and "failed:" in lowered:
        return (
            "mcp_request_failed",
            True,
            "A tool or data provider request failed, and the agent may retry with a corrected request.",
        )
    if "mcp timeout" in lowered:
        return (
            "mcp_timeout",
            True,
            "A tool or data provider timed out while processing your request.",
        )
    if "mcp request '" in lowered and "timeout" in lowered:
        return (
            "mcp_timeout",
            True,
            "A tool or data provider timed out while processing your request.",
        )
    if isinstance(exc, asyncio.TimeoutError) or "timeout" in lowered:
        return (
            "timeout",
            True,
            "The request timed out while waiting for a response.",
        )
    return (
        "internal_error",
        False,
        "The server hit an unexpected error while processing your request.",
    )


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
        "errorText": f"{detail} [job_id={job_id}, stage={stage}, retryable={str(retryable).lower()}]",
    }


def build_exception_error_event(job_id: str, stage: str, exc: BaseException) -> dict[str, Any]:
    error_type, retryable, detail = classify_exception(exc)
    return build_error_event(
        job_id=job_id,
        detail=f"{detail} Upstream detail: {exc}",
        error_type=error_type,
        retryable=retryable,
        stage=stage,
    )


def normalize_stream_error(job_id: str, stage: str, error: Any) -> dict[str, Any]:
    if isinstance(error, dict):
        detail = str(error.get("message") or error.get("detail") or error)
        error_type = str(error.get("type") or "stream_error")
    else:
        detail = str(error)
        error_type = "stream_error"

    retryable = error_type in {
        "mcp_timeout",
        "timeout",
        "llm_internal",
        "llm_unavailable",
        "rate_limit",
    }
    return build_error_event(
        job_id=job_id,
        detail=detail,
        error_type=error_type,
        retryable=retryable,
        stage=stage,
    )

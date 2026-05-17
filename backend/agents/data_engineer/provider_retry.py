"""Retry and normalization contracts for optional public data providers."""
from __future__ import annotations

from datetime import date
from typing import Any

from mcp_clients.bls_client import BLSPublicDataError, MAX_NO_KEY_YEAR_SPAN


def _coerce_year(value: int | str | None) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text)
    except Exception as exc:
        raise BLSPublicDataError("BLS start_year and end_year must be integers.") from exc


def normalize_bls_no_key_year_window(
    start_year: int | str | None,
    end_year: int | str | None,
    *,
    current_year: int | None = None,
) -> tuple[int | None, int | None, dict[str, Any]]:
    """Return a BLS no-key safe window plus metadata for any adjustment.

    The BLS client stays strict so direct callers see exact validation errors.
    The data-engineer tool is agent-facing and may normalize optional direct
    source checks to a focused recent window, which prevents retry churn after
    partial or over-wide year requests.
    """
    requested_start = _coerce_year(start_year)
    requested_end = _coerce_year(end_year)
    if requested_start is None and requested_end is None:
        return None, None, {}

    current = int(current_year if current_year is not None else date.today().year)
    start = requested_start
    end = requested_end
    adjustments: list[str] = []

    if start is None:
        end = int(end)
        start = end - MAX_NO_KEY_YEAR_SPAN + 1
        adjustments.append("inferred_start_year")
    elif end is None:
        end = current
        adjustments.append("inferred_end_year")

    if start > end:
        raise BLSPublicDataError("BLS start_year must be less than or equal to end_year.")

    if end - start + 1 > MAX_NO_KEY_YEAR_SPAN:
        start = end - MAX_NO_KEY_YEAR_SPAN + 1
        adjustments.append("bounded_to_no_key_window")

    metadata: dict[str, Any] = {}
    if adjustments or requested_start != start or requested_end != end:
        metadata = {
            "requested_year_window": {
                "start_year": requested_start,
                "end_year": requested_end,
            },
            "applied_year_window": {
                "start_year": start,
                "end_year": end,
            },
            "window_adjustment": adjustments,
            "coverage_note": (
                "BLS no-key direct checks are limited to 10 years. The tool "
                "used the latest allowed window ending at the requested or "
                "current end year; use FRED for long-history macro coverage."
            ),
        }
    return start, end, metadata


def bls_error_response(message: str) -> dict[str, Any]:
    """Build a compact BLS tool error with retry scope."""
    normalized = message.lower()
    quota_exhausted = any(
        token in normalized
        for token in (
            "daily threshold",
            "daily query limit",
            "query limit exceeded",
            "allocated to the user",
            "registration key",
        )
    )
    parameter_correctable = any(
        token in normalized
        for token in (
            "provide both start_year and end_year",
            "limited to 10 years",
            "malformed bls series id",
            "provide at least one bls series id",
            "limited to 25 series",
        )
    )
    transient = any(
        token in normalized
        for token in ("timed out", "request failed", "rate", "limit", "too many")
    )

    if quota_exhausted:
        retryable = False
        error_type = "provider_quota_exhausted"
        hint = (
            "BLS daily no-key quota is exhausted. Do not retry BLS in this run; "
            "preserve this error in metadata.fetch_errors and continue with FRED or other public sources."
        )
    elif parameter_correctable:
        retryable = True
        error_type = "correctable_parameters"
        hint = (
            "Retry at most once with a valid BLS ID and paired start_year/end_year "
            "spanning 10 years or less. For long histories, use FRED plus one "
            "focused BLS recent-window check."
        )
    elif transient:
        retryable = True
        error_type = "transient_provider_error"
        hint = "Retry at most once after the transient BLS request failure, then record a fetch_errors caveat."
    else:
        retryable = False
        error_type = "terminal_provider_error"
        hint = (
            "Use valid BLS IDs from bls_search_known_series or report BLS unavailable; "
            "do not switch to paid providers."
        )

    return {
        "status": "error",
        "provider": "BLS Public Data",
        "error": message,
        "retryable": retryable,
        "error_type": error_type,
        "retry_scope": "corrected_parameters" if parameter_correctable else (
            "transient" if transient and not quota_exhausted else "none"
        ),
        "hint": hint,
    }


def census_error_response(message: str) -> dict[str, Any]:
    """Build a compact Census tool error with terminal malformed-payload handling."""
    normalized = message.lower()
    malformed_payload = any(
        token in normalized
        for token in (
            "not valid json",
            "response was malformed",
            "expected a two-dimensional table",
            "invalid header row",
            "row width did not match",
            "did not include any data rows",
        )
    )
    parameter_correctable = any(
        token in normalized
        for token in (
            "allowlisted",
            "unsupported census",
            "malformed census variable",
            "provide at least one census",
            "limited to 50 variables",
            "state geography does not accept",
            "county geography state filter",
            "unsupported census geography",
            "allowed geographies",
        )
    )
    transient = any(
        token in normalized
        for token in ("timed out", "request failed", "rate", "too many", "429")
    )

    if malformed_payload:
        retryable = False
        error_type = "provider_payload_unusable"
        retry_scope = "none"
        hint = (
            "Census returned an unusable payload from otherwise valid-looking parameters. "
            "Do not retry Census by narrowing variables or geographies; preserve this "
            "error in metadata.fetch_errors and continue with the rest of the data plan."
        )
    elif parameter_correctable:
        retryable = True
        error_type = "correctable_parameters"
        retry_scope = "corrected_parameters"
        hint = (
            "Retry at most once with dataset 2023/acs/acs5/profile, geography state "
            "or county, and allowlisted variables such as population, median_income, "
            "housing_units, or median_home_value."
        )
    elif transient:
        retryable = True
        error_type = "transient_provider_error"
        retry_scope = "transient"
        hint = "Retry at most once after the transient Census request failure, then record a fetch_errors caveat."
    else:
        retryable = False
        error_type = "terminal_provider_error"
        retry_scope = "none"
        hint = "Report Census unavailable instead of switching to paid providers."

    return {
        "status": "error",
        "provider": "Census Data API",
        "error": message,
        "retryable": retryable,
        "error_type": error_type,
        "retry_scope": retry_scope,
        "hint": hint,
    }

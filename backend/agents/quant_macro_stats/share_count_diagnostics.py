"""Shared helpers for raw SEC share-count comparability diagnostics."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any


SHARE_COUNT_STATUS_SPLIT_AFFECTED = "split_affected"
SHARE_COUNT_STATUS_COMPARABLE = "comparable"
SHARE_COUNT_COMPARABILITY_UNCOMPARABLE = "raw_full_series_uncomparable"
SHARE_COUNT_COMPARABILITY_COMPARABLE = "raw_full_series_comparable"
SHARE_COUNT_TREND_UNCOMPARABLE = "raw_full_series_uncomparable"
SHARE_COUNT_SPLIT_LIMITATION = (
    "Raw SEC share counts have large adjacent discontinuities consistent with "
    "stock splits or other share-count basis changes; do not use the full raw "
    "series for buyback or dilution claims without split-adjusted evidence."
)

_RAW_SHARE_SOURCE_SERIES = {
    "share",
    "shares",
    "shares_b",
    "share_count",
    "share_count_b",
    "shares_outstanding",
    "diluted_shares",
    "weighted_average_shares",
}


def share_count_trend_from_change_pct(change_pct: float | None) -> str | None:
    """Return a conservative share-count direction label from a percent change."""

    if change_pct is None:
        return None
    if change_pct < -1.0:
        return "buyback"
    if change_pct > 1.0:
        return "dilution"
    return "stable"


def share_count_diagnostics_by_ticker(value: Any) -> dict[str, dict[str, Any]]:
    """Normalize share-count diagnostics to a ticker-keyed mapping."""

    diagnostics: dict[str, dict[str, Any]] = {}
    if isinstance(value, Mapping):
        if _diagnostic_has_ticker(value):
            ticker = _ticker_from_diagnostic(value)
            if ticker:
                diagnostics[ticker] = dict(value)
        else:
            for key, child in value.items():
                if not isinstance(child, Mapping):
                    continue
                ticker = _ticker_from_diagnostic(child) or str(key).upper()
                if ticker:
                    diagnostics[ticker] = dict(child)
    elif isinstance(value, list):
        for child in value:
            if not isinstance(child, Mapping):
                continue
            ticker = _ticker_from_diagnostic(child)
            if ticker:
                diagnostics[ticker] = dict(child)
    return diagnostics


def split_affected_share_count_diagnostics(value: Any) -> dict[str, dict[str, Any]]:
    """Return only diagnostics whose raw full-window share series is unsafe."""

    return {
        ticker: diagnostic
        for ticker, diagnostic in share_count_diagnostics_by_ticker(value).items()
        if share_count_diagnostic_is_split_affected(diagnostic)
    }


def share_count_diagnostic_is_split_affected(diagnostic: Mapping[str, Any]) -> bool:
    """Whether a diagnostic marks raw full-window share-counts uncomparable."""

    status = str(diagnostic.get("status") or "").strip().lower()
    comparability = str(diagnostic.get("comparability") or "").strip().lower()
    discontinuities = diagnostic.get("discontinuities")
    return (
        status == SHARE_COUNT_STATUS_SPLIT_AFFECTED
        or comparability == SHARE_COUNT_COMPARABILITY_UNCOMPARABLE
        or (isinstance(discontinuities, list) and bool(discontinuities))
    )


def source_series_uses_raw_shares(value: Any) -> bool:
    """Return true when chart provenance cites raw share-count source series."""

    return any(
        _source_series_token_is_raw_share(token)
        for token in _source_series_tokens(value)
    )


def append_share_count_limitation(existing: Any) -> list[str]:
    """Return normalized limitations with the share-count warning included once."""

    limitations: list[str] = []
    if isinstance(existing, str):
        limitations = [existing]
    elif isinstance(existing, Iterable) and not isinstance(
        existing, (Mapping, bytes, bytearray)
    ):
        limitations = [str(item) for item in existing if str(item).strip()]
    elif existing is not None:
        limitations = [str(existing)]

    if SHARE_COUNT_SPLIT_LIMITATION not in limitations:
        limitations.append(SHARE_COUNT_SPLIT_LIMITATION)
    return limitations


def _diagnostic_has_ticker(value: Mapping[str, Any]) -> bool:
    return bool(str(value.get("ticker") or "").strip())


def _ticker_from_diagnostic(value: Mapping[str, Any]) -> str:
    return str(value.get("ticker") or "").strip().upper()


def _source_series_tokens(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, Mapping):
        tokens: list[str] = []
        for key, child in value.items():
            tokens.append(str(key))
            tokens.extend(_source_series_tokens(child))
        return tokens
    if isinstance(value, (str, Path)):
        return [part.strip() for part in str(value).split(",") if part.strip()]
    if isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray)):
        tokens = []
        for item in value:
            tokens.extend(_source_series_tokens(item))
        return tokens
    return [str(value)]


def _source_series_token_is_raw_share(value: str) -> bool:
    token = value.strip().lower().replace("-", "_").replace(" ", "_")
    if token in _RAW_SHARE_SOURCE_SERIES:
        return True
    suffix = token.rsplit(".", maxsplit=1)[-1]
    return suffix in _RAW_SHARE_SOURCE_SERIES

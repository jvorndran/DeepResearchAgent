"""Execution-summary validation and output-contract normalization."""

import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable

from .._utils import finite_number as _finite
from ..company.sec_company_facts_evidence import (
    is_sec_company_facts_file,
    sec_company_facts_evidence,
)
from ..share_count_diagnostics import (
    SHARE_COUNT_COMPARABILITY_UNCOMPARABLE,
    SHARE_COUNT_TREND_UNCOMPARABLE,
    split_affected_share_count_diagnostics,
)
from .current_scalar_aliases import (
    expand_current_scalar_aliases as _expand_current_scalar_aliases,
)
from .numeric_fact_contracts import normalize_numeric_facts, normalize_unit
from .source_unit_fidelity import normalize_source_unit_metadata


_COMPACT_HANDOFF_KEYS = (
    "historical_window_coverage",
    "analog_similarity_ranking",
    "analog_profile_rows",
    "forecast_rows",
    "forecast_table",
    "walk_forward_backtest_rows",
    "model_validation_rows",
    "model_comparison_by_horizon",
    "model_comparison_rows",
    "historical_failure_episodes",
    "predictor_contributions",
    "forecast_band_rows",
    "company_context_status",
    "sec_company_fundamentals",
    "event_backtest_metrics",
    "lead_time_rows",
    "signal_score_rows",
    "signal_event_rows",
    "signal_false_positive_windows",
    "signal_validation_metrics",
    "latest_signal_observation",
    "current_signal_facts",
    "signal_design",
    "composite_current_row",
    "composite_score_rows",
    "composite_validation_metrics",
    "feature_coverage",
    "current_regime_row",
    "regime_evidence_rows",
    "regime_history_rows",
    "regime_analog_rows",
    "missing_indicator_rows",
    "scenario_score_rows",
    "replay_rows",
    "latest_fundamentals",
    "company_history_rows",
    "sec_fact_provenance",
    "trend_diagnostics",
    "share_count_diagnostics",
    "macro_overlay",
    "company_macro_sensitivity",
    "source_coverage",
    "requested_geography_coverage",
    "source_snapshots",
    "source_unit_metadata",
    "unit_comparisons",
    "source_unit_errors",
    "numeric_facts",
    "chart_provenance",
    "generated_by",
    "chart_normalization_issues",
    "chart_source_table_validation",
    "chart_render_table_validation",
    "chart_projection_transforms",
)

_COMMON_VALIDATION_CONTAINER_KEYS = (
    "forecast_diagnostics",
    "statistical_summary",
    "forecast",
    "recession_risk",
)

_OBSOLETE_PRESERVATION_KEYS = frozenset(
    {
        "preserve_report_aligned_charts",
        "supplemental_validation_only",
    }
)

_SEC_COMPANY_EVIDENCE_FIELD_MAP = {
    "history_rows": "company_history_rows",
    "latest_fundamentals": "latest_fundamentals",
    "sec_fact_provenance": "sec_fact_provenance",
    "trend_diagnostics": "trend_diagnostics",
    "share_count_diagnostics": "share_count_diagnostics",
    "macro_overlay": "macro_overlay",
    "company_macro_sensitivity": "company_macro_sensitivity",
    "company_context_status": "company_context_status",
}
_NUMERIC_FACT_TEXT_FIELDS = ("id", "label", "display_value", "unit", "source_key")
_NUMERIC_FACT_FINITE_FIELDS = ("raw_value", "tolerance")
_CURRENT_SCALAR_FACT_CONTAINERS = ("statistical_summary",)
_CURRENT_SCALAR_DATE_FIELDS = ("latest_date",)
_CURRENT_SCALAR_NESTED_MAX_DEPTH = 4
_CURRENT_SCALAR_TEMPORAL_TOKENS = frozenset(
    {
        "current",
        "latest",
        "last",
        "now",
        "today",
        "recent",
        "asof",
        "as",
        "of",
    }
)
_CURRENT_SCALAR_EXPLICIT_TEMPORAL_TOKENS = _CURRENT_SCALAR_TEMPORAL_TOKENS - {
    "as",
    "of",
}
_CURRENT_SCALAR_GENERIC_TOKENS = _CURRENT_SCALAR_TEMPORAL_TOKENS | frozenset(
    {
        "value",
        "level",
        "rate",
        "pct",
        "percent",
        "percentage",
        "point",
        "points",
    }
)
_CURRENT_SCALAR_STRUCTURAL_PATH_TOKENS = frozenset({"all", "values"})
_CURRENT_SCALAR_IDENTITY_STOP_TOKENS = _CURRENT_SCALAR_GENERIC_TOKENS | frozenset(
    {
        "avg",
        "average",
        "billion",
        "billions",
        "bps",
        "chg",
        "change",
        "changed",
        "delta",
        "dollar",
        "dollars",
        "gap",
        "grow",
        "growth",
        "index",
        "indexed",
        "million",
        "millions",
        "mom",
        "nominal",
        "pp",
        "qoq",
        "ratio",
        "real",
        "rolling",
        "spread",
        "thousand",
        "thousands",
        "usd",
        "window",
        "wow",
        "yoy",
    }
)
_CURRENT_SCALAR_WINDOW_TOKEN_RE = re.compile(
    r"^\d+(?:mo|m|month|months|q|quarter|quarters|yr|year|years)$"
)
_CURRENT_SCALAR_WINDOW_PHRASE_RE = re.compile(
    r"\b(\d+)\s*[-_]?\s*(mo|m|month|months|q|quarter|quarters|yr|year|years)\b"
)
_CURRENT_SCALAR_FIELD_RE = re.compile(
    r"(?:^|_)(?:current|latest|last|recent|now|today)(?:_|$)|"
    r"(?:^|_)(?:yoy|qoq|mom|wow|year_over_year|month_over_month)(?:_|$)|"
    r"(?:^|_)\d+(?:mo|m|month|months|q|quarter|quarters|yr|year|years)(?:_|$)|"
    r"(?:^|_)(?:rolling|window|average|avg)(?:_|$)"
)
_DERIVED_CURRENT_SCALAR_FIELD_RE = re.compile(
    r"(?:^|_)(?:yoy|qoq|mom|wow|chg|change|changed|growth|delta|spread|gap|"
    r"ratio|real|avg|average|rolling|window|sahm|curve|indexed|index)(?:_|$)|"
    r"(?:^|_)\d+(?:mo|m|month|months|q|quarter|quarters|yr|year|years)(?:_|$)"
)
_UNAVAILABLE_SOURCE_STATUSES = frozenset(
    {
        "failed",
        "failure",
        "error",
        "missing",
        "no_data",
        "not_available",
        "not_covered",
        "not_fetched",
        "unavailable",
        "insufficient",
    }
)
_NESTED_HISTORICAL_SCALAR_TOKENS = frozenset(
    {
        "baseline",
        "covid",
        "historical",
        "history",
        "high",
        "low",
        "pandemic",
        "peak",
        "pre",
        "precovid",
        "recovery",
        "trough",
    }
)
_NESTED_SHARE_COUNT_DIAGNOSTIC_TOKENS = frozenset(
    {
        "comparability",
        "comparable",
    }
)
_CURRENT_SCALAR_SOURCE_DESCRIPTOR_TOKENS = {
    "civpart": {"labor", "force"},
    "participation": {"labor", "force"},
    "jtsjol": {"job", "jobs"},
    "opening": {"job", "jobs"},
    "openings": {"job", "jobs"},
}
_CURRENT_SCALAR_REQUIRED_MODIFIER_TOKENS = frozenset(
    {
        "average",
        "change",
        "delta",
        "gap",
        "growth",
        "mom",
        "qoq",
        "ratio",
        "real",
        "rolling",
        "spread",
        "window",
        "wow",
        "yoy",
    }
)
_CURRENT_SCALAR_MODIFIER_TOKEN_ALIASES = {
    "avg": "average",
    "chg": "change",
    "changed": "change",
    "grow": "growth",
}
_CURRENT_SIGNAL_REQUIRED_TEXT_FIELDS = (
    "signal_id",
    "direction",
    "as_of_date",
    "source_key",
    "chart_id",
    "data_key",
)
_CURRENT_SIGNAL_FINITE_FIELDS = ("value", "threshold", "threshold_distance")
_DURATION_FACT_UNITS = {"days", "weeks", "months"}
_CURRENT_STATE_DURATION_ROLE = "current_state_duration"
_HISTORICAL_DURATION_ROLE = "historical_duration"
_DURATION_TOKEN_STOPWORDS = frozenset(
    {
        "day",
        "days",
        "duration",
        "episode",
        "episodes",
        "month",
        "months",
        "period",
        "periods",
        "week",
        "weeks",
    }
)
_HORIZON_DURATION_TOKENS = frozenset({"horizon"})
_ELAPSED_SINCE_REFERENCE_TOKENS = frozenset({"last", "previous", "prior"})
_ELAPSED_SINCE_CURRENT_DURATION_TOKENS = frozenset(
    {
        "active",
        "began",
        "begin",
        "beginning",
        "begun",
        "current",
        "onset",
        "start",
        "started",
        "starts",
        "still",
    }
)
_EPISODE_STATE_TOKENS = frozenset(
    {
        "invert",
        "inverted",
        "inversion",
        "recession",
        "recessionary",
        "sahm",
        "usrec",
    }
)
_EPISODE_TOKEN_ALIASES = {
    "invert": {"inversion", "inverted"},
    "inverted": {"invert", "inversion"},
    "inversion": {"invert", "inverted"},
    "recession": {"recessionary", "usrec"},
    "recessionary": {"recession", "usrec"},
    "usrec": {"recession", "recessionary"},
}


def normalize_quant_execution_summary(execution_summary: dict[str, Any]) -> dict[str, Any]:
    """Return a normalized execution summary using the quant output contract."""

    if not isinstance(execution_summary, dict):
        raise ValueError("execution_summary must be a JSON object")
    summary = deepcopy(execution_summary)
    for rule in _SUMMARY_NORMALIZATION_RULES:
        rule(summary)
    return summary


def build_quant_output_handoff(
    summary: dict[str, Any],
    *,
    charts_json: str,
    execution_summary_json: str,
    evidence_bundle_json: str,
    chart_ids: list[str],
    dropped_chart_ids: list[str],
    statistical_summary_excerpt: str | None = None,
) -> dict[str, Any]:
    """Build the compact writer/QA handoff from normalized summary fields."""

    excerpt = statistical_summary_excerpt
    if excerpt is None:
        excerpt = str(summary.get("statistical_summary", ""))[:600]

    handoff: dict[str, Any] = {
        "charts_json": charts_json,
        "execution_summary_json": execution_summary_json,
        "evidence_bundle_json": evidence_bundle_json,
        "chart_ids": chart_ids,
        "dropped_chart_ids": dropped_chart_ids,
        "statistical_summary_excerpt": str(excerpt)[:600],
    }
    for key in _COMPACT_HANDOFF_KEYS:
        if key in summary:
            handoff[key] = summary[key]
    return handoff


def _validation_source_payloads(summary: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    direct_nested = [
        value
        for key in _COMMON_VALIDATION_CONTAINER_KEYS
        if isinstance((value := summary.get(key)), dict)
    ]
    return tuple(_iter_nested_mappings(*direct_nested))


def _drop_obsolete_preservation_flags(summary: dict[str, Any]) -> None:
    """Remove removed output-preservation controls from saved summaries."""

    for key in _OBSOLETE_PRESERVATION_KEYS:
        summary.pop(key, None)


def _preserve_sec_company_facts_contract(summary: dict[str, Any]) -> None:
    """Attach helper-authored SEC company evidence when SEC CSVs are present."""

    sec_files = _sec_company_data_files(summary)
    if not sec_files:
        return

    try:
        evidence = sec_company_facts_evidence(
            sec_files,
            query=_sec_company_query_context(summary),
        )
    except Exception as exc:
        raise ValueError(
            "SEC company-facts files are present in execution_summary.json, "
            "but sec_company_facts_evidence(...) could not build reusable "
            f"helper evidence: {exc}"
        ) from exc

    if not _has_complete_sec_company_evidence(evidence):
        detail = _sec_company_evidence_error_detail(evidence)
        raise ValueError(
            "SEC company-facts files are present in execution_summary.json, "
            "but reusable helper evidence was not produced. Call "
            "sec_company_facts_evidence(data_files, query=...) from analysis.py "
            "or provide valid SEC company-facts CSV inputs before "
            f"save_quant_outputs(...).{detail}"
        )

    for evidence_key, summary_key in _SEC_COMPANY_EVIDENCE_FIELD_MAP.items():
        value = evidence.get(evidence_key)
        if _is_non_empty_contract_value(value):
            summary[summary_key] = value

    _merge_sec_company_source_coverage(summary, evidence.get("source_coverage"))
    _merge_sec_company_source_unit_metadata(summary, evidence.get("source_unit_metadata"))
    _merge_sec_company_methods(summary, evidence.get("methods_used"))
    _merge_sec_company_limitations(summary, evidence.get("limitations"))
    _replace_sec_company_numeric_facts(
        summary,
        evidence.get("numeric_facts"),
        sec_source_refs=_sec_company_source_references(summary),
    )


def _sec_company_data_files(summary: dict[str, Any]) -> dict[str, str]:
    data_files: dict[str, str] = {}
    seen_paths: set[str] = set()
    for key, path in _iter_data_file_items(summary):
        key_text = str(key)
        path_text = str(path)
        if not is_sec_company_facts_file(key_text, path_text):
            continue
        if path_text in seen_paths:
            continue
        seen_paths.add(path_text)
        if key_text in data_files and data_files[key_text] != path_text:
            key_text = _unique_data_file_key(data_files, key_text, path_text)
        data_files[key_text] = path_text
    return data_files


def _iter_data_file_items(summary: dict[str, Any]) -> Iterable[tuple[str, Any]]:
    for container_key in ("source_files", "data_files"):
        container = summary.get(container_key)
        if isinstance(container, dict):
            yield from container.items()

    manifest = summary.get("quant_input_manifest")
    if isinstance(manifest, dict):
        data_files = manifest.get("data_files")
        if isinstance(data_files, dict):
            yield from data_files.items()


def _unique_data_file_key(
    data_files: dict[str, str],
    key: str,
    path: str,
) -> str:
    stem = Path(path).stem or key or "sec_company_facts"
    candidate = stem
    suffix = 2
    while candidate in data_files:
        candidate = f"{stem}_{suffix}"
        suffix += 1
    return candidate


def _sec_company_query_context(summary: dict[str, Any]) -> str | None:
    parts = [
        str(value).strip()
        for key in ("query", "original_query", "title", "description")
        if (value := summary.get(key))
    ]
    return "\n".join(part for part in parts if part) or None


def _has_complete_sec_company_evidence(evidence: Any) -> bool:
    if not isinstance(evidence, dict):
        return False
    latest = evidence.get("latest_fundamentals")
    if not isinstance(latest, dict) or not latest:
        return False
    source_coverage = evidence.get("source_coverage")
    if not isinstance(source_coverage, dict):
        return False
    sec_coverage = source_coverage.get("sec_company_facts")
    if not isinstance(sec_coverage, dict) or sec_coverage.get("status") != "covered":
        return False
    numeric_facts = evidence.get("numeric_facts")
    return isinstance(numeric_facts, list) and any(
        _is_sec_company_helper_fact(fact) for fact in numeric_facts
    )


def _sec_company_evidence_error_detail(evidence: Any) -> str:
    if not isinstance(evidence, dict):
        return ""
    errors = evidence.get("source_errors")
    if isinstance(errors, list) and errors:
        first = errors[0]
        if isinstance(first, dict) and first.get("error"):
            return f" First SEC source error: {first.get('error')}"
    return ""


def _merge_sec_company_source_coverage(
    summary: dict[str, Any],
    helper_source_coverage: Any,
) -> None:
    if not isinstance(helper_source_coverage, dict):
        return
    source_coverage = summary.get("source_coverage")
    if not isinstance(source_coverage, dict):
        source_coverage = {}
    else:
        source_coverage = dict(source_coverage)
    source_coverage.update(helper_source_coverage)
    summary["source_coverage"] = source_coverage


def _merge_sec_company_source_unit_metadata(
    summary: dict[str, Any],
    helper_source_unit_metadata: Any,
) -> None:
    helper_records = normalize_source_unit_metadata(helper_source_unit_metadata)
    if not helper_records:
        return

    records = normalize_source_unit_metadata(summary.get("source_unit_metadata"))
    by_identity = {
        _source_unit_metadata_identity(record): record
        for record in records
        if _source_unit_metadata_identity(record)
    }
    for record in helper_records:
        identity = _source_unit_metadata_identity(record)
        if identity:
            by_identity[identity] = record
    summary["source_unit_metadata"] = list(by_identity.values())


def _source_unit_metadata_identity(record: dict[str, Any]) -> str:
    for key in ("source_key", "series_id", "concept_id", "source_file", "title"):
        value = record.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _merge_sec_company_methods(summary: dict[str, Any], helper_methods: Any) -> None:
    if isinstance(helper_methods, str):
        helper_methods = [helper_methods]
    if not isinstance(helper_methods, list):
        return

    methods = summary.get("methods_used")
    if isinstance(methods, str):
        methods = [methods]
    elif isinstance(methods, list):
        methods = list(methods)
    else:
        methods = []

    for method in helper_methods:
        if isinstance(method, str) and method not in methods:
            methods.append(method)
    if methods:
        summary["methods_used"] = methods


def _merge_sec_company_limitations(
    summary: dict[str, Any],
    helper_limitations: Any,
) -> None:
    if not isinstance(helper_limitations, list) or not helper_limitations:
        return

    limitations = summary.get("limitations")
    if isinstance(limitations, dict):
        merged = dict(limitations)
        merged["sec_company_facts"] = helper_limitations
        summary["limitations"] = merged
        return

    if isinstance(limitations, list):
        merged = list(limitations)
    elif limitations:
        merged = [limitations]
    else:
        merged = []

    for limitation in helper_limitations:
        if limitation not in merged:
            merged.append(limitation)
    summary["limitations"] = merged


def _replace_sec_company_numeric_facts(
    summary: dict[str, Any],
    helper_numeric_facts: Any,
    *,
    sec_source_refs: set[str],
) -> None:
    helper_facts: list[dict[str, Any]] = []
    if isinstance(helper_numeric_facts, list):
        helper_facts = [
            fact
            for fact in helper_numeric_facts
            if isinstance(fact, dict) and _is_sec_company_helper_fact(fact)
        ]
    if not helper_facts:
        return

    existing_facts = summary.get("numeric_facts")
    preserved_facts: list[Any] = []
    if isinstance(existing_facts, list):
        preserved_facts = [
            fact
            for fact in existing_facts
            if not _is_sec_company_numeric_fact(fact, sec_source_refs=sec_source_refs)
        ]
    summary["numeric_facts"] = preserved_facts + helper_facts


def _sec_company_source_references(summary: dict[str, Any]) -> set[str]:
    refs: set[str] = set()
    for key, path in _iter_data_file_items(summary):
        key_text = str(key)
        path_text = str(path)
        if not is_sec_company_facts_file(key_text, path_text):
            continue
        for value in (key, path):
            text = str(value).strip()
            if text:
                refs.add(text)
        path_obj = Path(path_text)
        for value in (path_obj.name, path_obj.stem):
            if value:
                refs.add(value)
    return refs


def _is_sec_company_helper_fact(fact: Any) -> bool:
    if not isinstance(fact, dict):
        return False
    fact_id = str(fact.get("id") or "")
    source_key = str(fact.get("source_key") or "")
    return fact_id.startswith("sec_company_facts.") and source_key.startswith(
        "sec_company_facts.latest_fundamentals."
    )


def _is_sec_company_numeric_fact(
    fact: Any,
    *,
    sec_source_refs: set[str],
) -> bool:
    if not isinstance(fact, dict):
        return False
    fact_id = str(fact.get("id") or "")
    source_key = str(fact.get("source_key") or "")
    return (
        fact_id.startswith("sec_company_facts.")
        or source_key.startswith("sec_company_facts")
        or source_key in sec_source_refs
    )


def _is_non_empty_contract_value(value: Any) -> bool:
    if isinstance(value, (dict, list)):
        return bool(value)
    return value is not None and value != ""


def _sanitize_split_affected_share_trends(summary: dict[str, Any]) -> None:
    """Remove unsafe full-window share trend labels for split-affected raw series."""

    diagnostics = split_affected_share_count_diagnostics(
        summary.get("share_count_diagnostics")
    )
    if not diagnostics:
        return

    stats = summary.get("statistical_summary")
    if not isinstance(stats, dict):
        return

    for ticker, diagnostic in diagnostics.items():
        for target in _statistical_summary_share_targets(stats, ticker):
            if "shares_trend" not in target:
                continue
            target["shares_trend"] = SHARE_COUNT_TREND_UNCOMPARABLE
            target["shares_trend_raw_sec_comparability"] = (
                SHARE_COUNT_COMPARABILITY_UNCOMPARABLE
            )
            if diagnostic.get("latest_comparable_trend") is not None:
                target["shares_latest_comparable_trend"] = diagnostic.get(
                    "latest_comparable_trend"
                )
            if diagnostic.get("latest_comparable_change_pct") is not None:
                target["shares_latest_comparable_change_pct"] = diagnostic.get(
                    "latest_comparable_change_pct"
                )
            if diagnostic.get("limitation"):
                target["shares_trend_limitation"] = diagnostic.get("limitation")


def _statistical_summary_share_targets(
    stats: dict[str, Any],
    ticker: str,
) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    ticker_key = str(ticker).upper()
    direct = stats.get(ticker_key)
    if isinstance(direct, dict):
        targets.append(direct)

    for value in stats.values():
        if not isinstance(value, dict) or value in targets:
            continue
        if str(value.get("ticker") or "").strip().upper() == ticker_key:
            targets.append(value)
    return targets


def _collect_validation_methods(summary: dict[str, Any]) -> None:
    nested = _validation_source_payloads(summary)
    methods = summary.setdefault("methods_used", [])
    if isinstance(methods, str):
        methods = [methods]
        summary["methods_used"] = methods
    if not isinstance(methods, list):
        return

    for payload in nested:
        payload_methods = payload.get("methods_used") if isinstance(payload, dict) else None
        if isinstance(payload_methods, str):
            payload_methods = [payload_methods]
        if isinstance(payload_methods, list):
            for method in payload_methods:
                if isinstance(method, str) and method not in methods:
                    methods.append(method)


def _non_empty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_current_scalar_fact_slot(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    return value is None or _finite(value) is not None


def _semantic_tokens(*values: Any) -> tuple[str, ...]:
    tokens: list[str] = []
    for value in values:
        text = str(value or "").lower()
        for token in re.split(r"[^a-z0-9]+", text):
            if token:
                tokens.append(token)
        for match in _CURRENT_SCALAR_WINDOW_PHRASE_RE.finditer(text):
            amount, unit = match.groups()
            if unit in {"mo", "m", "month", "months"}:
                tokens.append(f"{amount}mo")
            elif unit in {"q", "quarter", "quarters"}:
                tokens.append(f"{amount}q")
            else:
                tokens.append(f"{amount}yr")
    return tuple(tokens)


def _field_core_tokens(field: str) -> set[str]:
    return _expand_current_scalar_aliases({
        token
        for token in _semantic_tokens(field)
        if token not in _CURRENT_SCALAR_GENERIC_TOKENS
    })


def _current_scalar_identity_tokens(*values: Any) -> set[str]:
    return _expand_current_scalar_aliases({
        token
        for token in _semantic_tokens(*values)
        if token not in _CURRENT_SCALAR_IDENTITY_STOP_TOKENS
        and not _CURRENT_SCALAR_WINDOW_TOKEN_RE.fullmatch(token)
    })


def _current_scalar_modifier_tokens(*values: Any) -> set[str]:
    modifiers: set[str] = set()
    for token in _semantic_tokens(*values):
        canonical = _CURRENT_SCALAR_MODIFIER_TOKEN_ALIASES.get(token, token)
        if (
            canonical in _CURRENT_SCALAR_REQUIRED_MODIFIER_TOKENS
            or _CURRENT_SCALAR_WINDOW_TOKEN_RE.fullmatch(canonical)
        ):
            modifiers.add(canonical)
    return modifiers


def current_scalar_semantic_tokens(*values: Any) -> set[str]:
    """Return the semantic token aliases used for current-scalar matching."""

    return _expand_current_scalar_aliases({
        token for token in _semantic_tokens(*values) if token
    })


def _current_scalar_field_tokens_match_fact(
    field_tokens: set[str],
    fact_tokens: set[str],
) -> bool:
    if not field_tokens or not fact_tokens:
        return False
    if field_tokens <= fact_tokens:
        return True
    matched_tokens = field_tokens & fact_tokens
    if not matched_tokens:
        return False
    allowed_descriptors: set[str] = set()
    for token in matched_tokens:
        allowed_descriptors.update(_CURRENT_SCALAR_SOURCE_DESCRIPTOR_TOKENS.get(token, ()))
    return field_tokens - fact_tokens <= allowed_descriptors


def _current_scalar_fact_covers_field_modifiers(
    *,
    field: str,
    fact_values: Iterable[Any],
) -> bool:
    field_modifiers = _current_scalar_modifier_tokens(field)
    if not field_modifiers:
        return True
    fact_modifiers = _current_scalar_modifier_tokens(*fact_values)
    return field_modifiers <= fact_modifiers


def _is_current_scalar_field_name(field: str, container: dict[str, Any]) -> bool:
    normalized = "_".join(_semantic_tokens(field))
    if not normalized:
        return False
    if _CURRENT_SCALAR_FIELD_RE.search(normalized):
        return True
    if normalized.endswith("_value"):
        base = normalized[: -len("_value")]
        normalized_siblings = {"_".join(_semantic_tokens(sibling)) for sibling in container}
        return any(
            sibling in normalized_siblings
            or any(
                candidate.startswith(f"{base}_") and candidate.endswith(sibling_suffix)
                for candidate in normalized_siblings
            )
            for sibling, sibling_suffix in (
                (f"{base}_status", "_status"),
                (f"{base}_triggered", "_triggered"),
                (f"{base}_state", "_state"),
            )
        )
    return False


def _is_derived_current_scalar_field(field: str) -> bool:
    normalized = "_".join(_semantic_tokens(_current_scalar_fact_match_field(field)))
    return bool(_DERIVED_CURRENT_SCALAR_FIELD_RE.search(normalized))


def _current_scalar_fact_match_field(field: str) -> str:
    """Return the field identity used to match a current scalar to facts."""

    path_parts = tuple(part for part in str(field).split(".") if part)
    if not path_parts:
        return field
    leaf = path_parts[-1]
    if _current_scalar_identity_tokens(leaf):
        return leaf
    for parent in reversed(path_parts[:-1]):
        parent_tokens = (
            _current_scalar_identity_tokens(parent)
            - _CURRENT_SCALAR_STRUCTURAL_PATH_TOKENS
        )
        if parent_tokens:
            return f"{parent}.{leaf}"
    return field


def _is_historical_nested_current_scalar_path(path_parts: tuple[str, ...]) -> bool:
    if len(path_parts) <= 1:
        return False
    tokens = set(_semantic_tokens(*path_parts))
    if tokens & _CURRENT_SCALAR_EXPLICIT_TEMPORAL_TOKENS:
        return False
    if tokens & _NESTED_HISTORICAL_SCALAR_TOKENS:
        return True
    return any(re.fullmatch(r"(?:19|20)\d{2}", token) for token in tokens)


def _is_nested_share_count_diagnostic_scalar_path(path_parts: tuple[str, ...]) -> bool:
    if len(path_parts) <= 1:
        return False
    tokens = set(_semantic_tokens(*path_parts))
    return bool(
        "shares" in tokens and tokens & _NESTED_SHARE_COUNT_DIAGNOSTIC_TOKENS
    )


def _collect_current_scalar_fact_slots(
    payload: dict[str, Any],
    *,
    path: tuple[str, ...] = (),
    slots: dict[str, Any],
    depth: int = 0,
) -> None:
    if depth > _CURRENT_SCALAR_NESTED_MAX_DEPTH:
        return

    has_current_date = any(
        payload.get(date_field) is not None for date_field in _CURRENT_SCALAR_DATE_FIELDS
    )
    for field, field_value in payload.items():
        field_name = str(field)
        if field_name in _CURRENT_SCALAR_DATE_FIELDS:
            continue
        if isinstance(field_value, dict):
            _collect_current_scalar_fact_slots(
                field_value,
                path=(*path, field_name),
                slots=slots,
                depth=depth + 1,
            )
            continue
        if not _is_current_scalar_fact_slot(field_value):
            continue

        slot_path = (*path, field_name)
        if _is_historical_nested_current_scalar_path(slot_path):
            continue
        if _is_nested_share_count_diagnostic_scalar_path(slot_path):
            continue
        if has_current_date or _is_current_scalar_field_name(field_name, payload):
            slots[".".join(slot_path)] = field_value


def _current_scalar_fact_slots(summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    containers: dict[str, dict[str, Any]] = {}
    for key in _CURRENT_SCALAR_FACT_CONTAINERS:
        value = summary.get(key)
        if not isinstance(value, dict):
            continue
        scalar_fact_slots: dict[str, Any] = {}
        _collect_current_scalar_fact_slots(value, slots=scalar_fact_slots)
        if scalar_fact_slots:
            containers[key] = scalar_fact_slots
    return containers


def current_scalar_fact_slots(summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return current/latest/window scalar slots controlled by numeric_facts."""

    return deepcopy(_current_scalar_fact_slots(summary))


def _current_scalar_fact_slots_requiring_facts(
    summary: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    required: dict[str, dict[str, Any]] = {}
    for container, fields in _current_scalar_fact_slots(summary).items():
        required_fields: dict[str, Any] = {}
        for field, value in fields.items():
            if value is None:
                continue
            if _current_signal_facts_cover_scalar(summary, str(field), value):
                continue
            required_fields[field] = value
        if required_fields:
            required[container] = required_fields
    return required


def _current_scalar_fact_containers(summary: dict[str, Any]) -> list[str]:
    return list(_current_scalar_fact_slots_requiring_facts(summary))


def _format_container_fields(fields_by_container: dict[str, list[str]]) -> str:
    return ", ".join(
        f"{container}.{field}"
        for container, fields in fields_by_container.items()
        for field in fields
    )


def _reject_null_current_scalar_slots(summary: dict[str, Any]) -> None:
    null_slots = {
        container: [
            field
            for field, value in fields.items()
            if value is None
            and not _source_coverage_marks_unavailable(summary, container, field)
        ]
        for container, fields in _current_scalar_fact_slots(summary).items()
    }
    null_slots = {container: fields for container, fields in null_slots.items() if fields}
    if not null_slots:
        return

    raise ValueError(
        "execution_summary current/latest scalar snapshots cannot include null "
        "scalar fields: "
        + _format_container_fields(null_slots)
        + ". Use latest_numeric_fact(...) to emit latest finite observations with "
        "their own as_of_date, or preserve explicit unavailable source_coverage "
        "for missing current/latest sources before save_quant_outputs(...)."
    )


def _source_coverage_marks_unavailable(
    summary: dict[str, Any],
    container: str,
    field: str,
) -> bool:
    coverage = summary.get("source_coverage")
    if not isinstance(coverage, dict):
        return False
    field_tokens = _field_core_tokens(field)
    if not field_tokens:
        return False

    def walk(
        value: Any,
        path: tuple[str, ...] = (),
        depth: int = 0,
    ) -> Iterable[tuple[tuple[str, ...], dict[str, Any]]]:
        if depth > 4 or not isinstance(value, dict):
            return
        yield path, value
        for child_key, child_value in value.items():
            if isinstance(child_value, dict):
                yield from walk(child_value, (*path, str(child_key)), depth + 1)

    for path, payload in walk(coverage):
        status = str(payload.get("status") or payload.get("availability") or "").strip().lower()
        if status not in _UNAVAILABLE_SOURCE_STATUSES:
            continue
        payload_tokens = _expand_current_scalar_aliases(
            set(_semantic_tokens(container, *path, *payload.values()))
        )
        if field_tokens & payload_tokens:
            return True
    return False


def _validate_no_freeform_statistical_assessment(summary: dict[str, Any]) -> None:
    stats = summary.get("statistical_summary")
    if not isinstance(stats, dict):
        return
    assessment = stats.get("assessment")
    if isinstance(assessment, str) and assessment.strip():
        raise ValueError(
            "execution_summary.statistical_summary.assessment is freeform "
            "qualitative prose. Move report-facing current claims into typed "
            "numeric_facts with display_value, as_of_date, metric, source_key, "
            "and operation/transform metadata, and keep statistical_summary to "
            "computed values."
        )


def _fact_matches_current_scalar(
    fact: dict[str, Any],
    *,
    field: str,
    value: Any,
) -> bool:
    number = _finite(value)
    fact_value = _finite(fact.get("raw_value", fact.get("value")))
    if number is None or fact_value is None:
        return False
    tolerance = _finite(fact.get("tolerance"))
    if tolerance is None:
        tolerance = 0.0
    if abs(float(fact_value) - float(number)) > max(float(tolerance), 1e-9):
        return False

    match_field = _current_scalar_fact_match_field(field)
    field_tokens = _current_scalar_identity_tokens(match_field)
    fact_tokens = _current_scalar_identity_tokens(
        fact.get("id"),
        fact.get("label"),
        fact.get("metric"),
        fact.get("source_key"),
    )
    if not field_tokens or not fact_tokens:
        return False
    return _current_scalar_field_tokens_match_fact(
        field_tokens,
        fact_tokens,
    ) and _current_scalar_fact_covers_field_modifiers(
        field=match_field,
        fact_values=(
            fact.get("id"),
            fact.get("label"),
            fact.get("metric"),
            fact.get("source_key"),
            fact.get("operation"),
            fact.get("transform_basis"),
        ),
    )


def _current_signal_fact_matches_current_scalar(
    fact: dict[str, Any],
    *,
    field: str,
    value: Any,
) -> bool:
    number = _finite(value)
    signal_value = _finite(fact.get("value"))
    if number is None or signal_value is None:
        return False
    tolerance = _finite(fact.get("tolerance"))
    if tolerance is None:
        tolerance = 0.0
    if abs(float(signal_value) - float(number)) > max(float(tolerance), 1e-9):
        return False

    match_field = _current_scalar_fact_match_field(field)
    field_tokens = _current_scalar_identity_tokens(match_field)
    fact_tokens = _current_scalar_identity_tokens(
        fact.get("signal_id"),
        fact.get("label"),
        fact.get("source_key"),
        fact.get("data_key"),
        fact.get("method"),
    )
    if not field_tokens or not fact_tokens:
        return False
    return _current_scalar_field_tokens_match_fact(
        field_tokens,
        fact_tokens,
    ) and _current_scalar_fact_covers_field_modifiers(
        field=match_field,
        fact_values=(
            fact.get("signal_id"),
            fact.get("label"),
            fact.get("source_key"),
            fact.get("data_key"),
            fact.get("method"),
        ),
    )


def _current_signal_facts_cover_scalar(
    summary: dict[str, Any],
    field: str,
    value: Any,
) -> bool:
    facts = summary.get("current_signal_facts")
    if not isinstance(facts, list):
        return False
    return any(
        isinstance(fact, dict)
        and _current_signal_fact_matches_current_scalar(fact, field=field, value=value)
        for fact in facts
    )


def _validate_current_scalar_fact_coverage(
    summary: dict[str, Any],
    facts: list[dict[str, Any]],
) -> None:
    missing: list[str] = []
    malformed: list[str] = []
    for container, slots in _current_scalar_fact_slots_requiring_facts(summary).items():
        for field, value in slots.items():
            matches = [
                fact
                for fact in facts
                if _fact_matches_current_scalar(fact, field=field, value=value)
            ]
            if not matches:
                missing.append(f"{container}.{field}")
                continue
            fact = matches[0]
            missing_fields = [
                field_name
                for field_name in ("as_of_date", "metric", "source_key")
                if not _non_empty_text(fact.get(field_name))
            ]
            if _is_derived_current_scalar_field(field) and not (
                _non_empty_text(fact.get("operation"))
                or _non_empty_text(fact.get("transform_basis"))
            ):
                missing_fields.append("operation_or_transform_basis")
            if missing_fields:
                label = str(fact.get("id") or fact.get("source_key") or field)
                malformed.append(f"{label}: missing {', '.join(missing_fields)}")

    if missing:
        raise ValueError(
            "execution_summary current/latest/window scalar snapshots require "
            "matching display-ready numeric_facts for "
            + ", ".join(missing[:12])
            + ". Build those facts with latest_numeric_fact(...) or "
            "numeric_fact(...), using metric/source_key values that identify the "
            "controlled scalar."
        )
    if malformed:
        raise ValueError(
            "execution_summary current/latest/window scalar numeric_facts are "
            "missing required metadata: "
            + "; ".join(malformed[:12])
            + ". Include as_of_date, metric, source_key, and operation or "
            "transform_basis for derived window/change/spread facts."
        )


def _episode_tokens_from_inactive_flag(field: Any) -> set[str]:
    tokens = list(_semantic_tokens(field))
    if len(tokens) < 2:
        return set()
    if tokens[0] == "still":
        episode_tokens = tokens[1:]
    elif tokens[0] == "active":
        episode_tokens = tokens[1:]
    elif tokens[-1] == "active":
        episode_tokens = tokens[:-1]
    else:
        return set()
    return _expand_episode_tokens(
        token
        for token in episode_tokens
        if token not in {"active", "current", "state", "still"}
    )


def _expand_episode_tokens(tokens: Iterable[str]) -> set[str]:
    expanded: set[str] = set()
    for token in tokens:
        if not token:
            continue
        expanded.add(token)
        expanded.update(_EPISODE_TOKEN_ALIASES.get(token, ()))
    return expanded


def _inactive_episode_state_flags(summary: dict[str, Any]) -> list[tuple[str, set[str]]]:
    flags: list[tuple[str, set[str]]] = []
    for payload in _iter_nested_mappings(summary, max_depth=3):
        for key, value in payload.items():
            if value is not False:
                continue
            episode_tokens = _episode_tokens_from_inactive_flag(key)
            if episode_tokens:
                flags.append((str(key), episode_tokens))
    return flags


def _duration_episode_tokens(*values: Any) -> set[str]:
    tokens = set(_semantic_tokens(*values))
    if _tokens_describe_elapsed_or_horizon_duration(tokens):
        return set()
    expanded = _expand_episode_tokens(tokens - _DURATION_TOKEN_STOPWORDS)
    if not expanded & _EPISODE_STATE_TOKENS:
        return set()
    return expanded


def _tokens_describe_elapsed_or_horizon_duration(tokens: set[str]) -> bool:
    if tokens & _HORIZON_DURATION_TOKENS:
        return True
    if "since" not in tokens:
        return False
    if tokens & _ELAPSED_SINCE_REFERENCE_TOKENS:
        return True
    return not bool(tokens & _ELAPSED_SINCE_CURRENT_DURATION_TOKENS)


def _duration_tokens_match_inactive_flag(
    fact_tokens: set[str],
    inactive_tokens: set[str],
) -> bool:
    return bool(fact_tokens and inactive_tokens and fact_tokens & inactive_tokens)


def _current_state_duration_fact_errors(
    facts: list[dict[str, Any]],
    inactive_flags: list[tuple[str, set[str]]],
) -> list[str]:
    errors: list[str] = []
    for fact in facts:
        unit = normalize_unit(fact.get("unit"))
        if unit not in _DURATION_FACT_UNITS:
            continue
        number = _finite(fact.get("raw_value", fact.get("value")))
        if number is None or abs(float(number)) <= 1e-12:
            continue
        role = str(fact.get("semantic_role") or "").strip()
        if role == _HISTORICAL_DURATION_ROLE:
            continue
        label = str(fact.get("id") or fact.get("label") or fact.get("source_key"))
        episode_active = fact.get("episode_active")
        if role == _CURRENT_STATE_DURATION_ROLE and episode_active is False:
            errors.append(
                f"{label}: episode_active=false but raw_value={number} {unit}"
            )
            continue
        fact_tokens = _duration_episode_tokens(
            fact.get("id"),
            fact.get("label"),
            fact.get("metric"),
            fact.get("source_key"),
        )
        matched_inactive_flag = False
        for flag_name, inactive_tokens in inactive_flags:
            if _duration_tokens_match_inactive_flag(fact_tokens, inactive_tokens):
                errors.append(
                    f"{label}: duration contradicts inactive state flag {flag_name}=false"
                )
                matched_inactive_flag = True
                break
        if matched_inactive_flag or not fact_tokens:
            continue
        if role == _CURRENT_STATE_DURATION_ROLE and episode_active is True:
            continue
        errors.append(
            f"{label}: nonzero episode duration requires "
            "semantic_role=current_state_duration with episode_active=true "
            "or semantic_role=historical_duration"
        )
    return errors


def _current_state_duration_scalar_errors(
    summary: dict[str, Any],
    inactive_flags: list[tuple[str, set[str]]],
) -> list[str]:
    errors: list[str] = []
    for container, slots in _current_scalar_fact_slots(summary).items():
        for field, value in slots.items():
            number = _finite(value)
            if number is None or abs(float(number)) <= 1e-12:
                continue
            field_tokens = _duration_episode_tokens(field)
            field_has_duration_unit = bool(
                set(_semantic_tokens(field)) & _DURATION_TOKEN_STOPWORDS
            )
            if not field_tokens or not field_has_duration_unit:
                continue
            for flag_name, inactive_tokens in inactive_flags:
                if _duration_tokens_match_inactive_flag(field_tokens, inactive_tokens):
                    errors.append(
                        f"{container}.{field}: duration contradicts inactive "
                        f"state flag {flag_name}=false"
                    )
                    break
    return errors


def _validate_current_state_episode_durations(summary: dict[str, Any]) -> None:
    """Reject ambiguous episode-duration facts before writer/QA handoff."""

    inactive_flags = _inactive_episode_state_flags(summary)
    facts = summary.get("numeric_facts")
    normalized_facts = facts if isinstance(facts, list) else []
    errors = _current_state_duration_fact_errors(normalized_facts, inactive_flags)
    errors.extend(_current_state_duration_scalar_errors(summary, inactive_flags))
    if not errors:
        return
    raise ValueError(
        "Malformed execution_summary current-state duration facts: "
        + "; ".join(errors[:12])
        + ". Use current_state_duration_fact(..., episode_active=<flag>) for "
        "active/current episode durations, emit 0 duration with state_description "
        "when inactive, or mark completed episodes with "
        "semantic_role=historical_duration."
    )


def _validate_numeric_facts(summary: dict[str, Any]) -> None:
    _reject_null_current_scalar_slots(summary)
    required_current_containers = _current_scalar_fact_containers(summary)
    if "numeric_facts" not in summary:
        if required_current_containers:
            raise ValueError(
                "execution_summary.numeric_facts is required when current/latest "
                "scalar containers are present ("
                + ", ".join(required_current_containers)
                + "). Build display-ready facts with latest_numeric_fact(...) or "
                "numeric_fact(...) before save_quant_outputs(...), or remove the "
                "current scalar snapshot if no scalar fact evidence is required."
            )
        return

    facts = summary.get("numeric_facts")
    if not isinstance(facts, list):
        raise ValueError(
            "execution_summary.numeric_facts must be a list of canonical numeric "
            "fact objects built with numeric_fact(...) or latest_numeric_fact(...)."
        )
    if required_current_containers and not facts:
        raise ValueError(
            "execution_summary.numeric_facts cannot be empty when current/latest "
            "scalar containers are present ("
            + ", ".join(required_current_containers)
            + "). Build display-ready facts with latest_numeric_fact(...) or "
            "numeric_fact(...) before save_quant_outputs(...), or remove the "
            "current scalar snapshot if no scalar fact evidence is required."
        )

    errors: list[str] = []
    for index, fact in enumerate(facts):
        fallback_id = f"numeric_facts[{index}]"
        if not isinstance(fact, dict):
            errors.append(f"{fallback_id}: expected object")
            continue

        fact_id = str(fact.get("id") or "").strip()
        label = fact_id or fallback_id
        missing_text = [
            field for field in _NUMERIC_FACT_TEXT_FIELDS if not _non_empty_text(fact.get(field))
        ]
        non_finite = [
            field for field in _NUMERIC_FACT_FINITE_FIELDS if _finite(fact.get(field)) is None
        ]
        if missing_text or non_finite:
            problems = []
            if missing_text:
                problems.append(f"missing non-empty {', '.join(missing_text)}")
            if non_finite:
                problems.append(f"missing finite {', '.join(non_finite)}")
            errors.append(f"{label}: {'; '.join(problems)}")

    if errors:
        raise ValueError(
            "Malformed execution_summary.numeric_facts: "
            + "; ".join(errors)
            + ". Use numeric_fact(...) or latest_numeric_fact(...) from "
            "agents.quant_macro_stats to build facts with raw_value, "
            "display_value, tolerance, and source_key; keep numeric_facts empty "
            "only when no scalar fact evidence is required."
        )
    _validate_current_scalar_fact_coverage(summary, facts)


def _validate_current_signal_facts(summary: dict[str, Any]) -> None:
    """Validate threshold-signal facts before they enter writer/QA handoffs."""

    if "current_signal_facts" not in summary:
        return
    facts = summary.get("current_signal_facts")
    if not isinstance(facts, list):
        raise ValueError("execution_summary.current_signal_facts must be a list.")

    errors: list[str] = []
    for index, fact in enumerate(facts):
        fallback_id = f"current_signal_facts[{index}]"
        if not isinstance(fact, dict):
            errors.append(f"{fallback_id}: expected object")
            continue

        label = str(fact.get("signal_id") or fallback_id)
        missing_text = [
            field
            for field in _CURRENT_SIGNAL_REQUIRED_TEXT_FIELDS
            if not _non_empty_text(fact.get(field))
        ]
        non_finite = [
            field
            for field in _CURRENT_SIGNAL_FINITE_FIELDS
            if _finite(fact.get(field)) is None
        ]
        direction = str(fact.get("direction") or "").strip().lower()
        if direction not in {"high", "low"}:
            errors.append(f"{label}: direction must be 'high' or 'low'")
        triggered = fact.get("triggered")
        if not isinstance(triggered, bool):
            errors.append(f"{label}: triggered must be a boolean")

        if missing_text or non_finite:
            problems = []
            if missing_text:
                problems.append(f"missing non-empty {', '.join(missing_text)}")
            if non_finite:
                problems.append(f"missing finite {', '.join(non_finite)}")
            errors.append(f"{label}: {'; '.join(problems)}")
            continue
        if direction not in {"high", "low"} or not isinstance(triggered, bool):
            continue

        value = float(_finite(fact.get("value")))
        threshold = float(_finite(fact.get("threshold")))
        distance = float(_finite(fact.get("threshold_distance")))
        expected_triggered = (
            value >= threshold if direction == "high" else value <= threshold
        )
        if triggered is not expected_triggered:
            errors.append(
                f"{label}: triggered={triggered} contradicts value={value}, "
                f"threshold={threshold}, direction={direction}"
            )
        expected_distance = (
            value - threshold if direction == "high" else threshold - value
        )
        tolerance = _finite(fact.get("tolerance"))
        if tolerance is None:
            tolerance = 0.005
        if abs(distance - expected_distance) > max(float(tolerance), 1e-9):
            errors.append(
                f"{label}: threshold_distance={distance} contradicts expected "
                f"{expected_distance}"
            )

    if errors:
        raise ValueError(
            "Malformed execution_summary.current_signal_facts: "
            + "; ".join(errors)
            + ". Use sahm_rule_signal(...) or emit current threshold-signal "
            "facts with signal_id, value, threshold, direction, triggered, "
            "threshold_distance, as_of_date, source_key, chart_id, and data_key."
        )


def _normalize_numeric_fact_contracts(summary: dict[str, Any]) -> None:
    """Canonicalize legacy numeric_facts before saving or handing off artifacts."""

    if "numeric_facts" not in summary:
        return
    try:
        summary["numeric_facts"] = normalize_numeric_facts(
            summary.get("numeric_facts"),
            strict=True,
        )
    except ValueError as exc:
        raise ValueError(f"Invalid execution_summary.numeric_facts: {exc}") from exc


def _iter_nested_mappings(*values: Any, max_depth: int = 3) -> Iterable[dict[str, Any]]:
    """Yield mapping payloads reachable from helper handoff containers."""

    def walk(value: Any, depth: int) -> Iterable[dict[str, Any]]:
        if depth > max_depth or not isinstance(value, dict):
            return
        yield value
        for child in value.values():
            if isinstance(child, dict):
                yield from walk(child, depth + 1)

    for value in values:
        yield from walk(value, 0)


_SUMMARY_NORMALIZATION_RULES = (
    _drop_obsolete_preservation_flags,
    _preserve_sec_company_facts_contract,
    _sanitize_split_affected_share_trends,
    _validate_no_freeform_statistical_assessment,
    _normalize_numeric_fact_contracts,
    _validate_current_state_episode_durations,
    _collect_validation_methods,
    _validate_current_signal_facts,
    _validate_numeric_facts,
)

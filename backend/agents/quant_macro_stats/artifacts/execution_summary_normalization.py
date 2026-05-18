"""Execution-summary validation and output-contract normalization."""
from copy import deepcopy
from typing import Any, Iterable

from .._utils import finite_number as _finite


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
    "trend_diagnostics",
    "macro_overlay",
    "company_macro_sensitivity",
    "source_coverage",
    "numeric_facts",
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

_NUMERIC_FACT_TEXT_FIELDS = ("id", "label", "display_value", "unit", "source_key")
_NUMERIC_FACT_FINITE_FIELDS = ("raw_value", "tolerance")
_CURRENT_SCALAR_FACT_CONTAINERS = ("statistical_summary",)
_CURRENT_SCALAR_DATE_FIELDS = ("latest_date",)


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


def _current_scalar_fact_slots(summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    containers: dict[str, dict[str, Any]] = {}
    for key in _CURRENT_SCALAR_FACT_CONTAINERS:
        value = summary.get(key)
        if not isinstance(value, dict):
            continue
        has_current_date = any(
            value.get(date_field) is not None for date_field in _CURRENT_SCALAR_DATE_FIELDS
        )
        if not has_current_date:
            continue
        scalar_fact_slots = {
            field: field_value
            for field, field_value in value.items()
            if field not in _CURRENT_SCALAR_DATE_FIELDS
            and _is_current_scalar_fact_slot(field_value)
        }
        if scalar_fact_slots:
            containers[key] = scalar_fact_slots
    return containers


def _current_scalar_fact_containers(summary: dict[str, Any]) -> list[str]:
    return list(_current_scalar_fact_slots(summary))


def _format_container_fields(fields_by_container: dict[str, list[str]]) -> str:
    return ", ".join(
        f"{container}.{field}"
        for container, fields in fields_by_container.items()
        for field in fields
    )


def _reject_null_current_scalar_slots(summary: dict[str, Any]) -> None:
    null_slots = {
        container: [field for field, value in fields.items() if value is None]
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
        "their own as_of_date, or remove the null scalar fields before "
        "save_quant_outputs(...)."
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
    _collect_validation_methods,
    _validate_numeric_facts,
)

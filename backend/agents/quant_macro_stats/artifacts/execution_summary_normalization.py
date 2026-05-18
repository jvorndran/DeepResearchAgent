"""Execution-summary validation and output-contract normalization."""
from copy import deepcopy
from typing import Any, Iterable


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
    "source_unit_metadata",
    "unit_comparisons",
    "source_unit_errors",
    "numeric_facts",
    "chart_provenance",
    "generated_by",
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
)

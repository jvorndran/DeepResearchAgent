"""Agent-facing catalog for reusable quant macro helper functions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class QuantHelperSpec:
    """Compact metadata used to teach agents which helper to import."""

    name: str
    import_path: str
    signature: str
    use_when: str
    preserves: tuple[str, ...] = ()


@dataclass(frozen=True)
class QuantHelperCategory:
    """A small group of related helper functions."""

    name: str
    purpose: str
    helpers: tuple[QuantHelperSpec, ...]


QUANT_HELPER_CATALOG: tuple[QuantHelperCategory, ...] = (
    QuantHelperCategory(
        name="data",
        purpose="Resolve local handoff files and create aligned macro panels.",
        helpers=(
            QuantHelperSpec(
                name="resolve_series_sources",
                import_path="agents.quant_macro_stats",
                signature="resolve_series_sources(data_files, specs, *, context)",
                use_when="Map requested series aliases to exact data_files keys before loading.",
                preserves=("resolved_sources", "missing_specs", "source_coverage"),
            ),
            QuantHelperSpec(
                name="load_monthly_panel",
                import_path="agents.quant_macro_stats",
                signature="load_monthly_panel(data_files, specs, *, context, frequency='M')",
                use_when="Load multiple local CSV series into one dated monthly panel.",
                preserves=("panel", "resolution", "limitations"),
            ),
            QuantHelperSpec(
                name="align_period_features",
                import_path="agents.quant_macro_stats",
                signature=(
                    "align_period_features(series_frames, *, frequency='M', "
                    "how='outer', fill_method=None, fill_limit=None, "
                    "fill_scope='lower_frequency')"
                ),
                use_when=(
                    "Align daily, weekly, monthly, or quarterly frames by common "
                    "period without forward-filling same-frequency stale tails."
                ),
                preserves=("date", "named feature columns", "source-period freshness"),
            ),
        ),
    ),
    QuantHelperCategory(
        name="forecasting",
        purpose="Build transparent forecast, validation, and failure-evidence rows.",
        helpers=(
            QuantHelperSpec(
                name="direct_ols_forecast",
                import_path="agents.quant_macro_stats",
                signature=(
                    "direct_ols_forecast(data, target_col, feature_cols, *, "
                    "horizon=6, include_target_lag=True, run_backtests=True)"
                ),
                use_when="Create direct OLS forecast rows and diagnostics without importing statsmodels.",
                preserves=(
                    "forecast_rows",
                    "model_spec",
                    "diagnostics",
                    "model_validation_rows",
                    "methods_used",
                ),
            ),
            QuantHelperSpec(
                name="walk_forward_ols_backtest",
                import_path="agents.quant_macro_stats",
                signature=(
                    "walk_forward_ols_backtest(data, target_col, feature_cols, *, "
                    "horizon=6, min_observations=24)"
                ),
                use_when="Find historical forecast misses or compare direct forecast errors over time.",
                preserves=("walk_forward_backtest_rows", "model_validation_rows"),
            ),
            QuantHelperSpec(
                name="forecast_model_comparison_rows",
                import_path="agents.quant_macro_stats",
                signature="forecast_model_comparison_rows(model_validation_rows)",
                use_when="Turn forecast validation output into compact comparison table rows.",
                preserves=("winner_by_mae", "direct_beats_last_value"),
            ),
            QuantHelperSpec(
                name="forecast_failure_episodes",
                import_path="agents.quant_macro_stats",
                signature="forecast_failure_episodes(backtest_result)",
                use_when="Extract largest forecast miss windows for report evidence.",
                preserves=("episode_start", "episode_end", "max_error"),
            ),
            QuantHelperSpec(
                name="forecast_false_alarm_episodes",
                import_path="agents.quant_macro_stats",
                signature=(
                    "forecast_false_alarm_episodes(data, *, signal_col, "
                    "event_col, threshold, prediction_horizon)"
                ),
                use_when="Explain prior signal false positives around event forecasts.",
                preserves=("start", "end", "max_signal", "future_event"),
            ),
            QuantHelperSpec(
                name="forecast_band_rows",
                import_path="agents.quant_macro_stats",
                signature="forecast_band_rows(panel, forecast_rows, *, latest_value, target_col)",
                use_when="Combine recent history and forecast intervals for one chart dataset.",
                preserves=("date", "actual", "forecast", "lower", "upper"),
            ),
            QuantHelperSpec(
                name="predictor_contribution_rows",
                import_path="agents.quant_macro_stats",
                signature=(
                    "predictor_contribution_rows(*, forecast_result, forecast_frame, "
                    "target_col, feature_cols, panel=None)"
                ),
                use_when="Rank model predictors and expose latest contribution evidence.",
                preserves=("feature", "coefficient", "latest_value", "contribution"),
            ),
        ),
    ),
    QuantHelperCategory(
        name="signals_and_regimes",
        purpose="Validate recession signals, classify macro regimes, and normalize scenarios.",
        helpers=(
            QuantHelperSpec(
                name="event_signal_backtest",
                import_path="agents.quant_macro_stats",
                signature=(
                    "event_signal_backtest(data, *, signal_col, target_col, "
                    "threshold, prediction_horizon)"
                ),
                use_when="Measure hit/miss/lead-time behavior for a single signal threshold.",
                preserves=("event_backtest_metrics", "lead_time_rows", "methods_used"),
            ),
            QuantHelperSpec(
                name="signal_framework_backtest",
                import_path="agents.quant_macro_stats",
                signature=(
                    "signal_framework_backtest(data, *, component_cols, recession_col, "
                    "threshold, lookback_periods)"
                ),
                use_when="Validate a composite binary signal framework against recession/event windows.",
                preserves=(
                    "signal_score_rows",
                    "signal_event_rows",
                    "signal_false_positive_windows",
                    "signal_validation_metrics",
                ),
            ),
            QuantHelperSpec(
                name="build_composite_predictive_indicator",
                import_path="agents.quant_macro_stats",
                signature=(
                    "build_composite_predictive_indicator(data, *, target_col, "
                    "feature_cols, prediction_horizon=6)"
                ),
                use_when="Score multiple predictors into a transparent current risk indicator.",
                preserves=(
                    "composite_current_row",
                    "composite_score_rows",
                    "composite_validation_metrics",
                    "feature_coverage",
                ),
            ),
            QuantHelperSpec(
                name="classify_recession_regime",
                import_path="agents.quant_macro_stats",
                signature="classify_recession_regime(data, *, recession_col='USREC')",
                use_when="Produce current regime, evidence rows, and historical analog rows.",
                preserves=(
                    "current_regime_row",
                    "regime_evidence_rows",
                    "regime_history_rows",
                    "regime_analog_rows",
                ),
            ),
            QuantHelperSpec(
                name="historical_scenario_replay",
                import_path="agents.quant_macro_stats",
                signature=(
                    "historical_scenario_replay(data, *, signal_cols, outcome_col, "
                    "windows, lookahead_periods=6)"
                ),
                use_when="Replay explicitly named historical windows against current signal logic.",
                preserves=("replay_rows", "replay_design"),
            ),
            QuantHelperSpec(
                name="normalize_scenario_evidence_rows",
                import_path="agents.quant_macro_stats",
                signature="normalize_scenario_evidence_rows(rows)",
                use_when="Clean caller-authored base/bull/bear or trigger evidence rows.",
                preserves=("scenario", "metric", "value", "score", "drivers", "evidence"),
            ),
        ),
    ),
    QuantHelperCategory(
        name="analogs_and_company",
        purpose="Build reusable analog-window and company-fundamental evidence.",
        helpers=(
            QuantHelperSpec(
                name="build_analog_evidence",
                import_path="agents.quant_macro_stats",
                signature=(
                    "build_analog_evidence(panel, *, value_cols, current_window, analog_windows)"
                ),
                use_when="Rank explicit historical windows against the current macro profile.",
                preserves=(
                    "historical_window_coverage",
                    "analog_similarity_ranking",
                    "analog_profiles",
                    "comparison_design",
                ),
            ),
            QuantHelperSpec(
                name="summarize_sec_company_facts",
                import_path="agents.quant_macro_stats",
                signature="summarize_sec_company_facts(path)",
                use_when="Summarize one SEC company facts CSV into core fiscal metrics.",
                preserves=("revenue_latest", "net_margin_pct", "fiscal_year_latest"),
            ),
            QuantHelperSpec(
                name="sec_company_facts_evidence",
                import_path="agents.quant_macro_stats",
                signature=(
                    "sec_company_facts_evidence(data_files, *, query, tickers=None, "
                    "include_macro_overlay=True)"
                ),
                use_when="Build multi-company fundamentals, trend, macro overlay, and numeric facts.",
                preserves=(
                    "latest_fundamentals",
                    "history_rows",
                    "trend_diagnostics",
                    "company_macro_sensitivity",
                    "numeric_facts",
                ),
            ),
        ),
    ),
    QuantHelperCategory(
        name="artifacts",
        purpose="Normalize chart and execution-summary artifacts for the writer.",
        helpers=(
            QuantHelperSpec(
                name="numeric_fact",
                import_path="agents.quant_macro_stats",
                signature=(
                    "numeric_fact(fact_id, label, raw_value, *, unit, precision, "
                    "source_key=None)"
                ),
                use_when="Record auditable scalar values in execution_summary.numeric_facts.",
                preserves=("id", "label", "value", "display_value", "source_key"),
            ),
            QuantHelperSpec(
                name="chart_provenance",
                import_path="agents.quant_macro_stats",
                signature="chart_provenance(source_series=..., raw_window=..., displayed_window=...)",
                use_when=(
                    "Attach raw source dates, displayed labels, resampling, and "
                    "normalization metadata to each chart before saving."
                ),
                preserves=(
                    "source_series",
                    "raw_latest_observation",
                    "displayed_latest_label",
                    "normalization",
                ),
            ),
            QuantHelperSpec(
                name="source_unit_metadata",
                import_path="agents.quant_macro_stats",
                signature="source_unit_metadata(source_key, source_file=..., units=...)",
                use_when=(
                    "Record source units before direct gaps, differences, ratios, or "
                    "overlays across wage, price, rate, or index series."
                ),
                preserves=("source_key", "series_id", "units", "unit_family", "unit_basis"),
            ),
            QuantHelperSpec(
                name="unit_comparison",
                import_path="agents.quant_macro_stats",
                signature="unit_comparison(comparison_id, sources, operation='difference')",
                use_when=(
                    "Validate that compared source_unit_metadata records share a "
                    "compatible unit, or document an explicit conversion."
                ),
                preserves=("status", "compatible", "sources", "conversion"),
            ),
            QuantHelperSpec(
                name="attach_methods_used",
                import_path="agents.quant_macro_stats",
                signature="attach_methods_used(charts, methods)",
                use_when="Annotate chart definitions with method labels before saving.",
                preserves=("methods_used",),
            ),
            QuantHelperSpec(
                name="attach_summary_methods",
                import_path="agents.quant_macro_stats",
                signature="attach_summary_methods(summary, methods)",
                use_when="Merge method labels into an execution summary.",
                preserves=("methods_used",),
            ),
            QuantHelperSpec(
                name="save_quant_outputs",
                import_path="agents.quant_macro_stats",
                signature="save_quant_outputs(output_dir, charts, execution_summary)",
                use_when="Always use for final charts.json and execution_summary.json writes.",
                preserves=("charts_json", "execution_summary_json", "chart_ids"),
            ),
        ),
    ),
)


def iter_quant_helper_specs(
    categories: Iterable[QuantHelperCategory] = QUANT_HELPER_CATALOG,
) -> Iterable[QuantHelperSpec]:
    """Yield every helper spec in catalog order."""

    for category in categories:
        yield from category.helpers


def format_quant_helper_catalog_for_prompt(
    *,
    categories: Iterable[QuantHelperCategory] = QUANT_HELPER_CATALOG,
    max_line_length: int = 145,
) -> str:
    """Render a compact, stable helper-selection guide for agent prompts."""

    lines = [
        "Import helpers from `agents.quant_macro_stats`; choose by task, not by reading source.",
    ]
    for category in categories:
        lines.append(f"{category.name}: {category.purpose}")
        for helper in category.helpers:
            preserved = (
                f" Preserves: {', '.join(helper.preserves)}."
                if helper.preserves
                else ""
            )
            line = f"- {helper.signature}: {helper.use_when}{preserved}"
            if len(line) <= max_line_length:
                lines.append(line)
                continue
            lines.append(f"- {helper.signature}")
            lines.append(f"  Use when: {helper.use_when}{preserved}")
    return "\n".join(lines)


__all__ = [
    "QUANT_HELPER_CATALOG",
    "QuantHelperCategory",
    "QuantHelperSpec",
    "format_quant_helper_catalog_for_prompt",
    "iter_quant_helper_specs",
]

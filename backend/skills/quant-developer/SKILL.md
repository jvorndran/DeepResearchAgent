---
name: quant-developer
description: Compact index for quantitative analysis script generation and repair.
---

# Quant Developer Skill

Use the system prompt as the primary contract. The detailed references in this
directory are:

- `sandbox-environment.md` for paths, write/execute workflow, FRED CSV loading,
  mixed-frequency joins, and unit-safe threshold comparisons.
- `code-execution-errors.md` for focused retry rules after Python tracebacks.
- `chart-generation.md` for canonical `charts.json` schema requirements.
- For macro lead-lag/regime questions, use the local deterministic helper
  `agents/quant_macro_stats.py` for rolling correlations, lag tests, recession
  windows, OLS regressions, direct OLS forecast tables, stationarity diagnostics,
  composite predictive indicators, mixed-frequency period-key alignment, and
  `methods_used` labels before writing artifacts.
- For econometric forecast questions, do not read `agents/quant_macro_stats.py`
  to rediscover helper signatures and do not hand-roll OLS loops. Use this
  canonical call directly after local series alignment:
  `direct_ols_forecast(data, target_col, feature_cols, date_col="date",
  horizon=6, include_target_lag=True, min_observations=12,
  prediction_interval=0.95)`. It returns JSON-safe `model_spec`,
  `estimation_window`, `target_variable`, `features`, `diagnostics`,
  `forecast_table`, `backtest_summary`, `model_comparison`, `methods_used`,
  `method_notes`, and `caveats`.
  Pass a dedicated forecast frame containing only `date`, `target_col`, and the
  selected forecast features. Do not reuse a broad regime/consumer/source panel
  after a global `.dropna()` across unrelated late-starting series; derive the
  forecast frame from raw aligned local series and call
  `dropna(subset=[target_col, *feature_cols])` only on those forecast columns.
  When the user asks about forecast confidence, prediction quality, or whether a
  model adds useful information, discuss the helper's walk-forward
  `backtest_summary` and `model_comparison` against naive baselines rather than
  relying on in-sample fit alone.
  If you build a custom recursive pseudo-OOS table, call
  `direct_ols_forecast(..., run_backtests=False)` inside that repeated loop and
  run the default full-backtest helper once for the current forecast artifact.
  Otherwise each recursive forecast call runs its own horizon-by-horizon
  walk-forward validation and can time out the sandbox.
- For six-month unemployment forecasts using yield curve, claims, payrolls, and
  industrial production, load each FRED CSV as a local single-series frame and
  call `align_period_features(series_frames, frequency="M", how="outer",
  timestamp_position="start", fill_method="ffill", fill_limit=2)` before
  deriving features. This avoids empty joins between weekly claims/month-end
  resamples and month-start FRED macro series. Derive features such as
  `T10Y2Y`, `ICSA`, `PAYEMS_CHG`, and `INDPRO_CHG`, build a dedicated
  `forecast_frame` with `dropna(subset=["UNRATE", "T10Y2Y", "ICSA",
  "PAYEMS_CHG", "INDPRO_CHG"])`, then call
  `direct_ols_forecast(forecast_frame, target_col="UNRATE", feature_cols=["T10Y2Y",
  "ICSA", "PAYEMS_CHG", "INDPRO_CHG"], horizon=6)`. Put the returned dict at
  top level in `execution_summary.json`; do not add a second manual OLS path.
  For custom pseudo-OOS unemployment forecast charts, use
  `run_backtests=False` in the repeated recursive calls, then use the single
  full current-forecast helper output for `backtest_summary` and
  `model_comparison`.
- Pandas frequency aliases are operation-specific: use `"ME"`/`"QE"` for
  `.resample(...)`, but use `"M"`/`"Q"` for `.dt.to_period(...)` and
  `pd.Period(...)`. Do not pass resample aliases into Period conversion.
- For recession-window summaries, call `recession_window_summary(...)` and keep
  its returned `at_start`, `exact_lookbacks`, `prior_windows`, `method_notes`,
  and `methods_used` fields in `execution_summary.json`. Do not hand-roll
  `.tail(...)` pre-recession slices; the helper's lookbacks exclude the
  recession start month to avoid lookahead.
- For composite predictive indicator questions, call
  `build_composite_predictive_indicator(...)` and write its returned acceptance
  keys directly into `execution_summary.json`; do not hand-roll full-sample
  normalization or omit the "predictive indicator" limitation language.
- For event-signal or historical-cycle questions, call the local validation
  helpers after building a clean local panel; do not satisfy "historical
  simulation", "what happened next", "prior cycle windows", or "backtest
  evidence" with narrative-only analog tables:
  `event_signal_backtest(data, signal_col="...", target_col="...",
  threshold=..., direction="high"|"low", prediction_horizon=...)` for hit/miss,
  false-positive, precision/recall, and lead-time evidence;
  `signal_framework_backtest(data, component_cols=[...], recession_col="USREC",
  threshold=3, lookback_periods=12, false_alarm_lookahead_periods=12)` for
  multi-component recession-warning scores with pre-recession windows and
  false-alarm episodes; and
  `historical_scenario_replay(data, signal_cols=[...], outcome_col="...",
  windows=[...])` for prior-cycle replay rows. Preserve their returned
  `backtest_summary`/`false_positive_analysis` or `historical_simulations`
  fields in `execution_summary.json`. Use these as validation evidence, not as
  causal proof. `save_quant_outputs(...)` will promote real nested
  `forecast_diagnostics.backtest_summary`, `forecast_diagnostics.model_comparison`,
  and `historical_replay.historical_simulations` to the top-level keys that QA
  and the writer expect; it will not invent missing validation artifacts, so
  compute them before saving.
- For explicit "looks like 1995, 2001, 2008, 2020, or current cycle" prompts,
  call `compare_analog_windows(data, date_col="date", value_cols=[...],
  windows=[...], current_window={...})` after building the aligned local panel.
  Preserve its `analog_similarity_ranking`, `analog_profiles`,
  `analogy_breakdown`, `comparison_design`, `methods_used`, and limitations in
  `execution_summary.json`. Do not hand-roll Euclidean distance loops or
  one-line `if`/semicolon math blocks for analog comparison.
- For scenario or stress-testing questions, call
  `build_scenario_stress_test(rows, topic="...")` and write its returned
  `scenario_table` directly into `execution_summary.json`; include exactly
  base, bull, and bear rows with assumptions, indicator_triggers, confidence,
  and uncertainty_notes. Do not pass dataframe/forecast arguments such as
  `target_col`, `base_forecast`, or `scenario_vars`; if you need to repair the
  row schema manually, import and call `validate_scenario_table(rows)` on the
  same list.
  If the user asks for scenario triggers or trigger levels, encode those
  thresholds in `scenario_table[*].indicator_triggers`; do not create a chart
  with `type="table"` because report charts do not render table chart types.
- For recession/regime classification questions, call
  `align_period_features(...)` first to build one monthly local panel from
  daily, monthly, and quarterly handoff series, then call
  `classify_recession_regime(...)` after converting that aligned panel into
  comparable rates, labor, inflation, credit, and output signals or explicit
  thresholded `indicator_specs`. Do not hand-roll mixed-frequency resampling or
  broad date merges; use the helper's controlled `fill_method="ffill",
  fill_limit=2` option for quarterly macro series in monthly panels, but do not
  forward-fill projection series such as NROU beyond the latest usable month;
  use the latest row that satisfies at least three required categories. Use the
  canonical classifier call shape
  `classify_recession_regime(scored_frame, date_col="date",
  indicator_specs=indicator_specs, recession_col="USREC", momentum_periods=3,
  min_categories=3, analog_count=3)` when `USREC` is present, or omit
  `recession_col` otherwise. Each `indicator_specs` item needs `name`, `column`,
  `category`, `weak_threshold`, `strong_threshold`, and `favorable_when`
  (`"high"` or `"low"`). Use it when the user asks for expansion, slowdown,
  recession, recovery, or reacceleration labels. Do not read
  `agents/quant_macro_stats.py` to rediscover this signature before writing
  `analysis.py`, and do not use it for provider fetches, causal claims, or
  guaranteed forecasts. Expected top-level output for `execution_summary.json`:
  `regime_label`, `regime_score`, `category_scores`, `evidence_table`,
  `historical_analogs`, `false_positive_caveat`, `missing_indicators`, and
  `methods_used`. Call budget: one helper call after local data is aligned.
  Fallback: if fewer than three categories are usable, preserve
  `status="insufficient_categories"` and explain which indicators were missing
  instead of inventing a label.
- For broad macro + equity + regional + international prompts, make the first
  script FRED/helper-centered. Load the FRED series needed for recession risk,
  unemployment outlook, consumer stress, scenarios, and regime classification.
  When the user explicitly asks for international peer, regional consumer, BLS
  verification, or company earnings-risk comparisons and the handoff includes
  matching World Bank, Census, BLS, or SEC EDGAR CSVs, load those files only for
  compact summary rows in `execution_summary` such as
  `international_comparison`, `regional_consumer_stats`,
  `apple_earnings_risk`, and `msft_earnings_risk`. Preserve provider paths in
  `execution_summary["source_context_files"]` only when they are background
  context. Never leave explicitly requested provider sections as `not processed`
  placeholders when source CSVs are available.
- For SEC EDGAR company-facts CSVs, call
  `summarize_sec_company_facts(path)` from `agents.quant_macro_stats` once per
  issuer. Do not infer company metrics from `select_dtypes`, positional numeric
  columns, or `.iloc[:, -1]`; SEC CSVs include shares, assets, debt, and other
  numeric fields, so positional inference can create impossible margins or
  growth rates. Preserve helper fields such as `revenue_growth_pct`,
  `net_income_growth_pct`, `net_margin_pct`, `revenue_cagr_pct`, and
  `debt_to_assets_pct`.
- The first `DATA_FILES` manifest may be a subset of the handoff for broad
  multi-source tasks. Copy exact CSV path strings only for the FRED/local series
  the script will load; omit unused SEC EDGAR, Census, BLS, and World Bank files
  instead of retyping long auto-saved paths that create suffix typos.
- Use the compact first-draft shape: imports plus `sys.path`, one `DATA_FILES`
  subset, one `load_series(key)` helper for FRED/local series,
  `series_frames = {k: load_series(k) for k in FRED_KEYS}`, one
  `align_period_features(...)` call, a few derived
  columns, helper calls for recession risk / unemployment forecast / scenarios /
  regime classification / historical replay as applicable, at most four charts, and
  `handoff = save_quant_outputs(...)`.
- For explicit analog-window prompts such as "does the current cycle look like
  1995, 2001, 2008, 2020, or something different", use the analog fast path:
  align the core FRED panel, call `compare_analog_windows(...)`, preserve its
  `analog_similarity_ranking`, `analog_profiles`, `analogy_breakdown`,
  `comparison_design`, and limitations at top level, optionally call
  `summarize_sec_company_facts(path)` once per requested issuer, make two or
  three charts, and save. Do not add unemployment forecast, scenario/stress, or
  regime-classifier helpers unless those artifacts were explicitly requested.
- Print the handoff object returned by `save_quant_outputs(...)` directly. Do
  not rebuild `chart_ids` from the original `charts` dict afterward, because
  `save_quant_outputs` may drop non-renderable charts before saving and the
  writer must only see saved chart IDs.
- Chart output must satisfy the frontend Recharts render contract, not just
  Pydantic schema. Axis charts need non-empty `data`, an `xAxisKey` present on
  every row, and each `series[*].dataKey` must have at least one finite numeric
  value. Scatter charts need finite numeric `xKey` and `yKey` values. Pie charts
  need named slices with finite values. After a report exists, failures from
  `scripts/validate_report_charts.sh <report.json>` are deterministic chart
  bugs to fix in chart construction or writer normalization.
- If you find yourself repeatedly writing the same runtime code across
  generated `analysis.py` scripts, that pattern belongs in a common helper
  rather than another long script. Good candidates are provider CSV loaders,
  mixed-frequency panel builders, chart-row serializers, compact validation
  checks, model/backtest summary tables, and artifact handoff assembly. Keep new
  helpers small, deterministic, local-data-only, JSON-safe, and covered by
  focused tests. Do not extract one-off query logic or broad report-specific
  business rules.
- Never install packages from a run script. Optional local `statsmodels` is
  handled only inside `agents/quant_macro_stats.py`; if unavailable, keep the
  helper's `statsmodels_unavailable` fallback note.

Do not read this index before writing the initial `analysis.py` unless a prior
tool result specifically asks for skill discovery. If a referenced file is
needed, read only that file.

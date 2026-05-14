---
name: quant-macro-helper-workflows
description: Deterministic macro helper routes, canonical call signatures, forecast/backtest acceptance keys, regime classification, scenarios, and pandas/FRED safety rules.
triggers:
  - forecast
  - backtest
  - recession
  - regime
  - scenario
  - analog
  - FRED
  - econometric
  - composite indicator
---

# Quant Macro Helper Workflows

Use this skill for macro lead-lag, recession-window, regime, forecast,
scenario, composite-indicator, historical replay, analog-window, and
econometric tasks. Use helper outputs instead of hand-rolling the same
statistics inside `analysis.py`.

## Deterministic Macro Helpers

- For macro lead-lag/regime/forecasting/composite-indicator/scenario questions,
  prefer the local deterministic helper in `agents/quant_macro_stats.py`.
  Import only the needed helpers after adding the backend directory to
  `sys.path`. Do not read `agents/quant_macro_stats.py` to rediscover helper
  signatures or to rediscover this signature before writing `analysis.py`.
- Available helper routes include `align_period_features`,
  `rolling_correlation`, `lead_lag_correlations`, `recession_window_summary`,
  `ols_regression`, `direct_ols_forecast`, `walk_forward_ols_backtest`,
  `event_signal_backtest`, `signal_framework_backtest`,
  `historical_scenario_replay`, `compare_analog_windows`,
  `build_composite_predictive_indicator`, `build_scenario_stress_test`,
  `validate_scenario_table`, `classify_recession_regime`,
  `summarize_sec_company_facts`, `attach_methods_used`,
  `attach_summary_methods`, and `save_quant_outputs`.
- Use helper outputs instead of hand-rolling mixed-frequency alignment, lag
  selection, recession-window loops, OLS regressions, direct forecast tables,
  walk-forward validation, signal hit/miss tests, historical replay rows,
  threshold false-alarm episodes, pre-recession signal score tables, analog
  window distances/breakdowns, composite indicator scoring, scenario schema
  validation, recession/regime labels, SEC company-facts metric extraction, JSON
  serialization, or chart-ID handoff construction.

## FRED And Pandas Safety

- FRED unit/threshold/display safety: align thresholds and labels with raw FRED
  units. Initial claims series `ICSA` and `IC4WSA` use raw `Number` counts;
  compare a 300k threshold as `300000`, or create
  `ICSA_thousands = ICSA / 1000` and compare to `300`. Never emit labels such
  as `210750k`, and do not compare raw counts to abbreviated thresholds.
- FRED frequency alignment: when joining daily or weekly FRED series such as
  Treasury yields or initial claims with monthly or quarterly macro series,
  first aggregate higher-frequency series to the target frequency and normalize
  every input to the same period key. For monthly joins, use
  `date.dt.to_period("M")`; for quarterly joins, create
  `quarter = date.dt.to_period("Q")` in every frame and merge on `quarter`.
  Do not merge quarter-start GDP dates directly against quarter-end resample
  timestamps. Do not merge month-end dates from resampling directly against
  month-start FRED dates.
- Pandas Resampling vs Period Keys: Use `'QE'` for quarterly and `'ME'` for
  monthly only with `.resample(...)`. Never call `.to_period("QE")` or
  `.to_period("ME")`.
- Mixed-frequency first draft requirement: if the input includes daily or
  weekly FRED rates/yields/claims plus monthly or quarterly macro series, the
  initial `analysis.py` must use period-key merges from the start. Prefer
  `align_period_features(series_frames, frequency="M", how="outer", timestamp_position="start", fill_method="ffill", fill_limit=2)`
  instead of `resample("ME").mean().to_frame()`, quarterly Cartesian joins, or
  broad `dropna()` alignment. The helper exposes only `date` plus one column
  per series key; do not reference `panel["period"]` or `panel.period`. Guard
  against empty output with `mixed-frequency FRED merge produced no rows`.
- Derived-column ordering: create derived columns before taking filtered
  `.copy()` subsets that reference them. If needed, rebuild the subset or
  explicitly assign the column; trace which dataframe actually owns the missing
  column.
- FRED helper consistency: if a loader renames `value`, Do not write helpers
  that still reference `df["value"]` after calling the renaming loader.
- JSON serialization safety: Use `save_quant_outputs` for final artifact
  writes. It recursively converts pandas/numpy values in chart data,
  `referenceLines`, `referenceAreas`, and execution summaries.
- Pandas chart-row construction: when converting resampled results to chart
  rows, make the object a named Series before iteration, for example
  `df["metric"].resample("QE").mean()` and `quarterly.items()`. Do not iterate
  over a single-column DataFrame with `iterrows()`. Use `.fillna(...)`, not
  nonexistent typo variants such as `.fillname(...)`.
- Pairwise correlation safety: for simple cross-country or cross-series
  correlation matrices, prefer pandas directly. Use
  `corr = numeric_frame.corr(min_periods=3).round(3).fillna(0)`. Only use
  `scipy.stats.pearsonr` when p-values are explicitly needed; do not run
  `pearsonr` on self-pairs or duplicate column selections such as
  `pivot[[c1, c1]]` because `valid[c1]` becomes a DataFrame instead of a
  Series. Set self-correlations directly to `1.0`/`0.0` and pass arrays with
  `to_numpy(dtype=float)`.

## Forecasting And Backtests

- For econometric forecasting prompts, do not import `statsmodels` directly, do
  not import `sklearn.linear_model`, do not hand-roll OLS/ARIMA forecast loops,
  and do not read helper source to rediscover helper signatures. Importing
  `direct_ols_forecast` is not enough; call
  `direct_ols_forecast(data, target_col, feature_cols, date_col="date", horizon=6, include_target_lag=True, min_observations=12, prediction_interval=0.95)`.
- Use `run_backtests=False` for repeated recursive pseudo-OOS loops. Forecast
  rows always include `date`, `forecast_period`, `forecast`, `lower`, and
  `upper`; Use `row["date"]` or `row["forecast_period"]`, and handle
  `lower_80`/`upper_80`.
- Preserve helper keys as top-level keys.
  Do not rename them to `model_specification`, `estimation_period`. Required keys include
  `model_spec`, `estimation_window`, `target_variable`, `features`,
  `diagnostics`, `forecast_table`, `backtest_summary`, `model_comparison`,
  `methods_used`, `method_notes`, and `caveats`.
- Pass a dedicated forecast frame containing only `date`, `target_col`, and the
  selected forecast features. Do not reuse a broad regime/consumer/source panel
  after a global `.dropna()` across unrelated late-starting series; derive the
  forecast frame from raw aligned local series and call
  `dropna(subset=[target_col, *feature_cols])` only on those forecast columns.
  Do not pass a broad regime/consumer/international panel into unemployment
  forecast helpers.
- For six-month unemployment forecast prompts using yield curve, claims, payrolls, and
  industrial production, load each FRED CSV as a local single-series frame and
  call `align_period_features(series_frames, frequency="M", how="outer", timestamp_position="start", fill_method="ffill", fill_limit=2)`.
  This avoids empty joins between weekly claims or resampled month-end observations and month-start FRED macro series.
  Then derive features such as `T10Y2Y`, `ICSA`, `PAYEMS_CHG`, and
  `INDPRO_CHG`, build a dedicated `forecast_frame` with
  `dropna(subset=["UNRATE", "T10Y2Y", "ICSA", "PAYEMS_CHG", "INDPRO_CHG"])`,
  and call `direct_ols_forecast(forecast_frame, target_col="UNRATE", feature_cols=["T10Y2Y", "ICSA", "PAYEMS_CHG", "INDPRO_CHG"], horizon=6)`.
  Do not add a second manual OLS implementation.
  For custom pseudo-OOS unemployment forecast charts, use `run_backtests=False`
  in repeated recursive helper calls.
- For chart-heavy six-month unemployment forecast-overlay prompts with UNRATE,
  PAYEMS, and available predictor evidence such as ICSA/IC4WSA, U6RATE,
  DGS10/FEDFUNDS, NROU, CPIAUCSL/PCEPI, or GDPC1/GDP, use
  `build_unemployment_forecast_chart_pack_artifacts(job_id, data_files, query)`
  before custom code. It writes the governed forecast-band, actual-vs-fitted,
  baseline-error, scatter, radar/radialBar, hierarchy, and signal-flow charts
  plus the direct OLS and walk-forward validation handoff.
- For broad macro-cycle, macro-regime, soft-landing/reacceleration, or
  investment-committee chart packs with rates or yield-curve spreads,
  inflation, labor, output, consumer sentiment/savings/income stress, USREC,
  and analog data already fetched, use
  `build_macro_cycle_chart_pack_artifacts(job_id, data_files, query)` before
  custom code. PSAVERT is useful but not required. It writes eight governed
  charts and a latest-year change/analog/synthesis execution summary.
- For CPI/core CPI/Fed funds chart-heavy policy-lag prompts with `CPIAUCSL`,
  `CPILFESL`, `FEDFUNDS`, and optional `USREC`, use
  `build_inflation_policy_chart_pack_artifacts(job_id, data_files, query)`
  before broad macro-cycle helpers. It writes overlay, policy-gap,
  scatter/bubble, radar, radialBar, treemap, funnel, and sankey charts tied to
  the inflation-policy question.
- If the prompt asks where the model failed historically, prior false alarms,
  missed calls, or hit/miss evidence, call `signal_framework_backtest(...)`
  with `threshold=2, lookback_periods=12, false_alarm_lookahead_periods=12`;
  do not treat `direct_ols_forecast` as a substitute for hit/miss analysis.

## Recession Windows, Regimes, And Composite Indicators

- For recession-window prompts, you MUST call `recession_window_summary(...)`
  and preserve `exact_lookbacks`; Do not compute pre-recession values with
  `.tail(...)` because helper lookbacks exclude the start month to avoid
  lookahead.
- For composite predictive indicator prompts, you MUST call
  `build_composite_predictive_indicator(...)`. For composite recession-risk
  indicator prompts, use `target_col="USREC"` and `prediction_horizon=1`.
  Do not compute a second F1 grid search. Do not hand-roll full-sample z-scores,
  and do not rescale `latest_index_value`, z-scores, or weighted sums yourself;
  plot `score_history[*]["composite_percentile_0_100"]` for 0-100 recession
  risk. If one predictor starts much later than the rest, preserve
  `feature_coverage`.
- Before success, Raise `ValueError` if any key is missing: `target`,
  `prediction_horizon`, `input_features`, `feature_transforms`,
  `normalization_method`, `weights_or_model`, `backtest_summary`,
  `latest_index_value`, `thresholds`, and `limitations`. A stdout handoff is
  valid only if `analysis.py` validated the required predictive-indicator
  summary keys before printing it. Call it a predictive indicator, not a
  guaranteed forecast.
- For recession/regime classification prompts, call
  `align_period_features(series_frames, frequency="M", how="outer", timestamp_position="start", fill_method="ffill", fill_limit=2)`
  then MUST call `classify_recession_regime(...)` using
  `classify_recession_regime(scored_frame, date_col="date", indicator_specs=indicator_specs, recession_col="USREC", momentum_periods=3, min_categories=3, analog_count=3)`.
  Do not hand-roll monthly/quarterly/daily resampling loops; select the latest
  row that satisfies the helper's minimum category coverage; do not run
  post-success shell probes. Use this canonical call shape without reading
  helper source. Each indicator spec has `weak_threshold`, `strong_threshold`,
  and `favorable_when`; `weak_threshold` must always be numerically less than
  `strong_threshold`, and use `favorable_when="low"` to make lower raw values
  score stronger.
- Do not hand-roll the regime label; verify `methods_used` includes
  `recession_regime_classifier` and preserve `regime_label`, `evidence_table`,
  `historical_analogs`, `false_positive_caveat`, `category_scores`,
  `missing_indicators`, and `methods_used`.

## Scenarios And Historical Replay

- If the user asks for scenario triggers, do not encode those as a chart with
  `type="table"`. Put thresholds in helper-backed `scenario_table` rows and let
  the technical writer render the markdown table.
- For scenario or stress-testing questions, call
  `build_scenario_stress_test(rows, topic="...")` and write its returned
  `scenario_table` directly into `execution_summary.json`; include exactly
  base, bull, and bear rows with assumptions, indicator_triggers, confidence,
  and uncertainty_notes. Do not pass dataframe/forecast arguments such as
  `target_col`, `base_forecast`, or `scenario_vars`; if you need to repair the
  row schema manually, import and call `validate_scenario_table(rows)` on the
  same list.
- For event-signal or historical-cycle questions, call local validation helpers
  after building a clean local panel; do not satisfy "historical simulation",
  "what happened next", "prior cycle windows", or "backtest evidence" with
  narrative-only analog tables:
  `event_signal_backtest(data, signal_col="...", target_col="...", threshold=..., direction="high"|"low", prediction_horizon=...)`,
  `signal_framework_backtest(data, component_cols=[...], recession_col="USREC", threshold=3, lookback_periods=12, false_alarm_lookahead_periods=12)`,
  and `historical_scenario_replay(data, signal_cols=[...], outcome_col="...", windows=[...])`.
  Preserve returned `backtest_summary`/`false_positive_analysis` or
  `historical_simulations` fields in `execution_summary.json`. Use these as
  validation evidence, not causal proof.
- For explicit "looks like 1995, 2001, 2008, 2020, or current cycle" prompts,
  call `compare_analog_windows(data, date_col="date", value_cols=[...], windows=[...], current_window={...})`
  after building the aligned local panel. Preserve `analog_similarity_ranking`,
  `analog_profiles`, `analogy_breakdown`, `comparison_design`, `methods_used`,
  and limitations in `execution_summary.json`. Do not hand-roll Euclidean
  distance loops or one-line `if`/semicolon math blocks for analog comparison.

## Runtime Boundary

- No runtime package installation: Never run `pip`, `ensurepip`, `get-pip.py`,
  or other installers. Keep free/no-key constraints strict. If optional
  `statsmodels` is unavailable, continue with the local helper's NumPy/SciPy
  fallback and preserve `statsmodels_unavailable`.

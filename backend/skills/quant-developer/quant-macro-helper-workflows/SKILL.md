---
name: quant-macro-helper-workflows
description: Reusable macro helper signatures, forecast/backtest evidence keys, regime classification, scenarios, and pandas/FRED safety rules.
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

## Reusable Helper Library

- Import only the needed helpers from `agents.quant_macro_stats` after adding
  the backend directory to `sys.path`. Do not read helper source to rediscover
  signatures before writing `analysis.py`.
- The system prompt includes the authoritative compact helper catalog generated
  from `agents.quant_macro_stats.QUANT_HELPER_CATALOG`. Use that catalog to pick
  helpers by task category; the top-level `agents.quant_macro_stats` facade is
  the stable import surface even though the implementation is organized under
  `data/`, `stats/`, `company/`, and `artifacts/`.
- Core helpers include `align_period_features`, `rolling_correlation`,
  `lead_lag_correlations`, `recession_window_summary`, `ols_regression`,
  `direct_ols_forecast`, `walk_forward_ols_backtest`,
  `event_signal_backtest`, `signal_framework_backtest`,
  `historical_scenario_replay`, `build_analog_evidence`,
  `build_composite_predictive_indicator`, `normalize_scenario_evidence_rows`,
  `classify_recession_regime`,
  `forecast_band_rows`,
  `forecast_model_comparison_rows`,
  `forecast_failure_episodes`, `forecast_false_alarm_episodes`,
  `predictor_contribution_rows`,
  `summarize_sec_company_facts`, `sec_company_facts_evidence`,
  `attach_methods_used`, `attach_summary_methods`, and `save_quant_outputs`.
- Use helper outputs instead of hand-rolling mixed-frequency alignment, lag
  selection, recession-window loops, OLS regressions, direct forecast tables,
  walk-forward validation, signal hit/miss tests, historical replay rows,
  false-alarm episodes, analog distances, composite indicator scoring,
  scenario evidence row normalization, regime labels, SEC metric extraction, JSON
  serialization, or chart-ID handoff construction.
- For company projection or sensitivity prompts, call the SEC company helper for
  reusable fundamentals, trend diagnostics, macro overlays, numeric facts, and
  source coverage, then compose any caller-requested projection or scenario rows
  inside `analysis.py` from explicit assumptions. Treat
  `company_macro_sensitivity` as numeric/context rows only; do not rely on a
  prebuilt company projection, risk-channel, or macro-link payload.

## FRED And Pandas Safety

- FRED unit/threshold/display safety: align thresholds and labels with raw FRED
  units. Initial claims series `ICSA` and `IC4WSA` use raw `Number` counts;
  compare a 300k threshold as `300000`, or create
  `ICSA_thousands = ICSA / 1000` and compare to `300`.
- For daily or weekly FRED series joined with monthly or quarterly macro
  series, aggregate higher-frequency series to the target frequency and
  normalize every input to the same period key. Prefer
  `align_period_features(series_frames, frequency="M", how="outer", timestamp_position="start", fill_method="ffill", fill_limit=2)`.
- Use `'QE'` for quarterly and `'ME'` for monthly only with `.resample(...)`.
  Never call `.to_period("QE")` or `.to_period("ME")`.
- JSON serialization safety: use `save_quant_outputs` for final artifact
  writes. It recursively converts pandas/numpy values in chart data,
  reference annotations, and execution summaries.
- Pairwise correlation safety: for simple cross-country or cross-series
  correlation matrices, prefer pandas directly with
  `corr = numeric_frame.corr(min_periods=3).round(3).fillna(0)`.

## Forecasting And Backtests

- For econometric forecasting prompts, do not import `statsmodels` directly, do
  not import `sklearn.linear_model`, and do not hand-roll OLS/ARIMA forecast
  loops. Call
  `direct_ols_forecast(data, target_col, feature_cols, date_col="date", horizon=6, include_target_lag=True, min_observations=12, prediction_interval=0.95)`.
- For governed forecast prompts, compose reusable helpers inside `analysis.py`:
  call `direct_ols_forecast(...)` for forecast rows, `walk_forward_ols_backtest(...)`
  for validation misses, optional `event_signal_backtest(...)` for false-alarm
  evidence, then assemble top-level execution-summary rows directly in
  `analysis.py`: `forecast_table`, `model_comparison_by_horizon`,
  `historical_failure_episodes`, `event_backtest_metrics`,
  `signal_false_positive_windows`, `predictor_contributions`, `forecast_band_rows`,
  diagnostics, methods, limitations, numeric facts, and source coverage when
  applicable. Use `forecast_band_rows(...)`,
  `forecast_model_comparison_rows(...)`,
  `forecast_failure_episodes(...)`, `forecast_false_alarm_episodes(...)`, and
  `predictor_contribution_rows(...)` for chart/table inputs. Compose any
  baseline win/loss prose or false-alarm summary in `analysis.py` from those
  reusable rows and event metrics; do not import a prebuilt forecast artifact
  generator.
- Use `run_backtests=False` for repeated recursive pseudo-OOS loops. Forecast
  helper rows are returned under `forecast_rows` and include `date`,
  `forecast_period`, `forecast`, `lower`, and `upper`; handle optional
  `lower_80`/`upper_80`. If `run_backtests=True`, use
  `walk_forward_backtest_rows` and `model_validation_rows` as helper inputs;
  do not spread the raw helper return as the final execution summary.
- Pass a dedicated forecast frame containing only `date`, `target_col`, and the
  selected forecast features. Do not reuse a broad regime/source panel after a
  global `.dropna()` across unrelated late-starting series.
- If the prompt asks where the model failed historically, prior false alarms,
  missed calls, or hit/miss evidence, prefer
  `walk_forward_ols_backtest(...)` plus `event_signal_backtest(...)` and generic
  forecast evidence rows for forecast work, or call `signal_framework_backtest(...)`
  with `threshold=2, lookback_periods=12, false_alarm_lookahead_periods=12` for
  custom binary signal frameworks; do not treat `direct_ols_forecast` as a
  substitute for hit/miss analysis.

## Recession Windows, Regimes, And Composite Indicators

- For recession-window prompts, call `recession_window_summary(...)` and
  preserve `exact_lookbacks`; do not compute pre-recession values with
  `.tail(...)` because helper lookbacks exclude the start month to avoid
  lookahead.
- For composite predictive indicator prompts, call
  `build_composite_predictive_indicator(...)`. For composite recession-risk
  indicator prompts, use `target_col="USREC"` and `prediction_horizon=1`.
  Preserve reusable helper outputs such as `composite_current_row`,
  `composite_score_rows`, `composite_validation_metrics`,
  `composite_validation_design`, `feature_coverage`, `feature_transforms`,
  `normalization_stats`, `weights_or_model`, `thresholds`, and `methods_used`
  as top-level `execution_summary` evidence. Compose any report-facing risk
  label, probability wording, table title, or backtest prose in `analysis.py`
  from those rows and diagnostics.
- For recession/regime classification prompts, call
  `classify_recession_regime(scored_frame, date_col="date", indicator_specs=indicator_specs, recession_col="USREC", momentum_periods=3, min_categories=3, analog_count=3)`.
  Preserve reusable helper outputs such as `current_regime_row`,
  `regime_evidence_rows`, `regime_history_rows`, `regime_analog_rows`,
  `missing_indicator_rows`, `regime_design`, and `methods_used`. Compose any
  report-facing labels, caveats, or section text in `analysis.py` from those
  rows rather than relying on a prebuilt regime report packet.

## Scenarios And Historical Replay

- If the user asks for scenario triggers, compose caller-specific scenario
  evidence rows in `analysis.py`, then call
  `normalize_scenario_evidence_rows(rows)`. Preserve reusable rows as top-level
  `scenario_score_rows` or another generic evidence key in
  `execution_summary.json`; do not emit a quant-owned `scenario_table` contract.
- Scenario rows should carry the relevant metrics, scores, values, drivers,
  notes, or evidence needed for the request. Do not include report narrative
  fields such as `interpretation`; `analysis.py` owns any report-facing
  base/bull/bear labels, threshold prose, table headers, and scenario narrative.
- For event-signal or historical-cycle questions, call local validation helpers
  after building a clean panel:
  `event_signal_backtest(...)`, `signal_framework_backtest(...)`, and
  `historical_scenario_replay(...)`. Supply explicit `windows=[...]` to
  `historical_scenario_replay(...)`; it returns reusable `replay_rows` and
  `replay_design` for `analysis.py` to place into whatever top-level evidence
  fields the user request needs. Preserve signal helper outputs such as
  `event_backtest_metrics`, `lead_time_rows`, `signal_score_rows`,
  `signal_event_rows`, `signal_false_positive_windows`,
  `signal_validation_metrics`, `latest_signal_observation`, `signal_design`,
  methods, limitations, and replay rows as generic evidence rather than relying
  on a prebuilt report packet.
- For analog-window questions, call `build_analog_evidence(...)` only after
  defining explicit `analog_windows` and `current_window` in `analysis.py`.
  Preserve row-level helper outputs such as `historical_window_coverage`,
  `analog_similarity_ranking`, `analog_profiles`, `analog_profile_rows`,
  `comparison_design`, `methods_used`, and `limitations`. Compose any
  report-facing analog label, score wording, tables, or chart labels in
  `analysis.py` from those rows.

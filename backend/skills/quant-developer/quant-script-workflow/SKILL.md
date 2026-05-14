---
name: quant-script-workflow
description: Script budget, first-write workflow, data_files usage, broad multi-source handling, SEC company facts, and artifact handoff rules for quant-developer analysis.py generation.
triggers:
  - analysis.py
  - write_file
  - data_files
  - execution_summary
  - broad macro
  - SEC EDGAR
  - source_context_files
---

# Quant Script Workflow

Use this skill before writing or repairing `analysis.py`. It is the focused
workflow contract; load more specialized quant skills only when their task shape
applies.

## SCRIPT BUDGET & RECOVERY

- Keep `analysis.py` compact: target under 120 lines. For ordinary
  non-chart-heavy prompts, 3-4 computed charts is enough. For explicit chart,
  chart-pack, dashboard, visual-evidence, or chart-validation prompts, target
  6-8 distinct renderable charts by using shared helpers and loops instead of
  repeated bespoke blocks. For broad multi-source investment-committee
  requests, compute required quantitative handoff fields first and leave
  qualitative source synthesis to the technical writer.
- The tool boundary rejects oversized Python writes above 360 lines or 28,000
  characters before they reach the sandbox. If your first draft would exceed
  that, simplify before calling `write_file`. After three blocked pre-write
  drafts, the next `write_file` is the final compact rewrite opportunity; it
  must be under 120 lines and should call local macro helpers rather than
  expanding bespoke analysis blocks.
- Before `write_file`, mentally lint for syntax traps: no nested f-string dict
  literals, no chained ternaries with multiple `if` clauses, and no giant
  single-line `print(json.dumps(...))`.
- If `write_file` reports truncation, overwrite failure, or the file already
  exists, do not delete/rewrite with shell. Use `read_file` to inspect the
  existing file and `edit_file` with the smallest exact replacement. If two
  edit attempts fail, write a compact replacement script to `analysis_v2.py`
  and still save final artifacts in the original job output directory.
- A successful script stdout that includes `charts_json`,
  `execution_summary_json`, and `chart_ids` is already a validation signal.
  Once `execute` succeeds and stdout includes valid handoff fields, stop. Do
  not run extra exploratory checks, re-open the script, read
  `execution_summary.json`, or tune optional aesthetics unless there is a
  concrete failed tool result or invalid chart output.
- Do not edit a successful script merely to make a conclusion field more
  positive. For consistency/guarantee questions, preserve
  counterexample-sensitive booleans and explain the nuance in
  `statistical_summary`. If the user asks whether a relationship is
  "consistent", "always", "guaranteed", or similar, test counterexamples across
  periods/regimes and report material near-zero or negative cases as
  "supportive but not consistent/guaranteed."

## Initial Script Guardrails

- For FRED recession-dashboard or recession chart-pack tasks with UNRATE,
  INDPRO, USREC, and either T10Y3M or real GDP (GDPC1/GDP), your first non-skill
  tool call must be `build_recession_dashboard_artifacts(job_id, data_files,
  query)`. Do not check helper availability with `write_file`. The tool writes
  `charts.json`, `execution_summary.json`, and a reproducible `code/analysis.py`
  using deterministic chart generation, avoiding a large first `write_file`
  payload. Credit/risk-context CSVs are useful when present but not required.
- For chart-heavy CPI/core CPI/Fed funds macro tasks with CPIAUCSL, CPILFESL,
  FEDFUNDS, and optional USREC, prefer
  `build_inflation_policy_chart_pack_artifacts(job_id, data_files, query)`
  before writing custom code. It produces a governed 6-8 chart pack spanning
  trend overlays, policy-gap history, lagged scatter/bubble evidence,
  normalized regime profiles, current component scores, lag-regime hierarchy,
  staged filters, and signal flow.
- For broad macro-cycle, macro-regime, soft-landing/reacceleration, or
  investment-committee chart packs with FEDFUNDS, CPIAUCSL/PCEPI, a rate
  signal such as DGS10/GS10/T10Y2Y/T10Y3M, UNRATE, PAYEMS, INDPRO,
  GDPC1/GDP, a consumer-stress proxy such as UMCSENT/PSAVERT/DSPIC96/PCEC96,
  USREC, and optional T10YIE, CIVPART, TCU, MORTGAGE30US, CSUSHPISA, or
  STLFSI, prefer
  `build_macro_cycle_chart_pack_artifacts(job_id, data_files, query)` before
  writing custom code. It produces a governed 8-chart pack spanning
  rates/inflation, labor, output, consumer stress, latest-year changes,
  historical analog distance, normalized profiles, and synthesis flow.
- For chart-heavy FRED consumer-stress dashboards with PSAVERT, AHETPI,
  UNRATE, CPIAUCSL, UMCSENT, DPCERA3M086SBEA, TOTALSL, and optional U6RATE,
  PCEPILFE, DRALACBN/DRCLACBS, DTCOLNVHFNM, or USREC, prefer
  `build_consumer_stress_dashboard_artifacts(job_id, data_files, query)`
  before writing custom code. It produces a governed 8-chart dashboard covering
  normalized stress overlays, savings-vs-sentiment scatter/bubble evidence,
  labor-depth area views, current radar/radialBar component profiles,
  consumption-savings tradeoffs, credit stress, and contribution hierarchy.
- For chart-heavy historical replay or analog-window macro packs with UNRATE,
  CPIAUCSL, FEDFUNDS, INDPRO, USREC, and optional DGS10, ICSA, PCE, DSPIC96,
  CIVPART, or CES0500000003, prefer
  `build_historical_replay_chart_pack_artifacts(job_id, data_files, query)`
  before writing custom code. It produces a governed replay pack with current
  overlays, historical analog paths, analog distance scatter/bubble evidence,
  normalized radar profiles, radialBar signal scores, and contribution
  hierarchy.
- For chart-heavy unemployment forecast or forecast-overlay packs with UNRATE,
  PAYEMS, and available predictor evidence such as ICSA/IC4WSA, U6RATE,
  DGS10/FEDFUNDS, NROU, CPIAUCSL/PCEPI, or GDPC1/GDP, prefer
  `build_unemployment_forecast_chart_pack_artifacts(job_id, data_files, query)`
  before writing custom code. It produces a governed 8-chart pack covering
  forecast bands, actual-vs-fitted validation, baseline errors, fitted-vs-actual
  scatter/bubble evidence, predictor contribution radar/radialBar views,
  uncertainty hierarchy, and signal-flow explanation.
- If no deterministic chart-pack tool fits, your first tool call MUST be
  `write_file` for the generated analysis script. Do not call
  `ls`, `glob`, `read_file`, `execute`, or any other inspection tool before the
  initial script is written, except for reading native quant skill `SKILL.md`
  files.
- Write the first script only to `/code/analysis.py`; do not use task-specific
  first-attempt names such as `regime_classification.py`.
- Trust the data-engineer schema/file-path handoff. Treat the `data_files` map
  in the task description as the canonical manifest. In `analysis.py`, define
  one `DATA_FILES = {...}` dictionary by copying exact path strings, then load
  files by stable keys such as `DATA_FILES["UNRATE"]`.
- Do not manually retype long auto-saved filenames into separate string
  literals, because one-character suffix errors cause avoidable
  `FileNotFoundError` retries.
- Do not use `execute` for shell-based CSV inspection (`head`, `tail`, `cat`,
  `grep`, `awk`, `sed`, `wc`, `ls`, directory probes, or one-off pandas
  snippets). Put all data loading, cleaning, latest-date checks, and validation
  inside `analysis.py`, then run that script once.
- Execute the script with the default sandbox timeout. Do not pass large timeout
  values such as 120000; timeout negotiation is not part of the analysis.

## Broad Multi-Source First Draft

- For broad macro + equity + regional + international prompts, keep the first
  draft FRED/helper-centered. Load the FRED series needed for recession risk,
  unemployment outlook, consumer stress, scenarios, and regime classification,
  plus `USREC` when available.
- When the user explicitly asks for international peer, regional consumer, BLS
  verification, or company earnings-risk comparisons and the handoff includes
  matching World Bank, Census, BLS, or SEC EDGAR CSVs, load those files only for
  compact summary rows in `execution_summary` such as
  `international_comparison`, `regional_consumer_stats`,
  `apple_earnings_risk`, and `msft_earnings_risk`.
- If a provider file is background context, add its path/provider to
  `execution_summary["source_context_files"]` without loading it.
  Never leave explicitly requested provider sections as `not processed` placeholders when source CSVs are available.
- Use one generic FRED loader and one `series_frames` dict, then call
  `align_period_features(...)` once. Keep provider-specific context handling
  short: no extra charts, no deep joins, no broad pivots, and no
  narrative-only placeholders.
- A compact broad-prompt first draft should follow this shape: imports plus
  `sys.path`, one `DATA_FILES` subset, one `load_series(key)` helper for
  FRED/local series, `series_frames = {k: load_series(k) for k in FRED_KEYS}`,
  `panel = align_period_features(...)`, a few derived columns, helper calls for
  recession risk / unemployment forecast / scenarios / regime classification /
  historical replay as applicable, 3-4 charts for ordinary prompts or 6-8
  charts for explicit chart-heavy/dashboard prompts, and `handoff =
  save_quant_outputs(...)`.
- The first `DATA_FILES` manifest may be a subset of the handoff for broad
  multi-source tasks. Copy exact CSV path strings only for the FRED/local series
  the script will load; omit unused SEC EDGAR, Census, BLS, and World Bank files
  instead of retyping long auto-saved paths that create suffix typos.

## Historical Replay And Analog Fast Paths

- For historical-simulation, prior-cycle, prior-downturn/prior-recession
  comparison, "what happened next", or analog-window requests, start with
  `compare_analog_windows(...)`, `historical_scenario_replay(...)`, and/or
  `signal_framework_backtest(...)`. Do not add `direct_ols_forecast(...)`
  unless the user explicitly asks for a point forecast such as a six-month
  unemployment forecast.
- If the query asks for backtesting, historical replay/simulation,
  prior-downturn/prior-recession comparison, forecast diagnostics, or
  comparison against naive explanations, the first script must preserve
  explicit top-level `backtest_summary`, `model_comparison`, and/or
  `historical_simulations` keys from the relevant helper outputs before calling
  `save_quant_outputs(...)`; do not defer those keys to a second enrichment
  script.
- For explicit analog-window prompts such as "does the current cycle look like
  1995, 2001, 2008, 2020, or something different", use the analog fast path:
  align the core FRED panel, call `compare_analog_windows(...)`, preserve its
  `analog_similarity_ranking`, `analog_profiles`, `analogy_breakdown`,
  `comparison_design`, and limitations at top level, optionally call
  `summarize_sec_company_facts(path)` once per requested issuer, make three to
  five charts by default or six to eight when the prompt is explicitly
  chart-heavy, and save. Do not add unemployment forecast, scenario/stress, or
  regime-classifier helpers unless those artifacts were explicitly requested.

## SEC And Provider Context

- For SEC EDGAR company-facts CSVs, call `summarize_sec_company_facts(path)`
  from `agents.quant_macro_stats` once per issuer. Do not infer company metrics
  from `select_dtypes`, positional numeric columns, or `.iloc[:, -1]`; SEC CSVs
  include shares, assets, debt, and other numeric fields, so positional
  inference can create impossible margins or growth rates.
- Preserve helper fields such as `revenue_growth_pct`, `net_income_growth_pct`,
  `net_margin_pct`, `revenue_cagr_pct`, and `debt_to_assets_pct`.
- FMP remains disabled and unavailable. Do not request paid/keyed provider data
  or invent FMP-backed quote, market-data, estimate, or financial-statement
  fields.

## Artifact Handoff

- Prefer `save_quant_outputs` from `agents.quant_macro_stats` for final artifact
  writes. It saves strict JSON, converts pandas/numpy values, writes
  `execution_summary.json`, derives saved `chart_ids`, and returns the compact
  handoff object. Never import `agents.quant_utils`.
- Print the handoff object returned by `save_quant_outputs(...)` directly. Do
  not rebuild `chart_ids` from the original `charts` dict afterward, because
  `save_quant_outputs` may drop non-renderable charts before saving and the
  writer must only see saved chart IDs.
- If you find yourself repeatedly writing the same runtime code across
  generated `analysis.py` scripts, that pattern belongs in a common helper
  rather than another long script. Keep helpers deterministic, local-data-only,
  JSON-safe, and covered by focused tests.
- No runtime package installation: Never run `pip`, `ensurepip`, `get-pip.py`,
  `uv`, `poetry`, `conda`, `mamba`, `apt`, or other installers. Optional local
  `statsmodels` is handled only inside `agents/quant_macro_stats.py`; if
  unavailable, keep the helper's NumPy/SciPy fallback note.

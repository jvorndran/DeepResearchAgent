---
name: quant-script-workflow
description: First-write workflow, script budget, data_files usage, provider context, and artifact handoff rules for quant-developer analysis.py generation.
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

Use this skill before writing or repairing `analysis.py`. The quant developer
must create the analysis script and compose reusable helpers; there is no
report-specific shortcut tool.

## Script Budget And Recovery

- Keep `analysis.py` compact: target under 120 lines. For ordinary
  non-chart-heavy prompts, 3-4 computed charts is enough. For explicit chart,
  dashboard, visual-evidence, or chart-validation prompts, target 6-8 distinct
  renderable charts by using shared helpers and loops instead of repeated
  bespoke blocks.
- The tool boundary rejects oversized Python writes above 360 lines or 28,000
  characters before they reach the sandbox. If your first draft would exceed
  that, simplify before calling `write_file`. After three blocked pre-write
  drafts, the next `write_file` is the final compact rewrite opportunity.
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
  Once `execute` succeeds and stdout includes valid handoff fields, stop.

## Initial Script Guardrails

- Your first non-skill tool call must be `write_file` for
  `/code/analysis.py`. Do not call `ls`, `glob`, `read_file`, `execute`, or
  any other inspection tool before the initial script is written, except for
  reading native quant skill `SKILL.md` files.
- Trust the data-engineer schema/file-path handoff. Treat the `data_files` map
  in the task description as the canonical manifest. In `analysis.py`, define
  one `DATA_FILES = {...}` dictionary by copying exact path strings, then load
  files by stable keys such as `DATA_FILES["UNRATE"]`.
- Do not manually retype long auto-saved filenames into separate string
  literals, because one-character suffix errors cause avoidable
  `FileNotFoundError` retries.
- Do not use `execute` for shell-based CSV inspection. Put all data loading,
  cleaning, latest-date checks, and validation inside `analysis.py`, then run
  that script once.

## Broad Multi-Source Drafts

- For broad macro + equity + regional + international prompts, keep the first
  draft FRED/helper-centered. Load the FRED series needed for recession risk,
  unemployment outlook, consumer stress, scenarios, and regime classification,
  plus `USREC` when available.
- When the user explicitly asks for international peer, regional consumer, BLS
  verification, or company earnings-risk comparisons and the handoff includes
  matching World Bank, Census, BLS, or SEC EDGAR CSVs, load those files only for
  compact summary rows in `execution_summary`.
- If a provider file is background context, add its path/provider to
  `execution_summary["source_context_files"]` without loading it. Never leave
  explicitly requested provider sections as `not processed` placeholders when
  source CSVs are available.
- Use one generic FRED loader and one `series_frames` dict, then call
  `align_period_features(...)` once. Keep provider-specific context handling
  short: no extra charts, no deep joins, no broad pivots, and no
  narrative-only placeholders.

## Historical Replay And Analogs

- For historical-simulation, prior-cycle, prior-downturn/prior-recession
  comparison, "what happened next", or analog-window requests, compose
  reusable rows with `build_analog_evidence(...)`,
  `historical_scenario_replay(...)`, and/or `signal_framework_backtest(...)`.
  When calling `historical_scenario_replay(...)`, define the historical windows
  explicitly in `analysis.py`; the helper does not choose report-specific
  default cycles.
  Do not add `direct_ols_forecast(...)`
  unless the user explicitly asks for a point forecast.
- If the query asks for backtesting, historical replay/simulation,
  prior-downturn/prior-recession comparison, forecast diagnostics, or
  comparison against naive explanations, choose top-level evidence fields in
  `analysis.py` from the reusable helper rows and diagnostics before calling
  `save_quant_outputs(...)`. For signal helpers, preserve reusable evidence
  such as `event_backtest_metrics`, `lead_time_rows`, `signal_score_rows`,
  `signal_event_rows`, `signal_false_positive_windows`,
  `signal_validation_metrics`, `latest_signal_observation`, and
  `signal_design`; do not expect a prebuilt report packet.
- For explicit analog-window prompts, align the core FRED panel, call
  `build_analog_evidence(...)` with caller-defined `analog_windows`
  containing explicit label/start/end dictionaries, preserve generic
  `historical_window_coverage`, `analog_similarity_ranking`,
  `analog_profiles`, `analog_profile_rows`, methods, limitations, and any
  caller-composed replay rows, optionally call
  `summarize_sec_company_facts(path)` once per requested issuer, then save.

## SEC And Provider Context

- For SEC EDGAR company-facts CSVs, call `summarize_sec_company_facts(path)`
  from `agents.quant_macro_stats` once per issuer. Do not infer company metrics
  from `select_dtypes`, positional numeric columns, or `.iloc[:, -1]`.
- For fuller company evidence, call `sec_company_facts_evidence(...)` with
  resolved SEC fact sources and optional macro overlay data. Use helper
  fields such as `latest_fundamentals`, `history_rows`, `trend_diagnostics`,
  `macro_overlay`, `company_macro_sensitivity`, `numeric_facts`, and
  `source_coverage`; `company_macro_sensitivity` is numeric/context evidence,
  not a prewritten company risk narrative.
- For company projection or stress questions, compose projection/scenario rows
  in `analysis.py` from `latest_fundamentals`, `history_rows`,
  trend diagnostics, macro overlay rows, and explicit caller assumptions; save
  the rows as generic top-level evidence with numeric facts, methods,
  limitations, and source coverage.
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
  `save_quant_outputs` may drop non-renderable charts before saving.
- Treat every run as authoritative for its own artifacts: build the current
  charts and evidence rows inside `analysis.py`, then save them once. Do not
  reuse prior `charts.json`, align output to an existing `report.json`, or
  merge a previous execution summary into the current handoff.
- Execution summaries should expose reusable evidence fields: `numeric_facts`,
  source paths, methods used, chart IDs, tables, model diagnostics,
  limitations, and source coverage.
- If you repeatedly write the same runtime code across generated
  `analysis.py` scripts, that pattern belongs in a common helper rather than
  another long script. Keep helpers deterministic, local-data-only, JSON-safe,
  and covered by focused tests.

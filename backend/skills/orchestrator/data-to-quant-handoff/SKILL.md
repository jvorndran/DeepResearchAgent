---
name: data-to-quant-handoff
description: Use before every quant-developer delegation for data_files, schema_summary, forecast, OLS, recession-window, and handoff payload rules.
---

# Data to Quant Handoff

Use this skill before every `quant-developer` delegation.

## Required task payload

The quant-developer task description must include:

- `job_id` copied verbatim.
- A compact JSON `data_files` map from series ID or metric name to absolute CSV path.
- `schema_summary` and row counts from data-engineer.
- The analysis goal and the full approved user request when relevant.

Tell quant-developer to paste the `data_files` JSON object into `analysis.py` as a single dictionary and reference paths by key, not by retyping long auto-saved filenames into separate string literals. Tell it to use those exact paths and not call `glob`, `ls`, or `read_file` to rediscover them.

When helper composition depends on the user's requested scope, include the full
approved user request in the task description. Quant-developer should write
`analysis.py`, call reusable helpers there, and compose any requested charts
from helper evidence rows rather than invoking a report-specific artifact
route.

## Econometric forecast handoff

For econometric forecast requests, especially six-month unemployment forecasts using yield curve, claims, payrolls, and industrial production:

- Tell quant-developer to align local series to monthly period keys.
- Tell it to derive predictor columns before modeling.
- Tell it to call `direct_ols_forecast(...)` from `agents.quant_macro_stats`.
- Do not ask it to import `statsmodels` directly or hand-roll OLS diagnostics/forecast tables.

## Recession windows

If the data handoff includes FRED `USREC`, pass the saved `USREC` CSV path in `data_files`. Quant-developer must not fetch recession dates itself.

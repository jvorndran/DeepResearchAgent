---
name: technical-writer-handoff
description: Use before every technical-writer delegation for plan_report_structure, write_research_report, execution_summary_json, charts_json, and compact quant handoffs.
---

# Technical Writer Handoff

Use this skill before every `technical-writer` delegation.

## Tool contract

The task description must explicitly say to call `plan_report_structure` first:

1. Call `plan_report_structure` first with `charts_json_path`, `execution_summary`, and `original_query`.
2. Then call `write_research_report`.
3. Then call `validate_research_report_file`.
4. Never call `read_file`, `ls`, `glob`, `grep`, `execute`, or `write_file`.

Use the full approved user request, not the condensed research summary or first sentence, as `original_query`.

If `plan_report_structure` returns truncated-looking text, use `execution_summary_for_draft` as-is and continue; do not try to recover by reading files.

## Compact quant handoff

If quant-developer returns `execution_summary_json`, pass that absolute path to technical-writer and tell it to use the file's contents as `execution_summary`. Do not ask quant-developer to restate or expand the full statistical summary inline.

A usable ordinary quant handoff does not need one chart for every user-requested concept. Accept a compact 3-4 chart handoff for non-chart-heavy prompts when it includes computed recession risk/regime, unemployment outlook, scenario/stress output, and source-context metadata; the technical-writer can cover remaining requested views with tables and prose grounded in `execution_summary_json`.

For explicit chart, chart-pack, dashboard, visual-evidence, or chart-validation prompts, require a nonempty chart handoff and generally expect 6-8 distinct chart IDs. Do not call technical-writer on an empty chart map for those prompts.

If the quant handoff has `"status":"failed"` or says quant-developer exceeded its script-write retry budget, do not immediately re-run quant-developer. For ordinary non-chart-heavy prompts, continue to technical-writer only when the returned `charts_json` and `execution_summary_json` paths contain usable artifacts and require explicit caveats about missing local quant artifacts. For chart-heavy prompts, stop after emitting a concise QA-rejected status that names quant-developer as the required recovery owner.

If `chart_ids` is empty, treat the quant handoff as incomplete rather than reusable. For chart-heavy prompts, make exactly one QA-driven quant-developer recovery delegation with the original `data_files` map and `schema_summary` before technical-writer. If that recovery delegation is blocked because the quant retry budget is already exhausted, stop after emitting a concise QA-rejected status; do not call technical-writer or quality-analyst again on the same failed quant artifacts.

If QA `required_fixes` say `execution_summary.json` lacks a requested analog
window, historical simulation, backtest row, or other computed coverage, route
that repair to `quant-developer` once before technical-writer. Do not ask the
writer to paper over missing computed windows with prose caveats.

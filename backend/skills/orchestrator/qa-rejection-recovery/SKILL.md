---
name: qa-rejection-recovery
description: Use after any quality-analyst rejection for retry limits, required_fixes handling, and writer-versus-quant recovery routing.
---

# QA Recovery Rules

1. **Rule of Three:** Max 3 retries per subagent. If the 3rd retry still fails or gets rejected, abort.
2. **Analysis:** Read `reason` and `required_fixes` from the `quality-analyst` JSON result. Do not re-run QA just to recover details and do not inspect artifacts yourself.
3. **Re-delegate:**
   - **Writer-owned fixes:** Send back to `technical-writer` for data fidelity failures in report prose, numerical discrepancies between report prose and `execution_summary`, citation/source coverage, framing, interpretation, formatting, chart-marker issues against existing chart IDs, sign/direction wording, and any contradiction where the report text conflicts with existing `execution_summary` numbers.
   - **Quant-owned fixes:** Send back to `quant-developer` when QA explicitly says computed artifacts are missing, stale, invalid, need recalculation/new analysis, a requested chart family or chart definition is missing from `charts.json`, or the report has zero chart definitions / missing `charts.json` for a chart-required request. Do not ask quant to patch narrative wording or inspect `report.json`.
4. **Mixed reasons:** If the QA reason says both report fidelity and computed artifacts are suspect, send the first recovery pass to `technical-writer` unless `required_fixes` explicitly names recalculation.
5. **Context:** Pass the exact `reason` and `required_fixes` to the subagent in the `task()`. For quant fixes, make the task text explicit: `QA rejected the report because computed artifacts are missing/invalid/stale...` and name the missing chart family or chart ID. For writer fixes, also pass the same `charts_json_path`, `execution_summary`, `data_sources`, and `original_query` used in the prior writer task so it can rewrite through `plan_report_structure` without direct file reads. The writer already has tools that load the execution summary safely; do not pre-read or summarize it for the writer. For quant fixes, pass the prior `data_files` map and `schema_summary` again.
6. **No general-purpose recovery:** Do not use `general-purpose` to read `execution_summary.json`, `charts.json`, or report artifacts after rejection.

---
name: qa-rejection-recovery
description: Concise rules for handling report rejections
triggers: [rejection, rejected, qa, fix, retry]
---

# QA Recovery Rules

1. **Rule of Three:** Max 3 retries per subagent. If the 3rd retry still fails or gets rejected, abort.
2. **Analysis:** Read `reason` and `required_fixes` from the `quality-analyst` JSON result. Do not re-run QA just to recover details.
3. **Re-delegate:**
   - **Writer-owned fixes:** Send back to `technical-writer` for prose, formatting, citation/source coverage, framing, interpretation, sign/direction wording, and any contradiction where the report text conflicts with existing `execution_summary` numbers.
   - **Quant-owned fixes:** Send back to `quant-developer` only when QA explicitly says computed artifacts are missing, stale, invalid, or need recalculation/new analysis. Do not ask quant to patch narrative wording or inspect `report.json`.
4. **Context:** Pass the `reason` and `required_fixes` to the subagent explicitly in the `task()`. For writer fixes, also pass the same `charts_json_path`, `execution_summary`, `data_sources`, and `original_query` used in the prior writer task so it can rewrite through `plan_report_structure` without direct file reads. For quant fixes, pass the prior `data_files` map and `schema_summary` again.

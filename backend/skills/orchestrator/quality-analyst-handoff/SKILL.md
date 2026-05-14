---
name: quality-analyst-handoff
description: Use before every quality-analyst delegation for QA review inputs, report_path, charts_json_path, execution_summary, and required_fixes contract.
---

# Quality Analyst Handoff

Use this skill before every `quality-analyst` delegation.

## Task contract

The quality-analyst task description must require compact JSON with:

- `status`
- `report_path`
- when rejected, `reason` and `required_fixes`

Pass the review inputs as metadata and paths, not raw data arrays:

- Absolute `report_json_path`
- Absolute `charts_json_path`
- `execution_summary` or the absolute `execution_summary_json` path returned by quant-developer
- `data_sources` metadata JSON
- `original_query` verbatim

Do not ask quality-analyst to edit files, read generated code, recompute statistics, or patch narrative prose. It reviews and returns a decision only. If it rejects the report, read `qa-rejection-recovery` before the next delegation.

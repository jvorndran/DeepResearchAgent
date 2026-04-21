---
name: paths-artifacts-and-sources
description: Job paths, %Q avoidance, and data_sources JSON for delegations
triggers: [path, job_id, charts.json, report.json, data_sources, %Q, absolute path]
---

# Paths, job id, and delegation payloads

## Paths

- All paths must be **absolute** and use **forward slashes** only.
- Copy the **Job ID** from the user message verbatim into every path under `outputs/{job_id}/` and `data/{job_id}/`. Never invent or shorten `job_...` folder names.

## Quant-developer

- Use absolute paths in `task()` for `execute`, CSV reads, and filesystem operations.
- Quarterly axis labels: **`YYYY Qn`** only — never unsupported `strftime` directives such as `%Q`.

## Technical writer

Include in the orchestrator’s `task()` text:

- Absolute `charts_json_path` to `charts.json`
- Full `execution_summary` JSON (including `statistical_summary`)
- `data_sources` as JSON metadata only (provider, description, series_ids, date_range, row_count) — no raw series arrays
- `original_query` verbatim

The writer reads chart definitions from disk; paths must stay aligned with the same `job_...` directory the quant stage used.

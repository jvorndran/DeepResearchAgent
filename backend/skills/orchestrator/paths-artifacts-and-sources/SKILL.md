---
name: paths-artifacts-and-sources
description: Use for every delegation involving job_id paths, charts.json, report.json, FRED auto-saved paths, quarterly labels, absolute paths, or data_sources JSON.
---

# Paths, job id, and delegation payloads

## Paths

- All paths must be **absolute** and use **forward slashes** only.
- Copy the **Job ID** from the user message verbatim into every output path under `/home/vorndranj/projects/DeepResearchAgent/backend/outputs/{job_id}/`. Never invent, shorten, or rename `job_...` folder names.
- Do not demand exact data filenames or job-folder copies from data-engineer. Use the saved paths it returns.
- If FRED returns `status:auto_saved`, the returned `file_path` (often under `/home/vorndranj/projects/DeepResearchAgent/backend/data/_auto/`) is already the canonical data path; pass it unchanged to quant-developer and do not call `save_data`.

## Quant-developer

- Use absolute paths in `task()` for `execute`, CSV reads, and filesystem operations.
- Quarterly axis labels: **`YYYY Qn`** only — never unsupported `strftime` directives such as `%Q`.

## Technical writer

Include in the orchestrator’s `task()` text:

- Absolute `charts_json_path` to `charts.json`
- Full `execution_summary` JSON (including `statistical_summary`). If the quant-developer returns an `execution_summary_json` path, pass that absolute path and instruct the technical writer to use its contents as the execution summary instead of asking the quant-developer to restate the full JSON inline.
- `data_sources` as JSON metadata only (provider, description, series_ids, date_range, row_count) — no raw series arrays
- `original_query` verbatim

The writer reads chart definitions from disk; paths must stay aligned with the same `job_...` directory the quant stage used.

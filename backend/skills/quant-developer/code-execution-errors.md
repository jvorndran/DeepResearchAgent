---
name: code-execution-errors
description: Concise rules for fixing common Python execution errors
triggers: [error, fix, retry, pandas, KeyError, FileNotFoundError]
---

# Fixes

## Pandas Resampling
- **Error:** `ValueError: Invalid frequency`
- **Fix:** Use `'QE'` for quarterly, `'ME'` for monthly. **NEVER** `'Q'` or `'M'`.

## File Paths
- **Error:** `FileNotFoundError`
- **Fix:** Always use the Windows absolute path provided by the Orchestrator for `read_csv`.

## Filesystem Tool Paths
- **Error:** `Windows absolute paths are not supported`
- **Fix:** `read_file`, `write_file`, `edit_file`, `ls`, and `glob` must use virtual `/projects/...` paths. Convert `C:\projects\DeepResearchAgent\...` to `/projects/DeepResearchAgent/...` first.

## Date Labels
- **Error:** Unsupported `strftime` directives such as `%Q`
- **Fix:** Build quarter labels with attributes, e.g. `f"{dt.year} Q{dt.quarter}"`. For month labels, use `f"{dt.year}-{dt.month:02d}"`.

## Data Merging
- **Error:** `KeyError: 'date'`
- **Fix:** Verify column names from the schema sample rows. Some sources use `Date` or `period`.

## Charts JSON
- **Error:** `JSONDecodeError`
- **Fix:** Ensure the `charts.json` is a dict keyed by `snake_case` IDs. Use `json.dumps(charts, indent=2)` to save.

**Rule:** Read `stderr` using `read_file`, apply fix via `edit_file`, and retry. Max 3 attempts.

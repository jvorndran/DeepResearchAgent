---
name: code-execution-errors
description: Concise rules for fixing common Python execution errors
triggers: [error, fix, retry, pandas, KeyError, FileNotFoundError]
---

# Fixes

## Pandas Resampling
- **Error:** `ValueError: Invalid frequency`
- **Fix:** For `.resample(...)`, use `'QE'` for quarterly and `'ME'` for monthly. For `.dt.to_period(...)` or `pd.Period(...)`, use `'Q'` and `'M'`; pandas Period conversion rejects `'QE'` and `'ME'`.

## File Paths
- **Error:** `FileNotFoundError`
- **Fix:** Always use the absolute path provided by the Orchestrator for `read_csv` and all filesystem tools.

## Date Labels
- **Error:** Unsupported `strftime` directives such as `%Q`
- **Fix:** Build quarter labels with attributes, e.g. `f"{dt.year} Q{dt.quarter}"`. For month labels, use `f"{dt.year}-{dt.month:02d}"`.

## Data Merging
- **Error:** `KeyError: 'date'`
- **Fix:** Verify column names from the schema sample rows. Some sources use `Date` or `period`.
- **Error:** `KeyError: 'value'` or `value_x`/`value_y` confusion after merging FRED series.
- **Fix:** FRED CSVs share a generic `value` column. Before any merge, reduce each frame to `date,value`, parse `date`, cast `value` with `pd.to_numeric(errors="coerce")`, drop null `date`/`value`, and rename `value` to the series ID or metric name.
- **Error:** `KeyError: 'value'` inside a growth/helper function after `load_fred(...)` succeeds.
- **Fix:** The loader already renamed `value`. Make helpers accept the renamed column, or infer the single non-date column before computing pct changes, peaks, troughs, or summaries.
- **Error:** Empty merge, `Data range: NaT to NaT`, or zero rows after combining daily FRED data with monthly/quarterly series.
- **Fix:** Do not merge month-end resample dates directly with month-start FRED dates, or quarter-end resample timestamps directly with quarter-start GDP dates. Aggregate higher-frequency data to the target frequency, create a shared period key such as `date.dt.to_period("M")` or `date.dt.to_period("Q")`, merge on that period key, then derive one consistent chart date from the period.
- **Error:** `TypeError: type NaTType doesn't define __round__ method` or chart JSON contains `NaN`/`NaT`.
- **Fix:** Only round/serialize values after `pd.notna(...)`; emit `None` for missing chart values. Drop nulls for scatter and period-stat rows that require both x and y values.
- **Error:** `ValueError: The truth value of a Series is ambiguous` after `resample(...).mean().iterrows()` or chart rows contain pandas Series objects.
- **Fix:** Select the metric column before resampling and iterate the resulting Series with `.items()`, e.g. `quarterly = df["metric"].resample("QE").mean()` then `for dt, value in quarterly.items()`. Do not use `pd.notna(row)` on `iterrows()` output from a one-column DataFrame.
- **Error:** `AttributeError` from typo variants such as `.fillname(...)`.
- **Fix:** Use pandas `.fillna(...)` for mapped optional display fields like colors or labels.
- **Error:** `KeyError` for a derived column such as `*_growth_*`, `*_forward_*`, `tight`, `period`, or a regime flag after filtering a dataframe.
- **Fix:** Check which dataframe owns the column. Derived columns must be created before making filtered `.copy()` subsets that reference them; otherwise rebuild the subset after adding the column, or explicitly assign the derived column onto the subset.
- **Anti-loop:** Do not keep moving unrelated code after the same missing-column traceback. Read the traceback, inspect the line that references the missing column, and patch the dataframe construction order once.

## Charts JSON
- **Error:** `JSONDecodeError`
- **Fix:** Ensure the `charts.json` is a dict keyed by `snake_case` IDs. Use `json.dumps(charts, indent=2)` to save.
- **Error:** `TypeError: Object of type Timestamp/Period/int64/float64 is not JSON serializable` or repeated `json.dump(..., default=...)` failures.
- **Fix:** Recursively sanitize the full charts and execution-summary objects before dumping: convert pandas timestamps to strings, periods to strings, numpy scalars to Python scalars, and `NaN`/`NaT` to `None`. Apply this to chart data, `referenceLines`, `referenceAreas`, and summary metrics.
- **Error:** `'list' object has no attribute 'keys'` during validation.
- **Fix:** The root of `charts.json` must be a dict keyed by chart ID, not a list of chart objects.

## Script Write/Repair Loop
- **Error:** `write_file` reports truncation, overwrite failure, or "already exists".
- **Fix:** Do not delete and rewrite with shell. Use `read_file`, then `edit_file` with the smallest exact replacement.
- **Fallback:** If two edits fail, write a compact replacement script to `analysis_v2.py`, execute that path, and keep the `charts.json` destination unchanged.

**Rule:** Read `stderr` using `read_file`, apply fix via `edit_file`, and retry. Max 3 attempts.

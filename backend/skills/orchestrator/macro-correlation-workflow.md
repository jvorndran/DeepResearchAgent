---
name: macro-correlation-workflow
description: Blueprint for FRED macro correlation queries
triggers: [GDP, unemployment, inflation, CPI, interest rate, FRED, macro, correlation]
---

# Macro Correlation Blueprint

## Data Engineer
1. **Search:** `fred_search` for series IDs (e.g., `GDPC1`, `UNRATE`).
2. **Fetch & Save:** `fred_get_series` → `save_data` for each series.
3. **Schema:** `extract_schema` on all files.

## Quant Developer
1. **Merge:** Inner join on "date".
2. **Stats:** Pearson r, p-value, Spearman rho (`scipy.stats`).
3. **Resample:** Resample to lower frequency (e.g., quarterly) before join.
4. **Paths:** Use Windows absolute paths for `execute` and `pandas.read_csv`, but `/projects/...` virtual paths for filesystem tools.
5. **Quarter Labels:** Format quarterly labels as `YYYY Qn`; never use unsupported `strftime` directives like `%Q`.
6. **Charts:** 
   - `time_series_overlay`: Line chart (both series).
   - `correlation_scatter`: Scatter chart (x=series1, y=series2).

## Technical Writer
- **Type:** `macro_indicator`
- **Focus:** Correlation coefficients, statistical significance, and "So What?" of the trend.

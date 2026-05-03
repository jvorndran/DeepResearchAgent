---
name: macro-correlation-workflow
description: Blueprint for FRED macro correlation queries
triggers: [GDP, unemployment, inflation, CPI, interest rate, FRED, macro, correlation]
---

# Macro Correlation Blueprint

## Data Engineer
1. **Search:** `fred_search` for series IDs (e.g., `GDPC1`, `UNRATE`).
2. **Recession windows:** If the request asks for recession-window summaries, NBER windows, regime classification, or recession bars/overlays, include FRED `USREC` (monthly NBER recession indicator) in the first fetch set unless the user named an equivalent recession indicator. Pass its saved CSV path to quant-developer as a normal data file; quant-developer should not fetch recession dates itself.
3. **Fetch:** `fred_get_series` for each series. If the result is `status:auto_saved`, keep the returned `file_path` and do not call `save_data`; call `save_data` only for successful results that were not already saved.
4. **Schema:** `extract_schema` on all files.

## Quant Developer
1. **Merge:** Inner join on "date".
2. **Stats:** Pearson r, p-value, Spearman rho (`scipy.stats`).
3. **Resample:** Resample to lower frequency (e.g., quarterly) before join.
4. **Mixed FRED frequencies:** When daily series are joined to monthly or quarterly series, aggregate first, add a shared period key such as `date.dt.to_period("M")` or `date.dt.to_period("Q")`, merge on that key, and only then derive display dates. Do not merge daily/month-end resample dates directly with month-start FRED observations.
5. **Recession windows:** Use the provided `USREC` local CSV and `recession_window_summary(...)` for window summaries. Do not call public FRED URLs from the quant script to recover missing recession dates.
6. **Paths:** Use absolute paths consistently for all tools (`execute`, `pandas.read_csv`, and filesystem tools).
7. **Quarter Labels:** Format quarterly labels as `YYYY Qn`; never use unsupported `strftime` directives like `%Q`.
8. **Charts:** 
   - `time_series_overlay`: Line chart (both series).
   - `correlation_scatter`: Scatter chart (x=series1, y=series2).

## Technical Writer
- **Type:** `macro_indicator`
- **Focus:** Correlation coefficients, statistical significance, and "So What?" of the trend.

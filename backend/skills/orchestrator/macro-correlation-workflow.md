---
name: macro-correlation-workflow
description: End-to-end delegation blueprint for macroeconomic correlation queries — FRED series, Pearson/Spearman analysis, scatter + time-series charts
triggers:
  - GDP
  - unemployment
  - inflation
  - CPI
  - interest rate
  - FRED
  - macroeconomic
  - macro
  - correlation
  - federal reserve
  - monetary policy
  - economic indicator
---

# Macro Correlation Workflow

Use this workflow when the query asks to correlate two or more macroeconomic indicators.

## Phase 2 — Data Engineer Task

```
Fetch two FRED time series and save each as a separate CSV:
1. Search for series IDs using fred_search if needed (e.g. "real GDP quarterly")
2. Fetch: fred_get_series("GDPC1"), then save_fmp_data(ticker="GDPC1", data_type="real_gdp_quarterly")
3. Fetch: fred_get_series("UNRATE"), then save_fmp_data(ticker="UNRATE", data_type="unemployment_rate")
4. extract_schema on both files
Return: data_files dict, row_counts, column schemas
```

Common series pairs:
- GDP growth vs unemployment: `GDPC1` + `UNRATE`
- Inflation vs interest rates: `CPIAUCSL` + `FEDFUNDS`
- GDP vs CPI: `GDPC1` + `CPIAUCSL`
- Employment vs wages: `PAYEMS` + `AHETPI`

## Phase 3 — Quant Developer Task

```
Perform correlation analysis on the two FRED series:
- Data files: [<path1>, <path2>] (Windows absolute paths)
- Schemas: [<schema1>, <schema2>]
- Job ID: {job_id}

Analysis to perform:
1. Merge both DataFrames on "date" column (inner join)
2. Compute Pearson r and p-value (scipy.stats.pearsonr)
3. Compute Spearman rho as robustness check
4. Identify recession periods (date ranges where GDP contracted QoQ) and note if correlation tightens

Charts to produce (save to outputs/{job_id}/charts.json):
- "time_series_overlay": line chart — both series over time on shared x-axis (normalize to % change if units differ)
- "correlation_scatter": scatter chart — x=series1, y=series2, each point labeled by year

Print stdout summary: {correlation_coefficient, p_value, spearman_rho, n_observations, key_finding, chart_ids}
```

## Phase 4 — Technical Writer Task

```
analysis_type = "macro_indicator"
```

Pass: `charts_json_path`, `execution_summary`, `data_sources` (both FRED series with date ranges), `original_query`, `job_id`.

`data_sources` format:
```json
[
  {"provider": "FRED", "description": "Real GDP (GDPC1)", "tickers": ["GDPC1"], "date_range": {"start": "2000", "end": "2024"}, "row_count": 96},
  {"provider": "FRED", "description": "Unemployment Rate (UNRATE)", "tickers": ["UNRATE"], "date_range": {"start": "2000", "end": "2024"}, "row_count": 288}
]
```

## Gotchas

- FRED series have different frequencies (GDP=quarterly, UNRATE=monthly) — tell the quant developer to resample to the lower frequency before correlating
- Normalize to % change or z-score when units differ (billions of dollars vs percentage points)
- Pearson requires near-normal distributions — if distributions are skewed, Spearman rho is more meaningful

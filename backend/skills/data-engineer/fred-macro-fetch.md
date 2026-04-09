---
name: fred-macro-fetch
description: Workflow for fetching macroeconomic time-series data from the FRED MCP Server
triggers:
  - FRED
  - macroeconomic
  - macro data
  - GDP
  - inflation
  - CPI
  - unemployment
  - interest rates
  - federal reserve
  - economic indicators
  - fred_get_series
---

# FRED MCP Data Fetch Workflow

## When to Use FRED vs FMP

| Data Type | Use |
|-----------|-----|
| GDP, CPI, PCE, inflation, interest rates, unemployment, money supply, trade balance | **FRED** |
| Stock quotes, financial statements, earnings, market cap | **FMP** |
| Mixed queries (e.g., "compare AAPL revenue with GDP growth") | **Both** |

## Available FRED Tools

- `fred_browse` — Browse available FRED categories and series
- `fred_search(query)` — Search for series by keyword (e.g., "unemployment rate", "real GDP")
- `fred_get_series(series_id)` — Fetch time-series data for a FRED series ID

## Common Series IDs

| Series ID | Description | Frequency |
|-----------|-------------|-----------|
| `GDPC1` | Real GDP (chained 2017 dollars) | Quarterly |
| `GDP` | Nominal GDP | Quarterly |
| `CPIAUCSL` | CPI All Items (seasonally adjusted) | Monthly |
| `PCEPI` | PCE Price Index | Monthly |
| `FEDFUNDS` | Federal Funds Rate | Monthly |
| `UNRATE` | Unemployment Rate | Monthly |
| `DGS10` | 10-Year Treasury Yield | Daily |
| `M2SL` | M2 Money Supply | Monthly |
| `BAAA` | Moody's Aaa Corporate Bond Yield | Monthly |

## Mandatory Workflow

```
1. fred_search("real GDP growth")     # If series ID is unknown
2. fred_get_series("GDPC1")           # Fetch the series
3. save_fmp_data(
       data=<result>,
       ticker="GDPC1",               # Use series ID as ticker
       data_type="real_gdp_quarterly" # Descriptive data_type
   )
4. extract_schema(file_paths=[<saved_path>])
```

The `job_id` is injected automatically from runtime context; do not pass it as an argument to `save_fmp_data`.

## CSV Output Schema

FRED data saved to CSV has this column structure:
```
date          value    series_id    title                    units     frequency
2024-01-01    28000.0  GDPC1        Real Gross Domestic...   Bil. Ch.  Quarterly
```

- `date`: YYYY-MM-DD string — parse with `pd.to_datetime(df["date"])`
- `value`: float — the actual data point
- Additional metadata columns: `series_id`, `title`, `units`, `frequency`, etc.

**Do NOT use `json.loads()` on any column** — the data is already in flat tabular rows.

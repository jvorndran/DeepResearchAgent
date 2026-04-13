---
name: fred-macro-fetch
description: Concise workflow for fetching FRED macro data
triggers: [FRED, macro, GDP, inflation, CPI, unemployment, interest rates]
---

# FRED Workflow

1. **Search:** `fred_search(query="real GDP")` if ID unknown.
2. **Fetch:** `fred_get_series(series_id="GDPC1")`.
3. **Save:** `save_data(data=<result>, ticker="GDPC1", data_type="gdp")`.
4. **Schema:** `extract_schema(file_paths=[<saved_path>])`.

## Common IDs
- `GDPC1`: Real GDP
- `CPIAUCSL`: CPI
- `UNRATE`: Unemployment
- `FEDFUNDS`: Fed Funds Rate
- `DGS10`: 10-Year Treasury Yield

**Rule:** `save_data` immediately after `fred_get_series`. Return only the JSON summary.

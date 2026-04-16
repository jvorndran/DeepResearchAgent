---
name: fred-macro-fetch
description: Concise workflow for fetching FRED macro data
triggers: [FRED, macro, GDP, inflation, CPI, unemployment, interest rates]
---

# FRED Workflow

> **Mandatory:** Always call `fred_search` before `fred_get_series` — even for
> well-known series IDs. Never assume or recall a series ID; always verify it first.
> Skipping this step causes 400 errors from the FRED API.

1. **Search:** `fred_search(query="real GDP")` — use the `id` field from the result as your series ID.
2. **Fetch:** `fred_get_series(series_id=<id from search result>)`.
3. **Save:** Only after a successful fetch, pass the tool output exactly as returned into `save_data(...)`. If the fetch result is a compact pointer JSON, do not expand it first: `save_data(data=<fetch_result>, ticker="GDPC1", data_type="gdp")`.
4. **Schema:** `extract_schema(file_paths=[<saved_path>])`.

## Recovery

- You may make up to 3 MCP attempts total for the same macro data objective.
- If a FRED tool returns JSON with `"status":"error"`, do not call `save_data` on it.
- If `fred_get_series` fails with a 400 error, it almost always means the series ID is wrong. Go back to `fred_search` with a refined query and use the ID returned from there.
- Never repeat the exact same failed FRED request verbatim.

## Common IDs
- `GDPC1`: Real GDP
- `CPIAUCSL`: CPI
- `UNRATE`: Unemployment
- `FEDFUNDS`: Fed Funds Rate
- `DGS10`: 10-Year Treasury Yield

**Rules:**
- Always `fred_search` → `fred_get_series` → `save_data`. Never skip the search step.
- Never paste raw series arrays into chat; rely on the returned pointer/file flow and return only the JSON summary.

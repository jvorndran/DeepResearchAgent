---
name: fred-macro-fetch
description: Concise workflow for fetching FRED macro data
triggers: [FRED, macro, GDP, inflation, CPI, unemployment, interest rates]
---

# FRED Workflow

**Do not spam `fred_search`.** One search per distinct series unless the first returned no usable IDs or `fred_get_series` failed with a bad ID.
Assistant message content must be empty while calling tools. Do not narrate setup, say "Now...", or describe the next tool call.
Do not call shell or filesystem tools for FRED fetches. `fred_get_series` may return `status:auto_saved` with an already persisted CSV path; use that path directly. `save_data` is only for successful fetch results that were not already auto-saved. Do not create directories or rewrite cleaned `date,value` CSV copies.

1. **Search (once per series):** `fred_search(query="...")` — use a `series_id` from the result.
2. **Fetch immediately:** `fred_get_series(series_id=<id>)` — do not run another search to refine wording if you already have candidates.
3. **Save:** If the fetch returns `status:auto_saved`, keep its `file_path` and do not call `save_data`. Otherwise pass the successful fetch output into `save_data(...)` as returned (external pointer JSON is OK).
4. **Schema:** `extract_schema(file_paths=[<saved_path>])` if needed.

## Real Wage Requests

If the request asks for real wages, real average hourly earnings, or inflation-adjusted earnings, verify that the chosen FRED earnings series title or units explicitly says real/inflation-adjusted. Do not label nominal average-hourly-earnings series such as `AHETPI` as real. If no exact real hourly earnings series is found within the search budget, save the best nominal earnings series plus a FRED price index such as `CPIAUCSL`, and mark the handoff metadata so quant-developer deflates nominal earnings before analyzing real wage gains.

## Recovery

- Up to **3 MCP tool calls total** per macro objective (every `fred_search` and `fred_get_series` counts).
- If `fred_get_series` returns 400 / invalid series, **one** follow-up `fred_search` with a clearer query is allowed, then `fred_get_series` again — not five parallel searches.
- If a tool returns JSON with `"status":"error"`, do not call `save_data` on it.

## Common IDs (still use one search per task policy unless orchestrator already fixed the ID)

Reference only — your workflow is search → get_series → save, not search → search → search.

| ID | Series |
|----|--------|
| GDPC1 | Real GDP |
| CPIAUCSL | CPI |
| UNRATE | Unemployment |
| FEDFUNDS | Fed Funds |
| DGS10 | 10Y Treasury |

Never paste raw arrays into chat; return only the JSON summary with paths.

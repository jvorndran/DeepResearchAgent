---
name: census-regional-context
description: Fetch no-key Census regional context without invalid state filters
triggers: [Census, state, county, regional, median income, population, housing]
---

# Census Regional Context Workflow

State/county demographics, income, population, and housing context use Census public data via `census_get_table`.

- **CENSUS REGIONAL CONTEXT:** Use Census for population, median household
  income, housing units, and median home value context. `census_get_table` saves
  Census CSVs and returns `data_files`; do not call `save_data` afterward.
- Scope is strict: dataset `2023/acs/acs5/profile`, geography `state` or
  `county`, variables/aliases `population`, `median_income`, `housing_units`,
  and `median_home_value`. Limit: 50 variables per query and 500 queries per IP
  per day; batch where feasible.
- State comparisons: call `geography="state"` once with no `state` filter.
  State geography does not accept a state filter. County comparisons: use
  `geography="county"` with `state="SS"`. Use `state="SS"` only when narrowing
  county geography.
- Treat Census `error_type:provider_payload_unusable` or `retryable:false` as
  terminal for the current data objective. Preserve the compact error in
  `metadata.fetch_errors`, do not retry with a narrower variable set, and do not
  switch to paid providers.
- For regional consumer-stress questions, Census state income/population/housing data is the regional context; do not chase additional state-level FRED income/demographic series unless the user explicitly asked for a named regional FRED series. Pair the Census table with a small national FRED macro set and return paths for downstream merge/analysis.
- If Census returns `status:disabled` or `status:error`, report the
  regional-data caveat, do not switch to paid providers, and do not replace the
  failed Census context with broad state-level FRED unemployment, income, GDP,
  HPI, or demographic sweeps.

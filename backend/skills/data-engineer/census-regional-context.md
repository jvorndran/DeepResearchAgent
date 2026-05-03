---
name: census-regional-context
description: Fetch no-key Census regional context without invalid state filters
triggers: [Census, state, county, regional, median income, population, housing]
---

# Census Regional Context Workflow

Use `census_get_table` for state/county demographics, income, population, and
housing context.

- State comparisons: call `census_get_table(..., geography="state")` once with
  no `state` filter, then let downstream analysis filter the saved all-states
  CSV to the requested states. State geography does not accept a state filter.
- County comparisons: use `geography="county"` with `state="SS"` when a single
  state's counties are needed.
- Keep variables to the supported aliases such as `population`,
  `median_income`, `housing_units`, and `median_home_value`.
- The tool saves a CSV and returns `data_files`; do not call `save_data`
  afterward and do not switch to paid providers if Census returns an error.

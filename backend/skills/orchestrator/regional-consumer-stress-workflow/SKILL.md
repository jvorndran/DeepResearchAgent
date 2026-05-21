---
name: regional-consumer-stress-workflow
description: Use for regional or state-level US consumer-stress requests involving Census, income, population, housing, by-state, or regional context.
---

# Regional Consumer-Stress Workflow

Use this skill for requests asking whether US consumers are under stress "regionally", "by state", or with Census income/population/housing context.

## Data Engineer

- Require exactly one batched `census_get_table` state table for regional context.
- Pair it with a small national FRED macro set, at most 6 series such as unemployment, real disposable income, saving rate, consumer credit delinquencies, sentiment, and house prices.
- Explicitly forbid broad state-level FRED sweeps for unemployment, GDP, HPI, income, or demographics unless the user names specific states or specific regional FRED series.

## Quant Developer

- Keep regional context compact. Prefer summary rows and a small state ranking table over wide state-by-month panels.
- Preserve Census metadata and row counts in `execution_summary` for writer source coverage.
- For any state, regional, or place-specific request, preserve
  `requested_geography_coverage` in `execution_summary` using structured
  regional evidence (`regional_top10`, `state_comparison`, or
  `consumer_stress.regional_context`) or structured unavailable-source evidence
  from `source_coverage` / `metadata.fetch_errors`; do not rely on a freeform
  caveat string alone.

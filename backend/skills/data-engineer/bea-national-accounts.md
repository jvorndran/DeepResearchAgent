---
name: bea-national-accounts
description: Fetch keyed BEA NIPA tables for GDP, income, consumption, and corporate-profits evidence
triggers: [BEA, NIPA, GDP, GDI, personal income, PCE, corporate profits, national accounts]
---

# BEA National Accounts Workflow

First-party national-accounts evidence uses BEA NIPA tables via
`bea_get_nipa_table`.

- **BEA NATIONAL ACCOUNTS:** Use BEA for GDP, real GDP, personal income,
  personal consumption expenditures, and corporate profits when the query needs
  first-party national-accounts evidence. `bea_get_nipa_table` saves BEA CSVs
  and returns `data_files`; do not call `save_data` afterward.
- Supported tables: `T10101` real GDP percent change, `T10105` current-dollar
  GDP, `T10106` real GDP chained dollars, `T20100` personal income and its
  disposition, `T20305` PCE by major product type, and `T61600D` corporate
  profits by industry. Use optional `line_numbers` for focused component rows.
- Supported frequencies are `Q` and `A`. Keep the BEA frequency explicit and
  have quant-developer align quarterly BEA data with monthly FRED/BLS data
  through a declared transform; do not silently forward-fill or mix periods.
- BEA requires `BEA_API_KEY` or `BEA_USER_ID`. If BEA returns
  `status:disabled` or `status:error`, preserve the compact payload in
  `metadata.fetch_errors`; use FRED only as an active-provider fallback when BEA
  is unavailable and the fallback limitation is explicit.
- Preserve BEA source descriptors from the CSV: `table_name`, `concept_id`,
  `line_number`, `frequency`, `units`, `unit_mult`, `release_cadence`, and
  `revision_policy`.

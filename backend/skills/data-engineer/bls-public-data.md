---
name: bls-public-data
description: Fetch no-key BLS public labor, wage, CPI/PPI, employment, or productivity source checks
triggers: [BLS, labor, wages, CPI, PPI, employment, productivity, source reconciliation]
---

# BLS Public Data Workflow

Direct BLS labor, wage, CPI/PPI, employment, productivity source checks use BLS
public data via tools `bls_search_known_series`, `bls_get_series`.

- **BLS DIRECT SOURCE CHECKS:** Use `bls_get_series` for direct BLS data, source
  reconciliation against FRED, or BLS definitions for
  labor/wages/CPI/PPI/employment/productivity. If the ID is unknown, call
  `bls_search_known_series` once, then fetch the best candidate.
- `bls_get_series` saves BLS CSVs and returns `data_files`; do not call
  `save_data` afterward.
- BLS Public Data API v1 requires no key but has limited metadata. Use returned
  curated metadata for direct-BLS versus FRED source differences.
- Keep no-key requests to a 10-year-or-smaller window; for longer histories,
  prefer FRED plus a focused BLS recent-window check.

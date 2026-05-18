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
- For production/nonsupervisory earnings, keep the source ID and units explicit:
  `CES0500000008` is average hourly earnings (`dollars per hour`), while
  `CES0500000030` is average weekly earnings (`dollars per week`). Do not
  substitute the weekly series for an hourly wage comparison.
- `bls_get_series` normalizes partial or over-wide no-key year windows to one
  explicit 10-year-or-smaller direct-source check and returns the requested
  versus applied window in metadata. Do not retry the same BLS objective after
  that normalization; for longer histories, prefer FRED plus the focused BLS
  recent-window check.
- If BLS returns `retryable:false`, preserve the compact error in
  `metadata.fetch_errors` and continue with FRED or other active public sources.

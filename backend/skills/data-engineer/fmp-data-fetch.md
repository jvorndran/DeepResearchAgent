---
name: fmp-data-fetch
description: Disabled FMP workflow; do not fetch FMP data
triggers: [FMP, stock data, income statement, balance sheet, cash flow, price]
---

# FMP Disabled

FMP remains disabled and unavailable for data-engineer.

- Do not call FMP tools, enable FMP toolsets, request FMP credentials, or switch
  to paid/keyed providers.
- Do not fetch stock quotes, market data, analyst estimates, or FMP-backed
  financial statements.
- For public-company fundamentals, use `sec_fetch_company_facts` only when the
  SEC provider is selected. If SEC EDGAR does not cover the requested concept,
  return a compact limitation in `metadata.fetch_errors`.

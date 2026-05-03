---
name: sec-edgar-company-facts
description: Concise workflow for SEC no-key public-company fundamentals
triggers: [SEC, EDGAR, company facts, revenue, net income, margin, cash flow, assets, liabilities, shares, CIK, ticker]
---

# SEC EDGAR Company Facts Workflow

Use `sec_fetch_company_facts` for issuer-level SEC facts only: revenue, net income, gross profit, operating income, operating cash flow, capital expenditures, R&D expense, SG&A expense, diluted EPS, cash, securities, debt, equity, assets, liabilities, shares, and recent 10-K/10-Q filing metadata.

1. **Fetch:** `sec_fetch_company_facts(identifier=<ticker_or_cik>, periods<=5)`.
2. **Handoff:** The tool saves a parsed fiscal-year fundamentals CSV and returns `data_files`, `row_counts`, `schema_summary`, and SEC metadata. Use that path directly.
3. **Citations:** Tell downstream agents to cite SEC `data.sec.gov` companyfacts/submissions endpoints from the tool metadata.

## Boundaries

- SEC EDGAR requires no API key; do not add keys, OAuth, signup flows, or paid providers.
- Do not call `save_data` after a successful SEC result and do not try to create arbitrary JSON exports; the returned CSV path is canonical.
- Do not use SEC EDGAR for stock prices, analyst estimates, market data, or non-filing fundamentals.
- Preserve blank filing concepts as explicit limitations; do not fill missing margin, cash-flow, or balance-sheet fields from memory.
- If the tool returns `status:disabled`, report that SEC EDGAR is disabled and do not switch to FMP.
- If the tool returns `status:error`, fix malformed ticker/CIK input once if obvious; otherwise report the compact error.

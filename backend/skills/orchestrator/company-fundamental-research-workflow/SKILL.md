---
name: company-fundamental-research-workflow
description: Use for public-company or ticker fundamental research, business quality, financial health, balance sheet, cash-flow, margin, SEC, 10-K, and 10-Q requests.
---

# Company Fundamental Research Blueprint

## Scope
Use this workflow when the user asks for deep fundamental research on a public company or ticker.

Use current available company filing data only. Do not add macroeconomic, regional, labor, inflation, rates, recession, World Bank, BLS, Census, market-price, analyst-estimate, transcript, or news data unless the user explicitly asks for those sources.

## Data Engineer
1. **SEC-only fetch:** Delegate ticker/CIK fundamentals to data-engineer with SEC EDGAR scope only.
2. **Periods:** Use `sec_fetch_company_facts(identifier=<ticker_or_cik>, periods=10)`.
3. **Fields:** Request revenue, net income, gross profit, operating income, operating cash flow, capital expenditures, cash, securities, current debt, long-term debt, equity, assets, liabilities, shares, and 10-K/10-Q filing metadata.
4. **Handoff:** Return saved paths, row counts, schema summary, filing metadata, company name, ticker, CIK, and SEC source metadata.
5. **Boundary:** Do not request FRED, BLS, World Bank, Census, FMP, stock quotes, valuation multiples, analyst estimates, transcripts, or news.

## Quant Developer
1. **Merge:** Sort SEC fiscal-year fundamentals ascending before calculating trends.
2. **Growth:** Calculate revenue growth and available CAGR windows.
3. **Profitability:** Calculate gross, operating, and net margin trends when source fields are available.
4. **Cash generation:** Calculate operating cash flow margin, capex intensity, free-cash-flow proxy as operating cash flow minus capital expenditures, and free-cash-flow margin.
5. **Balance sheet:** Calculate cash and securities trend, current debt, long-term debt, total debt, debt/assets, liabilities/assets, and equity/assets.
6. **Efficiency:** Calculate asset turnover if revenue and assets exist.
7. **Share count:** Use `share_count_diagnostics` from the SEC helper before
   writing a dilution/buyback proxy. Raw SEC share counts are not split-adjusted;
   when diagnostics mark the full series as split-affected or uncomparable, do
   not ask for or accept a full-period buyback/dilution label.
8. **Diagnostics:** Include filing coverage, period coverage, and missing-field diagnostics in the execution summary.
9. **Charts:**
   - `income_statement_trend`: Revenue, gross profit, operating income, and net income.
   - `margin_trend`: Gross, operating, and net margins.
   - `cash_flow_trend`: Operating cash flow, capex, and free-cash-flow proxy.
   - `balance_sheet_trend`: Assets, liabilities, equity, and debt.
   - `share_count_trend`: Shares outstanding.

## Technical Writer
- **Type:** `company_fundamental_research`
- **Structure:** Filing coverage and source limitations; growth profile; profitability quality; cash generation and reinvestment; balance-sheet strength; dilution or buyback signal; overall fundamental quality assessment; data limitations.
- **Caveats:** State clearly when market price, valuation multiples, analyst estimates, earnings call transcripts, recent news, segment-level detail, or management commentary are unavailable from the current SEC-only source set.

---
name: equity-earnings-workflow
description: Blueprint for company financial statement and earnings queries
triggers: [revenue, earnings, income statement, EPS, margin, AAPL, MSFT, TSMC, ticker]
---

# Equity Earnings Blueprint

## Data Engineer
1. **SEC fundamentals:** Delegate ticker/CIK fundamentals to data-engineer with SEC EDGAR scope only: revenue, net income, gross profit, operating income, operating cash flow, capital expenditures, R&D expense, SG&A expense, diluted EPS, cash, debt, equity, assets, liabilities, shares, and 10-K/10-Q filing metadata.
2. **Fetch:** Use `sec_fetch_company_facts(identifier=<ticker_or_cik>, periods<=5)`.
3. **Boundary:** Do not request FMP, stock quotes, analyst estimates, or paid-provider market data.

## Quant Developer
1. **Merge:** Sort SEC fiscal-year fundamentals ascending before calculating trends.
2. **Analysis:** YoY revenue growth, net margin when revenue and net income are available, balance-sheet leverage from assets/liabilities, and share-count trend.
3. **Charts:** 
   - `revenue_trend`: Bar chart.
   - `margin_trend`: Line chart (gross vs net %).

## Technical Writer
- **Type:** `earnings_analysis`
- **Focus:** Growth rates, profitability ratios, and operational efficiency.

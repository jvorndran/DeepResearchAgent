---
name: equity-earnings-workflow
description: Blueprint for company financial statement and earnings queries
triggers: [revenue, earnings, income statement, EPS, margin, AAPL, MSFT, TSMC, ticker]
---

# Equity Earnings Blueprint

## Data Engineer
1. **Statements:** `getIncomeStatement`, `getBalanceSheetStatement`, `getCashFlowStatement`.
2. **Fetch:** Use `FY` (annual) or `Q1-Q4` (quarterly). `limit ≤ 5`.
3. **Save & Schema:** `save_data` → `extract_schema`.

## Quant Developer
1. **Merge:** Sort by "date" ascending before calculating trends.
2. **Analysis:** YoY revenue growth, gross margin %, net margin %.
3. **Charts:** 
   - `revenue_trend`: Bar chart.
   - `margin_trend`: Line chart (gross vs net %).

## Technical Writer
- **Type:** `earnings_analysis`
- **Focus:** Growth rates, profitability ratios, and operational efficiency.

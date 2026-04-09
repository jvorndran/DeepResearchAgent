---
name: equity-earnings-workflow
description: End-to-end delegation blueprint for equity earnings and financial statement queries — FMP income/balance/cash flow, revenue trends, margin analysis
triggers:
  - revenue
  - earnings
  - income statement
  - EPS
  - margin
  - net income
  - operating income
  - cash flow
  - balance sheet
  - financial statements
  - AAPL
  - MSFT
  - TSMC
  - stock
  - equity
  - ticker
---

# Equity Earnings Workflow

Use this workflow when the query analyzes a company's financial performance over time.

## Phase 2 — Data Engineer Task

```
Fetch financial statement data for {ticker} using the pre-enabled statements toolset:
1. getIncomeStatement(symbol="{ticker}", period="FY", limit=5)
   → save_fmp_data(ticker="{ticker}", data_type="income_statement")
2. (if margins needed) getCashFlowStatement(symbol="{ticker}", period="FY", limit=5)
   → save_fmp_data(ticker="{ticker}", data_type="cash_flow")
3. extract_schema on all saved files
Return: data_files, row_counts, column schemas
```

Key FMP column names (camelCase — exact):
- Revenue: `revenue` or `totalRevenue`
- Net income: `netIncome`
- Operating income: `operatingIncome`
- Gross profit: `grossProfit`
- EPS diluted: `epsdiluted`
- Free cash flow: `freeCashFlow`
- Date: `date` (fiscal year end, YYYY-MM-DD)

**Period note**: `"FY"` = full fiscal year. For quarterly, use `"Q1"`/`"Q2"`/`"Q3"`/`"Q4"`. Max `limit=5`.

## Phase 3 — Quant Developer Task

```
Perform earnings trend analysis for {ticker}:
- Data files: [<income_statement_path>] (Windows absolute paths)
- Schemas: [<schema>]
- Job ID: {job_id}

Analysis to perform:
1. Compute YoY revenue growth: (revenue[t] - revenue[t-1]) / revenue[t-1]
2. Compute gross margin: grossProfit / revenue
3. Compute net margin: netIncome / revenue
4. (optional) Compute FCF margin if cash flow data provided

Charts to produce (save to outputs/{job_id}/charts.json):
- "revenue_trend": bar chart — revenue by fiscal year
- "margin_trend": line chart — gross margin % and net margin % by year (two series)

Print stdout summary: {revenue_cagr, latest_gross_margin, latest_net_margin, yoy_growth_rates, chart_ids}
```

## Phase 4 — Technical Writer Task

```
analysis_type = "earnings_analysis"
```

`data_sources` format:
```json
[{"provider": "FMP MCP Server", "description": "Annual income statement for AAPL", "tickers": ["AAPL"], "date_range": {"start": "2020", "end": "2024"}, "row_count": 5}]
```

## Multi-Ticker Comparison

When comparing two tickers (e.g. AAPL vs MSFT):
1. Fetch and save each ticker's income statement separately
2. Tell quant developer to merge on fiscal year (inner join on normalized year)
3. Produce a grouped bar chart comparing the key metric side by side
4. Use `analysis_type = "sector_comparison"` for the technical writer

## Gotchas

- FMP returns most recent year first — tell quant developer to `df.sort_values("date")` to get chronological order
- Revenue is in USD thousands or millions depending on the company — check units from the schema sample rows
- EPS is already per-share — no normalization needed

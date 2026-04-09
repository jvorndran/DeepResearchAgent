---
name: sector-comparison-workflow
description: End-to-end delegation blueprint for multi-ticker sector comparison queries — peer benchmarking, grouped bar charts, relative positioning
triggers:
  - sector
  - compare
  - comparison
  - peer
  - vs
  - versus
  - multiple tickers
  - benchmark
  - relative
  - industry
  - competitors
---

# Sector Comparison Workflow

Use this workflow when comparing a metric across two or more companies or tickers.

## Phase 2 — Data Engineer Task

Fetch the same statement type for each ticker. Save each as a separate file.

```
For each ticker in [{ticker1}, {ticker2}, ...]:
  1. getIncomeStatement(symbol="{ticker}", period="FY", limit=5)
     → save_fmp_data(ticker="{ticker}", data_type="income_statement")
  2. extract_schema on each file

Return: data_files dict (one entry per ticker), row_counts per ticker, schemas
```

For ratio-based comparison (P/E, ROE, ROIC):
```
1. enable_toolset("company") first
2. getKeyMetrics(symbol="{ticker}", period="FY", limit=5)
   → save_fmp_data(ticker="{ticker}", data_type="key_metrics")
```

## Phase 3 — Quant Developer Task

```
Perform sector comparison for {metric} across {tickers}:
- Data files: {ticker1: path1, ticker2: path2, ...} (Windows absolute paths)
- Schemas: [<schemas>]
- Job ID: {job_id}
- Metric to compare: {metric} (e.g. "revenue", "netIncome", "grossProfit")

Analysis to perform:
1. Load each ticker's CSV, sort by date ascending
2. Merge into a single wide DataFrame: columns = [year, {ticker1}_{metric}, {ticker2}_{metric}, ...]
3. Compute relative positioning: which ticker leads in each year
4. Compute CAGR for each ticker over the period

Charts to produce (save to outputs/{job_id}/charts.json):
- "comparison_bar": grouped bar chart — {metric} by year, one bar series per ticker
- "relative_share": (optional) 100% stacked bar showing proportional split

Print stdout summary: {leader, cagr_per_ticker, latest_values_per_ticker, chart_ids}
```

## Phase 4 — Technical Writer Task

```
analysis_type = "sector_comparison"
```

`data_sources` format (one entry per ticker):
```json
[
  {"provider": "FMP MCP Server", "description": "Annual income for AAPL", "tickers": ["AAPL"], "date_range": {"start": "2020", "end": "2024"}, "row_count": 5},
  {"provider": "FMP MCP Server", "description": "Annual income for MSFT", "tickers": ["MSFT"], "date_range": {"start": "2020", "end": "2024"}, "row_count": 5}
]
```

## Gotchas

- Different tickers may have different fiscal year ends — merge on calendar year (extract year from date) rather than exact date
- Revenue units: most large-caps report in millions — verify from sample rows, don't assume
- When one company is much larger (e.g. AAPL vs small-cap), absolute comparison is misleading — tell quant developer to also compute YoY growth rates as a normalized comparison
- Limit 5 rows per ticker — if user requests 10 years, acknowledge you're showing the most recent 5

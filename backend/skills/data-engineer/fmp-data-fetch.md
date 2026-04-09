---
name: fmp-data-fetch
description: Complete workflow for fetching equity and financial statement data from the FMP MCP Server
triggers:
  - FMP
  - financial data
  - stock data
  - income statement
  - balance sheet
  - cash flow
  - historical price
  - getIncomeStatement
  - getHistoricalPrice
  - equity data
  - financial statements
---

# FMP MCP Data Fetch Workflow

## Tool Categories and Enablement

The `statements` toolset is **pre-enabled** at startup. These tools are ready immediately:
- `getIncomeStatement(symbol, period, limit)` — revenue, net income, margins
- `getBalanceSheetStatement(symbol, period, limit)` — assets, liabilities, equity
- `getCashFlowStatement(symbol, period, limit)` — operating/investing/financing cash flow
- `getKeyMetrics(symbol, period, limit)` — EPS, P/E, ROE, ROIC, FCF yield
- `getRatios(symbol, period, limit)` — liquidity, profitability, valuation ratios

Other toolsets must be enabled first with `enable_toolset(name=...)`:
- `charts` → `getHistoricalPrice`, `getDividendHistory`
- `quotes` → `getQuote`, `getBatchQuote`
- `company` → `getCompanyProfile`, `getStockList`
- `economics` → `getEconomicIndicators`

## Period Normalization

**Only these period values are valid**: `"FY"`, `"Q1"`, `"Q2"`, `"Q3"`, `"Q4"`

Common aliases and their correct equivalents:
- `"annual"` → `"FY"`
- `"yearly"` → `"FY"`
- `"quarterly"` → `"Q1"` (use Q1/Q2/Q3/Q4 for specific quarters)

The API returns a 402 error for invalid period values.

## API Limit

Statement tools (`getIncomeStatement`, etc.) support **maximum `limit=5`**. Never request more than 5 rows — returns a 402 error. If the user asks for 10 years, fetch 5.

## Mandatory Workflow

```
# Statements data (pre-enabled):
1. getIncomeStatement(symbol="AAPL", period="FY", limit=5)
2. save_fmp_data(data=<result>, ticker="AAPL", data_type="income_statement")
3. extract_schema(file_paths=[<saved_path>])

# Other data types:
1. enable_toolset(name="charts")
2. getHistoricalPrice(symbol="AAPL", from="2020-01-01", to="2024-12-31")
3. save_fmp_data(data=<result>, ticker="AAPL", data_type="historical_price")
4. extract_schema(file_paths=[<saved_path>])
```

**Always call `save_fmp_data` immediately after each FMP tool call** — before calling the next tool. The `job_id` is injected automatically from runtime context; do not pass it as an argument.

## Meta-Tools

Only use these when needed:
- `list_toolsets` — see all available toolsets and their status
- `enable_toolset` — activate a toolset before using its tools
- `describe_toolset` — get parameter details for a toolset's tools

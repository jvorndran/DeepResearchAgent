---
name: fmp-data-fetch
description: Concise workflow for fetching FMP equity/financial data
triggers: [FMP, stock data, income statement, balance sheet, cash flow, price]
---

# FMP Workflow

1. **Pre-enabled:** `getIncomeStatement`, `getBalanceSheetStatement`, `getCashFlowStatement`, `getKeyMetrics`, `getRatios`.
2. **Enable:** `enable_toolset(name="charts")` for `getHistoricalPrice`.
3. **Fetch:** Call tool directly as a function (e.g. `getIncomeStatement(symbol="AAPL", period="FY", limit=5)`).
4. **Save:** `save_data(data=<result>, ticker="AAPL", data_type="income_statement")`.

## Rules
- **Limit:** `limit ≤ 5` for statement tools.
- **Period:** ONLY `"FY"`, `"Q1"`, `"Q2"`, `"Q3"`, `"Q4"`.
- **Immediate:** `save_data` after EVERY fetch.
- **Return:** JSON summary only.
- **NO economics toolset:** NEVER call `enable_toolset("economics")` or use `getEconomicIndicators`/`getTreasuryRates`. Use FRED for all macro data.

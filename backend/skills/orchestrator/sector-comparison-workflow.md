---
name: sector-comparison-workflow
description: Blueprint for comparing multiple tickers or sectors
triggers: [compare, AAPL vs MSFT, vs, sector, peers]
---

# Sector Comparison Blueprint

## Data Engineer
1. **Fetch:** Fetch same statements for multiple tickers (e.g., AAPL and MSFT).
2. **Save & Schema:** Separate CSVs for each ticker.

## Quant Developer
1. **Merge:** Inner join on normalized year.
2. **Analysis:** Side-by-side metric comparison (e.g., revenue, margin, EPS).
3. **Charts:** 
   - `metric_comparison`: Grouped bar chart comparing tickers.

## Technical Writer
- **Type:** `sector_comparison`
- **Focus:** Relative strength, market positioning, and leaders vs. laggards.

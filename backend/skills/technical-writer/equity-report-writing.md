---
name: equity-report-writing
description: Concise rules for equity research report markdown
triggers: [equity, stock, company, sector, earnings, investment thesis, catalysts, valuation]
---

# Equity Report Rules

1. **Analytical Tone:** Use specific statistics in parentheticals (e.g., `(r=0.82, p<0.01)`). Write in a professional, authoritative investment bank style.
2. **Frameworks:** Discuss competitive positioning, valuation multiples, revenue segments, and peer benchmarking.
3. **Structure (Order):**
   - ## Executive Summary (The "Call" & Price Target Implications)
   - ## Research Query (original text)
   - ## Data Sources (source, ticker, dates)
   - ## Investment Thesis & Catalysts (Core argument and upcoming events)
   - ## Financial Analysis & Valuation (Historical performance and forecasts)
   - ## Investment Risks (Operational, macro, and company-specific)
   - ## Methodology
   - ## Limitations
   - ## Disclaimer (must contain "financial advice" and "Past performance")

## Inline Charts
`<!-- CHART:chart_id -->` immediately after referencing text.

## Using Statistical Summary
- The `execution_summary.statistical_summary` contains computed numbers from the quant developer.
  Cite every specific value inline in your analysis sections using parentheticals.
- Populate `data_sources` when calling `write_research_report`: extract `series_ids`,
  `date_range` (start/end dates inferred from data), and `row_count` from the description
  you received — do not leave these fields null.

## Rule
- **Word Count:** 600-800+ words. Deep, thorough equity analysis.
- **Save:** Call `write_research_report`.

---
name: macro-report-writing
description: Concise rules for macroeconomic research report markdown
triggers: [macro, economy, gdp, inflation, unemployment, correlation, trend, policy]
---

# Macro Report Rules

1. **Analytical Tone:** Use specific statistics in parentheticals (e.g., `(r=0.82, p<0.01)`). Write in a professional, authoritative investment bank style.
2. **Frameworks:** Discuss economic cycles, interest rate impacts, structural headwinds, and broad market correlations.
3. **Structure (Order):**
   - ## Executive Summary (Macro View)
   - ## Research Query (original text)
   - ## Data Sources (source, ticker, dates)
   - ## Macro Environment & Policy Context (Current conditions and monetary/fiscal policy)
   - ## Indicator Analysis & Market Implications (Trends and impact on asset classes)
   - ## Structural Risks (Economic headwinds and thesis risks)
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
- **Word Count:** 600-800+ words. Deep, thorough macro analysis.
- **Save:** Call `write_research_report`.

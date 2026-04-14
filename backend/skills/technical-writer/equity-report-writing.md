---
name: equity-report-writing
description: Concise rules for equity research report markdown
triggers: [equity, stock, company, sector, earnings, investment thesis, catalysts, valuation]
---

# Equity Report Rules

1. **Analytical Tone:** Use specific statistics in parentheticals (e.g., `(r=0.82, p<0.01)`). Write in a professional, authoritative investment bank style.
2. **Frameworks:** Discuss competitive positioning, valuation multiples, revenue segments, and peer benchmarking.
3. **Structure (Order):**
   - ## Executive Summary (at the top: The "Call" & Price Target Implications)
   - **[Your Custom Analysis Sections]**: (e.g. Investment Thesis, Catalysts, Valuation, Risks, etc. Use your own headings and subheadings to structure the analysis logically.)
   - ## Research Query (original text restated at the bottom)
   - ## Disclaimer (must contain "financial advice" and "Past performance")

## Inline Charts
`<!-- CHART:chart_id -->` immediately after referencing text.

## Using Statistical Summary
- The `execution_summary.statistical_summary` contains computed numbers from the quant developer.
  Cite every specific value inline in your analysis sections using parentheticals.

## Rule
- **Word Count:** 1000+ words. Deep, thorough equity analysis.
- **Save:** Call `write_research_report`.

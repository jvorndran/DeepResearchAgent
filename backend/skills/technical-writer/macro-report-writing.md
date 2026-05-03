---
name: macro-report-writing
description: Concise rules for macroeconomic research report markdown
triggers: [macro, economy, gdp, inflation, unemployment, correlation, trend, policy]
---

# Macro Report Rules

1. **Analytical Tone:** Use specific statistics in parentheticals (e.g., `(r=0.82, p<0.01)`). Write in a professional, authoritative investment bank style.
2. **Frameworks:** Discuss economic cycles, interest rate impacts, structural headwinds, and broad market correlations.
3. **Structure (Order):**
   - ## Executive Summary (at the top: Macro View and Key Findings)
   - **[Your Custom Analysis Sections]**: (e.g. Macro Environment, Policy Context, Indicator Analysis, Structural Risks, etc. Use your own headings and subheadings to structure the analysis logically.)
   - ## Research Query (original text restated at the bottom)
   - Do **not** add a `## Disclaimer` section — the system appends a standard legal footer on save.

## Inline Charts
`<!-- CHART:chart_id -->` immediately after referencing text.

## Using Statistical Summary
- The `execution_summary.statistical_summary` contains computed numbers from the quant developer.
  Cite every specific value inline in your analysis sections using parentheticals.
- If the query asks for scenarios or stress testing, render
  `execution_summary.scenario_table` as a `## Scenario Table` markdown table
  with Scenario, Assumptions, Indicator Triggers, Confidence, and Uncertainty
  Notes columns before saving.

## Rule
- **Word Count:** 1000+ words. Deep, thorough macro analysis.
- **Save:** Call `write_research_report`.

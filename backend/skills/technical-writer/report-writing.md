---
name: report-writing
description: Analytical frameworks, section templates, and QA anti-patterns for the technical-writer producing research reports
triggers:
  - report
  - write report
  - research report
  - technical writer
  - markdown narrative
  - analytical framework
  - counterfactual
  - regime switching
  - decomposition
  - report writing
---

# Research Report Writing Guide

## Analytical Frameworks

Go beyond simple econometric labels. Apply these frameworks to produce high-quality analysis:

| Framework | When to Apply | Example |
|-----------|--------------|---------|
| **Counterfactual** | When a key variable shifted | "Had the Fed held rates flat, GDP growth would likely have remained ~2.5% based on the historical sensitivity coefficient" |
| **Leading vs. Lagging** | Mixed indicator types | "PMI (leading) turned negative 6 months before GDP (lagging) contracted" |
| **Regime Switching** | Structural breaks in data | "The correlation coefficient shifts from -0.89 in the 2004–2019 era to -0.71 in the 2020–2024 post-pandemic regime" |
| **Elasticity** | Sensitivity analysis | "A 100bp rate increase correlates with a 0.4pp rise in unemployment over 4 quarters" |
| **Mean Reversion** | Stretched values | "The P/E ratio at 28x is 1.8 standard deviations above its 20-year mean of 18x" |
| **Decomposition** | Aggregate metrics | "CPI's 7.1% peak: shelter contributed 3.2pp, energy 1.9pp, food 1.4pp, core services 0.6pp" |
| **Diffusion** | Breadth of trends | "The rally is narrow: only 35% of S&P 500 constituents are above their 200-day MA" |

## Required Section Order

```markdown
## Executive Summary
[2-3 sentences. Single most important finding with exact statistic.]

## Research Query
[Verbatim original query — no paraphrasing]

## Data Sources
[Bullet per source: provider, series IDs, date range, row counts]

## [Analysis Section 1 — unique title]
[2-4 paragraphs. Distinct aspect. Cite specific numbers.]

<!-- CHART:chart_id_1 -->

## [Analysis Section 2 — different topic from Section 1]
[Different content. Address another dimension.]

<!-- CHART:chart_id_2 -->

## Methodology
[Data collection approach, specific series, analytical methods used]

## Limitations
[Specific to THIS analysis — not generic boilerplate]

## Disclaimer
**IMPORTANT DISCLAIMER**: This report is for informational purposes only and does not
constitute financial advice. All analysis is based on historical data.
Past performance is not indicative of future results.
```

## Chart Placement Rules

- Place `<!-- CHART:id -->` on its own line **immediately after** the paragraph that references it
- Never cluster all chart markers at the bottom of the report
- Use exactly the IDs returned by `plan_report_structure` — never invent IDs

## QA Anti-Patterns (will fail quality review)

❌ Copying the same sentence into two sections
❌ Sections with only 1 sentence
❌ Generic boilerplate (same text could apply to any report)
❌ Inventing statistics not in execution_summary
❌ Predictive language: "will increase", "should buy", "expect the price to"
❌ All chart markers clustered at the bottom
❌ Missing disclaimer with required phrases
❌ Executive summary without a specific statistic (r-value, coefficient, %)

## Quality Bar

A passing report has:
- Word count > 400
- ≥ 1 chart referenced inline (every available chart used)
- No validation_issues from `write_research_report`
- Each section contains unique prose specific to this query's data
- Executive summary names the exact statistic

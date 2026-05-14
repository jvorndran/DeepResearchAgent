---
name: macro-report-writing
description: Macroeconomic research-report structure, scenario-table formatting, and macro narrative rules.
---

# Macro Report Writing

Use this skill when `plan_report_structure.general_rules` says Macro Report, or
when the query is about macroeconomics, economic cycles, scenarios, stress
testing, recession risk, inflation, labor markets, rates, credit, GDP, regional
consumer conditions, or policy.

## Analytical Tone

- Write in dense, investment-bank-style analytical prose.
- Cite specific computed values inline using parentheticals such as
  `(r = 0.82, p < 0.01)` or `(slope of -0.05 pp/month)`.
- Discuss economic cycles, interest-rate impacts, structural headwinds,
  broad-market correlations, and policy context when supported by the handoff.
- Preserve the sign convention from `execution_summary_for_draft`; do not flip
  spread, slope, correlation, or delta directions in prose.

## Structure

Use the plan result as the controlling outline, with this default order:

1. `## Executive Summary` at the top, focused on the macro view and key
   findings.
2. Custom analytical sections that fit the question, such as macro environment,
   policy context, indicator analysis, market implications, structural risks,
   scenarios, or regional stress.
3. `## Research Query` near the bottom, restating the original question.

Do not add a `## Disclaimer` section because the system appends the legal footer
after save.

## Scenario Table

When `general_rules` requires `## Scenario Table`, render a markdown table with
exactly these headers:

`Scenario`, `Assumptions`, `Indicator Triggers`, `Confidence`, `Uncertainty Notes`

The first-column row keys must be lowercase `base`, `bull`, and `bear`. Use
semicolons or `<br>` inside cells for multiple items, not extra columns. Use
`execution_summary_for_draft` scenario rows when present and do not invent
probability weights when only confidence labels are supplied.

## Word Count

Aim for 1000+ words of dense analytical content unless the user explicitly asks
for a shorter memo.

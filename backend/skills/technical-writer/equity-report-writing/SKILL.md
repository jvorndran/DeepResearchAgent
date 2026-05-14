---
name: equity-report-writing
description: Equity, stock, company, sector, earnings, and valuation report structure and narrative rules.
---

# Equity Report Writing

Use this skill when `plan_report_structure.general_rules` says Equity Report, or
when the query is about a stock, company, sector, earnings, catalysts,
fundamentals, valuation, peers, or investment thesis.

## Analytical Tone

- Write in professional equity-research prose with a clear investment argument.
- Cite specific computed values inline using parentheticals such as
  `(r = 0.82, p < 0.01)`, revenue CAGR, margin, growth rate, peer spread, or
  drawdown values from `execution_summary_for_draft`.
- Copy company growth rates, margins, fiscal-year labels, and sign/direction
  language exactly from the quant output. Do not substitute public-memory values
  for handoff values.

## Structure

Use the plan result as the controlling outline, with this default order:

1. `## Executive Summary` at the top, focused on the call, price-target
   implications when supported, and key findings.
2. Custom analytical sections that fit the question, such as investment thesis,
   competitive positioning, catalysts, financial analysis, segment trends,
   valuation, peer benchmarking, macro sensitivity, and risks.
3. `## Research Query` near the bottom, restating the original question.

Do not add a `## Disclaimer` section because the system appends the legal footer
after save.

## Source Handling

Use exact provider names from the handoff. SEC EDGAR should be cited for SEC
company-facts material. Do not cite generic "Company Filings" unless the
handoff explicitly used that provider name.

## Word Count

Aim for 1000+ words of thorough equity analysis unless the user explicitly asks
for a shorter memo.

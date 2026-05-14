---
name: broad-investment-committee-workflow
description: Use for broad investment-committee macro cycle briefs spanning labor, inflation, credit, production, consumption, international peers, regional context, and earnings risk.
---

# Broad Investment-Committee Workflow

Use this skill for broad macro cycle requests that combine labor, inflation, credit, production, consumption, policy, international peers, regional consumer context, and Apple/Microsoft earnings risk.

## First data-engineer task

Name the selected free/no-key provider families implied by the approved query instead of letting data-engineer discover substitutes by trial and error.

For broad investment-committee macro cycle requests, explicitly require:

- FRED for the compact national macro and `USREC` set.
- BLS only for focused direct labor/inflation source checks when useful.
- World Bank `worldbank_get_indicator` for annual peer-country GDP-growth/inflation comparisons.
- Exactly one batched Census state table for regional context.
- SEC EDGAR `sec_fetch_company_facts` for AAPL and MSFT.
- No paid/keyed providers; FMP remains disabled and unavailable.

If Census or World Bank returns `status:error`, tell data-engineer to return the compact error as a caveat and continue with available data, not to replace it with broad guessed FRED sweeps.

## Quant and writer scope

- Ask quant-developer for a compact first pass: computed recession risk/regime, unemployment outlook, scenario/stress output, and source-context metadata.
- For ordinary broad prompts, do not require one chart for every user-requested concept. For explicit chart, dashboard, chart-pack, visual-evidence, or chart-validation prompts, ask quant-developer for 6-8 distinct renderable charts that cover the requested dimensions.
- Let technical-writer cover secondary source views with tables and prose grounded in `execution_summary_json`.

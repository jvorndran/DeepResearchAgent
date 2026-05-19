---
name: market-valuation-data
description: Availability-only market valuation data workflow
triggers: [stock price, share price, market cap, valuation, multiples, analyst estimates, estimate revisions, price target]
---

# Market Valuation Data Workflow

Use `market_get_valuation_availability` when the approved query asks for stock
price, market capitalization, valuation multiples, analyst estimates, estimate
revisions, price targets, or upside/downside evidence.

## MARKET VALUATION DATA

1. **Capability check only:** Call
   `market_get_valuation_availability(identifier=<ticker>, requested_capabilities=[...])`.
2. **Handoff:** Preserve the returned `source_coverage.valuation_market_data`
   payload under execution-summary metadata. It includes `status`, `reason`,
   `limitation`, `capabilities`, and diagnostics.
3. **Limitation:** If status is `not_available`, state that market price,
   market cap, valuation multiples, analyst estimates, and estimate revisions
   are unavailable from the current provider set.

## Boundaries

- This provider is availability-only. Do not fabricate price, market cap,
  multiples, analyst estimates, revisions, price targets, or upside/downside.
- Do not call FMP, OpenBB directly, quote feeds, paid/keyed providers, or web
  search as a substitute.
- Do not call `save_data` for this tool; it returns metadata, not rows.
- SEC company facts remain fundamentals evidence only. Do not convert SEC
  revenue, EPS, or shares into market valuation facts without a live market-data
  provider result.

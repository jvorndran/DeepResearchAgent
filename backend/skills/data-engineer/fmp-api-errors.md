---
name: fmp-api-errors
description: Disabled FMP error handling; report unavailability instead of retrying FMP
triggers:
  - FMP
  - 402
  - toolset not enabled
  - invalid period
  - MCP error
---

# FMP Error Handling Disabled

FMP remains disabled and unavailable. Do not recover FMP errors by correcting
periods, lowering limits, enabling toolsets, requesting credentials, or trying a
different paid/keyed provider.

If a task asks for FMP-backed data, return a compact limitation in
`metadata.fetch_errors`. For public-company fundamentals, use SEC EDGAR only
when the SEC provider is selected; otherwise ask the orchestrator to reroute the
toolbox rather than calling unavailable FMP tools.

---
name: fmp-api-errors
description: Recovery procedures for FMP MCP API errors — 402 limit exceeded, invalid period, missing toolset, NaN responses
triggers:
  - 402
  - error
  - invalid period
  - rate limit
  - toolset not enabled
  - NaN
  - tool not found
  - failed to fetch
  - MCP error
  - -32602
---

# FMP API Error Recovery

## Error: 402 — Row Limit Exceeded

**Cause**: Requested `limit` > 5 for statement tools.
**Fix**: Retry with `limit=5`. Never request more than 5 rows regardless of user's time horizon.

```
getIncomeStatement(symbol="AAPL", period="FY", limit=5)   ✓
getIncomeStatement(symbol="AAPL", period="FY", limit=10)  ✗ → 402
```

## Error: -32602 — Invalid Period Value

**Cause**: Passed `"annual"`, `"yearly"`, `"quarterly"` instead of valid enum values.
**Valid values**: `"FY"`, `"Q1"`, `"Q2"`, `"Q3"`, `"Q4"` — nothing else.
**Fix**: Map aliases before calling:

| Wrong | Correct |
|-------|---------|
| `"annual"` | `"FY"` |
| `"yearly"` | `"FY"` |
| `"quarterly"` | `"Q1"` |
| `"quarter"` | `"Q1"` |

## Error: Tool Not Found / "toolset not enabled"

**Cause**: Called a tool from a toolset that wasn't enabled first.
**Fix**: Call `enable_toolset(name="<toolset>")` first, then retry.

Common toolset → tool mappings:
- `getHistoricalPrice` → enable `"charts"` first
- `getQuote` → enable `"quotes"` first
- `getCompanyProfile` → enable `"company"` first

**Note**: `statements` toolset is pre-enabled — `getIncomeStatement` etc. work immediately.

## Error: NaN / Infinity in Response

**Cause**: FMP returns NaN for missing data points.
**Behavior**: The `save_data` tool auto-sanitizes NaN before saving to CSV. If NaN appears in a raw tool result before saving, just call `save_data` — it will be cleaned.

## Error: MCP Timeout

**Cause**: FMP server took longer than 30 seconds.
**Effect**: `MCPTimeoutError` is raised and **aborts the entire workflow**. This is intentional.
**Action**: Report the timeout to the orchestrator. Do not retry in a loop.

## General Retry Strategy

1. Read the exact error message
2. Identify which fix applies above
3. Retry **once** with the corrected call
4. If it fails again → return the error to the orchestrator with the exact message

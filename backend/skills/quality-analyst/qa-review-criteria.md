---
name: qa-review-criteria
description: Severity classification table for QA triage — which issues are CRITICAL (reject), AUTO-FIXABLE (patch), or MINOR (note and approve)
triggers:
  - triage
  - severity
  - critical
  - auto-fix
  - patch
  - reject
  - validate
  - compliance
  - disclaimer
  - chart marker
---

# QA Review Criteria

## Severity Classification

| Issue | Severity | Action |
|-------|----------|--------|
| Predictive language (`"will increase"`, `"should buy"`, `"is expected to"`) | **CRITICAL** | `reject_report` |
| Investment advice or buy/sell/hold recommendations | **CRITICAL** | `reject_report` |
| Narrative fallacy — claims not supported by data | **CRITICAL** | `reject_report` |
| Missing required section (Executive Summary, Data Sources, Methodology) | **CRITICAL** | `reject_report` |
| Empty or placeholder executive summary | **CRITICAL** | `reject_report` |
| Original query not found anywhere in markdown | **CRITICAL** | `reject_report` |
| Invented statistics not present in execution_summary | **CRITICAL** | `reject_report` |
| Pydantic schema validation error | **CRITICAL** | `reject_report` |
| Missing `"does not constitute financial advice"` | **AUTO-FIXABLE** | `patch_report(path, "add_disclaimer")` |
| Missing `"Past performance is not indicative of future results"` | **AUTO-FIXABLE** | `patch_report(path, "add_past_performance")` |
| Missing report footer | **AUTO-FIXABLE** | `patch_report(path, "add_footer")` |
| Broken `<!-- CHART:id -->` markers (ID not in charts dict) | **AUTO-FIXABLE** | `patch_report(path, "remove_broken_chart_markers")` |
| Minor formatting, wordiness, typos | **MINOR** | Note in `approve_report` |
| Single-sentence sections | **MINOR** | Note in `approve_report` |

## Analytical Quality Checks

These require judgment — apply during Step 1 after reading the markdown:

- **Narrative fallacy**: Does the report invent causal stories to explain noise? Claims require statistical backing from execution_summary.
- **Assumption stress**: Does analysis assume linear trends without acknowledging risks or regime shifts?
- **Framework usage**: Has the technical writer applied relevant analytical frameworks (counterfactual, decomposition, regime switching) rather than just reciting numbers? See `report-writing` skill for the full framework list.

## After Auto-Patching

Always re-run `validate_report_format` after any `patch_report` call. Do **not** rely on the pre-patch validation results. If re-validation fails → escalate to CRITICAL → `reject_report`.

## Terminal Actions

`approve_report` and `reject_report` are **terminal**. Once called, make NO further tool calls.

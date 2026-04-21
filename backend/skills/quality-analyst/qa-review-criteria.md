---
name: qa-review-criteria
description: Concise rules for report quality review
triggers: [QA, review, approve, reject, compliance, validation]
---

# QA Review Rules

## Critical (Reject)
- **Compliance:** Investment advice or predictive "will increase" language.
- **Accuracy:** Major discrepancies between text and `execution_summary`.
- **Formatting:** Missing mandatory sections or broken chart markers.

## Auto-Fixable (Patch)
- Missing disclaimer, footer, or past performance notice.
- Broken `<!-- CHART:id -->` markers (if ID is not in `report.charts`).

## Workflow
1. `run_quality_gate` (schema + mandatory markdown + compliance + charts; may auto-patch safe issues).
2. If Critical → `reject_report`.
3. If the gate still fails after `auto_patch=True`, call `reject_report` with concrete `required_fixes`.
4. If Clean → `approve_report`.

**Terminal:** `approve` and `reject` end your turn.

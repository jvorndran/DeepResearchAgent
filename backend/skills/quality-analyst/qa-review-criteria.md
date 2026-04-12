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
1. `validate_report_format` → 2. `check_compliance` → 3. `verify_chart_references`.
4. If Critical → `reject_report`.
5. If Auto-fixable → `patch_report` → `validate_report_format`.
6. If Clean → `approve_report`.

**Terminal:** `approve` and `reject` end your turn.

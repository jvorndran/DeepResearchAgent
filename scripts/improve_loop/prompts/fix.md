Phase: fix

Read the latest `review-*-summary.md`, `plan-summary.md`, `analysis-summary.md`, `current-diff.patch`, and `test-evidence.md`. Fix only the review findings.

The analysis summary links back to `trace-digest.md`; keep the fix aligned with that reviewed evidence.

Holistic improvement gate: if review finds the patch too narrow, refocus on the reusable failure class instead of adding another special case.

Code quality gate: resolve the finding with the smallest clean design change that matches local patterns. Do not widen scope, add broad heuristics, keep obsolete branches, or weaken tests to get approval.

Rerun the focused tests named by the review when practical. Summarize changed files, findings addressed, tests run, and any residual risk to the selected report-quality criteria.

End exactly with:
IMPROVE_FIX_RESULT: patched|no_patch|blocked
IMPROVE_TARGET: <short subsystem name>
IMPROVE_FILES_CHANGED: <comma-separated files or none>
IMPROVE_TESTS_RUN: <commands or none>
IMPROVE_NEXT_SIGNAL: <one short sentence>

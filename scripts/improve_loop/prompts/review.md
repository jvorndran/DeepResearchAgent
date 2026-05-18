Phase: review

Review `current-diff.patch` against `analysis-summary.md`, `plan-summary.md`, the quality criteria named there, build or latest fix summary, and `test-evidence.md`. This is read-only.

The run summary links `trace-digest.md`; use it only as needed to check quality-impact evidence.

Lead with correctness issues, behavioral regressions, scope drift, missing tests, weak report-quality linkage, or workaround smells. Approve only when the diff plausibly improves the selected user-facing report criteria and is adequately verified.

Holistic improvement gate: request changes when the patch only handles a rare edge case, lacks a general failure class, or does not improve reusable agent behavior, context, artifact flow, or specialist contracts.

Code quality gate: request changes for tech debt such as duplicated logic, broad string matching, one-off query branches, unclear ownership, schema drift, prompt bloat, hidden global state, dead code left behind, or tests that only bless brittle behavior.

End exactly with:
IMPROVE_REVIEW_RESULT: approved|changes_requested|blocked
IMPROVE_REVIEW_FINDINGS: <short finding summary>
IMPROVE_NEXT_SIGNAL: <one short sentence>

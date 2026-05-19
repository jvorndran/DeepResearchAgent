Phase: fix

Read the latest `review-*-summary.md`, `plan-summary.md`,
`analysis-summary.md`, `current-diff.patch`, and `test-evidence.md`. Fix only
the review findings.

Keep the feature scope stable. Do not weaken tests or switch roadmap targets to
obtain approval. Prefer the smallest clean design change that matches local
patterns.

Rerun focused tests when practical. Summarize findings addressed, changed files,
tests run, and remaining risk.

End exactly with:
FEATURE_FIX_RESULT: patched|no_patch|blocked
FEATURE_TARGET: <short feature name>
FEATURE_FILES_CHANGED: <comma-separated files or none>
FEATURE_TESTS_RUN: <commands or none>
FEATURE_NEXT_SIGNAL: <one short sentence>

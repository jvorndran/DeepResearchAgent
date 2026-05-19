Phase: review

Review `current-diff.patch` against `analysis-summary.md`, `plan-summary.md`,
the roadmap file named in the phase context, the build or latest fix summary,
and `test-evidence.md`. This is read-only.

Lead with correctness issues, behavioral regressions, roadmap mismatch, missing
tests, scope drift, weak architecture fit, or code-quality debt. Approve only
when the diff plausibly advances the selected roadmap feature and is adequately
verified.

Request changes for:
- broad untyped payloads where a typed contract was practical
- prompt-only changes for deterministic artifact problems
- duplicated source/fact/chart contracts
- hidden global state or brittle string routing
- incomplete tests for the feature's behavioral surface
- implementation that jumps to a different roadmap feature

End exactly with:
FEATURE_REVIEW_RESULT: approved|changes_requested|blocked
FEATURE_REVIEW_FINDINGS: <short finding summary>
FEATURE_NEXT_SIGNAL: <one short sentence>

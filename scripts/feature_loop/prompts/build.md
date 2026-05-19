Phase: build

Read `plan-summary.md`, `analysis-summary.md`, `feature-request.md`, the roadmap
file named in the phase context, and compact memory. Implement only the planned
feature slice.

## Build Rules

- Follow the plan's scope, files, and tests.
- If inspection proves the plan unsafe or wrong, return `no_patch` or `blocked`
  with evidence instead of switching to a different feature.
- Prefer typed payloads, Pydantic models, validators, explicit source/artifact
  metadata, and local helper APIs.
- Keep edits focused. Do not widen into unrelated roadmap features.
- Add or update tests proportional to the feature risk.
- Avoid prompt-only fixes when code, schema, or guardrails can enforce the
  contract.

Summarize changed behavior, files, tests, and residual risk.

End exactly with:
FEATURE_BUILD_RESULT: patched|no_patch|blocked
FEATURE_TARGET: <short feature name>
FEATURE_FILES_CHANGED: <comma-separated files or none>
FEATURE_TESTS_RUN: <commands or none>
FEATURE_NEXT_SIGNAL: <one short sentence>

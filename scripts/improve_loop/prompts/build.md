Phase: build

Read `plan-summary.md`, `analysis-summary.md`, `run-summary.md`, and compact memory. Follow artifact paths from `run-summary.md` only when needed. Implement the planned root-cause fix tied to the selected report-quality target and criteria.

The run summary links `trace-digest.md`; use it only as evidence for how trace behavior affected report quality.

Follow the plan's files, scope, and tests. If inspection proves the plan is unsafe or wrong, return `no_patch` or `blocked` with evidence instead of improvising a new target. Prefer structured contracts, validators, typed state, tool payloads, artifact preservation, or clearer specialist ownership over wording pressure.

Holistic improvement gate: favor fixes that improve agent behavior, context, artifacts, or specialist contracts across a recurring class of tasks. Return `no_patch` or `blocked` for narrow rare-case tweaks that do not materially improve the agent.

Code quality gate: follow local patterns, keep ownership clear, remove dead paths you replace, and avoid new catch-all heuristics, duplicated logic, hidden global state, prompt bloat, or one-off query branches. If a clean fix is not clear, return `blocked` or `no_patch` instead of adding debt.

Run focused tests for the changed behavior. Summarize changed files, behavior or contract changes, tests run, and how the patch should improve the user's final report experience.

End exactly with:
IMPROVER_RESULT: patched|no_patch|blocked
IMPROVE_TARGET: <short subsystem name>
IMPROVE_FILES_CHANGED: <comma-separated files or none>
IMPROVE_TESTS_RUN: <commands or none>
IMPROVE_NEXT_SIGNAL: <one short sentence>

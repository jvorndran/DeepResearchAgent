Phase: plan

Read `analysis-summary.md`, `run-summary.md`, `trace-digest.md` through the run summary, relevant code, and compact memory. Make no edits. Your job is to explore the codebase and turn the analyzed issue into one buildable fix.

Planning checklist:
1. Restate the selected issue, report-quality criteria, holistic improvement claim, and code-quality risks.
2. Map the issue to code ownership: agents, skills, tools, schemas, artifact flow, prompts, tests, or runner harness.
3. Inspect the likely files and nearby tests; cite paths and the current behavior that creates the failure class.
4. Compare two or three fix designs. For each, state reuse across tasks, debt risk, likely files, and verification.
5. Apply the agent-engineering lens: keep agents simple/composable; add a tool for high-impact data/action with clear names, typed inputs, compact outputs, and actionable errors; add a skill for reusable on-demand workflow/domain context; edit prompts only for concise roles, sequence, boundaries, or edge cases; use code/schema/guardrails for deterministic validation, safety, artifact or state contracts.
6. Choose one design that improves a recurring agent behavior or artifact contract, not a rare one-off.
7. Define exact build scope, handoff changes, files to edit, tests/evals to run, rollback risk, what must not change, and the signal to watch.

Holistic improvement gate: choose a reusable agent-quality fix or return `no_plan`/`blocked`.

Code quality gate: prefer local patterns, structured contracts, clear ownership, and focused tests. Reject broad string matching, one-off query branches, prompt bloat, duplicated logic, or hidden state.

Write a concise decision record with evidence for each checklist step; do not include private scratch reasoning.

End exactly with:
IMPROVE_PLAN_RESULT: planned|no_plan|blocked
IMPROVE_TARGET: <short subsystem name>
IMPROVE_PLAN_FILES: <comma-separated likely files or unknown>
IMPROVE_PLAN_TESTS: <commands to run or unknown>
IMPROVE_NEXT_SIGNAL: <one short sentence>

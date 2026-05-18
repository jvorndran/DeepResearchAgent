---
name: agent-improver
description: >-
  Iteratively improves the Deep Research Agent by running the full agent,
  analyzing trace and report artifacts, and patching one product-quality target.
---

# Agent Improvement Loop

Use this skill when improving the Deep Research Agent from a completed runner
execution. The outer shell harness owns iteration. Each Codex phase should finish
its assigned work and exit with the required machine-readable lines.

## Artifact Order

Treat runner artifacts as the source of truth. Read paths, not pasted contents,
in this order:

1. `run-summary.md`
2. `trace-digest.md`
3. `trace_diagnostics.json`
4. `runner_status.json`
5. Report artifacts listed by the runner, especially `report.json` and charts
6. `logs/improve-loop/memory.md`

Do not carry raw spans, full logs, full prompts, or full diffs between phases.
Store and cite paths instead.

## Phase Contract

The simplified harness is:

```text
run -> analyze -> plan -> build -> review -> fix/review until approved
```

- `run`: shell runs `backend/tests/runner.py` once; budgets are not stop conditions.
- `analyze`: inspect trace, report, and charts; make no edits; choose one target.
- `plan`: explore source/tests, compare designs, and write the implementation plan.
- `build`: implement the planned root-cause fix and run focused verification.
- `review`: read-only review against analysis, plan, quality criteria, and tests.
- `fix`: address review findings only and rerun focused tests when practical.

## Analysis Guidance

Trace inefficiency is evidence, not the default goal. Note redundant calls,
retry churn, slow handoffs, missing tool selection, and artifact handoff problems,
then judge whether they harmed the final report.

Report quality is the primary target. Use the inline analyze-prompt criteria to
assess:

- Answer fit
- Evidence coverage
- Analytical rigor
- Chart usefulness
- Narrative clarity
- Caveats and actionability
- Artifact integrity

Choose the single fix that most improves the final user experience. Efficiency
work is appropriate only when it clearly blocked report quality.

Prefer holistic fixes that improve a recurring class of agent behavior, context,
artifact flow, or specialist contracts. Reject rare one-off tweaks unless they
expose a reusable failure class.

## Implementation Guidance

Prefer durable contracts over brittle wording: typed payloads, explicit state
fields, validators, structured tool returns, artifact preservation, and clearer
specialist ownership. Avoid broad substring routing, magic prompt phrases,
single-query branches, and prompt-only workarounds when code or schema can solve
the class of failure.

Code quality is a phase gate, not cleanup for later. Plans should name debt
risks, builds should prefer the smallest clean design that follows local
patterns, reviews should request changes for brittle or messy patches, and fixes
should address findings without widening scope or weakening tests.

Scale tests to the patch risk. For report or chart changes, run relevant static
chart or artifact validation when a `report.json` path exists. If verification is
blocked, record the command, path, and error class.

## Required Lines

Run summaries must include:

```text
RUN_RESULT: completed|failed
RUN_TRACE_DIGEST: <path>
```

Analysis summaries must end with:

```text
IMPROVE_ANALYSIS_RESULT: analysis_complete|no_target|blocked
IMPROVE_TARGET: <short subsystem name>
IMPROVE_QUALITY_CRITERIA: <criteria names this target improves>
IMPROVE_NEXT_SIGNAL: <one short sentence>
```

Plan summaries must end with:

```text
IMPROVE_PLAN_RESULT: planned|no_plan|blocked
IMPROVE_TARGET: <short subsystem name>
IMPROVE_PLAN_FILES: <comma-separated likely files or unknown>
IMPROVE_PLAN_TESTS: <commands to run or unknown>
IMPROVE_NEXT_SIGNAL: <one short sentence>
```

Build summaries must end with:

```text
IMPROVER_RESULT: patched|no_patch|blocked
IMPROVE_TARGET: <short subsystem name>
IMPROVE_FILES_CHANGED: <comma-separated files or none>
IMPROVE_TESTS_RUN: <commands or none>
IMPROVE_NEXT_SIGNAL: <one short sentence>
```

Review summaries must end with:

```text
IMPROVE_REVIEW_RESULT: approved|changes_requested|blocked
IMPROVE_REVIEW_FINDINGS: <short finding summary>
IMPROVE_NEXT_SIGNAL: <one short sentence>
```

Fix summaries must end with:

```text
IMPROVE_FIX_RESULT: patched|no_patch|blocked
IMPROVE_TARGET: <short subsystem name>
IMPROVE_FILES_CHANGED: <comma-separated files or none>
IMPROVE_TESTS_RUN: <commands or none>
IMPROVE_NEXT_SIGNAL: <one short sentence>
```

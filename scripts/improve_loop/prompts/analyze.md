Phase: analyze

Read `run-summary.md` first. It points to `trace-digest.md`, status, and report artifacts. Also read `memory.md`. Make no edits.

## Analysis Workflow

1. Reconstruct the user's job: decision, audience, requested output, and what would make it more useful.
2. Verify the artifact chain: `report.json`, summaries, charts, code, sources, and validations when present.
3. Scan the trace for quality-impacting inefficiencies: redundant calls, retry churn, unclear delegation, weak source/tool choice, context bloat, repair loops, or artifact handoff confusion. Choose inefficiency only when it hurt report quality.
4. Read the report as the user: is the conclusion clear in two minutes, evidence trustworthy, charts/tables useful, and skeptical follow-up answered?
5. Score each criterion as `good`, `minor_gap`, `major_gap`, or `blocked`. Name the top two gaps and evidence.
6. Diagnose the agent-engineering failure class: instruction clarity, tool/schema affordance, skill vs prompt placement, context load, handoff/orchestration, guardrail, or eval gap.
7. Compare two or three candidate root-cause fixes. For each, state criteria improved, likely files/modules, verification, reuse, and tech-debt risk.
8. Select the broadest reusable agent-quality lift; reject rare one-off fixes unless they expose a general failure class.

## Quality Criteria

- Answer fit: user decision, scope, audience, output.
- Evidence coverage: right sources, citations, staleness/conflicts.
- Analytical rigor: baselines, comparisons, uncertainty, no overclaiming.
- Chart usefulness: renderable, legible, non-redundant, decision-linked.
- Narrative clarity: scan-friendly structure, headings, tables, conclusions.
- Caveats and actionability: what would change and what cannot be concluded.
- Artifact integrity: preserves outputs, charts, source metadata, validations.

## Analysis Summary Shape

Keep output compact but decision-complete: user job, trace notes, criteria scores, two biggest report gaps, candidates considered, selected target, code quality risks, files/modules to inspect first, verification, and machine lines.

End exactly with:
IMPROVE_ANALYSIS_RESULT: analysis_complete|no_target|blocked
IMPROVE_TARGET: <short subsystem name>
IMPROVE_QUALITY_CRITERIA: <criteria names this target improves>
IMPROVE_NEXT_SIGNAL: <one short sentence>

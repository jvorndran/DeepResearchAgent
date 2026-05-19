Phase: plan

Read `analysis-summary.md`, `feature-request.md`, the roadmap file named in the
phase context, compact memory, and relevant source/tests. Make no edits.

## Planning Checklist

1. Restate the selected feature, roadmap section, target flow stage, and user
   benefit.
2. Inspect likely files and nearby tests. Cite paths and current behavior.
3. Choose a narrow, production-quality implementation slice that advances the
   roadmap without trying to complete the whole architecture at once.
4. Compare two or three designs. For each, state reuse, debt risk, likely files,
   tests, and rollback risk.
5. Prefer typed contracts, validators, source descriptors, explicit artifact
   metadata, and deterministic routing over prompt-only instructions.
6. Define exact edit scope, tests to run, what must not change, and the next
   signal to watch.

Return `no_plan` if the selected feature cannot be safely built in one pass.

End exactly with:
FEATURE_PLAN_RESULT: planned|no_plan|blocked
FEATURE_TARGET: <short feature name>
FEATURE_PLAN_FILES: <comma-separated likely files or unknown>
FEATURE_PLAN_TESTS: <commands to run or unknown>
FEATURE_NEXT_SIGNAL: <one short sentence>

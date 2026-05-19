Phase: analyze

Read `feature-request.md`, the roadmap file named in the phase context, and
the compact run index if present. Make no edits. Treat the roadmap markdown as
the durable implementation memory.

## Analysis Workflow

1. Identify the highest-leverage roadmap feature to implement next. Honor any
   preferred target named in `feature-request.md`.
2. Map the selected feature to the target agent flow:
   `planner -> source recipe -> typed fetch -> validated transforms -> evidence bundle -> chart/report projection -> QA`.
3. State the user-facing improvement this feature should create.
4. Identify the current repo surface likely involved: agents, tools, schemas,
   skills, prompts, tests, harnesses, or docs.
5. Compare two or three candidate slices if the roadmap feature is large. Choose
   one buildable slice that can land in a single approved pass.
6. Call out code-quality risks: schema drift, duplicated contracts, prompt-only
   fixes, hidden state, brittle routing, or broad untyped payloads.

Prefer durable implementation features over exploratory notes. If no useful
feature can be selected from the roadmap, return `no_target`.

## Analysis Summary Shape

Keep output compact but decision-complete: selected roadmap feature, target flow
stage, product improvement, likely files/modules, candidate slices considered,
chosen implementation slice, risks, and verification direction.

End exactly with:
FEATURE_ANALYSIS_RESULT: feature_selected|no_target|blocked
FEATURE_TARGET: <short feature name>
FEATURE_ROADMAP_SECTION: <roadmap heading or unknown>
FEATURE_FLOW_STAGE: <planner|source recipe|typed fetch|validated transforms|evidence bundle|chart/report projection|QA|cross-cutting>
FEATURE_SELECTION_NOTES: <one short sentence explaining why this feature slice is next>

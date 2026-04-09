---
name: qa-rejection-recovery
description: How to handle a quality-analyst rejection — extracting required_fixes and re-delegating to technical-writer with specific corrective instructions
triggers:
  - rejected
  - status: rejected
  - required_fixes
  - QA rejection
  - re-delegate
  - fix report
  - revision
---

# QA Rejection Recovery

## When the Quality Analyst Returns `status: rejected`

1. **Extract the `required_fixes` list** from the JSON response — do not paraphrase.
2. **Count this as one retry** toward the Rule of Three (max 3 QA rejections per job).
3. **Re-delegate to technical-writer** with ALL of the following in your task instruction:
   - The `report_json_path` to revise
   - The `charts_json_path` (unchanged)
   - The verbatim `required_fixes` list
   - The `original_query` and `job_id`
   - The explicit instruction: "Read the existing report.json, apply the required fixes, then call `write_research_report` with the corrected markdown."

## Task Template for Re-delegation

```
task(name="technical-writer", task="""
Revise the existing report for job {job_id}.

Report to fix: outputs/{job_id}/report.json
Charts: outputs/{job_id}/charts.json
Original query: {original_query}

Required fixes from QA:
{required_fixes as bullet list}

Read the existing report.json first to retrieve the current markdown.
Apply ALL required fixes. Then call write_research_report with the corrected markdown.
""")
```

## Rule of Three Enforcement

Track rejection count per job:
- Rejection 1 → re-delegate with fixes
- Rejection 2 → re-delegate with fixes + escalate tone: "Previous revision still failed QA. Address every listed fix precisely."
- Rejection 3 → **abort**: report to user that report could not pass QA after 3 attempts; list the outstanding issues

## Common Fix Patterns

| QA rejection reason | What to tell technical-writer |
|---------------------|-------------------------------|
| Predictive language | "Replace all future-tense predictions with historical observations. Forbidden: 'will increase', 'should buy'. Use: 'historically', 'as of the data period'." |
| Missing disclaimer | "Add a ## Disclaimer section with both required phrases." |
| Narrative fallacy | "Remove causal claims not supported by the correlation statistics. Cite r-value and p-value for every causal assertion." |
| Missing executive summary statistic | "The executive summary must name the exact r-value, coefficient, or percentage from execution_summary." |
| Chart marker at bottom | "Move each `<!-- CHART:id -->` marker to immediately after the paragraph that references it." |

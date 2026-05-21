---
name: report-writing-contract
description: Common technical-writer drafting, chart, source, and validation rules for every ResearchReport.
---

# Report Writing Contract

Use this skill after `plan_report_structure` and before drafting any
technical-writer report.

## Drafting Discipline

- Draft internally and pass the complete narrative directly as the `markdown`
  argument to `write_research_report`.
- You write the prose; the tools only plan, save, and validate it.
- Follow `general_rules` from `plan_report_structure` as the controlling
  outline and report-type contract.
- The `plan_report_structure` result includes `execution_summary_for_draft`,
  which is the controlling fact set from the quant developer. Read it carefully
  and weave every specific number into the relevant analysis sections: exact
  slopes, r values, peak dates, deltas, p-values, forecast values, regime
  labels, and scenario outputs.
- The plan also includes `chart_facts_for_draft`, and those facts are prepended
  to `execution_summary_for_draft`. Treat them as the controlling chart
  contract. Do not describe chart series, overlays, reference bands, rankings,
  nodes, or fields unless they appear in those chart facts.
- Treat the `Exact headline metrics from execution_summary.json` block as
  controlling facts. Copy current values, signs, directions, regime labels,
  explicitly supplied scenario probabilities, and company growth rates exactly.
  Do not substitute older public-memory values or infer an inversion/decline
  when the exact metric says the sign is positive.
- Scenario helper rows usually provide confidence labels, not probabilities. Do
  not invent probability weights, Fed-cut paths, product mix estimates, or
  policy assumptions unless they appear in `execution_summary_for_draft`.
- If `execution_summary_for_draft` looks truncated, continue with the compact
  fields returned by `plan_report_structure`. Do not call `read_file`, `ls`,
  `glob`, `grep`, `execute`, or `write_file` to recover more context.
- If the compact handoff includes `requested_subject_evidence`, treat it as a
  directness contract. When status is `proxy_only`, explicitly label the broad
  aggregate evidence as proxy/indirect, state the missing direct
  subject-specific evidence limitation, and explain confidence using source
  directness, recency, conflicting evidence, or triggers that would change the
  conclusion. Do not turn proxy-only evidence into direct claims about the
  requested population.

## Save Shape

Call `write_research_report` with:

- `markdown`
- `charts_json_path`
- `data_sources`
- `original_query`
- optional: `title`, `executive_summary`, `analysis_type`

Copy `charts_json_path` and `original_query` from the plan result unchanged
into `write_research_report`.

Do not pass `execution_summary` to `write_research_report`; that argument
belongs only to `plan_report_structure`.

End the markdown body with `## Research Query`; do not write a disclaimer
section because the pipeline appends the standard footer.

## Chart Contract

- Place `<!-- CHART:id -->` markers immediately after the text that discusses
  the chart.
- Embed every ID returned in `chart_ids`.
- Use only IDs returned in `chart_ids`.
- Describe only the chart type, axis keys, series, reference areas, scatter
  encodings, segment labels, and flow nodes returned in `chart_facts_for_draft`.
- If the query asks for more visuals than the quant output provides, cover the
  missing view with a markdown table or prose and state the data/artifact
  limitation. Do not create chart markers for unavailable chart IDs.

## Source Contract

`data_sources` must cite only providers evidenced by the handoff or
`execution_summary_for_draft`. For the current public-source feature set, use
exact provider names such as FRED, BLS Public Data, Census Data API, World Bank
Indicators API, and SEC EDGAR. Do not cite OECD, BIS, IMF, generic "Company
Filings", or paid/keyed providers unless the handoff explicitly says that
provider was used.

## Validation

Call `validate_research_report_file` after saving. An empty `report_json_path`
uses the job output directory, or pass the absolute `report_path` returned by
`write_research_report`. If `passes_gate` is false, revise markdown and call
`write_research_report` again until the gate passes or the blockers require new
data.

If `write_research_report` reports an argument error, retry using the Save Shape
rules above. Do not use filesystem or shell tools to save, patch, or recover the
report.

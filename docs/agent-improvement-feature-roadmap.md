# Agent Improvement Feature Roadmap

This roadmap turns the improve-loop findings into implementation features. The
main trend from the salvaged passes is that most quality failures were artifact
contract failures, not pure model reasoning failures: data, charts, summaries,
provenance, and report prose could drift out of sync.

## Target Agent Flow

The long-term architecture should make the agent flow explicit and typed:

```text
planner
  -> source recipe
  -> typed fetch
  -> validated transforms
  -> evidence bundle
  -> chart/report projection
  -> QA
```

### 1. Planner

The planner turns the user request into an analysis plan and declares what
evidence is needed before any data is fetched.

Responsibilities:
- Classify the job type, such as macro risk, company fundamentals, peer
  comparison, recession signal, consumer stress, or valuation.
- Define answer requirements: rankings, charts, scenarios, historical
  comparisons, valuation evidence, caveats, and monitoring points.
- Declare required evidence families, not specific ad hoc tool calls.
- Decide whether the question needs real-time data, historical vintages,
  official macro data, SEC fundamentals, market data, or cross-provider
  corroboration.

Output:
- `AnalysisPlan`
- required evidence families
- expected source coverage
- required chart/report sections
- QA success criteria

### 2. Source Recipe

The source recipe converts the plan into a deterministic data acquisition
contract.

Responsibilities:
- Map each evidence requirement to source providers and source IDs.
- Specify FRED/BLS/BEA/Census/SEC/OpenBB provider choices.
- Define frequency, unit, transform, fiscal-period, and vintage requirements.
- Declare acceptable fallbacks and required limitations when data is
  unavailable.

Output:
- `SourceRecipe`
- `SourceDescriptor` entries
- provider capability checks
- fallback and missing-data policy

### 3. Typed Fetch

Typed fetchers retrieve source data and store raw snapshots with provider
metadata.

Responsibilities:
- Fetch data through source-specific clients.
- Normalize API responses into typed raw records.
- Preserve request URL/query, retrieval time, provider metadata, and response
  hash.
- Fail explicitly on partial, stale, malformed, or rate-limited responses.

Output:
- raw source snapshots
- typed raw tables
- fetch diagnostics
- source freshness metadata

### 4. Validated Transforms

Transforms convert raw source tables into analysis-ready tables while enforcing
schema, unit, frequency, and semantic contracts.

Responsibilities:
- Align periods and fiscal years.
- Convert units only through declared transforms.
- Validate one row per chart axis key where required.
- Validate non-null current/latest facts.
- Validate peer/group coverage.
- Distinguish levels, changes, year-over-year rates, normalized indexes,
  spreads, and correlations.

Output:
- validated normalized tables
- transform descriptors
- validation results
- reusable numeric facts

### 5. Evidence Bundle

The evidence bundle is the single authoritative handoff artifact for downstream
agents.

Responsibilities:
- Collect source descriptors, raw/normalized table references, facts, charts,
  methods, limitations, and validation diagnostics.
- Make every reportable number addressable by `fact_id`.
- Make every chart traceable to source table IDs and transform IDs.
- Run cross-artifact consistency checks before writer delegation.

Output:
- `EvidenceBundle`
- stable `fact_id`s
- stable `chart_id`s
- source coverage summary
- limitations and diagnostics

### 6. Chart/Report Projection

Chart and report projection turns the evidence bundle into user-facing artifacts
without inventing new evidence.

Responsibilities:
- Generate charts from validated source tables.
- Write report prose using cited `fact_id`s and `chart_id`s.
- Separate evidence, interpretation, caveats, and monitoring points.
- Avoid unsupported claims when the evidence bundle lacks required data.
- Preserve all non-dropped chart IDs in `report.json`.

Output:
- `charts.json`
- `report.json`
- chart audit metadata
- report validation metadata

### 7. QA

QA verifies the final artifacts against the original plan and evidence bundle.

Responsibilities:
- Check answer fit against planner success criteria.
- Verify every material quantitative claim maps to a fact.
- Verify chart coverage, source coverage, and limitations.
- Route failures to the correct upstream owner:
  - planner for wrong scope
  - data-engineer for missing or malformed source data
  - quant-developer for transform/fact/chart problems
  - technical-writer for prose, structure, or citation problems

Output:
- approval or structured rejection
- failure category
- required upstream owner
- required fixes

## Priority 1: Canonical Evidence Bundle

### Feature
Create a typed `EvidenceBundle` as the single handoff contract between
data-engineer, quant-developer, technical-writer, and quality-analyst.

### Why
Multiple passes fixed cases where `execution_summary.json`, `numeric_facts`,
charts, and prose represented the same fact differently. A single bundle should
make it impossible to hand off conflicting facts without an explicit validation
failure.

### Implementation Notes
- Define a Pydantic model with `sources`, `raw_tables`, `normalized_tables`,
  `facts`, `charts`, `methods`, `limitations`, `validation`, and `artifacts`.
- Require every report fact to cite a `fact_id`.
- Require every chart to cite its source table and transformed columns.
- Make the writer consume bundle IDs instead of restating arbitrary numbers.
- Emit machine-readable validation failures before writer delegation.

### Acceptance Criteria
- Writer cannot save a report that references uncited quantitative claims.
- QA can trace each report number to a fact ID and source ID.
- Chart IDs and fact IDs are stable across `execution_summary.json`,
  `charts.json`, and `report.json`.

## Priority 2: Source Registry And Dataset Semantics

### Feature
Add a source registry that records provider, series/concept ID, unit, frequency,
currency, fiscal period, transform basis, vintage/as-of date, and revision
policy for every dataset.

### Why
Repeated fixes addressed mixed frequency, source-unit mismatch, SEC fiscal-year
semantics, stale data, and transform confusion. These should be first-class
metadata, not prose conventions.

### Implementation Notes
- Create `SourceDescriptor` and `TransformDescriptor` models.
- Store source descriptors inside the evidence bundle.
- Validate compatible units before comparisons.
- Validate compatible frequencies before joins.
- Require explicit transform basis for correlations, growth rates, spreads, and
  normalized indexes.

### Acceptance Criteria
- Hourly and weekly wage series cannot be directly differenced or overlaid.
- Monthly and quarterly data cannot be merged without a declared period key.
- Correlations with different transform bases are skipped or labeled, not
  compared as the same fact.

## Priority 3: Dataframe Validation Layer

### Feature
Add dataframe-level validation before saving quant artifacts.

### Why
Pydantic validates JSON artifacts after they exist. The failures showed that
many bad outputs start earlier as malformed dataframes: duplicate axis rows,
lost peer groups, null current facts, and unit-incompatible joins.

### Recommended Library
Use Pandera for dataframe validation. It supports runtime validation for
dataframe-like objects and works with pandas plus other backends.

Reference: https://pandera.readthedocs.io/

### Implementation Notes
- Add schemas for common table types:
  - time series panel
  - SEC company fundamentals
  - peer comparison table
  - scenario rows
  - forecast rows
  - chart source table
- Validate uniqueness constraints such as one row per chart axis key.
- Validate required finite columns before emitting numeric facts.

### Acceptance Criteria
- Invalid tables fail before `save_quant_outputs`.
- Chart normalization no longer has to infer or repair ambiguous table shape.
- Validation errors identify the source table and failed column.

## Priority 4: Official Macro Data Expansion

### Feature
Harden and expand official macro data adapters.

### Why
The agent needs broader first-party data coverage for macro, labor, income,
spending, housing, and business-cycle work. This reduces unsupported claims and
keeps evidence coverage from depending on whatever data the model happened to
fetch.

### Data Sources
- FRED and ALFRED for macro series, transformations, and vintages.
  - Observations API: https://fred.stlouisfed.org/docs/api/fred/series_observations.html
  - Real-time periods: https://fred.stlouisfed.org/docs/api/fred/realtime_period.html
- BLS for labor, wages, CPI, employment, and productivity.
  - API overview: https://www.bls.gov/bls/api_features.htm
- BEA for GDP, income, consumption, profits, and national accounts.
  - Open data: https://www.bea.gov/open-data
- Census economic indicators for retail, durable goods, housing, trade, and
  business formation.
  - Time series API: https://api.census.gov/data/timeseries.html

### Implementation Notes
- Add source-specific descriptors with frequency, units, release cadence, and
  revision behavior.
- Add reusable workflows for common macro packs.
- Add ALFRED/vintage mode for historical questions like "what was known then?"

### Acceptance Criteria
- Macro reports cite source coverage by provider and series.
- Historical comparisons can use vintage data when needed.
- Missing source coverage becomes an explicit limitation.

## Priority 5: SEC And Company Fundamentals Upgrade

### Feature
Strengthen SEC EDGAR company facts, submissions, and XBRL frames support for
company analysis and peer comparisons.

### Why
Several reports depended on company fundamentals. The improve loop repeatedly
fixed SEC helper evidence, fiscal-year handling, and unsupported business-driver
claims.

### Data Source
SEC EDGAR APIs provide company submissions, company facts, company concept, and
XBRL frames. They do not require API keys and update throughout the day, with
nightly bulk files.

Reference: https://www.sec.gov/edgar/sec-api-documentation

### Implementation Notes
- Add a robust ticker-to-CIK resolver with cache.
- Prefer SEC helper output for revenue, margins, debt, cash, EPS, cash flow, and
  shares.
- Add fiscal-period alignment for peer comparisons.
- Add filing freshness and amendment handling.
- Store SEC fact taxonomy, unit, form, fiscal period, and accession metadata.

### Acceptance Criteria
- Company reports cannot use SEC data without helper-produced numeric facts and
  source coverage.
- Peer charts preserve ticker coverage and fiscal-period labels.
- Reports distinguish business fundamentals from valuation evidence.

## Priority 6: Market And Valuation Data Provider Abstraction

### Feature
Add a market/valuation provider layer for prices, market cap, multiples,
estimates, revisions, and sector comparisons.

### Why
Some reports discussed valuation risk without actual valuation data. The agent
needs a separate evidence path for price and market expectations, distinct from
SEC fundamentals.

### Candidate Library
OpenBB can be useful as a provider router, but should be wrapped behind an
internal interface because many providers require keys and coverage varies.

References:
- Provider docs: https://docs.openbb.co/odp/python/extensions/providers
- Data providers: https://my.openbb.dev/app/platform/data-providers

### Implementation Notes
- Define a `MarketDataProvider` interface.
- Support configured providers with explicit capability checks.
- Cache market snapshots with timestamp and provider metadata.
- Require valuation reports to state when market data is unavailable.

### Acceptance Criteria
- Valuation claims require market data facts or explicit limitations.
- Provider availability is visible in the evidence bundle.
- Reports separate fundamental quality from valuation risk.

## Priority 7: Chart Source Tables And Lossless Chart Contracts

### Feature
Make charts derive from validated source tables rather than ad hoc chart dicts.

### Why
Grouped peer charts were silently corrupted when long-form grouped data was
collapsed into wide chart rows. Chart integrity should be structural and
deterministic.

### Implementation Notes
- Require every chart to declare a source table ID.
- Store chart source table schema and transform.
- Reject repeated `series.dataKey` with ambiguous `groupBy`.
- Support only lossless long-to-wide conversion when group keys are explicit.
- Keep `chart_normalization_issues` in the handoff.

### Acceptance Criteria
- Peer comparison charts preserve all companies or fail.
- Duplicate axis rows are rejected unless an aggregation is declared.
- Chart audit can explain exactly which source table caused the blocker.

## Priority 8: Permanent Regression Benchmark Suite

### Feature
Turn the improve-loop failures into a permanent benchmark suite.

### Why
The loop surfaced real user-facing failure modes. These should become durable
evals so future changes improve the agent instead of reopening old gaps.

### Benchmark Cases
- NVIDIA resilience if AI spending cools.
- AAPL, MSFT, NVDA long-term quality comparison.
- Broad-market ETF and big-tech macro risks.
- Recession signal and "cried wolf" historical comparison.
- Consumer stress dashboard with wage, credit, savings, and inflation evidence.
- Mixed-frequency macro chart pack.
- SEC company fundamentals with valuation limitation.

### Acceptance Criteria
- Each benchmark checks artifact integrity, source coverage, chart validity, and
  final answer quality.
- CI can run a fast deterministic subset.
- Full agent runs produce trace digests and report artifacts for review.

## Priority 9: Earlier Failure Routing

### Feature
Move more failures upstream before report writing.

### Why
Many fixes made QA smarter, but catching errors at QA is expensive. Bad quant
handoffs should route directly back to quant-developer before the writer spends
tokens on unusable inputs.

### Implementation Notes
- Run evidence-bundle validation immediately after quant output.
- Block writer delegation on artifact-fact mismatch, chart handoff mismatch,
  missing helper evidence, source-unit mismatch, and stale helper evidence.
- Emit repair instructions with required upstream owner.

### Acceptance Criteria
- Technical-writer only receives validated evidence bundles.
- QA failures become rare and focused on narrative quality.
- Orchestrator recovery routes to the correct owner deterministically.

## Priority 10: Reproducible Data And Artifact Cache

### Feature
Add a content-addressed cache for fetched source data, normalized tables,
evidence bundles, and generated artifacts.

### Why
The agent needs reproducibility across runs. A report should be auditable from
the exact data snapshot used, not just current API state.

### Implementation Notes
- Hash raw API responses and normalized tables.
- Store provider, URL/query, retrieval timestamp, and response metadata.
- Persist source snapshots under job output directories or a shared cache.
- Add cache invalidation by provider freshness policy.

### Acceptance Criteria
- A report can be regenerated from stored source snapshots.
- CI fixtures can use frozen source snapshots.
- Source freshness is explicit in report limitations.

## Suggested Implementation Order

1. Canonical `EvidenceBundle`.
2. Source registry and transform descriptors.
3. Dataframe validation with Pandera.
4. Official macro source expansion.
5. SEC fundamentals upgrade.
6. Chart source table contract.
7. Market/valuation provider abstraction.
8. Regression benchmark suite.
9. Earlier failure routing.
10. Reproducible artifact cache.

## Implementation History

This section is updated by `scripts/codex_feature_loop.sh` when a feature pass is
approved. It is the durable feature-loop memory: each entry records what was
implemented, where it landed, how it was tested, and which part of the target
agent flow it advanced.

- [x] Roadmap feature implementation harness
  - Roadmap section: feature loop infrastructure
  - Flow stage: cross-cutting
  - Run/pass: manual / current
  - Summary: implemented in the current working tree
  - Files changed: `scripts/codex_feature_loop.sh`, `scripts/feature_loop/prompts/*`
  - Tests: `bash -n scripts/codex_feature_loop.sh`; `scripts/codex_feature_loop.sh --help`; dry-run pass with logs redirected to `/tmp`
  - Implementation: reworked the feature loop around roadmap feature selection, plan/build/review/fix phases, approved-pass commits, and roadmap implementation-history updates instead of signal-style memory.
  - Review: pending user review

- [x] 2026-05-19T13:27:28-04:00 - Feature loop multi-pass default fix
  - Roadmap section: feature loop infrastructure
  - Flow stage: cross-cutting
  - Run/pass: manual / current
  - Summary: fixed the harness control flow defaults after the first approved feature pass stopped the run.
  - Files changed: `scripts/codex_feature_loop.sh`, `docs/agent-improvement-feature-roadmap.md`
  - Tests: `bash -n scripts/codex_feature_loop.sh`; `scripts/codex_feature_loop.sh --help`; `LOG_ROOT=/tmp/dra-feature-loop-check RUN_ID=default-iteration-check FEATURE_LOOP_AUTO_COMMIT=0 FEATURE_LOOP_AUTO_PUSH=0 scripts/codex_feature_loop.sh --dry-run 2`; `DRY_RUN_REVIEW_SEQUENCE=approved LOG_ROOT=/tmp/dra-feature-loop-default10 RUN_ID=default-ten-check FEATURE_LOOP_AUTO_COMMIT=0 FEATURE_LOOP_AUTO_PUSH=0 scripts/codex_feature_loop.sh --dry-run`
  - Implementation: changed the default feature pass count from 1 to 10, made the per-feature fix/review loop unlimited by default, printed the pass range at startup, and recorded final review findings at the top of pass summaries so roadmap memory uses the approved review instead of the first failed attempt.
  - Review: local shell validation confirmed the harness reaches feature pass 10 by default.

- [x] 2026-05-19T10:04:03-04:00 - Canonical Evidence Bundle save-boundary slice
  - Roadmap section: Priority 1: Canonical Evidence Bundle
  - Flow stage: evidence bundle
  - Run/pass: 20260519-084446 / 1
  - Summary: /home/vorndranj/projects/DeepResearchAgent/logs/feature-loop/runs/20260518-215941/feature-1/summary.md
  - Files changed: backend/agents/quant_macro_stats/artifacts/evidence_bundle.py, backend/agents/quant_macro_stats/artifacts/quant_output_writer.py, backend/agents/quant_macro_stats/artifacts/execution_summary_normalization.py, backend/agents/report_artifacts.py, backend/agents/quality_analyst/fidelity.py, backend/agents/quality_analyst/tools.py, backend/tests/test_quant_macro_stats.py, backend/tests/test_quality_analyst_subagent.py
  - Tests: uv run pytest tests/test_quant_macro_stats.py -k "evidence_bundle or save_quant_outputs_writes_generic_evidence_payload or preserves_chart_provenance or overwrites_stale_artifacts or rejects_conflicting_correlation_facts"; uv run pytest tests/test_technical_writer_flow_boundaries.py -k "validate_research_report_file_rejects_missing_handoff_chart_ids or validate_research_report_file_rejects_artifact_fact_mismatch"; uv run pytest tests/test_quality_analyst_subagent.py -k "load_report_for_review"; uv run ruff check agents/quant_macro_stats/artifacts/evidence_bundle.py agents/quant_macro_stats/artifacts/quant_output_writer.py agents/quant_macro_stats/artifacts/execution_summary_normalization.py agents/report_artifacts.py agents/quality_analyst/fidelity.py agents/quality_analyst/tools.py tests/test_quant_macro_stats.py tests/test_quality_analyst_subagent.py
  - Implementation: Added a typed evidence_bundle.json sidecar at save_quant_outputs and surfaced its path and compact IDs to QA.
  - Review: Incomplete patch missing new module; QA accepts unvalidated bundle JSON; bundle validation does not enforce fact-to-source traceability.

- [x] 2026-05-19T14:38:54-04:00 - Source registry and transform descriptors
  - Roadmap section: Priority 2: Source Registry And Dataset Semantics
  - Flow stage: source recipe
  - Run/pass: 20260519-132826 / 1
  - Summary: /home/vorndranj/projects/DeepResearchAgent/logs/feature-loop/runs/20260519-132826/feature-1/summary.md
  - Files changed: backend/agents/quant_macro_stats/artifacts/evidence_bundle.py, backend/agents/quant_macro_stats/artifacts/numeric_fact_contracts.py, backend/agents/quant_macro_stats/artifacts/source_unit_fidelity.py, backend/agents/quant_macro_stats/catalog.py, backend/agents/quant_macro_stats/company/sec_company_facts_evidence.py, backend/tests/test_quant_macro_stats.py, backend/tests/test_quality_analyst_subagent.py, backend/tests/test_orchestrator_middleware.py
  - Tests: cd backend && uv run pytest tests/test_quant_macro_stats.py; cd backend && uv run pytest tests/test_quality_analyst_subagent.py -k "evidence_bundle or source_unit_mismatch or load_report_for_review"; cd backend && uv run pytest tests/test_orchestrator_middleware.py -k "evidence_bundle or quant_artifact_recovery"; cd backend && uv run ruff check agents/quant_macro_stats/artifacts/evidence_bundle.py agents/quant_macro_stats/artifacts/source_unit_fidelity.py agents/quant_macro_stats/artifacts/numeric_fact_contracts.py agents/quant_macro_stats/artifacts/quant_output_writer.py agents/quant_macro_stats/catalog.py agents/quant_macro_stats/company/sec_company_facts_evidence.py tests/test_quant_macro_stats.py tests/test_quality_analyst_subagent.py tests/test_orchestrator_middleware.py
  - Implementation: Implemented typed source and transform descriptors in evidence_bundle.json with save-boundary validation for source semantics and derived-transform basis.
  - Review: no blocking findings; roadmap-aligned source/transform descriptor slice with adequate targeted verification

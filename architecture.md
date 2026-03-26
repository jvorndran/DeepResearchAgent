┌─────────────────────────────────────────────────────────────────────────────────┐
│                        USER INTERFACE (React / Next.js)                         │
│                                                                                 │
│  ┌────────────────────────────────────────────────────────────────────────────┐ │
│  │ User: "Analyze TSMC vs GlobalFoundries CapEx and Silicon Wafer volume."    │ │
│  │ Agent: "Understood. Starting deep research job..."                         │ │
│  └────────────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────┬──────────────────────────────────────────────┘
                                   │ REST API (Sync) & SSE (Async Status)
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                       GCP API GATEWAY (Cloud Run - Sync)                        │
│ • Generates job_id. Writes initial state to Cloud SQL (MySQL).                  │
│ • Dispatches task to Cloud Tasks. Returns 202 Accepted.                         │
└─────────┬─────────────────────────────────────────────────────────────┬─────────┘
          │ Enqueues Task                                               │ Updates
          ▼                                                             ▼
┌─────────────────────────┐                                 ┌─────────────────────┐
│    GCP CLOUD TASKS      │                                 │ CLOUD SQL (MySQL)   │
│ • Manages async queue   │                                 │ • Job State         │
└─────────┬───────────────┘                                 │ • Agent Context     │
          │ Triggers                                        └─────────▲───────────┘
          ▼                                                           │ Reads/Writes
┌─────────────────────────────────────────────────────────────────────┴───────────┐
│                   DEEP RESEARCH WORKER (Cloud Run Job)                          │
│                                                                                 │
│  ┌────────────────────────────────────────────────────────────────────────────┐ │
│  │                  LANGCHAIN DEEP AGENTS ORCHESTRATION                       │ │
│  │                                                                            │ │
│  │ ┌──────────────────────────────────────────────────────────────────────┐   │ │
│  │ │  ORCHESTRATOR (Gemini 3.0 Flash Preview)                             │   │ │
│  │ │  Role: Project Manager / Research Director                           │   │ │
│  │ │                                                                      │   │ │
│  │ │  • Breaks down research query into delegatable tasks                 │   │ │
│  │ │  • Routes to subagents based on task requirements                    │   │ │
│  │ │  • Maintains conversation context across handoffs                    │   │ │
│  │ │  • Rule of Three: max 3 retries per subagent before abort            │   │ │
│  │ │  • On QA rejection: re-delegates to Technical Writer with fixes      │   │ │
│  │ └──────────────────────────────────────────────────────────────────────┘   │ │
│  │             │                                                              │ │
│  │             │ Delegates to Subagents                                       │ │
│  │             ▼                                                              │ │
│  │ ┌──────────────────────────────────────────────────────────────────────┐   │ │
│  │ │  ROLE-BASED SUBAGENTS (Autonomous Specialists)                       │   │ │
│  │ │                                                                      │   │ │
│  │ │  ┌────────────────────────────────────────────────────────────────┐  │   │ │
│  │ │  │ 1. DATA ENGINEER (Gemini 3.0 Flash)                            │  │   │ │
│  │ │  │    Role: Data Engineer / Data Analyst                          │  │   │ │
│  │ │  │                                                                │  │   │ │
│  │ │  │    Tools: fetch_financial_data, fetch_fred_data,               │  │   │ │
│  │ │  │           extract_data_schema, list_stored_files               │  │   │ │
│  │ │  │                                                                │  │   │ │
│  │ │  │    • Fetch financial data from FMP/FRED APIs                   │  │   │ │
│  │ │  │    • Save raw data to outputs/{job_id}/ (CSV)                  │  │   │ │
│  │ │  │    • Extract exact schemas (deterministic, no LLM)             │  │   │ │
│  │ │  │    • [STOP] Returns ONLY storage paths + metadata (no raw data)│  │   │ │
│  │ │  │    • [SHIELD] MITIGATES: Context window bloat                  │  │   │ │
│  │ │  └────────────────────────────────────────────────────────────────┘  │   │ │
│  │ │                                                                      │   │ │
│  │ │  ┌────────────────────────────────────────────────────────────────┐  │   │ │
│  │ │  │ 2. QUANTITATIVE DEVELOPER (OpenAI o1/o3)                       │  │   │ │
│  │ │  │    Role: Quantitative Developer / Quant Analyst                │  │   │ │
│  │ │  │                                                                │  │   │ │
│  │ │  │    Tools: generate_analysis_code, validate_code_syntax,        │  │   │ │
│  │ │  │           execute_analysis_code                                │  │   │ │
│  │ │  │                                                                │  │   │ │
│  │ │  │    • Receives ONLY schemas (no raw data arrays)                │  │   │ │
│  │ │  │    • Generates pandas/numpy/scipy analysis code                │  │   │ │
│  │ │  │    • Validates syntax before execution                         │  │   │ │
│  │ │  │    • Executes code in isolated Docker sandbox                  │  │   │ │
│  │ │  │    • Saves charts as named dict to outputs/{job_id}/charts.json│  │   │ │
│  │ │  │    • Prints compact execution_summary JSON to stdout           │  │   │ │
│  │ │  │    • [SHIELD] MITIGATES: Hallucinated column names             │  │   │ │
│  │ │  └────────────────────────────────────────────────────────────────┘  │   │ │
│  │ │                                                                      │   │ │
│  │ │  ┌────────────────────────────────────────────────────────────────┐  │   │ │
│  │ │  │ 3. TECHNICAL WRITER (Gemini 3.0 Flash Preview)                 │  │   │ │
│  │ │  │    Role: Technical Writer / Research Analyst                   │  │   │ │
│  │ │  │                                                                │  │   │ │
│  │ │  │    Tools: plan_report_structure, write_research_report         │  │   │ │
│  │ │  │                                                                │  │   │ │
│  │ │  │    • Reads charts.json directly from disk (not via context)    │  │   │ │
│  │ │  │    • Plans report structure by query type                      │  │   │ │
│  │ │  │    • Writes markdown with inline <!-- CHART:id --> markers     │  │   │ │
│  │ │  │    • Validates via Pydantic (ResearchReport schema v1)         │  │   │ │
│  │ │  │    • Sole producer of outputs/{job_id}/report.json             │  │   │ │
│  │ │  │    • On QA rejection: re-runs with required_fixes applied      │  │   │ │
│  │ │  └────────────────────────────────────────────────────────────────┘  │   │ │
│  │ │                                                                      │   │ │
│  │ │  ┌────────────────────────────────────────────────────────────────┐  │   │ │
│  │ │  │ 4. QUALITY ANALYST (Gemini 3.0 Flash)                          │  │   │ │
│  │ │  │    Role: Quality Analyst / Compliance Officer                  │  │   │ │
│  │ │  │                                                                │  │   │ │
│  │ │  │    Tools: validate_report_format, check_compliance,            │  │   │ │
│  │ │  │           verify_chart_references, patch_report,               │  │   │ │
│  │ │  │           approve_report, reject_report                        │  │   │ │
│  │ │  │                                                                │  │   │ │
│  │ │  │    • Validates Pydantic schema + mandatory markdown elements   │  │   │ │
│  │ │  │    • Checks compliance (no predictive language/advice)         │  │   │ │
│  │ │  │    • Verifies all <!-- CHART:id --> markers resolve            │  │   │ │
│  │ │  │    • AUTO-PATCHES minor issues without rejecting:              │  │   │ │
│  │ │  │        - Missing disclaimer → patch_report("add_disclaimer")   │  │   │ │
│  │ │  │        - Missing past perf notice → patch_report("add_past..") │  │   │ │
│  │ │  │        - Missing footer → patch_report("add_footer")           │  │   │ │
│  │ │  │        - Broken chart markers → patch_report("remove_broken..")│  │   │ │
│  │ │  │    • CRITICAL issues → reject_report with required_fixes list  │  │   │ │
│  │ │  │    • Final gatekeeper: nothing reaches user without approval   │  │   │ │
│  │ │  └────────────────────────────────────────────────────────────────┘  │   │ │
│  │ └──────────────────────────────────────────────────────────────────────┘   │ │
│  └─────────────────────────────────┬──────────────────────────────────────────┘ │
└────────────────────────────────────┼────────────────────────────────────────────┘
                                     │ Saves Final Artifacts
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                          GOOGLE CLOUD STORAGE (GCS)                             │
│ • outputs/{job_id}/raw_*.csv          <-- Kept separate from context window    │
│ • outputs/{job_id}/charts.json        <-- Named chart dict (Recharts-compatible)│
│ • outputs/{job_id}/report.json        <-- Canonical ResearchReport artifact     │
└─────────────────────────────────────────────────────────────────────────────────┘


## ORCHESTRATION WORKFLOW

```
Phase 1: INTAKE & CLARIFICATION
────────────────────────────────
User Query: "Analyze TSMC vs GlobalFoundries CapEx correlation with wafer volumes"
    │
    ▼
Orchestrator checklist (must ALL be confirmed before proceeding):
  [ ] Target assets / tickers defined
  [ ] Exact metrics specified
  [ ] Historical timeframe defined
  [ ] Visualization type requested
    │
    │ (clarifying questions if any item missing)
    ▼

Phase 2: DATA ACQUISITION
─────────────────────────
Orchestrator → task(name="data-engineer", task="Fetch TSMC + GFS capex 2020-2024")
    │
    ▼
Data Engineer:
  • Fetches from FMP/FRED APIs
  • Saves: outputs/{job_id}/raw_tsmc_capex.csv
           outputs/{job_id}/raw_gfs_capex.csv
  • Extracts compact schemas (columns, dtypes, 2 sample rows)
  • Returns: { storage_paths: [...], schemas: [...] }
    │
    ▼ (paths + schemas only — no raw data)

Phase 3: QUANTITATIVE ANALYSIS & CHART GENERATION
───────────────────────────────────────────────────
Orchestrator → task(name="quant-developer", task="Correlate capex with wafer volumes")
  Passes: schemas, storage_paths, chart format instructions
    │
    ▼
Quant Developer:
  • Generates pandas/scipy code using EXACT schema column names
  • Validates syntax
  • Executes in Docker sandbox (no network, read-only data mount)
  • Saves: outputs/{job_id}/charts.json  ← named dict keyed by chart_id
  • Prints: execution_summary JSON to stdout
    │
  ┌─┴──────────────────────────────────┐
  │ ERROR: returns traceback           │
  │   → Orchestrator retries with fix  │
  │   → Max 3 retries, then abort      │
  └────────────────────────────────────┘
    │
    ▼ (charts_json_path + execution_summary)

Phase 4: REPORT SYNTHESIS
──────────────────────────
Orchestrator → task(name="technical-writer", task="Write report for job {job_id}")
  Passes: charts_json_path, execution_summary, data_sources, original_query, job_id
  (NO chart data arrays — technical writer reads charts.json from disk directly)
    │
    ▼
Technical Writer:
  Step 1 → plan_report_structure(query_type, charts_json_path, execution_summary, query)
             Reads chart IDs from disk, returns section outline with chart placement
  Step 2 → write_research_report(outline, charts_json_path, execution_summary, ...)
             Reads full chart definitions from disk
             Builds markdown narrative with inline <!-- CHART:id --> markers
             Validates via Pydantic (ResearchReport schema v1)
             Saves: outputs/{job_id}/report.json
  Returns: { report_path, chart_count, word_count, validation_issues }
    │
    ▼ (report_json_path)

Phase 5: QUALITY ASSURANCE
───────────────────────────
Orchestrator → task(name="quality-analyst", task="Review report at outputs/{job_id}/report.json")
  Passes: report_json_path, execution_summary
    │
    ▼
Quality Analyst (4-step triage):
  Step 1 → validate_report_format(report_json_path)
             Pydantic schema check + mandatory element scan
  Step 2 → check_compliance(report.markdown)   ← TEXT not path
             Regex scan for predictive language / investment advice
  Step 3 → verify_chart_references(report_json_path)
             Checks every <!-- CHART:id --> resolves in report.charts
  Step 4 → TRIAGE:

    ┌──────────────────────────────────────────────────────────────────────┐
    │  Issue                          │ Severity    │ Action               │
    ├──────────────────────────────────────────────────────────────────────┤
    │  Predictive language / advice   │ CRITICAL    │ reject_report        │
    │  Missing exec summary / sources │ CRITICAL    │ reject_report        │
    │  Original query not in markdown │ CRITICAL    │ reject_report        │
    │  Pydantic schema error          │ CRITICAL    │ reject_report        │
    │  Missing disclaimer text        │ AUTO-FIX    │ patch_report(...)    │
    │  Missing past performance notice│ AUTO-FIX    │ patch_report(...)    │
    │  Missing footer                 │ AUTO-FIX    │ patch_report(...)    │
    │  Broken <!-- CHART:id --> marker│ AUTO-FIX    │ patch_report(...)    │
    │  Minor formatting / typos       │ MINOR       │ note in approve      │
    └──────────────────────────────────────────────────────────────────────┘

    AUTO-FIX path:
      patch_report(path, patch_type) × N
        → re-run validate_report_format
        → if still fails → now CRITICAL → reject_report
        → if passes → approve_report
    │
    ├──► APPROVED: { status: "approved", report_path, notes, ready_for_upload: true }
    │        │
    │        ▼
    │    Phase 6: Final Handoff
    │
    └──► REJECTED: { status: "rejected", reason, required_fixes: [...], ready_for_upload: false }
             │
             ▼
         Orchestrator re-delegates to Technical Writer with required_fixes list
         Technical Writer re-runs plan_report_structure → write_research_report
         Orchestrator re-delegates to Quality Analyst
         ┌─ Rule of Three: after 3 QA rejections → gracefully abort, surface reason to user

Phase 6: FINAL HANDOFF
────────────────────────
outputs/{job_id}/report.json is confirmed saved and approved.
Report contains:
  • Full markdown narrative with inline <!-- CHART:id --> markers
  • Complete chart definitions (Recharts-compatible JSON)
  • Data source metadata
  • ReportMetadata (analysis_type, chart_count, word_count)
Frontend renders report.json — charts resolved client-side by marker ID.
```


## KEY ARCHITECTURAL PRINCIPLES

### 1. Role-Based Subagents
Instead of generic "agents with tools", we have specialized roles:
- **Orchestrator**: Research director — delegates, coordinates, enforces retry limits
- **Data Engineer**: Fetches and schemas raw financial data; never passes arrays upstream
- **Quantitative Developer**: Writes and sandboxes analysis code; produces charts.json
- **Technical Writer**: Sole assembler of report.json; reads artifacts directly from disk
- **Quality Analyst**: Final gatekeeper; auto-patches minor issues, rejects critical ones

### 2. Data Decoupling
Raw data NEVER enters agent context:
- Data Engineer saves to `outputs/{job_id}/`, returns paths + compact schemas only
- Quant Developer reads CSVs inside sandbox, prints only a compact `execution_summary` to stdout
- Technical Writer reads `charts.json` from disk — chart data arrays never pass through orchestrator
- Quality Analyst reads `report.json` from disk via Pydantic

### 3. Multi-Model Routing
Different models for different strengths:
- **Gemini 3.0 Flash Preview**: Orchestrator, Technical Writer (reasoning, synthesis, writing)
- **Gemini 3.0 Flash**: Data Engineer, Quality Analyst (pattern detection, evaluation)
- **OpenAI gpt-5**: Quantitative Developer (mathematical reasoning, code generation)

### 4. Canonical Artifact: report.json (ResearchReport v1)
The single output artifact is `outputs/{job_id}/report.json` — a validated `ResearchReport` object:
- `markdown`: full narrative with `<!-- CHART:id -->` inline markers
- `charts`: dict of chart definitions keyed by chart_id (Recharts-compatible)
- `data_sources`: list of DataSource metadata objects
- `executive_summary`, `query`, `title`: top-level fields
- `metadata`: `analysis_type`, `chart_count`, `word_count`

### 5. QA Auto-Patch Loop
Quality Analyst can autonomously fix four classes of minor issues before deciding to approve/reject:
- All `patch_report` operations are idempotent (safe to call multiple times)
- After patching, QA always re-validates via `validate_report_format` — never trusts stale results
- Only CRITICAL findings (predictive language, missing required sections, schema errors) reach the Orchestrator as rejections

### 6. Error Handling & Rule of Three
Orchestrator manages all retry loops:
- Max 3 retries per subagent per phase
- QA rejections trigger re-delegation to Technical Writer with the `required_fixes` list
- After 3 QA rejections the orchestrator gracefully aborts and surfaces the rejection reason to the user
- No infinite loops — every retry path is bounded

### 7. Security
- Docker sandbox has NO network access
- Data files mounted as read-only
- Code execution time-limited (5 min timeout)
- Memory and CPU limits enforced


## BENEFITS OVER LANGGRAPH

### LangGraph (Old Approach)
- Rigid state machine with predefined nodes
- Explicit state object passed between nodes
- Hard-coded conditional edges for routing
- Checkpointing for state persistence

### LangChain Deep Agents (New Approach)
- Autonomous subagents with flexible delegation
- Conversation context instead of state object
- Dynamic routing via Orchestrator decisions
- Role-based specialization (more intuitive)

### Why This Is Better
1. **More Natural**: Subagents communicate like a real team
2. **Easier to Extend**: Add new subagents without rewiring the DAG
3. **Better Model Assignment**: Each role gets the best model for its task
4. **Clearer Code**: Role names (Data Engineer) vs generic names (ResearchAgent)
5. **Flexible Retries**: Orchestrator can retry any subagent with context
6. **Autonomous QA Patching**: Minor compliance gaps fixed in-place, reducing unnecessary rejection round-trips

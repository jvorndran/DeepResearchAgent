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
│  │ │  ORCHESTRATOR (Gemini 2.0 Flash)                                     │   │ │
│  │ │  Role: Project Manager / Research Director                           │   │ │
│  │ │                                                                      │   │ │
│  │ │  • Breaks down research query into delegatable tasks                 │   │ │
│  │ │  • Routes to subagents based on task requirements                    │   │ │
│  │ │  • Maintains conversation context across handoffs                    │   │ │
│  │ │  • Manages retry logic and error recovery                            │   │ │
│  │ └──────────────────────────────────────────────────────────────────────┘   │ │
│  │             │                                                              │ │
│  │             │ Delegates to Subagents                                       │ │
│  │             ▼                                                              │ │
│  │ ┌──────────────────────────────────────────────────────────────────────┐   │ │
│  │ │  ROLE-BASED SUBAGENTS (Autonomous Specialists)                       │   │ │
│  │ │                                                                      │   │ │
│  │ │  ┌────────────────────────────────────────────────────────────────┐  │   │ │
│  │ │  │ 1. DATA ENGINEER (Gemini 2.0 Flash)                            │  │   │ │
│  │ │  │    Role: Data Engineer / Data Analyst                          │  │   │ │
│  │ │  │                                                                │  │   │ │
│  │ │  │    Capabilities:                                               │  │   │ │
│  │ │  │    • Fetch financial data from FMP/FRED APIs                   │  │   │ │
│  │ │  │    • Save raw data to storage (GCS or local)                   │  │   │ │
│  │ │  │    • Extract exact schemas (deterministic, no LLM)             │  │   │ │
│  │ │  │    • 🛑 Returns ONLY storage paths + metadata (no raw data)    │  │   │ │
│  │ │  │    • 🛡️ MITIGATES: Context window bloat                        │  │   │ │
│  │ │  └────────────────────────────────────────────────────────────────┘  │   │ │
│  │ │                                                                      │   │ │
│  │ │  ┌────────────────────────────────────────────────────────────────┐  │   │ │
│  │ │  │ 2. QUANTITATIVE DEVELOPER (OpenAI o1/o3)                       │  │   │ │
│  │ │  │    Role: Quantitative Developer / Quant Analyst                │  │   │ │
│  │ │  │                                                                │  │   │ │
│  │ │  │    Capabilities:                                               │  │   │ │
│  │ │  │    • Generate pandas/numpy/scipy analysis code                 │  │   │ │
│  │ │  │    • Receives ONLY schemas (no raw data)                       │  │   │ │
│  │ │  │    • Validate code syntax before execution                     │  │   │ │
│  │ │  │    • Execute code in isolated Docker sandbox                   │  │   │ │
│  │ │  │    • Handle errors and retry with fixes                        │  │   │ │
│  │ │  │    • Output structured JSON for Recharts                       │  │   │ │
│  │ │  │    • 🛡️ MITIGATES: Hallucinated column names                   │  │   │ │
│  │ │  └────────────────────────────────────────────────────────────────┘  │   │ │
│  │ │                                                                      │   │ │
│  │ │  ┌────────────────────────────────────────────────────────────────┐  │   │ │
│  │ │  │ 3. TECHNICAL WRITER (Gemini 2.0 Flash)                         │  │   │ │
│  │ │  │    Role: Technical Writer / Research Analyst                   │  │   │ │
│  │ │  │                                                                │  │   │ │
│  │ │  │    Capabilities:                                               │  │   │ │
│  │ │  │    • Synthesize Markdown report from execution results         │  │   │ │
│  │ │  │    • Use strict template for consistency                       │  │   │ │
│  │ │  │    • Embed chart_data.json references (not static images)      │  │   │ │
│  │ │  │    • Extract key findings and statistical insights             │  │   │ │
│  │ │  │    • Include proper disclaimers                                │  │   │ │
│  │ │  └────────────────────────────────────────────────────────────────┘  │   │ │
│  │ │                                                                      │   │ │
│  │ │  ┌────────────────────────────────────────────────────────────────┐  │   │ │
│  │ │  │ 4. QUALITY ANALYST (Gemini 2.0 Flash)                          │  │   │ │
│  │ │  │    Role: Quality Analyst / Compliance Officer                  │  │   │ │
│  │ │  │                                                                │  │   │ │
│  │ │  │    Capabilities:                                               │  │   │ │
│  │ │  │    • Validate Markdown formatting                              │  │   │ │
│  │ │  │    • Cross-check findings with execution results               │  │   │ │
│  │ │  │    • Ensure no predictive financial advice (compliance)        │  │   │ │
│  │ │  │    • Verify chart references are correct                       │  │   │ │
│  │ │  │    • Final gatekeeper for artifact approval                    │  │   │ │
│  │ │  └────────────────────────────────────────────────────────────────┘  │   │ │
│  │ └──────────────────────────────────────────────────────────────────────┘   │ │
│  └─────────────────────────────────┬──────────────────────────────────────────┘ │
└────────────────────────────────────┼────────────────────────────────────────────┘
                                     │ Saves Final Artifacts
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                          GOOGLE CLOUD STORAGE (GCS)                             │
│ • /jobs/{job_id}/raw_tsmc_data.csv   <-- Kept separate from context window     │
│ • /jobs/{job_id}/scatter_plot.png                                               │
│ • /jobs/{job_id}/final_report.md                                                │
│ • /jobs/{job_id}/chart_data.json     <-- Interactive Recharts data              │
└─────────────────────────────────────────────────────────────────────────────────┘

## ORCHESTRATION WORKFLOW

### 1. Orchestrator receives query
```
User Query: "Analyze TSMC vs GlobalFoundries CapEx correlation with wafer volumes"
    ↓
Orchestrator: "I need to break this down into tasks:
  1. Fetch financial data for TSMC and GFS
  2. Fetch semiconductor wafer volume data
  3. Analyze the schemas
  4. Generate correlation analysis code
  5. Execute the code
  6. Write a report
  7. Review for quality"
```

### 2. Orchestrator → Data Engineer
```
Orchestrator delegates: "Fetch financial data for TSMC and GFS (capex, 2020-2024)"
    ↓
Data Engineer:
  • Fetches from FMP API
  • Saves to: /jobs/{job_id}/raw_tsmc_capex.csv
  • Saves to: /jobs/{job_id}/raw_gfs_capex.csv
  • Returns: {"storage_paths": [...], "metadata": {...}}
    ↓
Orchestrator receives: Storage paths ONLY (not raw data)
```

### 3. Orchestrator → Data Engineer (Schema Analysis)
```
Orchestrator delegates: "Analyze schemas for the fetched data"
    ↓
Data Engineer:
  • Loads CSVs with pandas (deterministic, no LLM)
  • Extracts: columns, dtypes, sample rows, shape
  • Returns: {"schemas": [{"columns": [...], "dtypes": {...}, "sample_rows": [...]}]}
    ↓
Orchestrator receives: Compact schemas (not full data)
```

### 4. Orchestrator → Quantitative Developer (Code Generation)
```
Orchestrator delegates: "Generate code to correlate capex with wafer volumes"
Context: Schemas (exact column names)
    ↓
Quantitative Developer:
  • Uses OpenAI o1/o3 with schema-based prompt
  • Generates pandas/scipy code with EXACT column names
  • Validates syntax
  • Saves to: /jobs/{job_id}/analysis_code.py
  • Returns: {"code_path": ..., "expected_outputs": ["chart_data.json"]}
```

### 5. Orchestrator → Quantitative Developer (Execution)
```
Orchestrator delegates: "Execute the generated code"
    ↓
Quantitative Developer:
  • Runs code in Docker sandbox (no network access)
  • Mounts data files as read-only
  • Captures stdout/stderr
  • Checks for chart_data.json output
    ↓
If SUCCESS:
  • Returns: {"status": "success", "output_paths": [...]}
    ↓
If ERROR:
  • Returns: {"status": "error", "traceback": "KeyError: 'revenue'"}
  • Orchestrator retries with Code Generation (includes error feedback)
  • Max 3 retries, then fail
```

### 6. Orchestrator → Technical Writer
```
Orchestrator delegates: "Write the final report"
Context: Execution results, chart data paths, original query
    ↓
Technical Writer:
  • Loads Markdown template
  • Extracts key findings from execution results
  • Embeds chart_data.json references
  • Adds disclaimers
  • Saves to: /jobs/{job_id}/final_report.md
  • Returns: {"report_path": ..., "report": "..."}
```

### 7. Orchestrator → Quality Analyst
```
Orchestrator delegates: "Review the report for quality and compliance"
    ↓
Quality Analyst:
  • Checks Markdown formatting
  • Verifies no predictive language
  • Cross-checks findings with execution results
  • Validates chart references
    ↓
If APPROVED:
  • Returns: {"status": "approved", "ready_for_upload": true}
  • Orchestrator uploads to GCS
    ↓
If REJECTED:
  • Returns: {"status": "rejected", "issues": [...]}
  • Orchestrator fails the job or requests Technical Writer revision
```

## KEY ARCHITECTURAL PRINCIPLES

### 1. Role-Based Subagents
Instead of generic "agents with tools", we have specialized roles:
- **Orchestrator**: Like a research director coordinating the team
- **Data Engineer**: Handles all data operations
- **Quantitative Developer**: Writes and runs analysis code
- **Technical Writer**: Synthesizes reports
- **Quality Analyst**: Final compliance check

### 2. Data Decoupling
Raw data NEVER enters agent context:
- Data Engineer saves to storage, returns paths only
- Schemas are compact (columns, dtypes, 2 sample rows max)
- Code operates on storage paths, not context data

### 3. Multi-Model Routing
Different models for different strengths:
- **Gemini 2.0 Flash**: Orchestrator, Data Engineer, Technical Writer, Quality Analyst
  (Good at reasoning, delegation, writing)
- **OpenAI o1/o3**: Quantitative Developer
  (Excellent at code generation and mathematical reasoning)

### 4. Error Handling
Orchestrator manages retries:
- Tracks retry count per subagent
- Max 3 retries before failure
- Includes error context in retry attempts
- No infinite loops

### 5. Security
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

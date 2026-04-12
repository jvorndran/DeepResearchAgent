# Deep Research Agent Flow

This document defines the end-to-end execution flow of the Deep Research Agent.

## 1. Phase 1: Intake & Clarification
- **Goal:** Ensure the research query is fully specified.
- **Agent:** Orchestrator
- **Logic:**
  - If tickers, metrics, or timeframe are missing/vague:
    - Orchestrator asks clarifying questions using `emit_chat_message`.
    - Workflow pauses for user input.
  - If query is fully specified:
    - Orchestrator confirms: "I now have what I need to proceed. Please click **Commence Deep Research** below to begin."
    - Workflow pauses for user approval.

## 2. Phase 2: Data Acquisition
- **Goal:** Fetch raw financial/macro data and extract schemas.
- **Agent:** `data-engineer`
- **Tools:** FMP MCP (Financial Modeling Prep), FRED MCP (Macro data), `save_data`, `extract_schema`.
- **Access Model:** Backend filesystem and shell tools are blocked by subagent middleware; only MCP data-fetch tools (`save_data`, `extract_schema`) are available.
- **Output:** CSV files in `backend/data/{job_id}/`.
- **Invariant:** Returns ONLY file paths, row counts, and column schemas to the Orchestrator. NEVER returns raw data arrays.

## 3. Phase 3: Quantitative Analysis
- **Goal:** Perform mathematical analysis and generate visualization data.
- **Agent:** `quant-developer`
- **Process:**
  - Receives file paths and schemas from Orchestrator.
  - Writes Python code (`analysis.py`) to `backend/outputs/{job_id}/code/`.
  - Executes code in sandbox using the venv Python interpreter.
  - Iterates on errors (max 3 retries).
- **Output:** `backend/outputs/{job_id}/charts.json` (Recharts-compatible format).
- **Chart Features:** All axis charts (line, bar, area) automatically render a `Brush` scrubber — no flag needed. Charts MAY include `referenceLines` (array of `{axis, value, label, color, dashed}`) to mark thresholds, averages, regime changes, or key dates.
- **Dual Y-Axis:** Handled automatically by the frontend. If the largest series value range exceeds the smallest by 10x or more, the component splits axes — highest-range series on the left, the rest on the right. The backend does not need to specify this.

## 4. Phase 4: Report Synthesis
- **Goal:** Assemble the final research report with narrative and chart markers.
- **Agent:** `technical-writer`
- **Process:**
  - Reads `charts.json` from disk.
  - Generates a substantive Markdown report (>400 words).
  - Places `<!-- CHART:id -->` markers after relevant paragraphs.
- **Access Model:** Direct backend filesystem and shell tools are blocked; artifact access happens through the report tools.
- **Output:** `backend/outputs/{job_id}/report.json` containing title, summary, and markdown.

## 5. Phase 5: Quality Assurance
- **Goal:** Final review for formatting, data integrity, and compliance.
- **Agent:** `quality-analyst`
- **Criteria:**
  - Validates Markdown structure.
  - Ensures no predictive/forbidden language (e.g., "will increase").
  - Verifies mandatory disclaimers are present.
  - Checks that all chart markers have corresponding data in `charts.json`.
- **Access Model:** Direct backend filesystem and shell tools are blocked; review proceeds through validation tools only.
- **Transitions:**
  - If **Approved:** Workflow completes.
  - If **Rejected:** Returns specific feedback to the Orchestrator for rework (usually back to `technical-writer` or `quant-developer`).

## 6. Global Invariants
- **Data Decoupling:** Raw data never crosses agent boundaries; only paths and schemas.
- **Task Delegation Contract:** Orchestrator delegates with `task(subagent_type="...", description="...")`; the description must be self-contained because subagent invocations are stateless.
- **Fallback Isolation:** The built-in `general-purpose` subagent is explicitly overridden to block filesystem and shell tools, preventing unsafe host execution during fallback delegation.
- **Path Systems:**
  - Virtual paths (`/projects/...`) for filesystem tools (`read_file`, `write_file`, `ls`). These must use forward slashes only; never mix backslashes into a virtual path.
  - Windows absolute paths (`C:\...`) for `execute` and `pandas.read_csv`.
- **Backend Scope:** The orchestrator's `LocalShellBackend` runs from the repository root with inherited environment variables so shell execution and filesystem access resolve consistently.
- **Compliance:** Every report must state "does not constitute financial advice" and "Past performance is not indicative of future results".

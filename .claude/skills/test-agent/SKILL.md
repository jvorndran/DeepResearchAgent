---
name: test-agent
description: This skill should be used when modifying agent files in backend/agents/, backend/mcp_clients/, or backend/core/ to verify the pipeline still works end-to-end. Activates when building, debugging, or changing any orchestrator, subagent, or MCP client code.
version: 1.1.0
---

# Test Agent

## When to Run

After modifying any file in `backend/agents/`, `backend/mcp_clients/`, or `backend/core/`.

Always run at minimum a Tier 1 smoke test before declaring a change complete.

## Iterative Debugging Workflow

**The core loop for fixing issues without waiting for full LLM runs every time:**

```
1. Run once (3-5 min, real API calls):
   python tests/runner.py --query "Show me Apple's (AAPL) annual revenue over the last 5 years."
   → note the job_id printed at the top

2. Replay instantly to inspect output (no API calls, <1s):
   python tests/runner.py --replay test-<job_id>

3. Edit runner.py or agent files

4. Replay again to verify formatting changes:
   python tests/runner.py --replay test-<job_id>

5. When satisfied, run a fresh real test to verify agent fixes:
   python tests/runner.py --query "..."
```

**Key insight:** `--replay` re-renders a saved `events.jsonl` through the current `format_event()`
logic instantly. Use it to iterate on output formatting without burning API credits or waiting minutes.

## How to Run

From the `backend/` directory:

```bash
# Tier 1 smoke test — single query, full streaming output
python tests/runner.py --query "Show me Apple's (AAPL) annual revenue over the last 5 years."

# Replay a previous run instantly (no API calls) — primary debugging tool
python tests/runner.py --replay test-<job_id>

# Run all Tier 1 queries sequentially
python tests/runner.py --tier 1

# Non-streaming fallback (less noisy, but hides intermediate events)
python tests/runner.py --query "..." --no-stream

# Run all predefined ambiguous queries with LLM judge evaluation
python tests/runner.py --question-test

# Single ambiguous query — auto-uses expected question if defined
python tests/runner.py --query "Tell me about tech stocks."

# Limit clarification rounds (default: 3)
python tests/runner.py --query "..." --max-turns 2
```

Artifacts are written to `backend/outputs/{job_id}/`.

## Reading the Output

Every line follows this format:
```
 [elapsed] [LABEL]        content
```

### Labels and what they mean

| Label | Meaning |
|---|---|
| `[START]` | Turn begins (turn 1 = fresh run, turn 2+ = after clarification) |
| `══ PHASE N ... ══` | Orchestrator is delegating to a subagent |
| `[INPUT]` | Full task description sent TO a subagent (up to 400 chars) |
| `[OUTPUT]` | Result returned FROM a subagent |
| `[MESSAGE]` | Orchestrator thinking/narrating out loud |
| `[TOOL CALL]` | Any non-task tool call (write_todos, ls, execute, etc.) |
| `[TOOL RESULT]` | Result of a non-task tool call |
| `[EVENT]` | Middleware/framework events (usually ignorable) |
| `[QUESTION]` | Orchestrator asked a clarifying question |
| `[LLM JUDGE]` | Auto-evaluating the question quality |
| `[VERDICT]` | PASS or FAIL on question appropriateness |
| `[LLM ANSWER]` | Generated answer fed back to continue the pipeline |
| `[COMPLETE]` | Run finished — check status |
| `[ERROR]` | Exception caught — see message |

### Phase transitions to look for

```
 [15.1s] ══════ PHASE 2: DATA ACQUISITION → data-engineer ══════
 [15.1s] [INPUT]        task: Fetch Apple's (AAPL) annual income statement...
 [47.0s] [OUTPUT]       {"status": "success", "data_files": {...}, "schemas": {...}}

 [52.0s] ══════ PHASE 3: QUANTITATIVE ANALYSIS → quant-developer ══════
 [52.0s] [INPUT]        task: Perform quantitative analysis... Python: C:\...\python.exe
 [169s]  [OUTPUT]       Path to charts.json ... Chart IDs [...] Key findings ...

 [298s]  ══════ PHASE 4: REPORT SYNTHESIS → technical-writer ══════
 [298s]  [INPUT]        task: Assemble the final research report...
 [...]   [OUTPUT]       {"report_path": "outputs/.../report.json", "chart_count": 2, ...}

 [...]   ══════ PHASE 5: QUALITY ASSURANCE → quality-analyst ══════
 [...]   [OUTPUT]       {"status": "approved", ...}
```

## What Constitutes a Pass

A run is considered passing when ALL of the following are true:

1. `[COMPLETE]  Status: completed` appears at the end
2. `run_summary.json` → `"status": "completed"` with no `"error"` field
3. `report.json` → FOUND (non-zero bytes)
4. `charts.json` → FOUND (non-zero bytes)
5. `events.jsonl` → FOUND with ≥ 10 lines
6. No Python exception tracebacks in any `[TOOL RESULT]` line

**Question-handling pass criteria:**
- Ambiguous query (e.g. "Tell me about tech stocks") → orchestrator asked a clarifying question → `[VERDICT]  PASS`
- Fully specified query (ticker + metric + timeframe) → orchestrator did NOT ask → pass (no `[QUESTION]` line)
- Fully specified query → orchestrator asked anyway → **FAIL** (over-cautious)

## Report Quality Evaluation

After a run shows `[COMPLETE]  Status: completed`, evaluate the actual report content:

### Step 1 — Find the report path
Look for the `[REPORT PATH]` line in the runner output. It will look like:
```
 [312.4s] [REPORT PATH]  outputs/test-xxxxxxxx/report.json
```

### Step 2 — Read the report
Use the `Read` tool on the exact path printed. The file is JSON.

### Step 3 — Evaluate against all 7 quality criteria

| # | Criterion | What to check | Pass condition |
|---|---|---|---|
| 1 | **Query alignment** | Does the report directly answer what was asked? | Executive summary and markdown address the specific ticker/metric/timeframe |
| 2 | **Data completeness** | Are `data_sources` populated? Do tickers/series match the request? Are date ranges correct? | `data_sources` non-empty; tickers present; date range matches request |
| 3 | **Chart coverage** | Do all `<!-- CHART:id -->` markers in markdown have a matching entry in `report.charts`? Are titles descriptive? | Every marker has a corresponding chart entry; no chart titled "Chart 1" or similar |
| 4 | **Markdown structure** | Does the markdown have `##` section headers? Is it substantive prose? | At least 2 `##` headers; not just a list of numbers |
| 5 | **Word count sanity** | Is `metadata.word_count` > 200? | `metadata.word_count` > 200 |
| 6 | **No placeholder text** | Scan for "TODO", "INSERT", "placeholder", "N/A", empty strings in key fields | None of these strings appear in title, executive_summary, or markdown |
| 7 | **Metric coverage** | Are specific metrics from the query (e.g. revenue, P/E ratio) present in the markdown? | All requested metrics appear in the markdown body |

### Step 4 — Report findings
Rate each criterion as `PASS`, `WARN`, or `FAIL` with a one-line explanation:
```
1. Query alignment:    PASS — executive summary addresses AAPL revenue 2019–2023
2. Data completeness:  PASS — data_sources has 1 entry, ticker AAPL, 5 annual rows
3. Chart coverage:     WARN — 2 CHART markers in markdown, only 1 entry in report.charts
4. Markdown structure: PASS — 4 ## headers, substantive paragraphs
5. Word count sanity:  PASS — metadata.word_count = 487
6. No placeholders:    PASS — no TODO/INSERT/placeholder found
7. Metric coverage:    FAIL — "revenue growth %" mentioned in query but absent from markdown
```

### Step 5 — On any FAIL, identify the responsible agent
| What failed | Responsible agent | What to fix |
|---|---|---|
| Missing/wrong data, bad date range, wrong ticker | `data-engineer` | Check data fetch instructions and output schema |
| Missing charts, wrong chart IDs, no quantitative analysis | `quant-developer` | Check chart generation and charts.json output |
| Placeholder text, bad structure, missing metrics in prose | `technical-writer` | Check report assembly and markdown generation |
| Report passes but quality-analyst rejected | `quality-analyst` | Check `required_fixes` in its `[OUTPUT]` |

---

## What to Do on Failure

### Step 1 — Replay the failed run first (instant, no API calls)
```bash
python tests/runner.py --replay <job_id>
```
Read the output top-to-bottom. Look for:
- Which phase was the last `[INPUT]` before failure?
- Does the corresponding `[OUTPUT]` show an error or missing data?
- Is there a `[TOOL RESULT]` with a Python traceback?

### Step 2 — Check run_summary.json for the top-level error
```bash
cat outputs/<job_id>/run_summary.json
```

### Step 3 — Grep events.jsonl for errors
```bash
grep -i "error\|exception\|traceback" outputs/<job_id>/events.jsonl | head -20
```

### Step 4 — Fetch the LangSmith trace for subagent internals
The replay only shows orchestrator-level events. For what happened *inside* a subagent:
```bash
python ../.claude/skills/test-agent/scripts/langsmith_fetch.py --last 1

# Or last 3 runs
python ../.claude/skills/test-agent/scripts/langsmith_fetch.py --last 3
```
Open `https://smith.langchain.com` → project **macro-agent** for the visual waterfall view.

### Common failure patterns

| Symptom | Cause | Fix |
|---|---|---|
| `'str' object has no attribute 'get'` in runner | tool_calls list contains strings, not dicts | Already patched in runner.py |
| quant-developer wastes 3 calls finding Python | `python` not in PATH | Fixed: `sys.executable` embedded in system prompt |
| Data path not found by quant-developer | relative `./data/...` path | Fixed: `DATA_STORAGE_DIR` now absolute in data_engineer.py |
| `report.json` NOT FOUND, run ends at Phase 4 | run timed out before technical-writer finished | Reduce quant-developer retry waste; check Python path fix applied |
| `ModuleNotFoundError` | not running from `backend/` dir | `cd backend/` then run |
| `AuthenticationError` | API key missing | Check `backend/.env` |
| quality-analyst rejects | compliance or schema issue | Read `[OUTPUT]` from quality-analyst for `required_fixes` list |
| `KeyError: 'messages'` in format_event | LangGraph state shape changed | Update `format_event()` in `tests/runner.py` |
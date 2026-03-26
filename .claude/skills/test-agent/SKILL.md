---
name: test-agent
description: This skill should be used when modifying agent files in backend/agents/, backend/mcp_clients/, or backend/core/ to verify the pipeline still works end-to-end. Activates when building, debugging, or changing any orchestrator, subagent, or MCP client code.
version: 1.0.0
---

# Test Agent

## When to Run

After modifying any file in `backend/agents/`, `backend/mcp_clients/`, or `backend/core/`.

Always run at minimum a Tier 1 smoke test before declaring a change complete.

## How to Run

From the `backend/` directory:

```bash
# Tier 1 smoke test — single query, full streaming output
python tests/runner.py --query "Show me Apple's (AAPL) annual revenue over the last 10 years."

# Run all Tier 1 queries sequentially
python tests/runner.py --tier 1

# Non-streaming fallback (less noisy, but hides intermediate events)
python tests/runner.py --query "..." --no-stream
```

Artifacts are written to `outputs/{job_id}/` at the repo root level.

## What to Look For in Streaming Output

- **Phase transitions** are visible in `[MESSAGE]` events:
  - `orchestrator: Breaking query into phases...` → Intake
  - `[TOOL CALL] task(agent=data-engineer, ...)` → Data Acquisition
  - `[TOOL CALL] task(agent=quant-developer, ...)` → Analysis
  - `[TOOL CALL] task(agent=technical-writer, ...)` → Report Synthesis
  - `[TOOL CALL] task(agent=quality-analyst, ...)` → QA
- **Subagent delegation events** (`[TOOL CALL] task(...)`) are present for each expected phase
- **No exception tracebacks** appear in `[TOOL RESULT]` events
- Final artifact summary shows both `report.json` and `charts.json` as **FOUND**

## What Constitutes a Pass

A run is considered passing when ALL of the following are true:

1. `[COMPLETE]  Status: completed` appears at the end of the console output
2. `run_summary.json` → `"status": "completed"` with no `"error"` field
3. `report.json` → FOUND (non-zero bytes)
4. `charts.json` → FOUND (non-zero bytes)
5. `events.jsonl` → FOUND with ≥ 10 lines (meaningful event count)
6. No Python exception tracebacks visible in any `[TOOL RESULT]` line

## LangSmith Trace Inspection (Primary Debugging Tool)

LangSmith tracing is always active (`LANGSMITH_TRACING=true` in `backend/.env`). Every run sends
full traces — including all subagent internals that the streaming runner cannot surface — to
`https://smith.langchain.com` under project `macro-agent`.

### Fetch traces from the command line

A trace fetcher script lives in this skill folder. Run it from the `backend/` directory:

```bash
# Show the last run's full call tree (default)
python ../.claude/skills/test-agent/scripts/langsmith_fetch.py

# Show the last 3 runs
python ../.claude/skills/test-agent/scripts/langsmith_fetch.py --last 3

# Fetch a specific run by ID
python ../.claude/skills/test-agent/scripts/langsmith_fetch.py --run-id <run-id>

# Specify a different project
python ../.claude/skills/test-agent/scripts/langsmith_fetch.py --project macro-agent --last 1
```

The output shows the full recursive call tree: orchestrator → task() → subagent → tool calls →
results. This is the right place to look when a subagent returns empty or fails silently, since
those internal events don't appear in the streaming runner output.

### Read the trace in the UI

Open `https://smith.langchain.com` → project **macro-agent** for the visual waterfall view with
full token counts, latency per step, and error messages.

---

## What to Do on Failure

1. **Fetch the LangSmith trace** (always do this first for subagent failures):
   ```bash
   python ../.claude/skills/test-agent/scripts/langsmith_fetch.py --last 1
   ```

2. **Check `events.jsonl`** for orchestrator-level errors:
   ```bash
   grep -i "error\|exception\|traceback" outputs/<job_id>/events.jsonl | head -20
   ```

3. **Check `run_summary.json`** for the top-level error message:
   ```bash
   cat outputs/<job_id>/run_summary.json
   ```

4. **Common failure patterns and fixes:**
   - Subagent returns empty result → fetch LangSmith trace to see what the subagent called internally
   - `KeyError: 'messages'` in format_event → state update shape changed; update `format_event()` in `tests/runner.py`
   - `ModuleNotFoundError` → run from `backend/` directory, not repo root
   - `AuthenticationError` / API key errors → check `.env` file in `backend/`
   - `quality-analyst` rejects → check `backend/agents/quality_analyst.py` validation logic

5. **Increase verbosity** by adding a print of the raw event dict to `format_event()` in `runner.py` to see the full LangGraph state update.

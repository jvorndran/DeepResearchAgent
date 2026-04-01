---
name: test-e2e
description: Iteratively run E2E tests, diagnose failures using logs and traces, fix bugs in components/backend, and repeat until all 4 phases pass. Use after modifying chat page, chat panel, initial prompt, generation loading, results panel, or backend stream endpoint.
version: 2.0.0
---

# Test E2E — Iterative Flow Improvement Loop

## Purpose

This skill drives a **fix → test → diagnose → fix** loop over the app's 4-phase user flow:

```
Phase 1 (initial) → Phase 2 (chatting) → Phase 3 (generating) → Phase 4 (completed)
```

You are not just running tests. You are diagnosing failures, editing source files, and iterating until the full flow passes cleanly. Do not declare victory until all 4 phases pass and the browser console log has no `[pageerror]` lines.

---

## Phase Map & State Machine

### Phase Definitions (`frontend/app/chat/page.tsx`)

| Phase | Component Shown | Triggered By |
|-------|----------------|--------------|
| `initial` | `InitialPrompt` | App start / "New Research" button |
| `chatting` | `ChatPanel` | User submits initial query |
| `generating` | `GenerationLoading` | Backend streams subagent activity OR user clicks "Begin research" |
| `completed` | `ResultsPanel` | useChat `status === "ready"` while `phase === "generating"` |

### Transition Logic (know this before touching anything)

**1 → 2 (initial → chatting):**
- User fills `initial-prompt-textarea`, clicks `initial-prompt-submit`
- `page.tsx` sets `phase = "chatting"` immediately, then after 50ms calls `sendMessage()` (race condition — see Known Issues)

**2 → 3 (chatting → generating), two paths:**
- **Auto:** Backend stream emits an `update` chunk with `ns` containing `"tools:"` prefix → `hasSubagentActivity = true` → useEffect fires
- **Manual:** User clicks `begin-research-btn` (enabled only after ≥1 assistant message)

**3 → 4 (generating → completed):**
- `useChat` status becomes `"ready"` while `phase === "generating"` → `handleGenerationComplete()` builds report and sets `phase = "completed"`

---

## Key Files

| File | Role |
|------|------|
| `frontend/app/chat/page.tsx` | Phase state machine — ALL transitions live here |
| `frontend/components/initial-prompt.tsx` | Phase 1 UI (`initial-prompt-textarea`, `initial-prompt-submit`) |
| `frontend/components/chat-panel.tsx` | Phase 2 UI (`chat-messages`, `begin-research-btn`, `chat-input`) |
| `frontend/components/generation-loading.tsx` | Phase 3 UI (`generation-loading`) |
| `frontend/components/results-panel.tsx` | Phase 4 UI (`results-panel`) |
| `frontend/components/chat-loader.tsx` | Typing indicator (no testid) |
| `backend/main.py` | SSE stream endpoint (`POST /api/chat/stream`) |
| `backend/agents/orchestrator.py` | Yields chunks consumed by main.py |
| `frontend/e2e/research-flow.spec.ts` | The single test driving all 4 phases |
| `frontend/e2e/global-setup.ts` | Auto-spawns backend, polls `/health` |
| `frontend/playwright.config.ts` | Timeouts, browser, webServer config |

---

## The Iteration Loop

### Step 0 — Kill stale processes (always first)

```bash
taskkill /F /IM "chrome.exe" /T 2>nul; taskkill /F /IM "node.exe" /FI "WINDOWTITLE eq playwright*" 2>nul; true
```

If port 3001 or 8000 is already held by a previous run:
```bash
netstat -ano | findstr :3001
netstat -ano | findstr :8000
# Then: taskkill /F /PID <pid>
```

### Step 1 — Run headed (watch it fail)

```bash
cd frontend && npm run test:e2e:headed
```

Watch which phase the browser gets stuck on. Note the exact error message (it will name the `data-testid` that timed out).

### Step 2 — Read the logs

```bash
# Browser JS errors and console output
cat frontend/e2e/logs/browser-console.log

# Backend Python output (startup errors, tracebacks, stream events)
cat frontend/e2e/logs/backend.log
```

### Step 2b — Fetch the LangSmith trace (agentic workflow analysis)

After any run — pass or fail — fetch the LangSmith trace to see what the subagents actually did:

```bash
cd backend && python ../.claude/skills/test-agent/scripts/langsmith_fetch.py --last 1
```

This prints the full run tree: every LLM call, tool call, subagent invocation, input/output, elapsed time, and errors — including internals that are invisible from the SSE stream.

**What to look for:**

| Pattern | What it means | Where to fix |
|---------|--------------|--------------|
| Same tool called 3+ times in a row for the same purpose | Agent confused — probably a path or format error it's retrying | Fix the system prompt for that subagent |
| `[ERROR]` on a tool call | A tool rejected the agent's input | Read the `ERR:` line — it names the exact invalid argument |
| Many `[llm]` calls with no `[tool]` between them | Agent is reasoning in circles, not acting | System prompt may be too vague about the next action to take |
| `write_file` followed immediately by a failure, then `edit_file` | Agent is rewriting vs editing — wasted turn | Instruct the agent to use `edit_file` for modifications |
| `execute` with a Python traceback in `out:` | Analysis script bug — agent should self-fix | Check if the agent recovers within 3 tries |
| `[?]` status on root run | Run didn't complete or LangSmith hasn't received end event yet | Wait and re-fetch, or check for backend crash |

**Efficiency target:** A clean data-engineer + quant-developer + technical-writer run should complete in under 20 LLM turns total. Runs with 30+ turns indicate a system prompt or path confusion issue worth fixing.

```bash
# Fetch last 3 runs to compare across iterations
cd backend && python ../.claude/skills/test-agent/scripts/langsmith_fetch.py --last 3

# Fetch a specific run by ID (copy from the Run ID line in the output)
cd backend && python ../.claude/skills/test-agent/scripts/langsmith_fetch.py --run-id <id>
```

View full traces with waterfall UI:
```
https://smith.langchain.com/o/default/projects/p/macro-agent
```

### Step 2c — Check report quality (after every passing run)

After the test passes, read the report output and grade it before declaring victory:

```bash
# Find the latest job output
ls backend/outputs/

# Read the report (replace JOB_ID with the actual directory name)
cat backend/outputs/JOB_ID/report.json | python -c "import sys,json; r=json.load(sys.stdin); print('word_count:', r['metadata']['word_count']); print('chart_count:', r['metadata']['chart_count']); print('---MARKDOWN---'); print(r['markdown'][:3000])"
```

**Report quality checklist:**

| Check | Pass | Fail → Fix in |
|-------|------|---------------|
| word_count > 400 | Report has substance | `technical_writer.py` system prompt |
| chart_count ≥ 1 | Charts referenced in text | `technical_writer.py` system prompt |
| Each `## Section` has unique prose | No copy-paste repetition | `technical_writer.py` system prompt |
| Executive summary names the exact statistic (r-value, %, coefficient) | Specific finding stated | `technical_writer.py` system prompt |
| Numbers cited inline (e.g. "r = -0.89") | Evidence-backed claims | `technical_writer.py` system prompt |
| `<!-- CHART:id -->` appears mid-document, not only at bottom | Charts in context | `technical_writer.py` system prompt |
| No `[pageerror]` in browser console | No JS crash during render | `results-panel.tsx` |
| Data source correctly named (e.g. "FRED" not "FRED (FMP MCP Server)") | Accurate provenance | `technical_writer.py` system prompt |

**If report quality fails**, edit `backend/agents/technical_writer.py` — the `system_prompt` key in `TECHNICAL_WRITER_SUBAGENT`. The tool (`write_research_report`) no longer generates content; all prose must come from the LLM. Strengthen the section-by-section writing guidance and anti-pattern warnings, then re-run.

---

### Step 3 — Diagnose using the failure table below

Map the symptom to the cause and file to edit.

### Step 4 — Edit the source file

Use the Edit tool on the specific component or backend file. Do not guess — read the file first.

### Step 5 — Repeat from Step 1

Re-run headed after each fix. A single test run takes up to 10 minutes for the full pipeline. If fixing a Phase 1/2 issue, you may Ctrl+C after Phase 3 is reached.

---

## Failure Diagnosis Table

| Symptom (what timed out) | Most Likely Cause | File to Edit |
|--------------------------|-------------------|--------------|
| `initial-prompt-textarea` never visible | Next.js not started or `/chat` page crash | `playwright.config.ts` webServer config or `page.tsx` render crash |
| `initial-prompt-submit` stays disabled | Textarea validation logic | `initial-prompt.tsx` |
| `chat-messages` never visible (60s timeout) | Backend unreachable; CORS error; stream endpoint crashed | `backend/main.py` — check CORS, check `/health` responds |
| `begin-research-btn` never enabled | No assistant message received; stream parsing broken | `page.tsx` useChat onData handler; `main.py` SSE format |
| `generation-loading` never appears (120s) | `hasSubagentActivity` never set true; `"tools:"` prefix not in ns | `page.tsx` lines 69-70; `orchestrator.py` ns format |
| `results-panel` never appears (10 min) | Backend pipeline hung or crashed mid-run | `backend/agents/orchestrator.py`; check backend.log traceback |
| `results-panel` is empty | Report arrived but renderer returned nothing | `components/results-panel.tsx`; report JSON shape mismatch |
| `[pageerror]` in browser-console.log | JS exception in browser | Read the error message — note the component and line number |
| Backend spawn fails (globalSetup error) | Python not in PATH; missing dependency; `main.py` import error | Run `cd backend && python main.py` manually to see the error |

---

## Known Issues (read before fixing anything)

These are pre-existing bugs in the codebase. If you encounter them, fix the root cause — do not work around them.

### CRITICAL

**Race condition — Phase 1→2 transition** (`page.tsx` ~line 126)
- A 50ms `setTimeout` delays `sendMessage()` after `setPhase("chatting")`
- Root cause: React state batching; ChatPanel may not be mounted when sendMessage fires
- Fix direction: Use a `useEffect` watching `phase === "chatting"` to trigger sendMessage, not a setTimeout

**Stream text arrives before phase transition** (`page.tsx` ~line 69 + `main.py` ~line 143)
- Backend can send `text-delta` events before any `"tools:"` namespace update
- First text chunk renders in chatting phase, but may belong to the generating phase narrative
- Fix direction: Distinguish clarifying-question text from pipeline-narration text in the stream protocol

**Message content format mismatch** (`page.tsx` ~line 98 vs `main.py` ~line 120)
- Backend sends mixed formats: sometimes `token.content` as string, sometimes list of content blocks
- Frontend expects `m.parts` array with `{type: 'text', text: '...'}`
- Fix direction: Normalize to a single format in `main.py` before yielding text events

**Completion double-call** (`page.tsx` ~lines 41-45, 87-92)
- `completionCalledRef` guards against double-calls but `handleGenerationComplete` is recreated when `sessionTitle` changes
- Fix direction: Move `completionCalledRef` check inside a stable ref callback, not inside a useCallback with dependencies

**Quant-developer Windows path confusion** (`quantitative_developer.py` system prompt)
- System prompt injected `OUTPUT_BASE_DIR` (a Windows path like `C:\...\outputs`) into examples for `write_file`/`read_file`/`ls`
- `LocalShellBackend` rejects Windows absolute paths for file tools — only virtual paths (`/projects/...`) are accepted
- `execute` is the exception — it runs a subprocess and DOES need the Windows path
- Result: agent burned 10+ extra LLM turns per run trying different path formats until it discovered virtual paths
- Fix direction: compute `OUTPUT_BASE_VIRTUAL` (strip drive letter) and use it in file-tool examples in the prompt; keep Windows path only for the `execute` command example

### MODERATE

**Manual "Begin research" sends redundant message** (`page.tsx` ~line 148)
- Sends hardcoded `"I am ready. Please begin the research."` string
- If orchestrator changes its trigger phrase detection, this silently breaks
- Fix direction: Use a dedicated signal (e.g., a special `job_action` field in the request body) instead of a magic string

**Chat auto-scroll depends on Radix internals** (`chat-panel.tsx` ~line 106)
- Uses `querySelector('[data-radix-scroll-area-viewport]')` — breaks if Radix changes its DOM structure
- Fix direction: Use a ref on a wrapper div and call `scrollIntoView` on the last message element

---

## What Constitutes a Pass

All of the following must be true:

1. `initial-prompt-textarea` was found and filled
2. `initial-prompt-submit` was clicked without error
3. `chat-messages` became visible within 60s (backend responded)
4. Either `generation-loading` appeared automatically OR `begin-research-btn` became enabled and was clicked
5. `generation-loading` appeared (pipeline started)
6. `results-panel` appeared and is not empty (pipeline completed)
7. No `[pageerror]` lines in `e2e/logs/browser-console.log`
8. `backend.log` contains no Python traceback

---

## Run Commands Reference

```bash
# Standard headless run (auto-starts backend + Next.js)
cd frontend && npm run test:e2e

# Headed run — watch Chromium drive all 4 phases (best for debugging)
cd frontend && npm run test:e2e:headed

# Interactive UI mode — timeline, step-by-step replay
cd frontend && npx playwright test --ui

# Show last HTML report
cd frontend && npx playwright show-report

# Show trace from last failure
cd frontend && npx playwright show-trace playwright-report/trace.zip
```

**One run at a time.** Playwright does not support concurrent runs against the same port. Always wait for the current run to finish (or Ctrl+C) before starting another.

---

## Log Files

| File | Contents |
|------|----------|
| `frontend/e2e/logs/backend.log` | FastAPI stdout/stderr — check for Python tracebacks |
| `frontend/e2e/logs/browser-console.log` | Browser console events — check for `[pageerror]` |
| `frontend/e2e/logs/backend.pid` | PID of spawned backend (deleted on teardown) |
| `frontend/playwright-report/index.html` | Full HTML report with traces, screenshots, video |

---

## globalSetup / globalTeardown Behaviour

- **globalSetup** probes `http://localhost:8000/health` first
  - Already running → logs "reusing existing", skips spawn
  - Not running → spawns `python main.py` from `../../backend`, pipes to `backend.log`, polls `/health` for up to 60s
- **globalTeardown** reads the PID file, kills the process if it was spawned by setup

---

## First-Time Setup Checklist

1. `cd frontend && npm install`
2. `npx playwright install chromium`
3. Verify backend runs: `cd backend && python main.py` (should print FastAPI startup)
4. Run headed: `cd frontend && npm run test:e2e:headed`
5. After pass, confirm:
   - `e2e/logs/backend.log` has FastAPI logs
   - `e2e/logs/browser-console.log` has no `[pageerror]`
   - `playwright-report/index.html` is green

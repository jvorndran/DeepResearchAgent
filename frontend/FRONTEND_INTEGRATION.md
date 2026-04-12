# Frontend ↔ Backend Streaming Integration

This document describes the complete streaming protocol between the Next.js frontend and the FastAPI backend, including all SSE event types and the two-page architecture.

---

## Architecture Overview

```
Home Page  ──POST /api/chat/stream──►  FastAPI  ──astream()──►  LangGraph Orchestrator
           ◄──SSE events────────────                              │
                                                                  ├─ emit_chat_message()
                                                                  └─ (stops — waits for next user message)

Chat Page  ──POST /api/chat/stream (begin message)──►  FastAPI  ──astream()──►  Orchestrator resumes
           ◄──SSE events (pipeline progress)──────────                           └─ task() ──► subagents
                                                                                      ├─ data-engineer
                                                                                      ├─ quant-developer
                                                                                      ├─ technical-writer
                                                                                      └─ quality-analyst
```

There are two pages. The **home page** (`/`) handles the intake conversation. The **chat page** (`/chat/[job_id]`) shows the live pipeline run.

---

## The SSE Stream: `/api/chat/stream`

### Request body

```ts
{
  messages: { role: "user" | "assistant", content: string }[],
  job_id?: string,          // omit on first request; backend generates one
  stream_telemetry?: boolean  // false = home page mode (suppress raw model tokens)
}
```

### Response

`text/event-stream` — each line: `data: <JSON>\n\n`, terminated by `data: [DONE]\n\n`.

---

## SSE Event Reference

### `start`
Emitted at the very beginning of every stream.

```json
{ "type": "start", "job_id": "job_abc123" }
```

- The frontend persists `job_id` and sends it on every subsequent request so all turns share the same LangGraph thread (checkpoint).

---

### `text`
Raw model token from the orchestrator (streamed when `stream_telemetry: true`).

```json
{ "type": "text", "delta": "I'll begin by..." }
```

- Only emitted on the **chat page** (`stream_telemetry` defaults to `true`).
- On the **home page** (`stream_telemetry: false`) raw tokens are suppressed; use `user_message` instead.

---

### `user_message`
The content of an `emit_chat_message` tool call — the only text the user should see in the intake chat UI.

```json
{ "type": "user_message", "markdown": "I need a few details before I begin...\n\n- What ticker?" }
```

- On the **home page**, this replaces `orchestratorText` entirely (one message per turn).
- On the **chat page**, it is appended to `orchestratorText` separated by `---`.
- The orchestrator calls `emit_chat_message` exactly once per user-visible turn.
- When this message contains the phrase **"Commence Deep Research"**, the frontend shows the Commence Deep Research button.

---

### `agent_start`
A subagent has started running inside a `task()` call.

```json
{ "type": "agent_start", "agent": "data-engineer" }
```

Possible agent values: `data-engineer`, `quant-developer`, `technical-writer`, `quality-analyst`.

---

### `agent_end`
A subagent has finished.

```json
{ "type": "agent_end", "agent": "data-engineer" }
```

---

### `tool_call`
A tool is being called by a subagent (or the orchestrator).

```json
{ "type": "tool_call", "agent": "data-engineer", "tool": "fred_get_series", "args": { "series_id": "GDPC1" } }
```

---

### `tool_result`
A tool call completed.

```json
{ "type": "tool_result", "agent": "data-engineer", "tool": "fred_get_series", "summary": "..." }
```

- `summary` is truncated to 300 characters.

---

### `finish`
The orchestrator's full run is complete.

```json
{ "type": "finish", "report_ready": true }
```

- `report_ready: true` → frontend fetches `GET /api/reports/{job_id}` to get the final report.
- `report_ready: false` → the run ended without a report (intake-only conversational turn).

---

### `error`

```json
{ "type": "error", "errorText": "MCP timeout: ..." }
```

---

## Two-Page Flow in Detail

### Phase 1: Intake (Home Page)

```
User types query
  → POST /api/chat/stream  { messages: [...], stream_telemetry: false }
  ← SSE: start  (frontend stores job_id)
  ← SSE: user_message  (orchestrator asks clarifying questions)
  ← SSE: finish  { report_ready: false }
  ← data: [DONE]

Frontend: shows assistant message, user answers question
  → POST /api/chat/stream  { messages: [..., answer], job_id: "job_abc123", stream_telemetry: false }
  ← SSE: user_message  ("I have what I need. Click Commence Deep Research...")
  ← SSE: finish  { report_ready: false }
  ← data: [DONE]

Frontend: detects "Commence Deep Research" in user_message → shows button
```

The orchestrator is instructed to **stop after `emit_chat_message`** on the ready turn — it does not call `task()`. This keeps the home page stream lightweight (no pipeline steps fire yet).

### Phase 2: Commence → Navigate to Chat Page

When the user clicks **Commence Deep Research**:

```ts
// page.tsx
sessionStorage.setItem(
  "pending_messages",
  JSON.stringify([{ role: "user", content: "Please begin the research now with the parameters discussed." }])
);
router.push(`/chat/${sessionJobId}`);
```

The chat page reads `pending_messages` from `sessionStorage` and immediately POSTs that single message to the same LangGraph thread.

### Phase 3: Pipeline Run (Chat Page)

```
Chat Page mounts, reads pending_messages from sessionStorage
  → POST /api/chat/stream  { messages: [{ role: "user", content: "Please begin the research now..." }], job_id: "job_abc123" }
  ← SSE: start
  ← SSE: agent_start  { agent: "data-engineer" }
  ← SSE: tool_call, tool_result  (repeated for each tool)
  ← SSE: agent_end  { agent: "data-engineer" }
  ← SSE: agent_start  { agent: "quant-developer" }
  ...
  ← SSE: finish  { report_ready: true }
  ← data: [DONE]

Frontend: fetches GET /api/reports/{job_id} → renders report
```

The orchestrator receives the "begin" message, sees intake is complete, and calls `task()` to delegate to the data-engineer subagent. No interrupts, no resume payloads.

### Phase 4: Refresh / Leave and Return

If the user navigates to `/chat/{job_id}` with no `pending_messages` in sessionStorage (e.g. after a page refresh), the hook detects `messages.length === 0` and enters **polling mode**:

```
GET /api/reports/{job_id}
→ 202  while report.json not yet written  (retry after 5s)
→ 404  if job_id is unknown
→ 200  { ...ResearchReport }             (renders report)
```

---

## `stream_telemetry` Flag

Controls what the home page sees vs. the chat page:

| Flag | Raw `text` tokens | `user_message` source |
|------|------------------|-----------------------|
| `true` (chat page default) | Emitted | From `emit_chat_message` tool call in updates stream, appended to orchestrator log |
| `false` (home page) | Suppressed | From `emit_chat_message` tool call; **replaces** orchestrator text each turn |

On the home page, the frontend passes `stream_telemetry: false` so only the structured `user_message` events reach the UI — no raw model tokens. This prevents half-rendered intermediate text from appearing in the intake chat.

---

## Thread Identity and Checkpointing

Every request that shares the same `job_id` maps to the same LangGraph thread (`configurable: { thread_id: job_id }`). The orchestrator uses `MemorySaver` as its checkpointer.

- The `job_id` is generated by the backend on the first `start` event.
- The frontend stores it in React state (`sessionJobId`) and sends it on every subsequent request.
- The chat page sends one new "begin" message to the existing thread; `add_messages` appends it to the checkpoint.
- The LangGraph thread persists as long as the server process is running (in-memory only).

---

## Report Fetching

When `finish` arrives with `report_ready: true`, the frontend fetches:

```
GET /api/reports/{job_id}
→ 202  while report.json not yet written
→ 404  if job_id is unknown
→ 200  { ...ResearchReport }
```

The report is written to `backend/outputs/{job_id}/report.json` by the quality-analyst subagent.

# Frontend Integration Guide — Deep Research Agent

## Overview

The backend exposes a single streaming endpoint. The frontend must:
1. POST a chat request and consume a Server-Sent Event (SSE) stream
2. Show live progress (orchestrator narration + pipeline tool activity)
3. After the stream ends, fetch and render the final `report.json`

---

## 1. Sending a Request

```
POST http://localhost:8000/api/chat/stream
Content-Type: application/json
```

**Request body:**
```json
{
  "messages": [
    { "role": "user", "content": "Analyze the historical relationship between US GDP and unemployment" }
  ],
  "job_id": "my_job_123"  // optional — if omitted, backend generates one
}
```

> The `job_id` is critical: it is the directory name under `outputs/` where `report.json` will be saved.
> If you don't provide one, extract it from the `start` event (see below).

---

## 2. SSE Stream Format

The response is `Content-Type: text/event-stream`. Each line is:
```
data: <JSON>\n\n
```
The stream terminates with `data: [DONE]\n\n`.

---

## 3. Event Types

### `start`
```json
{ "type": "start", "job_id": "my_job_123" }
```
Store `job_id` — used as fallback key if you need to call `GET /api/reports/{job_id}`.

---

### `text`
A streamed token from the orchestrator's narration (reasoning, phase announcements).
```json
{ "type": "text", "delta": "I will begin by delegating to the data-engineer..." }
```
Append `delta` to the orchestrator text bubble.

---

### `agent_start`
A subagent has been invoked.
```json
{ "type": "agent_start", "agent": "data-engineer" }
```
Add a new active step in the pipeline progress UI. Possible values: `data-engineer`, `quant-developer`, `technical-writer`, `quality-analyst`.

---

### `tool_call`
A tool is being invoked inside the active subagent.
```json
{ "type": "tool_call", "agent": "data-engineer", "tool": "fetch_fred_series", "args": { "series_id": "GDPC1" } }
```
Show as a child item under the current agent step. Suggested label mapping:

| `tool` | Display label |
|---|---|
| `fetch_fred_series` | Fetching FRED series |
| `fetch_fmp_*` | Fetching market data |
| `execute` / `execute_python` | Running analysis |
| `write_file` | Writing file |
| `plan_report_structure` | Planning report |
| `write_research_report` | Writing report |
| `validate_report_format` | Validating report |
| `check_compliance` | Checking compliance |
| `verify_chart_references` | Verifying charts |
| `patch_report` | Patching report |
| `approve_report` | Approving |
| `reject_report` | QA rejected — retrying |

---

### `tool_result`
The tool returned a result.
```json
{ "type": "tool_result", "agent": "data-engineer", "tool": "fetch_fred_series", "summary": "87 rows..." }
```
Optionally show `summary` in a collapsed detail panel under the tool call.

---

### `agent_end`
The subagent finished.
```json
{ "type": "agent_end", "agent": "data-engineer" }
```
Mark the agent step as complete (checkmark).

---

### `finish`
```json
{ "type": "finish", "report_ready": true }
```
Stream is fully done. `report_ready: true` means `report.json` was successfully written and can be fetched. `report_ready: false` means the pipeline ended without producing a report (e.g. QA rejected after 3 retries). **This is the trigger to call `GET /api/reports/{job_id}`.**

---

### `error`
```json
{ "type": "error", "errorText": "MCP timeout: ..." }
```
Show an error state.

---

## 4. Fetching the Final Report

### When to fetch

The `finish` event is the trigger. Only fetch when `report_ready: true`:

```typescript
case "finish":
  if (event.report_ready) {
    const report = await fetchReport(jobId);
    setReport(report);
  } else {
    setStatus("failed"); // pipeline ended without a report
  }
  break;
```

### Knowing when tool calling is done

Tool calling is done when you receive `agent_end` for `quality-analyst` — that is always the last subagent. The sequence at the end of a successful run looks like:

```
tool_call   { agent: "quality-analyst", tool: "approve_report" }
tool_result { agent: "quality-analyst", tool: "approve_report", summary: '{"status":"approved"...}' }
agent_end   { agent: "quality-analyst" }   ← all tool work complete
finish      { report_ready: true }          ← safe to fetch
```

If QA rejects and the technical writer retries, you'll see additional `agent_start`/`agent_end` cycles for `technical-writer` and `quality-analyst` before `finish`. The pipeline is always done when `finish` arrives — do not fetch before it.

### The endpoint

```
GET http://localhost:8000/api/reports/{job_id}
```

| Status | Meaning |
|---|---|
| `200` | Report is ready — body is the full `ResearchReport` JSON |
| `202` | Job is still running (outputs dir exists but report not written yet) |
| `404` | Unknown `job_id` |
| `500` | Report file exists but could not be parsed |

> The `202` case should not occur if you always wait for the `finish` event before fetching, but handle it defensively.

---

## 5. The `report.json` Schema

```typescript
interface ResearchReport {
  schema_version: 1;
  job_id: string;
  created_at: string;            // ISO 8601
  query: string;                 // Original user query
  title: string;                 // Report title
  executive_summary: string;     // Plain text summary
  markdown: string;              // Full report body — see Section 6
  charts: Record<string, ChartDef>;  // keyed by snake_case chart ID
  data_sources: DataSource[];
  metadata: {
    analysis_type: string;
    chart_count: number;
    word_count: number;
  };
}

interface DataSource {
  provider: string;              // e.g. "FRED (Federal Reserve Economic Data)"
  description: string;
  tickers?: string[];
  series_ids?: string[];
  date_range?: { start: string; end: string };
  row_count?: number;
}
```

### Chart types

All charts have `id`, `type`, `title`, `description`, and `data`.

#### Line / Bar / Area (`AxisChartDef`)
```typescript
{
  id: string;
  type: "line" | "bar" | "area";
  title: string;
  description: string;
  xAxisKey: string;              // key in each data row for the x-axis
  series: Array<{
    dataKey: string;             // key in each data row for this series value
    label: string;
    color: string;               // hex color, e.g. "#3b82f6"
  }>;
  data: Array<Record<string, number | string>>;
}
```

**Example data row:** `{ "date": "2008-03-31", "gdp_growth_pct": -0.427, "unrate": 5.0 }`

#### Scatter (`ScatterChartDef`)
```typescript
{
  id: string;
  type: "scatter";
  title: string;
  description: string;
  xKey: string;                  // key for x values
  yKey: string;                  // key for y values
  xLabel: string;
  yLabel: string;
  color: string;
  data: Array<Record<string, number>>;
}
```

#### Pie (`PieChartDef`)
```typescript
{
  id: string;
  type: "pie";
  title: string;
  description: string;
  data: Array<{ name: string; value: number; color?: string }>;
}
```

---

## 6. Rendering the Markdown Report

The `markdown` field is standard Markdown with **inline chart markers**:
```
<!-- CHART:gdp_unemployment_trends -->
```

Each marker must be replaced with the rendered chart component. The chart ID after `CHART:` is a key in `report.charts`.

### Rendering algorithm

1. Split `markdown` on `<!-- CHART:<id> -->` regex: `/<!--\s*CHART:(\S+?)\s*-->/g`
2. For each split segment: render as Markdown (using a library like `react-markdown`)
3. For each marker match: look up `report.charts[id]` and render the appropriate chart component based on `chart.type`

### Suggested chart library
Use **Recharts** — all chart definitions are designed for it:
- `AxisChartDef` → `<LineChart>` / `<BarChart>` / `<AreaChart>` with `<XAxis dataKey={xAxisKey}>` and multiple `<Line dataKey={series[i].dataKey}>`
- `ScatterChartDef` → `<ScatterChart>` with `<Scatter data={data}>` and `<XAxis dataKey={xKey}>`
- `PieChartDef` → `<PieChart>` with `<Pie data={data} dataKey="value" nameKey="name">`

---

## 7. Suggested UI State Machine

```
IDLE
  → user submits query
  → POST /api/chat/stream

STREAMING
  start        → store job_id
  text         → append to orchestrator narration bubble
  agent_start  → add pipeline step (spinner)
  tool_call    → add tool row under step (pending)
  tool_result  → mark tool row done, show summary
  agent_end    → mark pipeline step done (checkmark)

  finish (report_ready: true)  → GET /api/reports/{job_id} → REPORT_READY
  finish (report_ready: false) → FAILED
  error                        → ERROR

REPORT_READY
  → render: title, executive_summary, markdown+charts, data_sources footer

FAILED
  → show "Pipeline ended without a report" + orchestrator text for details

ERROR
  → show errorText
```

---

## 8. Complete Example: Parsing the Stream

```typescript
async function runResearch(messages: Message[]) {
  const response = await fetch("http://localhost:8000/api/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages }),
  });

  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let jobId = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const lines = buffer.split("\n");
    buffer = lines.pop()!; // keep last incomplete line

    for (const line of lines) {
      if (!line.startsWith("data: ")) continue;
      const raw = line.slice(6).trim();
      if (raw === "[DONE]") break;

      const event = JSON.parse(raw);

      switch (event.type) {
        case "start":
          jobId = event.job_id;
          break;
        case "text":
          appendOrchestratorText(event.delta);
          break;
        case "agent_start":
          addPipelineStep({ agent: event.agent, status: "running" });
          break;
        case "tool_call":
          addToolToStep(event.agent, { tool: event.tool, args: event.args, status: "running" });
          break;
        case "tool_result":
          updateToolInStep(event.agent, event.tool, { status: "done", summary: event.summary });
          break;
        case "agent_end":
          markStepDone(event.agent);
          break;
        case "finish":
          if (event.report_ready) {
            const report = await fetchReport(jobId);
            setReport(report);          // → REPORT_READY
          } else {
            setStatus("failed");        // → FAILED
          }
          break;
        case "error":
          setError(event.errorText);    // → ERROR
          break;
      }
    }
  }
}

async function fetchReport(jobId: string) {
  const res = await fetch(`http://localhost:8000/api/reports/${jobId}`);
  if (!res.ok) throw new Error(`Report fetch failed: ${res.status}`);
  return res.json(); // ResearchReport
}
```

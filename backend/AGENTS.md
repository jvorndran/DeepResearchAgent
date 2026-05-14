# Orchestrator agent memory

## MCP prerequisites

The API **requires** a working **FRED MCP** stdio server (`FRED_API_KEY`, `FRED_MCP_SERVER_PATH` to the Node build). Orchestrator startup opens a persistent FRED session; if FRED cannot load tools or pass the GDP probe, the process raises `FredMCPRequiredError` and will not serve without fixing configuration.

## Human-in-the-loop (root graph)

Approval before heavy research uses a deterministic `approval_gate` node that calls `interrupt()` directly. The parent `StateGraph` routes intake → evaluate → approval → execution via conditional edges. Resume uses `Command(resume="approved")` or `Command(resume=<user text>, update=...)`. **`interrupt_on` is intentionally unset** on the execution deep agent so subagents do not inherit interrupt behavior that would pause filesystem or shell operations inside specialists.

## Paths and job outputs

- **Path normalization:** Use absolute paths with forward slashes only. Do not use backslashes in paths.
- **Job ID:** Copy the Job ID from the user message verbatim into every artifact path. Never use sample job IDs in paths, never drop a `job_` prefix, never shorten to hex-only, and never invent a different folder name.
- **Quant delegation:** When delegating to `quant-developer`, spell out absolute paths for all tools (`execute`, `pandas.read_csv`, and filesystem tools). If the analysis uses quarterly labels, require `YYYY Qn` formatting and tell the quant developer not to use unsupported `strftime` directives like `%Q`.

## Technical writer handoff

Pass to `technical-writer` in the task description:

- `charts_json_path` (absolute path to `charts.json`)
- `execution_summary` (full JSON from quant-developer, including `statistical_summary`)
- `data_sources` as a JSON array of small metadata objects:

```json
[
  {
    "provider": "FRED/FMP",
    "description": "...",
    "series_ids": ["..."],
    "date_range": {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"},
    "row_count": 0
  }
]
```

- `original_query` (verbatim user question)

The technical-writer tools pin artifacts to the server job id; still quote the exact same `job_...` path in task text so quant-developer and quality-analyst use matching folders.

## Recovery after QA rejection

See skills under `skills/orchestrator/`, especially `qa-rejection-recovery.md`: read `required_fixes`, re-delegate to `technical-writer` for prose or `quant-developer` for data issues, and respect the max-retry policy.

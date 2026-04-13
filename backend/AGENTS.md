# Deep Research Agent — Cross-Agent Invariants

This file is loaded into every agent's system prompt. Rules here apply to ALL agents in the pipeline.

---

## 1. Windows Path Rules

This platform runs on **Windows**. There are TWO path systems in use:

| Context | Format | Example |
|---------|--------|---------|
| `write_file`, `read_file`, `ls`, `glob`, `grep` (virtual filesystem tools) | Virtual path — strip drive letter, use forward slashes | `/projects/DeepResearchAgent/backend/outputs/abc123/report.json` |
| `execute` (subprocess) | Windows absolute path | `C:\projects\DeepResearchAgent\backend\outputs\abc123\analysis.py` |
| `pandas.read_csv()` inside scripts | Windows absolute path | `C:\projects\DeepResearchAgent\backend\data\abc123\AAPL_income.csv` |

**Conversion rule**: `C:\foo\bar` → `/foo/bar` (strip drive letter + colon, convert backslashes)

---

## 2. Data Decoupling Law

**Raw data arrays NEVER cross agent boundaries.** This is the single most important rule.

- The **data-engineer** saves raw data to CSV and returns only: storage paths, row counts, column names, sample rows (2 max).
- The **quant-developer** reads CSVs directly from disk using Windows paths in `pandas.read_csv()`.
- The **orchestrator** stores only schemas and file paths in its state — never data rows.
- Tool results exceeding ~500 tokens should be saved to disk; return the path.

---

## 3. Chart Format Standard

Charts are saved to `outputs/{job_id}/charts.json` as a **dict keyed by snake_case chart ID**.

```json
{
  "aapl_revenue": {
    "id": "aapl_revenue",
    "type": "line",
    "title": "Apple Annual Revenue",
    "description": "Revenue trend 2020-2024",
    "xAxisKey": "year",
    "series": [{"dataKey": "revenue", "label": "Revenue ($M)", "color": "#3b82f6"}],
    "data": [{"year": "2020", "revenue": 274515}]
  }
}
```

Valid chart types: `"line"` | `"bar"` | `"area"` | `"scatter"` | `"pie"`

Charts are referenced in markdown with inline markers: `<!-- CHART:aapl_revenue -->`

Markers must be placed **after the paragraph that references the chart**, never clustered at the bottom.

---

## 4. Financial Compliance

Every final report **must** contain both of:
- `"does not constitute financial advice"`
- `"Past performance is not indicative of future results"`

**Forbidden language** (will fail QA): "will increase", "will decrease", "should buy", "should sell", "expect the price to", "predict", "forecast" (when applied to future prices or returns).

Use instead: "historically", "as of the data period", "the trend has shown", "based on historical analysis".

---

## 5. Job Artifact Locations

All job outputs are organized under `backend/` using `{job_id}` as the namespace:

| Artifact | Windows Path | Virtual Path |
|----------|-------------|--------------|
| Raw data CSVs | `C:\...\backend\data\{job_id}\*.csv` | `/projects/.../backend/data/{job_id}/*.csv` |
| Analysis script | `C:\...\backend\outputs\{job_id}\code\analysis.py` | `/projects/.../backend/outputs/{job_id}/code/analysis.py` |
| Charts JSON | `C:\...\backend\outputs\{job_id}\charts.json` | `/projects/.../backend/outputs/{job_id}/charts.json` |
| Report JSON | `C:\...\backend\outputs\{job_id}\report.json` | `/projects/.../backend/outputs/{job_id}/report.json` |

The `job_id` is always available in the runtime context and is automatically injected into tools that need it.

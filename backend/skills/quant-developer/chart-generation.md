---
name: chart-generation
description: Chart schema templates for AxisChartDef, ScatterChartDef, and PieChartDef — used by quant-developer to produce charts.json
triggers:
  - chart
  - charts.json
  - AxisChartDef
  - ScatterChartDef
  - PieChartDef
  - visualization
  - Recharts
  - chart generation
  - line chart
  - bar chart
  - scatter chart
  - pie chart
---

# Chart Generation Schema

Charts are saved to `outputs/{job_id}/charts.json` as a **dict keyed by snake_case chart ID**. All fields are at the top level — never nest under the type name.

## Color Palette (use in order)
`["#3b82f6", "#f59e0b", "#10b981", "#ef4444", "#8b5cf6"]`

---

## Variant A — Axis Charts (`type: "line" | "bar" | "area"`)

Use for: time series trends, bar comparisons, area charts.

```python
{
  "aapl_revenue": {
    "id": "aapl_revenue",           # SAME as dict key
    "type": "line",                  # "line" | "bar" | "area"
    "title": "Apple Annual Revenue (2020–2024)",
    "description": "Revenue grew from $274B to $391B over 5 years.",
    "xAxisKey": "year",              # Column name for x-axis
    "series": [
      {"dataKey": "revenue", "label": "Revenue ($M)", "color": "#3b82f6"}
    ],
    "data": [
      {"year": "2020", "revenue": 274515},
      {"year": "2021", "revenue": 365817}
    ]
  }
}
```

---

## Variant B — Scatter (`type: "scatter"`)

Use for: correlation analysis, two-variable relationships. No `xAxisKey` or `series` fields.

```python
{
  "correlation_scatter": {
    "id": "correlation_scatter",
    "type": "scatter",
    "title": "CapEx vs Wafer Volume",
    "description": "Each point is one quarter. Pearson r=0.82, p<0.001",
    "xKey": "tsmc_capex",
    "yKey": "wafer_volume",
    "xLabel": "TSMC CapEx (USD thousands)",
    "yLabel": "Wafer Volume (k units)",
    "color": "#10b981",
    "data": [{"tsmc_capex": 3100000, "wafer_volume": 8200}]
  }
}
```

---

## Variant C — Pie (`type: "pie"`)

Use for: breakdowns, proportions, segment shares. Self-describing `{name, value, color}` slices.

```python
{
  "sector_pie": {
    "id": "sector_pie",
    "type": "pie",
    "title": "Revenue by Segment",
    "description": "FY2024 revenue breakdown",
    "data": [
      {"name": "Logic", "value": 45, "color": "#3b82f6"},
      {"name": "Memory", "value": 30, "color": "#f59e0b"}
    ]
  }
}
```

---

## Mandatory Validation Block

Include this in every `analysis.py` before writing `charts.json`:

```python
REQUIRED_BASE_KEYS = {"id", "type", "title", "description", "data"}
AXIS_REQUIRED_KEYS = {"xAxisKey", "series"}   # camelCase — NOT x_axis_key or y_axis_label
for chart_id, chart_def in charts.items():
    # Inject id from dict key if accidentally omitted
    if "id" not in chart_def:
        chart_def["id"] = chart_id
    missing = REQUIRED_BASE_KEYS - set(chart_def.keys())
    if missing:
        raise ValueError(f"Chart '{chart_id}' missing required fields: {missing}")
    if chart_def.get("type") in ("line", "bar", "area"):
        axis_missing = AXIS_REQUIRED_KEYS - set(chart_def.keys())
        if axis_missing:
            raise ValueError(f"Axis chart '{chart_id}' missing camelCase fields: {axis_missing}. "
                             f"Use xAxisKey (NOT x_axis_key) and series list (NOT y_axis_label)")
    if not isinstance(chart_def.get("id"), str) or not isinstance(chart_def.get("type"), str):
        raise ValueError(f"Chart '{chart_id}': 'id' and 'type' must be strings at top level")
print("charts.json validation passed")
```

## Critical Anti-Pattern

❌ WRONG — nested under type name:
```json
{"aapl_revenue": {"type": "line", "line": {"id": "aapl_revenue", "title": "..."}}}
```

✅ CORRECT — all fields at TOP LEVEL:
```json
{"aapl_revenue": {"id": "aapl_revenue", "type": "line", "title": "...", ...}}
```

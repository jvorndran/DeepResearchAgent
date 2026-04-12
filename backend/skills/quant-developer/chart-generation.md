---
name: chart-generation
description: Concise rules for Recharts JSON generation
triggers: [chart, Recharts, AxisChartDef, ScatterChartDef, PieChartDef, JSON]
---

# Chart Rules

1. **Format:** Dict keyed by `snake_case` ID.
2. **Path:** `{OUTPUT_BASE_DIR}/{job_id}/charts.json`.
3. **Palette:** `["#3b82f6", "#f59e0b", "#10b981", "#ef4444", "#8b5cf6"]`.
4. **Period labels:** For quarterly data, format labels as `YYYY Qn`. Never use unsupported directives like `%Q`.

## AxisChart (Line, Bar, Area)
```json
{
  "id": "revenue_trend",
  "type": "line",
  "title": "Revenue",
  "description": "Revenue trend over time.",
  "xAxisKey": "date",
  "data": [{"date": "2024", "value": 100}],
  "series": [{"dataKey": "value", "label": "Revenue", "color": "#3b82f6"}],
  "referenceLines": [
    {"axis": "y", "value": 80, "label": "Baseline", "color": "#888", "dashed": true},
    {"axis": "x", "value": "2023", "label": "Policy Change", "color": "#ef4444", "dashed": false}
  ]
}
```
**`referenceLines` is optional** but should be included whenever it adds analytical value — e.g., historical averages, targets, crisis dates, rate decisions, or regime changes. Each entry: `axis` (`"x"` or `"y"`), `value` (the data-domain value), `label` (short string), `color` (hex), `dashed` (bool).

## ScatterChart
```json
{
  "id": "gdp_vs_unrate",
  "type": "scatter",
  "title": "GDP vs UNRATE",
  "description": "Relationship between GDP growth and unemployment changes.",
  "xKey": "gdp_growth",
  "yKey": "unrate_change",
  "xLabel": "GDP Growth (%)",
  "yLabel": "Unemployment Change (pp)",
  "color": "#ef4444",
  "data": [{"gdp_growth": 2, "unrate_change": -0.5}]
}
```

## PieChart
```json
{
  "id": "revenue_mix",
  "type": "pie",
  "title": "Revenue Mix",
  "description": "Revenue share by segment.",
  "data": [{"name": "A", "value": 40, "color": "#3b82f6"}]
}
```

**Rule:** Use the canonical report schema only. Do not emit legacy `config`, `xAxis`, `yAxis`, `key`, or `name` fields.

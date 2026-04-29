---
name: chart-generation
description: Concise rules for Recharts JSON generation
triggers: [chart, Recharts, AxisChartDef, ScatterChartDef, PieChartDef, TreemapChartDef, JSON]
---

# Chart Rules

1. **Format:** Dict keyed by `snake_case` ID.
2. **Path:** `{OUTPUT_BASE_DIR}/{job_id}/charts.json`.
3. **Palette:** `["#3b82f6", "#f59e0b", "#10b981", "#ef4444", "#8b5cf6"]`.
4. **Period labels:** For quarterly data, format labels as `YYYY Qn`. Never use unsupported directives like `%Q`.
5. **Supported types only:** Use only `line`, `bar`, `area`, `composed`, `scatter`, or `pie`. Do not emit `radar`, `heatmap`, `table`, or other unsupported chart types. Period comparisons should be grouped `bar` or `composed` charts.
6. **Mixed FRED frequencies:** Merge monthly and quarterly FRED data on period keys, not raw timestamps. For quarterly joins, create `quarter = date.dt.to_period("Q")` in every frame, merge on `quarter`, and derive display labels with `YYYY Qn`; never merge quarter-start GDP dates directly against quarter-end resample timestamps.

## AxisChart (Line, Bar, Area, Composed)
```json
{
  "id": "revenue_trend",
  "type": "composed",
  "title": "Revenue vs Margin",
  "description": "Revenue trend over time compared to profit margin.",
  "xAxisKey": "date",
  "data": [{"date": "2024", "revenue": 100, "margin": 15}],
  "series": [
    {"dataKey": "revenue", "label": "Revenue", "color": "#3b82f6", "type": "bar", "yAxisId": "left"},
    {"dataKey": "margin", "label": "Margin (%)", "color": "#f59e0b", "type": "line", "yAxisId": "right"}
  ],
  "referenceLines": [
    {"axis": "y", "value": 80, "label": "Baseline", "color": "#888", "dashed": true},
    {"axis": "x", "value": "2023", "label": "Policy Change", "color": "#ef4444", "dashed": false}
  ],
  "referenceAreas": [
    {"x1": "2020-03", "x2": "2020-06", "label": "Pandemic", "fill": "#fee2e2", "opacity": 0.5}
  ]
}
```
**`type` field in `series`:** For `"composed"` charts, explicitly set `"type": "line" | "bar" | "area"` on each series.
**`yAxisId` field in `series`:** Optionally use `"left"` or `"right"` to map series to specific axes when displaying data with different scales.
**`shape` field in `series`:** Optionally use `"shape": "candlestick"` for bar charts representing financial OHLC data.
**`referenceLines` and `referenceAreas` are optional** but should be included whenever they add analytical value — e.g., historical averages, targets, crisis dates, rate decisions, or regime changes.

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

## TreemapChart
```json
{
  "id": "portfolio_allocation",
  "type": "treemap",
  "title": "Portfolio Weights",
  "description": "Allocation by sector.",
  "data": [{"name": "Tech", "size": 45, "color": "#3b82f6"}]
}
```

**Rule:** Use the canonical report schema only. Do not emit legacy `chartType`, `xKey`, `yKeys`, `config`, `xAxis`, `yAxis`, `key`, or `name` fields.

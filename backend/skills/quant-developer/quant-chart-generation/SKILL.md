---
name: quant-chart-generation
description: Concise rules for Recharts JSON generation
triggers: [chart, Recharts, AxisChartDef, ScatterChartDef, PieChartDef, TreemapChartDef, RadarChartDef, RadialBarChartDef, FunnelChartDef, SankeyChartDef, SunburstChartDef, JSON]
---

# Chart Rules

1. **Format:** Dict keyed by `snake_case` ID.
2. **Path:** `{OUTPUT_BASE_DIR}/{job_id}/charts.json`.
3. **Palette:** `["#3b82f6", "#f59e0b", "#10b981", "#ef4444", "#8b5cf6"]`.
4. **Period labels:** For quarterly data, format labels as `YYYY Qn`. Never use unsupported directives like `%Q`.
5. **Supported types only:** Use only `line`, `bar`, `area`, `composed`, `scatter`, `pie`, `treemap`, `radar`, `radialBar`, `funnel`, `sankey`, or `sunburst`. Do not emit `heatmap`, `table`, or arbitrary Recharts passthrough. Period comparisons should usually be grouped `bar`, `composed`, or `radar` charts depending on the analytical purpose.
6. **Mixed FRED frequencies:** Merge monthly and quarterly FRED data on period keys, not raw timestamps. For quarterly joins, create `quarter = date.dt.to_period("Q")` in every frame, merge on `quarter`, and derive display labels with `YYYY Qn`; never merge quarter-start GDP dates directly against quarter-end resample timestamps.
7. **Unique axis labels:** Every axis chart must have at most one data row per
   `xAxisKey` value. Aggregate daily or weekly FRED series to the chart period
   before merging, then assert the final chart frame has no duplicate labels.
8. **Missing values:** Preserve unavailable observations as `null` or omit the
   series field for that row. Never replace missing source observations,
   unavailable capex, stale peer values, or unreported periods with `0` unless
   the source explicitly reports a true zero.
9. **Grouped comparisons:** Use canonical wide rows for peer or scenario
   comparisons: one row per `xAxisKey` value and one numeric column per series.
   Do not emit long-form grouped axis charts with repeated `series.dataKey` and
   `config.groupBy`; unsupported grouped shapes are rejected or repaired before
   handoff.
10. **Dual axes:** Use a right axis only when series have materially different
   units or scales. Same-unit growth/rate series with similar numeric ranges
   should share the left axis so the chart does not imply a false divergence.
11. **Chart-heavy requests:** When the user asks for charts, a chart pack,
   dashboard, visual evidence, or chart validation, create a rich pack of 6-8
   distinct renderable charts when the data supports it. Prefer at least three
   chart families when each one clarifies a different analytical question. Cover the requested
   analytical dimensions instead of stopping after a compact sample: trend,
   dual-axis spread/context, recession or reference bands, forecast/backtest,
   historical replay or analogs, stress components, and missing-data/source
   coverage where applicable. Do not return an empty chart map for a chart
   request; emit a failed quantitative handoff if charts cannot be generated.
12. **Insight check:** Before saving, ask whether each chart makes the report
   more insightful than a table or sentence. Keep charts that answer a distinct
   analytical question; replace redundant charts with a better view rather than
   merely increasing count. Do not add novelty charts unless they make the
   user's decision easier; a mostly time-series pack is acceptable when time
   series are genuinely the most insightful views.
13. **Method labels:** For deterministic macro statistics, include `methods_used`
   on each relevant chart definition and in `execution_summary.json`. If a
   label names a correlation, growth rate, spread, or normalized index, add a
   chart-level `transform_basis`/`correlation_basis`/`calculation_basis` or a
   matching `execution_summary["transforms"]` descriptor built with
   `transform_descriptor(...)`.
14. **Provenance:** For charts that resample, index, normalize, or truncate
   source data, attach `provenance` from
   `chart_provenance(...)`: raw source window/latest observation, displayed
   window/latest label, frequency/resampling, normalization base, and
   limitations.
15. **Saving artifacts:** Prefer
   `save_quant_outputs(output_dir, charts, execution_summary)` from
   `agents.quant_macro_stats`. It writes strict JSON, derives `chart_ids` from
   the saved chart map, mirrors chart provenance into
   `execution_summary.json`, saves the actual generating script path when
   available, and returns the compact handoff to print. Never import
   `agents.quant_utils`.

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
**Variants:** Use `stackId` for stacked bars/areas and `"layout": "vertical"` for horizontal bar charts. These are variants of `bar`/`composed`, not new chart types.

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
For bubble scatters, include optional `sizeKey` with positive numeric values and optional `colorKey` when point-level colors are encoded in `color`/`fill`.

## PieChart
Every pie chart MUST include `id`, `type` (`"pie"`), `title`, `description`,
and `data` as an array of `{"name": "...", "value": <number>, "color":
"#3b82f6"}` slices. Use optional `innerRadius` for donut pies.

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

## RadarChart
Use for normalized profiles across comparable dimensions, not raw time series.

```json
{
  "id": "risk_profile",
  "type": "radar",
  "title": "Risk Profile",
  "description": "Current scores by risk dimension.",
  "angleKey": "metric",
  "series": [{"dataKey": "score", "label": "Score", "color": "#3b82f6"}],
  "data": [{"metric": "Labor", "score": 70}]
}
```

## RadialBarChart
Use for current score components or incidence counts with positive values.

```json
{
  "id": "component_scores",
  "type": "radialBar",
  "title": "Component Scores",
  "description": "Positive component scores.",
  "data": [{"name": "Labor", "value": 70, "color": "#3b82f6"}]
}
```

## FunnelChart
Use for staged filters or narrowing sample counts. Values must be positive.

```json
{
  "id": "filter_funnel",
  "type": "funnel",
  "title": "Filter Funnel",
  "description": "Observations remaining at each stage.",
  "data": [{"name": "All observations", "value": 240, "color": "#3b82f6"}]
}
```

## SankeyChart
Use for flows or decomposition paths. Link `source` and `target` are zero-based indexes into `nodes`; link values must be positive.

```json
{
  "id": "signal_flow",
  "type": "sankey",
  "title": "Signal Flow",
  "description": "Inputs flowing into composite components.",
  "data": {
    "nodes": [{"name": "Inputs"}, {"name": "Labor"}, {"name": "Composite"}],
    "links": [{"source": 0, "target": 1, "value": 12}, {"source": 1, "target": 2, "value": 12}]
  }
}
```

## SunburstChart
Use for contribution hierarchy. The root must have non-empty `children`; leaves need positive `value` or `size`.

```json
{
  "id": "contribution_hierarchy",
  "type": "sunburst",
  "title": "Contribution Hierarchy",
  "description": "Nested contribution shares.",
  "data": {
    "name": "Total",
    "children": [{"name": "Labor", "value": 40, "fill": "#3b82f6"}]
  }
}
```

## Choosing Chart Types
- Trends over time: `line`, `area`, or `composed` with reference bands.
- Overlays with different mark types: `composed`.
- Relationships: `scatter`; add `sizeKey` for bubble relationships.
- Normalized profiles: `radar`.
- Current component scores or incidence counts: `radialBar`.
- Contribution hierarchy: `treemap` or `sunburst`.
- Staged filters: `funnel`.
- Flows or decomposition paths: `sankey`.

**Rule:** Use the canonical report schema only. Do not emit legacy `chartType`, `yKeys`, `config`, `xAxis`, `yAxis`, or `key` fields. Use `xKey`/`yKey` only for canonical `scatter` charts.

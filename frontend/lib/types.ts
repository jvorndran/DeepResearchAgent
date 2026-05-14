export type ResearchStatus = "idle" | "loading" | "streaming" | "report_ready" | "failed" | "error";

export interface Message {
  role: "user" | "assistant";
  content: string;
  metadata?: Record<string, unknown>;
  parts?: Array<Record<string, unknown>>;
}

export interface ToolCall {
  tool: string;
  args: unknown;
  status: "running" | "done";
  summary?: string;
}

export interface PipelineStep {
  agent: string | null;
  status: "running" | "done";
  tools: ToolCall[];
}

export interface DataSource {
  provider: string;
  description: string;
  tickers?: string[];
  series_ids?: string[];
  date_range?: { start: string; end: string };
  row_count?: number;
}

export interface ScenarioRow {
  scenario: "base" | "bull" | "bear";
  assumptions: string[];
  indicator_triggers: string[];
  confidence: "low" | "medium" | "high";
  uncertainty_notes: string;
}

export interface SeriesDef {
  dataKey: string;
  label: string;
  color: string;
  type?: "line" | "bar" | "area";
  yAxisId?: "left" | "right";
  stackId?: string;
  shape?: string;
  strokeDasharray?: string;
}

export interface ReferenceLineDef {
  axis: "x" | "y";
  value: string | number;
  label?: string;
  color?: string;
  dashed?: boolean;
}

export interface ReferenceAreaDef {
  x1?: string | number;
  x2?: string | number;
  y1?: string | number;
  y2?: string | number;
  label?: string;
  fill?: string;
  opacity?: number;
}

export interface AxisChartDef {
  id: string;
  type: "line" | "bar" | "area" | "composed";
  title: string;
  description: string;
  xAxisKey: string;
  series: SeriesDef[];
  data: Array<Record<string, number | string | null>>;
  layout?: "horizontal" | "vertical";
  referenceLines?: ReferenceLineDef[];
  referenceAreas?: ReferenceAreaDef[];
}

export interface ScatterChartDef {
  id: string;
  type: "scatter";
  title: string;
  description: string;
  xKey: string;
  yKey: string;
  xLabel: string;
  yLabel: string;
  color: string;
  data: Array<Record<string, number | string | null>>;
  sizeKey?: string;
  colorKey?: string;
  nameKey?: string;
}

export interface PieChartDef {
  id: string;
  type: "pie";
  title: string;
  description: string;
  data: Array<{ name: string; value: number; color?: string }>;
  innerRadius?: number | string;
}

export interface RadarChartDef {
  id: string;
  type: "radar";
  title: string;
  description: string;
  angleKey: string;
  series: SeriesDef[];
  data: Array<Record<string, number | string | null>>;
}

export interface SegmentDatum {
  name: string;
  value: number;
  color?: string;
  fill?: string;
}

export interface RadialBarChartDef {
  id: string;
  type: "radialBar";
  title: string;
  description: string;
  data: SegmentDatum[];
  dataKey?: string;
  innerRadius?: number | string;
  outerRadius?: number | string;
}

export interface FunnelChartDef {
  id: string;
  type: "funnel";
  title: string;
  description: string;
  data: SegmentDatum[];
  dataKey?: string;
  nameKey?: string;
}

export interface HierarchyDatum {
  [key: string]: unknown;
  name: string;
  value?: number;
  size?: number;
  color?: string;
  fill?: string;
  children?: HierarchyDatum[];
}

export interface TreemapChartDef {
  id: string;
  type: "treemap";
  title: string;
  description: string;
  data: HierarchyDatum[];
  valueKey?: "size" | "value";
}

export interface SankeyChartDef {
  id: string;
  type: "sankey";
  title: string;
  description: string;
  data: {
    nodes: Array<{ name: string; color?: string; fill?: string }>;
    links: Array<{ source: number; target: number; value: number; color?: string; fill?: string }>;
  };
}

export interface SunburstChartDef {
  id: string;
  type: "sunburst";
  title: string;
  description: string;
  data: HierarchyDatum;
  valueKey?: "value" | "size";
}

export type ChartDef =
  | AxisChartDef
  | ScatterChartDef
  | PieChartDef
  | RadarChartDef
  | RadialBarChartDef
  | FunnelChartDef
  | TreemapChartDef
  | SankeyChartDef
  | SunburstChartDef;

export interface ResearchReport {
  schema_version: 1;
  job_id: string;
  created_at: string;
  query: string;
  title: string;
  executive_summary: string;
  markdown: string;
  charts: Record<string, ChartDef>;
  scenario_table?: ScenarioRow[] | null;
  data_sources: DataSource[];
  metadata: {
    analysis_type: string;
    chart_count: number;
    word_count: number;
  };
}

export interface SavedReportSummary {
  id: number;
  job_id: string;
  title: string;
  query: string;
  created_at: string;
  updated_at: string;
}

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

export interface SeriesDef {
  dataKey: string;
  label: string;
  color: string;
  type?: "line" | "bar" | "area";
  yAxisId?: "left" | "right";
  shape?: string;
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
  data: Array<Record<string, number | string>>;
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
  data: Array<Record<string, number>>;
}

export interface PieChartDef {
  id: string;
  type: "pie";
  title: string;
  description: string;
  data: Array<{ name: string; value: number; color?: string }>;
}

export interface TreemapChartDef {
  id: string;
  type: "treemap";
  title: string;
  description: string;
  data: Array<{ name: string; size: number; color?: string }>;
}

export type ChartDef = AxisChartDef | ScatterChartDef | PieChartDef | TreemapChartDef;

export interface ResearchReport {
  schema_version: 1;
  job_id: string;
  created_at: string;
  query: string;
  title: string;
  executive_summary: string;
  markdown: string;
  charts: Record<string, ChartDef>;
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

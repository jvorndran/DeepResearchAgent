"use client";

import {
  LineChart, Line,
  BarChart, Bar,
  AreaChart, Area,
  ComposedChart,
  ScatterChart, Scatter,
  PieChart, Pie,
  Treemap,
  RadarChart, Radar,
  RadialBarChart, RadialBar,
  FunnelChart, Funnel,
  Sankey,
  SunburstChart,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  PolarGrid, PolarAngleAxis, PolarRadiusAxis,
  ZAxis,
  Brush, ReferenceLine, ReferenceArea,
  Cell,
} from "recharts";
import type { ChartDef, SeriesDef, AxisChartDef, HierarchyDatum } from "@/lib/types";
import { validateChartRenderContract } from "@/lib/chart-contract";
import { useElementWidth } from "@/hooks/use-pretext";

interface ReportChartProps {
  chartId: string;
  chart: ChartDef;
}

type CandlestickShapeProps = {
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  fill?: string;
  stroke?: string;
  payload?: Record<string, unknown>;
  yAxis?: { scale?: ((value: number) => number) | undefined };
};

type ChartReferenceArea = {
  x1?: number | string;
  x2?: number | string;
  y1?: number | string;
  y2?: number | string;
  yAxisId?: "left" | "right";
  fill?: string;
  opacity?: number;
  label?: string;
};

type ChartReferenceLine = {
  axis?: "x" | "y";
  value: number | string;
  yAxisId?: "left" | "right";
  color?: string;
  dashed?: boolean;
  label?: string;
};

type TreemapContentProps = {
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  name?: string;
  color?: string;
  fill?: string;
};

const _PALETTE = ["#3b82f6", "#f59e0b", "#10b981", "#ef4444", "#8b5cf6"];

function toNumber(value: unknown): number | null {
  const num = Number(value);
  return Number.isFinite(num) ? num : null;
}

function datumFill(row: object, fallback: string, key?: string): string {
  const record = row as Record<string, unknown>;
  const value = (key ? record[key] : undefined) ?? record.fill ?? record.color;
  return typeof value === "string" && value.trim() ? value : fallback;
}

function hierarchyValueKey(
  nodes: HierarchyDatum | HierarchyDatum[],
  preferred?: "size" | "value"
): "size" | "value" {
  if (preferred) return preferred;
  const stack = Array.isArray(nodes) ? [...nodes] : [nodes];
  while (stack.length) {
    const node = stack.shift();
    if (!node) continue;
    if (node.size != null) return "size";
    if (node.value != null) return "value";
    if (node.children) stack.push(...node.children);
  }
  return "value";
}

function withHierarchyTotals(node: HierarchyDatum, valueKey: "size" | "value"): HierarchyDatum {
  if (!node.children?.length) return node;
  const children = node.children.map((child) => withHierarchyTotals(child, valueKey));
  const total = children.reduce((sum, child) => {
    const raw = child[valueKey] ?? (valueKey === "size" ? child.value : child.size);
    const numeric = Number(raw);
    return Number.isFinite(numeric) ? sum + numeric : sum;
  }, 0);
  return {
    ...node,
    [valueKey]: node[valueKey] ?? total,
    children,
  };
}

const Candlestick = (props: CandlestickShapeProps) => {
  const { x, y, width, height, fill, stroke, payload, yAxis } = props;
  if (x == null || y == null || width == null || height == null) {
    return null;
  }

  const open = toNumber(payload?.open);
  const high = toNumber(payload?.high);
  const low = toNumber(payload?.low);
  const close = toNumber(payload?.close);
  const scale = yAxis?.scale;
  const color = stroke ?? fill ?? "#2563eb";

  if (
    open == null ||
    high == null ||
    low == null ||
    close == null ||
    typeof scale !== "function"
  ) {
    return <rect x={x} y={y} width={width} height={height} fill={color} />;
  }

  const centerX = x + width / 2;
  const bodyWidth = Math.max(width * 0.55, 3);
  const bodyX = centerX - bodyWidth / 2;
  const highY = scale(high);
  const lowY = scale(low);
  const openY = scale(open);
  const closeY = scale(close);
  const bodyY = Math.min(openY, closeY);
  const bodyHeight = Math.max(Math.abs(closeY - openY), 1);

  return (
    <g>
      <line x1={centerX} x2={centerX} y1={highY} y2={lowY} stroke={color} strokeWidth={1.5} />
      <rect x={bodyX} y={bodyY} width={bodyWidth} height={bodyHeight} fill={color} stroke={color} />
    </g>
  );
};

function computeYDomain(
  dataKeys: string[],
  data: Array<Record<string, number | string | null>>,
  chartType: string
): [number | string, number | string] {
  if (chartType === "bar") return [0, "auto"];

  const vals = data
    .flatMap(d => dataKeys.map(k => Number(d[k])))
    .filter(v => isFinite(v));

  if (!vals.length) return [0, "auto"];

  const min = Math.min(...vals);
  const max = Math.max(...vals);

  if (min < 0 || max === 0 || min / max < 0.5) return [0, "auto"];

  const pad = (max - min) * 0.05;
  return [
    (dataMin: number) => Math.min(dataMin, min) - pad,
    (dataMax: number) => Math.max(dataMax, max) + pad,
  ] as unknown as [number | string, number | string];
}

function resolveAxisIds(
  series: SeriesDef[],
  data: Array<Record<string, number | string | null>>
): Record<string, "left" | "right"> {
  // If series explicitly define yAxisId, use that directly.
  if (series.some(s => s.yAxisId === "left" || s.yAxisId === "right")) {
    return Object.fromEntries(series.map(s => [s.dataKey, s.yAxisId || "left"]));
  }

  const ranges = series.map(s => {
    const vals = data.map(d => Number(d[s.dataKey])).filter(v => isFinite(v));
    const max = vals.length ? Math.max(...vals) : 0;
    const min = vals.length ? Math.min(...vals) : 0;
    return { dataKey: s.dataKey, range: max - min };
  });

  const positiveRanges = ranges.map(r => r.range).filter(r => r > 0);
  const maxRange = positiveRanges.length ? Math.max(...positiveRanges) : 0;
  const minRange = positiveRanges.length ? Math.min(...positiveRanges) : 0;
  const dual = series.length >= 2 && minRange > 0 && maxRange / minRange >= 10;

  if (!dual) return Object.fromEntries(series.map(s => [s.dataKey, "left"]));

  const sorted = [...ranges].sort((a, b) => b.range - a.range);
  const leftKey = sorted[0].dataKey;
  return Object.fromEntries(series.map(s => [s.dataKey, s.dataKey === leftKey ? "left" : "right"]));
}

function renderReferenceAreas(chart: AxisChartDef) {
  if (!chart.referenceAreas) return null;
  return (chart.referenceAreas as ChartReferenceArea[]).map((ra, i) => (
    <ReferenceArea
      key={`ra-${i}`}
      x1={ra.x1}
      x2={ra.x2}
      y1={ra.y1}
      y2={ra.y2}
      yAxisId={ra.yAxisId ?? "left"}
      fill={ra.fill ?? "#ccc"}
      fillOpacity={ra.opacity ?? 0.3}
      label={ra.label}
    />
  ));
}

function renderReferenceLines(chart: AxisChartDef) {
  if (!chart.referenceLines) return null;
  return (chart.referenceLines as ChartReferenceLine[]).map((rl, i) => (
    <ReferenceLine
      key={`rl-${i}`}
      {...(rl.axis === "x" ? { x: rl.value } : { y: rl.value, yAxisId: rl.yAxisId ?? "left" })}
      stroke={rl.color ?? "#888"}
      strokeDasharray={rl.dashed ? "4 4" : undefined}
      label={rl.label}
    />
  ));
}

export default function ReportChart({ chartId, chart }: ReportChartProps) {
  const { ref: chartFrameRef, width: chartFrameWidth } = useElementWidth<HTMLDivElement>();
  const chartWidth = Math.floor(chartFrameWidth);
  const chartHeight = Math.min(352, Math.max(240, Math.round(chartWidth * 0.55)));
  const contractIssues = validateChartRenderContract(chartId, chart);
  if (contractIssues.length > 0) {
    return (
      <figure className="not-prose my-10 w-full flex flex-col gap-3" key={chartId}>
        <h3 className="text-base font-semibold text-center text-foreground shrink-0">
          {chart.title || chartId}
        </h3>
        <div
          data-testid="chart-render-contract-error"
          className="rounded-sm border border-destructive/30 bg-destructive/10 p-4 text-sm text-destructive"
        >
          Chart could not be rendered because its data contract is invalid:
          {" "}
          {contractIssues.slice(0, 3).join("; ")}
        </div>
      </figure>
    );
  }

  return (
    <figure
      className="not-prose my-10 w-full flex flex-col gap-3"
      key={chartId}
    >
      <h3 className="text-base font-semibold text-center text-foreground shrink-0">
        {chart.title}
      </h3>
      <div
        ref={chartFrameRef}
        className="not-prose w-full min-h-[240px] overflow-hidden"
        style={{ height: `${chartHeight}px` }}
      >
        {chartWidth > 0 ? (
          chart.type === "line" || chart.type === "bar" || chart.type === "area" || chart.type === "composed" ? (() => {
            const axisIds = resolveAxisIds(chart.series, chart.data);
            const dual = Object.values(axisIds).includes("right");
            const leftKeys = chart.series.filter(s => axisIds[s.dataKey] === "left").map(s => s.dataKey);
            const rightKeys = chart.series.filter(s => axisIds[s.dataKey] === "right").map(s => s.dataKey);
            
            const ChartComponent = chart.type === "line" ? LineChart :
                                   chart.type === "bar" ? BarChart :
                                   chart.type === "area" ? AreaChart : ComposedChart;
            const verticalLayout = chart.layout === "vertical";

            const hasBarOnLeft = chart.series.some(s => axisIds[s.dataKey] === "left" && (chart.type === "composed" ? s.type === "bar" : chart.type === "bar"));
            const leftDomainType = hasBarOnLeft ? "bar" : "line";
            
            const hasBarOnRight = dual && chart.series.some(s => axisIds[s.dataKey] === "right" && (chart.type === "composed" ? s.type === "bar" : chart.type === "bar"));
            const rightDomainType = hasBarOnRight ? "bar" : "line";

            return (
              <ChartComponent
                width={chartWidth}
                height={chartHeight}
                data={chart.data}
                layout={chart.layout ?? undefined}
                margin={{ top: 5, right: dual ? 60 : 30, left: verticalLayout ? 90 : 20, bottom: 5 }}
              >
                <CartesianGrid strokeDasharray="3 3" />
                {verticalLayout ? (
                  <>
                    <XAxis type="number" domain={computeYDomain(leftKeys, chart.data, leftDomainType)} />
                    <YAxis type="category" dataKey={chart.xAxisKey} width={110} />
                  </>
                ) : (
                  <>
                    <XAxis dataKey={chart.xAxisKey} />
                    <YAxis
                      {...(dual ? { yAxisId: "left" as const } : {})}
                      orientation="left"
                      domain={computeYDomain(leftKeys, chart.data, leftDomainType)}
                    />
                    {dual && <YAxis yAxisId="right" orientation="right" domain={computeYDomain(rightKeys, chart.data, rightDomainType)} />}
                  </>
                )}
                <Tooltip />
                <Legend />
                {renderReferenceAreas(chart)}
                {chart.series.map((s, i) => {
                  const yAxisId = axisIds[s.dataKey];
                  const shape = s.shape === "candlestick" ? <Candlestick /> : undefined;
                  const type = chart.type === "composed" ? (s.type ?? "line") : chart.type;
                  const seriesId = `${chartId}-${s.dataKey}`;
                  const stackId = s.stackId ?? undefined;
                  const strokeDasharray = s.strokeDasharray ?? undefined;

                  if (type === "bar") {
                    return <Bar key={i} id={seriesId} dataKey={s.dataKey} name={s.label} fill={s.color} yAxisId={verticalLayout || !dual ? undefined : yAxisId} shape={shape} stackId={stackId} isAnimationActive={false} />;
                  } else if (type === "area") {
                    return <Area key={i} id={seriesId} type="monotone" dataKey={s.dataKey} name={s.label} fill={s.color} stroke={s.color} yAxisId={verticalLayout || !dual ? undefined : yAxisId} stackId={stackId} strokeDasharray={strokeDasharray} isAnimationActive={false} />;
                  } else {
                    return <Line key={i} id={seriesId} type="monotone" dataKey={s.dataKey} name={s.label} stroke={s.color} yAxisId={verticalLayout || !dual ? undefined : yAxisId} strokeDasharray={strokeDasharray} isAnimationActive={false} />;
                  }
                })}
                {renderReferenceLines(chart)}
                {!verticalLayout && <Brush dataKey={chart.xAxisKey} height={24} stroke="#8884d8" />}
              </ChartComponent>
            );
          })() : chart.type === "scatter" ? (
            <ScatterChart width={chartWidth} height={chartHeight} margin={{ top: 20, right: 20, bottom: 20, left: 20 }}>
              <CartesianGrid />
              <XAxis type="number" dataKey={chart.xKey} name={chart.xLabel} />
              <YAxis type="number" dataKey={chart.yKey} name={chart.yLabel} />
              {chart.sizeKey ? <ZAxis type="number" dataKey={chart.sizeKey} range={[70, 520]} /> : null}
              <Tooltip cursor={{ strokeDasharray: "3 3" }} />
              <Legend />
              <Scatter name={chart.title} data={chart.data} fill={chart.color}>
                {chart.colorKey
                  ? chart.data.map((row, index) => (
                      <Cell key={`scatter-cell-${index}`} fill={datumFill(row, chart.color, chart.colorKey)} />
                    ))
                  : null}
              </Scatter>
            </ScatterChart>
          ) : chart.type === "radar" ? (
            <RadarChart width={chartWidth} height={chartHeight} data={chart.data} outerRadius="75%">
              <PolarGrid />
              <PolarAngleAxis dataKey={chart.angleKey} />
              <PolarRadiusAxis />
              <Tooltip />
              <Legend />
              {chart.series.map((series, index) => (
                <Radar
                  key={series.dataKey}
                  name={series.label}
                  dataKey={series.dataKey}
                  stroke={series.color}
                  fill={series.color}
                  fillOpacity={index === 0 ? 0.28 : 0.14}
                />
              ))}
            </RadarChart>
          ) : chart.type === "radialBar" ? (
            <RadialBarChart
              width={chartWidth}
              height={chartHeight}
              data={chart.data}
              innerRadius={chart.innerRadius ?? "18%"}
              outerRadius={chart.outerRadius ?? "86%"}
              startAngle={90}
              endAngle={-270}
            >
              <Tooltip />
              <Legend iconSize={10} layout="vertical" verticalAlign="middle" align="right" />
              <RadialBar dataKey={chart.dataKey ?? "value"} background label={{ position: "insideStart", fill: "#fff" }}>
                {chart.data.map((row, index) => (
                  <Cell key={`radial-cell-${index}`} fill={datumFill(row, _PALETTE[index % _PALETTE.length])} />
                ))}
              </RadialBar>
            </RadialBarChart>
          ) : chart.type === "funnel" ? (
            <FunnelChart width={chartWidth} height={chartHeight} margin={{ top: 20, right: 40, bottom: 20, left: 40 }}>
              <Tooltip />
              <Legend />
              <Funnel data={chart.data} dataKey={chart.dataKey ?? "value"} nameKey={chart.nameKey ?? "name"} isAnimationActive={false} label>
                {chart.data.map((row, index) => (
                  <Cell key={`funnel-cell-${index}`} fill={datumFill(row, _PALETTE[index % _PALETTE.length])} />
                ))}
              </Funnel>
            </FunnelChart>
          ) : chart.type === "treemap" ? (
            <Treemap
              width={chartWidth}
              height={chartHeight}
              data={chart.data}
              dataKey={hierarchyValueKey(chart.data, chart.valueKey)}
              nameKey="name"
              stroke="#fff"
              content={(props: TreemapContentProps) => {
                const { x, y, width, height, name, color, fill } = props;
                if (x == null || y == null || width == null || height == null) {
                  return <g />;
                }
                return (
                  <g>
                    <rect x={x} y={y} width={width} height={height} fill={color || fill || "#3b82f6"} stroke="#fff" />
                    {width > 30 && height > 20 && (
                      <text x={x + width / 2} y={y + height / 2} textAnchor="middle" fill="#fff" fontSize={12}>
                        {name}
                      </text>
                    )}
                  </g>
                );
              }}
            >
              <Tooltip />
            </Treemap>
          ) : chart.type === "sankey" ? (
            <Sankey
              width={chartWidth}
              height={chartHeight}
              data={chart.data}
              dataKey="value"
              nameKey="name"
              nodePadding={18}
              nodeWidth={12}
              linkCurvature={0.55}
              iterations={48}
              margin={{ top: 12, right: 24, bottom: 12, left: 24 }}
              node={{ fill: "#3b82f6", stroke: "rgba(15, 23, 42, 0.25)" }}
              link={{ stroke: "rgba(59, 130, 246, 0.35)" }}
            >
              <Tooltip />
            </Sankey>
          ) : chart.type === "sunburst" ? (() => {
            const valueKey = hierarchyValueKey(chart.data, chart.valueKey);
            const data = withHierarchyTotals(chart.data, valueKey);
            return (
              <SunburstChart
                width={chartWidth}
                height={chartHeight}
                data={data}
                dataKey={valueKey}
                nameKey="name"
                innerRadius={36}
                padding={2}
                fill="#3b82f6"
                stroke="#fff"
              >
                <Tooltip />
              </SunburstChart>
            );
          })() : chart.type === "pie" ? (
            <PieChart width={chartWidth} height={chartHeight}>
              <Pie data={chart.data} dataKey="value" nameKey="name" cx="50%" cy="50%" innerRadius={chart.innerRadius ?? 0} outerRadius="80%" fill="#8884d8" label>
                {chart.data.map((row, index) => (
                  <Cell key={`pie-cell-${index}`} fill={datumFill(row, _PALETTE[index % _PALETTE.length])} />
                ))}
              </Pie>
              <Tooltip />
              <Legend />
            </PieChart>
          ) : null
        ) : null}
      </div>
      {chart.description ? (
        <figcaption className="text-sm text-muted-foreground text-center leading-relaxed px-1 pb-1">
          {chart.description}
        </figcaption>
      ) : null}
    </figure>
  );
}

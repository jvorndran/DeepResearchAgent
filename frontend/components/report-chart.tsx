"use client";

import {
  LineChart, Line,
  BarChart, Bar,
  AreaChart, Area,
  ComposedChart,
  ScatterChart, Scatter,
  PieChart, Pie,
  Treemap,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
  Brush, ReferenceLine, ReferenceArea,
} from "recharts";
import type { ChartDef, SeriesDef, AxisChartDef } from "@/lib/types";

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

function toNumber(value: unknown): number | null {
  const num = Number(value);
  return Number.isFinite(num) ? num : null;
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
  data: Array<Record<string, number | string>>,
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
  data: Array<Record<string, number | string>>
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
  return (
    <figure
      className="my-10 w-full flex flex-col gap-3"
      key={chartId}
    >
      <h3 className="text-base font-semibold text-center text-foreground shrink-0">
        {chart.title}
      </h3>
      <div className="h-[min(22rem,55vw)] w-full min-h-[240px]">
        <ResponsiveContainer width="100%" height="100%">
          {chart.type === "line" || chart.type === "bar" || chart.type === "area" || chart.type === "composed" ? (() => {
            const axisIds = resolveAxisIds(chart.series, chart.data);
            const dual = Object.values(axisIds).includes("right");
            const leftKeys = chart.series.filter(s => axisIds[s.dataKey] === "left").map(s => s.dataKey);
            const rightKeys = chart.series.filter(s => axisIds[s.dataKey] === "right").map(s => s.dataKey);
            
            const ChartComponent = chart.type === "line" ? LineChart :
                                   chart.type === "bar" ? BarChart :
                                   chart.type === "area" ? AreaChart : ComposedChart;

            const hasBarOnLeft = chart.series.some(s => axisIds[s.dataKey] === "left" && (chart.type === "composed" ? s.type === "bar" : chart.type === "bar"));
            const leftDomainType = hasBarOnLeft ? "bar" : "line";
            
            const hasBarOnRight = dual && chart.series.some(s => axisIds[s.dataKey] === "right" && (chart.type === "composed" ? s.type === "bar" : chart.type === "bar"));
            const rightDomainType = hasBarOnRight ? "bar" : "line";

            return (
              <ChartComponent data={chart.data} margin={{ top: 5, right: dual ? 60 : 30, left: 20, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey={chart.xAxisKey} />
                <YAxis yAxisId="left" orientation="left" domain={computeYDomain(leftKeys, chart.data, leftDomainType)} />
                {dual && <YAxis yAxisId="right" orientation="right" domain={computeYDomain(rightKeys, chart.data, rightDomainType)} />}
                <Tooltip />
                <Legend />
                {renderReferenceAreas(chart)}
                {chart.series.map((s, i) => {
                  const yAxisId = axisIds[s.dataKey];
                  const shape = s.shape === "candlestick" ? <Candlestick /> : undefined;
                  const type = chart.type === "composed" ? (s.type ?? "line") : chart.type;

                  if (type === "bar") {
                    return <Bar key={i} dataKey={s.dataKey} name={s.label} fill={s.color} yAxisId={yAxisId} shape={shape} />;
                  } else if (type === "area") {
                    return <Area key={i} type="monotone" dataKey={s.dataKey} name={s.label} fill={s.color} stroke={s.color} yAxisId={yAxisId} />;
                  } else {
                    return <Line key={i} type="monotone" dataKey={s.dataKey} name={s.label} stroke={s.color} yAxisId={yAxisId} />;
                  }
                })}
                {renderReferenceLines(chart)}
                <Brush dataKey={chart.xAxisKey} height={24} stroke="#8884d8" />
              </ChartComponent>
            );
          })() : chart.type === "scatter" ? (
          <ScatterChart margin={{ top: 20, right: 20, bottom: 20, left: 20 }}>
            <CartesianGrid />
            <XAxis type="number" dataKey={chart.xKey} name={chart.xLabel} />
            <YAxis type="number" dataKey={chart.yKey} name={chart.yLabel} />
            <Tooltip cursor={{ strokeDasharray: "3 3" }} />
            <Legend />
            <Scatter name={chart.title} data={chart.data} fill={chart.color} />
          </ScatterChart>
        ) : chart.type === "treemap" ? (
          <Treemap
            data={chart.data}
            dataKey="size"
            nameKey="name"
            stroke="#fff"
            content={(props: TreemapContentProps) => {
              const { x, y, width, height, name, color, fill } = props;
              if (x == null || y == null || width == null || height == null) {
                return <g />;
              }
              return (
                <g>
                  <rect x={x} y={y} width={width} height={height} fill={color || fill || "#8884d8"} stroke="#fff" />
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
        ) : (
          <PieChart>
            <Pie data={chart.data} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={150} fill="#8884d8" label />
            <Tooltip />
            <Legend />
          </PieChart>
          )}
        </ResponsiveContainer>
      </div>
      {chart.description ? (
        <figcaption className="text-sm text-muted-foreground text-center leading-relaxed px-1 pb-1">
          {chart.description}
        </figcaption>
      ) : null}
    </figure>
  );
}

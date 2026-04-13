"use client";

import {
  LineChart, Line,
  BarChart, Bar,
  AreaChart, Area,
  ScatterChart, Scatter,
  PieChart, Pie,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
  Brush, ReferenceLine,
} from "recharts";
import type { ChartDef, SeriesDef } from "@/lib/types";

interface ReportChartProps {
  chartId: string;
  chart: ChartDef;
}

/**
 * Computes a Y-axis domain for the given data keys.
 * If the minimum value is more than 50% of the maximum (data clustered well
 * above zero), anchoring at 0 wastes space — use a padded auto domain instead.
 * Bar charts always anchor at 0 so bars have a meaningful baseline.
 */
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

/**
 * Returns a yAxisId ("left" | "right") for each series dataKey.
 * When the largest series range exceeds the smallest by 10x or more,
 * the high-range series go on the left axis and the rest on the right.
 * Otherwise everything shares the left axis.
 */
function resolveAxisIds(
  series: SeriesDef[],
  data: Array<Record<string, number | string>>
): Record<string, "left" | "right"> {
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

  // Largest range → left (primary), rest → right
  const sorted = [...ranges].sort((a, b) => b.range - a.range);
  const leftKey = sorted[0].dataKey;
  return Object.fromEntries(series.map(s => [s.dataKey, s.dataKey === leftKey ? "left" : "right"]));
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
          {chart.type === "line" ? (() => {
            const axisIds = resolveAxisIds(chart.series, chart.data);
            const dual = Object.values(axisIds).includes("right");
            const leftKeys = chart.series.filter(s => axisIds[s.dataKey] === "left").map(s => s.dataKey);
            const rightKeys = chart.series.filter(s => axisIds[s.dataKey] === "right").map(s => s.dataKey);
            return (
              <LineChart data={chart.data} margin={{ top: 5, right: dual ? 60 : 30, left: 20, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey={chart.xAxisKey} />
                <YAxis yAxisId="left" orientation="left" domain={computeYDomain(leftKeys, chart.data, "line")} />
                {dual && <YAxis yAxisId="right" orientation="right" domain={computeYDomain(rightKeys, chart.data, "line")} />}
                <Tooltip />
                <Legend />
                {chart.series.map((s, i) => (
                  <Line key={i} type="monotone" dataKey={s.dataKey} name={s.label} stroke={s.color} yAxisId={axisIds[s.dataKey]} />
                ))}
                {chart.referenceLines?.map((rl, i) => (
                  <ReferenceLine
                    key={i}
                    {...(rl.axis === "x" ? { x: rl.value } : { y: rl.value, yAxisId: "left" })}
                    stroke={rl.color ?? "#888"}
                    strokeDasharray={rl.dashed ? "4 4" : undefined}
                    label={rl.label}
                  />
                ))}
                <Brush dataKey={chart.xAxisKey} height={24} stroke="#8884d8" />
              </LineChart>
            );
          })() : chart.type === "bar" ? (() => {
            const axisIds = resolveAxisIds(chart.series, chart.data);
            const dual = Object.values(axisIds).includes("right");
            const leftKeys = chart.series.filter(s => axisIds[s.dataKey] === "left").map(s => s.dataKey);
            const rightKeys = chart.series.filter(s => axisIds[s.dataKey] === "right").map(s => s.dataKey);
            return (
              <BarChart data={chart.data} margin={{ top: 5, right: dual ? 60 : 30, left: 20, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey={chart.xAxisKey} />
                <YAxis yAxisId="left" orientation="left" domain={computeYDomain(leftKeys, chart.data, "bar")} />
                {dual && <YAxis yAxisId="right" orientation="right" domain={computeYDomain(rightKeys, chart.data, "bar")} />}
                <Tooltip />
                <Legend />
                {chart.series.map((s, i) => (
                  <Bar key={i} dataKey={s.dataKey} name={s.label} fill={s.color} yAxisId={axisIds[s.dataKey]} />
                ))}
                {chart.referenceLines?.map((rl, i) => (
                  <ReferenceLine
                    key={i}
                    {...(rl.axis === "x" ? { x: rl.value } : { y: rl.value, yAxisId: "left" })}
                    stroke={rl.color ?? "#888"}
                    strokeDasharray={rl.dashed ? "4 4" : undefined}
                    label={rl.label}
                  />
                ))}
                <Brush dataKey={chart.xAxisKey} height={24} stroke="#8884d8" />
              </BarChart>
            );
          })() : chart.type === "area" ? (() => {
            const axisIds = resolveAxisIds(chart.series, chart.data);
            const dual = Object.values(axisIds).includes("right");
            const leftKeys = chart.series.filter(s => axisIds[s.dataKey] === "left").map(s => s.dataKey);
            const rightKeys = chart.series.filter(s => axisIds[s.dataKey] === "right").map(s => s.dataKey);
            return (
              <AreaChart data={chart.data} margin={{ top: 5, right: dual ? 60 : 30, left: 20, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey={chart.xAxisKey} />
                <YAxis yAxisId="left" orientation="left" domain={computeYDomain(leftKeys, chart.data, "area")} />
                {dual && <YAxis yAxisId="right" orientation="right" domain={computeYDomain(rightKeys, chart.data, "area")} />}
                <Tooltip />
                <Legend />
                {chart.series.map((s, i) => (
                  <Area key={i} type="monotone" dataKey={s.dataKey} name={s.label} fill={s.color} stroke={s.color} yAxisId={axisIds[s.dataKey]} />
                ))}
                {chart.referenceLines?.map((rl, i) => (
                  <ReferenceLine
                    key={i}
                    {...(rl.axis === "x" ? { x: rl.value } : { y: rl.value, yAxisId: "left" })}
                    stroke={rl.color ?? "#888"}
                    strokeDasharray={rl.dashed ? "4 4" : undefined}
                    label={rl.label}
                  />
                ))}
                <Brush dataKey={chart.xAxisKey} height={24} stroke="#8884d8" />
              </AreaChart>
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

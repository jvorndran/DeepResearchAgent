"use client"

import { Card } from "@/components/ui/card"
import {
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  Label,
} from "recharts"

export interface ScatterSeries {
  key: string
  label: string
  xKey: string
  yKey: string
  data: Record<string, number | string>[]
  color?: string
}

export interface ScatterPlotProps {
  title: string
  subtitle?: string
  series: ScatterSeries[]
  xLabel?: string
  yLabel?: string
  height?: number
  showTrendline?: boolean
}

const CHART_COLORS = [
  "oklch(0.78 0.12 75)",   // Primary gold
  "oklch(0.65 0.08 45)",   // Warm amber
  "oklch(0.6 0.12 180)",   // Teal
  "oklch(0.7 0.1 320)",    // Rose
  "oklch(0.55 0.1 145)",   // Emerald
]

function CustomDot(props: { cx?: number; cy?: number; fill?: string }) {
  const { cx = 0, cy = 0, fill } = props
  return (
    <circle
      cx={cx}
      cy={cy}
      r={4}
      fill={fill}
      fillOpacity={0.75}
      stroke={fill}
      strokeOpacity={1}
      strokeWidth={1}
    />
  )
}

function CustomTooltip({ active, payload }: { active?: boolean; payload?: { name: string; value: number; payload: Record<string, number | string> }[] }) {
  if (!active || !payload?.length) return null
  const data = payload[0]?.payload
  const keys = Object.keys(data ?? {})
  return (
    <div className="rounded-md border border-border/50 bg-popover/95 px-3 py-2 shadow-xl backdrop-blur-sm">
      {keys.map(k => (
        <div key={k} className="flex items-center gap-2 py-0.5">
          <span className="text-[10px] text-muted-foreground">{k}:</span>
          <span className="font-mono text-xs font-semibold text-foreground">{String(data[k])}</span>
        </div>
      ))}
    </div>
  )
}

export function ScatterPlot({ title, subtitle, series, xLabel, yLabel, height = 300 }: ScatterPlotProps) {
  return (
    <Card className="border-border/50 bg-card/50 p-5">
      <div className="mb-4">
        <h3 className="text-sm font-semibold tracking-tight text-foreground">{title}</h3>
        {subtitle && <p className="mt-0.5 text-xs text-muted-foreground">{subtitle}</p>}
      </div>

      {/* Legend */}
      {series.length > 1 && (
        <div className="mb-3 flex flex-wrap gap-3">
          {series.map((s, i) => (
            <div key={s.key} className="flex items-center gap-1.5">
              <div
                className="h-2 w-2 rounded-full"
                style={{ background: s.color ?? CHART_COLORS[i % CHART_COLORS.length] }}
              />
              <span className="text-[10px] text-muted-foreground">{s.label}</span>
            </div>
          ))}
        </div>
      )}

      <ResponsiveContainer width="100%" height={height}>
        <ScatterChart margin={{ top: 10, right: 20, left: 0, bottom: 30 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="oklch(0.28 0.015 260 / 0.3)" />
          <XAxis
            dataKey={series[0]?.xKey}
            type="number"
            tick={{ fontSize: 10, fill: "oklch(0.55 0.02 260)" }}
            tickLine={false}
            axisLine={{ stroke: "oklch(0.28 0.015 260)" }}
            domain={["auto", "auto"]}
          >
            {xLabel && <Label value={xLabel} offset={-15} position="insideBottom" style={{ fontSize: 10, fill: "oklch(0.55 0.02 260)" }} />}
          </XAxis>
          <YAxis
            dataKey={series[0]?.yKey}
            type="number"
            tick={{ fontSize: 10, fill: "oklch(0.55 0.02 260)" }}
            tickLine={false}
            axisLine={{ stroke: "oklch(0.28 0.015 260)" }}
            width={40}
          >
            {yLabel && <Label value={yLabel} angle={-90} position="insideLeft" style={{ fontSize: 10, fill: "oklch(0.55 0.02 260)" }} />}
          </YAxis>
          <Tooltip content={<CustomTooltip />} cursor={{ strokeDasharray: "3 3", stroke: "oklch(0.28 0.015 260)" }} />
          {series.map((s, i) => (
            <Scatter
              key={s.key}
              name={s.label}
              data={s.data as Record<string, number>[]}
              fill={s.color ?? CHART_COLORS[i % CHART_COLORS.length]}
              shape={<CustomDot fill={s.color ?? CHART_COLORS[i % CHART_COLORS.length]} />}
            />
          ))}
        </ScatterChart>
      </ResponsiveContainer>
    </Card>
  )
}

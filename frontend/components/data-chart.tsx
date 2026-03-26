"use client"

import { Card } from "@/components/ui/card"
import {
  ComposedChart,
  Line,
  Bar,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer
} from "recharts"

// Chart color palette using CSS custom properties
const CHART_COLORS = [
  "oklch(0.78 0.12 75)",   // Primary gold
  "oklch(0.65 0.08 45)",   // Warm amber
  "oklch(0.6 0.12 180)",   // Teal
  "oklch(0.7 0.1 320)",    // Rose
  "oklch(0.55 0.1 145)",   // Emerald
]

export interface DataSeries {
  key: string
  label: string
  type: "line" | "bar" | "area"
  yAxisId?: "left" | "right"
  color?: string
  dashed?: boolean
  unit?: string
  valuePrefix?: string
  valueSuffix?: string
}

export interface DataChartProps {
  data: Record<string, string | number>[]
  series: DataSeries[]
  xAxisKey: string
  title: string
  subtitle?: string
  height?: number
}

interface CustomTooltipProps {
  active?: boolean
  payload?: Array<{
    name: string
    value: number
    color: string
    dataKey: string
  }>
  label?: string
  series: DataSeries[]
}

function CustomTooltip({ active, payload, label, series }: CustomTooltipProps) {
  if (active && payload && payload.length) {
    return (
      <div className="rounded-md border border-border bg-popover/95 px-3 py-2 shadow-xl backdrop-blur-sm">
        <p className="mb-2 text-xs font-semibold tracking-wide text-foreground uppercase">{label}</p>
        <div className="space-y-1">
          {payload.map((entry, index) => {
            const config = series.find(s => s.key === entry.dataKey)
            return (
              <div key={index} className="flex items-center justify-between gap-4 text-xs">
                <div className="flex items-center gap-2">
                  <div
                    className="h-2 w-2 rounded-sm"
                    style={{ backgroundColor: entry.color }}
                  />
                  <span className="text-muted-foreground">
                    {config?.label || entry.name}
                  </span>
                </div>
                <span className="font-mono font-medium text-foreground">
                  {config?.valuePrefix || ""}{entry.value.toLocaleString()}{config?.valueSuffix || config?.unit || ""}
                </span>
              </div>
            )
          })}
        </div>
      </div>
    )
  }
  return null
}

export function DataChart({ 
  data, 
  series, 
  xAxisKey, 
  title, 
  subtitle,
  height = 320 
}: DataChartProps) {
  const hasRightAxis = series.some(s => s.yAxisId === "right")
  
  return (
    <Card className="border-border/50 bg-card/50 p-5">
      <div className="mb-5">
        <h3 className="text-base font-semibold tracking-tight text-foreground">
          {title}
        </h3>
        {subtitle && (
          <p className="mt-0.5 text-xs text-muted-foreground">
            {subtitle}
          </p>
        )}
      </div>
      
      <div style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data} margin={{ top: 10, right: hasRightAxis ? 10 : 0, left: -10, bottom: 0 }}>
            <CartesianGrid
              strokeDasharray="3 3"
              stroke="oklch(0.28 0.015 260 / 0.5)"
              vertical={false}
            />
            <XAxis
              dataKey={xAxisKey}
              tick={{ fill: "oklch(0.55 0.02 260)", fontSize: 10 }}
              tickLine={false}
              axisLine={{ stroke: "oklch(0.28 0.015 260)" }}
              interval="preserveStartEnd"
              tickMargin={8}
            />
            <YAxis
              yAxisId="left"
              tick={{ fill: "oklch(0.55 0.02 260)", fontSize: 10 }}
              tickLine={false}
              axisLine={false}
              tickMargin={4}
            />
            {hasRightAxis && (
              <YAxis
                yAxisId="right"
                orientation="right"
                tick={{ fill: "oklch(0.55 0.02 260)", fontSize: 10 }}
                tickLine={false}
                axisLine={false}
                tickMargin={4}
              />
            )}
            <Tooltip content={<CustomTooltip series={series} />} />
            <Legend
              wrapperStyle={{ paddingTop: "16px" }}
              formatter={(value) => {
                const config = series.find(s => s.key === value)
                return (
                  <span className="text-[10px] uppercase tracking-wider text-muted-foreground">
                    {config?.label || value}
                  </span>
                )
              }}
            />
            {series.map((s, index) => {
              const color = s.color || CHART_COLORS[index % CHART_COLORS.length]
              const yAxisId = s.yAxisId || "left"
              
              if (s.type === "bar") {
                return (
                  <Bar
                    key={s.key}
                    yAxisId={yAxisId}
                    dataKey={s.key}
                    fill={color}
                    radius={[3, 3, 0, 0]}
                    opacity={0.85}
                  />
                )
              }
              
              if (s.type === "area") {
                return (
                  <Area
                    key={s.key}
                    yAxisId={yAxisId}
                    type="monotone"
                    dataKey={s.key}
                    stroke={color}
                    fill={color}
                    fillOpacity={0.15}
                    strokeWidth={2}
                  />
                )
              }
              
              return (
                <Line
                  key={s.key}
                  yAxisId={yAxisId}
                  type="monotone"
                  dataKey={s.key}
                  stroke={color}
                  strokeWidth={2}
                  dot={false}
                  strokeDasharray={s.dashed ? "5 5" : undefined}
                  activeDot={{ r: 4, fill: color, stroke: "oklch(0.15 0.008 260)", strokeWidth: 2 }}
                />
              )
            })}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </Card>
  )
}

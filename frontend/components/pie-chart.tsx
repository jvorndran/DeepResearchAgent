"use client"

import { Card } from "@/components/ui/card"
import {
  PieChart as RechartsPieChart,
  Pie,
  Cell,
  ResponsiveContainer,
  Tooltip,
  Legend
} from "recharts"

const CHART_COLORS = [
  "oklch(0.78 0.12 75)",
  "oklch(0.65 0.08 45)",
  "oklch(0.6 0.12 180)",
  "oklch(0.7 0.1 320)",
  "oklch(0.55 0.1 145)",
]

export interface PieDataItem {
  name: string
  value: number
}

export interface DataPieChartProps {
  data: PieDataItem[]
  title: string
  subtitle?: string
  valuePrefix?: string
  valueSuffix?: string
  showLegend?: boolean
  innerRadius?: number
}

interface CustomTooltipProps {
  active?: boolean
  payload?: Array<{
    name: string
    value: number
    payload: PieDataItem & { percent: number }
  }>
  valuePrefix?: string
  valueSuffix?: string
}

function CustomTooltip({ active, payload, valuePrefix = "", valueSuffix = "" }: CustomTooltipProps) {
  if (active && payload && payload.length) {
    const data = payload[0]
    return (
      <div className="rounded-md border border-border bg-popover/95 px-3 py-2 shadow-xl backdrop-blur-sm">
        <p className="mb-1 text-xs font-semibold text-foreground">{data.name}</p>
        <p className="text-xs text-muted-foreground">
          {valuePrefix}{data.value.toLocaleString()}{valueSuffix}
        </p>
        <p className="text-xs text-muted-foreground">
          {(data.payload.percent * 100).toFixed(1)}% of total
        </p>
      </div>
    )
  }
  return null
}

export function DataPieChart({
  data,
  title,
  subtitle,
  valuePrefix = "",
  valueSuffix = "",
  showLegend = true,
  innerRadius = 0
}: DataPieChartProps) {
  const total = data.reduce((sum, item) => sum + item.value, 0)
  
  return (
    <Card className="border-border/50 bg-card/50 p-5">
      <div className="mb-4">
        <h3 className="text-base font-semibold tracking-tight text-foreground">
          {title}
        </h3>
        {subtitle && (
          <p className="mt-0.5 text-xs text-muted-foreground">
            {subtitle}
          </p>
        )}
      </div>
      
      <div className="h-[280px]">
        <ResponsiveContainer width="100%" height="100%">
          <RechartsPieChart>
            <Pie
              data={data}
              cx="50%"
              cy="50%"
              innerRadius={innerRadius}
              outerRadius={90}
              paddingAngle={2}
              dataKey="value"
              stroke="oklch(0.15 0.008 260)"
              strokeWidth={2}
            >
              {data.map((_, index) => (
                <Cell 
                  key={`cell-${index}`} 
                  fill={CHART_COLORS[index % CHART_COLORS.length]}
                />
              ))}
            </Pie>
            <Tooltip content={<CustomTooltip valuePrefix={valuePrefix} valueSuffix={valueSuffix} />} />
            {showLegend && (
              <Legend
                layout="vertical"
                align="right"
                verticalAlign="middle"
                formatter={(value, entry) => {
                  const item = data.find(d => d.name === value)
                  const percent = item ? ((item.value / total) * 100).toFixed(1) : 0
                  return (
                    <span className="text-[11px] text-muted-foreground">
                      {value} <span className="text-foreground font-medium">({percent}%)</span>
                    </span>
                  )
                }}
              />
            )}
          </RechartsPieChart>
        </ResponsiveContainer>
      </div>
    </Card>
  )
}

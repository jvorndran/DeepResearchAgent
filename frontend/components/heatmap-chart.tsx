"use client"

import { Card } from "@/components/ui/card"
import { cn } from "@/lib/utils"

export interface HeatmapData {
  row: string
  col: string
  value: number
}

export interface HeatmapChartProps {
  title: string
  subtitle?: string
  data: HeatmapData[]
  rows: string[]
  cols: string[]
  minColor?: string
  maxColor?: string
  valuePrefix?: string
  valueSuffix?: string
  minLabel?: string
  maxLabel?: string
}

function getIntensity(value: number, min: number, max: number): number {
  if (max === min) return 0.5
  return (value - min) / (max - min)
}

function interpolateColor(t: number, from: [number,number,number], to: [number,number,number]): string {
  const r = Math.round(from[0] + (to[0] - from[0]) * t)
  const g = Math.round(from[1] + (to[1] - from[1]) * t)
  const b = Math.round(from[2] + (to[2] - from[2]) * t)
  return `rgb(${r},${g},${b})`
}

export function HeatmapChart({
  title,
  subtitle,
  data,
  rows,
  cols,
  valuePrefix = "",
  valueSuffix = "",
  minLabel = "Low",
  maxLabel = "High",
}: HeatmapChartProps) {
  const values = data.map(d => d.value)
  const min = Math.min(...values)
  const max = Math.max(...values)

  // Deep charcoal → amber-gold palette matching the design system
  const coldRgb: [number,number,number] = [30, 32, 48]
  const warmRgb: [number,number,number] = [198, 152, 76]

  function getCellValue(row: string, col: string): number | null {
    const cell = data.find(d => d.row === row && d.col === col)
    return cell ? cell.value : null
  }

  return (
    <Card className="border-border/50 bg-card/50 p-5">
      <div className="mb-4">
        <h3 className="text-sm font-semibold tracking-tight text-foreground">{title}</h3>
        {subtitle && <p className="mt-0.5 text-xs text-muted-foreground">{subtitle}</p>}
      </div>

      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-xs">
          <thead>
            <tr>
              <th className="pb-2 pr-3 text-left text-[10px] font-medium text-muted-foreground" />
              {cols.map(col => (
                <th
                  key={col}
                  className="pb-2 px-1 text-center text-[10px] font-medium text-muted-foreground max-w-[52px] truncate"
                >
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map(row => (
              <tr key={row}>
                <td className="pr-3 py-0.5 text-[10px] font-medium text-muted-foreground whitespace-nowrap">
                  {row}
                </td>
                {cols.map(col => {
                  const val = getCellValue(row, col)
                  if (val === null) {
                    return (
                      <td key={col} className="py-0.5 px-1">
                        <div className="mx-auto h-8 w-full min-w-[40px] max-w-[52px] rounded-sm bg-muted/20" />
                      </td>
                    )
                  }
                  const t = getIntensity(val, min, max)
                  const bg = interpolateColor(t, coldRgb, warmRgb)
                  const textColor = t > 0.55 ? "text-[#1a1c2e]" : "text-foreground/70"
                  return (
                    <td key={col} className="py-0.5 px-1">
                      <div
                        className={cn(
                          "mx-auto flex h-8 w-full min-w-[40px] max-w-[52px] items-center justify-center rounded-sm font-mono text-[10px] font-semibold transition-all duration-200 hover:scale-105 hover:z-10 relative",
                          textColor
                        )}
                        style={{ background: bg }}
                        title={`${row} / ${col}: ${valuePrefix}${val}${valueSuffix}`}
                      >
                        {val > 0 ? "+" : ""}{val}
                      </div>
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Legend */}
      <div className="mt-4 flex items-center gap-3">
        <span className="text-[10px] text-muted-foreground">{minLabel}</span>
        <div
          className="h-2 flex-1 rounded-full"
          style={{
            background: `linear-gradient(to right, rgb(${coldRgb.join(",")}), rgb(${warmRgb.join(",")}))`
          }}
        />
        <span className="text-[10px] text-muted-foreground">{maxLabel}</span>
      </div>
    </Card>
  )
}

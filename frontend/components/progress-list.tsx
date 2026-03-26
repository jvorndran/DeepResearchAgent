"use client"

import { Card } from "@/components/ui/card"
import { cn } from "@/lib/utils"

export interface ProgressListItem {
  label: string
  value: number
  maxValue?: number
  displayValue?: string
  sublabel?: string
  color?: "primary" | "amber" | "rose" | "sky" | "emerald"
}

export interface ProgressListProps {
  title: string
  subtitle?: string
  items: ProgressListItem[]
  unit?: string
  showRank?: boolean
}

const colorMap: Record<string, string> = {
  primary: "bg-primary",
  amber:   "bg-amber-400",
  rose:    "bg-rose-500",
  sky:     "bg-sky-400",
  emerald: "bg-emerald-400",
}

const glowMap: Record<string, string> = {
  primary: "shadow-[0_0_6px_1px_var(--color-primary)]",
  amber:   "shadow-[0_0_6px_1px_theme(colors.amber.400)]",
  rose:    "shadow-[0_0_6px_1px_theme(colors.rose.500)]",
  sky:     "shadow-[0_0_6px_1px_theme(colors.sky.400)]",
  emerald: "shadow-[0_0_6px_1px_theme(colors.emerald.400)]",
}

export function ProgressList({ title, subtitle, items, unit = "", showRank = true }: ProgressListProps) {
  const maxVal = Math.max(...items.map(i => i.maxValue ?? i.value))

  return (
    <Card className="border-border/50 bg-card/50 p-5">
      <div className="mb-4">
        <h3 className="text-sm font-semibold tracking-tight text-foreground">{title}</h3>
        {subtitle && <p className="mt-0.5 text-xs text-muted-foreground">{subtitle}</p>}
      </div>

      <div className="space-y-3">
        {items.map((item, index) => {
          const pct = ((item.value) / (item.maxValue ?? maxVal)) * 100
          const color = item.color ?? "primary"
          const display = item.displayValue ?? `${item.value.toLocaleString()}${unit}`

          return (
            <div key={index} className="group">
              <div className="mb-1.5 flex items-center gap-2">
                {showRank && (
                  <span className="w-4 shrink-0 text-right text-[10px] font-mono font-bold text-muted-foreground">
                    {index + 1}
                  </span>
                )}
                <span className="min-w-0 flex-1 truncate text-xs font-medium text-foreground">
                  {item.label}
                </span>
                {item.sublabel && (
                  <span className="shrink-0 text-[10px] text-muted-foreground">{item.sublabel}</span>
                )}
                <span className={cn(
                  "shrink-0 font-mono text-xs font-semibold",
                  color === "primary" ? "text-primary" :
                  color === "amber" ? "text-amber-400" :
                  color === "rose" ? "text-rose-400" :
                  color === "sky" ? "text-sky-400" : "text-emerald-400"
                )}>
                  {display}
                </span>
              </div>
              <div className={cn("relative h-1.5 overflow-hidden rounded-full bg-muted/40", showRank && "ml-6")}>
                <div
                  className={cn(
                    "h-full rounded-full transition-all duration-700",
                    colorMap[color],
                    glowMap[color]
                  )}
                  style={{ width: `${Math.max(pct, 2)}%` }}
                />
              </div>
            </div>
          )
        })}
      </div>
    </Card>
  )
}

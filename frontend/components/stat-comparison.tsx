"use client"

import { Card } from "@/components/ui/card"
import { cn } from "@/lib/utils"

export interface ComparisonEntity {
  name: string
  badge?: string
  stats: {
    label: string
    value: string | number
    unit?: string
    highlight?: boolean
  }[]
}

export interface StatComparisonProps {
  title: string
  subtitle?: string
  entities: ComparisonEntity[]
}

export function StatComparison({ title, subtitle, entities }: StatComparisonProps) {
  return (
    <Card className="border-border/50 bg-card/50 p-5">
      <div className="mb-4">
        <h3 className="text-sm font-semibold tracking-tight text-foreground">{title}</h3>
        {subtitle && <p className="mt-0.5 text-xs text-muted-foreground">{subtitle}</p>}
      </div>

      <div className={cn(
        "grid gap-3",
        entities.length === 2 ? "grid-cols-2" :
        entities.length === 3 ? "grid-cols-3" :
        "grid-cols-2"
      )}>
        {entities.map((entity, index) => (
          <div
            key={index}
            className={cn(
              "rounded-lg border bg-muted/20 p-3",
              index === 0 ? "border-primary/30" : "border-border/40"
            )}
          >
            <div className="mb-3 flex items-start justify-between gap-2">
              <p className={cn(
                "text-xs font-semibold leading-tight",
                index === 0 ? "text-primary" : "text-foreground"
              )}>
                {entity.name}
              </p>
              {entity.badge && (
                <span className={cn(
                  "shrink-0 rounded-sm border px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-widest",
                  index === 0
                    ? "border-primary/30 bg-primary/10 text-primary"
                    : "border-border bg-muted text-muted-foreground"
                )}>
                  {entity.badge}
                </span>
              )}
            </div>
            <div className="space-y-2.5">
              {entity.stats.map((stat, si) => (
                <div key={si} className="flex flex-col gap-0.5">
                  <p className="text-[9px] font-semibold uppercase tracking-widest text-muted-foreground">
                    {stat.label}
                  </p>
                  <p className={cn(
                    "font-mono text-sm font-bold",
                    stat.highlight
                      ? (index === 0 ? "text-primary" : "text-amber-400")
                      : "text-foreground"
                  )}>
                    {typeof stat.value === "number" ? stat.value.toLocaleString() : stat.value}
                    {stat.unit && (
                      <span className="ml-0.5 text-[10px] font-normal text-muted-foreground">
                        {stat.unit}
                      </span>
                    )}
                  </p>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </Card>
  )
}

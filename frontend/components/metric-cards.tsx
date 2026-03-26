"use client"

import { Card } from "@/components/ui/card"
import { TrendingUp, TrendingDown, Minus } from "lucide-react"
import { cn } from "@/lib/utils"

export interface MetricData {
  label: string
  value: string | number
  change?: number
  changeLabel?: string
  prefix?: string
  suffix?: string
}

export interface MetricCardsProps {
  metrics: MetricData[]
  title?: string
}

export function MetricCards({ metrics, title }: MetricCardsProps) {
  return (
    <div>
      {title && (
        <h3 className="mb-3 text-base font-semibold tracking-tight text-foreground">
          {title}
        </h3>
      )}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {metrics.map((metric, index) => {
          const isPositive = metric.change && metric.change > 0
          const isNegative = metric.change && metric.change < 0
          const isNeutral = metric.change === 0
          
          return (
            <Card 
              key={index}
              className="border-border/50 bg-card/50 p-4"
            >
              <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                {metric.label}
              </p>
              <p className="mt-1 text-2xl font-bold tracking-tight text-foreground">
                {metric.prefix || ""}
                {typeof metric.value === "number" 
                  ? metric.value.toLocaleString() 
                  : metric.value}
                {metric.suffix || ""}
              </p>
              {metric.change !== undefined && (
                <div className="mt-2 flex items-center gap-1.5">
                  <span className={cn(
                    "inline-flex items-center gap-0.5 text-xs font-medium",
                    isPositive && "text-emerald-400",
                    isNegative && "text-rose-400",
                    isNeutral && "text-muted-foreground"
                  )}>
                    {isPositive ? (
                      <TrendingUp className="h-3 w-3" />
                    ) : isNeutral ? (
                      <Minus className="h-3 w-3" />
                    ) : (
                      <TrendingDown className="h-3 w-3" />
                    )}
                    {isPositive ? "+" : ""}{metric.change.toFixed(1)}%
                  </span>
                  {metric.changeLabel && (
                    <span className="text-[10px] text-muted-foreground">
                      {metric.changeLabel}
                    </span>
                  )}
                </div>
              )}
            </Card>
          )
        })}
      </div>
    </div>
  )
}

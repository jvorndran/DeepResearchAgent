"use client"

import { Card } from "@/components/ui/card"
import { cn } from "@/lib/utils"

export type NumberedListVariant = "findings" | "risks" | "recommendations" | "steps"

export interface NumberedListItem {
  title: string
  description?: string
  tag?: string
  severity?: "high" | "medium" | "low"
}

export interface NumberedListProps {
  title: string
  subtitle?: string
  items: NumberedListItem[]
  variant?: NumberedListVariant
}

const variantConfig: Record<NumberedListVariant, {
  indexBg: string
  indexText: string
  tagColor: string
  accentBar: string
}> = {
  findings: {
    indexBg: "bg-primary/15",
    indexText: "text-primary",
    tagColor: "bg-primary/10 text-primary border-primary/25",
    accentBar: "bg-primary/30",
  },
  risks: {
    indexBg: "bg-rose-500/15",
    indexText: "text-rose-400",
    tagColor: "bg-rose-500/10 text-rose-400 border-rose-500/25",
    accentBar: "bg-rose-500/30",
  },
  recommendations: {
    indexBg: "bg-emerald-500/15",
    indexText: "text-emerald-400",
    tagColor: "bg-emerald-500/10 text-emerald-400 border-emerald-500/25",
    accentBar: "bg-emerald-500/30",
  },
  steps: {
    indexBg: "bg-amber-400/15",
    indexText: "text-amber-400",
    tagColor: "bg-amber-400/10 text-amber-400 border-amber-400/25",
    accentBar: "bg-amber-400/30",
  },
}

const severityStyles: Record<string, string> = {
  high:   "bg-rose-500/10 text-rose-400 border-rose-500/30",
  medium: "bg-amber-400/10 text-amber-400 border-amber-400/30",
  low:    "bg-sky-400/10 text-sky-400 border-sky-400/30",
}

export function NumberedList({ title, subtitle, items, variant = "findings" }: NumberedListProps) {
  const styles = variantConfig[variant]

  return (
    <Card className="border-border/50 bg-card/50 p-5">
      <div className="mb-4">
        <h3 className="text-sm font-semibold tracking-tight text-foreground">{title}</h3>
        {subtitle && <p className="mt-0.5 text-xs text-muted-foreground">{subtitle}</p>}
      </div>

      <div className="space-y-2.5">
        {items.map((item, index) => (
          <div
            key={index}
            className="flex gap-3 rounded-md border border-border/30 bg-muted/20 p-3 transition-colors hover:border-border/50 hover:bg-muted/30"
          >
            {/* Index badge */}
            <div className={cn(
              "mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-sm text-[10px] font-bold",
              styles.indexBg, styles.indexText
            )}>
              {index + 1}
            </div>

            {/* Content */}
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-start gap-2">
                <p className="flex-1 text-xs font-semibold text-foreground leading-snug">
                  {item.title}
                </p>
                {item.severity && (
                  <span className={cn(
                    "shrink-0 rounded-sm border px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-widest",
                    severityStyles[item.severity]
                  )}>
                    {item.severity}
                  </span>
                )}
                {item.tag && !item.severity && (
                  <span className={cn(
                    "shrink-0 rounded-sm border px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-widest",
                    styles.tagColor
                  )}>
                    {item.tag}
                  </span>
                )}
              </div>
              {item.description && (
                <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
                  {item.description}
                </p>
              )}
            </div>
          </div>
        ))}
      </div>
    </Card>
  )
}

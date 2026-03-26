"use client"

import { Card } from "@/components/ui/card"
import { cn } from "@/lib/utils"

export type TimelineEventType = "milestone" | "risk" | "decision" | "data" | "neutral"

export interface TimelineEvent {
  date: string
  title: string
  description?: string
  type?: TimelineEventType
  badge?: string
}

export interface TimelineProps {
  title: string
  subtitle?: string
  events: TimelineEvent[]
}

const typeConfig: Record<TimelineEventType, { dot: string; badge: string; border: string }> = {
  milestone: {
    dot: "bg-primary shadow-[0_0_8px_2px_var(--color-primary)]",
    badge: "bg-primary/15 text-primary border-primary/30",
    border: "border-l-primary/40",
  },
  risk: {
    dot: "bg-rose-500 shadow-[0_0_8px_2px_theme(colors.rose.500)]",
    badge: "bg-rose-500/15 text-rose-400 border-rose-500/30",
    border: "border-l-rose-500/40",
  },
  decision: {
    dot: "bg-amber-400 shadow-[0_0_8px_2px_theme(colors.amber.400)]",
    badge: "bg-amber-400/15 text-amber-400 border-amber-400/30",
    border: "border-l-amber-400/40",
  },
  data: {
    dot: "bg-sky-400 shadow-[0_0_8px_2px_theme(colors.sky.400)]",
    badge: "bg-sky-400/15 text-sky-400 border-sky-400/30",
    border: "border-l-sky-400/40",
  },
  neutral: {
    dot: "bg-muted-foreground",
    badge: "bg-muted text-muted-foreground border-border",
    border: "border-l-border",
  },
}

export function Timeline({ title, subtitle, events }: TimelineProps) {
  return (
    <Card className="border-border/50 bg-card/50 p-5">
      <div className="mb-5">
        <h3 className="text-sm font-semibold tracking-tight text-foreground">{title}</h3>
        {subtitle && <p className="mt-0.5 text-xs text-muted-foreground">{subtitle}</p>}
      </div>

      <div className="relative space-y-0">
        {events.map((event, index) => {
          const type = event.type ?? "neutral"
          const styles = typeConfig[type]
          const isLast = index === events.length - 1

          return (
            <div key={index} className="relative flex gap-4">
              {/* Spine line + dot */}
              <div className="relative flex flex-col items-center">
                <div className={cn(
                  "relative z-10 mt-1 h-2.5 w-2.5 shrink-0 rounded-full",
                  styles.dot
                )} />
                {!isLast && (
                  <div className="mt-1 w-px flex-1 bg-border/40 min-h-[28px]" />
                )}
              </div>

              {/* Content */}
              <div className={cn(
                "mb-6 min-w-0 flex-1 rounded-md border-l-2 bg-muted/20 px-3 py-2.5",
                styles.border
              )}>
                <div className="flex flex-wrap items-start gap-2">
                  <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                    <p className="text-xs font-semibold text-foreground leading-snug">{event.title}</p>
                    <p className="text-[10px] text-muted-foreground">{event.date}</p>
                  </div>
                  {(event.badge ?? event.type) && (
                    <span className={cn(
                      "shrink-0 rounded-sm border px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-widest",
                      styles.badge
                    )}>
                      {event.badge ?? event.type}
                    </span>
                  )}
                </div>
                {event.description && (
                  <p className="mt-1.5 text-[11px] leading-relaxed text-muted-foreground">
                    {event.description}
                  </p>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </Card>
  )
}

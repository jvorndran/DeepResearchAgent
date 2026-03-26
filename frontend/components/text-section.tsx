"use client"

import { Card } from "@/components/ui/card"
import { cn } from "@/lib/utils"

export interface TextSectionProps {
  title: string
  children: React.ReactNode
  variant?: "default" | "highlight" | "warning"
}

export function TextSection({ title, children, variant = "default" }: TextSectionProps) {
  return (
    <Card className={cn(
      "border-border/50 p-5",
      variant === "default" && "bg-card/50",
      variant === "highlight" && "border-primary/30 bg-primary/5",
      variant === "warning" && "border-amber-500/30 bg-amber-500/5"
    )}>
      <h3 className={cn(
        "mb-3 text-base font-semibold tracking-tight",
        variant === "highlight" && "text-primary",
        variant === "warning" && "text-amber-400",
        variant === "default" && "text-foreground"
      )}>
        {title}
      </h3>
      <div className="prose prose-sm prose-invert max-w-none">
        {children}
      </div>
    </Card>
  )
}

export interface QuoteBlockProps {
  quote: string
  source: string
  role?: string
}

export function QuoteBlock({ quote, source, role }: QuoteBlockProps) {
  return (
    <Card className="border-l-4 border-l-primary border-border/50 bg-card/50 p-5">
      <blockquote className="text-sm italic leading-relaxed text-muted-foreground">
        &ldquo;{quote}&rdquo;
      </blockquote>
      <div className="mt-3">
        <p className="text-xs font-medium text-foreground">{source}</p>
        {role && <p className="text-[10px] text-muted-foreground">{role}</p>}
      </div>
    </Card>
  )
}

export interface CalloutProps {
  type: "insight" | "risk" | "recommendation"
  title: string
  children: React.ReactNode
}

export function Callout({ type, title, children }: CalloutProps) {
  const typeStyles = {
    insight: "border-primary/40 bg-primary/10 text-primary",
    risk: "border-rose-500/40 bg-rose-500/10 text-rose-400",
    recommendation: "border-emerald-500/40 bg-emerald-500/10 text-emerald-400"
  }
  
  const labels = {
    insight: "Key Insight",
    risk: "Risk Factor",
    recommendation: "Recommendation"
  }
  
  return (
    <Card className={cn("border p-5", typeStyles[type])}>
      <div className="mb-2 text-[10px] font-bold uppercase tracking-widest opacity-80">
        {labels[type]}
      </div>
      <h4 className="mb-2 text-sm font-semibold text-foreground">{title}</h4>
      <div className="text-sm leading-relaxed text-muted-foreground">
        {children}
      </div>
    </Card>
  )
}

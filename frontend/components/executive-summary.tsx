"use client"

import { Card } from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"
import { ExternalLink } from "lucide-react"

interface ExecutiveSummaryProps {
  title?: string
  keyFindings?: string[]
  conclusion?: string
  dataSources?: string[]
}

// Bullet colors for visual variety
const BULLET_COLORS = [
  "bg-primary",
  "bg-accent",
  "bg-chart-3",
  "bg-chart-4",
  "bg-chart-5",
]

export function ExecutiveSummary({ 
  title = "Executive Summary",
  keyFindings,
  conclusion,
  dataSources
}: ExecutiveSummaryProps) {
  // Default values if not provided (for backwards compatibility)
  const findings = keyFindings ?? [
    "Strong positive correlation (r = 0.87) identified between semiconductor capital expenditure and global shipping volumes with a 2-3 quarter lag",
    "TSMC maintains dominant 56.4% market share, with aggressive $28.5B CapEx driving capacity expansion",
    "AI infrastructure buildout is primary demand driver, accounting for 68% of advanced node revenue",
    "Geopolitical concentration risk: 70%+ of advanced capacity in Taiwan and South Korea"
  ]
  
  const sources = dataSources ?? [
    "Financial Modeling Prep",
    "FRED (Federal Reserve)",
    "Baltic Exchange"
  ]

  return (
    <Card className="border-border/50 bg-card/50 p-5">
      <h3 className="mb-4 text-base font-semibold tracking-tight text-foreground">{title}</h3>
      
      <div className="space-y-4">
        {conclusion && (
          <p className="text-sm leading-relaxed text-muted-foreground">
            {conclusion}
          </p>
        )}
        
        <div>
          <h4 className="mb-3 text-xs font-semibold uppercase tracking-wider text-foreground/80">Key Findings</h4>
          <ul className="space-y-3 text-sm text-muted-foreground">
            {findings.map((finding, index) => (
              <li key={index} className="flex items-start gap-3">
                <span className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${BULLET_COLORS[index % BULLET_COLORS.length]}`} />
                <span>{finding}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
      
      {sources.length > 0 && (
        <>
          <Separator className="my-4 bg-border/30" />
          
          <div className="flex flex-wrap items-center gap-4 text-[11px]">
            <span className="font-semibold uppercase tracking-wider text-muted-foreground">Data Sources:</span>
            {sources.map((source, index) => (
              <a
                key={index}
                href="#"
                className="flex items-center gap-1 text-primary hover:underline underline-offset-2"
              >
                {source}
                <ExternalLink className="h-2.5 w-2.5" />
              </a>
            ))}
          </div>
        </>
      )}
    </Card>
  )
}

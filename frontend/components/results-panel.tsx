"use client"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar"
import { Separator } from "@/components/ui/separator"
import { ReportRenderer } from "./report-renderer"
import { createSampleReport, type ReportSchema } from "@/lib/report-schema"
import { Download, Share2 } from "lucide-react"
import { cn } from "@/lib/utils"

interface ResultsPanelProps {
  report?: ReportSchema
  className?: string
}

export function ResultsPanel({ report, className }: ResultsPanelProps) {
  // Use provided report or fall back to sample
  const reportData = report ?? createSampleReport()
  const { metadata } = reportData
  
  const handleExport = () => {
    // In a real app, this would generate PDF/export
    alert("Export functionality would generate a PDF report")
  }

  const statusColors = {
    pending: "border-muted-foreground/30 bg-muted/50 text-muted-foreground",
    running: "border-chart-3/30 bg-chart-3/10 text-chart-3",
    completed: "border-primary/30 bg-primary/10 text-primary",
    error: "border-destructive/30 bg-destructive/10 text-destructive"
  }

  return (
    <div className={cn("flex min-h-0 w-full flex-1 flex-col bg-background", className)}>
      {/* Header */}
      <div className="flex flex-shrink-0 items-center justify-between border-b border-border/50 px-6 py-4">
        <div className="flex items-center gap-4">
          <div>
            <h1 className="text-base font-semibold tracking-tight text-foreground">
              {metadata.title}
            </h1>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {metadata.id} &middot; {new Date(metadata.createdAt).toLocaleDateString("en-US", { 
                year: "numeric", 
                month: "short", 
                day: "numeric" 
              })}
            </p>
          </div>
          <Badge 
            variant="outline" 
            className={`text-[10px] uppercase tracking-wider font-medium ${statusColors[metadata.status]}`}
          >
            {metadata.status}
          </Badge>
        </div>
        
        <div className="flex items-center gap-3">
          <Button 
            variant="outline" 
            size="sm" 
            className="h-8 gap-2 border-border/50 bg-secondary/50 text-xs hover:bg-secondary"
            onClick={handleExport}
          >
            <Download className="h-3.5 w-3.5" />
            Export Report
          </Button>
          <Button 
            variant="ghost" 
            size="sm" 
            className="h-8 w-8 p-0 text-muted-foreground hover:text-foreground"
          >
            <Share2 className="h-4 w-4" />
          </Button>
          {metadata.author && (
            <>
              <Separator orientation="vertical" className="h-6 bg-border/50" />
              <div className="flex items-center gap-2">
                <div className="text-right">
                  <p className="text-xs font-medium text-foreground">{metadata.author.name}</p>
                  {metadata.author.role && (
                    <p className="text-[10px] text-muted-foreground">{metadata.author.role}</p>
                  )}
                </div>
                <Avatar className="h-8 w-8 border border-border/50">
                  <AvatarImage src={metadata.author.avatar || "/placeholder-avatar.jpg"} alt={metadata.author.name} />
                  <AvatarFallback className="bg-secondary text-secondary-foreground text-xs">
                    {metadata.author.name.split(" ").map(n => n[0]).join("")}
                  </AvatarFallback>
                </Avatar>
              </div>
            </>
          )}
        </div>
      </div>
      
      {/* Scrollable Content - Uses schema-driven renderer */}
      <div className="flex-1 overflow-y-auto">
        <div className="p-6">
          <ReportRenderer report={reportData} />
        </div>
      </div>
    </div>
  )
}

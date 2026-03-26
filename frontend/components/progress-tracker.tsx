"use client"

import { Card } from "@/components/ui/card"
import { Database, FileCode, Terminal, FileText, Check } from "lucide-react"

interface Step {
  id: number
  label: string
  description: string
  icon: React.ElementType
  status: "completed" | "in-progress" | "pending"
}

const steps: Step[] = [
  {
    id: 1,
    label: "Data Collection",
    description: "FMP / FRED APIs",
    icon: Database,
    status: "completed"
  },
  {
    id: 2,
    label: "Schema Extraction",
    description: "Data Structure",
    icon: FileCode,
    status: "completed"
  },
  {
    id: 3,
    label: "Analysis",
    description: "Python Sandbox",
    icon: Terminal,
    status: "completed"
  },
  {
    id: 4,
    label: "Synthesis",
    description: "Report Generation",
    icon: FileText,
    status: "completed"
  }
]

export function ProgressTracker() {
  return (
    <Card className="border-border/50 bg-card/50 p-4">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
          Workflow Progress
        </h3>
        <span className="text-[10px] font-mono text-primary/80">LangGraph</span>
      </div>
      
      <div className="flex items-center">
        {steps.map((step, index) => (
          <div key={step.id} className="flex flex-1 items-center">
            <div className="flex flex-col items-center">
              <div
                className={`relative flex h-9 w-9 items-center justify-center rounded-md ${
                  step.status === "completed"
                    ? "bg-primary/15 ring-1 ring-primary/30"
                    : step.status === "in-progress"
                    ? "bg-primary/20 ring-1 ring-primary/50"
                    : "bg-secondary ring-1 ring-border/50"
                }`}
              >
                <step.icon
                  className={`h-4 w-4 ${
                    step.status === "completed"
                      ? "text-primary"
                      : step.status === "in-progress"
                      ? "text-primary"
                      : "text-muted-foreground"
                  }`}
                />
                {step.status === "completed" && (
                  <div className="absolute -right-0.5 -top-0.5 flex h-3.5 w-3.5 items-center justify-center rounded-full bg-primary">
                    <Check className="h-2 w-2 text-primary-foreground" />
                  </div>
                )}
              </div>
              <div className="mt-2 text-center">
                <p className="text-[11px] font-medium text-foreground">{step.label}</p>
                <p className="mt-0.5 text-[9px] text-muted-foreground">{step.description}</p>
              </div>
            </div>
            
            {index < steps.length - 1 && (
              <div className="mx-3 h-px flex-1 bg-gradient-to-r from-primary/40 via-primary/20 to-transparent" />
            )}
          </div>
        ))}
      </div>
    </Card>
  )
}

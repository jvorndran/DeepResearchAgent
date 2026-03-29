"use client"

import { useEffect, useMemo } from "react"
import {
  WorkflowVisualizer,
  createGeneratingWorkflowState,
} from "@/components/workflow-visualizer"
import { Loader2 } from "lucide-react"

interface GenerationLoadingProps {
  /** Called when the demo pipeline finishes (replace with real SSE/job later). */
  onComplete: () => void
  /** Simulated duration in ms before `onComplete`. */
  durationMs?: number
}

export function GenerationLoading({
  onComplete,
}: GenerationLoadingProps) {
  const workflow = useMemo(() => createGeneratingWorkflowState(), [])

  return (
    <div className="flex h-full w-full flex-col overflow-auto bg-background">
      <div className="mx-auto flex w-full max-w-3xl flex-col items-center px-4 py-10 text-center">
        <div className="mb-2 flex items-center justify-center gap-2 text-lg font-semibold text-foreground">
          <Loader2 className="h-5 w-5 animate-spin text-primary" />
          Generating your report
        </div>
        <p className="max-w-lg text-sm text-muted-foreground">
          The orchestrator is running sub-agents and tools. This screen replaces
          chat until the report is ready.
        </p>
      </div>
      <div className="mx-auto w-full max-w-4xl flex-1 px-4 pb-10">
        <WorkflowVisualizer workflow={workflow} />
      </div>
    </div>
  )
}

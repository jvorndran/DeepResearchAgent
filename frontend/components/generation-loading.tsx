"use client"

import { useMemo } from "react"
import {
  WorkflowVisualizer,
  createGeneratingWorkflowState,
} from "@/components/workflow-visualizer"
import { Loader2, AlertTriangle } from "lucide-react"

interface GenerationLoadingProps {
  /** Called when the pipeline finishes. */
  onComplete: () => void
  /** Non-null when the stream has errored (may self-recover via SDK retry). */
  errorMessage?: string | null
}

export function GenerationLoading({
  onComplete,
  errorMessage,
}: GenerationLoadingProps) {
  const workflow = useMemo(() => createGeneratingWorkflowState(), [])

  return (
    <div data-testid="generation-loading" className="flex h-full w-full flex-col overflow-auto bg-background">
      <div className="mx-auto flex w-full max-w-3xl flex-col items-center px-4 py-10 text-center">
        {errorMessage ? (
          <div className="mb-2 flex items-center justify-center gap-2 text-lg font-semibold text-destructive">
            <AlertTriangle className="h-5 w-5" />
            {errorMessage}
          </div>
        ) : (
          <div className="mb-2 flex items-center justify-center gap-2 text-lg font-semibold text-foreground">
            <Loader2 className="h-5 w-5 animate-spin text-primary" />
            Generating your report
          </div>
        )}
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

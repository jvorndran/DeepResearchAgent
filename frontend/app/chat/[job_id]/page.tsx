"use client";

import { use, useState } from "react";
import { useResearchStream } from "@/hooks/use-research-stream";
import AppHeader from "@/components/app-header";
import StreamingView from "@/components/streaming-view";
import ReportView from "@/components/report-view";
import ErrorView from "@/components/error-view";
import type { Message } from "@/lib/types";

export default function ChatPage({ params }: { params: Promise<{ job_id: string }> }) {
  const { job_id } = use(params);

  const [messages] = useState<Message[]>(() => {
    if (typeof window === "undefined") return [];
    const stored = sessionStorage.getItem("pending_messages");
    sessionStorage.removeItem("pending_messages");
    return stored ? (JSON.parse(stored) as Message[]) : [];
  });

  const { status, orchestratorText, pipelineSteps, report, errorText } = useResearchStream({
    jobId: job_id,
    messages,
  });

  return (
    <div className="flex flex-col min-h-screen bg-background">
      <AppHeader showNewResearch />
      <main className="flex-1 flex flex-col relative">
        {(status === "idle" || status === "loading") && (
          <div className="flex flex-1 items-center justify-center text-muted-foreground text-sm font-mono animate-pulse">
            Loading report…
          </div>
        )}
        {status === "streaming" && (
          <StreamingView orchestratorText={orchestratorText} pipelineSteps={pipelineSteps} />
        )}
        {status === "report_ready" && report && (
          <ReportView report={report} />
        )}
        {(status === "failed" || status === "error") && (
          <ErrorView status={status} errorText={errorText} />
        )}
      </main>
    </div>
  );
}

"use client";

import { useState } from "react";
import { useResearchStream } from "@/hooks/use-research-stream";
import AppHeader from "@/components/app-header";
import StreamingView from "@/components/streaming-view";
import ReportView from "@/components/report-view";
import ErrorView from "@/components/error-view";
import type { Message } from "@/lib/types";

export default function ChatPageClient({ jobId }: { jobId: string }) {
  const [messages] = useState<Message[]>(() => {
    if (typeof window === "undefined") return [];
    const stored = sessionStorage.getItem("pending_messages");
    sessionStorage.removeItem("pending_messages");
    return stored ? (JSON.parse(stored) as Message[]) : [];
  });

  const { status, orchestratorText, report, errorText } = useResearchStream({
    jobId,
    messages,
  });

  return (
    <div className="flex flex-col min-h-screen bg-background">
      <AppHeader showNewResearch />
      <main className="flex-1 flex flex-col relative">
        {(status === "idle" || status === "loading") && (
          <div className="flex flex-1 items-center justify-center text-muted-foreground text-sm font-mono animate-pulse">
            Loading report...
          </div>
        )}
        {status === "streaming" && (
          <StreamingView orchestratorText={orchestratorText} />
        )}
        {status === "report_ready" && report && <ReportView report={report} />}
        {(status === "failed" || status === "error") && (
          <ErrorView status={status} errorText={errorText} />
        )}
      </main>
    </div>
  );
}

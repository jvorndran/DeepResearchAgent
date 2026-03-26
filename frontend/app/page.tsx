"use client"

import { useState, useCallback, useMemo } from "react"
import { SidebarInset, SidebarTrigger } from "@/components/ui/sidebar"
import { Separator } from "@/components/ui/separator"
import { AppSidebar, type ReportHistoryItem } from "@/components/app-sidebar"
import { InitialPrompt } from "@/components/initial-prompt"
import { ChatPanel, type ChatMessage } from "@/components/chat-panel"
import { GenerationLoading } from "@/components/generation-loading"
import { ResultsPanel } from "@/components/results-panel"

type Phase = "initial" | "chatting" | "generating" | "completed"

function formatNow() {
  return new Date().toLocaleTimeString("en-US", {
    hour: "numeric",
    minute: "2-digit",
  })
}

const ASSISTANT_WELCOME =
  "Thanks for the details. Ask follow-up questions to refine tickers, time range, or metrics. When you're ready, click **Begin research** to run the full agent pipeline (you'll see a progress screen, then the final report)."

const ASSISTANT_ACK =
  "Noted — I'll fold that into the plan. Anything else before we run the pipeline?"

export default function DashboardPage() {
  const [phase, setPhase] = useState<Phase>("initial")
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [reports, setReports] = useState<ReportHistoryItem[]>([
    {
      id: "sample-semis",
      title: "Semiconductor CapEx vs. shipping",
      createdAt: new Date(Date.now() - 86400000 * 3).toISOString(),
    },
  ])
  const [activeReportId, setActiveReportId] = useState<string | null>(null)
  const [sessionTitle, setSessionTitle] = useState("")

  const handleInitialSubmit = useCallback((query: string) => {
    const title =
      query.length > 48 ? `${query.slice(0, 47).trimEnd()}…` : query
    setSessionTitle(title)
    setMessages([
      { role: "user", content: query, timestamp: formatNow() },
      {
        role: "assistant",
        content: ASSISTANT_WELCOME,
        timestamp: formatNow(),
      },
    ])
    setPhase("chatting")
  }, [])

  const handleSendMessage = useCallback((text: string) => {
    setMessages((prev) => [
      ...prev,
      { role: "user", content: text, timestamp: formatNow() },
    ])
    window.setTimeout(() => {
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: ASSISTANT_ACK,
          timestamp: formatNow(),
        },
      ])
    }, 500)
  }, [])

  const handleBeginResearch = useCallback(() => {
    setPhase("generating")
  }, [])

  const handleGenerationComplete = useCallback(() => {
    const id = `report-${Date.now()}`
    const title = sessionTitle || "Latest research"
    setReports((prev) => [
      {
        id,
        title,
        createdAt: new Date().toISOString(),
      },
      ...prev,
    ])
    setActiveReportId(id)
    setPhase("completed")
  }, [sessionTitle])

  const handleNewResearch = useCallback(() => {
    setPhase("initial")
    setMessages([])
    setActiveReportId(null)
    setSessionTitle("")
  }, [])

  const handleSelectReport = useCallback((id: string) => {
    setActiveReportId(id)
    setPhase("completed")
  }, [])

  const canBeginResearch =
    messages.filter((m) => m.role === "assistant").length >= 1

  const headerTitle = useMemo(() => {
    switch (phase) {
      case "initial":
        return "Nexus Research"
      case "chatting":
        return "Refine scope"
      case "generating":
        return "Running pipeline"
      case "completed":
        return "Report"
      default:
        return "Nexus Research"
    }
  }, [phase])

  return (
    <>
      <AppSidebar
        reports={reports}
        activeReportId={activeReportId}
        onNewResearch={handleNewResearch}
        onSelectReport={handleSelectReport}
      />
      <SidebarInset className="flex h-svh flex-col overflow-hidden">
        <header className="flex h-14 shrink-0 items-center gap-2 border-b border-border/50 px-3">
          <SidebarTrigger />
          <Separator orientation="vertical" className="h-6" />
          <span className="text-sm font-medium text-foreground">
            {headerTitle}
          </span>
        </header>
        <div className="min-h-0 flex-1 overflow-hidden">
          {phase === "initial" && (
            <InitialPrompt onSubmit={handleInitialSubmit} />
          )}
          {phase === "chatting" && (
            <div className="flex h-full justify-center overflow-hidden px-2 py-4 md:px-6">
              <ChatPanel
                variant="centered"
                messages={messages}
                onSendMessage={handleSendMessage}
                onBeginResearch={handleBeginResearch}
                canBeginResearch={canBeginResearch}
              />
            </div>
          )}
          {phase === "generating" && (
            <GenerationLoading onComplete={handleGenerationComplete} />
          )}
          {phase === "completed" && (
            <ResultsPanel className="h-full min-h-0" />
          )}
        </div>
      </SidebarInset>
    </>
  )
}

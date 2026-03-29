"use client"

import { useState, useCallback, useMemo, useEffect } from "react"
import { useChat } from "@ai-sdk/react"
import { DefaultChatTransport } from "ai"
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
  const [reports, setReports] = useState<ReportHistoryItem[]>([
    {
      id: "sample-semis",
      title: "Semiconductor CapEx vs. shipping",
      createdAt: new Date(Date.now() - 86400000 * 3).toISOString(),
    },
  ])
  const [activeReportId, setActiveReportId] = useState<string | null>(null)
  const [sessionTitle, setSessionTitle] = useState("")

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

  const { messages, data, isLoading, setMessages, sendMessage } = useChat({
    transport: new DefaultChatTransport({
      api: 'http://localhost:8000/api/chat/stream'
    }),
    onFinish: () => {
      if (phase === "generating") {
        handleGenerationComplete()
      }
    }
  })

  useEffect(() => {
    if (data && data.length > 0) {
      const hasSubagentUpdate = data.some((item: any) => 
        item.type === "update" && item.ns && item.ns.length > 0 && item.ns[0].startsWith("tools:")
      )
      
      if (hasSubagentUpdate && phase === "chatting") {
        setPhase("generating")
      }
    }
  }, [data, phase])

  useEffect(() => {
    if (!isLoading && phase === "generating") {
      handleGenerationComplete()
    }
  }, [isLoading, phase, handleGenerationComplete])

  const mappedMessages = useMemo(() => {
    return messages.map((m) => {
      // Extract text from parts if available, otherwise fallback to content (for backwards compatibility)
      let textContent = "";
      if (m.parts && Array.isArray(m.parts)) {
        textContent = m.parts
          .filter((p: any) => p.type === 'text')
          .map((p: any) => p.text)
          .join('');
      } else if ('content' in m) {
        textContent = (m as any).content;
      }

      return {
        role: m.role as "user" | "assistant",
        content: textContent,
        timestamp: (m as any).createdAt ? (m as any).createdAt.toLocaleTimeString("en-US", {
          hour: "numeric",
          minute: "2-digit",
        }) : undefined,
      };
    })
  }, [messages])

  const handleInitialSubmit = useCallback(async (query: string) => {
    const title =
      query.length > 48 ? `${query.slice(0, 47).trimEnd()}…` : query
    setSessionTitle(title)
    
    setPhase("chatting")
    
    // We need to wait for the phase change to render before appending
    setTimeout(() => {
      if (sendMessage) {
        sendMessage({
          text: query
        }, {
          data: { jobId: `job_${Date.now()}` }
        } as any)
      }
    }, 50)
  }, [sendMessage])

  const handleSendMessage = useCallback((text: string) => {
    if (sendMessage) {
      sendMessage({
        text: text
      })
    }
  }, [sendMessage])

  const handleBeginResearch = useCallback(() => {
    if (sendMessage) {
      sendMessage({
        text: "I am ready. Please begin the research."
      })
    }
    setPhase("generating")
  }, [sendMessage])

  const handleNewResearch = useCallback(() => {
    setPhase("initial")
    setMessages([])
    setActiveReportId(null)
    setSessionTitle("")
  }, [setMessages])

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
                messages={mappedMessages}
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
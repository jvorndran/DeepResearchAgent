"use client"

import { useState, useCallback, useMemo, useEffect, useRef } from "react"
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
  const [hasSubagentActivity, setHasSubagentActivity] = useState(false)
  const [streamError, setStreamError] = useState<string | null>(null)
  const [initialQuery, setInitialQuery] = useState<string | null>(null)
  const completionCalledRef = useRef(false)

  const handleGenerationComplete = useCallback(() => {
    if (completionCalledRef.current) return
    completionCalledRef.current = true
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

  const { messages, status, setMessages, sendMessage } = useChat({
    transport: new DefaultChatTransport({
      api: 'http://localhost:8000/api/chat/stream'
    }),
    onData: (dataPart: any) => {
      console.log("[onData]", JSON.stringify(dataPart).slice(0, 200))
      // Auto-transition to generating when pipeline subagents start
      // dataPart is the full data-* chunk; payload is in dataPart.data
      const payload = dataPart?.data ?? dataPart
      if (payload?.type === "update" && Array.isArray(payload?.ns) && payload.ns.length > 0 && (payload.ns[0] as string).startsWith("tools:")) {
        setHasSubagentActivity(true)
      }
    },
  })

  // Debug: log status and messages changes
  useEffect(() => {
    console.log(`[chat] status=${status} phase=${phase} messages=${messages.length} hasSubagent=${hasSubagentActivity}`)
  }, [status, phase, messages.length, hasSubagentActivity])

  // Auto-transition chatting → generating when subagent pipeline starts immediately
  useEffect(() => {
    if (hasSubagentActivity && phase === "chatting") {
      setPhase("generating")
    }
  }, [hasSubagentActivity, phase])

  // Complete when stream finishes in generating phase; surface errors
  useEffect(() => {
    if (phase !== "generating") return
    if (status === "ready") {
      setStreamError(null)
      handleGenerationComplete()
    } else if (status === "error") {
      setStreamError("The pipeline encountered an error. Retrying…")
    } else {
      // Recovered from error (status back to streaming/submitted)
      setStreamError(null)
    }
  }, [status, phase, handleGenerationComplete])

  const mappedMessages = useMemo(() => {
    const result: ChatMessage[] = []
    
    // Add initial query as first message if present
    if (initialQuery && phase !== "initial") {
      result.push({
        role: "user",
        content: initialQuery,
        timestamp: formatNow(),
      })
    }
    
    // Add backend messages
    messages.forEach((m) => {
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

      result.push({
        role: m.role as "user" | "assistant",
        content: textContent,
        timestamp: (m as any).createdAt ? (m as any).createdAt.toLocaleTimeString("en-US", {
          hour: "numeric",
          minute: "2-digit",
        }) : undefined,
      });
    })
    
    return result
  }, [messages, initialQuery, phase])

  const handleInitialSubmit = useCallback(async (query: string) => {
    const title =
      query.length > 48 ? `${query.slice(0, 47).trimEnd()}…` : query
    setSessionTitle(title)
    setInitialQuery(query)
    setPhase("chatting")
  }, [])

  const handleSendMessage = useCallback((text: string) => {
    if (sendMessage) {
      sendMessage({
        text: text
      })
    }
  }, [sendMessage])

  const handleBeginResearch = useCallback(() => {
    if (sendMessage && initialQuery) {
      sendMessage({
        text: initialQuery
      }, {
        data: { jobId: `job_${Date.now()}`, beginResearch: true }
      } as any)
    }
    setPhase("generating")
  }, [sendMessage, initialQuery])

  const handleNewResearch = useCallback(() => {
    setPhase("initial")
    setMessages([])
    setActiveReportId(null)
    setSessionTitle("")
    setHasSubagentActivity(false)
    setStreamError(null)
    setInitialQuery(null)
    completionCalledRef.current = false
  }, [setMessages])

  const handleSelectReport = useCallback((id: string) => {
    setActiveReportId(id)
    setPhase("completed")
  }, [])

  const canBeginResearch = initialQuery !== null

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
                isLoading={status === "submitted" || (status === "streaming" && mappedMessages.length > 0 && mappedMessages[mappedMessages.length - 1].role === "user")}
              />
            </div>
          )}
          {phase === "generating" && (
            <GenerationLoading onComplete={handleGenerationComplete} errorMessage={streamError} />
          )}
          {phase === "completed" && (
            <ResultsPanel className="h-full min-h-0" />
          )}
        </div>
      </SidebarInset>
    </>
  )
}
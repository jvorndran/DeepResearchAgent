"use client"

import { useState, useRef, useEffect } from "react"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Button } from "@/components/ui/button"
import { Paperclip, Sparkles, User, Mic, ArrowUp, FlaskConical } from "lucide-react"
import { cn } from "@/lib/utils"

export interface ChatMessage {
  role: "user" | "assistant"
  content: string
  timestamp?: string
}

interface ChatPanelProps {
  /** `sidebar` = narrow column with border; `centered` = main-stage chat. */
  variant?: "sidebar" | "centered"
  messages: ChatMessage[]
  onSendMessage: (text: string) => void
  onBeginResearch: () => void
  /** Enable after at least one assistant turn (e.g. scope discussion). */
  canBeginResearch?: boolean
}

function MessageBubble({
  message,
  index,
}: {
  message: ChatMessage
  index: number
}) {
  const isUser = message.role === "user"

  return (
    <div
      className={`group flex gap-3 ${isUser ? "flex-row-reverse" : "flex-row"} animate-in fade-in slide-in-from-bottom-2 duration-300`}
      style={{ animationDelay: `${index * 50}ms` }}
    >
      <div
        className={`relative flex h-8 w-8 shrink-0 items-center justify-center rounded-full transition-transform duration-200 group-hover:scale-105 ${
          isUser
            ? "bg-gradient-to-br from-primary/20 to-primary/5 ring-1 ring-primary/30"
            : "bg-gradient-to-br from-accent/20 to-accent/5 ring-1 ring-accent/30"
        }`}
      >
        {isUser ? (
          <User className="h-4 w-4 text-primary/80" />
        ) : (
          <Sparkles className="h-4 w-4 text-accent" />
        )}
        {!isUser && (
          <span className="absolute -bottom-0.5 -right-0.5 h-2.5 w-2.5 rounded-full border-2 border-sidebar bg-emerald-500" />
        )}
      </div>

      <div
        className={`flex max-w-[min(100%,36rem)] flex-col gap-1 ${isUser ? "items-end" : "items-start"}`}
      >
        <div
          className={`relative overflow-hidden rounded-2xl px-4 py-2.5 text-[13px] leading-relaxed transition-all duration-200 ${
            isUser
              ? "bg-gradient-to-br from-primary to-primary/90 text-primary-foreground rounded-br-md shadow-lg shadow-primary/20"
              : "bg-gradient-to-br from-secondary/90 to-secondary/70 text-secondary-foreground rounded-bl-md ring-1 ring-border/30 backdrop-blur-sm"
          }`}
        >
          <div
            className={`absolute inset-0 bg-gradient-to-r from-transparent via-white/5 to-transparent opacity-0 transition-opacity duration-500 group-hover:opacity-100 ${isUser ? "" : "via-white/3"}`}
          />
          <p className="relative whitespace-pre-line">{message.content}</p>
        </div>

        {message.timestamp && (
          <span className="px-1 text-[10px] text-muted-foreground/60 opacity-0 transition-opacity duration-200 group-hover:opacity-100">
            {message.timestamp}
          </span>
        )}
      </div>
    </div>
  )
}

export function ChatPanel({
  variant = "sidebar",
  messages,
  onSendMessage,
  onBeginResearch,
  canBeginResearch = false,
}: ChatPanelProps) {
  const [inputValue, setInputValue] = useState("")
  const [isFocused, setIsFocused] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto"
      textareaRef.current.style.height =
        Math.min(textareaRef.current.scrollHeight, 120) + "px"
    }
  }, [inputValue])

  const send = () => {
    const t = inputValue.trim()
    if (!t) return
    onSendMessage(t)
    setInputValue("")
  }

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  const isCentered = variant === "centered"

  return (
    <div
      className={cn(
        "flex h-full w-full flex-col overflow-hidden bg-gradient-to-b from-sidebar to-sidebar/95",
        variant === "sidebar" && "border-r border-border/40",
        isCentered && "mx-auto max-w-3xl bg-transparent",
      )}
    >
      <div
        className={cn(
          "relative flex shrink-0 items-center gap-3 border-b border-border/40 px-5 py-4",
          isCentered && "rounded-t-2xl border border-b-0 border-border/40 bg-sidebar/80",
        )}
      >
        <div className="absolute inset-x-0 -bottom-px h-px bg-gradient-to-r from-transparent via-primary/20 to-transparent" />

        <div className="relative">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-primary/20 via-primary/10 to-transparent ring-1 ring-primary/20 backdrop-blur-sm">
            <Sparkles className="h-5 w-5 text-primary" />
          </div>
          <span className="absolute -bottom-0.5 -right-0.5 h-3 w-3 rounded-full border-2 border-sidebar bg-emerald-500" />
        </div>

        <div className="flex flex-col">
          <h2 className="text-sm font-semibold tracking-tight text-foreground">
            Research Assistant
          </h2>
          <div className="flex items-center gap-1.5">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-500" />
            <p className="text-[11px] text-muted-foreground">Clarifying scope</p>
          </div>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-hidden">
        <ScrollArea className="h-full w-full">
          <div
            className={cn(
              "space-y-4 px-4 py-5",
              isCentered && "px-2 sm:px-4",
            )}
          >
            {messages.map((message, index) => (
              <MessageBubble key={index} message={message} index={index} />
            ))}
          </div>
        </ScrollArea>
      </div>

      <div
        className={cn(
          "relative shrink-0 border-t border-border/40 p-4",
          isCentered &&
            "rounded-b-2xl border border-t-0 border-border/40 bg-sidebar/80",
        )}
      >
        <div className="absolute inset-x-0 -top-px h-px bg-gradient-to-r from-transparent via-border/50 to-transparent" />

        <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-[11px] text-muted-foreground">
            When scope is clear, start the full pipeline (chat hides until the
            report is ready).
          </p>
          <Button
            size="sm"
            className="shrink-0 gap-2"
            disabled={!canBeginResearch}
            onClick={onBeginResearch}
          >
            <FlaskConical className="h-4 w-4" />
            Begin research
          </Button>
        </div>

        <div
          className={`relative overflow-hidden rounded-2xl bg-gradient-to-b from-secondary/80 to-secondary/60 ring-1 transition-all duration-300 ${
            isFocused
              ? "ring-primary/50 shadow-lg shadow-primary/10"
              : "ring-border/40"
          }`}
        >
          <div
            className={`absolute inset-0 rounded-2xl bg-gradient-to-r from-primary/0 via-primary/10 to-primary/0 opacity-0 transition-opacity duration-500 ${isFocused ? "opacity-100" : ""}`}
          />

          <div className="relative flex items-end gap-2 p-2">
            <Button
              variant="ghost"
              size="icon"
              type="button"
              className="h-8 w-8 shrink-0 rounded-xl text-muted-foreground transition-all duration-200 hover:scale-105 hover:bg-muted/50 hover:text-foreground"
            >
              <Paperclip className="h-4 w-4" />
            </Button>

            <textarea
              ref={textareaRef}
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onFocus={() => setIsFocused(true)}
              onBlur={() => setIsFocused(false)}
              onKeyDown={onKeyDown}
              placeholder="Ask a follow-up question..."
              rows={1}
              className="max-h-[120px] min-h-[36px] flex-1 resize-none bg-transparent py-2 text-sm text-foreground placeholder:text-muted-foreground/60 focus:outline-none"
            />

            <Button
              variant="ghost"
              size="icon"
              type="button"
              className="h-8 w-8 shrink-0 rounded-xl text-muted-foreground transition-all duration-200 hover:scale-105 hover:bg-muted/50 hover:text-foreground"
            >
              <Mic className="h-4 w-4" />
            </Button>

            <Button
              type="button"
              size="icon"
              disabled={!inputValue.trim()}
              onClick={send}
              className={`h-9 w-9 shrink-0 rounded-xl transition-all duration-300 ${
                inputValue.trim()
                  ? "bg-gradient-to-br from-primary to-primary/80 shadow-lg shadow-primary/30 hover:scale-105 hover:shadow-primary/40"
                  : "bg-muted text-muted-foreground"
              }`}
            >
              <ArrowUp className="h-4 w-4" />
            </Button>
          </div>
        </div>

        <p className="mt-2 text-center text-[10px] text-muted-foreground/50">
          Enter to send · Shift + Enter for new line
        </p>
      </div>
    </div>
  )
}

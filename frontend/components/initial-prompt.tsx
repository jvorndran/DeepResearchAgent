"use client"

import { useState, useRef, useEffect } from "react"
import { Button } from "@/components/ui/button"
import { Sparkles, ArrowUp } from "lucide-react"

interface InitialPromptProps {
  onSubmit: (query: string) => void
}

export function InitialPrompt({ onSubmit }: InitialPromptProps) {
  const [value, setValue] = useState("")
  const [focused, setFocused] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto"
      textareaRef.current.style.height =
        Math.min(textareaRef.current.scrollHeight, 160) + "px"
    }
  }, [value])

  const handleSubmit = () => {
    const q = value.trim()
    if (!q) return
    onSubmit(q)
    setValue("")
  }

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }

  return (
    <div className="flex h-full w-full flex-col items-center justify-center px-4 py-8">
      <div className="mb-8 flex flex-col items-center gap-3 text-center">
        <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-primary/20 via-primary/10 to-transparent ring-1 ring-primary/20">
          <Sparkles className="h-7 w-7 text-primary" />
        </div>
        <h1 className="text-balance text-2xl font-semibold tracking-tight text-foreground md:text-3xl">
          What should we research?
        </h1>
        <p className="max-w-md text-balance text-sm text-muted-foreground">
          Describe your question or analysis. You&apos;ll refine scope in chat,
          then we&apos;ll run the full agent pipeline.
        </p>
      </div>

      <div className="w-full max-w-2xl">
        <div
          className={`relative overflow-hidden rounded-2xl bg-gradient-to-b from-secondary/90 to-secondary/60 p-1 ring-1 transition-all duration-300 ${
            focused
              ? "ring-primary/50 shadow-lg shadow-primary/10"
              : "ring-border/40"
          }`}
        >
          <div className="rounded-xl bg-background/80 backdrop-blur-sm">
            <textarea
              ref={textareaRef}
              value={value}
              onChange={(e) => setValue(e.target.value)}
              onFocus={() => setFocused(true)}
              onBlur={() => setFocused(false)}
              onKeyDown={onKeyDown}
              placeholder="e.g. Compare AAPL revenue growth to sector peers over the last 8 quarters…"
              rows={3}
              data-testid="initial-prompt-textarea"
              className="min-h-[100px] w-full resize-none bg-transparent px-4 py-3 text-sm text-foreground placeholder:text-muted-foreground/60 focus:outline-none"
            />
            <div className="flex items-center justify-end gap-2 border-t border-border/40 px-3 py-2">
              <Button
                size="sm"
                disabled={!value.trim()}
                className="gap-1.5 rounded-xl"
                onClick={handleSubmit}
                data-testid="initial-prompt-submit"
              >
                <span>Start</span>
                <ArrowUp className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </div>
        <p className="mt-3 text-center text-[10px] text-muted-foreground/60">
          Enter to send · Shift + Enter for new line
        </p>
      </div>
    </div>
  )
}

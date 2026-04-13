"use client";

import { useRef, useEffect } from "react";
import { ArrowRight } from "@phosphor-icons/react";
import ReactMarkdown from "react-markdown";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ScrollArea } from "@/components/ui/scroll-area";
import { usePretextHeight, useElementWidth } from "@/hooks/use-pretext";
import type { Message } from "@/lib/types";

const assistantProse =
  "prose prose-lg max-w-none dark:prose-invert prose-p:font-serif prose-p:leading-relaxed prose-p:text-foreground/90 prose-headings:font-serif prose-h3:mt-0 prose-h3:mb-3 prose-strong:text-foreground prose-ul:my-3 prose-ol:my-3 prose-li:my-1 prose-p:my-2 first:prose-p:mt-0 last:prose-p:mb-0";

function MarkdownContent({ children, className }: { children: string; className?: string }) {
  return (
    <div
      className={
        className ??
        "prose prose-lg max-w-none dark:prose-invert prose-p:font-serif prose-p:leading-relaxed prose-headings:font-serif prose-li:font-serif prose-strong:text-foreground prose-ul:my-3 prose-ol:my-3 prose-p:my-2 first:prose-p:mt-0 last:prose-p:mb-0"
      }
    >
      <ReactMarkdown>{children}</ReactMarkdown>
    </div>
  );
}

interface ChatInterfaceProps {
  messages: Message[];
  isStreamingChat: boolean;
  orchestratorText: string;
  inputValue: string;
  onInputChange: (value: string) => void;
  onSend: () => void;
  onBeginResearch: () => void;
}

export default function ChatInterface({
  messages,
  isStreamingChat,
  orchestratorText,
  inputValue,
  onInputChange,
  onSend,
  onBeginResearch,
}: ChatInterfaceProps) {
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const { ref: streamContainerRef, width: streamContainerWidth } = useElementWidth<HTMLDivElement>();

  // Pretext-powered height reservation for orchestratorText as it streams
  // Font: 18px Cormorant Garamond (assistantProse uses font-serif)
  // Line-height: 28px (approx prose-lg default)
  const streamFont = "18px 'Cormorant Garamond', serif";
  const streamLineHeight = 28;
  const streamHorizontalPadding = 32; // pl-4 = 16px, plus some buffer
  const { height: reservedStreamHeight } = usePretextHeight(
    orchestratorText,
    streamFont,
    Math.max(0, streamContainerWidth - streamHorizontalPadding),
    streamLineHeight
  );

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, orchestratorText, isStreamingChat]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      onSend();
    }
  };

  const hasMessages = messages.length > 0 || isStreamingChat;
  /** After the assistant’s first reply (e.g. clarifying questions) — not on the empty landing state. */
  const hasAssistantReply = messages.some((m) => m.role === "assistant");

  return (
    <div
      className={`flex min-h-0 flex-1 flex-col transition-all duration-700 ease-[cubic-bezier(0.2,0.8,0.2,1)] ${hasMessages ? "" : "justify-center"}`}
    >
      {hasMessages && (
        <ScrollArea className="h-full min-h-0 flex-1 overflow-hidden px-6 py-12 md:px-12 lg:px-24">
          <div className="max-w-4xl mx-auto flex flex-col gap-12 pb-8">
            {messages.map((msg, idx) => (
              <div key={idx} data-testid="message-item" data-role={msg.role} className="flex flex-col gap-2 animate-in fade-in slide-in-from-bottom-4 duration-700">
                <div className="text-xs uppercase tracking-[0.2em] text-muted-foreground font-sans">
                  {msg.role === "user" ? "Inquiry" : "Analysis"}
                </div>
                <div
                  className={`pl-4 ${msg.role === "user" ? "border-l border-primary/30 text-foreground" : "border-l-2 border-primary text-foreground/90"}`}
                >
                  <MarkdownContent
                    className={
                      msg.role === "user"
                        ? "prose prose-lg max-w-none dark:prose-invert prose-p:font-serif prose-p:leading-relaxed prose-p:text-foreground prose-headings:font-serif prose-strong:text-foreground prose-ul:my-3 prose-p:my-2 first:prose-p:mt-0"
                        : assistantProse
                    }
                  >
                    {msg.content}
                  </MarkdownContent>
                </div>
              </div>
            ))}

            {isStreamingChat && (
              <div ref={streamContainerRef} className="flex flex-col gap-2 animate-in fade-in duration-500">
                <div className="text-xs uppercase tracking-[0.2em] text-muted-foreground font-sans flex items-center gap-2">
                  <span className="w-1.5 h-1.5 bg-primary rounded-full animate-pulse"></span>
                  Processing
                </div>
                <div 
                  className="pl-4 border-l-2 border-primary/50 text-foreground/70 transition-[min-height] duration-300 ease-out"
                  style={{ minHeight: `${reservedStreamHeight}px` }}
                >
                  {orchestratorText ? (
                    <MarkdownContent className={`${assistantProse} prose-p:text-foreground/80`}>
                      {orchestratorText}
                    </MarkdownContent>
                  ) : (
                    <span className="text-lg font-serif animate-pulse">Preparing reply…</span>
                  )}
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>
        </ScrollArea>
      )}

      <div
        className={`w-full shrink-0 px-6 md:px-12 lg:px-24 ${hasMessages ? "pb-12 pt-8 bg-background border-t border-border/50" : "max-w-5xl mx-auto"}`}
      >
        {!hasMessages && (
          <div className="mb-16 animate-in fade-in slide-in-from-bottom-8 duration-1000">
            <h2 className="text-5xl md:text-7xl font-serif tracking-tight text-foreground mb-6 leading-[1.1]">
              What thesis shall we explore today?
            </h2>
            <div className="h-px w-24 bg-primary mb-6"></div>
            <p className="text-lg text-muted-foreground font-sans font-light max-w-2xl">
              Formulate a complex macroeconomic inquiry or equity analysis. The agent will synthesize data, construct narratives, and deliver a comprehensive report.
            </p>
          </div>
        )}

        <div className="max-w-4xl mx-auto relative group">
          <div className="absolute -inset-1 bg-gradient-to-r from-primary/20 via-transparent to-primary/20 blur opacity-0 group-focus-within:opacity-100 transition-opacity duration-1000 pointer-events-none"></div>
          <div className="relative bg-background border border-border focus-within:border-primary transition-colors duration-500">
            <Textarea
              value={inputValue}
              onChange={(e) => onInputChange(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={isStreamingChat}
              autoResize={true}
              font="18px 'Cormorant Garamond', serif"
              lineHeight={28}
              paddingVertical={48}
              maxHeight={300}
              placeholder="e.g., Analyze the historical relationship between US GDP growth and tech sector valuations..."
              data-testid="research-input"
              className="w-full resize-none border-0 bg-transparent px-6 py-6 text-lg font-serif shadow-none focus-visible:ring-0 disabled:opacity-50 placeholder:text-muted-foreground/50 placeholder:font-sans placeholder:text-base placeholder:font-light overflow-hidden"
              rows={1}
            />
            <div className="flex items-center justify-between px-6 pb-4 pt-2 border-t border-border/30">
              <div className="text-[10px] uppercase tracking-[0.1em] text-muted-foreground font-sans">
                Press <kbd className="font-mono text-primary px-1">Enter</kbd> to submit
              </div>
              <Button
                data-testid="send-button"
                size="icon"
                variant="ghost"
                className="rounded-none hover:bg-primary hover:text-primary-foreground transition-colors duration-300 w-10 h-10 border border-transparent hover:border-primary"
                onClick={onSend}
                disabled={!inputValue.trim() || isStreamingChat}
              >
                <ArrowRight weight="light" size={20} />
              </Button>
            </div>
          </div>

          {hasAssistantReply && (
            <div className="flex justify-start mt-8 animate-in fade-in slide-in-from-bottom-4 duration-700">
              <Button
                data-testid="begin-research-button"
                onClick={onBeginResearch}
                disabled={isStreamingChat}
                size="lg"
                className="rounded-none bg-foreground text-background hover:bg-primary hover:text-primary-foreground font-sans uppercase tracking-[0.15em] text-xs px-10 py-6 transition-all duration-500 border border-transparent disabled:opacity-50"
              >
                Commence Deep Research
                <ArrowRight className="ml-3" weight="light" size={16} />
              </Button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
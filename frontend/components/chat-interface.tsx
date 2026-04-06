"use client";

import { useRef, useEffect } from "react";
import { ArrowRight } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ScrollArea } from "@/components/ui/scroll-area";
import type { Message } from "@/lib/types";

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

  return (
    <div className={`flex flex-col h-full transition-all duration-700 ease-[cubic-bezier(0.2,0.8,0.2,1)] ${hasMessages ? "justify-end" : "justify-center"}`}>
      {hasMessages && (
        <ScrollArea className="flex-1 px-6 py-12 md:px-12 lg:px-24">
          <div className="max-w-4xl mx-auto flex flex-col gap-12 pb-24">
            {messages.map((msg, idx) => (
              <div key={idx} data-testid="message-item" data-role={msg.role} className="flex flex-col gap-2 animate-in fade-in slide-in-from-bottom-4 duration-700">
                <div className="text-xs uppercase tracking-[0.2em] text-muted-foreground font-sans">
                  {msg.role === "user" ? "Inquiry" : "Analysis"}
                </div>
                <div className={`text-lg md:text-xl font-serif leading-relaxed ${msg.role === "user" ? "text-foreground pl-4 border-l border-primary/30" : "text-foreground/80 pl-4 border-l-2 border-primary"}`}>
                  {msg.content}
                </div>
              </div>
            ))}

            {isStreamingChat && (
              <div className="flex flex-col gap-2 animate-in fade-in duration-500">
                <div className="text-xs uppercase tracking-[0.2em] text-muted-foreground font-sans flex items-center gap-2">
                  <span className="w-1.5 h-1.5 bg-primary rounded-full animate-pulse"></span>
                  Processing
                </div>
                <div className="text-lg md:text-xl font-serif leading-relaxed text-foreground/60 pl-4 border-l-2 border-primary/50">
                  {orchestratorText || <span className="animate-pulse">Synthesizing data...</span>}
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>
        </ScrollArea>
      )}

      <div className={`w-full px-6 md:px-12 lg:px-24 ${hasMessages ? "pb-12 pt-8 bg-background border-t border-border/50" : "max-w-5xl mx-auto"}`}>
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
          <div className="absolute -inset-1 bg-gradient-to-r from-primary/20 via-transparent to-primary/20 blur opacity-0 group-focus-within:opacity-100 transition-opacity duration-1000"></div>
          <div className="relative bg-background border border-border focus-within:border-primary transition-colors duration-500">
            <Textarea
              value={inputValue}
              onChange={(e) => onInputChange(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={isStreamingChat}
              placeholder="e.g., Analyze the historical relationship between US GDP growth and tech sector valuations..."
              data-testid="research-input"
              className="min-h-[80px] max-h-[300px] w-full resize-none border-0 bg-transparent px-6 py-6 text-lg font-serif shadow-none focus-visible:ring-0 disabled:opacity-50 placeholder:text-muted-foreground/50 placeholder:font-sans placeholder:text-base placeholder:font-light"
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

          {messages.length > 1 && !isStreamingChat && (
            <div className="flex justify-start mt-8 animate-in fade-in slide-in-from-bottom-4 duration-700">
              <Button 
                data-testid="begin-research-button" 
                onClick={onBeginResearch} 
                size="lg" 
                className="rounded-none bg-foreground text-background hover:bg-primary hover:text-primary-foreground font-sans uppercase tracking-[0.15em] text-xs px-10 py-6 transition-all duration-500 border border-transparent"
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
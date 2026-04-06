"use client";

import { useRef, useEffect, useState } from "react";
import { CircleNotch, Terminal, Cpu } from "@phosphor-icons/react";
import { ScrollArea } from "@/components/ui/scroll-area";
import ReactMarkdown from "react-markdown";
import type { PipelineStep } from "@/lib/types";

interface StreamingViewProps {
  orchestratorText: string;
  pipelineSteps: PipelineStep[];
}

export default function StreamingView({ orchestratorText, pipelineSteps }: StreamingViewProps) {
  const orchestratorEndRef = useRef<HTMLDivElement>(null);
  const [displayedText, setDisplayedText] = useState("");

  // Lightning-fast custom typewriter effect
  useEffect(() => {
    let animationFrameId: number;

    const tick = () => {
      setDisplayedText((current) => {
        if (current === orchestratorText) return current;

        // If the text was reset or completely changed, snap to the new text immediately
        if (orchestratorText.length < current.length || !orchestratorText.startsWith(current)) {
          return orchestratorText;
        }

        const remaining = orchestratorText.length - current.length;
        
        // Calculate dynamic speed:
        // - At minimum, add 3 characters per frame (180 chars/sec)
        // - If we fall behind, add 20% of the remaining text per frame to catch up instantly
        const stepSize = Math.max(3, Math.ceil(remaining * 0.2));
        
        return orchestratorText.slice(0, current.length + stepSize);
      });

      animationFrameId = requestAnimationFrame(tick);
    };

    animationFrameId = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(animationFrameId);
  }, [orchestratorText]);

  useEffect(() => {
    orchestratorEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [displayedText]);

  // Pre-process text to convert <thinking> and <tool_use> tags into blockquotes for markdown rendering
  const processedText = displayedText
    ? displayedText
        .replace(/<thinking>/g, '> 🧠 **Analysis**\n> \n> ')
        .replace(/<\/thinking>/g, '\n\n')
        .replace(/<tool_use>/g, '> 🛠️ **Tool Execution**\n> \n> ')
        .replace(/<\/tool_use>/g, '\n\n')
    : "";

  return (
    <ScrollArea data-testid="streaming-view" className="flex-1 px-6 py-12 md:px-12 lg:px-24 bg-background">
      <div className="max-w-5xl mx-auto flex flex-col gap-16 pb-24 animate-in fade-in slide-in-from-bottom-8 duration-1000">
        <div className="flex flex-col gap-4 border-l-2 border-primary pl-6">
          <h2 className="text-3xl md:text-5xl font-serif tracking-tight text-foreground flex items-center gap-4">
            <CircleNotch className="animate-spin text-primary" weight="light" size={40} />
            Synthesizing Intelligence
          </h2>
          <p className="text-lg text-muted-foreground font-sans font-light max-w-2xl">
            The orchestrator is currently coordinating specialized sub-agents to compile, analyze, and structure the requested intelligence.
          </p>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-12 gap-12">
          {/* Orchestrator Log */}
          <div className="lg:col-span-7 flex flex-col gap-6">
            <div className="flex items-center gap-3 border-b border-border pb-4">
              <Terminal className="text-primary" weight="light" size={24} />
              <h3 className="text-xl font-serif tracking-wide uppercase text-foreground">Orchestrator Telemetry</h3>
            </div>
            <div className="relative group">
              <div className="absolute -inset-0.5 bg-gradient-to-b from-primary/10 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-1000 blur-sm"></div>
              <div className="relative border border-border bg-card/50 backdrop-blur-sm shadow-sm overflow-hidden">
                <div className="flex items-center justify-between px-4 py-2 border-b border-border/50 bg-muted/20">
                  <div className="flex gap-2">
                    <div className="w-2 h-2 rounded-full bg-destructive/50"></div>
                    <div className="w-2 h-2 rounded-full bg-primary/50"></div>
                    <div className="w-2 h-2 rounded-full bg-green-500/50"></div>
                  </div>
                  <span className="text-[10px] uppercase tracking-[0.2em] text-muted-foreground font-mono">System.Log</span>
                </div>
                <ScrollArea className="h-[500px] w-full p-6">
                  {processedText ? (
                    <div className="prose prose-sm max-w-none dark:prose-invert prose-p:font-sans prose-p:text-foreground/80 prose-p:leading-relaxed">
                      <ReactMarkdown
                        components={{
                          code({ node, inline, className, children, ...props }: any) {
                            const match = /language-(\w+)/.exec(className || "");
                            return !inline ? (
                              <div className="bg-muted/30 border border-border rounded-md p-4 my-4 font-mono text-xs overflow-x-auto">
                                <code className={className} {...props}>
                                  {children}
                                </code>
                              </div>
                            ) : (
                              <code className="bg-muted px-1.5 py-0.5 rounded-md font-mono text-xs text-primary" {...props}>
                                {children}
                              </code>
                            );
                          },
                          blockquote({ children }) {
                            return (
                              <blockquote className="border-l-2 border-primary/50 pl-4 py-2 my-4 bg-primary/5 text-muted-foreground font-sans text-sm italic">
                                {children}
                              </blockquote>
                            );
                          },
                        }}
                      >
                        {processedText}
                      </ReactMarkdown>
                      <span className="inline-block w-2 h-4 ml-1 bg-primary animate-pulse align-middle mt-2" />
                    </div>
                  ) : (
                    <div className="font-mono text-sm text-muted-foreground">
                      Initializing agent network...
                      <span className="inline-block w-2 h-4 ml-1 bg-primary animate-pulse align-middle" />
                    </div>
                  )}
                  <div ref={orchestratorEndRef} />
                </ScrollArea>
              </div>
            </div>
          </div>

          {/* Pipeline Activity */}
          <div className="lg:col-span-5 flex flex-col gap-6">
            <div className="flex items-center gap-3 border-b border-border pb-4">
              <Cpu className="text-primary" weight="light" size={24} />
              <h3 className="text-xl font-serif tracking-wide uppercase text-foreground">Active Sub-Routines</h3>
            </div>
            <div className="flex flex-col gap-6 max-h-[500px] overflow-y-auto pr-4 custom-scrollbar">
              {pipelineSteps.length === 0 && (
                <div className="text-sm text-muted-foreground font-sans font-light italic py-8 border-l border-border pl-4">
                  Initializing agent network...
                </div>
              )}
              {pipelineSteps.map((step, i) => (
                <div key={i} data-testid="pipeline-step" className={`flex flex-col gap-4 p-5 border transition-all duration-500 ${step.status === "running" ? "border-primary bg-primary/5" : "border-border/50 bg-transparent opacity-70"}`}>
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <div className={`w-8 h-8 flex items-center justify-center border ${step.status === "running" ? "border-primary text-primary" : "border-border text-muted-foreground"}`}>
                        <span className="font-serif text-lg">{step.agent.substring(0, 1).toUpperCase()}</span>
                      </div>
                      <span className={`font-sans uppercase tracking-[0.15em] text-xs ${step.status === "running" ? "text-foreground font-medium" : "text-muted-foreground"}`}>
                        {step.agent.replace("-", " ")}
                      </span>
                    </div>
                    <span className="text-[10px] uppercase tracking-[0.2em] font-mono">
                      {step.status === "running"
                        ? <span className="text-primary animate-pulse">Active</span>
                        : <span className="text-muted-foreground">Complete</span>
                      }
                    </span>
                  </div>

                  {step.tools.length > 0 && (
                    <div className="flex flex-col gap-3 mt-2 pl-4 ml-4 border-l border-border/30">
                      {step.tools.map((tool, j) => (
                        <div key={j} className="flex flex-col gap-2">
                          <div className="flex items-center justify-between">
                            <span className="text-muted-foreground font-mono text-[10px] tracking-wider uppercase">
                              {tool.tool}
                            </span>
                            <span className="text-[10px]">
                              {tool.status === "running"
                                ? <CircleNotch className="animate-spin text-primary" size={12} />
                                : <span className="text-muted-foreground/50">✓</span>
                              }
                            </span>
                          </div>
                          {tool.summary && (
                            <div className="text-xs text-foreground/70 font-sans font-light leading-relaxed border-l border-primary/20 pl-3">
                              {tool.summary}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </ScrollArea>
  );
}
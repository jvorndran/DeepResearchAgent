"use client";

import { useRef, useEffect, useState } from "react";
import { CircleNotch, Terminal, Cpu } from "@phosphor-icons/react";
import { ScrollArea } from "@/components/ui/scroll-area";
import ReactMarkdown from "react-markdown";
import type { PipelineStep } from "@/lib/types";

function StreamingHeader() {
  return (
    <div className="flex flex-col gap-4 border-l-2 border-primary pl-6">
      <h2 className="text-3xl md:text-5xl font-serif tracking-tight text-foreground flex items-center gap-4">
        <CircleNotch className="animate-spin text-primary" weight="light" size={40} />
        Synthesizing Intelligence
      </h2>
      <p className="text-lg text-muted-foreground font-sans font-light max-w-2xl">
        The orchestrator is currently coordinating specialized sub-agents to compile, analyze, and structure the requested intelligence.
      </p>
    </div>
  );
}

function OrchestratorTelemetry({ orchestratorText }: { orchestratorText: string }) {
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
  let processedText = displayedText
    ? displayedText
        .replace(/<thinking>/g, '> 🧠 **Analysis**\n> \n> ')
        .replace(/<\/thinking>/g, '\n\n')
        .replace(/<tool_use>/g, '> 🛠️ **Tool Execution**\n> \n> ')
        .replace(/<\/tool_use>/g, '\n\n')
    : "";

  // Parse Python-like todo lists: Updated todo list to [{'content': '...', 'status': '...'}, ...]
  processedText = processedText.replace(/Updated todo list to (\[.*?\])/g, (match, listStr) => {
    try {
      const items = [];
      const regex = /['"]content['"]:\s*['"]([^'"]*)['"],\s*['"]status['"]:\s*['"]([^'"]*)['"]/g;
      let m;
      while ((m = regex.exec(listStr)) !== null) {
        items.push({ content: m[1], status: m[2] });
      }
      
      if (items.length > 0) {
        let md = "\n\n### TASK_PLAN_HEADER\n\n";
        items.forEach(item => {
          md += `- STATUS:${item.status}|${item.content}\n`;
        });
        return md + "\n\n";
      }
      return match;
    } catch {
      return match;
    }
  });

  return (
    <div className="lg:col-span-7 flex flex-col gap-6">
      <div className="flex items-center gap-3 border-b border-border pb-4">
        <Terminal className="text-primary" weight="light" size={24} />
        <h3 className="text-xl font-serif tracking-wide uppercase text-foreground">Orchestrator Telemetry</h3>
      </div>
      <div className="relative group">
        <div className="absolute -inset-0.5 bg-gradient-to-b from-primary/10 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-1000 blur-sm"></div>
        <div className="relative border border-border bg-card/50 backdrop-blur-sm shadow-[4px_4px_0px_0px_var(--border)] overflow-hidden transition-all duration-500 group-hover:shadow-[4px_4px_0px_0px_var(--primary)]">
          <div className="flex items-center justify-between px-4 py-2 border-b border-border/50 bg-muted/20">
            <div className="flex gap-2">
              <div className="w-2 h-2 bg-destructive/50"></div>
              <div className="w-2 h-2 bg-primary/50"></div>
              <div className="w-2 h-2 bg-green-500/50"></div>
            </div>
            <span className="text-[10px] uppercase tracking-[0.2em] text-muted-foreground font-mono">System.Log</span>
          </div>
          <ScrollArea data-testid="orchestrator-log" className="h-[500px] w-full p-6">
            {processedText ? (
              <div data-testid="orchestrator-log-content" className="prose prose-sm max-w-none dark:prose-invert prose-p:font-sans prose-p:text-foreground/80 prose-p:leading-relaxed">
                <ReactMarkdown
                  components={{
                    h3({ children, ...props }) {
                      if (children?.toString() === "TASK_PLAN_HEADER") {
                        return <div className="text-[10px] uppercase tracking-[0.2em] text-muted-foreground font-sans mt-8 mb-4 border-b border-border/50 pb-2">Execution Plan</div>;
                      }
                      return <h3 className="text-lg font-serif tracking-tight mt-6 mb-3 text-foreground" {...props}>{children}</h3>;
                    },
                    ul({ children, ...props }) {
                      return <ul className="flex flex-col gap-0 my-4 border border-border/30 bg-card/30" {...props}>{children}</ul>;
                    },
                    li({ children }: React.HTMLAttributes<HTMLElement>) {
                      const childArray = Array.isArray(children) ? [...children] : [children];
                      const firstChild = childArray[0];
                      let status = "";
                      
                      if (typeof firstChild === 'string' && firstChild.startsWith('STATUS:')) {
                        const match = firstChild.match(/^STATUS:(done|completed|in_progress|pending)\|(.*)/);
                        if (match) {
                          status = match[1];
                          childArray[0] = match[2];
                        }
                      }

                      if (status) {
                        const isDone = status === 'done' || status === 'completed';
                        const isProgress = status === 'in_progress';
                        
                        return (
                          <li className={`flex items-start gap-4 p-3 border-b border-border/30 last:border-0 ${isProgress ? 'bg-primary/5' : isDone ? 'opacity-70' : 'opacity-50'} transition-all duration-500`}>
                            <div className="mt-0.5 shrink-0">
                              {isDone ? (
                                <div className="w-4 h-4 flex items-center justify-center border border-primary/50 bg-primary/10 text-primary text-[10px] font-mono">✓</div>
                              ) : isProgress ? (
                                <div className="w-4 h-4 flex items-center justify-center border border-primary">
                                  <div className="w-1.5 h-1.5 bg-primary animate-pulse" />
                                </div>
                              ) : (
                                <div className="w-4 h-4 border border-border/50" />
                              )}
                            </div>
                            <div className={`font-sans text-sm ${isProgress ? 'text-foreground' : 'text-muted-foreground'}`}>
                              {childArray}
                            </div>
                          </li>
                        );
                      }

                      return <li className="list-disc ml-6 marker:text-primary/50 mb-1 font-sans text-sm text-foreground/80 leading-relaxed">{children}</li>;
                    },
                    p({ children, ...props }) {
                      return <p className="font-sans text-sm text-foreground/80 leading-relaxed mb-4" {...props}>{children}</p>;
                    },
                    code({ inline, className, children, ...props }: React.HTMLAttributes<HTMLElement> & { inline?: boolean }) {
                      return !inline ? (
                        <div className="bg-muted/30 border border-border p-4 my-4 font-mono text-xs overflow-x-auto">
                          <code className={className} {...props}>
                            {children}
                          </code>
                        </div>
                      ) : (
                        <code className="bg-muted px-1.5 py-0.5 font-mono text-xs text-primary" {...props}>
                          {children}
                        </code>
                      );
                    },
                    blockquote({ children }) {
                      return (
                        <blockquote className="border-l-2 border-primary pl-4 py-3 my-6 bg-primary/5 text-muted-foreground font-sans text-sm italic">
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
  );
}

function PipelineActivity({ pipelineSteps }: { pipelineSteps: PipelineStep[] }) {
  return (
    <div className="lg:col-span-5 flex flex-col gap-6">
      <div className="flex items-center gap-3 border-b border-border pb-4">
        <Cpu className="text-primary" weight="light" size={24} />
        <h3 className="text-xl font-serif tracking-wide uppercase text-foreground">Active Sub-Routines</h3>
      </div>
      <div className="flex flex-col gap-4 max-h-[500px] overflow-y-auto pr-4 custom-scrollbar">
        {pipelineSteps.length === 0 && (
          <div className="text-[10px] text-muted-foreground font-mono uppercase tracking-[0.2em] py-8 border border-border border-dashed flex items-center justify-center bg-muted/10">
            Initializing agent network...
          </div>
        )}
        {pipelineSteps.map((step, i) => (
          <div key={i} data-testid="pipeline-step" className={`flex flex-col gap-4 p-4 border transition-all duration-500 ${step.status === "running" ? "border-primary bg-primary/5 shadow-[4px_4px_0px_0px_var(--primary)]" : "border-border/50 bg-transparent opacity-70"}`}>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className={`w-8 h-8 flex items-center justify-center border ${step.status === "running" ? "border-primary text-primary bg-primary/10" : "border-border text-muted-foreground"}`}>
                  <span className="font-serif text-lg">{step.agent.substring(0, 1).toUpperCase()}</span>
                </div>
                <span className={`font-mono uppercase tracking-[0.2em] text-[10px] ${step.status === "running" ? "text-foreground font-bold" : "text-muted-foreground"}`}>
                  {step.agent.replace("-", "_")}
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
                        &gt; {tool.tool}
                      </span>
                      <span className="text-[10px]">
                        {tool.status === "running"
                          ? <CircleNotch className="animate-spin text-primary" size={12} />
                          : <span className="text-muted-foreground/50 font-mono">[OK]</span>
                        }
                      </span>
                    </div>
                    {tool.summary && (
                      <div className="text-xs text-foreground/70 font-mono leading-relaxed border-l border-primary/20 pl-3 py-1 bg-muted/20">
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
  );
}

interface StreamingViewProps {
  orchestratorText: string;
  pipelineSteps: PipelineStep[];
}

export default function StreamingView({ orchestratorText, pipelineSteps }: StreamingViewProps) {
  return (
    <ScrollArea data-testid="streaming-view" className="flex-1 px-6 py-12 md:px-12 lg:px-24 bg-background">
      <div className="max-w-5xl mx-auto flex flex-col gap-16 pb-24 animate-in fade-in slide-in-from-bottom-8 duration-1000">
        <StreamingHeader />

        <div className="grid grid-cols-1 lg:grid-cols-12 gap-12">
          <OrchestratorTelemetry orchestratorText={orchestratorText} />
          <PipelineActivity pipelineSteps={pipelineSteps} />
        </div>
      </div>
    </ScrollArea>
  );
}
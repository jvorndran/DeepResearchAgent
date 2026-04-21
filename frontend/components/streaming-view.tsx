"use client";

import { useRef, useEffect, useState, useMemo, memo } from "react";
import { CircleNotch, Terminal, Cpu, Brain, Wrench, Database, CheckCircle, ListChecks } from "@phosphor-icons/react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { usePretextHeight, useElementWidth } from "@/hooks/use-pretext";
import ReactMarkdown from "react-markdown";
import type { PipelineStep } from "@/lib/types";

const tryFormatJson = (str: string | undefined): string => {
  if (!str) return "";
  try {
    const parsed = JSON.parse(str);
    return JSON.stringify(parsed, null, 2);
  } catch {
    return str;
  }
};

const StreamingHeader = memo(function StreamingHeader() {
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
});

const TerminalWindow = memo(function TerminalWindow({ title, children, testId, className, autoScrollDep }: { title: string; children: React.ReactNode; testId?: string; className?: string; autoScrollDep?: any }) {
  const viewportRef = useRef<HTMLDivElement>(null);
  const [isAutoScrolling, setIsAutoScrolling] = useState(true);

  const handleScroll = () => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    
    // Check if user is near the bottom (within 50px)
    const isNearBottom = viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight < 50;
    setIsAutoScrolling(isNearBottom);
  };

  useEffect(() => {
    if (isAutoScrolling && viewportRef.current) {
      viewportRef.current.scrollTop = viewportRef.current.scrollHeight;
    }
  }, [autoScrollDep, isAutoScrolling]);

  return (
    <div className="relative group">
      <div className="absolute -inset-0.5 bg-gradient-to-b from-primary/10 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-1000 blur-sm"></div>
      <div className="relative border border-border bg-card/50 backdrop-blur-sm shadow-[4px_4px_0px_0px_var(--border)] overflow-hidden transition-all duration-500 group-hover:shadow-[4px_4px_0px_0px_var(--primary)]">
        <div className="flex items-center justify-between px-4 py-2 border-b border-border/50 bg-muted/20">
          <div className="flex gap-2">
            <div className="w-2 h-2 bg-destructive/50"></div>
            <div className="w-2 h-2 bg-primary/50"></div>
            <div className="w-2 h-2 bg-green-500/50"></div>
          </div>
          <span className="text-[10px] uppercase tracking-[0.2em] text-muted-foreground font-mono">{title}</span>
        </div>
        <ScrollArea 
          data-testid={testId} 
          className={`h-[700px] w-full p-6 ${className ?? ""}`}
          viewportRef={viewportRef}
          onScroll={handleScroll}
        >
          {children}
        </ScrollArea>
      </div>
    </div>
  );
});

const OrchestratorTelemetry = memo(function OrchestratorTelemetry({ orchestratorText }: { orchestratorText: string }) {
  const [displayedText, setDisplayedText] = useState("");
  const { ref: containerRef, width: containerWidth } = useElementWidth<HTMLDivElement>();

  // Use Pretext to calculate the height of the full orchestratorText
  // to reserve space during the typewriter effect.
  // Font: 14px sans-serif (prose-sm font-sans)
  // Line-height: 20px (prose-sm default)
  const font = "14px sans-serif";
  const lineHeight = 20;
  const horizontalPadding = 48; // p-6 = 24px each side
  const { height: reservedHeight } = usePretextHeight(
    orchestratorText,
    font,
    Math.max(0, containerWidth - horizontalPadding),
    lineHeight
  );

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

  // Pre-process text to convert <thinking> and <tool_use> tags into blockquotes for markdown rendering
  const processedText = useMemo(() => displayedText
    ? displayedText
        .replace(/<thinking>([\s\S]*?)<\/thinking>/g, '\n```thinking\n$1\n```\n')
        .replace(/<tool_use>([\s\S]*?)<\/tool_use>/g, '\n```tool_use\n$1\n```\n')
        .replace(/\\n/g, '\n')
    : "", [displayedText]);

  const markdownComponents = useMemo(() => ({
    h3({ children, ...props }: any) {
      if (children?.toString() === "TASK_PLAN_HEADER") {
        return <div className="text-[10px] uppercase tracking-[0.2em] text-muted-foreground font-sans mt-8 mb-4 border-b border-border/50 pb-2">Execution Plan</div>;
      }
      return <h3 className="text-lg font-serif tracking-tight mt-6 mb-3 text-foreground" {...props}>{children}</h3>;
    },
    ul({ children, ...props }: any) {
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
    p({ children, ...props }: any) {
      return <p className="font-sans text-sm text-foreground/80 leading-relaxed mb-4" {...props}>{children}</p>;
    },
    code({ inline, className, children, ...props }: React.HTMLAttributes<HTMLElement> & { inline?: boolean }) {
      const match = /language-([\w-]+)(?:\|([^|]+)\|([^|]+))?/.exec(className || "");
      const type = match ? match[1] : "";
      const agent = match ? match[2] : "";
      const tool = match ? match[3] : "";

      if (!inline && type === "thinking") {
        return (
          <div className="my-6 border-l-2 border-indigo-500/50 bg-indigo-500/5 pl-4 py-3 pr-4 rounded-r-md">
            <div className="flex items-center gap-2 mb-2 text-indigo-500/80">
              <Brain weight="light" size={16} />
              <span className="text-[10px] uppercase tracking-widest font-semibold">Internal Monologue</span>
            </div>
            <div className="font-serif text-sm text-muted-foreground italic leading-relaxed">
              {children}
            </div>
          </div>
        );
      }

      if (!inline && type === "tool-call") {
        if (tool === "write_todos") {
          try {
            const parsed = JSON.parse(String(children));
            const todos = parsed.todos || [];
            return (
              <div className="my-6 border border-primary/20 rounded-md overflow-hidden bg-card shadow-sm">
                <div className="flex items-center gap-2 px-3 py-2 bg-primary/5 border-b border-primary/10">
                  <ListChecks weight="light" size={14} className="text-primary/70" />
                  <span className="text-[10px] uppercase tracking-wider text-foreground/80 font-mono">Task Manifest Updated</span>
                </div>
                <div className="p-3 bg-background flex flex-col gap-2">
                  {todos.map((t: any, i: number) => {
                    const isDone = t.status === 'done' || t.status === 'completed';
                    const isProgress = t.status === 'in_progress';
                    return (
                      <div key={i} className={`flex items-start gap-3 p-2 border border-border/30 rounded-sm ${isProgress ? 'bg-primary/5 border-primary/30' : isDone ? 'opacity-70' : 'opacity-50'}`}>
                        <div className="mt-0.5 shrink-0">
                          {isDone ? (
                            <div className="w-3 h-3 flex items-center justify-center border border-primary/50 bg-primary/10 text-primary text-[8px] font-mono">✓</div>
                          ) : isProgress ? (
                            <div className="w-3 h-3 flex items-center justify-center border border-primary">
                              <div className="w-1.5 h-1.5 bg-primary animate-pulse" />
                            </div>
                          ) : (
                            <div className="w-3 h-3 border border-border/50" />
                          )}
                        </div>
                        <span className={`font-sans text-xs ${isProgress ? 'text-foreground' : 'text-muted-foreground'}`}>
                          {t.content}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          } catch {
            // fallback
          }
        }

        if (tool === "execute" || tool === "python") {
          let cmd = String(children);
          try {
            const parsed = JSON.parse(cmd);
            if (parsed.command) cmd = parsed.command;
            if (parsed.code) cmd = parsed.code;
          } catch {}
          return (
            <div className="my-6 border border-border/50 rounded-md overflow-hidden bg-[#0D0D0D] shadow-sm">
              <div className="flex items-center gap-2 px-3 py-2 bg-[#1A1A1A] border-b border-white/10">
                <div className="flex gap-1.5">
                  <div className="w-2.5 h-2.5 rounded-full bg-red-500/80"></div>
                  <div className="w-2.5 h-2.5 rounded-full bg-yellow-500/80"></div>
                  <div className="w-2.5 h-2.5 rounded-full bg-green-500/80"></div>
                </div>
                <span className="ml-2 text-[10px] uppercase tracking-wider text-white/50 font-mono">
                  {agent} <span className="text-white/30">running</span> shell
                </span>
              </div>
              <div className="p-3 font-mono text-[11px] text-green-400 overflow-x-auto max-h-48 overflow-y-auto whitespace-pre-wrap break-all">
                <code>$ {cmd}</code>
              </div>
            </div>
          );
        }

        return (
          <div className="my-6 border border-border/50 rounded-md overflow-hidden bg-card shadow-sm">
            <div className="flex items-center justify-between px-3 py-2 bg-muted/30 border-b border-border/50">
              <div className="flex items-center gap-2">
                <Wrench weight="light" size={14} className="text-primary/70" />
                <span className="text-[10px] uppercase tracking-wider text-foreground/80 font-mono">
                  {agent} <span className="text-muted-foreground">executing</span> {tool}
                </span>
              </div>
              <CircleNotch className="animate-spin text-primary/50" size={12} />
            </div>
            <div className="p-3 bg-muted/10 font-mono text-[10px] text-muted-foreground overflow-x-auto max-h-48 overflow-y-auto whitespace-pre-wrap break-all">
              <code>{children}</code>
            </div>
          </div>
        );
      }

      if (!inline && type === "tool-result") {
        return (
          <div className="my-6 border border-green-500/20 rounded-md overflow-hidden bg-card shadow-sm">
            <div className="flex items-center justify-between px-3 py-2 bg-green-500/5 border-b border-green-500/10">
              <div className="flex items-center gap-2">
                <Database weight="light" size={14} className="text-green-500/70" />
                <span className="text-[10px] uppercase tracking-wider text-foreground/80 font-mono">
                  {agent} <span className="text-muted-foreground">received</span> {tool} output
                </span>
              </div>
              <CheckCircle weight="light" size={12} className="text-green-500/50" />
            </div>
            <div className="p-3 bg-green-500/5 font-mono text-[10px] text-foreground/70 overflow-x-auto max-h-48 overflow-y-auto whitespace-pre-wrap break-words">
              <code>{tryFormatJson(String(children))}</code>
            </div>
          </div>
        );
      }

      return !inline ? (
        <div className="bg-muted/10 border border-border/50 rounded-sm p-4 my-4 font-mono text-[11px] overflow-x-auto">
          <code className={className} {...props}>
            {children}
          </code>
        </div>
      ) : (
        <code className="bg-muted/50 border border-border/50 rounded-sm px-1.5 py-0.5 font-mono text-[11px] text-primary" {...props}>
          {children}
        </code>
      );
    },
    blockquote({ children }: any) {
      return (
        <blockquote className="border-l-2 border-primary pl-4 py-3 my-6 bg-primary/5 text-muted-foreground font-sans text-sm italic">
          {children}
        </blockquote>
      );
    },
  }), []);

  return (
    <div className="lg:col-span-7 flex flex-col gap-6">
      <div className="flex items-center gap-3 border-b border-border pb-4">
        <Terminal className="text-primary" weight="light" size={24} />
        <h3 className="text-xl font-serif tracking-wide uppercase text-foreground">Orchestrator Telemetry</h3>
      </div>
      <div ref={containerRef}>
        <TerminalWindow title="System.Log" testId="orchestrator-log" autoScrollDep={processedText}>
          <div 
            style={{ minHeight: `${reservedHeight}px` }}
            className="transition-[min-height] duration-300 ease-out"
          >
            {processedText ? (
              <div data-testid="orchestrator-log-content" className="prose prose-sm max-w-none dark:prose-invert prose-p:font-sans prose-p:text-foreground/80 prose-p:leading-relaxed">
                <ReactMarkdown components={markdownComponents}>
                  {processedText}
                </ReactMarkdown>
                <span className="inline-block w-2.5 h-4 ml-1 bg-primary animate-pulse align-middle mt-1" />
              </div>
            ) : (
              <div className="font-mono text-sm text-muted-foreground">
                Initializing agent network...
                <span className="inline-block w-2.5 h-4 ml-1 bg-primary animate-pulse align-middle" />
              </div>
            )}
          </div>
        </TerminalWindow>
      </div>
    </div>
  );
});

const PipelineActivity = memo(function PipelineActivity({ pipelineSteps }: { pipelineSteps: PipelineStep[] }) {
  return (
    <div className="lg:col-span-5 flex flex-col gap-6">
      <div className="flex items-center gap-3 border-b border-border pb-4">
        <Cpu className="text-primary" weight="light" size={24} />
        <h3 className="text-xl font-serif tracking-wide uppercase text-foreground">Active Sub-Routines</h3>
      </div>
      <TerminalWindow title="Pipeline.Run" autoScrollDep={pipelineSteps}>
        <div className="flex flex-col gap-4">
          {pipelineSteps.length === 0 && (
            <div className="text-[10px] text-muted-foreground font-mono uppercase tracking-[0.2em] py-8 border border-border border-dashed flex items-center justify-center bg-muted/10">
              Initializing agent network...
            </div>
          )}
          {pipelineSteps.map((step, i) => (
            <div key={i} data-testid="pipeline-step" className={`flex flex-col gap-4 p-4 border transition-all duration-500 animate-in fade-in slide-in-from-left-4 ${step.status === "running" ? "border-primary bg-primary/5 shadow-[4px_4px_0px_0px_var(--primary)]" : "border-border/50 bg-transparent opacity-70"}`}>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className={`w-8 h-8 flex items-center justify-center border ${step.status === "running" ? "border-primary text-primary bg-primary/10" : "border-border text-muted-foreground"}`}>
                    <span className="font-serif text-lg">{step.agent ? step.agent.substring(0, 1).toUpperCase() : "O"}</span>
                  </div>
                  <span className={`font-mono uppercase tracking-[0.2em] text-[10px] ${step.status === "running" ? "text-foreground font-bold" : "text-muted-foreground"}`}>
                    {step.agent ? step.agent.replace("-", "_") : "ORCHESTRATOR"}
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
                        <div className="flex items-center gap-2">
                          <span className="text-primary/70 font-mono text-[11px]">&gt;</span>
                          <span className="text-foreground/90 font-mono text-xs tracking-wide">
                            {tool.tool}
                          </span>
                        </div>
                        <span className="text-[10px]">
                          {tool.status === "running"
                            ? <CircleNotch className="animate-spin text-primary" size={12} />
                            : <span className="text-muted-foreground/50 font-mono">[OK]</span>
                          }
                        </span>
                      </div>
                      {tool.tool === "write_todos" && (tool.args as any)?.todos ? (
                        <div className="flex flex-col gap-2 mt-1">
                          {((tool.args as any).todos).map((t: any, idx: number) => {
                             const isDone = t.status === 'done' || t.status === 'completed';
                             const isProgress = t.status === 'in_progress';
                             return (
                               <div key={idx} className={`flex items-start gap-3 p-2 border border-border/30 ${isProgress ? 'bg-primary/5 border-primary/30' : isDone ? 'opacity-70' : 'opacity-50'}`}>
                                 <div className="mt-0.5 shrink-0">
                                   {isDone ? (
                                     <div className="w-3 h-3 flex items-center justify-center border border-primary/50 bg-primary/10 text-primary text-[8px] font-mono">✓</div>
                                   ) : isProgress ? (
                                     <div className="w-3 h-3 flex items-center justify-center border border-primary">
                                       <div className="w-1.5 h-1.5 bg-primary animate-pulse" />
                                     </div>
                                   ) : (
                                     <div className="w-3 h-3 border border-border/50" />
                                   )}
                                 </div>
                                 <span className={`font-sans text-xs ${isProgress ? 'text-foreground' : 'text-muted-foreground'}`}>
                                   {t.content}
                                 </span>
                               </div>
                             );
                          })}
                        </div>
                      ) : (
                        <div className="flex flex-col gap-2 mt-1">
                          {tool.args && Object.keys(tool.args).length > 0 && (
                            <div className="flex flex-col gap-1">
                              <span className="text-[9px] uppercase tracking-wider text-muted-foreground/60 font-sans ml-1">Arguments</span>
                              <div className="text-[11px] text-muted-foreground font-mono whitespace-pre-wrap break-words border border-border/40 rounded-md p-3 bg-muted/20 max-h-40 overflow-y-auto shadow-inner">
                                {JSON.stringify(tool.args, null, 2)}
                              </div>
                            </div>
                          )}
                          {tool.summary && (
                            <div className="flex flex-col gap-1">
                              <span className="text-[9px] uppercase tracking-wider text-primary/60 font-sans ml-1">Result</span>
                              <div className="text-[11px] text-foreground/80 font-mono whitespace-pre-wrap break-words border border-primary/20 rounded-md p-3 bg-primary/5 max-h-64 overflow-y-auto shadow-inner">
                                {tryFormatJson(tool.summary)}
                              </div>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      </TerminalWindow>
    </div>
  );
});

interface StreamingViewProps {
  orchestratorText: string;
  pipelineSteps: PipelineStep[];
}

export default memo(function StreamingView({ orchestratorText, pipelineSteps }: StreamingViewProps) {
  return (
    <ScrollArea data-testid="streaming-view" className="flex-1 px-6 py-12 md:px-12 lg:px-24 bg-background">
      <div className="max-w-7xl mx-auto flex flex-col gap-16 pb-24 animate-in fade-in slide-in-from-bottom-8 duration-1000">
        <StreamingHeader />

        <div className="grid grid-cols-1 lg:grid-cols-12 gap-12">
          <OrchestratorTelemetry orchestratorText={orchestratorText} />
          <PipelineActivity pipelineSteps={pipelineSteps} />
        </div>
      </div>
    </ScrollArea>
  );
});
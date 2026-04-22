"use client";

import { useRef, useEffect, useState, useMemo, memo } from "react";
import { Terminal, Brain, Wrench, Database, CheckCircle, ListChecks } from "@phosphor-icons/react";
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

const CustomSpinner = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" className="animate-spin text-primary">
    <rect x="3" y="3" width="7" height="7" stroke="currentColor" strokeWidth="2" />
    <rect x="14" y="14" width="7" height="7" stroke="currentColor" strokeWidth="2" />
    <circle cx="17.5" cy="6.5" r="3.5" stroke="currentColor" strokeWidth="2" />
    <circle cx="6.5" cy="17.5" r="3.5" stroke="currentColor" strokeWidth="2" />
  </svg>
);

const StreamingHeader = memo(function StreamingHeader() {
  return (
    <div className="flex flex-col gap-4 border-l-4 border-primary pl-6">
      <h2 className="text-3xl md:text-5xl font-serif tracking-tight text-foreground flex items-center gap-4">
        <CustomSpinner />
        <span>Synthesizing Intelligence</span>
      </h2>
      <p className="text-lg text-muted-foreground font-sans font-light max-w-2xl">
        The orchestrator is currently coordinating specialized sub-agents to compile, analyze, and structure the requested intelligence.
      </p>
    </div>
  );
});

const OrchestratorLogContent = memo(function OrchestratorLogContent({ orchestratorText, displayedText, reservedHeight, markdownComponents }: any) {
  return (
    <div 
      style={{ minHeight: `${reservedHeight}px` }}
      className="transition-[min-height] duration-300 ease-out"
    >
      {displayedText ? (
        <div data-testid="orchestrator-log-content" className="prose prose-sm max-w-none dark:prose-invert prose-p:font-sans prose-p:text-foreground/80 prose-p:leading-relaxed break-words overflow-wrap-anywhere">
          <ReactMarkdown components={markdownComponents}>
            {orchestratorText}
          </ReactMarkdown>
          <span className="inline-block w-2.5 h-4 ml-1 bg-primary align-middle mt-1 animate-[pulse_1s_steps(2,start)_infinite]">█</span>
        </div>
      ) : (
        <div className="font-mono text-sm text-muted-foreground flex items-center">
          Initializing agent network...
          <span className="inline-block w-2.5 h-4 ml-1 bg-primary align-middle animate-[pulse_1s_steps(2,start)_infinite]">█</span>
        </div>
      )}
    </div>
  );
});

export default memo(function StreamingView({ orchestratorText }: { orchestratorText: string; pipelineSteps: PipelineStep[] }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const logViewportRef = useRef<HTMLDivElement>(null);
  const [mousePosition, setMousePosition] = useState({ x: 0, y: 0 });
  const [isHovered, setIsHovered] = useState(false);
  const [isLogAutoScrolling, setIsLogAutoScrolling] = useState(true);

  const { ref: logContainerRef, width: logContainerWidth } = useElementWidth<HTMLDivElement>();
  const [displayedText, setDisplayedText] = useState("");

  const font = "14px sans-serif";
  const lineHeight = 20;
  const horizontalPadding = 64; // p-8 = 32px each side
  const { height: reservedHeight } = usePretextHeight(
    orchestratorText,
    font,
    Math.max(0, logContainerWidth - horizontalPadding),
    lineHeight
  );

  useEffect(() => {
    let animationFrameId: number;
    const tick = () => {
      setDisplayedText((current) => {
        if (current === orchestratorText) return current;
        if (orchestratorText.length < current.length || !orchestratorText.startsWith(current)) return orchestratorText;
        const remaining = orchestratorText.length - current.length;
        const stepSize = Math.max(3, Math.ceil(remaining * 0.2));
        return orchestratorText.slice(0, current.length + stepSize);
      });
      animationFrameId = requestAnimationFrame(tick);
    };
    animationFrameId = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(animationFrameId);
  }, [orchestratorText]);

  useEffect(() => {
    if (isLogAutoScrolling && logViewportRef.current) {
      logViewportRef.current.scrollTop = logViewportRef.current.scrollHeight;
    }
  }, [displayedText, isLogAutoScrolling]);

  const handleLogScroll = () => {
    const viewport = logViewportRef.current;
    if (!viewport) return;
    const isNearBottom = viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight < 50;
    setIsLogAutoScrolling(isNearBottom);
  };

  const handleMouseMove = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    setMousePosition({ x: e.clientX - rect.left, y: e.clientY - rect.top });
  };

  const processedText = useMemo(() => displayedText
    ? displayedText
        .replace(/<thinking>([\s\S]*?)<\/thinking>/g, '\n```thinking\n$1\n```\n')
        .replace(/<tool_use>([\s\S]*?)<\/tool_use>/g, '\n```tool_use\n$1\n```\n')
        .replace(/\\n/g, '\n')
    : "", [displayedText]);

  const markdownComponents = useMemo(() => ({
    h3({ children, ...props }: any) {
      if (children?.toString() === "TASK_PLAN_HEADER") {
        return <div className="text-[10px] uppercase tracking-[0.3em] text-primary/80 font-mono mt-8 mb-4 border-b border-primary/20 pb-2 flex items-center gap-2"><ListChecks size={14} /> Execution Plan</div>;
      }
      return <h3 className="text-xl font-serif tracking-tight mt-6 mb-3 text-foreground border-l-2 border-primary pl-3" {...props}>{children}</h3>;
    },
    ul({ children, ...props }: any) {
      return <ul className="flex flex-col gap-0 my-4 border border-border/30 bg-card/10 backdrop-blur-sm shadow-sm max-w-full overflow-hidden" {...props}>{children}</ul>;
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
          <li className={`flex items-start gap-4 p-3 border-b border-border/30 last:border-0 ${isProgress ? 'bg-primary/5' : isDone ? 'opacity-70' : 'opacity-50'} transition-all duration-500 max-w-full overflow-hidden`}>
            <div className="mt-0.5 shrink-0">
              {isDone ? (
                <div className="w-4 h-4 flex items-center justify-center border border-primary/50 bg-primary/10 text-primary text-[10px] font-mono">✓</div>
              ) : isProgress ? (
                <div className="w-4 h-4 flex items-center justify-center text-primary">
                  <CustomSpinner />
                </div>
              ) : (
                <div className="w-4 h-4 border border-border/50 bg-background/50" />
              )}
            </div>
            <div className={`font-sans text-sm min-w-0 flex-1 break-words ${isProgress ? 'text-foreground' : 'text-muted-foreground'}`}>
              {childArray}
            </div>
          </li>
        );
      }
      return <li className="list-disc ml-6 marker:text-primary/50 mb-1 font-sans text-sm text-foreground/80 leading-relaxed break-words">{children}</li>;
    },
    p({ children, ...props }: any) {
      return <p className="font-sans text-sm text-foreground/80 leading-relaxed mb-4 break-words" {...props}>{children}</p>;
    },
    code({ inline, className, children, ...props }: React.HTMLAttributes<HTMLElement> & { inline?: boolean }) {
      const match = /language-([\w-]+)(?:\|([^|]+)\|([^|]+))?/.exec(className || "");
      const type = match ? match[1] : "";
      const agent = match ? match[2] : "";
      const tool = match ? match[3] : "";
      if (!inline && type === "thinking") {
        return (
          <div className="my-6 border-l border-indigo-500/30 bg-indigo-500/5 pl-4 py-3 pr-4 group transition-all duration-500 max-w-full overflow-hidden">
            <div className="flex items-center gap-2 mb-2 text-indigo-500/80">
              <Brain weight="light" size={16} />
              <span className="text-[10px] uppercase tracking-widest font-mono">Internal Monologue</span>
            </div>
            <div className="font-serif text-sm text-muted-foreground italic leading-relaxed blur-[3px] group-hover:blur-none transition-all duration-500 select-none group-hover:select-auto break-words overflow-wrap-anywhere">
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
              <div className="my-6 border border-primary/20 bg-card/40 backdrop-blur-md shadow-sm max-w-full overflow-hidden">
                <div className="flex items-center gap-2 px-3 py-2 bg-primary/10 border-b border-primary/10">
                  <ListChecks weight="light" size={14} className="text-primary/90" />
                  <span className="text-[10px] uppercase tracking-wider text-primary font-mono">Task Manifest Updated</span>
                </div>
                <div className="p-3 bg-transparent flex flex-col gap-2 overflow-hidden">
                  {todos.map((t: any, i: number) => {
                    const isDone = t.status === 'done' || t.status === 'completed';
                    const isProgress = t.status === 'in_progress';
                    return (
                      <div key={i} className={`flex items-start gap-3 p-2 border border-border/30 bg-background/50 overflow-hidden ${isProgress ? 'border-primary/40 shadow-[inset_2px_0_0_0_var(--primary)]' : isDone ? 'opacity-70' : 'opacity-50'}`}>
                        <div className="mt-0.5 shrink-0">
                          {isDone ? (
                            <div className="w-3 h-3 flex items-center justify-center border border-primary/50 bg-primary/10 text-primary text-[8px] font-mono">✓</div>
                          ) : isProgress ? (
                            <div className="w-3 h-3 flex items-center justify-center text-primary">
                              <CustomSpinner />
                            </div>
                          ) : (
                            <div className="w-3 h-3 border border-border/50" />
                          )}
                        </div>
                        <span className={`font-mono text-xs min-w-0 flex-1 break-words ${isProgress ? 'text-foreground' : 'text-muted-foreground'}`}>
                          {t.content}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          } catch { /* fallback */ }
        }
        if (tool === "execute" || tool === "python") {
          let cmd = String(children);
          try {
            const parsed = JSON.parse(cmd);
            if (parsed.command) cmd = parsed.command;
            if (parsed.code) cmd = parsed.code;
          } catch {}
          return (
            <div className="my-6 border border-border/50 bg-[#0a0a0a] shadow-sm relative overflow-hidden group max-w-full">
              <div className="absolute top-0 left-0 w-full h-[1px] bg-green-500/50 shadow-[0_0_8px_2px_rgba(34,197,94,0.5)] -translate-y-full group-hover:animate-[scan_2s_ease-in-out_infinite] z-10" style={{ animationName: 'scan' }}></div>
              <style>{`
                @keyframes scan {
                  0% { transform: translateY(-100%); opacity: 0; }
                  10% { opacity: 1; }
                  90% { opacity: 1; }
                  100% { transform: translateY(200px); opacity: 0; }
                }
              `}</style>
              <div className="flex items-center gap-2 px-3 py-2 bg-[#141414] border-b border-white/10 relative z-20">
                <div className="flex gap-1.5">
                  <div className="w-2.5 h-2.5 bg-red-500/80"></div>
                  <div className="w-2.5 h-2.5 bg-yellow-500/80"></div>
                  <div className="w-2.5 h-2.5 bg-green-500/80"></div>
                </div>
                <span className="ml-2 text-[10px] uppercase tracking-[0.2em] text-white/50 font-mono truncate">
                  {agent} <span className="text-white/30">running</span> shell
                </span>
              </div>
              <div className="p-4 font-mono text-[11px] text-green-400 overflow-x-auto max-h-48 overflow-y-auto whitespace-pre-wrap break-words relative z-20 bg-[radial-gradient(ellipse_at_center,_var(--tw-gradient-stops))] from-green-900/10 via-[#0a0a0a] to-[#0a0a0a] overflow-wrap-anywhere">
                <code>$ {cmd}</code>
              </div>
            </div>
          );
        }
        return (
          <div className="my-6 border border-border/50 bg-card/40 backdrop-blur-md shadow-sm relative overflow-hidden group max-w-full">
            <div className="absolute top-0 left-0 w-full h-[1px] bg-primary/50 shadow-[0_0_8px_2px_rgba(var(--primary-rgb),0.5)] -translate-y-full group-hover:animate-[scan_2s_ease-in-out_infinite] z-10" style={{ animationName: 'scan' }}></div>
            <div className="flex items-center justify-between px-3 py-2 bg-muted/30 border-b border-border/50 relative z-20 overflow-hidden">
              <div className="flex items-center gap-2 min-w-0">
                <Wrench weight="light" size={14} className="text-primary/70" />
                <span className="text-[10px] uppercase tracking-[0.2em] text-foreground/80 font-mono truncate">
                  {agent} <span className="text-muted-foreground">executing</span> {tool}
                </span>
              </div>
              <CustomSpinner />
            </div>
            <div className="p-4 bg-muted/10 font-mono text-[10px] text-muted-foreground overflow-x-auto max-h-48 overflow-y-auto whitespace-pre-wrap break-words relative z-20 overflow-wrap-anywhere">
              <code>{children}</code>
            </div>
          </div>
        );
      }
      if (!inline && type === "tool-result") {
        return (
          <div className="my-6 border border-green-500/30 bg-card/40 backdrop-blur-md shadow-sm max-w-full overflow-hidden">
            <div className="flex items-center justify-between px-3 py-2 bg-green-500/10 border-b border-green-500/20">
              <div className="flex items-center gap-2 min-w-0">
                <Database weight="light" size={14} className="text-green-500/90" />
                <span className="text-[10px] uppercase tracking-[0.2em] text-foreground/80 font-mono truncate">
                  {agent} <span className="text-muted-foreground">received</span> {tool} output
                </span>
              </div>
              <CheckCircle weight="light" size={12} className="text-green-500/70 shadow-[0_0_10px_rgba(34,197,94,0.3)] rounded-full shrink-0" />
            </div>
            <div className="p-4 bg-green-500/5 font-mono text-[10px] text-foreground/70 overflow-x-auto max-h-48 overflow-y-auto whitespace-pre-wrap break-words relative z-20 overflow-wrap-anywhere">
              <code>{tryFormatJson(String(children))}</code>
            </div>
          </div>
        );
      }
      return !inline ? (
        <div className="bg-muted/10 border border-border/50 p-4 my-4 font-mono text-[11px] overflow-x-auto shadow-inner max-w-full break-words whitespace-pre-wrap overflow-wrap-anywhere">
          <code className={className} {...props}>
            {children}
          </code>
        </div>
      ) : (
        <code className="bg-muted/50 border border-border/50 px-1.5 py-0.5 font-mono text-[11px] text-primary break-all" {...props}>
          {children}
        </code>
      );
    },
    blockquote({ children }: any) {
      return (
        <blockquote className="border-l-4 border-primary pl-4 py-3 my-6 bg-primary/5 text-muted-foreground font-serif text-sm italic shadow-[inset_10px_0_20px_-10px_color-mix(in_srgb,var(--primary)_10%,transparent)] break-words">
          {children}
        </blockquote>
      );
    },
  }), [displayedText]);

  return (
    <div data-testid="streaming-view" className="flex-1 px-6 py-12 md:px-12 lg:px-24 bg-background overflow-y-auto h-screen">
      <div className="max-w-7xl mx-auto flex flex-col gap-16 pb-24 animate-in fade-in slide-in-from-bottom-8 duration-1000">
        <StreamingHeader />

        <div 
          className="relative group flex h-[850px] w-full overflow-hidden" 
          ref={containerRef}
          onMouseMove={handleMouseMove}
          onMouseEnter={() => setIsHovered(true)}
          onMouseLeave={() => setIsHovered(false)}
        >
          {/* Unified Frame */}
          <div className="relative border border-border bg-card/40 backdrop-blur-md transition-colors duration-500 group-hover:border-primary/50 flex-1 flex flex-col h-full overflow-hidden min-w-0">
            {/* Interactive Lighting Overlay */}
            <div 
              className="pointer-events-none absolute -inset-px transition-opacity duration-300 z-10"
              style={{
                opacity: isHovered ? 1 : 0,
                background: `radial-gradient(1000px circle at ${mousePosition.x}px ${mousePosition.y}px, color-mix(in srgb, var(--primary) 8%, transparent), transparent 40%)`,
              }}
            />

            {/* Textures */}
            <div className="absolute inset-0 opacity-[0.03] bg-[url('data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSI0IiBoZWlnaHQ9IjQiPjxyZWN0IHdpZHRoPSI0IiBoZWlnaHQ9IjQiIGZpbGw9IiNmZmYiIGZpbGwtb3BhY2l0eT0iMC4wNSIvPjwvc3ZnPg==')] pointer-events-none mix-blend-overlay z-0"></div>
            <div className="absolute inset-0 bg-[linear-gradient(to_right,#80808012_1px,transparent_1px),linear-gradient(to_bottom,#80808012_1px,transparent_1px)] bg-[size:32px_32px] pointer-events-none z-0"></div>

            {/* Header / Title Bar */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-border/50 bg-muted/20 shrink-0 relative z-20">
              <div className="flex items-center gap-3">
                <Terminal size={20} className="text-primary/70" />
                <span className="text-[11px] uppercase tracking-[0.4em] text-muted-foreground font-mono font-bold">Orchestrator.System_Telemetry</span>
              </div>
              <div className="flex items-center gap-4">
                 <div className="flex gap-2">
                    <div className="w-2 h-2 bg-destructive/50"></div>
                    <div className="w-2 h-2 bg-primary/50"></div>
                    <div className="w-2 h-2 bg-green-500/50"></div>
                 </div>
                 <div className="flex items-center gap-2 border-l border-border/50 pl-4">
                    <div className="w-2 h-2 rounded-full bg-green-500 animate-pulse"></div>
                    <span className="text-[9px] uppercase tracking-widest text-green-500 font-mono font-bold underline decoration-green-500/30 underline-offset-4">Live.Link</span>
                 </div>
              </div>
            </div>

            {/* System Log Section */}
            <div className="flex-1 min-h-0 overflow-hidden relative z-20" ref={logContainerRef}>
              <ScrollArea 
                className="h-full [&_[data-radix-scroll-area-viewport]]:p-8 [&_[data-radix-scroll-area-viewport]]:md:p-12 [&_[data-radix-scroll-area-thumb]]:!bg-primary/50"
                viewportRef={logViewportRef}
                onScroll={handleLogScroll}
              >
                <OrchestratorLogContent 
                  orchestratorText={processedText} 
                  displayedText={displayedText}
                  reservedHeight={reservedHeight}
                  markdownComponents={markdownComponents}
                />
              </ScrollArea>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
});
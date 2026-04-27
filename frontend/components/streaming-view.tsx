"use client";

import { useRef, useEffect, useState, useMemo, useCallback, memo } from "react";
import { Terminal, Brain, Wrench, Database, CheckCircle, ListChecks } from "@phosphor-icons/react";
import ReactMarkdown from "react-markdown";
import type { Components } from "react-markdown";
import type { PipelineStep } from "@/lib/types";

type TodoItem = {
  status?: string;
  content?: React.ReactNode;
};

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

const OrchestratorLogContent = memo(function OrchestratorLogContent({
  orchestratorText,
  displayedText,
  markdownComponents,
}: {
  orchestratorText: string;
  displayedText: string;
  markdownComponents: Components;
}) {
  return (
    <div className="transition-all duration-300 ease-out">
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

const TodoManifest = memo(function TodoManifest({ todos, className }: { todos: TodoItem[]; className?: string }) {
  if (!todos || todos.length === 0) return null;
  
  return (
    <div className={`border-b border-primary/20 bg-card/80 backdrop-blur-xl shadow-md shrink-0 relative z-30 ${className}`}>
      <div className="flex items-center gap-2 px-6 py-3 bg-primary/10 border-b border-primary/10">
        <ListChecks weight="light" size={18} className="text-primary/90" />
        <span className="text-[10px] uppercase tracking-[0.3em] text-primary font-mono font-bold">Research Manifest</span>
      </div>
      <div className="p-4 flex flex-col gap-2 max-h-[220px] overflow-y-auto scrollbar-thin scrollbar-thumb-primary/30 scrollbar-track-transparent">
        {todos.map((t, i) => {
          const isDone = t.status === 'done' || t.status === 'completed';
          const isProgress = t.status === 'in_progress';
          return (
            <div key={i} className={`flex items-start gap-3 p-2 border border-border/30 bg-background/40 transition-all duration-500 ${isProgress ? 'border-primary/40 shadow-[inset_2px_0_0_0_var(--primary)]' : isDone ? 'opacity-60' : 'opacity-40'}`}>
              <div className="mt-0.5 shrink-0">
                {isDone ? (
                  <div className="w-3.5 h-3.5 flex items-center justify-center border border-primary/50 bg-primary/10 text-primary text-[9px] font-mono">✓</div>
                ) : isProgress ? (
                  <div className="w-3.5 h-3.5 flex items-center justify-center text-primary">
                    <CustomSpinner />
                  </div>
                ) : (
                  <div className="w-3.5 h-3.5 border border-border/50" />
                )}
              </div>
              <span className={`font-mono text-[11px] min-w-0 flex-1 break-words ${isProgress ? 'text-foreground' : 'text-muted-foreground'}`}>
                {t.content}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
});

export default memo(function StreamingView({ orchestratorText, pipelineSteps }: { orchestratorText: string; pipelineSteps: PipelineStep[] }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const spotlightRef = useRef<HTMLDivElement>(null);
  const logViewportRef = useRef<HTMLDivElement>(null);
  const displayedTextRef = useRef("");
  const pointerFrameRef = useRef<number | null>(null);
  const pendingPointerRef = useRef({ x: 0, y: 0 });
  const [isLogAutoScrolling, setIsLogAutoScrolling] = useState(true);

  const [displayedText, setDisplayedText] = useState("");

  const latestTodos = useMemo(() => {
    for (let i = pipelineSteps.length - 1; i >= 0; i--) {
      const tool = pipelineSteps[i].tools.find(t => t.tool === 'write_todos');
      const args = tool?.args as { todos?: unknown[] } | undefined;
      if (Array.isArray(args?.todos)) {
        return args.todos as TodoItem[];
      }
    }
    return null;
  }, [pipelineSteps]);

  const cleanOrchestratorText = useMemo(() => {
    return orchestratorText.replace(/\n\n```tool-call\|[^|]*\|write_todos\n[\s\S]*?```/g, '');
  }, [orchestratorText]);

  useEffect(() => {
    displayedTextRef.current = displayedText;
  }, [displayedText]);

  useEffect(() => {
    let animationFrameId: number | null = null;

    const tick = () => {
      const current = displayedTextRef.current;

      if (current === cleanOrchestratorText) return;

      let nextText: string;
      if (cleanOrchestratorText.length < current.length || !cleanOrchestratorText.startsWith(current)) {
        nextText = cleanOrchestratorText;
      } else {
        const remaining = cleanOrchestratorText.length - current.length;
        const stepSize = Math.max(3, Math.ceil(remaining * 0.2));
        nextText = cleanOrchestratorText.slice(0, current.length + stepSize);
      }

      displayedTextRef.current = nextText;
      setDisplayedText(nextText);

      if (nextText !== cleanOrchestratorText) {
        animationFrameId = requestAnimationFrame(tick);
      }
    };

    animationFrameId = requestAnimationFrame(tick);
    return () => {
      if (animationFrameId !== null) cancelAnimationFrame(animationFrameId);
    };
  }, [cleanOrchestratorText]);

  useEffect(() => {
    return () => {
      if (pointerFrameRef.current !== null) cancelAnimationFrame(pointerFrameRef.current);
    };
  }, []);

  useEffect(() => {
    if (isLogAutoScrolling && logViewportRef.current) {
      logViewportRef.current.scrollTop = logViewportRef.current.scrollHeight;
    }
  }, [displayedText, isLogAutoScrolling]);

  const handleLogScroll = (e: React.UIEvent<HTMLDivElement>) => {
    const viewport = e.currentTarget;
    const isNearBottom = viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight < 100;
    setIsLogAutoScrolling(isNearBottom);
  };

  const handleMouseMove = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
    if (!containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    pendingPointerRef.current = { x: e.clientX - rect.left, y: e.clientY - rect.top };

    if (pointerFrameRef.current !== null) return;

    pointerFrameRef.current = requestAnimationFrame(() => {
      pointerFrameRef.current = null;
      spotlightRef.current?.style.setProperty("--spotlight-x", `${pendingPointerRef.current.x}px`);
      spotlightRef.current?.style.setProperty("--spotlight-y", `${pendingPointerRef.current.y}px`);
    });
  }, []);

  const processedText = useMemo(() => {
    if (!displayedText) return "";
    let text = displayedText;
    
    // Handle thinking tags (including unclosed)
    if (text.includes("<thinking>")) {
      if (text.includes("</thinking>")) {
        text = text.replace(/<thinking>([\s\S]*?)<\/thinking>/g, '\n```thinking\n$1\n```\n');
      } else {
        text = text.replace(/<thinking>([\s\S]*)$/g, '\n```thinking\n$1\n```\n');
      }
    }

    // Handle tool_use tags (including unclosed)
    if (text.includes("<tool_use>")) {
      if (text.includes("</tool_use>")) {
        text = text.replace(/<tool_use>([\s\S]*?)<\/tool_use>/g, '\n```tool_use\n$1\n```\n');
      } else {
        text = text.replace(/<tool_use>([\s\S]*)$/g, '\n```tool_use\n$1\n```\n');
      }
    }

    return text.replace(/\\n/g, '\n');
  }, [displayedText]);

  const markdownComponents = useMemo<Components>(() => ({
    h3({ children, ...props }: React.HTMLAttributes<HTMLHeadingElement>) {
      if (String(children) === "TASK_PLAN_HEADER") {
        return <div className="text-[10px] uppercase tracking-[0.3em] text-primary/80 font-mono mt-8 mb-4 border-b border-primary/20 pb-2 flex items-center gap-2"><ListChecks size={14} /> Execution Plan</div>;
      }
      return <h3 className="text-xl font-serif tracking-tight mt-6 mb-3 text-foreground border-l-2 border-primary pl-3" {...props}>{children}</h3>;
    },
    ul({ children, ...props }: React.HTMLAttributes<HTMLUListElement>) {
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
    p({ children, ...props }: React.HTMLAttributes<HTMLParagraphElement>) {
      return <p className="font-sans text-sm text-foreground/80 leading-relaxed mb-4 break-words" {...props}>{children}</p>;
    },
    code({ inline, className, children, ...props }: React.HTMLAttributes<HTMLElement> & { inline?: boolean }) {
      const match = /language-([\w-]+)(?:\|([^|]+)\|([^|]+))?/.exec(className || "");
      const type = match ? match[1] : "";
      const agent = match ? match[2] : "";
      const tool = match ? match[3] : "";
      if (!inline && type === "thinking") {
        return (
          <div className="my-6 pl-4 border-l-2 border-border/40 group transition-all duration-500 max-w-full overflow-hidden">
            <div className="flex items-center gap-2 mb-2 opacity-50">
              <Brain weight="regular" size={14} />
              <span className="text-[10px] uppercase tracking-widest font-mono font-medium">Internal Monologue</span>
            </div>
            <div className="font-serif text-[14px] text-muted-foreground/80 italic leading-relaxed break-words overflow-wrap-anywhere">
              {children}
            </div>
          </div>
        );
      }
      if (!inline && type === "tool-call") {
        if (tool === "execute" || tool === "python") {
          let cmd = String(children);
          try {
            const parsed = JSON.parse(cmd);
            if (parsed.command) cmd = parsed.command;
            if (parsed.code) cmd = parsed.code;
          } catch {}
          return (
            <div className="my-6 border border-border/30 bg-[#000] shadow-sm relative overflow-hidden max-w-full">
              <div className="flex items-center justify-between px-3 py-2 bg-[#0a0a0a] border-b border-border/20">
                <div className="flex items-center gap-2">
                  <Terminal size={14} className="text-muted-foreground" />
                  <span className="text-[10px] uppercase tracking-widest text-muted-foreground font-mono">
                    {agent ? `${agent} • shell` : 'shell'}
                  </span>
                </div>
              </div>
              <div className="p-4 font-mono text-[12px] text-[#e5e5e5] overflow-x-auto max-h-64 overflow-y-auto whitespace-pre-wrap break-words scrollbar-thin scrollbar-thumb-border/20 scrollbar-track-transparent">
                <code>$ {cmd}</code>
              </div>
            </div>
          );
        }
        return (
          <div className="my-6 border border-border/30 bg-card shadow-sm relative overflow-hidden max-w-full">
            <div className="flex items-center justify-between px-3 py-2 bg-muted/20 border-b border-border/30">
              <div className="flex items-center gap-2">
                <Wrench weight="regular" size={14} className="text-muted-foreground" />
                <span className="text-[10px] uppercase tracking-widest text-muted-foreground font-mono">
                  {agent ? `${agent} • ${tool}` : tool}
                </span>
              </div>
              <CustomSpinner />
            </div>
            <div className="p-4 bg-transparent font-mono text-[12px] text-muted-foreground overflow-x-auto max-h-64 overflow-y-auto whitespace-pre-wrap break-words scrollbar-thin scrollbar-thumb-border/30 scrollbar-track-transparent">
              <code>{children}</code>
            </div>
          </div>
        );
      }

      if (!inline && type === "tool-result") {
        return (
          <div className="my-6 border border-border/30 bg-card shadow-sm max-w-full overflow-hidden">
            <div className="flex items-center justify-between px-3 py-2 bg-muted/20 border-b border-border/30">
              <div className="flex items-center gap-2">
                <Database weight="regular" size={14} className="text-muted-foreground" />
                <span className="text-[10px] uppercase tracking-widest text-muted-foreground font-mono">
                  {agent ? `${agent} • result` : 'result'}
                </span>
              </div>
              <CheckCircle weight="regular" size={14} className="text-muted-foreground" />
            </div>
            <div className="p-4 bg-transparent font-mono text-[12px] text-foreground/80 overflow-x-auto max-h-64 overflow-y-auto whitespace-pre-wrap break-words scrollbar-thin scrollbar-thumb-border/30 scrollbar-track-transparent">
              <code>{tryFormatJson(String(children))}</code>
            </div>
          </div>
        );
      }
      return !inline ? (
        <div className="bg-muted/10 border border-border/30 p-4 my-6 font-mono text-[12px] overflow-x-auto max-w-full break-words whitespace-pre-wrap overflow-wrap-anywhere">
          <code className={className} {...props}>
            {children}
          </code>
        </div>
      ) : (
        <code className="bg-muted/30 border border-border/30 px-1 py-0.5 font-mono text-[11px] text-foreground break-all" {...props}>
          {children}
        </code>
      );
    },
    blockquote({ children }: React.BlockquoteHTMLAttributes<HTMLQuoteElement>) {
      return (
        <blockquote className="border-l-4 border-primary pl-4 py-3 my-6 bg-primary/5 text-muted-foreground font-serif text-sm italic shadow-[inset_10px_0_20px_-10px_color-mix(in_srgb,var(--primary)_10%,transparent)] break-words">
          {children}
        </blockquote>
      );
    },
  }), []);

  return (
    <div data-testid="streaming-view" className="flex-1 px-6 py-12 md:px-12 lg:px-24 bg-background">
      <div className="max-w-7xl mx-auto flex flex-col gap-16 pb-24 animate-in fade-in slide-in-from-bottom-8 duration-1000">
        <StreamingHeader />

        <div 
          className="relative group flex h-[850px] w-full overflow-hidden" 
          ref={containerRef}
          onMouseMove={handleMouseMove}
        >
          {/* Unified Frame */}
          <div className="relative border border-border bg-card/40 backdrop-blur-md transition-colors duration-500 group-hover:border-primary/50 flex-1 flex flex-col h-full overflow-hidden min-w-0">
            {/* Interactive Lighting Overlay */}
            <div 
              ref={spotlightRef}
              className="pointer-events-none absolute -inset-px opacity-0 transition-opacity duration-300 z-10 group-hover:opacity-100"
              style={{
                background: "radial-gradient(1000px circle at var(--spotlight-x, 50%) var(--spotlight-y, 50%), color-mix(in srgb, var(--primary) 8%, transparent), transparent 40%)",
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
            <div className="flex-1 min-h-0 relative z-20 flex flex-col">
              <div 
                ref={logViewportRef}
                onScroll={handleLogScroll}
                className="absolute inset-0 overflow-y-auto overflow-x-hidden scrollbar-thin scrollbar-thumb-primary/50 scrollbar-track-transparent"
              >
                <TodoManifest todos={latestTodos ?? []} className="sticky top-0" />
                <div className="p-8 md:p-12">
                  <OrchestratorLogContent 
                    orchestratorText={processedText} 
                    displayedText={displayedText}
                    markdownComponents={markdownComponents}
                  />
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
});

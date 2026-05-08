"use client";

import { Children, isValidElement, useRef, useEffect, useState, useMemo, useCallback, memo } from "react";
import type { ReactNode } from "react";
import {
  ArrowDown,
  Brain,
  CaretDown,
  ChartBar,
  CheckCircle,
  CircleNotch,
  Code,
  Database,
  ListChecks,
  MagnifyingGlass,
  NotePencil,
  Wrench,
} from "@phosphor-icons/react";
import ReactMarkdown from "react-markdown";
import type { Components } from "react-markdown";

const tryFormatJson = (str: string | undefined): string => {
  if (!str) return "";
  try {
    const parsed = JSON.parse(str);
    return JSON.stringify(parsed, null, 2);
  } catch {
    return str;
  }
};

const normalizeToolName = (name: string): string => {
  return name
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
};

const titleCase = (value: string): string => {
  return normalizeToolName(value)
    .split(" ")
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
};

const isRecord = (value: unknown): value is Record<string, unknown> => {
  return typeof value === "object" && value !== null && !Array.isArray(value);
};

const truncateText = (value: string, limit: number): string => {
  const normalized = value.replace(/\s+/g, " ").trim();
  return normalized.length > limit ? `${normalized.slice(0, limit - 3)}...` : normalized;
};

const nodeContainsStatusMarker = (node: ReactNode): boolean => {
  if (typeof node === "string") return node.startsWith("STATUS:");
  if (typeof node === "number" || typeof node === "boolean" || node == null) return false;
  if (Array.isArray(node)) return node.some(nodeContainsStatusMarker);
  if (isValidElement<{ children?: ReactNode }>(node)) return nodeContainsStatusMarker(node.props.children);
  return false;
};

const statusLabel = (status: string): string => {
  if (status === "done" || status === "completed") return "Done";
  if (status === "in_progress" || status === "running") return "Active";
  return "Pending";
};

const payloadMeta = (value: string) => {
  const trimmed = value.trim();
  let kind = "text";

  try {
    const parsed = JSON.parse(trimmed);
    kind = Array.isArray(parsed) ? "array" : typeof parsed;
  } catch {
    kind = trimmed.startsWith("{") || trimmed.startsWith("[") ? "partial json" : "text";
  }

  return {
    kind,
    lines: Math.max(1, value.split("\n").length),
    chars: value.length,
  };
};

const ToolIcon = memo(function ToolIcon({ tool, size = 18 }: { tool?: string; size?: number }) {
  const normalized = (tool ?? "").toLowerCase();
  if (normalized.includes("fred") || normalized.includes("fmp") || normalized.includes("data") || normalized.includes("sql")) {
    return <Database weight="regular" size={size} />;
  }
  if (normalized.includes("search") || normalized.includes("fetch") || normalized.includes("web")) {
    return <MagnifyingGlass weight="regular" size={size} />;
  }
  if (normalized.includes("python") || normalized.includes("execute") || normalized.includes("code")) {
    return <Code weight="regular" size={size} />;
  }
  if (normalized.includes("chart") || normalized.includes("analysis")) {
    return <ChartBar weight="regular" size={size} />;
  }
  if (normalized.includes("todo")) {
    return <ListChecks weight="regular" size={size} />;
  }
  if (normalized.includes("write") || normalized.includes("report") || normalized.includes("file")) {
    return <NotePencil weight="regular" size={size} />;
  }
  return <Wrench weight="regular" size={size} />;
});

type ToolActivityVariant = "call" | "command";

const toolActivityPresentation = (tool: string, variant: ToolActivityVariant) => {
  const normalized = tool.toLowerCase();

  if (variant === "command" || normalized.includes("python") || normalized.includes("execute") || normalized.includes("code")) {
    return {
      activityLabel: "code",
      iconClass: "text-amber-700 dark:text-amber-400",
      nameClass: "font-mono text-[13px] font-semibold text-foreground",
      labelClass: "text-amber-700 dark:text-amber-400",
      summaryClass: "font-mono text-[12px] leading-6 text-foreground/75",
      detailsClass: "border-amber-700/35 dark:border-amber-500/35",
      detailsLabel: "Command details",
    };
  }

  if (normalized.includes("fred") || normalized.includes("fmp") || normalized.includes("data") || normalized.includes("sql")) {
    return {
      activityLabel: "data",
      iconClass: "text-sky-700 dark:text-sky-400",
      nameClass: "font-sans text-sm font-semibold text-foreground",
      labelClass: "text-sky-700 dark:text-sky-400",
      summaryClass: "font-serif text-[15px] leading-6 text-foreground/80",
      detailsClass: "border-sky-700/30 dark:border-sky-500/30",
      detailsLabel: "Query details",
    };
  }

  if (normalized.includes("search") || normalized.includes("fetch") || normalized.includes("web")) {
    return {
      activityLabel: "search",
      iconClass: "text-teal-700 dark:text-teal-400",
      nameClass: "font-sans text-sm font-semibold text-foreground",
      labelClass: "text-teal-700 dark:text-teal-400",
      summaryClass: "font-serif text-[15px] leading-6 text-foreground/80",
      detailsClass: "border-teal-700/30 dark:border-teal-500/30",
      detailsLabel: "Lookup details",
    };
  }

  if (normalized.includes("write") || normalized.includes("report") || normalized.includes("file")) {
    return {
      activityLabel: "write",
      iconClass: "text-rose-700 dark:text-rose-400",
      nameClass: "font-sans text-sm font-semibold text-foreground",
      labelClass: "text-rose-700 dark:text-rose-400",
      summaryClass: "font-serif text-[15px] leading-6 text-foreground/80",
      detailsClass: "border-rose-700/30 dark:border-rose-500/30",
      detailsLabel: "Write details",
    };
  }

  if (normalized.includes("chart") || normalized.includes("analysis")) {
    return {
      activityLabel: "analyze",
      iconClass: "text-indigo-700 dark:text-indigo-400",
      nameClass: "font-sans text-sm font-semibold text-foreground",
      labelClass: "text-indigo-700 dark:text-indigo-400",
      summaryClass: "font-serif text-[15px] leading-6 text-foreground/80",
      detailsClass: "border-indigo-700/30 dark:border-indigo-500/30",
      detailsLabel: "Analysis details",
    };
  }

  return {
    activityLabel: "tool",
    iconClass: "text-primary",
    nameClass: "font-sans text-sm font-semibold text-foreground",
    labelClass: "text-primary",
    summaryClass: "font-serif text-[15px] leading-6 text-foreground/80",
    detailsClass: "border-border/70",
    detailsLabel: "Technical details",
  };
};

const summarizePayload = (payload: string, variant: ToolActivityVariant): string => {
  const trimmed = payload.trim();
  if (!trimmed) return "No arguments provided.";
  if (variant === "command") return "Running code or shell work for the current research step.";

  try {
    const parsed: unknown = JSON.parse(trimmed);

    if (isRecord(parsed)) {
      const keys = Object.keys(parsed);
      if (keys.length === 0) return "Called without arguments.";
      return `Arguments include ${keys.slice(0, 4).map(titleCase).join(", ")}${keys.length > 4 ? "..." : ""}.`;
    }

    if (Array.isArray(parsed)) return `Arguments include ${parsed.length.toLocaleString()} entries.`;
  } catch {
    return truncateText(trimmed, 140);
  }

  return truncateText(trimmed, 140);
};

const ToolActivityBlock = memo(function ToolActivityBlock({
  agent,
  tool,
  variant,
  payload,
}: {
  agent: string;
  tool?: string;
  variant: ToolActivityVariant;
  payload: string;
}) {
  const isCommand = variant === "command";
  const meta = payloadMeta(payload);
  const rawToolName = tool || "tool";
  const displayTool = titleCase(rawToolName);
  const agentLabel = agent ? titleCase(agent) : "Orchestrator";
  const statusLabel = isCommand ? "Running" : "Called";
  const summary = summarizePayload(payload, variant);
  const presentation = toolActivityPresentation(rawToolName, variant);

  return (
    <section className="not-prose my-4 max-w-full overflow-hidden py-1">
      <div className="flex items-start gap-3">
        <div className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center ${presentation.iconClass}`}>
          <ToolIcon tool={tool} size={17} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-1">
            <span className={`font-sans text-[10px] uppercase tracking-[0.14em] ${presentation.labelClass}`}>
              {presentation.activityLabel}
            </span>
            <span className={presentation.nameClass}>{displayTool}</span>
            <span className="max-w-full font-mono text-[11px] text-muted-foreground overflow-wrap-anywhere">
              {rawToolName}
            </span>
            <span className="font-sans text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
              {statusLabel}
            </span>
            <span className="hidden font-sans text-xs text-muted-foreground sm:inline">by {agentLabel}</span>
          </div>

          <p className={`mt-1 overflow-wrap-anywhere ${presentation.summaryClass}`}>{summary}</p>

          <details className="group/details mt-2">
            <summary className="flex cursor-pointer list-none flex-wrap items-center gap-x-2 gap-y-1 font-sans text-[10px] uppercase tracking-[0.14em] text-muted-foreground [&::-webkit-details-marker]:hidden">
              <span>{presentation.detailsLabel}</span>
              <span className="flex min-w-0 items-center gap-1">
                {meta.kind} / {meta.lines} lines / {meta.chars.toLocaleString()} chars
                <CaretDown size={12} className="transition-transform group-open/details:rotate-180" />
              </span>
            </summary>
            <div className={`mt-2 border-l pl-3 ${presentation.detailsClass}`}>
              <code className="block max-h-72 overflow-auto whitespace-pre-wrap break-words font-mono text-[12px] leading-relaxed text-muted-foreground overflow-wrap-anywhere">
                {isCommand ? `$ ${payload}` : payload}
              </code>
            </div>
          </details>
        </div>
      </div>
    </section>
  );
});

const ProgressMark = memo(function ProgressMark({ status }: { status?: string }) {
  const isDone = status === "done" || status === "completed";
  const isProgress = status === "in_progress" || status === "running";

  if (isDone) {
    return (
      <div className="flex h-4 w-4 items-center justify-center border border-green-500/40 bg-green-500/10 text-green-700 dark:text-green-400">
        <CheckCircle weight="fill" size={11} />
      </div>
    );
  }

  if (isProgress) {
    return (
      <div className="flex h-4 w-4 items-center justify-center text-primary">
        <CircleNotch size={14} className="animate-spin" />
      </div>
    );
  }

  return <div className="h-4 w-4 border border-border bg-background" />;
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
        <div
          data-testid="orchestrator-log-content"
          className="prose prose-lg max-w-none break-words dark:prose-invert prose-headings:font-serif prose-headings:tracking-tight prose-p:font-serif prose-p:text-foreground/85 prose-p:leading-7 prose-strong:text-foreground prose-a:text-primary overflow-wrap-anywhere"
        >
          <ReactMarkdown components={markdownComponents}>{orchestratorText}</ReactMarkdown>
          <span className="ml-1 inline-block h-4 w-1 animate-pulse bg-primary align-middle" />
        </div>
      ) : (
        <div className="flex items-center gap-3 border-l-2 border-primary/40 pl-4 font-serif text-lg text-muted-foreground">
          <CircleNotch size={16} className="animate-spin text-primary" />
          Opening live research ledger...
        </div>
      )}
    </div>
  );
});

export default memo(function StreamingView({
  orchestratorText,
}: {
  orchestratorText: string;
}) {
  const logViewportRef = useRef<HTMLDivElement>(null);
  const displayedTextRef = useRef("");
  const [isLogAutoScrolling, setIsLogAutoScrolling] = useState(true);
  const [displayedText, setDisplayedText] = useState("");

  const cleanOrchestratorText = useMemo(() => {
    return orchestratorText.replace(/\n\n```tool-call\|[^|]*\|write_todos\n[\s\S]*?```/g, "");
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
    if (isLogAutoScrolling && logViewportRef.current) {
      logViewportRef.current.scrollTop = logViewportRef.current.scrollHeight;
    }
  }, [displayedText, isLogAutoScrolling]);

  const handleLogScroll = (e: React.UIEvent<HTMLDivElement>) => {
    const viewport = e.currentTarget;
    const isNearBottom = viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight < 100;
    setIsLogAutoScrolling((current) => (current === isNearBottom ? current : isNearBottom));
  };

  const scrollToLatest = useCallback(() => {
    const viewport = logViewportRef.current;
    if (!viewport) return;
    viewport.scrollTo({ top: viewport.scrollHeight, behavior: "smooth" });
    setIsLogAutoScrolling(true);
  }, []);

  const processedText = useMemo(() => {
    if (!displayedText) return "";
    let text = displayedText;

    if (text.includes("<thinking>")) {
      if (text.includes("</thinking>")) {
        text = text.replace(/<thinking>([\s\S]*?)<\/thinking>/g, "\n```thinking\n$1\n```\n");
      } else {
        text = text.replace(/<thinking>([\s\S]*)$/g, "\n```thinking\n$1\n```\n");
      }
    }

    if (text.includes("<tool_use>")) {
      if (text.includes("</tool_use>")) {
        text = text.replace(/<tool_use>([\s\S]*?)<\/tool_use>/g, "\n```tool_use\n$1\n```\n");
      } else {
        text = text.replace(/<tool_use>([\s\S]*)$/g, "\n```tool_use\n$1\n```\n");
      }
    }

    return text.replace(/\\n/g, "\n");
  }, [displayedText]);

  const markdownComponents = useMemo<Components>(
    () => ({
      h3({ children, ...props }: React.HTMLAttributes<HTMLHeadingElement>) {
        if (String(children) === "TASK_PLAN_HEADER") {
          return (
            <div className="not-prose mb-4 mt-8 flex items-center gap-2 border-b border-border pb-2 text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
              <ListChecks size={14} />
              Research Plan
            </div>
          );
        }
        return (
          <h3 className="mb-3 mt-7 border-l-2 border-primary pl-3 text-2xl font-serif leading-tight tracking-tight text-foreground" {...props}>
            {children}
          </h3>
        );
      },
      ul({ children, ...props }: React.HTMLAttributes<HTMLUListElement>) {
        const hasStatusItems = Children.toArray(children).some(nodeContainsStatusMarker);
        if (!hasStatusItems) {
          return (
            <ul className="my-5 list-disc space-y-2 pl-6 marker:text-primary/60" {...props}>
              {children}
            </ul>
          );
        }
        return (
          <ul className="not-prose my-5 flex max-w-full flex-col gap-0 overflow-hidden border border-border bg-card/80" {...props}>
            {children}
          </ul>
        );
      },
      li({ children }: React.HTMLAttributes<HTMLElement>) {
        const childArray = Array.isArray(children) ? [...children] : [children];
        const firstChild = childArray[0];
        let status = "";
        if (typeof firstChild === "string" && firstChild.startsWith("STATUS:")) {
          const match = firstChild.match(/^STATUS:(done|completed|in_progress|pending)\|(.*)/);
          if (match) {
            status = match[1];
            childArray[0] = match[2];
          }
        }
        if (status) {
          const isDone = status === "done" || status === "completed";
          const isProgress = status === "in_progress";
          return (
            <li
              className={`flex max-w-full list-none items-start gap-4 overflow-hidden border-b border-border/70 p-3.5 last:border-0 ${
                isProgress ? "bg-primary/5" : isDone ? "bg-muted/15 text-muted-foreground" : "text-muted-foreground/70"
              }`}
            >
              <div className="mt-0.5 shrink-0">
                <ProgressMark status={status} />
              </div>
              <div className="min-w-0 flex-1">
                <div className={`break-words font-sans text-sm leading-relaxed ${isProgress ? "text-foreground" : ""}`}>
                  {childArray}
                </div>
                <div className="mt-1 font-sans text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
                  {statusLabel(status)}
                </div>
              </div>
            </li>
          );
        }
        return <li className="break-words font-serif text-[16px] leading-7 text-foreground/80">{children}</li>;
      },
      p({ children, ...props }: React.HTMLAttributes<HTMLParagraphElement>) {
        return (
          <p className="mb-5 break-words font-serif text-[17px] leading-7 text-foreground/85" {...props}>
            {children}
          </p>
        );
      },
      pre({ children }) {
        return <>{children}</>;
      },
      code({ inline, className, children, ...props }: React.HTMLAttributes<HTMLElement> & { inline?: boolean }) {
        const match = /language-([\w-]+)(?:\|([^|]+)\|([^|]+))?/.exec(className || "");
        const type = match ? match[1] : "";
        const agent = match ? match[2] : "";
        const tool = match ? match[3] : "";
        if (!inline && type === "thinking") {
          return (
            <div className="not-prose my-6 max-w-full overflow-hidden border-l-2 border-border/70 bg-muted/10 py-3 pl-4 pr-3">
              <div className="mb-2 flex items-center gap-2 font-sans text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
                <Brain weight="regular" size={14} />
                Reasoning Notes
              </div>
              <div className="break-words font-serif text-[15px] italic leading-6 text-muted-foreground/90 overflow-wrap-anywhere">
                {children}
              </div>
            </div>
          );
        }
        if (!inline && type === "tool-call") {
          if (tool === "execute" || tool === "python" || tool === "execute_python") {
            let cmd = String(children);
            try {
              const parsed = JSON.parse(cmd);
              if (parsed.command) cmd = parsed.command;
              if (parsed.code) cmd = parsed.code;
            } catch {}
            return <ToolActivityBlock agent={agent} tool={tool || "execute"} variant="command" payload={cmd} />;
          }
          return <ToolActivityBlock agent={agent} tool={tool} variant="call" payload={tryFormatJson(String(children))} />;
        }

        if (!inline && type === "tool-result") {
          return null;
        }
        return !inline ? (
          <div className="not-prose my-6 max-w-full overflow-x-auto border border-border bg-muted/20 p-4 font-mono text-[12px] whitespace-pre-wrap break-words text-muted-foreground overflow-wrap-anywhere">
            <code className={className} {...props}>
              {children}
            </code>
          </div>
        ) : (
          <code className="break-all border border-border bg-muted/30 px-1 py-0.5 font-mono text-[11px] text-foreground" {...props}>
            {children}
          </code>
        );
      },
      blockquote({ children }: React.BlockquoteHTMLAttributes<HTMLQuoteElement>) {
        return (
          <blockquote className="my-6 break-words border-l-4 border-primary bg-primary/5 py-3 pl-4 font-serif text-base italic leading-7 text-muted-foreground">
            {children}
          </blockquote>
        );
      },
    }),
    [],
  );

  return (
    <div data-testid="streaming-view" className="flex min-h-0 flex-1 bg-background px-4 py-5 md:px-8 md:py-8 lg:px-12">
      <section className="relative mx-auto flex min-h-0 w-full max-w-5xl flex-1 flex-col overflow-hidden animate-in fade-in slide-in-from-bottom-4 duration-500">
        <div className="flex shrink-0 flex-col gap-4 border-b border-border/70 px-1 pb-5 md:flex-row md:items-center md:justify-between">
          <div className="flex min-w-0 items-start gap-4">
            <div className="mt-0.5 hidden h-10 w-10 shrink-0 items-center justify-center border border-primary/25 bg-primary/5 text-primary sm:flex">
              <Brain weight="regular" size={18} />
            </div>
            <div className="min-w-0">
              <div className="font-sans text-[10px] uppercase tracking-[0.22em] text-primary">Live Research Ledger</div>
              <h3 className="mt-1 font-serif text-2xl leading-tight tracking-tight text-foreground">Research notes</h3>
              <p className="mt-1 max-w-2xl text-sm leading-6 text-muted-foreground">
                Coordinating agents, collecting evidence, and recording material updates as they arrive.
              </p>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-3 border border-border/70 bg-muted/35 px-3 py-2 font-sans text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
            <span className="h-1.5 w-1.5 animate-pulse bg-primary" aria-hidden="true" />
            Live
          </div>
        </div>

        <div className="relative min-h-0 flex-1">
          <div
            ref={logViewportRef}
            onScroll={handleLogScroll}
            data-testid="orchestrator-log"
            className="scrollbar-editorial absolute inset-0 overflow-y-auto overflow-x-hidden px-1 py-6 md:py-8"
          >
            <OrchestratorLogContent
              orchestratorText={processedText}
              displayedText={displayedText}
              markdownComponents={markdownComponents}
            />
          </div>
          {!isLogAutoScrolling && (
            <button
              type="button"
              onClick={scrollToLatest}
              className="absolute bottom-5 right-1 z-10 inline-flex items-center gap-2 border border-primary bg-background/90 px-3 py-2 font-sans text-[10px] uppercase tracking-[0.16em] text-primary shadow-lg backdrop-blur transition-colors hover:bg-primary hover:text-primary-foreground"
            >
              <ArrowDown size={14} />
              Latest
            </button>
          )}
        </div>
      </section>
    </div>
  );
});

"use client";

import { useState, useEffect, useRef } from "react";
import type { ResearchStatus, Message, PipelineStep, ResearchReport } from "@/lib/types";

export interface UseResearchStreamOptions {
  jobId: string;
  messages: Message[];
  requestNonce?: number;
  /** When false (home intake chat), raw model `text` tokens are omitted server-side; use `user_message` SSE only. */
  streamTelemetry?: boolean;
  onNavigate?: (jobId: string) => void;
  /** First `start` SSE in a session — persist and send as `job_id` on every later request (required for same thread). */
  onJobId?: (jobId: string) => void;
  onApprovalRequired?: (jobId: string) => void;
  onConversationalFinish?: (assistantText: string) => void;
}

export interface UseResearchStreamResult {
  status: ResearchStatus;
  orchestratorText: string;
  pipelineSteps: PipelineStep[];
  report: ResearchReport | null;
  errorText: string;
  isStreamingChat: boolean;
}

export function useResearchStream({
  jobId,
  messages,
  requestNonce = 0,
  streamTelemetry = true,
  onNavigate,
  onJobId,
  onApprovalRequired,
  onConversationalFinish,
}: UseResearchStreamOptions): UseResearchStreamResult {
  const [status, setStatus] = useState<ResearchStatus>("idle");
  const [orchestratorText, setOrchestratorText] = useState("");
  const [pipelineSteps, setPipelineSteps] = useState<PipelineStep[]>([]);
  const [report, setReport] = useState<ResearchReport | null>(null);
  const [errorText, setErrorText] = useState("");
  const [isStreamingChat, setIsStreamingChat] = useState(false);

  // Keep callbacks in refs so they don't trigger effect re-runs
  const onNavigateRef = useRef(onNavigate);
  onNavigateRef.current = onNavigate;
  const onJobIdRef = useRef(onJobId);
  onJobIdRef.current = onJobId;
  const onApprovalRequiredRef = useRef(onApprovalRequired);
  onApprovalRequiredRef.current = onApprovalRequired;
  const onConversationalFinishRef = useRef(onConversationalFinish);
  onConversationalFinishRef.current = onConversationalFinish;

  const hasNavigatedRef = useRef(false);
  const currentJobIdRef = useRef(jobId);

  useEffect(() => {
    // No messages — either poll for an existing report or do nothing
    if (messages.length === 0) {
      if (!jobId) return;
      // Refresh case: poll until report is ready
      let cancelled = false;
      const poll = async (delay = 0): Promise<void> => {
        if (delay) await new Promise<void>((r) => setTimeout(r, delay));
        if (cancelled) return;
        try {
          const res = await fetch(`http://localhost:8000/api/reports/${jobId}`);
          if (res.status === 202 || res.status === 404) { poll(5000); return; }
          if (!res.ok) throw new Error(`${res.status}`);
          const data = await res.json();
          if (!cancelled) { setReport(data); setStatus("report_ready"); }
        } catch (error: unknown) {
          if (!cancelled) {
            setStatus("error");
            setErrorText(error instanceof Error ? error.message : `Could not load report for job ${jobId}.`);
          }
        }
      };
      setStatus("loading");
      poll();
      return () => { cancelled = true; };
    }

    let cancelled = false;
    let currentOrchestratorText = "";
    let hasStartedResearch = false;
    let pendingNavigationJobId: string | null = null;
    let lastUserMessageMarkdown = "";
    currentJobIdRef.current = jobId;
    hasNavigatedRef.current = false;

    const fetchReport = async (id: string) => {
      try {
        const res = await fetch(`http://localhost:8000/api/reports/${id}`);
        if (!res.ok) throw new Error(`Report fetch failed: ${res.status}`);
        const data = await res.json();
        if (!cancelled) {
          setReport(data);
          setStatus("report_ready");
        }
      } catch (error: unknown) {
        if (!cancelled) {
          setStatus("error");
          setErrorText(error instanceof Error ? error.message : String(error));
        }
      }
    };

    const run = async () => {
      setIsStreamingChat(true);
      setOrchestratorText("");
      setPipelineSteps([]);
      setErrorText("");
      setStatus("idle");

      try {
        const body: Record<string, unknown> = { messages };
        if (jobId) body.job_id = jobId;
        if (streamTelemetry === false) body.stream_telemetry = false;

        const mockScenario = typeof window !== "undefined" && window.localStorage.getItem("__cypress_stream_scenario__");
        const streamUrl = mockScenario
          ? `/api/mock-stream?scenario=${mockScenario}`
          : "http://localhost:8000/api/chat/stream";

        const response = await fetch(streamUrl, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });

        if (!response.body) throw new Error("No response body");

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        const dispatchSseJson = async (raw: string) => {
          if (raw === "[DONE]") return;
          if (!raw) return;

          try {
            const event = JSON.parse(raw);
            // Debug: log every SSE event so we can diagnose streaming issues
            console.log("[SSE]", event.type, event);
            switch (event.type) {
                  case "start":
                    currentJobIdRef.current = event.job_id;
                    pendingNavigationJobId = event.job_id;
                    if (event.job_id) {
                      onJobIdRef.current?.(event.job_id);
                    }
                    break;
                  case "text":
                    if (streamTelemetry) {
                      currentOrchestratorText += event.delta;
                      setOrchestratorText(currentOrchestratorText);
                    }
                    break;
                  case "user_message": {
                    const md = typeof event.markdown === "string" ? event.markdown : "";
                    lastUserMessageMarkdown = md;
                    if (streamTelemetry === false) {
                      // Home page: replace orchestratorText with the latest message
                      currentOrchestratorText = md;
                      setOrchestratorText(md);
                      // Detect the "Commence Deep Research" ready message and fire approval callback
                      if (md.includes("Commence Deep Research")) {
                        onApprovalRequiredRef.current?.(currentJobIdRef.current ?? pendingNavigationJobId ?? "");
                      }
                    } else {
                      // Chat page: append emit_chat_message content to the orchestrator log.
                      // The orchestrator only emits structured output via this tool (no raw text
                      // tokens), so this is the only way the log gets populated.
                      currentOrchestratorText += (currentOrchestratorText ? "\n\n---\n\n" : "") + md;
                      setOrchestratorText(currentOrchestratorText);
                    }
                    break;
                  }
                  case "agent_start":
                    if (!hasStartedResearch) {
                      hasStartedResearch = true;
                      if (!hasNavigatedRef.current && onNavigateRef.current) {
                        hasNavigatedRef.current = true;
                        onNavigateRef.current(pendingNavigationJobId ?? currentJobIdRef.current);
                      }
                      setStatus("streaming");
                      setIsStreamingChat(false);
                    }
                    setPipelineSteps((prev) => {
                      const steps = [...prev];
                      const existing = steps.find((s) => s.agent === event.agent);
                      if (existing) {
                        existing.status = "running";
                      } else {
                        steps.push({ agent: event.agent, status: "running", tools: [] });
                      }
                      return steps;
                    });
                    break;
                  case "tool_call":
                    setPipelineSteps((prev) => {
                      const steps = [...prev];
                      let step = steps.find((s) => s.agent === event.agent);
                      if (!step && event.agent === null) {
                        step = { agent: null, status: "running", tools: [] };
                        steps.push(step);
                      }
                      if (step) {
                        if (event.tool === "write_todos") {
                          const existingTool = step.tools.find((t) => t.tool === "write_todos");
                          if (existingTool) {
                            existingTool.args = event.args;
                            existingTool.status = "running";
                          } else {
                            step.tools.push({ tool: event.tool, args: event.args, status: "running" });
                          }
                        } else {
                          step.tools.push({ tool: event.tool, args: event.args, status: "running" });
                        }
                      }
                      return steps;
                    });
                    // Route tool calls to orchestrator log so it shows real-time activity
                    if (event.agent && event.tool !== "emit_chat_message") {
                      currentOrchestratorText += `\\n\\n**→ ${event.tool}**`;
                      setOrchestratorText(currentOrchestratorText);
                    }
                    break;
                  case "tool_result":
                    setPipelineSteps((prev) => {
                      const steps = [...prev];
                      const step = steps.find((s) => s.agent === event.agent);
                      if (step) {
                        const tool = step.tools.findLast((t) => t.tool === event.tool);
                        if (tool) { tool.status = "done"; tool.summary = event.summary; }
                      }
                      return steps;
                    });
                    // Route tool results to orchestrator log
                    if (event.tool === "write_todos") {
                      // write_todos is now natively rendered in PipelineActivity
                    } else if (event.agent && event.summary && event.tool !== "emit_chat_message") {
                      currentOrchestratorText += `\\n> ${event.summary.slice(0, 200)}`;
                      setOrchestratorText(currentOrchestratorText);
                    }
                    break;
                  case "agent_end":
                    setPipelineSteps((prev) => {
                      const steps = [...prev];
                      const step = steps.find((s) => s.agent === event.agent);
                      if (step) step.status = "done";
                      return steps;
                    });
                    break;
                  case "finish":
                    if (event.report_ready) {
                      if (!hasNavigatedRef.current && onNavigateRef.current) {
                        hasNavigatedRef.current = true;
                        onNavigateRef.current(pendingNavigationJobId ?? currentJobIdRef.current);
                      }
                      await fetchReport(currentJobIdRef.current);
                    } else if (!hasStartedResearch) {
                      if (!cancelled) {
                        onConversationalFinishRef.current?.(
                          (streamTelemetry === false ? lastUserMessageMarkdown : "") ||
                            currentOrchestratorText,
                        );
                        setOrchestratorText("");
                        setIsStreamingChat(false);
                      }
                    } else {
                      if (!cancelled) {
                        setStatus("failed");
                        setIsStreamingChat(false);
                      }
                    }
                    break;
                  case "error":
                    if (!cancelled) {
                      setStatus("error");
                      setErrorText(event.errorText || "An error occurred");
                      setIsStreamingChat(false);
                    }
                    break;
                }
          } catch (e) {
            console.error("Error parsing SSE event:", e, raw);
          }
        };

        try {
          while (true) {
            if (cancelled) {
              reader.cancel().catch(() => {});
              break;
            }
            const { done, value } = await reader.read();
            if (value) {
              buffer += decoder.decode(value, { stream: true });
            }
            const lines = buffer.split("\n");
            buffer = lines.pop() || "";
            for (const line of lines) {
              if (!line.startsWith("data: ")) continue;
              await dispatchSseJson(line.slice(6).trim());
            }
            if (done) {
              const rest = buffer.trim();
              if (rest.startsWith("data: ")) {
                await dispatchSseJson(rest.slice(6).trim());
              }
              break;
            }
          }
        } finally {
          if (cancelled) reader.cancel().catch(() => {});
          else setIsStreamingChat(false);
        }
      } catch (error: unknown) {
        if (!cancelled) {
          setStatus("error");
          setErrorText(error instanceof Error ? error.message : String(error));
          setIsStreamingChat(false);
        }
      }
    };

    run();

    return () => { cancelled = true; };
  }, [messages, requestNonce, streamTelemetry]); // eslint-disable-line react-hooks/exhaustive-deps

  return { status, orchestratorText, pipelineSteps, report, errorText, isStreamingChat };
}

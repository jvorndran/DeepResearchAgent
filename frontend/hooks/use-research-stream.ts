"use client";

import { useState, useEffect, useRef } from "react";
import type { ResearchStatus, Message, PipelineStep, ResearchReport } from "@/lib/types";

export interface UseResearchStreamOptions {
  jobId: string;
  messages: Message[];
  onNavigate?: (jobId: string) => void;
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
  onNavigate,
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
  const onConversationalFinishRef = useRef(onConversationalFinish);
  onConversationalFinishRef.current = onConversationalFinish;

  const hasNavigatedRef = useRef(false);
  const currentJobIdRef = useRef(jobId);

  useEffect(() => {
    // Refresh case: no messages but we have a job_id — try to load existing report
    if (messages.length === 0 && jobId) {
      setStatus("idle");
      fetch(`http://localhost:8000/api/reports/${jobId}`)
        .then((res) => { if (!res.ok) throw new Error(`${res.status}`); return res.json(); })
        .then((data) => { setReport(data); setStatus("report_ready"); })
        .catch(() => { setStatus("error"); setErrorText(`Could not load report for job ${jobId}.`); });
      return;
    }

    if (messages.length === 0) return;

    let cancelled = false;
    let currentOrchestratorText = "";
    let hasStartedResearch = false;
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

        try {
          while (true) {
            if (cancelled) { reader.cancel().catch(() => {}); break; }
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });

            const lines = buffer.split("\n");
            buffer = lines.pop() || "";

            for (const line of lines) {
              if (!line.startsWith("data: ")) continue;
              const raw = line.slice(6).trim();
              if (raw === "[DONE]") break;
              if (!raw) continue;

              try {
                const event = JSON.parse(raw);
                switch (event.type) {
                  case "start":
                    currentJobIdRef.current = event.job_id;
                    if (!hasNavigatedRef.current && onNavigateRef.current) {
                      hasNavigatedRef.current = true;
                      onNavigateRef.current(event.job_id);
                    }
                    break;
                  case "text":
                    currentOrchestratorText += event.delta;
                    setOrchestratorText(currentOrchestratorText);
                    break;
                  case "agent_start":
                    if (!hasStartedResearch) {
                      hasStartedResearch = true;
                      setStatus("streaming");
                      setIsStreamingChat(false);
                    }
                    setPipelineSteps((prev) => [
                      ...prev,
                      { agent: event.agent, status: "running", tools: [] },
                    ]);
                    break;
                  case "tool_call":
                    setPipelineSteps((prev) => {
                      const steps = [...prev];
                      const step = steps.findLast((s) => s.agent === event.agent);
                      if (step) {
                        step.tools.push({ tool: event.tool, args: event.args, status: "running" });
                      }
                      return steps;
                    });
                    break;
                  case "tool_result":
                    setPipelineSteps((prev) => {
                      const steps = [...prev];
                      const step = steps.findLast((s) => s.agent === event.agent);
                      if (step) {
                        const tool = step.tools.findLast((t) => t.tool === event.tool);
                        if (tool) { tool.status = "done"; tool.summary = event.summary; }
                      }
                      return steps;
                    });
                    break;
                  case "agent_end":
                    setPipelineSteps((prev) => {
                      const steps = [...prev];
                      const step = steps.findLast((s) => s.agent === event.agent);
                      if (step) step.status = "done";
                      return steps;
                    });
                    break;
                  case "finish":
                    if (event.report_ready) {
                      await fetchReport(currentJobIdRef.current);
                    } else if (!hasStartedResearch) {
                      if (!cancelled) {
                        onConversationalFinishRef.current?.(currentOrchestratorText);
                        setOrchestratorText("");
                        setIsStreamingChat(false);
                      }
                    } else {
                      if (!cancelled) setStatus("failed");
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
            }
          }
        } finally {
          if (cancelled) reader.cancel().catch(() => {});
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
  }, [messages]); // eslint-disable-line react-hooks/exhaustive-deps

  return { status, orchestratorText, pipelineSteps, report, errorText, isStreamingChat };
}

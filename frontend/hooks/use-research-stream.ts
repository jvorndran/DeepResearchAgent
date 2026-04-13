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
    // No messages — page was refreshed mid-research (or navigated directly).
    // Try to reconnect to the live SSE stream if the job is still running,
    // otherwise fall back to polling for the completed report.
    if (messages.length === 0) {
      if (!jobId) return;
      let cancelled = false;

      const fetchReport = async (): Promise<void> => {
        const res = await fetch(`http://localhost:8000/api/reports/${jobId}`);
        if (!res.ok) throw new Error(`Report fetch failed: ${res.status}`);
        const data = await res.json();
        if (!cancelled) { setReport(data); setStatus("report_ready"); }
      };

      // Main entry: check status then either reconnect to SSE or poll.
      const checkAndConnect = async (): Promise<void> => {
        if (cancelled) return;

        // 1. Check current job status
        let statusRes: Response;
        try {
          statusRes = await fetch(`http://localhost:8000/api/reports/${jobId}`);
        } catch {
          if (!cancelled) {
            setStatus("error");
            setErrorText(`Could not connect to server for job ${jobId}.`);
          }
          return;
        }

        if (statusRes.status === 200) {
          // Report already ready
          try {
            const data = await statusRes.json();
            if (!cancelled) { setReport(data); setStatus("report_ready"); }
          } catch {
            if (!cancelled) { setStatus("error"); setErrorText("Failed to parse report."); }
          }
          return;
        }

        if (statusRes.status === 410) {
          if (!cancelled) {
            setStatus("error");
            setErrorText("Research was interrupted — the server was restarted mid-job. Please start a new research.");
          }
          return;
        }

        if (statusRes.status === 500) {
          if (!cancelled) {
            setStatus("error");
            setErrorText("Research job failed on the server.");
          }
          return;
        }

        if (statusRes.status !== 202) {
          if (!cancelled) {
            setStatus("error");
            setErrorText(`Could not load report for job ${jobId}.`);
          }
          return;
        }

        // 2. Job is running (202) — try to reconnect to live SSE stream
        let sseRes: Response;
        try {
          sseRes = await fetch(`http://localhost:8000/api/jobs/${jobId}/stream`);
        } catch {
          // Network error — retry after delay
          if (!cancelled) {
            await new Promise<void>((r) => setTimeout(r, 5000));
            checkAndConnect();
          }
          return;
        }

        if (sseRes.status === 404) {
          // Job finished between status check and SSE connect — poll once more
          await new Promise<void>((r) => setTimeout(r, 1000));
          if (!cancelled) checkAndConnect();
          return;
        }

        if (!sseRes.ok || !sseRes.body) {
          // SSE unavailable — fall back to polling
          await new Promise<void>((r) => setTimeout(r, 5000));
          if (!cancelled) checkAndConnect();
          return;
        }

        // 3. SSE connected — show streaming view and replay events
        if (!cancelled) {
          setStatus("streaming");
          setOrchestratorText("");
          setPipelineSteps([]);
          setErrorText("");
        }

        let currentOrchestratorText = "";
        const reader = sseRes.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        const handleEvent = async (event: Record<string, any>): Promise<void> => {
          if (cancelled) return;
          console.log("[SSE/reconnect]", event.type, event);
          switch (event.type) {
            case "start":
              break; // already know job_id from URL
            case "text":
              currentOrchestratorText += event.delta;
              setOrchestratorText(currentOrchestratorText);
              break;
            case "user_message": {
              const md = typeof event.markdown === "string" ? event.markdown : "";
              currentOrchestratorText += (currentOrchestratorText ? "\n\n---\n\n" : "") + md;
              setOrchestratorText(currentOrchestratorText);
              break;
            }
            case "agent_start":
              setStatus("streaming");
              setPipelineSteps((prev) => {
                const steps = [...prev];
                const existing = steps.find((s) => s.agent === event.agent);
                if (existing) { existing.status = "running"; } else { steps.push({ agent: event.agent, status: "running", tools: [] }); }
                return steps;
              });
              break;
            case "tool_call":
              setPipelineSteps((prev) => {
                const steps = [...prev];
                let step = steps.find((s) => s.agent === event.agent);
                if (!step && event.agent === null) { step = { agent: null, status: "running", tools: [] }; steps.push(step); }
                if (step) {
                  if (event.tool === "write_todos") {
                    const existingTool = step.tools.find((t) => t.tool === "write_todos");
                    if (existingTool) { existingTool.args = event.args; existingTool.status = "running"; }
                    else { step.tools.push({ tool: event.tool, args: event.args, status: "running" }); }
                  } else {
                    step.tools.push({ tool: event.tool, args: event.args, status: "running" });
                  }
                }
                return steps;
              });
              if (event.agent && event.tool !== "emit_chat_message") {
                currentOrchestratorText += `\\n\\n**→ ${event.tool}**`;
                setOrchestratorText(currentOrchestratorText);
              }
              break;
            case "tool_result":
              setPipelineSteps((prev) => {
                const steps = [...prev];
                const step = steps.find((s) => s.agent === event.agent);
                if (step) { const tool = step.tools.findLast((t) => t.tool === event.tool); if (tool) { tool.status = "done"; tool.summary = event.summary; } }
                return steps;
              });
              if (event.agent && event.summary && event.tool !== "emit_chat_message") {
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
                try { await fetchReport(); } catch { if (!cancelled) { setStatus("error"); setErrorText("Failed to load report after completion."); } }
              } else {
                if (!cancelled) setStatus("failed");
              }
              break;
            case "error":
              if (!cancelled) { setStatus("error"); setErrorText(event.errorText || "An error occurred"); }
              break;
          }
        };

        try {
          while (true) {
            if (cancelled) { reader.cancel().catch(() => {}); break; }
            const { done, value } = await reader.read();
            if (value) buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\n");
            buffer = lines.pop() || "";
            for (const line of lines) {
              if (!line.startsWith("data: ")) continue;
              const raw = line.slice(6).trim();
              if (!raw || raw === "[DONE]") continue;
              try { await handleEvent(JSON.parse(raw)); } catch (e) { console.error("Error parsing SSE:", e, raw); }
            }
            if (done) {
              const rest = buffer.trim();
              if (rest.startsWith("data: ")) {
                try { await handleEvent(JSON.parse(rest.slice(6).trim())); } catch { /* ignore */ }
              }
              break;
            }
          }
        } catch {
          // SSE stream dropped — retry
          if (!cancelled) {
            await new Promise<void>((r) => setTimeout(r, 3000));
            if (!cancelled) checkAndConnect();
          }
        } finally {
          reader.cancel().catch(() => {});
        }
      };

      setStatus("loading");
      checkAndConnect();
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

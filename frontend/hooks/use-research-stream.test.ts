import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Message, ResearchReport } from "@/lib/types";
import researchStreamEvents from "./fixtures/research-stream-full.json";
import { useResearchStream } from "./use-research-stream";

/** Turn saved stream events (JSON objects + terminal `"[DONE]"`) into an SSE wire body. */
function eventsToSseBody(events: readonly unknown[]): string {
  let out = "";
  for (const event of events) {
    if (event === "[DONE]") {
      out += "data: [DONE]\n";
      continue;
    }
    out += `data: ${JSON.stringify(event)}\n`;
  }
  return out;
}

function sseResponse(body: string): Response {
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(new TextEncoder().encode(body));
      controller.close();
    },
  });
  return new Response(stream, { status: 200, headers: { "Content-Type": "text/event-stream" } });
}

const FIXTURE_JOB_ID = "job_f6dd6b7f";

function mockReport(): ResearchReport {
  return {
    schema_version: 1,
    job_id: FIXTURE_JOB_ID,
    created_at: "2026-04-12T00:00:00.000Z",
    query: "US unemployment trends",
    title: "Fixture report",
    executive_summary: "Executive summary from test mock.",
    markdown: "# Report\n\nMock body.",
    charts: {},
    data_sources: [],
    metadata: { analysis_type: "fixture", chart_count: 0, word_count: 42 },
  };
}

describe("useResearchStream", () => {
  const messages: Message[] = [{ role: "user", content: "Research US employment trends" }];

  beforeEach(() => {
    vi.spyOn(console, "log").mockImplementation(() => {});
    vi.spyOn(Storage.prototype, "getItem").mockReturnValue(null);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("consumes the full SSE fixture through report_ready and loads the report", async () => {
    const sseBody = eventsToSseBody(researchStreamEvents);
    const reportJson = mockReport();

    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (url.includes("/api/chat/stream")) {
        return sseResponse(sseBody);
      }
      if (url.includes(`/api/reports/${FIXTURE_JOB_ID}`)) {
        return new Response(JSON.stringify(reportJson), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      return new Response(`unexpected fetch: ${url}`, { status: 500 });
    });
    vi.stubGlobal("fetch", fetchMock);

    const onNavigate = vi.fn();
    const onJobId = vi.fn();

    const { result } = renderHook(() =>
      useResearchStream({
        jobId: "",
        messages,
        requestNonce: 1,
        streamTelemetry: true,
        onNavigate,
        onJobId,
      }),
    );

    await waitFor(() => expect(result.current.status).toBe("report_ready"));
    await waitFor(() => expect(result.current.isStreamingChat).toBe(false));

    expect(onJobId).toHaveBeenCalledWith(FIXTURE_JOB_ID);
    expect(onNavigate).toHaveBeenCalledWith(FIXTURE_JOB_ID);
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/chat/stream",
      expect.objectContaining({
        method: "POST",
        headers: { "Content-Type": "application/json" },
      }),
    );
    expect(fetchMock).toHaveBeenCalledWith(`http://localhost:8000/api/reports/${FIXTURE_JOB_ID}`);

    const streamCall = fetchMock.mock.calls.find((c) => c[0] === "http://localhost:8000/api/chat/stream") as
      | [string, RequestInit]
      | undefined;
    expect(streamCall).toBeDefined();
    const [, streamInit] = streamCall!;
    expect(JSON.parse(streamInit.body as string)).toMatchObject({ messages });

    expect(result.current.errorText).toBe("");
    expect(result.current.report).toEqual(reportJson);
    expect(result.current.orchestratorText).toContain("Executive Summary");
    expect(result.current.orchestratorText).toContain("**→ fred_get_series**");

    const agents = result.current.pipelineSteps.map((s) => s.agent);
    expect(agents).toContain("data-engineer");
    expect(agents).toContain("tools");
    expect(agents).toContain("quality-analyst");

    const toolsSteps = result.current.pipelineSteps.filter((s) => s.agent === "tools");
    expect(toolsSteps.some((s) => s.tools.some((t) => t.tool === "fred_get_series"))).toBe(true);
  });

  it("omits raw text deltas when streamTelemetry is false but still surfaces user_message markdown", async () => {
    const sseBody = eventsToSseBody([
      { type: "start", job_id: "job_home" },
      {
        type: "user_message",
        markdown: "Hello\n\nClick **Commence Deep Research** to begin.",
      },
      { type: "finish", report_ready: false },
      "[DONE]",
    ]);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(sseResponse(sseBody)));

    const onApprovalRequired = vi.fn();
    const onConversationalFinish = vi.fn();

    renderHook(() =>
      useResearchStream({
        jobId: "",
        messages,
        requestNonce: 2,
        streamTelemetry: false,
        onApprovalRequired,
        onConversationalFinish,
      }),
    );

    await waitFor(() => expect(onConversationalFinish).toHaveBeenCalled());
    expect(onApprovalRequired).toHaveBeenCalledWith("job_home");
    expect(onConversationalFinish).toHaveBeenCalledWith(
      expect.stringContaining("Commence Deep Research"),
    );
  });
});

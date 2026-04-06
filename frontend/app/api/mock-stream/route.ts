import { NextRequest } from 'next/server';

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));
const enc = new TextEncoder();

const START_EVENTS = [
  `data: {"type":"start","job_id":"test-job-123"}`,
  `data: [DONE]`,
];

const SYNTHESIZING_EVENTS = [
  `data: {"type":"text","delta":"Received query: 'What is the revenue CAGR for NVIDIA from 2020\\u20132024?'\\n\\n"}`,
  `data: {"type":"text","delta":"Decomposing into sub-tasks. This is a quantitative financial analysis requiring historical income statement data and compound growth rate computation.\\n\\n"}`,
  `data: {"type":"text","delta":"Identifying required data sources: NVDA annual income statements FY2020\\u2013FY2024 from Financial Modeling Prep.\\n\\n"}`,
  `data: {"type":"text","delta":"Planning agent pipeline: data_engineer \\u2192 quantitative_developer \\u2192 technical_writer \\u2192 quality_analyst.\\n\\n"}`,
  `data: {"type":"text","delta":"Dispatching data_engineer to begin data acquisition..."}`,
  `data: [DONE]`,
];

const STREAMING_EVENTS = [
  `data: {"type":"text","delta":"Received query: 'What is the revenue CAGR for NVIDIA from 2020\\u20132024?'\\n\\n"}`,
  `data: {"type":"text","delta":"Step 1 \\u2014 Data acquisition: routing to data_engineer to pull NVDA annual revenue figures from FY2020 through FY2024 via the FMP API.\\n\\n"}`,
  `data: {"type":"agent_start","agent":"data_engineer"}`,
  `data: {"type":"tool_call","agent":"data_engineer","tool":"fetch_fmp_data","args":{"ticker":"NVDA","period":"annual"}}`,
  `data: {"type":"tool_result","agent":"data_engineer","tool":"fetch_fmp_data","summary":"Fetched 5 years of NVDA income statement data (5 rows)"}`,
  `data: {"type":"agent_end","agent":"data_engineer"}`,
  `data: {"type":"text","delta":"Data acquisition complete. FY2020 $10.9B \\u2192 FY2024 $60.9B. Data quality looks clean, no missing periods.\\n\\n"}`,
  `data: {"type":"text","delta":"Step 2 \\u2014 Quantitative analysis: handing off to quantitative_developer to compute CAGR using (end/start)^(1/n) - 1 over 4 periods.\\n\\n"}`,
  `data: {"type":"agent_start","agent":"quantitative_developer"}`,
  `data: {"type":"tool_call","agent":"quantitative_developer","tool":"execute_python","args":{}}`,
  `data: {"type":"tool_result","agent":"quantitative_developer","tool":"execute_python","summary":"Revenue CAGR: 42.3% (FY2020\\u2013FY2024)"}`,
  `data: {"type":"agent_end","agent":"quantitative_developer"}`,
  `data: {"type":"text","delta":"CAGR: 42.3%. Remarkably high \\u2014 driven by data center GPU demand. Flagging for contextualisation.\\n\\n"}`,
  `data: {"type":"text","delta":"Step 3 \\u2014 Report drafting: routing to technical_writer to produce structured markdown with chart annotations.\\n\\n"}`,
  `data: {"type":"agent_start","agent":"technical_writer"}`,
  `data: {"type":"agent_end","agent":"technical_writer"}`,
  `data: {"type":"text","delta":"Draft received. Executive summary, bar chart annotation, and disclaimer included. Routing to quality_analyst.\\n\\n"}`,
  `data: {"type":"text","delta":"Step 4 \\u2014 Quality review: checking factual accuracy, source citations, and disclaimer language.\\n\\n"}`,
  `data: {"type":"agent_start","agent":"quality_analyst"}`,
  `data: {"type":"agent_end","agent":"quality_analyst"}`,
  `data: {"type":"text","delta":"Quality check passed. All figures traceable to FMP source data. Report approved for delivery."}`,
  `data: [DONE]`,
];

const RESEARCH_EVENTS = [
  ...STREAMING_EVENTS.slice(0, -1), // all except [DONE]
  `data: {"type":"finish","report_ready":true}`,
  `data: [DONE]`,
];

const SCENARIOS: Record<string, { events: string[]; delay: number }> = {
  start:        { events: START_EVENTS,        delay: 0   },
  synthesizing: { events: SYNTHESIZING_EVENTS, delay: 400 },
  streaming:    { events: STREAMING_EVENTS,    delay: 350 },
  research:     { events: RESEARCH_EVENTS,     delay: 350 },
};

export async function POST(req: NextRequest) {
  const scenario = req.nextUrl.searchParams.get('scenario') ?? 'start';
  const { events, delay } = SCENARIOS[scenario] ?? SCENARIOS.start;

  const stream = new ReadableStream({
    async start(controller) {
      for (const event of events) {
        if (delay > 0) await sleep(delay);
        controller.enqueue(enc.encode(event + '\n'));
      }
      controller.close();
    },
  });

  return new Response(stream, {
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache, no-transform',
      'X-Accel-Buffering': 'no',
    },
  });
}

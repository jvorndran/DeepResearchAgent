import { NextRequest } from 'next/server';

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));
const enc = new TextEncoder();

const START_EVENTS = [
  `data: {"type":"start","job_id":"gdp_unemployment_20yr"}`,
  `data: {"type":"user_message","markdown":"I now have what I need. Please click **Commence Deep Research** below to approve and begin pulling data."}`,
  `data: {"type":"approval_required","job_id":"gdp_unemployment_20yr","action_requests":[],"review_configs":[]}`,
  `data: {"type":"finish","report_ready":false}`,
  `data: [DONE]`,
];

const SYNTHESIZING_EVENTS = [
  `data: {"type":"start","job_id":"gdp_unemployment_20yr"}`,
  `data: {"type":"text","delta":"Updated todo list to [{'content': 'Delegate data fetching to data-engineer for GDPC1 and UNRATE from FRED.', 'status': 'in_progress'}, {'content': 'Delegate analysis and chart generation to quant-developer.', 'status': 'pending'}, {'content': 'Delegate report synthesis to technical-writer.', 'status': 'pending'}, {'content': 'Delegate quality review to quality-analyst.', 'status': 'pending'}, {'content': 'Final handoff and report confirmation.', 'status': 'pending'}]"}`,
  `data: {"type":"text","delta":"Routing to data-engineer to fetch 20 years of FRED macroeconomic data..."}`,
  `data: {"type":"execution_started","job_id":"gdp_unemployment_20yr"}`,
  `data: [DONE]`,
];

const STREAMING_EVENTS = [
  `data: {"type":"start","job_id":"gdp_unemployment_20yr"}`,
  `data: {"type":"text","delta":"Updated todo list to [{'content': 'Delegate data fetching to data-engineer for GDPC1 and UNRATE from FRED.', 'status': 'in_progress'}, {'content': 'Delegate analysis and chart generation to quant-developer.', 'status': 'pending'}, {'content': 'Delegate report synthesis to technical-writer.', 'status': 'pending'}, {'content': 'Delegate quality review to quality-analyst.', 'status': 'pending'}, {'content': 'Final handoff and report confirmation.', 'status': 'pending'}]"}`,
  `data: {"type":"execution_started","job_id":"gdp_unemployment_20yr"}`,
  `data: {"type":"agent_start","agent":"tools"}`,
  `data: {"type":"text","delta":"Updated todo list to [{'content': 'Fetch GDPC1 from FRED', 'status': 'in_progress'}, {'content': 'Fetch UNRATE from FRED', 'status': 'pending'}, {'content': 'Save datasets using save_fmp_data', 'status': 'pending'}, {'content': 'Extract schemas using extract_schema', 'status': 'pending'}]"}`,
  `data: {"type":"tool_call","agent":"tools","tool":"fetch_fred_series","args":{"series_id":"GDPC1","start":"2004-01-01","end":"2024-12-31"}}`,
  `data: {"type":"tool_result","agent":"tools","tool":"fetch_fred_series","summary":"Fetched GDPC1: 80 quarterly observations (Q1 2004 \\u2013 Q4 2024)"}`,
  `data: {"type":"tool_call","agent":"tools","tool":"fetch_fred_series","args":{"series_id":"UNRATE","start":"2004-01-01","end":"2024-12-31"}}`,
  `data: {"type":"tool_result","agent":"tools","tool":"fetch_fred_series","summary":"Fetched UNRATE: 80 quarterly observations aggregated from monthly"}`,
  `data: {"type":"agent_end","agent":"tools"}`,
  `data: {"type":"text","delta":"Updated todo list to [{'content': 'Delegate data fetching to data-engineer for GDPC1 and UNRATE from FRED.', 'status': 'done'}, {'content': 'Delegate analysis and chart generation to quant-developer.', 'status': 'in_progress'}, {'content': 'Delegate report synthesis to technical-writer.', 'status': 'pending'}, {'content': 'Delegate quality review to quality-analyst.', 'status': 'pending'}, {'content': 'Final handoff and report confirmation.', 'status': 'pending'}]"}`,
  `data: {"type":"agent_start","agent":"tools"}`,
  `data: {"type":"text","delta":"Updated todo list to [{'content': 'Compute Pearson correlation between GDP growth and unemployment', 'status': 'in_progress'}, {'content': 'Identify contraction quarters', 'status': 'pending'}, {'content': 'Generate chart datasets', 'status': 'pending'}]"}`,
  `data: {"type":"tool_call","agent":"tools","tool":"execute_python","args":{}}`,
  `data: {"type":"tool_result","agent":"tools","tool":"execute_python","summary":"Pearson r = -0.4865 (p < 0.0001). 7 contraction quarters identified. Chart datasets prepared."}`,
  `data: {"type":"agent_end","agent":"tools"}`,
  `data: {"type":"text","delta":"Updated todo list to [{'content': 'Delegate data fetching to data-engineer for GDPC1 and UNRATE from FRED.', 'status': 'done'}, {'content': 'Delegate analysis and chart generation to quant-developer.', 'status': 'done'}, {'content': 'Delegate report synthesis to technical-writer.', 'status': 'in_progress'}, {'content': 'Delegate quality review to quality-analyst.', 'status': 'pending'}, {'content': 'Final handoff and report confirmation.', 'status': 'pending'}]"}`,
  `data: {"type":"agent_start","agent":"tools"}`,
  `data: {"type":"agent_end","agent":"tools"}`,
  `data: {"type":"text","delta":"Updated todo list to [{'content': 'Delegate data fetching to data-engineer for GDPC1 and UNRATE from FRED.', 'status': 'done'}, {'content': 'Delegate analysis and chart generation to quant-developer.', 'status': 'done'}, {'content': 'Delegate report synthesis to technical-writer.', 'status': 'done'}, {'content': 'Delegate quality review to quality-analyst.', 'status': 'in_progress'}, {'content': 'Final handoff and report confirmation.', 'status': 'pending'}]"}`,
  `data: {"type":"agent_start","agent":"tools"}`,
  `data: {"type":"agent_end","agent":"tools"}`,
  `data: {"type":"text","delta":"Updated todo list to [{'content': 'Delegate data fetching to data-engineer for GDPC1 and UNRATE from FRED.', 'status': 'done'}, {'content': 'Delegate analysis and chart generation to quant-developer.', 'status': 'done'}, {'content': 'Delegate report synthesis to technical-writer.', 'status': 'done'}, {'content': 'Delegate quality review to quality-analyst.', 'status': 'done'}, {'content': 'Final handoff and report confirmation.', 'status': 'in_progress'}]"}`,
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

  // If the request carries a `resume` payload it means the user clicked
  // "Commence Deep Research" — return the synthesizing events so the home
  // page transitions to the StreamingView.
  const selectedScenario = scenario;

  const { events, delay } = SCENARIOS[selectedScenario] ?? SCENARIOS.start;

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

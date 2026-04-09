// SSE payloads — match exact format the hook expects:
// buffer.split("\n") then filter lines starting with "data: "

const CONVERSATIONAL_SSE = [
  `data: {"type":"user_message","markdown":"### Clarifying questions\\n\\n- What specific time period should I cover?\\n- Which metrics should I prioritize?"}`,
  `data: {"type":"approval_required","job_id":"test-job-123","action_requests":[],"review_configs":[]}`,
  `data: {"type":"finish","report_ready":false}`,
  `data: [DONE]`,
].join('\n') + '\n';

const buildResearchSSE = (jobId: string) => [
  `data: {"type":"start","job_id":"${jobId}"}`,
  `data: {"type":"text","delta":"Updated todo list to [{'content': 'Delegate data fetching to data-engineer.', 'status': 'in_progress'}, {'content': 'Delegate analysis to quant-developer.', 'status': 'pending'}, {'content': 'Delegate report to technical-writer.', 'status': 'pending'}, {'content': 'Quality review.', 'status': 'pending'}]"}`,
  `data: {"type":"execution_started","job_id":"${jobId}"}`,
  `data: {"type":"agent_start","agent":"tools"}`,
  `data: {"type":"text","delta":"Updated todo list to [{'content': 'Fetch NVDA annual income statement', 'status': 'in_progress'}, {'content': 'Save datasets', 'status': 'pending'}, {'content': 'Extract schemas', 'status': 'pending'}]"}`,
  `data: {"type":"tool_call","agent":"tools","tool":"fetch_fmp_data","args":{"ticker":"NVDA","period":"annual"}}`,
  `data: {"type":"tool_result","agent":"tools","tool":"fetch_fmp_data","summary":"Fetched 5 years of NVDA income statement data (5 rows)"}`,
  `data: {"type":"agent_end","agent":"tools"}`,
  `data: {"type":"agent_start","agent":"tools"}`,
  `data: {"type":"tool_call","agent":"tools","tool":"execute_python","args":{}}`,
  `data: {"type":"tool_result","agent":"tools","tool":"execute_python","summary":"Revenue CAGR: 42.3% (FY2020\u2013FY2024)"}`,
  `data: {"type":"agent_end","agent":"tools"}`,
  `data: {"type":"agent_start","agent":"tools"}`,
  `data: {"type":"agent_end","agent":"tools"}`,
  `data: {"type":"agent_start","agent":"tools"}`,
  `data: {"type":"agent_end","agent":"tools"}`,
  `data: {"type":"finish","report_ready":true}`,
  `data: [DONE]`,
].join('\n') + '\n';

// home page stream — returns start event to trigger navigation
const buildStartSSE = (jobId: string) => [
  `data: {"type":"start","job_id":"${jobId}"}`,
  `data: [DONE]`,
].join('\n') + '\n';

// Custom commands
Cypress.Commands.add('mockStreamEndpoint', (jobId = 'test-job-123') => {
  cy.intercept('POST', 'http://localhost:8000/api/chat/stream', (req) => {
    const hasJobId = !!(req.body?.job_id);
    const body = hasJobId ? buildResearchSSE(jobId) : buildStartSSE(jobId);
    req.reply({
      statusCode: 200,
      headers: { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' },
      body,
    });
  }).as('chatStream');
});

Cypress.Commands.add('mockConversationalStream', () => {
  cy.intercept('POST', 'http://localhost:8000/api/chat/stream', {
    statusCode: 200,
    headers: { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' },
    body: CONVERSATIONAL_SSE,
  }).as('chatStream');
});

Cypress.Commands.add('mockReport', (jobId = 'test-job-123') => {
  cy.intercept('GET', `http://localhost:8000/api/reports/${jobId}`, { fixture: 'gdp_unemployment_20yr/report.json' }).as('getReport');
});

Cypress.Commands.add('mockErrorStream', (errorText = 'Pipeline failed: data unavailable') => {
  const errorSSE = [
    `data: {"type":"agent_start","agent":"data_engineer"}`,
    `data: {"type":"error","errorText":"${errorText}"}`,
    `data: [DONE]`,
  ].join('\n') + '\n';
  cy.intercept('POST', 'http://localhost:8000/api/chat/stream', {
    statusCode: 200,
    headers: { 'Content-Type': 'text/event-stream' },
    body: errorSSE,
  }).as('chatStream');
});

Cypress.Commands.add('snap', (name: string) => {
  if (Cypress.env('SCREENSHOTS') === 'true') {
    cy.screenshot(name);
  }
});

// SSE payloads — match exact format the hook expects:
// buffer.split("\n") then filter lines starting with "data: "

const CONVERSATIONAL_SSE = [
  `data: {"type":"text","delta":"To tailor this research, what time period and data frequency are you targeting?"}`,
  `data: {"type":"finish","report_ready":false}`,
  `data: [DONE]`,
].join('\n') + '\n';

const buildResearchSSE = (_jobId: string) => [
  `data: {"type":"agent_start","agent":"data_engineer"}`,
  `data: {"type":"tool_call","agent":"data_engineer","tool":"fetch_fmp_data","args":{"ticker":"NVDA","period":"annual"}}`,
  `data: {"type":"tool_result","agent":"data_engineer","tool":"fetch_fmp_data","summary":"Fetched 5 years of NVDA income statement data (5 rows)"}`,
  `data: {"type":"agent_end","agent":"data_engineer"}`,
  `data: {"type":"agent_start","agent":"quantitative_developer"}`,
  `data: {"type":"tool_call","agent":"quantitative_developer","tool":"execute_python","args":{}}`,
  `data: {"type":"tool_result","agent":"quantitative_developer","tool":"execute_python","summary":"Revenue CAGR: 42.3% (FY2020–FY2024)"}`,
  `data: {"type":"agent_end","agent":"quantitative_developer"}`,
  `data: {"type":"agent_start","agent":"technical_writer"}`,
  `data: {"type":"agent_end","agent":"technical_writer"}`,
  `data: {"type":"agent_start","agent":"quality_analyst"}`,
  `data: {"type":"agent_end","agent":"quality_analyst"}`,
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
  cy.intercept('GET', `http://localhost:8000/api/reports/${jobId}`, { fixture: 'mock-report.json' }).as('getReport');
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

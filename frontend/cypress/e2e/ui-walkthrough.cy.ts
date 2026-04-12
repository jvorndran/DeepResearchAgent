/**
 * UI Walkthrough — pause at each stage for visual inspection & live editing.
 * Run via: npm run cypress:open → select this spec
 * Click ▶ Resume in the command log to advance.
 *
 * Stages 2–3 set localStorage.__cypress_stream_scenario__ via onBeforeLoad so
 * the hook fetches /api/mock-stream directly (same-origin, real streaming, no proxy).
 * Stage 4 uses the same recorded transcript as unit tests (`research_stream_full`).
 * No cy.intercept on the stream — the browser talks straight to the Next.js mock route.
 */
export {};

const JOB_ID = 'gdp_unemployment_20yr';
/** Job id inside `hooks/fixtures/research-stream-full.json` (start + report fetch). */
const STREAM_FIXTURE_JOB_ID = 'job_f6dd6b7f';

const CONVERSATIONAL_SSE = [
  `data: {"type":"start","job_id":"${JOB_ID}"}`,
  `data: {"type":"user_message","markdown":"### Clarifying questions\\n\\n- What specific time period should I cover?\\n- Which metrics should I prioritize?"}`,
  `data: {"type":"approval_required","job_id":"${JOB_ID}","action_requests":[],"review_configs":[]}`,
  `data: {"type":"finish","report_ready":false}`,
  `data: [DONE]`,
].join('\n') + '\n';

/** Visit the chat page directly, bypassing the home-page "Begin Research" flow */
function visitChatPage(
  scenario: string,
  message = 'When US GDP contracts, what happens to unemployment? Analyze the historical relationship between US real GDP growth and the unemployment rate over the last 20 years.',
  jobId: string = JOB_ID,
) {
  cy.visit(`/chat/${jobId}`, {
    onBeforeLoad(win) {
      win.sessionStorage.setItem('pending_messages', JSON.stringify([{ role: 'user', content: message }]));
      win.localStorage.setItem('__cypress_stream_scenario__', scenario);
    },
  });
}

// ── Stage 1: Begin Research button ───────────────────────────────────────────

it('Stage 1 — Home: Begin Research button after multi-turn conversation', () => {
  cy.intercept('POST', 'http://localhost:8000/api/chat/stream', {
    statusCode: 200,
    headers: { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' },
    body: CONVERSATIONAL_SSE,
  }).as('chatStream');

  cy.visit('/');

  cy.get('[data-testid="research-input"]').type('Help me analyze NVIDIA');
  cy.get('[data-testid="send-button"]').click();
  cy.get('[data-testid="message-item"][data-role="assistant"]').should('exist');

  cy.get('[data-testid="research-input"]').type('Focus on FY2020–FY2024 annual revenue');
  cy.get('[data-testid="send-button"]').click();
  cy.get('[data-testid="message-item"][data-role="assistant"]').should('have.length.at.least', 2);

  cy.log('**STAGE 1 — Begin Research button visible below input**');
  cy.pause();
});

// ── Stage 2: Synthesizing Intelligence ───────────────────────────────────────

it('Stage 2 — Chat: Synthesizing Intelligence (orchestrator text streams in)', () => {
  // Hook fetches /api/mock-stream?scenario=synthesizing — backend-shaped SSE with
  // tool_call/tool_result + user_message + text deltas, but still no agent_start yet.
  // Pipeline panel stays on "Initializing subagents..." while the clarifying response streams in.
  visitChatPage('synthesizing');
  cy.get('[data-testid="streaming-view"]').should('exist');
  cy.get('[data-testid="orchestrator-log"]').should('contain.text', 'Tickers');

  cy.log('**STAGE 2 — Backend-shaped clarifying stream arrives before any agent cards appear**');
  cy.pause();
});

// ── Stage 3: Staggered pipeline streaming ────────────────────────────────────

it('Stage 3 — Chat: Pipeline agents streaming (watch agent cards appear)', () => {
  // Hook fetches /api/mock-stream?scenario=streaming — full pipeline, 350ms between events
  // Pause after first card appears — remaining cards stream in while paused
  visitChatPage('streaming');
  cy.get('[data-testid="pipeline-step"]').should('have.length.at.least', 1);

  cy.log('**STAGE 3 — Watch remaining agent cards + orchestrator text arrive while paused**');
  cy.pause();
});

// ── Stage 4: Report ───────────────────────────────────────────────────────────

it('Stage 4 — Chat: Full report with chart', () => {
  // Hook fetches /api/mock-stream?scenario=research_stream_full — same JSON as Vitest
  // (`hooks/fixtures/research-stream-full.json`) + finish:report_ready:true
  cy.intercept('GET', `http://localhost:8000/api/reports/${STREAM_FIXTURE_JOB_ID}`, {
    fixture: 'gdp_unemployment_20yr/report.json',
  }).as('getReport');

  visitChatPage('research_stream_full', undefined, STREAM_FIXTURE_JOB_ID);
  cy.wait('@getReport', { timeout: 20000 });
  cy.get('[data-testid="report-view"]').should('exist');
  cy.get('.recharts-wrapper').should('exist');

  cy.log('**STAGE 4 — Full report: title, executive summary, bar chart (stream = research-stream-full fixture)**');
  cy.pause();
});

// ── Stage 5: Error ────────────────────────────────────────────────────────────

it('Stage 5 — Chat: Error view', () => {
  cy.intercept('POST', 'http://localhost:8000/api/chat/stream', {
    statusCode: 200,
    headers: { 'Content-Type': 'text/event-stream' },
    body: [
      `data: {"type":"agent_start","agent":"data_engineer"}`,
      `data: {"type":"error","errorText":"Data fetch failed: NVDA ticker not found"}`,
      `data: [DONE]`,
    ].join('\n') + '\n',
  }).as('chatStream');

  cy.visit(`/chat/${JOB_ID}`, {
    onBeforeLoad(win) {
      win.sessionStorage.setItem('pending_messages', JSON.stringify([
        { role: 'user', content: 'Analyze NVDA' },
      ]));
    },
  });
  cy.get('[data-testid="error-view"]').should('exist');

  cy.log('**STAGE 5 — Error view with message and Start Over button**');
  cy.pause();
});

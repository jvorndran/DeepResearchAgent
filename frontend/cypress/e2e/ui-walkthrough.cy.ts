/**
 * UI Walkthrough — pause at each stage for visual inspection & live editing.
 * Run via: npm run cypress:open → select this spec
 * Click ▶ Resume in the command log to advance.
 *
 * Stages 2–4 set localStorage.__cypress_stream_scenario__ via onBeforeLoad so
 * the hook fetches /api/mock-stream directly (same-origin, real streaming, no proxy).
 * No cy.intercept needed — the browser talks straight to the Next.js mock route.
 */

const JOB_ID = 'test-job-123';

const CONVERSATIONAL_SSE = [
  `data: {"type":"text","delta":"To tailor this research, what time period and data frequency are you targeting?"}`,
  `data: {"type":"finish","report_ready":false}`,
  `data: [DONE]`,
].join('\n') + '\n';

/** Visit the chat page directly, bypassing the home-page "Begin Research" flow */
function visitChatPage(scenario: string, message = 'What is the revenue CAGR for NVIDIA from 2020–2024?') {
  cy.visit(`/chat/${JOB_ID}`, {
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
  // Hook fetches /api/mock-stream?scenario=synthesizing — text-only events, 400ms apart
  // Pipeline panel stays on "Initializing subagents..." while text types itself in
  visitChatPage('synthesizing');
  cy.get('[data-testid="streaming-view"]').should('exist');

  cy.log('**STAGE 2 — Orchestrator text streams in token by token, no agent cards yet**');
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
  // Hook fetches /api/mock-stream?scenario=research — full pipeline + finish:report_ready:true
  cy.intercept('GET', `http://localhost:8000/api/reports/${JOB_ID}`, {
    fixture: 'mock-report.json',
  }).as('getReport');

  visitChatPage('research');
  cy.wait('@getReport', { timeout: 20000 });
  cy.get('[data-testid="report-view"]').should('exist');
  cy.get('.recharts-wrapper').should('exist');

  cy.log('**STAGE 4 — Full report: title, executive summary, bar chart**');
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

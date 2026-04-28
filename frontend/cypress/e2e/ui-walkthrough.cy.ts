/**
 * UI Walkthrough — pause at each stage for visual inspection & live editing.
 * Run via: npm run cypress:open → select this spec
 * Click ▶ Resume in the command log to advance.
 *
 * Stages 1–4 use `hooks/fixtures/research-stream-full.json` via `/api/mock-stream`:
 * - `research_stream_full_home`: first `start` from the recording + synthetic HITL tail
 * - `research_stream_full`: full recorded transcript (same as Vitest)
 * The browser hits the Next.js mock route (localStorage `__cypress_stream_scenario__`).
 * GET `/api/reports/job_f6dd6b7f` is intercepted for any stage that may complete the stream.
 */
export {};

/** Job id inside `hooks/fixtures/research-stream-full.json` (start + report fetch). */
const STREAM_FIXTURE_JOB_ID = 'job_f6dd6b7f';

const QUERY =
  'Analyze the current trends in unemployment in the US';

function visitChatPage(
  scenario: string,
  message: string = QUERY,
  jobId: string = STREAM_FIXTURE_JOB_ID,
) {
  cy.visit(`/chat/${jobId}`, {
    onBeforeLoad(win) {
      win.sessionStorage.setItem('pending_messages', JSON.stringify([{ role: 'user', content: message }]));
      win.localStorage.setItem('__cypress_stream_scenario__', scenario);
    },
  });
}

describe('UI walkthrough (stream fixture)', () => {
  beforeEach(() => {
    cy.intercept('GET', `/api/backend/api/reports/${STREAM_FIXTURE_JOB_ID}`, {
      fixture: 'gdp_unemployment_20yr/report.json',
    }).as('getReport');
  });

  // ── Stage 1: Begin Research button ───────────────────────────────────────────

  it('Stage 1 — Home: Begin Research after intake (fixture start + HITL tail)', () => {
    cy.visit('/', {
      onBeforeLoad(win) {
        win.localStorage.setItem('__cypress_stream_scenario__', 'research_stream_full_home');
      },
    });

    cy.get('[data-testid="research-input"]').type(QUERY);
    cy.get('[data-testid="send-button"]').click();

    cy.get('[data-testid="message-item"][data-role="assistant"]', { timeout: 15000 }).should('exist');
    cy.get('[data-testid="message-item"][data-role="assistant"]').should('contain.text', 'FRED');

    cy.get('[data-testid="begin-research-button"]', { timeout: 10000 }).should('exist');

    cy.log('**STAGE 1 — Begin Research visible (mock uses recording `start` + clarifying tail)**');
    cy.pause();
  });

  // ── Stage 2: Orchestrator before / early pipeline ───────────────────────────

  it('Stage 2 — Chat: Orchestrator streams (fixture transcript)', () => {
    visitChatPage('research_stream_full');
    cy.get('[data-testid="streaming-view"]').should('exist');
    cy.get('[data-testid="orchestrator-log"]', { timeout: 120000 }).should('contain.text', 'fred_get_series');

    cy.log('**STAGE 2 — Full recording: orchestrator shows tool activity (e.g. fred_get_series)**');
    cy.pause();
  });

  // ── Stage 3: Pipeline cards ─────────────────────────────────────────────────

  it('Stage 3 — Chat: Pipeline agents (fixture transcript)', () => {
    visitChatPage('research_stream_full');
    cy.get('[data-testid="pipeline-step"]', { timeout: 120000 }).should('have.length.at.least', 1);
    cy.get('[data-testid="pipeline-step"]').should('contain.text', 'data-engineer');

    cy.log('**STAGE 3 — Full recording: agent cards (e.g. data-engineer) stream in**');
    cy.pause();
  });

  // ── Stage 4: Report ─────────────────────────────────────────────────────────

  it('Stage 4 — Chat: Full report with chart', () => {
    visitChatPage('research_stream_full');
    cy.wait('@getReport', { timeout: 120000 });
    cy.get('[data-testid="report-view"]').should('exist');
    cy.get('.recharts-wrapper').should('exist');

    cy.log('**STAGE 4 — Report + chart (stream completes → intercepted report JSON)**');
    cy.pause();
  });

  // ── Stage 5: Error ───────────────────────────────────────────────────────────

  it('Stage 5 — Chat: Error view', () => {
    cy.intercept('POST', '/api/backend/api/chat/stream', {
      statusCode: 200,
      headers: { 'Content-Type': 'text/event-stream' },
      body: [
        `data: {"type":"agent_start","agent":"data_engineer"}`,
        `data: {"type":"error","errorText":"Data fetch failed: NVDA ticker not found"}`,
        `data: [DONE]`,
      ].join('\n') + '\n',
    }).as('chatStream');

    cy.visit(`/chat/${STREAM_FIXTURE_JOB_ID}`, {
      onBeforeLoad(win) {
        win.localStorage.removeItem('__cypress_stream_scenario__');
        win.sessionStorage.setItem('pending_messages', JSON.stringify([
          { role: 'user', content: 'Analyze NVDA' },
        ]));
      },
    });
    cy.get('[data-testid="error-view"]').should('exist');

    cy.log('**STAGE 5 — Error view with message and Start Over button**');
    cy.pause();
  });
});

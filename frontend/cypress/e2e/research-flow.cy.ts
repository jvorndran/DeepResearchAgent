const QUERY = 'What has been AAPL revenue and net income growth over the last 5 years?';

describe('Research Agent — Happy Path (E2E)', () => {
  it('full flow: query → agent clarification → begin research → streaming → report', () => {
    // ── Phase 1: Home ──────────────────────────────────────────────────────────
    cy.visit('/');
    cy.snap('01-home-initial');
    cy.get('[data-testid="research-input"]').should('exist').and('have.value', '');

    cy.get('[data-testid="research-input"]').type(QUERY);
    cy.snap('02-query-typed');
    cy.get('[data-testid="send-button"]').click();

    // ── Phase 2: Real backend responds (HITL approval flow) ────────────────────
    cy.url().should('eq', Cypress.config('baseUrl') + '/');
    cy.get('[data-testid="message-item"][data-role="assistant"]', { timeout: 120000 })
      .should('exist');
    cy.snap('03-agent-clarification');

    cy.get('[data-testid="begin-research-button"]', { timeout: 10000 }).should('exist');
    cy.snap('04-begin-research-button');

    // ── Phase 3: Streaming view (real backend handles resume) ──────────────────
    cy.get('[data-testid="begin-research-button"]').click();
    cy.url().should('match', /\/chat\/.+/, { timeout: 15000 });

    cy.get('[data-testid="streaming-view"]', { timeout: 15000 }).should('exist');
    cy.snap('05-streaming-view');

    cy.get('[data-testid="orchestrator-log-content"]', { timeout: 30000 }).should('exist');
    cy.snap('06-orchestrator-streaming');

    // ── Phase 4: Final report (real pipeline takes 5–10 minutes) ──────────────
    cy.get('[data-testid="report-view"]', { timeout: 600000 }).should('exist');
    cy.get('[data-testid="report-title"]').should('exist').and('not.be.empty');
    cy.snap('07-report-rendered');

    cy.get('.recharts-wrapper').should('exist');
    cy.snap('08-chart-visible');
  });
});

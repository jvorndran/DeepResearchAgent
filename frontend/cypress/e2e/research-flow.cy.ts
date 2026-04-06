describe('Research Agent — Full Flow', () => {

  describe('Happy Path: Home → Streaming → Report', () => {
    const JOB_ID = 'test-job-123';

    beforeEach(() => {
      cy.mockStreamEndpoint(JOB_ID);
      cy.mockReport(JOB_ID);
    });

    it('shows empty chat state on load', () => {
      cy.visit('/');
      cy.snap('01-home-initial');
      cy.get('[data-testid="research-input"]').should('exist').and('have.value', '');
      cy.get('[data-testid="begin-research-button"]').should('not.exist');
    });

    it('submits query and navigates to /chat/[job_id]', () => {
      cy.visit('/');
      cy.get('[data-testid="research-input"]')
        .type('What is the revenue CAGR for NVIDIA from 2020–2024?');
      cy.snap('02-home-query-typed');
      cy.get('[data-testid="send-button"]').click();
      cy.url().should('include', `/chat/${JOB_ID}`);
      cy.snap('03-chat-page-loaded');
    });

    it('shows pipeline steps in streaming view on chat page', () => {
      cy.visit('/');
      cy.get('[data-testid="research-input"]')
        .type('What is the revenue CAGR for NVIDIA from 2020–2024?');
      cy.get('[data-testid="send-button"]').click();
      cy.url().should('include', `/chat/${JOB_ID}`);
      cy.get('[data-testid="streaming-view"]').should('exist');
      cy.get('[data-testid="pipeline-step"]').should('have.length.at.least', 1);
      cy.snap('04-pipeline-steps-visible');
      cy.contains('data_engineer').should('exist');
      cy.contains('quantitative_developer').should('exist');
    });

    it('renders the final report with title, summary, and chart', () => {
      cy.visit('/');
      cy.get('[data-testid="research-input"]')
        .type('What is the revenue CAGR for NVIDIA from 2020–2024?');
      cy.get('[data-testid="send-button"]').click();
      cy.url().should('include', `/chat/${JOB_ID}`);
      cy.wait('@getReport');
      cy.snap('05-report-rendered');
      cy.get('[data-testid="report-view"]').should('exist');
      cy.get('[data-testid="report-title"]')
        .should('contain', 'NVIDIA Revenue CAGR Analysis');
      cy.get('[data-testid="executive-summary"]')
        .should('contain', '42.3%');
      cy.get('.recharts-wrapper').should('exist');
      cy.snap('06-chart-visible');
    });
  });

  describe('Conversational Phase (multi-turn clarification)', () => {
    beforeEach(() => {
      cy.mockConversationalStream();
    });

    it('shows assistant reply after first message (no navigation)', () => {
      cy.visit('/');
      cy.get('[data-testid="research-input"]').type('Help me analyze NVIDIA');
      cy.get('[data-testid="send-button"]').click();
      cy.url().should('eq', Cypress.config('baseUrl') + '/');
      cy.get('[data-testid="message-item"][data-role="assistant"]')
        .should('contain', 'time period');
      cy.snap('07-conversational-reply');
    });

    it('shows Begin Research button after conversation starts', () => {
      cy.visit('/');
      cy.get('[data-testid="research-input"]').type('Help me analyze NVIDIA');
      cy.get('[data-testid="send-button"]').click();
      cy.get('[data-testid="begin-research-button"]').should('exist');
      cy.snap('08-begin-research-button');
    });
  });

  describe('Error State', () => {
    it('displays error view when report endpoint returns 404', () => {
      cy.intercept('GET', 'http://localhost:8000/api/reports/bad-job', {
        statusCode: 404,
        body: { detail: 'Not found' },
      });
      cy.visit('/chat/bad-job');
      cy.get('[data-testid="error-view"]').should('exist');
      cy.snap('09-error-view-404');
    });

    it('shows error view with pipeline error event on chat page', () => {
      cy.visit('/');
      cy.window().then((win) => {
        win.sessionStorage.setItem('pending_messages', JSON.stringify([
          { role: 'user', content: 'Analyze NVDA' },
        ]));
      });
      cy.mockErrorStream('Data fetch failed');
      cy.visit('/chat/test-job-123');
      cy.get('[data-testid="error-view"]').should('exist');
      cy.contains('Data fetch failed').should('exist');
      cy.snap('09-error-view-pipeline');
    });
  });

  describe('Direct Load / Refresh', () => {
    it('loads existing report when visiting /chat/[job_id] directly', () => {
      cy.mockReport('test-job-123');
      cy.visit('/chat/test-job-123');
      cy.wait('@getReport');
      cy.get('[data-testid="report-view"]').should('exist');
      cy.get('[data-testid="report-title"]').should('contain', 'NVIDIA');
      cy.snap('10-direct-load-report');
    });
  });

  describe('Visual Regression — Full Happy Path', () => {
    const JOB_ID = 'test-job-123';

    it('full happy path with screenshot at each state', () => {
      cy.mockStreamEndpoint(JOB_ID);
      cy.mockReport(JOB_ID);

      cy.visit('/');
      cy.snap('01-home-initial');

      cy.get('[data-testid="research-input"]')
        .type('What is the revenue CAGR for NVIDIA from 2020–2024?');
      cy.snap('02-home-query-typed');

      cy.get('[data-testid="send-button"]').click();
      cy.url().should('include', `/chat/${JOB_ID}`);
      cy.snap('03-chat-page-loaded');

      cy.get('[data-testid="pipeline-step"]').should('exist');
      cy.snap('04-pipeline-steps-visible');

      cy.wait('@getReport');
      cy.snap('05-report-rendered');

      cy.get('.recharts-wrapper').should('exist');
      cy.snap('06-chart-visible');
    });

    it('conversational reply state', () => {
      cy.mockConversationalStream();
      cy.visit('/');
      cy.get('[data-testid="research-input"]').type('Help me analyze NVIDIA');
      cy.get('[data-testid="send-button"]').click();
      cy.snap('07-conversational-reply');
      cy.get('[data-testid="begin-research-button"]').should('exist');
      cy.snap('08-begin-research-button');
    });

    it('error state', () => {
      cy.mockErrorStream('Data fetch failed');
      cy.visit('/chat/test-job-123');
      cy.snap('09-error-view');
    });
  });
});

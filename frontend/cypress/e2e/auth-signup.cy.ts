describe('Authentication — signup flow', () => {
  it('creates an account, establishes a session, and reaches the research home', () => {
    const stamp = Date.now();
    const email = `cypress-${stamp}@example.com`;
    const password = `Cypress-${stamp}!`;

    cy.intercept('POST', '/api/auth/sign-up/email').as('signUp');
    cy.intercept('GET', '/api/auth/get-session').as('getSession');

    cy.visit('/sign-up');
    cy.get('[data-testid="auth-form"]').should('be.visible');
    cy.get('[data-testid="auth-name"]').type('Cypress User');
    cy.get('[data-testid="auth-email"]').type(email);
    cy.get('[data-testid="auth-password"]').type(password);
    cy.get('[data-testid="auth-submit"]').click();

    cy.wait('@signUp').its('response.statusCode').should('be.oneOf', [200, 201]);
    cy.location('pathname', { timeout: 15000 }).should('eq', '/');
    cy.get('[data-testid="research-input"]', { timeout: 15000 }).should('be.visible');
    cy.contains('Cypress User').should('exist');

    cy.request('/api/auth/get-session').then((response) => {
      expect(response.status).to.eq(200);
      expect(response.body.user.email).to.eq(email);
    });
  });
});

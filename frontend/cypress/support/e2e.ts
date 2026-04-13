import './commands';

// Suppress uncaught exceptions from Next.js hydration mismatches during tests
Cypress.on('uncaught:exception', (_err, _runnable) => false);

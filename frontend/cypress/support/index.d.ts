declare namespace Cypress {
  interface Chainable {
    mockStreamEndpoint(jobId?: string): void;
    mockConversationalStream(): void;
    mockReport(jobId?: string): void;
    mockErrorStream(errorText?: string): void;
    /** Takes a screenshot only when SCREENSHOTS=true env var is set */
    snap(name: string): void;
  }
}

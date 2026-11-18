/// <reference types="cypress" />

/**
 * REAL tunnel test (no API simulation). Needs the stack started with the tunnel profile:
 *   docker compose -p obsdemo --profile tunnel up -d
 *   CYPRESS_TUNNEL_URL=https://<your>.ngrok-free.dev CYPRESS_COMPOSE_PROJECT=obsdemo npx cypress run --spec cypress/e2e/tunnel.cy.ts
 * It stops and restarts the ngrok container, so it is skipped unless TUNNEL_URL is set.
 */
const url = Cypress.env('TUNNEL_URL') as string | undefined;
const project = (Cypress.env('COMPOSE_PROJECT') as string | undefined) ?? 'observatorio-sismico';
const compose = (cmd: string) => cy.task('compose', ['-p', project, ...cmd.split(' ')], { timeout: 90000 });

(url ? describe : describe.skip)('Real ngrok tunnel', () => {
  it('shows the failure when the tunnel closes and recovers by itself when it reopens', () => {
    cy.intercept('GET', '**/config.json', { mode: 'api', apiUrl: url, refreshMs: 5000, skipNgrokWarning: true });
    cy.visit('/');
    cy.get('[data-testid=api-state]', { timeout: 30000 }).should('have.text', 'Accesible');
    cy.get('[data-testid=marker-count]').invoke('text').then((markers) => {
      expect(Number(markers)).to.be.greaterThan(0);
      cy.get('[data-testid=last-success]').invoke('text').then((lastSuccess) => {
        compose('stop ngrok');
        cy.get('[data-testid=failure-banner]', { timeout: 40000 }).should('be.visible').and('contain.text', lastSuccess);
        cy.get('[data-testid=marker-count]').should('have.text', markers); // last reading kept
        compose('start ngrok');
        cy.get('[data-testid=failure-banner]', { timeout: 90000 }).should('not.exist');
        cy.get('[data-testid=api-state]').should('have.text', 'Accesible');
        cy.get('[data-testid=last-success]').should('not.have.text', lastSuccess);
      });
    });
  });
});

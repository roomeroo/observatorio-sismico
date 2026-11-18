/// <reference types="cypress" />

/**
 * Generates the documentation screenshots against the REAL deployed panel and backend.
 *   CYPRESS_CAPTURAS=1 npx cypress run --spec cypress/e2e/capturas.cy.ts \
 *     --config baseUrl=https://adrian-observatorio-sismico.netlify.app
 * Needs the stack with the tunnel profile running and the replay already loaded.
 */
const run = Cypress.env('CAPTURAS');

(run ? describe : describe.skip)('Capturas para la memoria', () => {
  beforeEach(() => {
    cy.viewport(1280, 720);
    // faster polling only so the failure/recovery captures do not take minutes
    cy.intercept('GET', '**/config.json', (req) => {
      req.continue((res) => {
        res.body = { ...(typeof res.body === 'string' ? JSON.parse(res.body) : res.body), refreshMs: 5000 };
      });
    });
    cy.visit('/');
    cy.get('[data-testid=api-state]', { timeout: 40000 }).should('have.text', 'Accesible');
    cy.get('[data-testid=marker-count]').should(($e) => expect(Number($e.text())).to.be.greaterThan(0));
    cy.wait(2500); // map tiles
  });

  it('en vivo, filtros, gráficos, tabla y ficha', () => {
    cy.get('.topbar').invoke('css', 'position', 'static'); // so the sticky header does not cover element captures
    cy.screenshot('02-panel-vivo', { capture: 'viewport', overwrite: true });

    cy.get('[data-testid=total-count]').invoke('text').then((before) => {
      cy.screenshot('03-filtro-antes', { capture: 'viewport', overwrite: true });
      cy.get('[data-testid=filter-minmag]').type('5').blur();
      cy.get('[data-testid=total-count]').should('not.have.text', before);
      cy.wait(1500);
      cy.screenshot('04-filtro-despues', { capture: 'viewport', overwrite: true });
      cy.get('[data-testid=filter-minmag]').clear().blur();
      cy.get('[data-testid=total-count]').should('have.text', before);
    });

    for (const [tab, chart] of [['Por hora', 'chart-hourly'], ['Por lugar', 'chart-country'], ['Distribuciones', 'chart-magnitude']] as const) {
      cy.contains('[role=tab]', tab).click();
      cy.get(`[data-testid=${chart}]`).should('be.visible');
      cy.get('section[aria-label=Gráficos]').scrollIntoView({ offset: { top: -90, left: 0 } });
      cy.get('section[aria-label=Gráficos]').screenshot(`05-graficos-${tab.toLowerCase().replace(/ /g, '-').replace('ó', 'o')}`, { overwrite: true });
    }

    cy.get('[data-testid=filter-country]').select('SIN_PAIS');
    cy.get('[data-testid=events-table] tbody tr').should('have.length.greaterThan', 0);
    cy.get('section[aria-label="Tabla de eventos"]').scrollIntoView({ offset: { top: -90, left: 0 } });
    cy.get('section[aria-label="Tabla de eventos"]').screenshot('06-tabla-sin-pais', { overwrite: true });
    cy.get('[data-testid=filter-country]').select('');

    cy.get('[data-testid=events-table] tbody tr').first().click();
    cy.get('[data-testid=selected-event]').should('be.visible');
    cy.scrollTo('top');
    cy.wait(1500);
    cy.screenshot('07-ficha-evento', { capture: 'viewport', overwrite: true });
  });

  it('reproducción', () => {
    cy.get('[data-testid=filter-mode]').select('replay');
    cy.get('[data-testid=replay-badge]').should('be.visible');
    cy.get('[data-testid=total-count]').should('have.text', '23');
    cy.wait(2500);
    cy.screenshot('12-replay', { capture: 'viewport', overwrite: true });
  });

  it('fallo y recuperación del túnel', () => {
    cy.task('compose', ['stop', 'ngrok'], { timeout: 90000 });
    cy.get('[data-testid=failure-banner]', { timeout: 60000 }).should('be.visible');
    cy.wait(800);
    cy.screenshot('13-banner-fallo', { capture: 'viewport', overwrite: true });
    cy.task('compose', ['start', 'ngrok'], { timeout: 90000 });
    cy.get('[data-testid=failure-banner]', { timeout: 120000 }).should('not.exist');
    cy.wait(1500);
    cy.screenshot('14-recuperado', { capture: 'viewport', overwrite: true });
  });
});

/// <reference types="cypress" />

/**
 * End-to-end tests of the dashboard against a simulated API that really applies
 * the filters, so a filter change must propagate to every view.
 */
const API = 'http://api.test';
const HOUR = 3600_000;
const REPLAY_LOADED = 1793000000000;

interface Quake {
  id: string; hoursAgo: number; mag: number | null; depth: number | null;
  country_id: string | null; country: string; subregion: string | null; lon: number; lat: number;
}

const QUAKES: Quake[] = [
  { id: 'q1', hoursAgo: 1, mag: 6.1, depth: 30, country_id: 'JPN', country: 'Japón', subregion: 'Eastern Asia', lon: 140, lat: 36 },
  { id: 'q2', hoursAgo: 2, mag: 4.2, depth: 80, country_id: 'JPN', country: 'Japón', subregion: 'Eastern Asia', lon: 141, lat: 37 },
  { id: 'q3', hoursAgo: 3, mag: 5.4, depth: 400, country_id: 'CHL', country: 'Chile', subregion: 'South America', lon: -70, lat: -30 },
  { id: 'q4', hoursAgo: 5, mag: 3.1, depth: 10, country_id: 'CHL', country: 'Chile', subregion: 'South America', lon: -71, lat: -31 },
  { id: 'q5', hoursAgo: 6, mag: null, depth: 12, country_id: null, country: 'Sin país asignado', subregion: null, lon: -140, lat: 0 },
  { id: 'q6', hoursAgo: 9, mag: 5.0, depth: null, country_id: null, country: 'Sin país asignado', subregion: null, lon: 170, lat: -20 },
];

class FakeApi {
  up = true;
  mode: 'live' | 'replay' = 'live';
  revision = 0;
  calls = 0;
  readonly t0 = Date.now();
  lastIngestion = Date.now() - 60_000;

  private pick(url: URL, replay: boolean): Quake[] {
    const start = url.searchParams.get('start');
    const end = url.searchParams.get('end');
    const minMag = url.searchParams.get('min_mag');
    return QUAKES.filter((q) => {
      const t = this.t0 - q.hoursAgo * HOUR;
      if (replay !== (url.searchParams.get('mode') === 'replay')) return false;
      if (start && t < Date.parse(start)) return false;
      if (end && t >= Date.parse(end)) return false;
      if (minMag !== null && (q.mag === null || q.mag < Number(minMag))) return false;
      return true;
    });
  }

  events(url: URL) {
    const replay = url.searchParams.get('mode') === 'replay';
    const list = replay ? QUAKES.slice(0, 3).filter((q) => this.pickReplay(url, q)) : this.pick(url, false);
    return {
      type: 'FeatureCollection',
      metadata: {
        total: list.length, count: list.length, truncated: false, limit: 5000, offset: 0, null_magnitude_excluded: 0,
        generated: Date.now(), mode: replay ? 'replay' : 'live',
        ...(replay ? { replay_loaded_at: REPLAY_LOADED } : { last_ingestion: this.lastIngestion }),
      },
      features: list.map((q) => ({
        type: 'Feature', id: q.id,
        geometry: { type: 'Point', coordinates: [q.lon, q.lat, q.depth] },
        properties: {
          time: this.t0 - q.hoursAgo * HOUR, updated: this.revision, mag: q.id === 'q1' ? (q.mag as number) + this.revision : q.mag,
          magType: 'mb', place: `Lugar ${q.id}`, depth: q.depth, country_id: q.country_id, country_name: q.country_id ? q.country : null,
          subregion: q.subregion, geo_ambiguous: false,
        },
      })),
    };
  }

  private pickReplay(url: URL, q: Quake): boolean {
    const minMag = url.searchParams.get('min_mag');
    return !(minMag !== null && (q.mag === null || q.mag < Number(minMag)));
  }

  stats(url: URL) {
    const replay = url.searchParams.get('mode') === 'replay';
    const list = replay ? QUAKES.slice(0, 3).filter((q) => this.pickReplay(url, q)) : this.pick(url, false);
    const count = <K>(key: (q: Quake) => K) => {
      const m = new Map<K, number>();
      list.forEach((q) => m.set(key(q), (m.get(key(q)) ?? 0) + 1));
      return [...m];
    };
    const end = Date.parse(url.searchParams.get('end') ?? new Date().toISOString());
    const hourly = Array.from({ length: 24 }, (_, i) => {
      const h = Math.floor(end / HOUR) * HOUR - (23 - i) * HOUR;
      return { hour_utc: new Date(h).toISOString().replace('.000', ''), count: list.filter((q) => Math.floor((this.t0 - q.hoursAgo * HOUR) / HOUR) * HOUR === h).length };
    });
    const bin = (n: number) => Math.floor(n);
    const mags = new Map<number, number>();
    list.filter((q) => q.mag !== null).forEach((q) => mags.set(bin(q.mag!), (mags.get(bin(q.mag!)) ?? 0) + 1));
    const depthLabel = (d: number) => (d < 70 ? '<70 km' : d < 300 ? '70 a <300 km' : '>=300 km');
    const depths = new Map<string, number>();
    list.filter((q) => q.depth !== null).forEach((q) => depths.set(depthLabel(q.depth!), (depths.get(depthLabel(q.depth!)) ?? 0) + 1));
    return {
      filters: { start: url.searchParams.get('start'), end: url.searchParams.get('end') },
      total: list.length,
      by_country: count((q) => q.country_id ?? '').map(([id, n]) => {
        const q = list.find((x) => (x.country_id ?? '') === id)!;
        return { country_id: q.country_id, country: q.country, subregion: q.subregion, count: n };
      }),
      by_subregion: count((q) => q.subregion ?? 'Sin país asignado').map(([s, n]) => ({ subregion: s, count: n })),
      hourly,
      magnitude: { bins: [...mags].map(([from, n]) => ({ from, to: from + 1, label: `${from} a <${from + 1}`, count: n })), missing: list.filter((q) => q.mag === null).length },
      depth: { bins: [...depths].map(([label, n]) => ({ from: null, to: null, label, count: n })), missing: list.filter((q) => q.depth === null).length },
      comparison: { last_24h_count: list.length, last_24h_min_mag: 4, historical_year: 2025, historical_count: 18302, historical_days: 365, historical_daily_mean: 50.14, ratio: list.length / 50.14, note: 'El último periodo puede estar incompleto.' },
      missing: { magnitude: list.filter((q) => q.mag === null).length, depth: list.filter((q) => q.depth === null).length, country: list.filter((q) => !q.country_id).length, null_magnitude_excluded_by_min_mag: 0 },
      ...(replay ? { replay_loaded_at: REPLAY_LOADED } : { last_ingestion: this.lastIngestion }),
    };
  }

  health(url: URL) {
    const replay = url.searchParams.get('mode') === 'replay';
    return {
      status: 'ok', events: 6,
      period: replay
        ? { from: new Date(this.t0 - 3 * HOUR).toISOString(), to: new Date(this.t0 - 1 * HOUR).toISOString() }
        : { from: new Date(this.t0 - 9 * HOUR).toISOString(), to: new Date(this.t0 - 1 * HOUR).toISOString() },
      ...(replay ? { replay_loaded_at: REPLAY_LOADED } : { last_ingestion: this.lastIngestion }),
    };
  }
}

function setup(api: FakeApi) {
  cy.intercept('GET', '**/config.json', { apiUrl: API, refreshMs: 1000, skipNgrokWarning: true });
  cy.intercept('GET', 'https://tile.openstreetmap.org/**', { statusCode: 204, body: '' });
  const handler = (build: (url: URL) => unknown) => (req: Cypress.Request & { reply: Function; destroy: Function }) => {
    api.calls++;
    if (!api.up) return req.destroy();
    expect(req.headers['ngrok-skip-browser-warning']).to.eq('1');
    req.reply(build(new URL(req.url)));
  };
  cy.intercept('GET', `${API}/api/salud*`, handler((u) => api.health(u)));
  cy.intercept('GET', `${API}/api/eventos*`, handler((u) => api.events(u)));
  cy.intercept('GET', `${API}/api/estadisticas*`, handler((u) => api.stats(u)));
}

const sumValues = (selector: string) =>
  cy.get(`${selector} .value`).then(($els) => [...$els].reduce((s, e) => s + Number(e.textContent), 0));

describe('Observatorio dashboard', () => {
  let api: FakeApi;
  beforeEach(() => {
    api = new FakeApi();
    setup(api);
    cy.visit('/');
  });

  it('shows map markers, charts, counts and a table with ND for unknown magnitude', () => {
    cy.get('[data-testid=total-count]').should('have.text', '6');
    cy.get('[data-testid=marker-count]').should('have.text', '6');
    cy.get('[data-testid=table-count]').should('contain.text', '6');
    cy.get('[data-testid=legend]').should('contain.text', 'ND');
    cy.get('[data-testid=events-table] tr[data-id=q5] td').eq(1).should('have.text', 'ND');
    cy.get('[data-testid=chart-country]').should('contain.text', 'Sin país asignado');
    cy.get('[data-testid=chart-magnitude]').should('contain.text', 'ND');
    cy.get('[data-testid=chart-hourly] rect').should('have.length', 24);
    cy.get('[data-testid=status-panel]').should('contain.text', 'Accesible');
    cy.get('[data-testid=last-ingestion]').should('not.have.text', 'ND');
  });

  it('applies a minimum magnitude to map, charts, counts and table at once', () => {
    cy.get('[data-testid=marker-count]').should('have.text', '6');
    cy.get('[data-testid=filter-minmag]').type('5').blur();
    // magnitudes >= 5: q1 (6.1), q3 (5.4), q6 (5.0); ND is excluded, never treated as 0
    cy.get('[data-testid=total-count]').should('have.text', '3');
    cy.get('[data-testid=marker-count]').should('have.text', '3');
    cy.get('[data-testid=table-count]').should('contain.text', '3');
    cy.get('[data-testid=events-table] tbody tr').should('have.length', 3);
    cy.get('[data-testid=events-table] tr[data-id=q4]').should('not.exist');
    sumValues('[data-testid=chart-country]').should('eq', 3);
    sumValues('[data-testid=chart-subregion]').should('eq', 3);
    cy.get('[data-testid=chart-hourly] rect title').then(($t) => {
      const total = [...$t].reduce((s, e) => s + Number((e.textContent ?? '').split(': ')[1]), 0);
      expect(total).to.eq(3);
    });
    cy.get('[data-testid=chart-magnitude] rect title').then(($t) => {
      const total = [...$t].reduce((n, e) => n + Number((e.textContent ?? '').split(': ')[1]), 0);
      expect(total).to.eq(3 + 0); // 3 events with magnitude, ND (0) is the extra bar
    });
  });

  it('does not duplicate a marker when an event is revised', () => {
    cy.get('[data-testid=marker-count]').should('have.text', '6');
    cy.then(() => { api.revision = 1; });
    cy.wait(2500); // at least one more 1 s poll
    cy.get('[data-testid=marker-count]').should('have.text', '6');
    cy.get('[data-testid=events-table] tr[data-id=q1] td').eq(1).should('have.text', '7.1');
    cy.get('[data-testid=events-table] tbody tr').should('have.length', 6);
  });

  it('shows a failure banner keeping the last data, then recovers by itself', () => {
    cy.get('[data-testid=marker-count]').should('have.text', '6');
    cy.get('[data-testid=last-success]').invoke('text').then((lastSuccess) => {
      cy.get('[data-testid=failure-banner]').should('not.exist');
      cy.then(() => { api.up = false; }); // tunnel closed
      cy.get('[data-testid=failure-banner]', { timeout: 8000 }).should('be.visible').and('contain.text', lastSuccess);
      cy.get('[data-testid=api-state]').should('have.text', 'Sin respuesta');
      cy.get('[data-testid=marker-count]').should('have.text', '6'); // last data stays on screen
      cy.get('[data-testid=events-table] tbody tr').should('have.length', 6);
      cy.get('[data-testid=last-success]').should('have.text', lastSuccess);
      cy.then(() => { api.up = true; }); // tunnel reopened, nobody clicks anything
      cy.get('[data-testid=failure-banner]', { timeout: 8000 }).should('not.exist');
      cy.get('[data-testid=api-state]').should('have.text', 'Accesible');
      cy.get('[data-testid=last-success]').should('not.have.text', lastSuccess);
    });
  });

  it('labels replay mode and uses the replay interval', () => {
    cy.get('[data-testid=replay-badge]').should('not.exist');
    cy.get('[data-testid=filter-mode]').select('replay');
    cy.get('[data-testid=replay-badge]').should('be.visible').and('contain.text', 'REPRODUCCIÓN');
    cy.get('[data-testid=total-count]').should('have.text', '3');
    cy.get('[data-testid=filter-range]').should('not.exist');
    cy.get('[data-testid=last-ingestion]').should('have.text', new Date(REPLAY_LOADED).toISOString());
    cy.get('[data-testid=status-panel]').should('contain.text', 'Carga de la reproducción');
  });

  it('links table and map: selecting a row shows the event card and highlights the row', () => {
    cy.get('[data-testid=selected-event]').should('not.exist');
    cy.get('[data-testid=events-table] tr[data-id=q3]').click();
    cy.get('[data-testid=selected-event]').should('be.visible').and('contain.text', 'Lugar q3').and('contain.text', 'Chile');
    cy.get('[data-testid=events-table] tr[data-id=q3]').should('have.class', 'selected');
    cy.get('[data-testid=events-table] tr[data-id=q5]').click();
    cy.get('[data-testid=selected-event]').should('contain.text', 'ND').and('contain.text', 'Sin país asignado');
    cy.get('[data-testid=selected-event] button').click();
    cy.get('[data-testid=selected-event]').should('not.exist');
  });

  it('switches theme and shows the health pill', () => {
    cy.get('[data-testid=health-pill]').should('contain.text', 'Operativo');
    cy.get('[data-testid=theme-toggle]').click();
    cy.document().its('documentElement').invoke('getAttribute', 'data-theme').should('match', /dark|light/);
    cy.get('[data-testid=theme-toggle]').click();
  });

  it('keeps every chart usable through the tabs', () => {
    cy.get('[data-testid=chart-hourly]').should('be.visible');
    cy.get('[data-testid=chart-country]').should('not.be.visible');
    cy.contains('[role=tab]', 'Por lugar').click();
    cy.get('[data-testid=chart-country]').should('be.visible');
    cy.contains('[role=tab]', 'Distribuciones').click();
    cy.get('[data-testid=chart-magnitude]').should('be.visible');
    cy.get('[data-testid=chart-depth]').should('be.visible');
  });

  (Cypress.env('SHOTS') ? it : it.skip)('captures screenshots', () => {
    cy.get('[data-testid=marker-count]').should('have.text', '6');
    cy.get('[data-testid=events-table] tr[data-id=q1]').click();
    cy.wait(1200);
    cy.screenshot('desktop-light', { capture: 'fullPage' });
    cy.get('[data-testid=theme-toggle]').click();
    cy.contains('[role=tab]', 'Distribuciones').click();
    cy.wait(300);
    cy.screenshot('desktop-dark', { capture: 'fullPage' });
    cy.viewport(390, 844);
    cy.wait(500);
    cy.screenshot('mobile-dark', { capture: 'fullPage' });
  });

  it('never overlaps requests: a slow API gets one poll at a time', () => {
    let inflight = 0;
    let maxInflight = 0;
    cy.intercept('GET', `${API}/api/salud*`, (req) => {
      inflight++; maxInflight = Math.max(maxInflight, inflight);
      req.on('response', () => { inflight--; });
      req.reply({ delay: 2500, body: api.health(new URL(req.url)) });
    }).as('slowHealth');
    cy.wait(6000).then(() => expect(maxInflight).to.be.lte(1));
  });
});

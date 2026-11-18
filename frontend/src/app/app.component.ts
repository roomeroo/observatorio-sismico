import { Component, OnDestroy, OnInit, computed, inject, signal } from '@angular/core';
import { ApiService, EVENTS_LIMIT, iso } from './api.service';
import { Bar, BarChartComponent } from './bar-chart.component';
import { EventsTableComponent } from './events-table.component';
import { QuakeMapComponent } from './quake-map.component';
import { Mode, Range } from './query';

interface Option { value: string; label: string }

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [QuakeMapComponent, BarChartComponent, EventsTableComponent],
  templateUrl: './app.component.html',
  styleUrl: './app.component.css',
})
export class AppComponent implements OnInit, OnDestroy {
  readonly api = inject(ApiService);
  readonly iso = iso;
  readonly filters = this.api.filters;
  readonly snapshot = this.api.snapshot;
  readonly eventsLimit = EVENTS_LIMIT;
  readonly countries = signal<Option[]>([]);
  readonly subregions = signal<string[]>([]);
  readonly now = signal(Date.now());
  private clock?: ReturnType<typeof setInterval>;

  readonly isReplay = computed(() => this.filters().mode === 'replay');
  readonly hourlyBars = computed<Bar[]>(() =>
    (this.snapshot()?.stats.hourly ?? []).map((h) => ({ label: h.hour_utc.slice(5, 13).replace('T', ' ') + ':00', value: h.count })),
  );
  readonly countryBars = computed<Bar[]>(() =>
    (this.snapshot()?.stats.by_country ?? []).slice(0, 12).map((c) => ({ label: c.country, value: c.count, missing: !c.country_id })),
  );
  readonly subregionBars = computed<Bar[]>(() =>
    (this.snapshot()?.stats.by_subregion ?? []).slice(0, 10).map((s) => ({ label: s.subregion, value: s.count, missing: s.subregion === 'Sin país asignado' })),
  );
  readonly magnitudeBars = computed<Bar[]>(() => {
    const m = this.snapshot()?.stats.magnitude;
    return m ? [...m.bins.map((b) => ({ label: b.label, value: b.count })), { label: 'ND', value: m.missing, missing: true }] : [];
  });
  readonly depthBars = computed<Bar[]>(() => {
    const d = this.snapshot()?.stats.depth;
    return d ? [...d.bins.map((b) => ({ label: b.label, value: b.count })), { label: 'ND', value: d.missing, missing: true }] : [];
  });
  readonly truncated = computed(() => {
    return this.snapshot()?.events.metadata.truncated ?? false;
  });
  readonly ratioText = computed(() => {
    const c = this.snapshot()?.stats.comparison;
    if (!c) return 'ND';
    return c.ratio === null ? 'ND' : `${c.ratio.toFixed(2)}×`;
  });

  async ngOnInit(): Promise<void> {
    this.clock = setInterval(() => this.now.set(Date.now()), 15_000);
    void this.loadCatalog();
    await this.api.start();
  }

  ngOnDestroy(): void {
    clearInterval(this.clock);
  }

  private async loadCatalog(): Promise<void> {
    try {
      const response = await fetch('datos/paises.geojson');
      const data = (await response.json()) as { features: { properties: Record<string, string> }[] };
      const byId = new Map<string, string>();
      const subs = new Set<string>();
      for (const f of data.features) {
        byId.set(f.properties['ADM0_A3'], f.properties['NAME_ES'] ?? f.properties['ADMIN']);
        if (f.properties['SUBREGION']) subs.add(f.properties['SUBREGION']);
      }
      this.countries.set([...byId].map(([value, label]) => ({ value, label })).sort((a, b) => a.label.localeCompare(b.label, 'es')));
      this.subregions.set([...subs].sort());
    } catch {
      /* the selectors simply stay with their fixed options */
    }
  }

  onMode(value: string): void { this.api.setFilters({ mode: value as Mode }); }
  onRange(value: string): void { this.api.setFilters({ range: value as Range }); }
  onStart(value: string): void { this.api.setFilters({ start: value }); }
  onEnd(value: string): void { this.api.setFilters({ end: value }); }
  onMinMag(value: string): void {
    const n = value.trim() === '' ? null : Number(value);
    this.api.setFilters({ minMag: n !== null && Number.isFinite(n) ? n : null });
  }
  onCountry(value: string): void { this.api.setFilters({ country: value }); }
  onSubregion(value: string): void { this.api.setFilters({ subregion: value }); }
  resetFilters(): void {
    this.api.setFilters({ range: '24h', start: '', end: '', minMag: null, country: '', subregion: '' });
  }
  retry(): void { this.api.retryNow(); }
}

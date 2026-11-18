import { Injectable, OnDestroy, computed, signal } from '@angular/core';
import type { FeatureCollection, Point } from 'geojson';
import { Poller } from './poller';
import { DEFAULT_FILTERS, FilterState, Mode, buildQuery, resolveInterval } from './query';

/** Unix milliseconds (contract date format) to ISO-8601 UTC; ND when unknown. */
export function iso(ms: number | null | undefined): string {
  return typeof ms === 'number' && Number.isFinite(ms) ? new Date(ms).toISOString() : 'ND';
}

/** Round for display (USGS floats like 10.7399997711182 are noise); ND when unknown. */
export function num(value: number | null | undefined, digits = 1): string {
  return typeof value === 'number' && Number.isFinite(value) ? String(Number(value.toFixed(digits))) : 'ND';
}

export interface EventProps {
  time: number | null;
  updated: number;
  mag: number | null;
  magType: string | null;
  place: string | null;
  depth: number | null;
  country_id: string | null;
  country_name: string | null;
  subregion: string | null;
  geo_ambiguous: boolean;
}
export interface EventsMetadata {
  generated: number;
  last_ingestion?: number | null;
  replay_loaded_at?: number | null;
  mode: Mode;
  count: number;
  truncated: boolean;
  total: number;
  limit: number;
  offset: number;
  null_magnitude_excluded: number;
}
export type EventsResponse = FeatureCollection<Point, EventProps> & { metadata: EventsMetadata };

export interface Bin { label: string; count: number; from: number | null; to: number | null }
export interface StatsResponse {
  filters: { start: string; end: string };
  total: number;
  by_country: { country_id: string | null; country: string; subregion: string | null; count: number }[];
  by_subregion: { subregion: string; count: number }[];
  hourly: { hour_utc: string; count: number }[];
  magnitude: { bins: Bin[]; missing: number };
  depth: { bins: Bin[]; missing: number };
  comparison: {
    last_24h_count: number;
    historical_daily_mean: number;
    historical_year: number;
    historical_days: number;
    ratio: number | null;
    note: string;
  };
  missing: { magnitude: number; depth: number; country: number; null_magnitude_excluded_by_min_mag: number };
  last_ingestion?: number | null;
  replay_loaded_at?: number | null;
}
export interface HealthResponse {
  status: string;
  last_ingestion?: number | null;
  replay_loaded_at?: number | null;
  period: { from: string | null; to: string | null };
  events: number;
  last_poll?: { polled_at: string; status: string; latency_ms: number | null } | null;
}
export interface AppConfig { apiUrl: string; refreshMs: number; skipNgrokWarning: boolean }
export interface Snapshot { events: EventsResponse; stats: StatsResponse; health: HealthResponse; fetchedAt: string }

export const EVENTS_LIMIT = 5000;
export const STALE_AFTER_MS = 15 * 60_000;

@Injectable({ providedIn: 'root' })
export class ApiService implements OnDestroy {
  readonly filters = signal<FilterState>({ ...DEFAULT_FILTERS });
  readonly snapshot = signal<Snapshot | null>(null);
  readonly lastSuccessAt = signal<string | null>(null);
  readonly failure = signal<{ since: string; message: string } | null>(null);
  readonly loading = signal(false);
  readonly configError = signal<string | null>(null);
  readonly apiUrl = signal('');

  /** Data stays visible during a failure; this flags that it is the last known reading. */
  readonly stale = computed(() => this.failure() !== null && this.snapshot() !== null);
  readonly ingestionOld = computed(() => {
    const s = this.snapshot();
    const last = s?.health.last_ingestion;
    return this.filters().mode === 'live' && typeof last === 'number' && Date.now() - last > STALE_AFTER_MS;
  });

  private config?: AppConfig;
  private poller?: Poller;
  private controller = new AbortController();

  async start(): Promise<void> {
    try {
      const response = await fetch('config.json', { cache: 'no-store' });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const cfg = (await response.json()) as AppConfig;
      if (typeof cfg.apiUrl !== 'string' || !cfg.apiUrl) throw new Error('apiUrl ausente');
      this.config = { ...cfg, refreshMs: Math.max(1000, Number(cfg.refreshMs) || 60_000) };
      this.apiUrl.set(this.config.apiUrl.replace(/\/$/, ''));
    } catch {
      this.configError.set('No se pudo leer config.json: revisa public/config.json.');
      return;
    }
    this.poller = new Poller(() => this.fetchAll(), this.config.refreshMs);
    this.poller.start();
  }

  setFilters(patch: Partial<FilterState>): void {
    this.filters.update((f) => ({ ...f, ...patch }));
    this.poller?.refreshNow();
  }

  retryNow(): void {
    this.poller?.refreshNow();
  }

  ngOnDestroy(): void {
    this.poller?.stop();
    this.controller.abort();
  }

  private async get<T>(path: string, params: URLSearchParams): Promise<T> {
    const headers: Record<string, string> = {};
    if (this.config?.skipNgrokWarning) headers['ngrok-skip-browser-warning'] = '1';
    const query = params.toString();
    const response = await fetch(`${this.apiUrl()}${path}${query ? `?${query}` : ''}`, {
      headers,
      cache: 'no-store',
      signal: AbortSignal.any([this.controller.signal, AbortSignal.timeout(15_000)]),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return (await response.json()) as T;
  }

  private async fetchAll(): Promise<void> {
    this.loading.set(true);
    const filters = this.filters();
    try {
      const modeParams = buildQuery(filters, null);
      const health = await this.get<HealthResponse>('/api/salud', modeParams);
      const interval = resolveInterval(filters, new Date(), health.period);
      const [events, stats] = await Promise.all([
        this.get<EventsResponse>('/api/eventos', buildQuery(filters, interval, { limit: EVENTS_LIMIT })),
        this.get<StatsResponse>('/api/estadisticas', buildQuery(filters, interval)),
      ]);
      if (filters !== this.filters()) return; // filters changed meanwhile: the queued refresh will replace this
      const now = new Date().toISOString();
      this.snapshot.set({ events, stats, health, fetchedAt: now });
      this.lastSuccessAt.set(now);
      this.failure.set(null);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'error desconocido';
      this.failure.update((f) => f ?? { since: new Date().toISOString(), message });
      if (this.failure()) this.failure.update((f) => (f ? { ...f, message } : f));
    } finally {
      this.loading.set(false);
    }
  }
}

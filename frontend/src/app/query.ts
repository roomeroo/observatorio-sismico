/** Shared filter state and its translation into API query parameters. */
export type Mode = 'live' | 'replay';
export type Range = '24h' | '7d' | '30d' | 'custom';

export interface FilterState {
  mode: Mode;
  range: Range;
  start: string; // ISO 8601, used when range === 'custom'
  end: string;
  minMag: number | null;
  country: string; // ADM0_A3, 'SIN_PAIS' or '' for all
  subregion: string; // '' for all
}

export const DEFAULT_FILTERS: FilterState = {
  mode: 'live',
  range: '24h',
  start: '',
  end: '',
  minMag: null,
  country: '',
  subregion: '',
};

const RANGE_HOURS: Record<Exclude<Range, 'custom'>, number> = { '24h': 24, '7d': 168, '30d': 720 };

/** Concrete [start, end) interval for the current filter state. */
export function resolveInterval(
  filters: FilterState,
  now: Date,
  replayPeriod?: { from: string | null; to: string | null } | null,
): { start: string; end: string } | null {
  if (filters.mode === 'replay') {
    if (!replayPeriod?.from || !replayPeriod?.to) return null;
    // `to` is the latest event time; the interval end is exclusive.
    return { start: replayPeriod.from, end: new Date(Date.parse(replayPeriod.to) + 1000).toISOString() };
  }
  if (filters.range === 'custom') {
    if (!filters.start || !filters.end) return null;
    return { start: new Date(filters.start).toISOString(), end: new Date(filters.end).toISOString() };
  }
  const end = now;
  const start = new Date(end.getTime() - RANGE_HOURS[filters.range] * 3600_000);
  return { start: start.toISOString(), end: end.toISOString() };
}

export function buildQuery(
  filters: FilterState,
  interval: { start: string; end: string } | null,
  extra: Record<string, string | number> = {},
): URLSearchParams {
  const p = new URLSearchParams();
  if (interval) {
    p.set('start', interval.start);
    p.set('end', interval.end);
  }
  if (filters.minMag !== null && Number.isFinite(filters.minMag)) p.set('min_mag', String(filters.minMag));
  if (filters.country) p.set('country_id', filters.country);
  if (filters.subregion) p.set('subregion', filters.subregion);
  if (filters.mode === 'replay') p.set('mode', 'replay');
  for (const [k, v] of Object.entries(extra)) p.set(k, String(v));
  return p;
}

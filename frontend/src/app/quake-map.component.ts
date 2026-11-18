import { AfterViewInit, Component, ElementRef, OnDestroy, ViewChild, effect, input, output, signal } from '@angular/core';
import * as L from 'leaflet';
import type { FeatureCollection } from 'geojson';
import { iso, type EventsResponse } from './api.service';

export const DEPTH_COLORS = { shallow: '#e8a317', mid: '#e35b37', deep: '#7b3fb6', unknown: '#64748b' } as const;

export function depthColor(depth: number | null): string {
  if (depth === null || !Number.isFinite(depth)) return DEPTH_COLORS.unknown;
  return depth < 70 ? DEPTH_COLORS.shallow : depth < 300 ? DEPTH_COLORS.mid : DEPTH_COLORS.deep;
}
export function magRadius(mag: number | null): number {
  return mag === null || !Number.isFinite(mag) ? 4 : Math.max(3, Math.min(18, 3 + (mag + 1) * 2));
}

@Component({
  selector: 'app-quake-map',
  standalone: true,
  template: `
    <div class="wrap">
      <div #host class="map" data-testid="map" aria-label="Mapa interactivo de terremotos"></div>
      <div class="legend" data-testid="legend" aria-label="Leyenda del mapa">
        <strong>Profundidad</strong>
        <span><i class="dot" style="background:#e8a317"></i> &lt; 70 km</span>
        <span><i class="dot" style="background:#e35b37"></i> 70–299 km</span>
        <span><i class="dot" style="background:#7b3fb6"></i> ≥ 300 km</span>
        <span><i class="dot" style="background:#64748b"></i> prof. ND</span>
        <span><i class="dot nd"></i> magnitud ND</span>
        <small>Tamaño ∝ magnitud (escala visual, no energía) · <span data-testid="marker-count">{{ markerCount() }}</span> marcadores</small>
      </div>
    </div>
  `,
  styles: [
    `
      :host { display: block; height: 100%; }
      .wrap { position: relative; height: 100%; min-height: 420px; }
      .map { position: absolute; inset: 0; border-radius: 12px; z-index: 0; }
      .legend {
        position: absolute; left: 10px; bottom: 10px; z-index: 500; max-width: calc(100% - 20px);
        display: flex; flex-wrap: wrap; gap: 0.2rem 0.8rem; align-items: center; padding: 0.4rem 0.65rem;
        font-size: 0.75rem; background: color-mix(in srgb, var(--surface) 92%, transparent);
        border: 1px solid var(--border); border-radius: 8px; box-shadow: var(--shadow); backdrop-filter: blur(4px);
      }
      .legend small { flex-basis: 100%; color: var(--muted); }
      .dot { display: inline-block; width: 0.7rem; height: 0.7rem; border-radius: 50%; vertical-align: middle; }
      .dot.nd { background: #fff; border: 2px dashed #334155; box-sizing: border-box; }
    `,
  ],
})
export class QuakeMapComponent implements AfterViewInit, OnDestroy {
  @ViewChild('host', { static: true }) private host!: ElementRef<HTMLDivElement>;
  readonly events = input<EventsResponse | null>(null);
  readonly selectedId = input<string | null>(null);
  readonly selected = output<string>();
  readonly markerCount = signal(0);

  private map?: L.Map;
  private layer = L.layerGroup();
  private markers = new Map<string, L.CircleMarker>();
  private styles = new Map<string, L.CircleMarkerOptions>();
  private ready = signal(false);
  private highlighted?: string;

  constructor() {
    effect(() => {
      const data = this.events();
      if (this.ready()) this.render(data);
    });
    effect(() => {
      const id = this.selectedId();
      if (this.ready()) this.focus(id);
    });
  }

  async ngAfterViewInit(): Promise<void> {
    this.map = L.map(this.host.nativeElement, { center: [18, 0], zoom: 2, minZoom: 2, maxZoom: 8, preferCanvas: true, worldCopyJump: false });
    const base = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      noWrap: true,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(this.map);
    const borders = L.geoJSON(undefined, { style: { color: '#64748b', weight: 1, fill: false } }).addTo(this.map);
    this.layer.addTo(this.map);
    L.control.layers({ OpenStreetMap: base }, { 'Países (Natural Earth)': borders, Terremotos: this.layer }, { position: 'topright' }).addTo(this.map);
    this.map.attributionControl.addAttribution('Fronteras: Natural Earth · Datos: USGS');
    this.ready.set(true);
    // The container is sized by the CSS grid after first paint.
    setTimeout(() => this.map?.invalidateSize(), 0);
    try {
      const response = await fetch('datos/paises.geojson');
      if (response.ok) borders.addData((await response.json()) as FeatureCollection);
    } catch {
      /* borders are optional */
    }
  }

  ngOnDestroy(): void {
    this.map?.remove();
  }

  /** Upsert by event id so a revised event moves/updates its marker instead of duplicating it. */
  private render(data: EventsResponse | null): void {
    const seen = new Set<string>();
    for (const f of data?.features ?? []) {
      const id = String(f.id ?? '');
      const [lon, lat, depth] = f.geometry?.coordinates ?? [];
      const p = f.properties;
      if (!id || !p || !Number.isFinite(lon) || !Number.isFinite(lat) || Math.abs(lon) > 180 || Math.abs(lat) > 90) continue;
      seen.add(id);
      const nd = p.mag === null;
      const color = depthColor(typeof depth === 'number' ? depth : null);
      const style: L.CircleMarkerOptions = nd
        ? { radius: magRadius(null), color: '#334155', fillColor: '#ffffff', fillOpacity: 0.9, weight: 2, dashArray: '3 3' }
        : { radius: magRadius(p.mag), color, fillColor: color, fillOpacity: 0.75, weight: 1, dashArray: undefined };
      this.styles.set(id, style);
      let marker = this.markers.get(id);
      if (marker) {
        marker.setLatLng([lat, lon]).setStyle(id === this.highlighted ? this.hi(style) : style).setRadius(style.radius!);
      } else {
        marker = L.circleMarker([lat, lon], style).addTo(this.layer);
        marker.on('click', () => this.selected.emit(id));
        this.markers.set(id, marker);
      }
      marker.unbindPopup().bindPopup(this.card(id, p, depth));
    }
    for (const [id, marker] of this.markers) {
      if (!seen.has(id)) {
        this.layer.removeLayer(marker);
        this.markers.delete(id);
        this.styles.delete(id);
      }
    }
    this.markerCount.set(this.markers.size);
  }

  private hi(style: L.CircleMarkerOptions): L.CircleMarkerOptions {
    return { ...style, weight: 3, color: '#2563eb', fillOpacity: 1 };
  }

  private focus(id: string | null): void {
    if (this.highlighted) {
      const old = this.markers.get(this.highlighted);
      const style = this.styles.get(this.highlighted);
      if (old && style) old.setStyle(style);
    }
    this.highlighted = undefined;
    if (!id) return;
    const marker = this.markers.get(id);
    const style = this.styles.get(id);
    if (!marker || !style || !this.map) return;
    this.highlighted = id;
    marker.setStyle(this.hi(style)).bringToFront();
    this.map.flyTo(marker.getLatLng(), Math.max(this.map.getZoom(), 4), { duration: 0.6 });
    marker.openPopup();
  }

  private card(id: string, p: NonNullable<EventsResponse['features'][number]['properties']>, depth: number | undefined): HTMLElement {
    const box = document.createElement('div');
    box.className = 'quake-card';
    const rows: [string, string][] = [
      ['Lugar', p.place ?? 'Sin descripción'],
      ['Magnitud', p.mag === null ? 'ND' : `${p.mag}${p.magType ? ' ' + p.magType : ''}`],
      ['Profundidad', typeof depth === 'number' ? `${depth} km` : 'ND'],
      ['Fecha UTC', iso(p.time)],
      ['País', p.country_name ?? 'Sin país asignado'],
      ['ID', id],
    ];
    for (const [k, v] of rows) {
      const line = document.createElement('div');
      const b = document.createElement('strong');
      b.textContent = `${k}: `;
      line.append(b, document.createTextNode(v));
      box.append(line);
    }
    return box;
  }
}

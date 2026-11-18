import { AfterViewInit, Component, ElementRef, OnDestroy, ViewChild, effect, input, signal } from '@angular/core';
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
    <div #host class="map" data-testid="map" aria-label="Mapa interactivo de terremotos"></div>
    <div class="legend" data-testid="legend" aria-label="Leyenda del mapa">
      <strong>Profundidad</strong>
      <span><i class="dot" style="background:#e8a317"></i> &lt; 70 km</span>
      <span><i class="dot" style="background:#e35b37"></i> 70–299,99 km</span>
      <span><i class="dot" style="background:#7b3fb6"></i> ≥ 300 km</span>
      <span><i class="dot" style="background:#64748b"></i> profundidad ND</span>
      <span><i class="dot nd"></i> magnitud ND (anillo discontinuo)</span>
      <small>Tamaño creciente con la magnitud (escala visual, no energía). <span data-testid="marker-count">{{ markerCount() }}</span> marcadores.</small>
    </div>
  `,
  styles: [
    `
      :host { display: block; }
      .map { height: 460px; border-radius: 8px; border: 1px solid #cbd5e1; }
      .legend { display: flex; flex-wrap: wrap; gap: 0.35rem 1rem; align-items: center; padding: 0.5rem 0; font-size: 0.85rem; }
      .dot { display: inline-block; width: 0.8rem; height: 0.8rem; border-radius: 50%; vertical-align: middle; }
      .dot.nd { background: #fff; border: 2px dashed #334155; box-sizing: border-box; }
    `,
  ],
})
export class QuakeMapComponent implements AfterViewInit, OnDestroy {
  @ViewChild('host', { static: true }) private host!: ElementRef<HTMLDivElement>;
  readonly events = input<EventsResponse | null>(null);
  readonly markerCount = signal(0);

  private map?: L.Map;
  private layer = L.layerGroup();
  private markers = new Map<string, L.CircleMarker>();
  private ready = signal(false);

  constructor() {
    effect(() => {
      const data = this.events();
      if (this.ready()) this.render(data);
    });
  }

  async ngAfterViewInit(): Promise<void> {
    this.map = L.map(this.host.nativeElement, { center: [18, 0], zoom: 2, minZoom: 2, maxZoom: 8, preferCanvas: true, worldCopyJump: false });
    const base = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      noWrap: true,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(this.map);
    const borders = L.geoJSON(undefined, { style: { color: '#334155', weight: 1, fill: false } }).addTo(this.map);
    this.layer.addTo(this.map);
    L.control.layers({ OpenStreetMap: base }, { 'Países (Natural Earth)': borders, Terremotos: this.layer }).addTo(this.map);
    this.map.attributionControl.addAttribution('Fronteras: Natural Earth · Datos: USGS');
    this.ready.set(true);
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
      let marker = this.markers.get(id);
      if (marker) {
        marker.setLatLng([lat, lon]).setStyle(style).setRadius(style.radius!);
      } else {
        marker = L.circleMarker([lat, lon], style).addTo(this.layer);
        this.markers.set(id, marker);
      }
      marker.unbindPopup().bindPopup(this.card(id, p, depth));
    }
    for (const [id, marker] of this.markers) {
      if (!seen.has(id)) {
        this.layer.removeLayer(marker);
        this.markers.delete(id);
      }
    }
    this.markerCount.set(this.markers.size);
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

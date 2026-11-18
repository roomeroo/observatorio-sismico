import { ChangeDetectionStrategy, Component, computed, input, output, signal } from '@angular/core';
import { iso, num, type EventsResponse } from './api.service';

type SortKey = 'time' | 'mag' | 'depth';

@Component({
  selector: 'app-events-table',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="table-head">
      <h3>Eventos <span data-testid="table-count">({{ rows().length }})</span></h3>
      <div class="sort" role="group" aria-label="Ordenar tabla">
        @for (k of keys; track k.key) {
          <button type="button" [class.active]="sortKey() === k.key" (click)="sortBy(k.key)" [attr.aria-pressed]="sortKey() === k.key">
            {{ k.label }} {{ sortKey() === k.key ? (desc() ? '↓' : '↑') : '' }}
          </button>
        }
      </div>
    </div>
    <div class="scroll">
      <table data-testid="events-table">
        <caption class="sr-only">Eventos sísmicos del periodo y filtros seleccionados</caption>
        <thead>
          <tr><th scope="col">Fecha UTC</th><th scope="col">Magnitud</th><th scope="col">Profundidad (km)</th><th scope="col">País</th><th scope="col">Lugar</th><th scope="col">ID</th></tr>
        </thead>
        <tbody>
          @for (r of page(); track r.id) {
            <tr [attr.data-id]="r.id" [class.selected]="r.id === selectedId()" tabindex="0" (click)="select.emit(r.id)" (keydown.enter)="select.emit(r.id)" [attr.aria-selected]="r.id === selectedId()">
              <td>{{ iso(r.time) }}</td>
              <td [class.nd]="r.mag === null">{{ num(r.mag, 2) }}</td>
              <td>{{ num(r.depth) }}</td>
              <td [class.nd]="!r.countryId">{{ r.country }}</td>
              <td>{{ r.place ?? 'Sin descripción' }}</td>
              <td>{{ r.id }}</td>
            </tr>
          } @empty {
            <tr><td colspan="6" class="empty">Sin eventos para los filtros actuales.</td></tr>
          }
        </tbody>
      </table>
    </div>
    <nav class="pager" aria-label="Paginación de la tabla">
      <button type="button" (click)="go(-1)" [disabled]="pageIndex() === 0">Anterior</button>
      <span>Página {{ pageIndex() + 1 }} de {{ pages() }}</span>
      <button type="button" (click)="go(1)" [disabled]="pageIndex() >= pages() - 1">Siguiente</button>
    </nav>
  `,
  styles: [
    `
      .table-head { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 0.5rem; }
      h3 { margin: 0; }
      .sort button, .pager button { margin-right: 0.3rem; padding: 0.2rem 0.6rem; border: 1px solid var(--border); border-radius: 6px; background: var(--surface); cursor: pointer; }
      .sort button.active { background: var(--accent); color: #fff; border-color: var(--accent); }
      tbody tr { cursor: pointer; }
      tbody tr:hover { background: var(--surface-2); }
      tbody tr.selected { background: var(--accent-soft); }
      .scroll { overflow-x: auto; }
      table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
      th, td { text-align: left; padding: 0.3rem 0.5rem; border-bottom: 1px solid var(--border); white-space: nowrap; }
      td.nd { color: var(--muted); font-style: italic; }
      th { position: sticky; top: 0; background: var(--surface); font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted); }
      .scroll { max-height: 380px; overflow: auto; }
      .empty { color: var(--muted); }
      .pager { display: flex; gap: 0.5rem; align-items: center; margin-top: 0.5rem; }
      .sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
    `,
  ],
})
export class EventsTableComponent {
  readonly events = input<EventsResponse | null>(null);
  readonly selectedId = input<string | null>(null);
  readonly select = output<string>();
  readonly pageSize = 25;
  readonly iso = iso;
  readonly num = num;
  readonly keys: { key: SortKey; label: string }[] = [
    { key: 'time', label: 'Fecha' },
    { key: 'mag', label: 'Magnitud' },
    { key: 'depth', label: 'Profundidad' },
  ];
  readonly sortKey = signal<SortKey>('time');
  readonly desc = signal(true);
  readonly pageIndex = signal(0);

  readonly rows = computed(() => {
    const list = (this.events()?.features ?? []).map((f) => ({
      id: String(f.id ?? ''),
      time: f.properties.time,
      mag: f.properties.mag,
      depth: f.properties.depth,
      country: f.properties.country_name ?? 'Sin país asignado',
      countryId: f.properties.country_id,
      place: f.properties.place,
    }));
    const key = this.sortKey();
    const sign = this.desc() ? -1 : 1;
    // Unknown values (ND) always sort last, never as zero.
    return list.sort((a, b) => {
      const av = a[key];
      const bv = b[key];
      if (av === null && bv === null) return 0;
      if (av === null) return 1;
      if (bv === null) return -1;
      return (av - bv) * sign;
    });
  });
  readonly pages = computed(() => Math.max(1, Math.ceil(this.rows().length / this.pageSize)));
  readonly page = computed(() => {
    const start = Math.min(this.pageIndex(), this.pages() - 1) * this.pageSize;
    return this.rows().slice(start, start + this.pageSize);
  });

  sortBy(key: SortKey): void {
    if (this.sortKey() === key) this.desc.update((d) => !d);
    else {
      this.sortKey.set(key);
      this.desc.set(true);
    }
    this.pageIndex.set(0);
  }
  go(delta: number): void {
    this.pageIndex.update((i) => Math.min(this.pages() - 1, Math.max(0, i + delta)));
  }
}

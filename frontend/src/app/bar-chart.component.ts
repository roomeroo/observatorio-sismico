import { ChangeDetectionStrategy, Component, computed, input, signal } from '@angular/core';

export interface Bar { label: string; value: number; missing?: boolean }

/** Dependency-free SVG bar chart: vertical (time series / distributions) or horizontal (rankings). */
@Component({
  selector: 'app-bar-chart',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <figure class="chart" [attr.data-testid]="testId()">
      <figcaption>
        <span class="title">{{ title() }}</span>
        <span class="readout" aria-live="polite">{{ readout() }}</span>
      </figcaption>
      @if (bars().length === 0 || max() === 0) {
        <p class="empty">Sin datos para los filtros actuales.</p>
      }
      @if (layout() === 'vertical') {
        <svg [attr.viewBox]="'0 0 ' + width + ' ' + height" role="img" [attr.aria-label]="title()" preserveAspectRatio="none">
          @for (t of ticks(); track t) {
            <line [attr.x1]="left" [attr.x2]="width - 4" [attr.y1]="y(t)" [attr.y2]="y(t)" class="grid" />
            <text [attr.x]="left - 4" [attr.y]="y(t) + 3" class="tick" text-anchor="end">{{ t }}</text>
          }
          @for (b of bars(); track $index; let i = $index) {
            <rect
              [attr.x]="left + i * step()"
              [attr.y]="y(b.value)"
              [attr.width]="barWidth()"
              [attr.height]="innerBottom - y(b.value)"
              [class.missing]="b.missing"
              [class.active]="hover() === i"
              class="bar"
              (mouseenter)="hover.set(i)"
              (mouseleave)="hover.set(null)">
              <title>{{ b.label }}: {{ b.value }}</title>
            </rect>
          }
          <line [attr.x1]="left" [attr.x2]="width - 4" [attr.y1]="innerBottom" [attr.y2]="innerBottom" class="axis" />
          @for (i of labelIdx(); track i) {
            <text [attr.x]="left + i * step() + barWidth() / 2" [attr.y]="height - 3" class="tick" [attr.text-anchor]="i === 0 ? 'start' : i === bars().length - 1 ? 'end' : 'middle'">{{ bars()[i].label }}</text>
          }
        </svg>
      } @else {
        <ol class="hbars">
          @for (b of bars(); track $index; let i = $index) {
            <li [class.missing]="b.missing" [class.active]="hover() === i" (mouseenter)="hover.set(i)" (mouseleave)="hover.set(null)">
              <span class="name" [title]="b.label">{{ b.label }}</span>
              <span class="track"><span class="fill" [style.width.%]="pct(b.value)"></span></span>
              <span class="value">{{ b.value }}</span>
            </li>
          }
        </ol>
      }
    </figure>
  `,
  styles: [
    `
      .chart { margin: 0; }
      figcaption { display: flex; justify-content: space-between; gap: 0.5rem; align-items: baseline; margin-bottom: 0.35rem; flex-wrap: wrap; }
      .title { font-weight: 600; font-size: 0.9rem; }
      .readout { font-size: 0.78rem; color: var(--muted); min-height: 1em; }
      svg { width: 100%; height: 170px; display: block; }
      .bar { fill: var(--accent); opacity: 0.85; transition: opacity 0.1s; }
      .bar.active { opacity: 1; }
      .bar.missing { fill: var(--nd); }
      .grid { stroke: var(--border); stroke-width: 1; }
      .axis { stroke: var(--muted); stroke-width: 1; }
      .tick { font-size: 9px; fill: var(--muted); }
      .empty { color: var(--muted); font-size: 0.85rem; margin: 0.25rem 0; }
      .hbars { list-style: none; margin: 0; padding: 0; display: grid; gap: 0.3rem; }
      .hbars li { display: grid; grid-template-columns: minmax(6rem, 9rem) 1fr 3rem; gap: 0.5rem; align-items: center; font-size: 0.82rem; border-radius: 4px; padding: 1px 2px; }
      .hbars li.active { background: var(--surface-2); }
      .name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
      .track { background: var(--border); height: 0.65rem; border-radius: 999px; overflow: hidden; }
      .fill { display: block; height: 100%; background: var(--accent); border-radius: 999px; }
      li.missing .fill { background: var(--nd); }
      .value { text-align: right; font-weight: 600; }
    `,
  ],
})
export class BarChartComponent {
  readonly title = input.required<string>();
  readonly bars = input.required<Bar[]>();
  readonly layout = input<'vertical' | 'horizontal'>('vertical');
  readonly testId = input<string>('chart');
  readonly hover = signal<number | null>(null);

  readonly width = 600;
  readonly height = 170;
  readonly left = 30;
  readonly bottom = 16;
  readonly top = 8;
  readonly innerBottom = this.height - this.bottom;

  readonly max = computed(() => Math.max(0, ...this.bars().map((b) => b.value)));
  readonly step = computed(() => (this.width - this.left - 4) / Math.max(1, this.bars().length));
  readonly barWidth = computed(() => Math.max(1, this.step() * 0.78));
  readonly ticks = computed(() => {
    const m = this.max();
    if (m === 0) return [0];
    return [...new Set([0, Math.round(m / 2), m])];
  });
  /** Up to 6 evenly spaced x labels (always first and last) to avoid overlap. */
  readonly labelIdx = computed(() => {
    const n = this.bars().length;
    if (n === 0) return [];
    const k = Math.min(6, n);
    return [...new Set(Array.from({ length: k }, (_, i) => Math.round((i * (n - 1)) / Math.max(1, k - 1))))];
  });
  readonly readout = computed(() => {
    const i = this.hover();
    const b = i === null ? undefined : this.bars()[i];
    return b ? `${b.label} · ${b.value}` : '';
  });

  y(value: number): number {
    const m = this.max();
    const h = this.innerBottom - this.top;
    return m === 0 ? this.innerBottom : this.innerBottom - (value / m) * h;
  }
  pct(value: number): number {
    const m = this.max();
    return m === 0 ? 0 : (value / m) * 100;
  }
}

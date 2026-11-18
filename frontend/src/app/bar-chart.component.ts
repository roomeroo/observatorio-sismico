import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

export interface Bar { label: string; value: number; missing?: boolean }

/** Dependency-free SVG bar chart (vertical for time series, horizontal for rankings). */
@Component({
  selector: 'app-bar-chart',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <figure class="chart" [attr.data-testid]="testId()">
      <figcaption>{{ title() }}</figcaption>
      @if (bars().length === 0 || max() === 0) {
        <p class="empty">Sin datos para los filtros actuales.</p>
      }
      @if (layout() === 'vertical') {
        <svg [attr.viewBox]="'0 0 ' + width + ' ' + height" role="img" [attr.aria-label]="title()" preserveAspectRatio="none">
          @for (b of bars(); track $index; let i = $index) {
            <rect
              [attr.x]="margin + i * step()"
              [attr.y]="height - bottom - barHeight(b.value)"
              [attr.width]="barWidth()"
              [attr.height]="barHeight(b.value)"
              [class.missing]="b.missing"
              class="bar">
              <title>{{ b.label }}: {{ b.value }}</title>
            </rect>
          }
          <line [attr.x1]="margin" [attr.x2]="width - margin" [attr.y1]="height - bottom" [attr.y2]="height - bottom" class="axis" />
          <text [attr.x]="margin" [attr.y]="height - 4" class="tick">{{ firstLabel() }}</text>
          <text [attr.x]="width - margin" [attr.y]="height - 4" class="tick" text-anchor="end">{{ lastLabel() }}</text>
          <text [attr.x]="margin" y="12" class="tick">máx. {{ max() }}</text>
        </svg>
      } @else {
        <ol class="hbars">
          @for (b of bars(); track $index) {
            <li [class.missing]="b.missing">
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
      figcaption { font-weight: 600; margin-bottom: 0.25rem; }
      svg { width: 100%; height: 150px; display: block; }
      .bar { fill: #2563eb; }
      .bar.missing { fill: #94a3b8; }
      .axis { stroke: #64748b; stroke-width: 1; }
      .tick { font-size: 10px; fill: #475569; }
      .empty { color: #64748b; font-size: 0.85rem; margin: 0.25rem 0; }
      .hbars { list-style: none; margin: 0; padding: 0; display: grid; gap: 0.2rem; }
      .hbars li { display: grid; grid-template-columns: 9rem 1fr 3rem; gap: 0.4rem; align-items: center; font-size: 0.85rem; }
      .name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
      .track { background: #e2e8f0; height: 0.7rem; border-radius: 3px; overflow: hidden; }
      .fill { display: block; height: 100%; background: #2563eb; }
      li.missing .fill { background: #94a3b8; }
      .value { text-align: right; font-variant-numeric: tabular-nums; }
    `,
  ],
})
export class BarChartComponent {
  readonly title = input.required<string>();
  readonly bars = input.required<Bar[]>();
  readonly layout = input<'vertical' | 'horizontal'>('vertical');
  readonly testId = input<string>('chart');

  readonly width = 600;
  readonly height = 150;
  readonly margin = 8;
  readonly bottom = 18;

  readonly max = computed(() => Math.max(0, ...this.bars().map((b) => b.value)));
  readonly step = computed(() => (this.width - 2 * this.margin) / Math.max(1, this.bars().length));
  readonly barWidth = computed(() => Math.max(1, this.step() * 0.8));
  readonly firstLabel = computed(() => this.bars()[0]?.label ?? '');
  readonly lastLabel = computed(() => this.bars().at(-1)?.label ?? '');

  barHeight(value: number): number {
    const m = this.max();
    return m === 0 ? 0 : (value / m) * (this.height - this.bottom - 16);
  }
  pct(value: number): number {
    const m = this.max();
    return m === 0 ? 0 : (value / m) * 100;
  }
}

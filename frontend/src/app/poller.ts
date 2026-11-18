/**
 * Serial poller: the next run is scheduled only after the previous one settles,
 * so requests never overlap. A failing task does not stop polling, which gives
 * automatic recovery on the next tick once the API is back.
 */
export interface PollerTimers {
  setTimeout(fn: () => void, ms: number): unknown;
  clearTimeout(handle: unknown): void;
}

const browserTimers: PollerTimers = {
  setTimeout: (fn, ms) => setTimeout(fn, ms),
  clearTimeout: (handle) => clearTimeout(handle as ReturnType<typeof setTimeout>),
};

export class Poller {
  private handle: unknown;
  private inflight = false;
  private pending = false;
  private stopped = true;

  constructor(
    private readonly task: () => Promise<void>,
    private readonly intervalMs: number,
    private readonly timers: PollerTimers = browserTimers,
  ) {}

  get running(): boolean {
    return !this.stopped;
  }

  start(): void {
    if (!this.stopped) return;
    this.stopped = false;
    void this.tick();
  }

  stop(): void {
    this.stopped = true;
    this.pending = false;
    if (this.handle !== undefined) this.timers.clearTimeout(this.handle);
    this.handle = undefined;
  }

  /** Run now (e.g. after a filter change). Never overlaps a run in progress. */
  refreshNow(): void {
    if (this.stopped) return;
    if (this.handle !== undefined) {
      this.timers.clearTimeout(this.handle);
      this.handle = undefined;
    }
    void this.tick();
  }

  private async tick(): Promise<void> {
    if (this.inflight) {
      this.pending = true; // run once more right after the current one finishes
      return;
    }
    this.inflight = true;
    try {
      await this.task();
    } catch {
      // the task records its own failure; polling continues regardless
    } finally {
      this.inflight = false;
    }
    if (this.stopped) return;
    if (this.pending) {
      this.pending = false;
      return this.tick();
    }
    this.handle = this.timers.setTimeout(() => {
      this.handle = undefined;
      void this.tick();
    }, this.intervalMs);
  }
}

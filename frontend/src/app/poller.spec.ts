// Unit tests run with Node's built-in runner: `npm test`
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Poller, type PollerTimers } from './poller.ts';
import { buildQuery, DEFAULT_FILTERS, resolveInterval } from './query.ts';

/** Deterministic fake timers: nothing fires until `advance` is called. */
function fakeTimers() {
  let now = 0;
  let nextId = 1;
  const scheduled = new Map<number, { at: number; fn: () => void }>();
  const timers: PollerTimers = {
    setTimeout(fn, ms) {
      const id = nextId++;
      scheduled.set(id, { at: now + ms, fn });
      return id;
    },
    clearTimeout(handle) {
      scheduled.delete(handle as number);
    },
  };
  return {
    timers,
    pending: () => scheduled.size,
    async advance(ms: number) {
      now += ms;
      for (const [id, t] of [...scheduled]) {
        if (t.at <= now) {
          scheduled.delete(id);
          t.fn();
        }
      }
      await new Promise((r) => setImmediate(r));
    },
  };
}

const flush = () => new Promise((r) => setImmediate(r));

test('polls immediately and then every interval', async () => {
  const clock = fakeTimers();
  let runs = 0;
  const poller = new Poller(async () => void runs++, 60_000, clock.timers);
  poller.start();
  await flush();
  assert.equal(runs, 1);
  await clock.advance(59_999);
  assert.equal(runs, 1);
  await clock.advance(1);
  assert.equal(runs, 2);
  poller.stop();
  await clock.advance(120_000);
  assert.equal(runs, 2);
});

test('does not overlap: a slow request delays the next one', async () => {
  const clock = fakeTimers();
  let active = 0;
  let maxActive = 0;
  let runs = 0;
  let release!: () => void;
  const poller = new Poller(
    async () => {
      runs++;
      active++;
      maxActive = Math.max(maxActive, active);
      await new Promise<void>((r) => (release = r));
      active--;
    },
    60_000,
    clock.timers,
  );
  poller.start();
  await flush();
  assert.equal(clock.pending(), 0, 'no timer is scheduled while a request is in flight');
  await clock.advance(300_000);
  assert.equal(runs, 1);
  poller.refreshNow(); // a filter change during the slow request must not start a second one
  await flush();
  assert.equal(maxActive, 1);
  release();
  await flush();
  assert.equal(runs, 2, 'the queued refresh runs once, after the first finished');
  assert.equal(maxActive, 1);
  release();
  await flush();
  assert.equal(clock.pending(), 1);
  poller.stop();
});

test('recovers automatically after failures (tunnel closed and reopened)', async () => {
  const clock = fakeTimers();
  const outcomes: string[] = [];
  let apiUp = false;
  const poller = new Poller(
    async () => {
      if (!apiUp) {
        outcomes.push('error');
        throw new Error('network');
      }
      outcomes.push('ok');
    },
    60_000,
    clock.timers,
  );
  poller.start();
  await flush();
  await clock.advance(60_000);
  assert.deepEqual(outcomes, ['error', 'error']);
  apiUp = true; // tunnel reopened: no user action
  await clock.advance(60_000);
  assert.deepEqual(outcomes, ['error', 'error', 'ok']);
  await clock.advance(60_000);
  assert.deepEqual(outcomes, ['error', 'error', 'ok', 'ok']);
  poller.stop();
});

test('refreshNow replaces the pending timer and stop prevents further runs', async () => {
  const clock = fakeTimers();
  let runs = 0;
  const poller = new Poller(async () => void runs++, 60_000, clock.timers);
  poller.start();
  await flush();
  poller.refreshNow();
  await flush();
  assert.equal(runs, 2);
  assert.equal(clock.pending(), 1, 'exactly one timer pending');
  poller.stop();
  poller.refreshNow();
  await flush();
  assert.equal(runs, 2);
});

test('query builder maps filters to API parameters', () => {
  const now = new Date('2026-11-18T12:00:00Z');
  const interval = resolveInterval({ ...DEFAULT_FILTERS, range: '7d' }, now)!;
  assert.equal(interval.end, '2026-11-18T12:00:00.000Z');
  assert.equal(interval.start, '2026-11-11T12:00:00.000Z');
  const q = buildQuery({ ...DEFAULT_FILTERS, minMag: 5, country: 'JPN', subregion: 'Eastern Asia' }, interval, { limit: 10 });
  assert.equal(q.get('min_mag'), '5');
  assert.equal(q.get('country_id'), 'JPN');
  assert.equal(q.get('subregion'), 'Eastern Asia');
  assert.equal(q.get('limit'), '10');
  assert.equal(q.get('mode'), null);
  assert.equal(buildQuery({ ...DEFAULT_FILTERS, mode: 'replay' }, null).get('mode'), 'replay');
});

test('replay interval comes from the replay period, end exclusive', () => {
  const i = resolveInterval({ ...DEFAULT_FILTERS, mode: 'replay' }, new Date(), {
    from: '2025-03-28T06:20:52.715Z',
    to: '2025-03-28T11:58:59.857Z',
  })!;
  assert.equal(i.start, '2025-03-28T06:20:52.715Z');
  assert.equal(i.end, '2025-03-28T11:59:00.857Z');
  assert.equal(resolveInterval({ ...DEFAULT_FILTERS, mode: 'replay' }, new Date(), null), null);
});

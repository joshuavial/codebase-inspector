import assert from "node:assert/strict";
import { test } from "node:test";
import { BRANCH_POLL_MS, BranchPoll, RESCAN_DEBOUNCE_MS, watchIgnored, WorktreeWatch } from "./rescan";

test("git metadata and the model directory do not schedule a rescan", () => {
  assert.equal(watchIgnored(".git"), true);
  assert.equal(watchIgnored(".git/index"), true);
  assert.equal(watchIgnored(".cbi/model.db"), true);
  assert.equal(watchIgnored("src/.cbi/notes"), true);
  assert.equal(watchIgnored(null), true);
  assert.equal(watchIgnored(""), true);
  assert.equal(watchIgnored("src/main.ts"), false);
  assert.equal(watchIgnored("README.md"), false);
});

function watchHarness() {
  let onName: (name: string | null) => void = () => undefined;
  let pending: (() => void) | null = null;
  let closed = false;
  let fires = 0;
  let release: () => void = () => undefined;
  const watch = new WorktreeWatch({
    debounceMs: RESCAN_DEBOUNCE_MS,
    watch: (_dir, cb) => {
      onName = cb;
      return { close: () => { closed = true; } };
    },
    onFire: () => {
      fires += 1;
      return new Promise((resolve) => { release = resolve; });
    },
    setTimer: (fn) => {
      pending = fn;
      return 1 as unknown as ReturnType<typeof setTimeout>;
    },
    clearTimer: () => { pending = null; },
  });
  return {
    watch,
    fire: () => {
      const fn = pending;
      pending = null;
      fn?.();
    },
    release: () => release(),
    notify: (name: string | null) => onName(name),
    closed: () => closed,
    fires: () => fires,
  };
}

test("a burst of file changes scans once", () => {
  const harness = watchHarness();
  harness.watch.start("/repos/app");
  harness.notify("src/a.ts");
  harness.notify("src/b.ts");
  harness.notify(".cbi/model.db");
  assert.equal(harness.fires(), 0);
  harness.fire();
  assert.equal(harness.fires(), 1);
});

test("a change during a scan causes one more scan", async () => {
  const harness = watchHarness();
  harness.watch.start("/repos/app");
  harness.notify("README.md");
  harness.fire();
  assert.equal(harness.fires(), 1);
  harness.notify("src/a.ts");
  harness.fire();
  assert.equal(harness.fires(), 1);
  harness.release();
  await harness.watch.idle;
  assert.equal(harness.fires(), 2);
  harness.release();
  await harness.watch.idle;
});

test("rearm uses a caller delay when the reload needs longer to settle", () => {
  let delay = -1;
  const watch = new WorktreeWatch({
    rearmDelayMs: 0,
    watch: () => ({ close() {} }),
    onFire: () => undefined,
    setTimer: (_fn, ms) => {
      delay = ms;
      return 1 as unknown as ReturnType<typeof setTimeout>;
    },
    clearTimer: () => undefined,
  });
  watch.start("/repos/app");
  watch.rearm(1500);
  assert.equal(delay, 1500);
  watch.stop();
});

test("rearm opens a new watch and keeps a scan that is already running", async () => {
  let onName: (name: string | null) => void = () => undefined;
  const opened: string[] = [];
  let closes = 0;
  let pending: (() => void) | null = null;
  let release: () => void = () => undefined;
  let fires = 0;
  const watch = new WorktreeWatch({
    debounceMs: RESCAN_DEBOUNCE_MS,
    rearmDelayMs: 0,
    watch: (dir, cb) => {
      opened.push(dir);
      onName = cb;
      return { close: () => { closes += 1; } };
    },
    onFire: () => {
      fires += 1;
      return new Promise((resolve) => { release = resolve; });
    },
    setTimer: (fn) => {
      pending = fn;
      return 1 as unknown as ReturnType<typeof setTimeout>;
    },
    clearTimer: () => { pending = null; },
  });
  const tick = () => {
    const fn = pending;
    pending = null;
    fn?.();
  };
  watch.start("/repos/app");
  onName("README.md");
  tick();
  assert.equal(fires, 1);
  watch.rearm();
  tick();
  assert.equal(closes, 1);
  assert.deepEqual(opened, ["/repos/app", "/repos/app"]);
  onName("src/a.ts");
  release();
  await watch.idle;
  assert.equal(fires, 1);
  tick();
  assert.equal(fires, 2);
  release();
  await watch.idle;
  watch.stop();
  assert.equal(closes, 2);
});

test("a nameless change schedules a scan, and one during a scan does not chain", async () => {
  const harness = watchHarness();
  harness.watch.start("/repos/app");
  harness.notify(null);
  harness.fire();
  assert.equal(harness.fires(), 1);
  harness.notify(null);
  harness.release();
  await harness.watch.idle;
  assert.equal(harness.fires(), 1);
});

test("stopping cancels a pending scan and closes the watch", () => {
  const harness = watchHarness();
  harness.watch.start("/repos/app");
  harness.notify("src/a.ts");
  harness.watch.stop();
  harness.fire();
  assert.equal(harness.fires(), 0);
  assert.equal(harness.closed(), true);
});

function pollHarness(heads: string[]) {
  let pending: (() => void) | null = null;
  const moved: string[] = [];
  const poll = new BranchPoll({
    intervalMs: BRANCH_POLL_MS,
    head: async () => heads[0] ?? null,
    onMove: async (head) => { moved.push(head); },
    setTimer: (fn) => {
      pending = fn;
      return 1 as unknown as ReturnType<typeof setTimeout>;
    },
    clearTimer: () => { pending = null; },
  });
  return {
    poll,
    moved,
    tick: () => {
      const fn = pending;
      pending = null;
      fn?.();
    },
  };
}

test("a branch view rescans only when its head moves", async () => {
  const heads = ["aaa"];
  const harness = pollHarness(heads);
  harness.poll.start("aaa");
  harness.tick();
  await harness.poll.settled;
  assert.deepEqual(harness.moved, []);
  heads[0] = "bbb";
  harness.tick();
  await harness.poll.settled;
  assert.deepEqual(harness.moved, ["bbb"]);
  harness.tick();
  await harness.poll.settled;
  assert.deepEqual(harness.moved, ["bbb"]);
});

test("stopping the poll ignores a later tick", async () => {
  const heads = ["bbb"];
  const harness = pollHarness(heads);
  harness.poll.start("aaa");
  harness.poll.stop();
  harness.tick();
  await harness.poll.settled;
  assert.deepEqual(harness.moved, []);
});

test("the branch poll waits 30 seconds", () => {
  assert.equal(BRANCH_POLL_MS, 30_000);
  assert.equal(RESCAN_DEBOUNCE_MS >= 400, true);
});

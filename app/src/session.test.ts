import assert from "node:assert/strict";
import { test } from "node:test";
import { isModelChange, ProjectSession } from "./session";
import type { MapResult } from "./map-project";
import type { StatusJson } from "./types";

const status: StatusJson = { scanned_at: "t", nodes: {}, open_tasks: { "summarise-files": 1 } };
const ok: MapResult = { ok: true, status, viewer: "", commit: null };

test("model writes are the db, its journal and its wal", () => {
  assert.equal(isModelChange("model.db"), true);
  assert.equal(isModelChange("model.db-journal"), true);
  assert.equal(isModelChange("model.db-wal"), true);
  assert.equal(isModelChange("model.db-shm"), false);
  assert.equal(isModelChange("ignore"), false);
  assert.equal(isModelChange(null), false);
});

function harness() {
  let onName: (name: string | null) => void = () => undefined;
  let pending: (() => void) | null = null;
  let closed = false;
  let watched = "";
  const loaded: string[] = [];
  const indexes: string[] = [];
  const phases: string[] = [];
  let rebuilds = 0;
  let gate: (result: MapResult) => void = () => undefined;
  const session = new ProjectSession({
    debounceMs: 400,
    rebuild: () => {
      rebuilds += 1;
      return new Promise((resolve) => {
        gate = resolve;
      });
    },
    watch: (dir, cb) => {
      watched = dir;
      onName = cb;
      return { close: () => { closed = true; } };
    },
    loadViewer: async (index, hash) => {
      indexes.push(index);
      loaded.push(hash);
    },
    onStatus: () => undefined,
    onProgress: (phase) => phases.push(phase),
    setTimer: (fn) => {
      pending = fn;
      return 1 as unknown as ReturnType<typeof setTimeout>;
    },
    clearTimer: () => {
      pending = null;
    },
  });
  return {
    session,
    loaded,
    phases,
    fire: () => {
      const fn = pending;
      pending = null;
      fn?.();
    },
    release: (result: MapResult = ok) => gate(result),
    closed: () => closed,
    rebuilds: () => rebuilds,
    notify: (name: string | null) => onName(name),
    watched: () => watched,
    indexes,
  };
}

test("a model change reloads the viewer with the hash from before the rebuild", async () => {
  const h = harness();
  h.session.noteHash("#s=auth");
  h.session.startWatch("/repos/app", "/bin/cbi");
  h.notify("model.db");
  assert.equal(h.rebuilds(), 0);
  h.fire();
  h.release();
  await h.session.idle;
  assert.equal(h.rebuilds(), 1);
  assert.deepEqual(h.loaded, ["s=auth"]);
  assert.deepEqual(h.phases, ["build", "ready"]);
});

test("unrelated files do not rebuild", async () => {
  const h = harness();
  h.session.startWatch("/repos/app", "/bin/cbi");
  h.notify("ignore");
  h.notify(null);
  assert.equal(h.rebuilds(), 0);
  h.fire();
  assert.equal(h.rebuilds(), 0);
});

test("a change during a rebuild causes one more rebuild", async () => {
  const h = harness();
  h.session.noteHash("#s=1");
  h.session.startWatch("/repos/app", "/bin/cbi");
  h.notify("model.db-wal");
  h.fire();
  assert.equal(h.rebuilds(), 1);
  h.notify("model.db");
  h.fire();
  assert.equal(h.rebuilds(), 1);
  h.release();
  const first = h.session.idle;
  await first;
  assert.equal(h.rebuilds(), 2);
  h.release();
  await h.session.idle;
  assert.deepEqual(h.loaded, ["s=1", "s=1"]);
});

test("a ref model is watched in its own directory and reloaded from that viewer", async () => {
  const h = harness();
  const viewer = "/repos/app/.cbi/refs/abc/viewer/index.html";
  h.session.noteHash("#c=side");
  h.session.startWatch("/repos/app", "/bin/cbi", {
    modelDir: "/repos/app/.cbi/refs/abc",
    viewerIndex: viewer,
  });
  assert.equal(h.watched(), "/repos/app/.cbi/refs/abc");
  h.notify("model.db");
  h.fire();
  h.release();
  await h.session.idle;
  assert.deepEqual(h.indexes, [viewer]);
  assert.deepEqual(h.loaded, ["c=side"]);
});

test("stopping cancels a pending rebuild and closes the watch", async () => {
  const h = harness();
  h.session.startWatch("/repos/app", "/bin/cbi");
  h.notify("model.db");
  h.session.stop();
  h.fire();
  assert.equal(h.rebuilds(), 0);
  assert.equal(h.closed(), true);
});

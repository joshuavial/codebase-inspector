import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { after, test } from "node:test";
import { viewFromCache } from "./project-cache";
import { readRecents, RecentsStore } from "./recents";
import type { Recent } from "./types";

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "cbi-cache-"));
after(() => fs.rmSync(tmp, { recursive: true, force: true }));

function item(over: Partial<Recent> = {}): Recent {
  return {
    path: "/repos/app",
    displayName: "App",
    pinned: false,
    lastOpened: "2026-01-01T00:00:00.000Z",
    lastView: "#s=auth",
    ...over,
  };
}

test("the projects list renders from the cache without a status call", () => {
  const view = viewFromCache(item({
    cachedBranch: "main",
    cachedTaskState: "waiting",
    cachedTaskCount: 4,
    cachedMissing: false,
  }));
  assert.equal(view.branch, "main");
  assert.equal(view.taskState, "waiting");
  assert.equal(view.taskCount, 4);
  assert.equal(view.missing, false);
  assert.equal(view.refreshing, false);
});

test("a row that has never been cached is unknown, not missing", () => {
  const view = viewFromCache(item(), true);
  assert.equal(view.taskState, "unknown");
  assert.equal(view.branch, null);
  assert.equal(view.missing, false);
  assert.equal(view.refreshing, true);
});

test("a cached missing folder drops the branch and the tasks", () => {
  const view = viewFromCache(item({
    cachedBranch: "main",
    cachedTaskState: "complete",
    cachedTaskCount: 2,
    cachedMissing: true,
  }));
  assert.equal(view.missing, true);
  assert.equal(view.branch, null);
  assert.equal(view.taskState, "missing");
  assert.equal(view.taskCount, 0);
});

test("the snapshot survives reopen and a reread of the file", () => {
  const file = path.join(tmp, "recents.json");
  const store = new RecentsStore(file);
  store.open("/repos/app", "2026-01-01T00:00:00.000Z");
  store.setSnapshot("/repos/app", {
    cachedBranch: "main",
    cachedTaskState: "complete",
    cachedTaskCount: 0,
    cachedMissing: false,
  });
  store.open("/repos/app", "2026-02-01T00:00:00.000Z");
  const listed = readRecents(fs.readFileSync(file, "utf8"));
  assert.equal(listed[0]?.cachedBranch, "main");
  assert.equal(listed[0]?.cachedTaskState, "complete");
  assert.equal(listed[0]?.cachedTaskCount, 0);
  assert.equal(listed[0]?.lastOpened, "2026-02-01T00:00:00.000Z");
  assert.equal(viewFromCache(listed[0]).taskState, "complete");
});

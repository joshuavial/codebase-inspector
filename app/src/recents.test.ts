import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { after, test } from "node:test";
import { readRecents, RecentsStore } from "./recents";

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "cbi-recents-"));
after(() => fs.rmSync(tmp, { recursive: true, force: true }));

function store(): RecentsStore {
  return new RecentsStore(path.join(tmp, `recents-${Math.random().toString(16).slice(2)}.json`));
}

test("opening a project stores it and brings it to the front", () => {
  const recents = store();
  recents.open("/repos/older", "2026-01-01T00:00:00.000Z");
  recents.open("/repos/newer", "2026-02-01T00:00:00.000Z");
  const listed = recents.list();
  assert.deepEqual(listed.map((item) => item.path), ["/repos/newer", "/repos/older"]);
  assert.equal(listed[0].displayName, "newer");
  assert.equal(listed[0].pinned, false);
  assert.equal(listed[0].lastView, "");
});

test("opening again keeps the name, pin and last view", () => {
  const recents = store();
  recents.open("/repos/app", "2026-01-01T00:00:00.000Z");
  recents.rename("/repos/app", "App");
  recents.setPinned("/repos/app", true);
  recents.setLastView("/repos/app", "#s=auth");
  recents.open("/repos/app", "2026-03-01T00:00:00.000Z");
  const item = recents.get("/repos/app");
  assert.ok(item);
  assert.equal(item.displayName, "App");
  assert.equal(item.pinned, true);
  assert.equal(item.lastView, "#s=auth");
  assert.equal(item.lastOpened, "2026-03-01T00:00:00.000Z");
});

test("pinned projects stay above newer unpinned ones", () => {
  const recents = store();
  recents.open("/repos/pinned", "2026-01-01T00:00:00.000Z");
  recents.setPinned("/repos/pinned", true);
  recents.open("/repos/fresh", "2026-06-01T00:00:00.000Z");
  assert.deepEqual(recents.list().map((item) => item.path), ["/repos/pinned", "/repos/fresh"]);
  recents.setPinned("/repos/pinned", false);
  assert.deepEqual(recents.list().map((item) => item.path), ["/repos/fresh", "/repos/pinned"]);
});

test("rename changes only the display name", () => {
  const recents = store();
  recents.open("/repos/app", "2026-01-01T00:00:00.000Z");
  recents.rename("/repos/app", "  Sample Desktop  ");
  const item = recents.get("/repos/app");
  assert.equal(item?.displayName, "Sample Desktop");
  assert.equal(item?.path, "/repos/app");
});

test("an empty display name is refused", () => {
  const recents = store();
  recents.open("/repos/app", "2026-01-01T00:00:00.000Z");
  assert.throws(() => recents.rename("/repos/app", "   "), /empty/);
  assert.equal(recents.get("/repos/app")?.displayName, "app");
});

test("remove drops the project", () => {
  const recents = store();
  recents.open("/repos/app", "2026-01-01T00:00:00.000Z");
  recents.remove("/repos/app");
  assert.deepEqual(recents.list(), []);
  recents.remove("/repos/app");
  assert.deepEqual(recents.list(), []);
});

test("relocate points a missing entry at the new path", () => {
  const recents = store();
  recents.open("/repos/old", "2026-01-01T00:00:00.000Z");
  recents.rename("/repos/old", "Old name");
  recents.setPinned("/repos/old", true);
  recents.relocate("/repos/old", "/repos/new");
  const item = recents.get("/repos/new");
  assert.ok(item);
  assert.equal(item.displayName, "Old name");
  assert.equal(item.pinned, true);
  assert.equal(recents.get("/repos/old"), null);
});

test("relocating onto a project already listed drops the missing entry", () => {
  const recents = store();
  recents.open("/repos/kept", "2026-02-01T00:00:00.000Z");
  recents.rename("/repos/kept", "Kept");
  recents.open("/repos/gone", "2026-01-01T00:00:00.000Z");
  recents.relocate("/repos/gone", "/repos/kept");
  assert.deepEqual(recents.list().map((item) => item.path), ["/repos/kept"]);
  assert.equal(recents.get("/repos/kept")?.displayName, "Kept");
});

test("last view is stored without moving the project", () => {
  const recents = store();
  recents.open("/repos/a", "2026-02-01T00:00:00.000Z");
  recents.open("/repos/b", "2026-01-01T00:00:00.000Z");
  recents.setLastView("/repos/b", "#c=leaf");
  assert.deepEqual(recents.list().map((item) => item.path), ["/repos/a", "/repos/b"]);
  assert.equal(recents.get("/repos/b")?.lastView, "#c=leaf");
  assert.equal(recents.get("/repos/a")?.lastOpened, "2026-02-01T00:00:00.000Z");
});

test("a damaged file is an empty list", () => {
  const file = path.join(tmp, "damaged.json");
  fs.writeFileSync(file, "{");
  assert.deepEqual(new RecentsStore(file).list(), []);
  assert.deepEqual(readRecents("null"), []);
  assert.deepEqual(readRecents(JSON.stringify({ projects: [{ path: "/ok" }, { nope: true }, "x"] })).map((item) => item.path), ["/ok"]);
});

test("the file on disk is the saved list", () => {
  const file = path.join(tmp, "roundtrip.json");
  const recents = new RecentsStore(file);
  recents.open("/repos/app", "2026-01-01T00:00:00.000Z");
  const parsed = JSON.parse(fs.readFileSync(file, "utf8")) as { projects: { path: string }[] };
  assert.equal(parsed.projects[0].path, "/repos/app");
  assert.equal(fs.existsSync(`${file}.tmp`), false);
});

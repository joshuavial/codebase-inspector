import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { after, test } from "node:test";
import { CAPTURE_VIEW_JS, emptyView, parseCaptured, restoreScript, sectionTitle, ViewStore } from "./view-state";

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "cbi-views-"));
after(() => fs.rmSync(tmp, { recursive: true, force: true }));

function store(): ViewStore {
  return new ViewStore(path.join(tmp, `views-${Math.random().toString(16).slice(2)}.json`));
}

test("section titles drop the count so a rescan still matches", () => {
  assert.equal(sectionTitle("Files (3)"), "Files");
  assert.equal(sectionTitle("Integration points (12)"), "Integration points");
  assert.equal(sectionTitle("Tests (1)"), "Tests");
  assert.equal(sectionTitle("Environment"), "Environment");
});

test("a captured drawer round-trips, and junk is ignored", () => {
  const parsed = parseCaptured(JSON.stringify({
    hash: "#c=auth&s=fn",
    drawerHidden: false,
    sections: [
      { title: "Files (4)", open: true },
      { title: "Tests (1)", open: false },
      { title: "", open: true },
      { open: true },
    ],
  }));
  assert.deepEqual(parsed, {
    hash: "#c=auth&s=fn",
    drawerHidden: false,
    sections: [
      { title: "Files", open: true },
      { title: "Tests", open: false },
    ],
  });
  assert.equal(parseCaptured("nope"), null);
  assert.equal(parseCaptured("{}"), null);
});

test("the restore script carries the saved sections and the hidden drawer", () => {
  const script = restoreScript({
    hash: "#c=auth",
    drawerHidden: true,
    sections: [{ title: "Files (2)", open: false }],
  });
  assert.match(script, /"title":"Files"/);
  assert.match(script, /"open":false/);
  assert.match(script, /"drawerHidden":true/);
  assert.match(CAPTURE_VIEW_JS, /#drawer/);
  assert.match(CAPTURE_VIEW_JS, /no-drawer/);
});

test("each worktree and branch keeps its own hash and drawer", () => {
  const views = store();
  const main = "worktree:/repos/app";
  const side = "branch:side";
  views.set("/repos/app", main, { hash: "#c=main", drawerHidden: false, sections: [{ title: "Files", open: true }] });
  views.set("/repos/app", side, { hash: "#c=side", drawerHidden: true, sections: [{ title: "Tests", open: false }] });
  views.setLastKey("/repos/app", side);
  assert.equal(views.lastKey("/repos/app"), side);
  assert.deepEqual(views.get("/repos/app", main).sections, [{ title: "Files", open: true }]);
  assert.equal(views.get("/repos/app", side).drawerHidden, true);
  assert.deepEqual(views.get("/repos/app", "branch:missing"), emptyView());
  assert.equal(views.lastKey("/repos/other"), null);
});

test("a hash update does not clear the drawer sections", () => {
  const views = store();
  views.set("/repos/app", "worktree:/repos/app", {
    hash: "#c=1",
    drawerHidden: false,
    sections: [{ title: "Files (9)", open: true }],
  });
  views.setLastKey("/repos/app", "worktree:/repos/app");
  views.updateHash("/repos/app", "worktree:/repos/app", "#c=2");
  const saved = views.get("/repos/app", "worktree:/repos/app");
  assert.equal(saved.hash, "#c=2");
  assert.deepEqual(saved.sections, [{ title: "Files", open: true }]);
  assert.equal(views.lastKey("/repos/app"), "worktree:/repos/app");
});

test("a comparison keeps its own view beside the worktree it was opened from", () => {
  const views = store();
  const project = "/repos/app";
  const worktree = "worktree:/repos/app";
  const compare = `compare:${"a".repeat(40)}..${"b".repeat(40)}`;
  views.set(project, worktree, { hash: "#c=main", drawerHidden: false, sections: [{ title: "Files", open: true }] });
  views.set(project, compare, { hash: "#side=base", drawerHidden: true, sections: [] });
  views.setLastKey(project, worktree);
  views.updateHash(project, compare, "#c=changed");
  assert.equal(views.get(project, worktree).hash, "#c=main");
  assert.equal(views.get(project, compare).hash, "#c=changed");
  assert.equal(views.get(project, compare).drawerHidden, true);
  assert.equal(views.lastKey(project), worktree);
});

test("a corrupt file is treated as empty and the next save replaces it", () => {
  const file = path.join(tmp, "corrupt.json");
  fs.writeFileSync(file, "{");
  const views = new ViewStore(file);
  assert.equal(views.lastKey("/repos/app"), null);
  views.setLastKey("/repos/app", "branch:side");
  assert.equal(views.lastKey("/repos/app"), "branch:side");
  assert.equal(fs.readFileSync(file, "utf8").includes("branch:side"), true);
});

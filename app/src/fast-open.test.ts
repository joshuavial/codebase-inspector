import assert from "node:assert/strict";
import { test } from "node:test";
import {
  canonicalValue,
  countChangedFiles,
  fileStateQuery,
  instantOpen,
  parseFileStates,
  parseStatusTable,
  isCompareScript,
  payloadFingerprint,
  scriptPayload,
  sqliteArgs,
  statusQuery,
  commitFromViewer,
  verifyCommitArgv,
  viewerForTarget,
} from "./fast-open";

const exists = (files: string[]) => (file: string) => files.includes(file);

test("a mapped main checkout opens its viewer without a scan", () => {
  const opened = instantOpen({
    project: "/repos/app",
    picked: "/repos/app",
    lastKey: null,
    branchCommit: null,
    exists: exists(["/repos/app/.cbi/viewer/index.html"]),
  });
  assert.equal(opened?.index, "/repos/app/.cbi/viewer/index.html");
  assert.equal(opened?.kind, "worktree");
  assert.equal(opened?.ref, null);
});

test("a saved worktree opens that worktree's viewer", () => {
  const opened = instantOpen({
    project: "/repos/app",
    picked: "/repos/app",
    lastKey: "worktree:/repos/app-lane",
    branchCommit: null,
    exists: exists(["/repos/app-lane/.cbi/viewer/index.html", "/repos/app/.cbi/viewer/index.html"]),
  });
  assert.equal(opened?.cwd, "/repos/app-lane");
  assert.equal(opened?.index, "/repos/app-lane/.cbi/viewer/index.html");
});

test("a picked lane does not fall back to the main viewer", () => {
  const opened = instantOpen({
    project: "/repos/app",
    picked: "/repos/app-lane",
    lastKey: "worktree:/repos/app",
    branchCommit: null,
    exists: exists(["/repos/app/.cbi/viewer/index.html"]),
  });
  assert.equal(opened, null);
});

test("a saved branch opens the ref viewer for that commit", () => {
  const sha = "a".repeat(40);
  const opened = instantOpen({
    project: "/repos/app",
    picked: "/repos/app",
    lastKey: "branch:side",
    branchCommit: sha,
    exists: exists([`/repos/app/.cbi/refs/${sha}/viewer/index.html`]),
  });
  assert.equal(opened?.kind, "branch");
  assert.equal(opened?.ref, "side");
  assert.equal(opened?.commit, sha);
});

test("a branch without a commit falls back to the worktree viewer", () => {
  const opened = instantOpen({
    project: "/repos/app",
    picked: "/repos/app",
    lastKey: "branch:side",
    branchCommit: null,
    exists: exists(["/repos/app/.cbi/viewer/index.html"]),
  });
  assert.equal(opened?.kind, "worktree");
  assert.equal(opened?.index, "/repos/app/.cbi/viewer/index.html");
});

test("an unmapped project has no instant viewer", () => {
  assert.equal(instantOpen({
    project: "/repos/app",
    picked: "/repos/app",
    lastKey: null,
    branchCommit: null,
    exists: exists([]),
  }), null);
});

test("verify commit is a fixed read-only argv", () => {
  assert.deepEqual(verifyCommitArgv("side"), ["rev-parse", "--verify", "--end-of-options", "side"]);
  assert.equal(verifyCommitArgv("-side"), null);
  assert.equal(verifyCommitArgv("side:lock"), null);
});

test("a ref viewer path yields its commit", () => {
  const sha = "c".repeat(40);
  assert.equal(commitFromViewer(`/repos/app/.cbi/refs/${sha}/viewer/index.html`), sha);
  assert.equal(commitFromViewer("/repos/app/.cbi/viewer/index.html"), null);
});

test("a ref viewer is used only when the head is a sha", () => {
  const sha = "b".repeat(40);
  const found = viewerForTarget({
    cwd: "/repos/app",
    project: "/repos/app",
    ref: "side",
    head: sha,
    exists: (file) => file.endsWith(`${sha}/viewer/index.html`),
  });
  assert.equal(found, `/repos/app/.cbi/refs/${sha}/viewer/index.html`);
  assert.equal(viewerForTarget({
    cwd: "/repos/app",
    project: "/repos/app",
    ref: "side",
    head: "",
    exists: () => true,
  }), null);
});

test("status and file rows parse without a cbi process", () => {
  const status = parseStatusTable("scanned_at|2026-10-08T10:00:00+1300\ntask|summarise-files|2\ntask|confirm-structure|1\n");
  assert.equal(status.scanned_at, "2026-10-08T10:00:00+1300");
  assert.deepEqual(status.open_tasks, { "summarise-files": 2, "confirm-structure": 1 });
  assert.equal(parseStatusTable("scanned_at|\n").scanned_at, null);
  const states = parseFileStates("src/a.ts\x1fabc\nsrc/b.ts\x1fdef\n");
  assert.equal(states.get("src/a.ts"), "abc");
  assert.equal(countChangedFiles(states, parseFileStates("src/a.ts\x1fzzz\nsrc/c.ts\x1fdef\n")), 3);
  assert.equal(countChangedFiles(states, states), 0);
  assert.ok(statusQuery().includes("scanned_at"));
  assert.ok(fileStateQuery().includes("char(31)"));
  assert.deepEqual(sqliteArgs("/repos/app/.cbi/model.db", "SELECT 1"), [
    "-batch", "-noheader", "-separator", "|", "file:/repos/app/.cbi/model.db?immutable=1", "SELECT 1",
  ]);
  assert.ok(sqliteArgs("/repos/my app/.cbi/model.db", "SELECT 1")[4]?.includes("my%20app"));
});

test("a rebuild that only reorders a list is the same map", () => {
  const left = 'cbiLoad("concepts", {"env":[{"name":"NODE_ENV","symbols":["b","a"]}]});\n';
  const right = 'cbiLoad("concepts", {"env":[{"name":"NODE_ENV","symbols":["a","b"]}]});\n';
  assert.equal(payloadFingerprint([left]), payloadFingerprint([right]));
  const changed = 'cbiLoad("concepts", {"env":[{"name":"NODE_ENV","symbols":["a","b","c"]}]});\n';
  assert.notEqual(payloadFingerprint([left]), payloadFingerprint([changed]));
  assert.equal(scriptPayload("nope"), null);
  assert.equal(isCompareScript('cbiLoad("diff", null);\n'), false);
  assert.equal(isCompareScript('cbiLoad("diff", {"changes":[],"base":"a","head":"b"});\n'), true);
  assert.deepEqual(canonicalValue({ b: 1, a: ["z", "m"] }), { a: ["m", "z"], b: 1 });
});

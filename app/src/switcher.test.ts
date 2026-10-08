import assert from "node:assert/strict";
import { test } from "node:test";
import {
  branchHead,
  branchOf,
  buildEntries,
  formatScanned,
  initialTarget,
  keyOf,
  labelOf,
  parseInventory,
  readOnlyTarget,
  refInstruction,
  refOf,
  targetFromKey,
  usableRef,
  worktreeForFolder,
  type Inventory,
} from "./switcher";

const inventory: Inventory = {
  worktrees: [
    {
      path: "/repos/app",
      branch: "main",
      head: "a".repeat(40),
      lane: "main",
      hasModel: true,
      modelComplete: false,
      current: true,
    },
    {
      path: "/repos/app/.worktrees/fixture-lane",
      branch: "lane",
      head: "b".repeat(40),
      lane: "fixture-lane",
      hasModel: true,
      modelComplete: true,
      current: false,
    },
  ],
  branches: [
    { name: "main", head: "a".repeat(40), lane: "main", hasRefModel: false, current: true },
    { name: "lane", head: "b".repeat(40), lane: "fixture-lane", hasRefModel: true, current: false },
    { name: "side", head: "c".repeat(40), lane: "side", hasRefModel: false, current: false },
    { name: "-sneaky", head: "d".repeat(40), lane: "-sneaky", hasRefModel: false, current: false },
  ],
};

const raw = JSON.stringify({
  worktrees: [
    {
      path: "/repos/app",
      branch: "main",
      head: "a".repeat(40),
      lane: "main",
      has_model: true,
      model_complete: false,
      current: true,
    },
    { path: "", branch: "skip", head: "abc", lane: "skip", has_model: false, model_complete: false, current: false },
    { path: "/repos/app/.worktrees/detached", branch: null, head: "e".repeat(40), lane: null, has_model: false, model_complete: false, current: false },
  ],
  branches: [
    { name: "main", head: "a".repeat(40), lane: "main", has_ref_model: false, current: true },
    { name: "", head: "abc", lane: "", has_ref_model: false, current: false },
  ],
});

test("worktrees json keeps complete rows and drops blank ones", () => {
  const parsed = parseInventory(raw);
  assert.ok(parsed);
  assert.deepEqual(parsed.worktrees.map((worktree) => worktree.path), ["/repos/app", "/repos/app/.worktrees/detached"]);
  assert.equal(parsed.worktrees[0].hasModel, true);
  assert.equal(parsed.worktrees[0].modelComplete, false);
  assert.equal(parsed.worktrees[1].branch, null);
  assert.equal(parsed.worktrees[1].lane, null);
  assert.deepEqual(parsed.branches.map((branch) => branch.name), ["main"]);
  assert.equal(parseInventory("nope"), null);
  assert.equal(parseInventory("{}"), null);
});

test("the switcher lists worktrees with lane names and model state, and hides remotes until fetched", () => {
  const entries = buildEntries(inventory, "worktree:/repos/app", null);
  assert.deepEqual(entries.map((entry) => [entry.group, entry.label, entry.detail, entry.selected]), [
    ["worktree", "main", "tasks waiting", true],
    ["worktree", "fixture-lane", "lane · map complete", false],
    ["branch", "main", "checked out", false],
    ["branch", "lane", "checked out", false],
    ["branch", "side", "not scanned", false],
  ]);
  assert.equal(entries.some((entry) => entry.group === "remote"), false);
  assert.equal(entries.some((entry) => entry.label === "-sneaky"), false);
});

test("a branch with no worktree is a read-only ref, and a checked-out branch opens the worktree", () => {
  const entries = buildEntries(inventory, null, null);
  const side = entries.find((entry) => entry.label === "side");
  const lane = entries.find((entry) => entry.key === "branch:lane");
  assert.ok(side && lane);
  assert.deepEqual(side.target, { kind: "branch", name: "side", head: "c".repeat(40) });
  assert.equal(readOnlyTarget(side.target), true);
  assert.equal(refOf(side.target), "side");
  assert.equal(lane.target.kind, "worktree");
  if (lane.target.kind === "worktree") assert.equal(lane.target.path, "/repos/app/.worktrees/fixture-lane");
  assert.equal(readOnlyTarget(lane.target), false);
  assert.equal(refOf(lane.target), null);
});

test("remote branches are listed only from the fetch result, without origin/HEAD", () => {
  const entries = buildEntries(inventory, "remote:origin/feature", [
    { name: "origin/HEAD", head: "a".repeat(40) },
    { name: "origin/feature", head: "f".repeat(40) },
  ]);
  const remotes = entries.filter((entry) => entry.group === "remote");
  assert.deepEqual(remotes.map((entry) => entry.label), ["origin/feature"]);
  assert.equal(remotes[0].selected, true);
  assert.equal(remotes[0].detail, "f".repeat(12));
  assert.equal(readOnlyTarget(remotes[0].target), true);
});

test("opening a linked worktree selects it, and opening main restores the last branch", () => {
  const lane = initialTarget({
    inventory,
    main: "/repos/app",
    picked: "/repos/app/.worktrees/fixture-lane/src",
    branch: "main",
    lastKey: "branch:side",
  });
  assert.equal(lane.kind, "worktree");
  if (lane.kind === "worktree") assert.equal(lane.lane, "fixture-lane");

  const restored = initialTarget({
    inventory,
    main: "/repos/app",
    picked: "/repos/app",
    branch: "main",
    lastKey: "branch:side",
  });
  assert.deepEqual(restored, { kind: "branch", name: "side", head: "c".repeat(40) });

  const fresh = initialTarget({ inventory: null, main: "/repos/app", picked: "/repos/app", branch: "main", lastKey: null });
  assert.equal(fresh.kind, "worktree");
  assert.equal(branchOf(fresh), "main");
  assert.equal(labelOf(lane), "fixture-lane");
});

test("a saved worktree that is gone falls through to main, and a saved remote can be scanned", () => {
  assert.equal(targetFromKey("worktree:/missing", inventory), null);
  const remote = targetFromKey("remote:origin/main", inventory);
  assert.deepEqual(remote, { kind: "remote", name: "origin/main", head: "" });
  assert.equal(keyOf(remote!), "remote:origin/main");
  const main = initialTarget({
    inventory,
    main: "/repos/app",
    picked: "/repos/app",
    branch: "main",
    lastKey: "worktree:/missing",
  });
  assert.equal(main.kind, "worktree");
  if (main.kind === "worktree") assert.equal(main.path, "/repos/app");
});

test("refs that could change the argv are refused", () => {
  assert.equal(usableRef("origin/feature"), true);
  assert.equal(usableRef("feature/name"), true);
  assert.equal(usableRef("-rf"), false);
  assert.equal(usableRef("a..b"), false);
  assert.equal(usableRef("a b"), false);
  assert.equal(usableRef("HEAD@{1}"), false);
  assert.equal(targetFromKey("branch:-sneaky", inventory), null);
});

test("the folder match prefers the nested worktree and ignores a sibling prefix", () => {
  assert.equal(worktreeForFolder(inventory, "/repos/app-other")?.path, undefined);
  assert.equal(worktreeForFolder(inventory, "/repos/app/.worktrees/fixture-lane/file.ts")?.branch, "lane");
  assert.equal(branchHead(inventory, "side"), "c".repeat(40));
  assert.equal(branchHead(inventory, "missing"), null);
});

test("a comparison is its own view and is not restored as the last version", () => {
  const base = "a".repeat(40);
  const head = "b".repeat(40);
  const target = { kind: "compare" as const, base, head, label: "main..side" };
  assert.equal(keyOf(target), `compare:${base}..${head}`);
  assert.equal(labelOf(target), "main..side");
  assert.equal(branchOf(target), "");
  assert.equal(refOf(target), null);
  assert.equal(readOnlyTarget(target), true);
  assert.equal(targetFromKey(keyOf(target), inventory), null);
  const restored = initialTarget({
    inventory,
    main: "/repos/app",
    picked: "/repos/app",
    branch: "main",
    lastKey: keyOf(target),
  });
  assert.equal(restored.kind, "worktree");
  if (restored.kind === "worktree") assert.equal(restored.path, "/repos/app");
});

test("the header shows the scan time and waiting tasks", () => {
  assert.equal(formatScanned("2026-10-07T09:41:08+1300", false), "scanned 2026-10-07 09:41");
  assert.equal(formatScanned("2026-10-07T09:41:08+1300", true), "scanned 2026-10-07 09:41 · tasks waiting");
  assert.equal(formatScanned(null, true), "tasks waiting");
  assert.equal(formatScanned(null, false), "");
  assert.equal(refInstruction("/repos/app", "side"), "run `cbi tasks --ref side` in /repos/app and complete the tasks");
});

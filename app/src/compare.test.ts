import assert from "node:assert/strict";
import { test } from "node:test";
import {
  allowedGhArgs,
  isCommitSha,
  parsePrOids,
  planCompare,
  prViewArgs,
  readCompareForm,
  safeRef,
} from "./compare";
import type { Inventory } from "./switcher";

const base = "a".repeat(40);
const head = "b".repeat(40);

const inventory: Inventory = {
  worktrees: [
    {
      path: "/repos/app",
      branch: "main",
      head: base,
      lane: "main",
      hasModel: true,
      modelComplete: false,
      current: true,
    },
    {
      path: "/repos/app/.worktrees/fixture-lane",
      branch: "lane",
      head: head,
      lane: "fixture-lane",
      hasModel: true,
      modelComplete: true,
      current: false,
    },
  ],
  branches: [
    { name: "main", head: base, lane: "main", hasRefModel: false, current: true },
    { name: "side", head: "c".repeat(40), lane: "side", hasRefModel: false, current: false },
    { name: "-sneaky", head: "d".repeat(40), lane: "-sneaky", hasRefModel: false, current: false },
  ],
};

test("a pull request is read with gh and only those two commit fields", () => {
  assert.deepEqual(prViewArgs("2345"), ["pr", "view", "2345", "--json", "baseRefOid,headRefOid"]);
  assert.equal(prViewArgs("0"), null);
  assert.equal(prViewArgs("01"), null);
  assert.equal(prViewArgs("12;rm"), null);
  assert.equal(allowedGhArgs(["pr", "view", "2345", "--json", "baseRefOid,headRefOid"]), true);
  assert.equal(allowedGhArgs(["pr", "comment", "2345", "--body", "hi"]), false);
  assert.equal(allowedGhArgs(["pr", "view", "2345", "--json", "url"]), false);
  assert.equal(allowedGhArgs(["repo", "clone", "example"]), false);
});

test("gh json needs both commit oids and does not invent a side", () => {
  assert.deepEqual(parsePrOids(JSON.stringify({ baseRefOid: base, headRefOid: head, url: "https://example" })), {
    ok: true,
    base,
    head,
  });
  assert.equal(parsePrOids("nope").ok, false);
  const missing = parsePrOids(JSON.stringify({ baseRefOid: base }));
  assert.equal(missing.ok, false);
  if (missing.ok) return;
  assert.match(missing.error, /baseRefOid and headRefOid/);
  const named = parsePrOids(JSON.stringify({ baseRefOid: "main", headRefOid: head }));
  assert.equal(named.ok, false);
  if (named.ok) return;
  assert.match(named.error, /baseRefOid and headRefOid/);
  assert.equal(isCommitSha(base), true);
  assert.equal(isCommitSha("main"), false);
  assert.equal(isCommitSha(base.toUpperCase()), false);
});

test("the picker takes two sides, or a pull request number instead", () => {
  const refs = planCompare({
    base: { kind: "worktree", value: "/repos/app" },
    head: { kind: "branch", value: "side" },
    pr: "",
  }, inventory);
  assert.deepEqual(refs, {
    ok: true,
    mode: "refs",
    base: { ref: base, label: "main" },
    head: { ref: "c".repeat(40), label: "side" },
  });

  const lane = planCompare({
    base: { kind: "worktree", value: "/repos/app/.worktrees/fixture-lane" },
    head: { kind: "commit", value: "main" },
    pr: "  ",
  }, inventory);
  assert.equal(lane.ok, true);
  if (!lane.ok || lane.mode !== "refs") return;
  assert.equal(lane.base.label, "fixture-lane");
  assert.equal(lane.base.ref, head);
  assert.deepEqual(lane.head, { ref: "main", label: "main" });

  const pr = planCompare({
    base: null,
    head: null,
    pr: "2345",
  }, null);
  assert.deepEqual(pr, { ok: true, mode: "pr", number: "2345" });
});

test("a bad side or a bad pull request is refused", () => {
  assert.deepEqual(planCompare({ base: null, head: { kind: "branch", value: "side" }, pr: "" }, inventory), {
    ok: false,
    error: "Choose two sides.",
  });
  const badPr = planCompare({ base: { kind: "branch", value: "side" }, head: { kind: "branch", value: "main" }, pr: "12;rm" }, inventory);
  assert.equal(badPr.ok, false);
  if (badPr.ok) return;
  assert.match(badPr.error, /pull request number/);

  const missing = planCompare({ base: { kind: "worktree", value: "/nope" }, head: { kind: "branch", value: "side" }, pr: "" }, inventory);
  assert.equal(missing.ok, false);
  if (missing.ok) return;
  assert.match(missing.error, /unknown worktree/);

  const sneaky = planCompare({ base: { kind: "branch", value: "-sneaky" }, head: { kind: "branch", value: "side" }, pr: "" }, inventory);
  assert.equal(sneaky.ok, false);
  if (sneaky.ok) return;
  assert.match(sneaky.error, /unknown ref/);

  const injected = planCompare({ base: { kind: "commit", value: "main;rm" }, head: { kind: "commit", value: "HEAD" }, pr: "" }, inventory);
  assert.equal(injected.ok, false);
  if (injected.ok) return;
  assert.match(injected.error, /unknown ref main;rm/);

  const range = planCompare({ base: { kind: "commit", value: "main..side" }, head: { kind: "commit", value: "HEAD" }, pr: "" }, inventory);
  assert.equal(range.ok, false);
  assert.equal(safeRef("main..side"), false);
  assert.equal(safeRef("refs/heads/main"), true);

  const empty = planCompare({ base: { kind: "commit", value: "  " }, head: { kind: "commit", value: "HEAD" }, pr: "" }, inventory);
  assert.equal(empty.ok, false);
  if (empty.ok) return;
  assert.match(empty.error, /Enter a commit/);

  assert.equal(readCompareForm(null), null);
  assert.deepEqual(readCompareForm({ pr: " 8 ", base: { kind: "nope", value: "x" }, head: { kind: "commit", value: "HEAD" } }), {
    base: null,
    head: { kind: "commit", value: "HEAD" },
    pr: "8",
  });
});

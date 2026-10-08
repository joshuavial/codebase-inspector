import assert from "node:assert/strict";
import { test } from "node:test";
import { assertRemoteArgv, FETCH_ARGV, parseRemoteRefs, REMOTES_ARGV } from "./git-remotes";

test("remote branches drop the symbolic HEAD and stay sorted", () => {
  const text = [
    "origin/main\0aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "origin/HEAD\0aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "origin/feature\0bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    "upstream/topic\0cccccccccccccccccccccccccccccccccccccccc",
    "",
  ].join("\n");
  assert.deepEqual(parseRemoteRefs(text).map((ref) => ref.name), ["origin/feature", "origin/main", "upstream/topic"]);
  assert.equal(parseRemoteRefs("").length, 0);
  assert.equal(parseRemoteRefs("origin\0").length, 0);
});

test("the only git commands are a user fetch and a read of remote refs", () => {
  assert.deepEqual(FETCH_ARGV, ["fetch", "--prune"]);
  assert.equal(REMOTES_ARGV[0], "for-each-ref");
  assert.doesNotThrow(() => assertRemoteArgv(FETCH_ARGV));
  assert.doesNotThrow(() => assertRemoteArgv(REMOTES_ARGV));
  for (const verb of ["checkout", "switch", "stash", "reset", "clean", "worktree", "commit", "merge", "rebase"]) {
    assert.throws(() => assertRemoteArgv([verb]), new RegExp(`refusing git ${verb}`));
  }
});

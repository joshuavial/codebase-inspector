import assert from "node:assert/strict";
import { test } from "node:test";
import { errorToast, updateToast } from "./toast";

test("an unchanged build does not toast", () => {
  assert.equal(updateToast(3, "abc", "abc"), null);
  assert.equal(updateToast(3, "", "abc"), null);
  assert.equal(updateToast(0, "abc", ""), null);
});

test("a different build names how many files changed", () => {
  assert.deepEqual(updateToast(3, "old", "new"), {
    kind: "update",
    message: "Map updated: 3 files changed.",
    action: "Show",
  });
  assert.equal(updateToast(1, "old", "new")?.message, "Map updated: 1 file changed.");
  assert.equal(updateToast(0, "old", "new")?.message, "Map updated.");
});

test("a scan error keeps the detail and shortens the line", () => {
  const toast = errorToast("cbi scan failed.\nmodel is locked\ntry again");
  assert.equal(toast.kind, "error");
  assert.equal(toast.message, "cbi scan failed.");
  assert.match(toast.detail, /model is locked/);
  assert.equal(errorToast("   ").message, "Scan failed.");
  const long = errorToast(`${"x".repeat(200)}\nmore`);
  assert.equal(long.message.length, 180);
  assert.ok(long.message.endsWith("…"));
  assert.equal(long.detail, `${"x".repeat(200)}\nmore`);
});

import assert from "node:assert/strict";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { pathToFileURL } from "node:url";
import { sameViewer, sameViewerFile } from "./viewer-load";

const index = path.join(os.tmpdir(), "repo", ".cbi", "viewer", "index.html");
const url = `${pathToFileURL(index).href}#s=auth`;

test("the same file and hash is already showing", () => {
  assert.equal(sameViewer(url, index, "s=auth"), true);
});

test("a different hash needs a load", () => {
  assert.equal(sameViewer(url, index, "s=other"), false);
  assert.equal(sameViewer(url, index, ""), false);
});

test("a page that is not the viewer needs a load", () => {
  assert.equal(sameViewer("about:blank", index, ""), false);
  assert.equal(sameViewer("", index, "s=auth"), false);
});

test("the same viewer file ignores the hash", () => {
  assert.equal(sameViewerFile(url, index), true);
  assert.equal(sameViewerFile("about:blank", index), false);
});

test("a hash in the file url is not part of the path", () => {
  const spaced = path.join(os.tmpdir(), "my repo", "index.html");
  const spacedUrl = `${pathToFileURL(spaced).href}#s=a%20b`;
  assert.equal(sameViewer(spacedUrl, spaced, "s=a%20b"), true);
});

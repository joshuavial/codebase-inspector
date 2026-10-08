import assert from "node:assert/strict";
import path from "node:path";
import { test } from "node:test";
import { dockIcon, windowIcon } from "./icon";

test("the window icon is the build PNG", () => {
  assert.equal(windowIcon("/app"), path.join("/app", "build", "icon.png"));
});

test("the Dock icon is set in dev and left to the bundle when packaged", () => {
  assert.equal(dockIcon("/app", false), path.join("/app", "build", "icon.png"));
  assert.equal(dockIcon("/app", true), null);
});

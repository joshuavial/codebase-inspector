import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { after, test } from "node:test";
import { findCbi, readSetting, writeSetting } from "./cbi-bin";

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "cbi-bin-"));
after(() => fs.rmSync(tmp, { recursive: true, force: true }));

function lookup(files: string[]) {
  const have = new Set(files);
  return (opts: Omit<Parameters<typeof findCbi>[0], "isExecutable">) => findCbi({ ...opts, isExecutable: (file) => have.has(file) });
}

test("CBI_BIN wins when it is executable", () => {
  const found = lookup(["/opt/cbi"])({ envOverride: "/opt/cbi", setting: "/other", pathEnv: "/bin", home: "/Users/me" });
  assert.deepEqual(found, { ok: true, path: "/opt/cbi" });
});

test("a CBI_BIN that is not executable is an error", () => {
  const found = lookup([])({ envOverride: "/missing/cbi", home: "/Users/me" });
  assert.equal(found.ok, false);
  if (found.ok) return;
  assert.match(found.error, /CBI_BIN is set to \/missing\/cbi/);
  assert.match(found.error, /uv tool install/);
});

test("the saved path wins over PATH and is not replaced when it is wrong", () => {
  const bad = lookup(["/bin/cbi"])({ setting: "/typo/cbi", pathEnv: "/bin", home: "/Users/me" });
  assert.equal(bad.ok, false);
  if (bad.ok) return;
  assert.match(bad.error, /settings/);
  const good = lookup(["/bin/cbi"])({ setting: "/bin/cbi", pathEnv: "/nowhere", home: "/Users/me" });
  assert.deepEqual(good, { ok: true, path: "/bin/cbi" });
});

test("PATH is searched, then ~/.local/bin/cbi", () => {
  const onPath = lookup(["/opt/bin/cbi", "/Users/me/.local/bin/cbi"])({ pathEnv: "/usr/bin:/opt/bin", home: "/Users/me" });
  assert.deepEqual(onPath, { ok: true, path: "/opt/bin/cbi" });
  const local = lookup(["/Users/me/.local/bin/cbi"])({ pathEnv: "/usr/bin", home: "/Users/me" });
  assert.deepEqual(local, { ok: true, path: "/Users/me/.local/bin/cbi" });
});

test("windows searches PATH for cbi.exe, then the user local bin, then where", () => {
  const exe = "C:\\bin\\cbi.exe";
  const onPath = lookup([exe])({
    pathEnv: "C:\\Windows;C:\\bin",
    home: "C:\\Users\\me",
    platform: "win32",
    where: () => { throw new Error("where should not run"); },
  });
  assert.deepEqual(onPath, { ok: true, path: exe });
  const local = "C:\\Users\\me\\.local\\bin\\cbi.exe";
  const fromHome = lookup([local])({
    pathEnv: "C:\\Windows",
    home: "C:\\Users\\me",
    platform: "win32",
    where: () => null,
  });
  assert.deepEqual(fromHome, { ok: true, path: local });
  const fromWhere = lookup(["D:\\tools\\cbi.cmd"])({
    pathEnv: "C:\\Windows",
    home: "C:\\Users\\nobody",
    platform: "win32",
    where: () => "D:\\tools\\cbi.cmd",
  });
  assert.deepEqual(fromWhere, { ok: true, path: "D:\\tools\\cbi.cmd" });
});

test("a missing cbi explains how to install it", () => {
  const found = lookup([])({ pathEnv: "/usr/bin", home: "/Users/nobody" });
  assert.equal(found.ok, false);
  if (found.ok) return;
  assert.match(found.error, /cbi was not found/);
  assert.match(found.error, /uv tool install \./);
});

test("settings round-trip and a damaged file is unset", () => {
  const file = path.join(tmp, "settings.json");
  writeSetting(file, { cbiPath: "/bin/cbi" });
  assert.deepEqual(readSetting(file), { cbiPath: "/bin/cbi" });
  writeSetting(file, { cbiPath: null });
  assert.deepEqual(readSetting(file), { cbiPath: null });
  fs.writeFileSync(file, "{");
  assert.deepEqual(readSetting(file), { cbiPath: null });
});

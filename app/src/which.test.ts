import assert from "node:assert/strict";
import { test } from "node:test";
import { commandExecutable, commandNames, findOnPath, missingGit, pathSeparator } from "./which";

test("command names and PATH separators follow the platform", () => {
  assert.deepEqual(commandNames("code", "darwin"), ["code"]);
  assert.deepEqual(commandNames("code", "win32"), ["code.cmd", "code.exe", "code"]);
  assert.deepEqual(commandNames("git", "win32"), ["git.exe", "git.cmd", "git"]);
  assert.deepEqual(commandNames("cbi", "win32"), ["cbi.exe", "cbi.cmd", "cbi"]);
  assert.equal(pathSeparator("win32"), ";");
  assert.equal(pathSeparator("linux"), ":");
});

test("findOnPath on windows prefers exe, then where, and does not use where elsewhere", () => {
  const git = findOnPath("git", {
    pathEnv: "C:\\Windows;C:\\Program Files\\Git\\cmd",
    platform: "win32",
    isExecutable: (file) => file === "C:\\Program Files\\Git\\cmd\\git.exe",
    where: () => { throw new Error("where should not run"); },
  });
  assert.equal(git, "C:\\Program Files\\Git\\cmd\\git.exe");
  const fell = findOnPath("git", {
    pathEnv: "C:\\empty",
    platform: "win32",
    isExecutable: (file) => file === "D:\\git.exe",
    where: () => "D:\\git.exe",
  });
  assert.equal(fell, "D:\\git.exe");
  const linux = findOnPath("git", {
    pathEnv: "/usr/bin",
    platform: "linux",
    isExecutable: (file) => file === "/usr/bin/git",
    where: () => { throw new Error("where is windows-only"); },
  });
  assert.equal(linux, "/usr/bin/git");
});

test("a missing git message names the platform", () => {
  assert.match(missingGit("darwin"), /Xcode command line tools/);
  assert.match(missingGit("win32"), /Git for Windows/);
  assert.match(missingGit("linux"), /Install git/);
  assert.equal(commandExecutable("git", {
    pathEnv: "/nowhere",
    platform: "linux",
    isExecutable: () => false,
    where: null,
  }), "git");
});

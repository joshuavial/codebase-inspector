import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { after, test } from "node:test";
import { GIT_ARGV, realGit, resolveProject, type GitRunner } from "./project";

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "cbi-resolve-"));
after(() => fs.rmSync(tmp, { recursive: true, force: true }));

function git(cwd: string, args: string[]) {
  execFileSync("git", args, { cwd, stdio: "pipe" });
}

function initRepo(dir: string) {
  fs.mkdirSync(dir, { recursive: true });
  git(dir, ["init", "-q", "-b", "main"]);
  git(dir, ["config", "user.email", "t@example.com"]);
  git(dir, ["config", "user.name", "t"]);
  fs.writeFileSync(path.join(dir, "README.md"), "hello\n");
  git(dir, ["add", "README.md"]);
  git(dir, ["commit", "-q", "-m", "init"]);
}

function record(calls: string[][]): GitRunner {
  return (cwd, args) => {
    calls.push(args);
    return realGit(cwd, args);
  };
}

function assertAllowed(calls: string[][]) {
  for (const args of calls) {
    const ok = GIT_ARGV.some((expected) => expected.join(" ") === args.join(" "));
    assert.equal(ok, true, `unexpected git ${args.join(" ")}`);
  }
}

function porcelain(dir: string): string {
  return execFileSync("git", ["status", "--porcelain"], { cwd: dir, encoding: "utf8" });
}

test("a folder inside a repository resolves to that repository", () => {
  const root = path.join(tmp, "plain");
  initRepo(root);
  fs.mkdirSync(path.join(root, "src", "nested"), { recursive: true });
  const calls: string[][] = [];
  const result = resolveProject(path.join(root, "src", "nested"), record(calls));
  assert.equal(result.ok, true);
  if (!result.ok) return;
  assert.equal(result.main, fs.realpathSync(root));
  assert.equal(result.branch, "main");
  assertAllowed(calls);
  assert.equal(porcelain(root), "");
});

test("a file inside a repository resolves to the repository", () => {
  const root = path.join(tmp, "file-repo");
  initRepo(root);
  const result = resolveProject(path.join(root, "README.md"));
  assert.equal(result.ok, true);
  if (!result.ok) return;
  assert.equal(result.main, fs.realpathSync(root));
  assert.equal(porcelain(root), "");
});

test("a linked worktree resolves to the main worktree", () => {
  const root = path.join(tmp, "linked");
  const lane = path.join(tmp, "linked-lane");
  initRepo(root);
  git(root, ["worktree", "add", "-q", "-b", "lane", lane]);
  fs.mkdirSync(path.join(lane, "nested"), { recursive: true });
  const calls: string[][] = [];
  const result = resolveProject(path.join(lane, "nested"), record(calls));
  assert.equal(result.ok, true);
  if (!result.ok) return;
  assert.equal(result.main, fs.realpathSync(root));
  assert.equal(result.branch, "main");
  assertAllowed(calls);
  assert.equal(porcelain(root), "");
  assert.equal(porcelain(lane), "");
});

test("a detached main worktree is labelled detached", () => {
  const root = path.join(tmp, "detached");
  initRepo(root);
  git(root, ["checkout", "-q", "--detach"]);
  const result = resolveProject(root);
  assert.equal(result.ok, true);
  if (!result.ok) return;
  assert.equal(result.branch, "detached");
  assert.equal(result.main, fs.realpathSync(root));
  assert.equal(porcelain(root), "");
});

test("a submodule resolves to the submodule, including from its linked worktree", () => {
  const sub = path.join(tmp, "sub");
  const sup = path.join(tmp, "super");
  const lane = path.join(tmp, "sub-lane");
  initRepo(sub);
  initRepo(sup);
  execFileSync("git", ["-C", sup, "-c", "protocol.file.allow=always", "submodule", "add", "-q", sub, "lib"], { stdio: "pipe" });
  git(sup, ["commit", "-q", "-m", "add lib"]);
  git(path.join(sup, "lib"), ["worktree", "add", "-q", "-b", "lane", lane]);
  const fromCheckout = resolveProject(path.join(sup, "lib"));
  const fromLane = resolveProject(lane);
  const main = fs.realpathSync(path.join(sup, "lib"));
  assert.equal(fromCheckout.ok && fromCheckout.main, main);
  assert.equal(fromLane.ok && fromLane.main, main);
  assert.notEqual(fromLane.ok && fromLane.main, fs.realpathSync(sup));
});

test("a separate git dir resolves to its working tree", () => {
  const work = path.join(tmp, "separated");
  const gitdir = path.join(tmp, "separated.git");
  fs.mkdirSync(work, { recursive: true });
  git(work, ["init", "-q", "--separate-git-dir", gitdir, "-b", "main"]);
  git(work, ["config", "user.email", "t@example.com"]);
  git(work, ["config", "user.name", "t"]);
  fs.writeFileSync(path.join(work, "README.md"), "hello\n");
  git(work, ["add", "README.md"]);
  git(work, ["commit", "-q", "-m", "init"]);
  const result = resolveProject(work);
  assert.equal(result.ok, true);
  if (!result.ok) return;
  assert.equal(result.main, fs.realpathSync(work));
  assert.equal(result.branch, "main");
});

test("a folder that is not a repository is refused", () => {
  const dir = path.join(tmp, "nope");
  fs.mkdirSync(dir);
  const result = resolveProject(dir);
  assert.deepEqual(result, { ok: false, error: "This folder is not inside a git repository." });
});

test("a missing folder is refused", () => {
  const result = resolveProject(path.join(tmp, "missing"));
  assert.deepEqual(result, { ok: false, error: "That folder does not exist." });
});

test("a bare repository is refused", () => {
  const bare = path.join(tmp, "bare.git");
  git(tmp, ["init", "-q", "--bare", bare]);
  const calls: string[][] = [];
  const result = resolveProject(bare, record(calls));
  assert.equal(result.ok, false);
  if (result.ok) return;
  assert.match(result.error, /bare repository/);
  assert.deepEqual(calls, [["rev-parse", "--is-bare-repository"]]);
});

test("an old git without --path-format still resolves a relative common dir", () => {
  const root = path.join(tmp, "relative");
  const sub = path.join(root, "sub");
  fs.mkdirSync(sub, { recursive: true });
  const calls: string[][] = [];
  const fake: GitRunner = (_cwd, args) => {
    calls.push(args);
    const key = args.join(" ");
    if (key === "rev-parse --is-bare-repository") return { code: 0, stdout: "false\n", stderr: "" };
    if (key === "rev-parse --path-format=absolute --git-common-dir") return { code: 129, stdout: "", stderr: "unknown" };
    if (key === "rev-parse --git-common-dir") return { code: 0, stdout: "../.git\n", stderr: "" };
    if (key === "rev-parse --abbrev-ref HEAD") return { code: 0, stdout: "main\n", stderr: "" };
    return { code: 1, stdout: "", stderr: key };
  };
  const result = resolveProject(sub, fake, (file) => file);
  assert.deepEqual(result, { ok: true, main: root, branch: "main" });
  assertAllowed(calls);
});

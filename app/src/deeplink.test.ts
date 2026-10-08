import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { after, test } from "node:test";
import {
  allowedGitArgs,
  linkFromArgv,
  parseOpenUrl,
  realGh,
  validateOpen,
  validNodeId,
  viewerLocation,
  type GhRunner,
} from "./deeplink";
import { GIT_ARGV, realGit, type GitRunner } from "./project";

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "cbi-deeplink-"));
after(() => fs.rmSync(tmp, { recursive: true, force: true }));

const IDS = [
  "app",
  "bearer-auth",
  "ui/login",
  "local:repo",
  "local:repo:src/",
  "local:repo:src/shapes/circle.ts",
  "local:repo:src/shapes/circle.ts#Circle.area",
  "local:repo:src/shapes/circle.test.ts#measures the area",
  "local:repo:core/tests/test_geometry.py#TestCircle > test_area",
  "local:repo:core/tests/test_geometry.py#TestCircle > TestNested > test_unit",
  "local:repo:src/a.ts#same~f361afdb~2",
  "github.com/example/sample-lib:src/app.ts#Foo.bar",
  "local:fixture-app:deployable:fixture-cli",
  "local:repo:env:PORT",
  "local:repo:package:pkg",
  "local:repo:service:db",
];

const REJECTED = [
  "$(id)",
  "`id`",
  "id;rm -rf /",
  "id|id",
  "id && id",
  "id\nid",
  "<script>",
  "../etc/passwd",
  "local:repo:../../etc/passwd",
  "id > /tmp/pwn",
  "local:repo:src/a.ts#foo > /tmp/pwn",
  "http://evil.example",
  "-rf",
];

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

function link(params: Record<string, string>): string {
  return `cbi://open?${new URLSearchParams(params)}`;
}

function record(calls: string[][]): GitRunner {
  return (cwd, args) => {
    calls.push(args);
    return realGit(cwd, args);
  };
}

function assertReadOnly(calls: string[][]) {
  for (const args of calls) {
    const projectCall = GIT_ARGV.some((expected) => expected.join(" ") === args.join(" "));
    assert.equal(projectCall || allowedGitArgs(args), true, `unexpected git ${args.join(" ")}`);
  }
}

function porcelain(dir: string): string {
  return execFileSync("git", ["status", "--porcelain"], { cwd: dir, encoding: "utf8" });
}

test("node ids match the grammar and injection does not", () => {
  for (const id of IDS) assert.equal(validNodeId(id), true, id);
  for (const id of REJECTED) assert.equal(validNodeId(id), false, id);
});

test("a python-style link round-trips a node id", () => {
  const raw = "cbi://open?repo=%2Ftmp%2Ffixture&ref=main&node=local%3Arepo%3Asrc%2Fa.ts%23measures+the+area";
  const parsed = parseOpenUrl(raw);
  assert.equal(parsed.ok, true);
  if (!parsed.ok) return;
  assert.equal(parsed.query.repo, "/tmp/fixture");
  assert.equal(parsed.query.ref, "main");
  assert.equal(parsed.query.node, "local:repo:src/a.ts#measures the area");
});

test("viewer location keeps a back chip when a window is already open", () => {
  const cold = new URLSearchParams(viewerLocation("local:repo:deployable:web", null));
  assert.equal(cold.get("c"), "local:repo:deployable:web");
  assert.equal(cold.get("from"), null);
  const again = new URLSearchParams(viewerLocation("local:repo:src/a.ts#greet", "#c=old&s=1"));
  assert.equal(again.get("s"), "local:repo:src/a.ts#greet");
  assert.equal(again.get("from"), "~");
  assert.equal(again.get("bh"), "c=old&s=1");
  const top = new URLSearchParams(viewerLocation(null, ""));
  assert.equal(top.get("from"), "~");
  assert.equal(top.get("bh"), "-");
});

test("argv carries a cbi link for a second instance", () => {
  assert.equal(linkFromArgv(["electron", ".", "cbi://open?repo=%2Ftmp%2Frepo"]), "cbi://open?repo=%2Ftmp%2Frepo");
  assert.equal(linkFromArgv(["electron", "."]), null);
  const win = "cbi://open?repo=C%3A%5Csrc%5Crepo";
  assert.equal(linkFromArgv(["C:\\Program Files\\Codebase Inspector\\app.exe", win]), win);
  const parsed = parseOpenUrl(win, "win32");
  assert.equal(parsed.ok, true);
  if (!parsed.ok) return;
  assert.equal(parsed.query.repo, "C:\\src\\repo");
  const slash = parseOpenUrl("cbi://open?repo=C%3A%2Fsrc%2Frepo", "win32");
  assert.equal(slash.ok, true);
  if (!slash.ok) return;
  assert.equal(slash.query.repo, "C:/src/repo");
  assert.equal(parseOpenUrl(win).ok, false);
});

test("git argv for a link is read-only", () => {
  assert.equal(allowedGitArgs(["rev-parse", "--verify", "--end-of-options", "main^{commit}"]), true);
  assert.equal(allowedGitArgs(["checkout", "main"]), false);
  assert.equal(allowedGitArgs(["switch", "main"]), false);
  assert.equal(allowedGitArgs(["stash", "push"]), false);
  assert.equal(allowedGitArgs(["worktree", "add", "lane"]), false);
  assert.equal(allowedGitArgs(["reset", "--hard"]), false);
});

test("a worktree link resolves and a bad link is refused", () => {
  const repo = path.join(tmp, "repo");
  const lane = path.join(tmp, "lane");
  initRepo(repo);
  git(repo, ["worktree", "add", "-q", "-b", "lane", lane]);
  const calls: string[][] = [];
  const opened = validateOpen(link({ repo, ref: lane, node: "local:repo:deployable:web" }), record(calls));
  assert.equal(opened.ok, true);
  if (!opened.ok) return;
  assert.equal(opened.opened.project, fs.realpathSync(repo));
  assert.equal(opened.opened.cwd, fs.realpathSync(lane));
  assert.equal(opened.opened.branch, "lane");
  assert.deepEqual(opened.opened.refArgs, []);
  assert.equal(opened.opened.watch, true);
  assert.equal(opened.opened.node, "local:repo:deployable:web");
  assertReadOnly(calls);
  assert.equal(porcelain(repo), "");

  const branch = validateOpen(link({ repo, ref: "main" }), record(calls));
  assert.equal(branch.ok, true);
  if (!branch.ok) return;
  assert.deepEqual(branch.opened.refArgs, ["--ref", "main"]);
  assert.equal(branch.opened.watch, false);
  assert.ok(branch.opened.viewerIndex.includes(`${path.sep}refs${path.sep}`));
  assert.equal(porcelain(repo), "");
});

test("path traversal, a non-repo, an unknown ref and a bad node are refused", () => {
  const repo = path.join(tmp, "plain");
  initRepo(repo);
  const calls: string[][] = [];
  const git = record(calls);
  const escaped = `${repo}/../../etc/passwd`;
  const traversal = validateOpen(link({ repo: escaped, ref: "main" }), git);
  assert.equal(traversal.ok, false);
  if (traversal.ok) return;
  assert.match(traversal.error, /not allowed/);
  assert.equal(calls.length, 0);

  const outside = path.join(tmp, "not-a-repo");
  fs.mkdirSync(outside);
  const missing = validateOpen(link({ repo: outside }), git);
  assert.equal(missing.ok, false);
  if (missing.ok) return;
  assert.match(missing.error, /not inside a git repository/);

  const unknown = validateOpen(link({ repo, ref: "no-such-branch" }), git);
  assert.equal(unknown.ok, false);
  if (unknown.ok) return;
  assert.match(unknown.error, /unknown ref no-such-branch/);

  for (const node of ["$(id)", "`id`", "local:repo:../../etc/passwd", "id;rm -rf /"]) {
    const refused = parseOpenUrl(link({ repo, ref: "main", node }));
    assert.equal(refused.ok, false, node);
    if (refused.ok) return;
    assert.match(refused.error, /not valid/);
  }
  assert.equal(porcelain(repo), "");
  assertReadOnly(calls);
});

test("a compare link resolves both refs and a pr link uses gh", () => {
  const repo = path.join(tmp, "compare");
  initRepo(repo);
  fs.writeFileSync(path.join(repo, "README.md"), "next\n");
  git(repo, ["add", "README.md"]);
  git(repo, ["commit", "-q", "-m", "next"]);
  const head = execFileSync("git", ["rev-parse", "HEAD"], { cwd: repo, encoding: "utf8" }).trim();
  const base = execFileSync("git", ["rev-parse", "HEAD~1"], { cwd: repo, encoding: "utf8" }).trim();
  const calls: string[][] = [];
  const opened = validateOpen(link({ repo, compare: `${base}..${head}`, node: "local:repo:deployable:web" }), record(calls));
  assert.equal(opened.ok, true);
  if (!opened.ok) return;
  assert.equal(opened.opened.project, fs.realpathSync(repo));
  assert.equal(opened.opened.watch, false);
  assert.deepEqual(opened.opened.refArgs, []);
  assert.equal(opened.opened.node, "local:repo:deployable:web");
  assert.deepEqual(opened.opened.compare, { base, head, baseSha: base, headSha: head });
  assertReadOnly(calls);

  const ghCalls: string[][] = [];
  const gh: GhRunner = (_cwd, args) => {
    ghCalls.push(args);
    return { code: 0, stdout: JSON.stringify({ baseRefOid: base, headRefOid: head }), stderr: "" };
  };
  const pr = validateOpen(link({ repo, pr: "2345" }), record(calls), gh);
  assert.equal(pr.ok, true);
  if (!pr.ok) return;
  assert.deepEqual(ghCalls, [["pr", "view", "2345", "--json", "baseRefOid,headRefOid"]]);
  assert.equal(pr.opened.compare?.baseSha, base);
  assert.equal(pr.opened.compare?.headSha, head);
  assert.equal(pr.opened.compare?.base, base);

  const named = validateOpen(link({ repo, compare: "main..main" }), record(calls));
  assert.equal(named.ok, true);
  if (!named.ok || !named.opened.compare) return;
  assert.equal(named.opened.compare.base, "main");
  assert.equal(named.opened.compare.baseSha, head);

  const failed = validateOpen(link({ repo, pr: "8" }), record(calls), () => ({ code: 1, stdout: "", stderr: "no such pull request\n" }));
  assert.equal(failed.ok, false);
  if (failed.ok) return;
  assert.match(failed.error, /no such pull request/);

  const partial = validateOpen(link({ repo, pr: "9" }), record(calls), () => ({
    code: 0,
    stdout: JSON.stringify({ baseRefOid: base }),
    stderr: "",
  }));
  assert.equal(partial.ok, false);
  if (partial.ok) return;
  assert.match(partial.error, /baseRefOid and headRefOid/);

  const missing = "c".repeat(40);
  const unknownOid = validateOpen(link({ repo, pr: "10" }), record(calls), () => ({
    code: 0,
    stdout: JSON.stringify({ baseRefOid: base, headRefOid: missing }),
    stderr: "",
  }));
  assert.equal(unknownOid.ok, false);
  if (unknownOid.ok) return;
  assert.match(unknownOid.error, new RegExp(`unknown ref ${missing}`));

  const badRange = parseOpenUrl(link({ repo, compare: "main...feature" }));
  assert.equal(badRange.ok, false);
  if (badRange.ok) return;
  assert.match(badRange.error, /base\.\.head/);

  const badPr = parseOpenUrl(link({ repo, pr: "12;rm" }));
  assert.equal(badPr.ok, false);
  if (badPr.ok) return;
  assert.match(badPr.error, /pull request number/);

  const both = parseOpenUrl(link({ repo, compare: "main..main", pr: "1" }));
  assert.equal(both.ok, false);
  if (both.ok) return;
  assert.match(both.error, /not both/);

  const withRef = parseOpenUrl(link({ repo, ref: "main", compare: "main..main" }));
  assert.equal(withRef.ok, false);

  const unknown = validateOpen(link({ repo, compare: "main..no-such" }));
  assert.equal(unknown.ok, false);
  if (unknown.ok) return;
  assert.match(unknown.error, /unknown ref no-such/);
  assert.equal(porcelain(repo), "");
  assert.throws(() => realGh(repo, ["repo", "clone", "example"]), /refusing gh/);
});

test("an unknown parameter is refused", () => {
  const parsed = parseOpenUrl("cbi://open?repo=/tmp/repo&cmd=checkout");
  assert.equal(parsed.ok, false);
  if (parsed.ok) return;
  assert.match(parsed.error, /Unknown parameter cmd/);
});

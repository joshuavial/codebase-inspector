import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { after, test } from "node:test";
import {
  commandArgv,
  detachedArgv,
  EditorError,
  fillTemplate,
  findProgram,
  launchEditor,
  normalizeChoice,
  planViewerOpen,
  readEditorSettings,
  refEditorContext,
  resolveRefTarget,
  snapshotCache,
  snapshotNotice,
  splitTemplate,
  TEMPLATES,
  writeEditorSettings,
} from "./editor";

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "cbi-editor-"));
after(() => fs.rmSync(tmp, { recursive: true, force: true }));

test("the preset splits into the reuse-window command", () => {
  assert.deepEqual(splitTemplate(TEMPLATES.vscode), ["code", "--reuse-window", "{project}", "--goto", "{file}:{line}"]);
  assert.deepEqual(splitTemplate("cmd \"a b\" 'c d'"), ["cmd", "a b", "c d"]);
});

test("a path with spaces stays one argument, and a semicolon is not a shell separator", () => {
  assert.deepEqual(fillTemplate('open "{file}"', "/p", "/a file.ts", 3), ["open", "/a file.ts"]);
  assert.deepEqual(fillTemplate("echo {file};", "/p", "/a", 1), ["echo", "/a;"]);
  assert.deepEqual(fillTemplate("echo {file}", "/p", "/a", 0), ["echo", "/a"]);
});

test("an empty template or an unclosed quote is an error", () => {
  assert.throws(() => splitTemplate("   "), (err: unknown) => err instanceof EditorError && err.code === 2);
  assert.throws(() => splitTemplate('open "unterminated'), (err: unknown) => err instanceof EditorError && err.code === 2);
});

test("a worktree file is opened there, and a missing one is not on disk", () => {
  const workDir = path.join(tmp, "work");
  fs.mkdirSync(workDir, { recursive: true });
  const work = fs.realpathSync(workDir);
  fs.writeFileSync(path.join(work, "a.ts"), "x\n");
  const bin = path.join(tmp, "bin", "code");
  fs.mkdirSync(path.dirname(bin), { recursive: true });
  const exe = (file: string) => file === bin;
  const found = planViewerOpen({
    file: "a.ts", line: 4, project: path.join(tmp, "main"), targetKind: "worktree", targetPath: work,
    editor: "vscode", template: null, pathEnv: path.dirname(bin), home: tmp, isExecutable: exe,
  });
  assert.equal(found.ok, true);
  if (!found.ok) return;
  const file = fs.realpathSync(path.join(work, "a.ts"));
  assert.deepEqual(found.argv, [bin, "--reuse-window", work, "--goto", `${file}:4`]);
  const missing = planViewerOpen({
    file: "gone.ts", line: 1, project: work, targetKind: "worktree", targetPath: work,
    editor: "vscode", template: null, pathEnv: path.dirname(bin), home: tmp, isExecutable: exe,
  });
  assert.deepEqual(missing, { ok: false, error: "This file is not on disk." });
});

const SIDE = "b".repeat(40);

function editorOpen(extra: Record<string, unknown>) {
  const bin = path.join(tmp, "bin", "code");
  return planViewerOpen({
    file: "src/pay.py", line: 1, project: tmp, targetKind: "branch", targetPath: null,
    editor: "vscode", template: null, pathEnv: path.dirname(bin), home: tmp,
    isExecutable: (file) => file === bin,
    repo: tmp, branch: "feature/side-by-side", sha: SIDE, ...extra,
  });
}

test("a ref opens the worktree that has the branch, or the same commit", () => {
  const main = path.join(tmp, "wt-main");
  const side = path.join(tmp, "wt-side");
  const detached = path.join(tmp, "wt-detached");
  for (const dir of [main, side, detached]) fs.mkdirSync(path.join(dir, "src"), { recursive: true });
  fs.writeFileSync(path.join(main, "src", "pay.py"), "return 0\n");
  fs.writeFileSync(path.join(side, "src", "pay.py"), "return 1\n");
  fs.writeFileSync(path.join(detached, "src", "pay.py"), "return 2\n");
  const cache = path.join(tmp, "wt-cache");
  const rows = [
    { path: main, branch: "main", head: "c".repeat(40) },
    { path: side, branch: "feature/side-by-side", head: SIDE },
    { path: detached, branch: null, head: SIDE },
  ];
  const open = editorOpen({
    project: main, repo: main, cacheDir: cache, listWorktrees: () => rows,
    showBlob: () => { throw new Error("git show"); },
  });
  assert.equal(open.ok, true);
  if (!open.ok) return;
  assert.equal(open.notice, undefined);
  assert.equal(open.argv[2], fs.realpathSync(side));
  assert.equal(open.argv[4], `${fs.realpathSync(path.join(side, "src", "pay.py"))}:1`);
  assert.equal(fs.existsSync(cache), false);

  const commit = editorOpen({
    project: main, repo: main, line: 3, cacheDir: cache,
    listWorktrees: () => rows.filter((row) => row.path !== side),
    showBlob: () => { throw new Error("git show"); },
  });
  assert.equal(commit.ok, true);
  if (!commit.ok) return;
  assert.equal(commit.notice, undefined);
  assert.equal(commit.argv[2], fs.realpathSync(detached));
  assert.equal(commit.argv[4], `${fs.realpathSync(path.join(detached, "src", "pay.py"))}:3`);
  assert.equal(fs.existsSync(cache), false);
});

test("a ref snapshot is created and reused", () => {
  const main = path.join(tmp, "snap-main");
  fs.mkdirSync(path.join(main, "src"), { recursive: true });
  fs.writeFileSync(path.join(main, "src", "pay.py"), "return 0\n");
  const cache = path.join(tmp, "snap-cache");
  const bytes = Buffer.from("def arrears():\n    return 1\n");
  let shows = 0;
  const opts = {
    project: main, repo: main, line: 2, cacheDir: cache,
    listWorktrees: () => [{ path: main, branch: "main", head: "c".repeat(40) }],
    showBlob: () => { shows += 1; return bytes; },
  };
  const open = editorOpen(opts);
  assert.equal(open.ok, true);
  if (!open.ok) return;
  assert.equal(shows, 1);
  assert.equal(open.notice, snapshotNotice("feature/side-by-side", SIDE));
  assert.match(open.argv[2], new RegExp(`snap-main@feature-side-by-side-${SIDE.slice(0, 12)}$`));
  const file = open.argv[4].slice(0, -2);
  assert.equal(file.endsWith(`${path.sep}src${path.sep}pay.py`), true);
  assert.equal(fs.readFileSync(file, "utf8"), bytes.toString());
  assert.equal(fs.statSync(file).mode & 0o777, 0o444);
  assert.equal(fs.readFileSync(path.join(main, "src", "pay.py"), "utf8"), "return 0\n");
  const stamp = fs.statSync(file, { bigint: true }).mtimeNs;
  const again = editorOpen(opts);
  assert.equal(again.ok, true);
  if (!again.ok) return;
  assert.equal(shows, 1);
  assert.equal(again.argv[4], open.argv[4]);
  assert.equal(fs.statSync(file, { bigint: true }).mtimeNs, stamp);
});

test("a ref snapshot refuses a path that escapes", () => {
  const cache = path.join(tmp, "escape-cache");
  fs.mkdirSync(cache);
  const boom = () => { throw new Error("git was called"); };
  for (const rel of ["../secret", "/etc/passwd", "src/../../secret", "foo/../../../etc/passwd", "a\0b"]) {
    const open = editorOpen({
      file: rel, cacheDir: cache, listWorktrees: boom, showBlob: boom,
    });
    assert.equal(open.ok, false);
    if (open.ok) return;
    assert.match(open.error, /outside|no file/);
  }
  assert.deepEqual(fs.readdirSync(cache), []);
  const direct = () => resolveRefTarget("../secret", 1, {
    repo: tmp, branch: "side", sha: SIDE, cacheDir: cache, listWorktrees: boom, showBlob: boom,
  });
  assert.throws(direct, (err: unknown) => err instanceof EditorError);
});

test("a ref view names the branch and commit, and a worktree is not a ref", () => {
  assert.deepEqual(refEditorContext({ kind: "worktree", name: "main", head: SIDE }), { ref: false, branch: "", sha: "" });
  assert.deepEqual(refEditorContext({ kind: "branch", name: "side", head: SIDE }), { ref: true, branch: "side", sha: SIDE });
  assert.deepEqual(refEditorContext({ kind: "remote", name: "origin/side", head: SIDE }), { ref: true, branch: "origin/side", sha: SIDE });
  assert.deepEqual(refEditorContext({ kind: "compare", label: "main..side", head: SIDE }), { ref: true, branch: "", sha: SIDE });
  assert.deepEqual(refEditorContext({ kind: "compare", label: "side", head: SIDE }), { ref: true, branch: "side", sha: SIDE });
});

test("a path that leaves the project is refused, including through a symlink", () => {
  const work = path.join(tmp, "escape");
  fs.mkdirSync(work);
  const escaped = planViewerOpen({
    file: "../secret", line: 1, project: work, targetKind: "worktree", targetPath: work,
    editor: "vscode", template: null, pathEnv: "", home: tmp,
  });
  assert.deepEqual(escaped, { ok: false, error: "That path is outside the project." });
  const outside = path.join(tmp, "outside");
  fs.mkdirSync(outside);
  fs.writeFileSync(path.join(outside, "secret.txt"), "x");
  fs.symlinkSync(path.join(outside, "secret.txt"), path.join(work, "link.txt"));
  const linked = planViewerOpen({
    file: "link.txt", line: 1, project: work, targetKind: "worktree", targetPath: work,
    editor: "vscode", template: null, pathEnv: "", home: tmp,
  });
  assert.deepEqual(linked, { ok: false, error: "That path is outside the project." });
  fs.mkdirSync(path.join(work, "sub"));
  fs.writeFileSync(path.join(work, "sub", "a.txt"), "x");
  fs.symlinkSync(path.join(work, "sub", "a.txt"), path.join(work, "inside.txt"));
  const bin = path.join(tmp, "bin", "code");
  const ok = planViewerOpen({
    file: "inside.txt", line: 0, project: work, targetKind: "worktree", targetPath: work,
    editor: "vscode", template: null, pathEnv: path.dirname(bin), home: tmp, isExecutable: (file) => file === bin,
  });
  assert.equal(ok.ok, true);
  if (!ok.ok) return;
  assert.equal(ok.argv[4], `${fs.realpathSync(path.join(work, "sub", "a.txt"))}:1`);
});

test("code is taken from PATH, then the app bundle", () => {
  const home = path.join(tmp, "home");
  const bundle = path.join(home, "Applications", "Visual Studio Code.app/Contents/Resources/app/bin/code");
  const onPath = path.join(tmp, "pathbin", "code");
  const mac = { platform: "darwin" as const };
  assert.equal(findProgram("code", { pathEnv: path.dirname(onPath), home, isExecutable: (file) => file === onPath, ...mac }), onPath);
  assert.equal(findProgram("code", { pathEnv: "", home, isExecutable: (file) => file === bundle, ...mac }), bundle);
  assert.equal(findProgram("code", { pathEnv: "", home: path.join(tmp, "nobody"), isExecutable: () => false, ...mac }), null);
  const argv = commandArgv("vscode", null, "/proj", "/proj/a.ts", 2, {
    pathEnv: "", home, isExecutable: (file) => file === bundle, ...mac,
  });
  assert.deepEqual(argv, [bundle, "--reuse-window", "/proj", "--goto", "/proj/a.ts:2"]);
});

test("windows looks up code.cmd and caches snapshots under LocalAppData", () => {
  const cmd = "C:\\bin\\code.cmd";
  const found = findProgram("code", {
    pathEnv: "C:\\empty;C:\\bin",
    home: "C:\\Users\\me",
    platform: "win32",
    where: () => null,
    isExecutable: (file) => file === cmd,
  });
  assert.equal(found, cmd);
  const viaWhere = findProgram("code", {
    pathEnv: "",
    home: "C:\\Users\\me",
    platform: "win32",
    where: () => "D:\\editors\\code.cmd",
    isExecutable: (file) => file === "D:\\editors\\code.cmd",
  });
  assert.equal(viaWhere, "D:\\editors\\code.cmd");
  assert.equal(
    snapshotCache(null, "C:\\Users\\me", "win32", {}),
    "C:\\Users\\me\\AppData\\Local\\codebase-inspector\\snapshots",
  );
  assert.equal(
    snapshotCache(null, undefined, "win32", { LOCALAPPDATA: "D:\\Cache" }),
    "D:\\Cache\\codebase-inspector\\snapshots",
  );
  assert.equal(
    snapshotCache(null, "/home/me", "linux", {}),
    "/home/me/.cache/codebase-inspector/snapshots",
  );
  assert.equal(
    snapshotCache(null, "/home/me", "linux", { XDG_CACHE_HOME: "/var/cache" }),
    "/home/me/.cache/codebase-inspector/snapshots",
  );
  const spec = detachedArgv(["C:\\bin\\code.cmd", "--goto", "C:\\proj\\a.ts:1"], "win32");
  assert.equal(spec.command, "cmd.exe");
  assert.deepEqual(spec.args.slice(0, 3), ["/d", "/s", "/c"]);
  assert.match(spec.args[3], /code\.cmd/);
});

test("none does not launch, and a custom template must name the file", () => {
  const none = planViewerOpen({
    file: "a.ts", line: 1, project: tmp, targetKind: "worktree", targetPath: tmp,
    editor: "none", template: null, pathEnv: "", home: tmp, exists: () => true,
  });
  assert.deepEqual(none, { ok: false, error: "No editor is configured." });
  let called = false;
  const noneRef = planViewerOpen({
    file: "a.ts", line: 1, project: tmp, targetKind: "branch", targetPath: null,
    editor: "none", template: null, pathEnv: "", home: tmp,
    repo: tmp, branch: "side", sha: SIDE, cacheDir: path.join(tmp, "none-cache"),
    listWorktrees: () => { called = true; return []; },
    showBlob: () => { called = true; return Buffer.from("x"); },
  });
  assert.deepEqual(noneRef, { ok: false, error: "No editor is configured." });
  assert.equal(called, false);
  assert.throws(() => normalizeChoice("custom", "echo hi"), /must include \{file\}/);
  assert.deepEqual(normalizeChoice("custom", "echo {file}").editor, "custom");
});

test("dry run records argv and does not spawn", () => {
  const log = path.join(tmp, "argv.log");
  const marker = path.join(tmp, "spawned");
  const prev = process.env.CBI_EDITOR_DRY_RUN;
  process.env.CBI_EDITOR_DRY_RUN = log;
  try {
    launchEditor([marker, "--goto", "x:1"]);
  } finally {
    if (prev === undefined) delete process.env.CBI_EDITOR_DRY_RUN;
    else process.env.CBI_EDITOR_DRY_RUN = prev;
  }
  assert.equal(fs.existsSync(marker), false);
  assert.equal(fs.readFileSync(log, "utf8"), `${JSON.stringify([marker, "--goto", "x:1"])}\n`);
});

test("editor settings round-trip, and a damaged file resets to vscode", () => {
  const file = path.join(tmp, "editor.json");
  writeEditorSettings(file, { editor: "cursor", template: "keep {file}" });
  assert.deepEqual(readEditorSettings(file), { editor: "cursor", template: "keep {file}" });
  fs.writeFileSync(file, "{");
  assert.deepEqual(readEditorSettings(file), { editor: "vscode", template: "" });
  fs.writeFileSync(file, JSON.stringify({ editor: "emacs", template: "kept" }));
  assert.deepEqual(readEditorSettings(file), { editor: "vscode", template: "kept" });
});

test("the start screen names the vscode command", () => {
  const html = fs.readFileSync(path.join(__dirname, "../src/index.html"), "utf8");
  assert.match(html, /data-command="code --reuse-window \{project\} --goto \{file\}:\{line\}"/);
});

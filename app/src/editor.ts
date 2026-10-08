// Open one file in an editor. Same command shape as src/cbi/editor.py:
// split the template into argv first, then fill {project}, {file} and {line},
// so a path with spaces stays one argument. Nothing is run through a shell.
// A ref opens a worktree that already has that branch or commit, or a
// read-only snapshot from `git show`. Nothing is checked out.

import { execFileSync, spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

export const EDITORS = ["vscode", "cursor", "none"] as const;
export const TEMPLATES = {
  vscode: "code --reuse-window {project} --goto {file}:{line}",
  cursor: "cursor --reuse-window {project} --goto {file}:{line}",
};
export const NOT_CHECKED_OUT = "This file is not checked out.";
export const NOT_ON_DISK = "This file is not on disk.";
export const NOT_IN_COMMIT = "This file is not in that commit.";
export const OUTSIDE = "That path is outside the project.";
export const NO_EDITOR = "No editor is configured.";
export const BAD_COMMIT = "That commit is not a snapshot we can open.";
const SHA = /^[0-9a-fA-F]{40}$/;

const BIN_LABEL: Record<string, string> = { code: "VS Code", cursor: "Cursor" };
const MAC_APP: Record<string, string> = {
  code: "Visual Studio Code.app/Contents/Resources/app/bin/code",
  cursor: "Cursor.app/Contents/Resources/app/bin/cursor",
};

export class EditorError extends Error {
  code: number;
  constructor(message: string, code = 1) {
    super(message);
    this.code = code;
  }
}

export type EditorChoice = "vscode" | "cursor" | "none" | "custom";

export interface EditorSettings {
  editor: EditorChoice;
  template: string;
}

export function splitTemplate(template: string): string[] {
  if (!template || !template.trim()) throw new EditorError("The editor command is empty.", 2);
  const tokens: string[] = [];
  let buf = "";
  let quote: "'" | '"' | null = null;
  let escape = false;
  for (const ch of template) {
    if (escape) {
      buf += ch;
      escape = false;
      continue;
    }
    if (ch === "\\" && quote !== "'") {
      escape = true;
      continue;
    }
    if (quote) {
      if (ch === quote) quote = null;
      else buf += ch;
      continue;
    }
    if (ch === "'" || ch === '"') {
      quote = ch;
      continue;
    }
    if (/\s/.test(ch)) {
      if (buf) {
        tokens.push(buf);
        buf = "";
      }
      continue;
    }
    buf += ch;
  }
  if (escape) buf += "\\";
  if (quote) throw new EditorError("The editor command has an unclosed quote.", 2);
  if (buf) tokens.push(buf);
  if (!tokens.length) throw new EditorError("The editor command is empty.", 2);
  return tokens;
}

function subst(token: string, project: string, file: string, line: string): string {
  const keys: Array<[string, string]> = [["{project}", project], ["{file}", file], ["{line}", line]];
  let out = "";
  let i = 0;
  while (i < token.length) {
    const hit = keys.find(([key]) => token.startsWith(key, i));
    if (hit) {
      out += hit[1];
      i += hit[0].length;
    } else {
      out += token[i];
      i += 1;
    }
  }
  return out;
}

export function fillTemplate(template: string, project: string, file: string, line: number | null | undefined): string[] {
  const lineS = line ? String(line) : "1";
  return splitTemplate(template).map((token) => subst(token, String(project), String(file), lineS));
}

export function macCandidates(name: string, home: string): string[] {
  const rel = MAC_APP[name];
  if (!rel) return [];
  return [path.join("/Applications", rel), path.join(home, "Applications", rel)];
}

export function findProgram(name: string, opts: {
  pathEnv: string;
  home: string;
  isExecutable?: (file: string) => boolean;
}): string | null {
  const check = opts.isExecutable ?? defaultExecutable;
  for (const directory of (opts.pathEnv || "").split(path.delimiter)) {
    if (!directory) continue;
    const candidate = path.join(directory, name);
    if (check(candidate)) return candidate;
  }
  for (const candidate of macCandidates(name, opts.home)) {
    if (check(candidate)) return candidate;
  }
  return null;
}

function defaultExecutable(file: string): boolean {
  try {
    if (!fs.statSync(file).isFile()) return false;
    fs.accessSync(file, fs.constants.X_OK);
    return true;
  } catch {
    return false;
  }
}

export function resolveProgram(token: string, opts: {
  pathEnv: string;
  home: string;
  isExecutable?: (file: string) => boolean;
}): string {
  const check = opts.isExecutable ?? defaultExecutable;
  if (token.includes("/") || token.includes("\\")) {
    if (check(token)) return token;
    throw new EditorError(`The editor command was not found: ${token}`);
  }
  const found = findProgram(token, { ...opts, isExecutable: check });
  if (found) return found;
  const label = BIN_LABEL[token];
  if (label) throw new EditorError(`${label} was not found. Install it, or set a custom editor command.`);
  throw new EditorError(`The editor command was not found: ${token}`);
}

export function templateText(editor: string, template: string | null | undefined): string {
  if (template) return template;
  if (editor === "none") throw new EditorError(NO_EDITOR);
  if (editor === "vscode" || editor === "cursor") return TEMPLATES[editor];
  throw new EditorError(`Unknown editor ${editor}.`, 2);
}

export function commandArgv(editor: string, template: string | null | undefined, project: string, file: string, line: number, opts: {
  pathEnv?: string;
  home?: string;
  isExecutable?: (file: string) => boolean;
} = {}): string[] {
  const pathEnv = opts.pathEnv ?? process.env.PATH ?? "";
  const home = opts.home ?? os.homedir();
  const argv = fillTemplate(templateText(editor, template), project, file, line);
  argv[0] = resolveProgram(argv[0], { pathEnv, home, isExecutable: opts.isExecutable });
  return argv;
}

function canonical(file: string, follow: boolean): string {
  const abs = path.resolve(file);
  if (!follow) return abs;
  try {
    return fs.realpathSync(abs);
  } catch {
    const parent = path.dirname(abs);
    try {
      return path.join(fs.realpathSync(parent), path.basename(abs));
    } catch {
      return abs;
    }
  }
}

function inside(root: string, candidate: string): boolean {
  const rel = path.relative(root, candidate);
  return rel !== "" && !rel.startsWith(`..${path.sep}`) && rel !== ".." && !path.isAbsolute(rel);
}

export function safeParts(relPath: string): string[] {
  if (!relPath || relPath.includes("\0")) throw new EditorError("This item has no file.");
  const rel = relPath.trim().replace(/\\/g, "/");
  if (!rel || rel.startsWith("/") || (rel.length >= 2 && rel[1] === ":")) throw new EditorError(OUTSIDE);
  const parts: string[] = [];
  for (const part of rel.split("/")) {
    if (part === "" || part === ".") continue;
    if (part === "..") throw new EditorError(OUTSIDE);
    parts.push(part);
  }
  if (!parts.length) throw new EditorError("This item has no file.");
  return parts;
}

function lineNumber(line: number | null | undefined): number {
  return line && line > 0 ? line : 1;
}

export function resolveTarget(relPath: string, line: number | null | undefined, opts: {
  project: string;
  worktree: string;
  ref: boolean;
  exists?: (file: string) => boolean;
}): { project: string; file: string; line: number } {
  const parts = safeParts(relPath);
  const root = canonical(opts.worktree, opts.exists == null);
  const candidate = canonical(path.resolve(root, ...parts), opts.exists == null);
  if (!inside(root, candidate)) throw new EditorError(OUTSIDE);
  const number = lineNumber(line);
  const check = opts.exists ?? ((file: string) => {
    try { return fs.statSync(file).isFile(); } catch { return false; }
  });
  if (check(candidate)) return { project: canonical(opts.project, opts.exists == null), file: candidate, line: number };
  throw new EditorError(opts.ref ? NOT_CHECKED_OUT : NOT_ON_DISK);
}

export interface WorktreeRow {
  path: string;
  branch: string | null;
  head: string;
}

export function commitSha(sha: string): string {
  if (!SHA.test(sha || "")) throw new EditorError(BAD_COMMIT);
  return sha.toLowerCase();
}

export function snapshotComponent(text: string): string {
  let raw = String(text || "").replace(/\\/g, "-");
  while (raw.includes("..")) raw = raw.replaceAll("..", ".");
  raw = raw.replace(/\//g, "-");
  const cleaned = raw.replace(/[^A-Za-z0-9._+-]+/g, "-").replace(/^[.-]+|[.-]+$/g, "");
  return (cleaned || "ref").slice(0, 80);
}

export function snapshotNotice(branch: string, sha: string): string {
  const label = branch || sha.slice(0, 12);
  return `Opened a read-only copy from ${label} (${sha.slice(0, 7)}); not checked out locally.`;
}

export function snapshotCache(cacheDir?: string | null, home?: string): string {
  if (cacheDir) return cacheDir;
  if (process.env.CBI_SNAPSHOT_DIR) return process.env.CBI_SNAPSHOT_DIR;
  return path.join(home ?? os.homedir(), "Library", "Caches", "codebase-inspector", "snapshots");
}

export function parseWorktrees(text: string): WorktreeRow[] {
  const items: WorktreeRow[] = [];
  let cur: WorktreeRow | null = null;
  for (const line of (text || "").split("\n")) {
    if (line.startsWith("worktree ")) {
      if (cur?.head) items.push(cur);
      cur = { path: line.slice("worktree ".length), branch: null, head: "" };
    } else if (line.startsWith("HEAD ") && cur) {
      cur.head = line.slice("HEAD ".length);
    } else if (line.startsWith("branch ") && cur) {
      cur.branch = line.slice("branch ".length).replace(/^refs\/heads\//, "");
    } else if (line === "detached" && cur) {
      cur.branch = null;
    }
  }
  if (cur?.head) items.push(cur);
  return items;
}

function gitWorktrees(repo: string): WorktreeRow[] {
  try {
    const out = execFileSync("git", ["-C", repo, "worktree", "list", "--porcelain"], { encoding: "utf8" });
    return parseWorktrees(out);
  } catch {
    throw new EditorError("Could not list worktrees.");
  }
}

function gitShowBlob(repo: string, sha: string, rel: string): Buffer {
  try {
    return execFileSync("git", ["-C", repo, "--no-pager", "show", "--no-textconv", `${sha}:${rel}`], {
      maxBuffer: 64 * 1024 * 1024,
    });
  } catch {
    throw new EditorError(NOT_IN_COMMIT);
  }
}

export function repoSnapshotName(repo: string): string {
  try {
    const common = execFileSync("git", ["-C", repo, "rev-parse", "--path-format=absolute", "--git-common-dir"], { encoding: "utf8" }).trim();
    const dir = path.resolve(common);
    if (path.basename(dir) === ".git") {
      const name = path.basename(path.dirname(dir));
      if (name) return snapshotComponent(name);
    }
  } catch { /* a path that is not a repo keeps its folder name */ }
  return snapshotComponent(path.basename(repo));
}

function rankedWorktrees(entries: WorktreeRow[], branch: string, sha: string): WorktreeRow[] {
  const branchHits: WorktreeRow[] = [];
  const commitHits: WorktreeRow[] = [];
  for (const item of entries) {
    if (branch && item.branch === branch) branchHits.push(item);
    else if ((item.head || "").toLowerCase() === sha) commitHits.push(item);
  }
  return branchHits.concat(commitHits);
}

function contained(root: string, candidate: string): string {
  const base = path.resolve(root);
  const file = path.resolve(candidate);
  const rel = path.relative(base, file);
  if (!rel || rel === ".." || rel.startsWith(`..${path.sep}`) || path.isAbsolute(rel)) throw new EditorError(OUTSIDE);
  return file;
}

export function materializeSnapshot(repo: string, parts: string[], sha: string, branch: string, opts: {
  cacheDir?: string | null;
  home?: string;
  showBlob?: (repo: string, sha: string, rel: string) => Buffer;
} = {}): { folder: string; file: string; reused: boolean } {
  const rel = parts.join("/");
  const folder = path.join(snapshotCache(opts.cacheDir, opts.home), `${repoSnapshotName(repo)}@${snapshotComponent(branch)}-${sha.slice(0, 12)}`);
  const dest = contained(folder, path.resolve(folder, ...parts));
  if (fs.existsSync(dest) || isLink(dest)) {
    const st = fs.lstatSync(dest);
    if (st.isSymbolicLink() || !st.isFile()) throw new EditorError(OUTSIDE);
    return { folder: path.resolve(folder), file: dest, reused: true };
  }
  const data = (opts.showBlob ?? gitShowBlob)(repo, sha, rel);
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  const tmp = `${dest}.cbi-tmp`;
  if (isLink(tmp) || fs.existsSync(tmp)) fs.unlinkSync(tmp);
  const fd = fs.openSync(tmp, "wx", 0o644);
  try {
    fs.writeFileSync(fd, data);
  } finally {
    fs.closeSync(fd);
  }
  fs.chmodSync(tmp, 0o444);
  fs.renameSync(tmp, dest);
  return { folder: path.resolve(folder), file: dest, reused: false };
}

function isLink(file: string): boolean {
  try { return fs.lstatSync(file).isSymbolicLink(); } catch { return false; }
}

export function resolveRefTarget(relPath: string, line: number | null | undefined, opts: {
  repo: string;
  branch: string;
  sha: string;
  cacheDir?: string | null;
  home?: string;
  listWorktrees?: (repo: string) => WorktreeRow[];
  showBlob?: (repo: string, sha: string, rel: string) => Buffer;
  exists?: (file: string) => boolean;
}): { project: string; file: string; line: number; notice: string | null } {
  const parts = safeParts(relPath);
  const number = lineNumber(line);
  const sha = commitSha(opts.sha);
  const rel = parts.join("/");
  const entries = (opts.listWorktrees ?? gitWorktrees)(opts.repo);
  for (const item of rankedWorktrees(entries, opts.branch || "", sha)) {
    try {
      const opened = resolveTarget(rel, number, {
        project: item.path, worktree: item.path, ref: false, exists: opts.exists,
      });
      return { ...opened, notice: null };
    } catch (err) {
      if (err instanceof EditorError && err.message === NOT_ON_DISK) continue;
      throw err;
    }
  }
  const snap = materializeSnapshot(opts.repo, parts, sha, opts.branch || sha.slice(0, 12), opts);
  return { project: snap.folder, file: snap.file, line: number, notice: snapshotNotice(opts.branch, sha) };
}

/** Branch name and commit for a ref view. A worktree open is not a ref. */
export function refEditorContext(target: { kind: string; name?: string; head?: string; label?: string }): { ref: boolean; branch: string; sha: string } {
  if (target.kind === "worktree") return { ref: false, branch: "", sha: "" };
  const sha = typeof target.head === "string" ? target.head : "";
  let branch = "";
  if ((target.kind === "branch" || target.kind === "remote") && target.name) branch = target.name;
  else if (target.kind === "compare" && target.label && !target.label.includes("..")) branch = target.label;
  return { ref: true, branch, sha };
}

/** Where the editor looks. A worktree opens that checkout. Anything else is a ref. */
export function rootsFor(project: string, targetKind: string, targetPath: string | null): { project: string; worktree: string; ref: boolean } {
  if (targetKind === "worktree" && targetPath) return { project: targetPath, worktree: targetPath, ref: false };
  return { project, worktree: project, ref: true };
}

export function planViewerOpen(opts: {
  file: string;
  line?: number;
  project: string;
  targetKind: string;
  targetPath: string | null;
  editor: string;
  template: string | null;
  pathEnv?: string;
  home?: string;
  isExecutable?: (file: string) => boolean;
  exists?: (file: string) => boolean;
  repo?: string;
  branch?: string;
  sha?: string;
  cacheDir?: string | null;
  listWorktrees?: (repo: string) => WorktreeRow[];
  showBlob?: (repo: string, sha: string, rel: string) => Buffer;
}): { ok: true; argv: string[]; notice?: string } | { ok: false; error: string } {
  const roots = rootsFor(opts.project, opts.targetKind, opts.targetPath);
  try {
    if (opts.editor === "none") throw new EditorError(NO_EDITOR);
    if (opts.editor === "custom" && (!opts.template || !opts.template.includes("{file}"))) {
      throw new EditorError("The editor command must include {file}.", 2);
    }
    const template = opts.editor === "custom" ? opts.template : null;
    if (roots.ref) {
      const target = resolveRefTarget(opts.file, opts.line ?? 1, {
        repo: opts.repo || opts.project,
        branch: opts.branch || "",
        sha: opts.sha || "",
        cacheDir: opts.cacheDir,
        home: opts.home,
        listWorktrees: opts.listWorktrees,
        showBlob: opts.showBlob,
        exists: opts.exists,
      });
      const argv = commandArgv(opts.editor, template, target.project, target.file, target.line, {
        pathEnv: opts.pathEnv, home: opts.home, isExecutable: opts.isExecutable,
      });
      return target.notice ? { ok: true, argv, notice: target.notice } : { ok: true, argv };
    }
    const target = resolveTarget(opts.file, opts.line ?? 1, {
      project: roots.project, worktree: roots.worktree, ref: false, exists: opts.exists,
    });
    const argv = commandArgv(opts.editor, template, target.project, target.file, target.line, {
      pathEnv: opts.pathEnv, home: opts.home, isExecutable: opts.isExecutable,
    });
    return { ok: true, argv };
  } catch (err) {
    if (err instanceof EditorError) return { ok: false, error: err.message };
    throw err;
  }
}

/** Start argv detached. No shell. `CBI_EDITOR_DRY_RUN` records argv and does not spawn. */
export function launchEditor(argv: string[]) {
  const dry = process.env.CBI_EDITOR_DRY_RUN;
  if (dry) {
    fs.appendFileSync(dry, `${JSON.stringify(argv)}\n`);
    return;
  }
  const child = spawn(argv[0], argv.slice(1), { detached: true, stdio: "ignore", shell: false });
  child.unref();
}

export function readEditorSettings(file: string): EditorSettings {
  try {
    const parsed = JSON.parse(fs.readFileSync(file, "utf8")) as { editor?: unknown; template?: unknown };
    const template = typeof parsed.template === "string" ? parsed.template : "";
    const editor = parsed.editor;
    if (editor === "vscode" || editor === "cursor" || editor === "none" || editor === "custom") {
      return { editor, template };
    }
    return { editor: "vscode", template };
  } catch {
    return { editor: "vscode", template: "" };
  }
}

export function writeEditorSettings(file: string, settings: EditorSettings) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const tmp = `${file}.tmp`;
  fs.writeFileSync(tmp, `${JSON.stringify({ editor: settings.editor, template: settings.template }, null, 2)}\n`);
  fs.renameSync(tmp, file);
}

export function normalizeChoice(editor: string, template: string): EditorSettings {
  if (editor === "custom") {
    if (!template.includes("{file}")) throw new EditorError("The editor command must include {file}.", 2);
    splitTemplate(template);
    return { editor, template };
  }
  if (editor === "vscode" || editor === "cursor" || editor === "none") return { editor, template };
  throw new EditorError(`Unknown editor ${editor}.`, 2);
}

export function describeEditor(settings: EditorSettings): { editor: EditorChoice; template: string; command: string } {
  const command = settings.editor === "custom" ? settings.template
    : settings.editor === "none" ? ""
    : TEMPLATES[settings.editor];
  return { editor: settings.editor, template: settings.template, command };
}

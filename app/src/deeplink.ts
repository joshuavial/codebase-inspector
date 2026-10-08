import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { allowedGhArgs, parsePrOids, prViewArgs } from "./compare";
import { realGit, resolveProject, type GitResult, type GitRunner } from "./project";
import { commandExecutable } from "./which";

export type GhRunner = (cwd: string, args: string[]) => GitResult;

const SEGMENT = /^[A-Za-z0-9][A-Za-z0-9._:+-]*$/;
const QUAL_PART = /^[A-Za-z0-9][A-Za-z0-9 ._+~-]*$/;
const REF = /^[A-Za-z0-9][A-Za-z0-9._/@~^{}-]*$/;
const COMPARE = /^([A-Za-z0-9][A-Za-z0-9._/@~^{}-]*)\.\.([A-Za-z0-9][A-Za-z0-9._/@~^{}-]*)$/;
const PR = /^[1-9][0-9]{0,8}$/;

export interface OpenQuery {
  repo: string;
  ref: string | null;
  node: string | null;
  compare: { base: string; head: string } | null;
  pr: string | null;
}

export interface Opened {
  project: string;
  cwd: string;
  branch: string;
  refArgs: string[];
  viewerIndex: string;
  watch: boolean;
  node: string | null;
  /** Set when the link is a comparison. base and head are the link text; the shas are what resolved. */
  compare: { base: string; head: string; baseSha: string; headSha: string } | null;
}

export type OpenResult = { ok: true; opened: Opened } | { ok: false; error: string };

/** True when value is a concept id or a structured node id. Shell metacharacters and ".." are refused. */
export function validNodeId(value: string): boolean {
  if (!value || value.length > 512) return false;
  if (value.includes("..") || value.includes("//") || [...value].some((ch) => ch.charCodeAt(0) < 32 || ch.charCodeAt(0) === 127)) {
    return false;
  }
  const hash = value.indexOf("#");
  const head = hash === -1 ? value : value.slice(0, hash);
  const tail = hash === -1 ? null : value.slice(hash + 1);
  if (tail !== null && !validQual(tail)) return false;
  if (!head || head.includes(" ") || head.startsWith("/") || head.startsWith("-")) return false;
  if (head.startsWith("local:")) {
    const body = head.slice("local:".length);
    const colon = body.indexOf(":");
    const dirname = colon === -1 ? body : body.slice(0, colon);
    const rest = colon === -1 ? "" : body.slice(colon + 1);
    if (!SEGMENT.test(dirname)) return false;
    return colon === -1 || validPath(rest);
  }
  const colon = head.indexOf(":");
  const workspace = colon === -1 ? head : head.slice(0, colon);
  const rest = colon === -1 ? "" : head.slice(colon + 1);
  const parts = workspace.split("/");
  if (parts.length === 0 || parts.some((part) => !SEGMENT.test(part))) return false;
  if (colon !== -1) return parts.length >= 3 && validPath(rest);
  return true;
}

export function viewerLocation(node: string | null, previousHash: string | null): string {
  const params = new URLSearchParams();
  if (node) {
    if (node.includes("#")) params.set("s", node);
    else params.set("c", node);
  }
  if (previousHash !== null) {
    params.set("from", "~");
    const bare = previousHash.replace(/^#/, "");
    params.set("bh", bare || "-");
  }
  return params.toString();
}

export function linkFromArgv(argv: readonly string[]): string | null {
  return argv.find((arg) => arg.startsWith("cbi://")) ?? null;
}

/** The only git commands a link is allowed to run. All of them are read-only. */
export function allowedGitArgs(args: readonly string[]): boolean {
  if (args[0] === "rev-parse" && args[1] === "--verify" && args[2] === "--end-of-options" && args.length === 4) return true;
  const line = args.join(" ");
  return line === "rev-parse --path-format=absolute --show-toplevel"
    || line === "rev-parse --show-toplevel"
    || line === "rev-parse --abbrev-ref HEAD";
}

/** Absolute on the platform the link was built for. `path.isAbsolute` follows the host. */
export function isAbsolutePath(value: string, platform: string = process.platform): boolean {
  return (platform === "win32" ? path.win32 : path.posix).isAbsolute(value);
}

export function parseOpenUrl(raw: string, platform: string = process.platform): { ok: true; query: OpenQuery } | { ok: false; error: string } {
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    return { ok: false, error: "That link is not a cbi:// URL." };
  }
  if (url.protocol !== "cbi:" || url.hostname !== "open" || (url.pathname !== "" && url.pathname !== "/")) {
    return { ok: false, error: "That link is not a cbi://open URL." };
  }
  const allowed = new Set(["repo", "ref", "node", "compare", "pr"]);
  for (const key of url.searchParams.keys()) {
    if (!allowed.has(key)) return { ok: false, error: `Unknown parameter ${key}.` };
  }
  const repo = one(url, "repo");
  const ref = one(url, "ref");
  const node = one(url, "node");
  const compare = one(url, "compare");
  const pr = one(url, "pr");
  if (repo === "dup" || ref === "dup" || node === "dup" || compare === "dup" || pr === "dup") {
    return { ok: false, error: "That link repeats a parameter." };
  }
  if (!repo) return { ok: false, error: "The link needs a repo path." };
  if (repo.includes("\0") || repo.includes("\n") || hasDotDot(repo)) return { ok: false, error: "That path is not allowed." };
  if (!isAbsolutePath(repo, platform)) return { ok: false, error: "The repo path must be absolute." };
  if (ref !== null && (ref.includes("\0") || ref.includes("\n") || hasDotDot(ref))) {
    return { ok: false, error: "That path is not allowed." };
  }
  if (ref !== null && ref !== "" && !isAbsolutePath(ref, platform) && !safeRef(ref)) return { ok: false, error: `unknown ref ${ref}` };
  if (ref === "") return { ok: false, error: "unknown ref" };
  let compareSides: { base: string; head: string } | null = null;
  if (compare !== null) {
    if (compare.includes("...")) return { ok: false, error: "compare must be base..head" };
    const match = COMPARE.exec(compare);
    if (!match || match[0] !== compare) return { ok: false, error: "compare must be base..head" };
    compareSides = { base: match[1], head: match[2] };
  }
  if (pr !== null && !PR.test(pr)) return { ok: false, error: "pr must be a pull request number" };
  if (node !== null && !validNodeId(node)) return { ok: false, error: "That node id is not valid." };
  if (compareSides && pr !== null) return { ok: false, error: "pass compare or pr, not both" };
  if (compareSides && ref !== null) return { ok: false, error: "pass compare or a ref, not both" };
  if (pr !== null && ref !== null) return { ok: false, error: "pass pr or a ref, not both" };
  return { ok: true, query: { repo, ref, node, compare: compareSides, pr } };
}

/** `gh pr view`. Fixed argv, read-only. A missing gh is an error, not a guessed range. */
export function realGh(cwd: string, args: string[]): GitResult {
  if (!allowedGhArgs(args)) throw new Error(`refusing gh ${args.join(" ")}`);
  try {
    const stdout = execFileSync(commandExecutable("gh"), args, {
      cwd,
      shell: false,
      encoding: "utf8",
      timeout: 20_000,
      maxBuffer: 1024 * 1024,
      stdio: ["ignore", "pipe", "pipe"],
    });
    return { code: 0, stdout, stderr: "" };
  } catch (err) {
    const error = err as NodeJS.ErrnoException & { status?: number; stdout?: string; stderr?: string };
    if (error.code === "ENOENT") return { code: 127, stdout: "", stderr: "gh is not on PATH" };
    return { code: error.status ?? 1, stdout: error.stdout ?? "", stderr: error.stderr ?? error.message };
  }
}

export function validateOpen(raw: string, git: GitRunner = realGit, gh: GhRunner = realGh): OpenResult {
  const parsed = parseOpenUrl(raw);
  if (!parsed.ok) return parsed;
  const { query } = parsed;
  const resolved = resolveProject(query.repo, git);
  if (!resolved.ok) return resolved;
  const here = toplevel(query.repo, git) ?? resolved.main;
  if (query.compare || query.pr) return openComparison(resolved.main, query, git, gh);
  const ref = query.ref ?? query.repo;
  if (path.isAbsolute(ref)) {
    const other = resolveProject(ref, git);
    if (!other.ok || other.main !== resolved.main) {
      return { ok: false, error: "That path is not a worktree of this repository." };
    }
    const cwd = toplevel(ref, git);
    if (!cwd) return { ok: false, error: "That path is not a worktree of this repository." };
    return {
      ok: true,
      opened: {
        project: resolved.main,
        cwd,
        branch: branchOf(cwd, git),
        refArgs: [],
        viewerIndex: path.join(cwd, ".cbi", "viewer", "index.html"),
        watch: true,
        node: query.node,
        compare: null,
      },
    };
  }
  const checked = verify(here, ref, git);
  if (!checked.ok) return checked;
  const label = /^[0-9a-f]{40}$/.test(ref) ? checked.sha.slice(0, 12) : ref;
  return {
    ok: true,
    opened: {
      project: resolved.main,
      cwd: here,
      branch: label,
      refArgs: ["--ref", ref],
      viewerIndex: path.join(here, ".cbi", "refs", checked.sha, "viewer", "index.html"),
      watch: false,
      node: query.node,
      compare: null,
    },
  };
}

function openComparison(project: string, query: OpenQuery, git: GitRunner, gh: GhRunner): OpenResult {
  let base = query.compare?.base ?? "";
  let head = query.compare?.head ?? "";
  if (query.pr) {
    const args = prViewArgs(query.pr);
    if (!args) return { ok: false, error: "pr must be a pull request number" };
    let result: GitResult;
    try {
      result = gh(project, args);
    } catch (err) {
      return { ok: false, error: err instanceof Error ? err.message : String(err) };
    }
    if (result.code === 127) return { ok: false, error: result.stderr.trim() || "gh is not on PATH" };
    if (result.code !== 0) {
      const detail = (result.stderr || result.stdout).trim();
      return { ok: false, error: detail || "gh failed" };
    }
    const oids = parsePrOids(result.stdout);
    if (!oids.ok) return oids;
    base = oids.base;
    head = oids.head;
  }
  const baseCommit = verify(project, base, git);
  if (!baseCommit.ok) return baseCommit;
  const headCommit = verify(project, head, git);
  if (!headCommit.ok) return headCommit;
  return {
    ok: true,
    opened: {
      project,
      cwd: project,
      branch: "",
      refArgs: [],
      viewerIndex: path.join(project, ".cbi", "viewer", "index.html"),
      watch: false,
      node: query.node,
      compare: { base, head, baseSha: baseCommit.sha, headSha: headCommit.sha },
    },
  };
}

function validPath(value: string): boolean {
  if (!value) return false;
  const parts = value.split("/");
  if (parts[parts.length - 1] === "") parts.pop();
  return parts.length > 0 && parts.every((part) => SEGMENT.test(part));
}

function validQual(tail: string): boolean {
  if (!tail || tail.startsWith(" ") || tail.endsWith(" ")) return false;
  const parts = tail.split(" > ");
  if (parts.join(" > ") !== tail) return false;
  return parts.every((part) => QUAL_PART.test(part) && !part.includes("  ") && !part.startsWith(" ") && !part.endsWith(" "));
}

function hasDotDot(value: string): boolean {
  return value.split(/[/\\]/).includes("..");
}

function safeRef(value: string): boolean {
  return REF.test(value) && !value.includes("..");
}

function one(url: URL, key: string): string | null | "dup" {
  const all = url.searchParams.getAll(key);
  if (all.length > 1) return "dup";
  return all.length === 0 ? null : all[0];
}

function runGit(cwd: string, args: string[], git: GitRunner) {
  if (!allowedGitArgs(args)) throw new Error(`refusing git ${args.join(" ")}`);
  return git(cwd, args);
}

function text(stdout: string): string {
  return stdout.trim();
}

function gitCwd(input: string): string {
  try {
    if (fs.statSync(input).isFile()) return path.dirname(input);
  } catch {
    return input;
  }
  return input;
}

function toplevel(input: string, git: GitRunner): string | null {
  const folder = gitCwd(input);
  let result = runGit(folder, ["rev-parse", "--path-format=absolute", "--show-toplevel"], git);
  if (result.code !== 0) result = runGit(folder, ["rev-parse", "--show-toplevel"], git);
  const found = text(result.stdout);
  if (result.code !== 0 || !found) return null;
  const resolved = path.resolve(found);
  try {
    return fs.realpathSync(resolved);
  } catch {
    return resolved;
  }
}

function branchOf(cwd: string, git: GitRunner): string {
  const result = runGit(cwd, ["rev-parse", "--abbrev-ref", "HEAD"], git);
  const raw = text(result.stdout);
  if (result.code !== 0 || raw === "" || raw === "HEAD") return "detached";
  return raw;
}

export function verifyRef(cwd: string, ref: string, git: GitRunner = realGit): { ok: true; sha: string } | { ok: false; error: string } {
  return verify(cwd, ref, git);
}

function verify(cwd: string, ref: string, git: GitRunner): { ok: true; sha: string } | { ok: false; error: string } {
  if (!safeRef(ref)) return { ok: false, error: `unknown ref ${ref}` };
  const result = runGit(cwd, ["rev-parse", "--verify", "--end-of-options", `${ref}^{commit}`], git);
  if (result.code === 127) return { ok: false, error: result.stderr || "git was not found on PATH." };
  const sha = text(result.stdout);
  if (result.code !== 0 || !sha) return { ok: false, error: `unknown ref ${ref}` };
  return { ok: true, sha };
}

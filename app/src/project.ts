import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { commandExecutable, missingGit } from "./which";

export interface GitResult {
  code: number;
  stdout: string;
  stderr: string;
}

export type GitRunner = (cwd: string, args: string[]) => GitResult;

/** The only git invocations the app makes. All of them are read-only. */
export const GIT_ARGV = [
  ["rev-parse", "--is-bare-repository"],
  ["rev-parse", "--path-format=absolute", "--git-common-dir"],
  ["rev-parse", "--git-common-dir"],
  ["config", "--get", "core.worktree"],
  ["rev-parse", "--path-format=absolute", "--show-toplevel"],
  ["rev-parse", "--show-toplevel"],
  ["rev-parse", "--abbrev-ref", "HEAD"],
] as const;

const NOT_A_REPO = "This folder is not inside a git repository.";
const BARE = "This is a bare repository, so there is no working tree to map.";
const NO_WORKTREE = "This repository has no working tree to map.";
const NO_GIT = missingGit();

export type ResolveResult =
  | { ok: true; main: string; branch: string }
  | { ok: false; error: string };

export function realGit(cwd: string, args: string[]): GitResult {
  try {
    const stdout = execFileSync(commandExecutable("git"), args, {
      cwd,
      shell: false,
      encoding: "utf8",
      timeout: 15_000,
      maxBuffer: 1024 * 1024,
      stdio: ["ignore", "pipe", "pipe"],
    });
    return { code: 0, stdout, stderr: "" };
  } catch (err) {
    const error = err as NodeJS.ErrnoException & { status?: number; stdout?: string; stderr?: string };
    if (error.code === "ENOENT") return { code: 127, stdout: "", stderr: NO_GIT };
    return { code: error.status ?? 1, stdout: error.stdout ?? "", stderr: error.stderr ?? error.message };
  }
}

function allowed(args: string[]): boolean {
  return GIT_ARGV.some((expected) => expected.length === args.length && expected.every((part, i) => part === args[i]));
}

function runGit(cwd: string, args: readonly string[], git: GitRunner): GitResult {
  const list = [...args];
  if (!allowed(list)) throw new Error(`refusing git ${list.join(" ")}`);
  return git(cwd, list);
}

function text(result: GitResult): string {
  return result.stdout.trim();
}

/**
 * The repository's main worktree for a folder or a file inside one.
 * `git rev-parse --git-common-dir` is the parent of a normal checkout and of
 * every linked worktree. Submodules and separate git dirs keep the working
 * tree in core.worktree, falling back to this checkout's top level.
 */
export function resolveProject(
  input: string,
  git: GitRunner = realGit,
  realpath: (file: string) => string = fs.realpathSync,
): ResolveResult {
  let folder = input;
  try {
    const st = fs.statSync(input);
    if (st.isFile()) folder = path.dirname(input);
    else if (!st.isDirectory()) return { ok: false, error: NOT_A_REPO };
  } catch (err) {
    const code = (err as NodeJS.ErrnoException).code;
    return { ok: false, error: code === "ENOENT" ? "That folder does not exist." : "That folder could not be opened." };
  }

  const bare = runGit(folder, ["rev-parse", "--is-bare-repository"], git);
  if (bare.code === 127) return { ok: false, error: NO_GIT };
  if (bare.code !== 0) return { ok: false, error: NOT_A_REPO };
  if (text(bare) === "true") return { ok: false, error: BARE };

  let common = runGit(folder, ["rev-parse", "--path-format=absolute", "--git-common-dir"], git);
  if (common.code !== 0) common = runGit(folder, ["rev-parse", "--git-common-dir"], git);
  if (common.code !== 0 || !text(common)) return { ok: false, error: NOT_A_REPO };
  let commonDir = text(common);
  if (!path.isAbsolute(commonDir)) commonDir = path.resolve(folder, commonDir);

  let main: string;
  if (path.basename(commonDir) === ".git") {
    main = path.dirname(commonDir);
  } else {
    const worktree = runGit(folder, ["config", "--get", "core.worktree"], git);
    if (worktree.code === 0 && text(worktree)) {
      main = path.resolve(commonDir, text(worktree));
    } else {
      let top = runGit(folder, ["rev-parse", "--path-format=absolute", "--show-toplevel"], git);
      if (top.code !== 0) top = runGit(folder, ["rev-parse", "--show-toplevel"], git);
      if (top.code !== 0 || !text(top)) return { ok: false, error: NO_WORKTREE };
      main = text(top);
      if (!path.isAbsolute(main)) main = path.resolve(folder, main);
    }
  }

  try {
    main = realpath(main);
  } catch {
    return { ok: false, error: "The repository working tree does not exist." };
  }

  const branchRun = runGit(main, ["rev-parse", "--abbrev-ref", "HEAD"], git);
  if (branchRun.code !== 0) return { ok: false, error: NOT_A_REPO };
  const raw = text(branchRun);
  return { ok: true, main, branch: raw === "HEAD" || raw === "" ? "detached" : raw };
}

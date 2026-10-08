import path from "node:path";
import { usableRef, type Inventory } from "./switcher";

/** `gh pr view <n> --json` fields. Both are required; nothing is filled in. */
export const PR_JSON = "baseRefOid,headRefOid";

const PR = /^[1-9][0-9]{0,8}$/;
const REF = /^[A-Za-z0-9][A-Za-z0-9._/@~^{}-]*$/;
const SHA = /^[0-9a-f]{40}$/;

export interface SideChoice {
  kind: "worktree" | "branch" | "commit";
  value: string;
}

export interface CompareForm {
  base: SideChoice | null;
  head: SideChoice | null;
  pr: string;
}

export interface ResolvedSide {
  /** Git ref passed to rev-parse. A worktree or branch is its current commit. */
  ref: string;
  label: string;
}

export type ComparePlan =
  | { ok: true; mode: "pr"; number: string }
  | { ok: true; mode: "refs"; base: ResolvedSide; head: ResolvedSide }
  | { ok: false; error: string };

export function isCommitSha(value: string): boolean {
  return SHA.test(value);
}

/** A ref we will pass to `git rev-parse --verify`. `..` is a range, not a name. */
export function safeRef(value: string): boolean {
  return REF.test(value) && !value.includes("..");
}

export function prViewArgs(number: string): string[] | null {
  if (!PR.test(number)) return null;
  return ["pr", "view", number, "--json", PR_JSON];
}

/** The only gh command a comparison may run. It is read-only. */
export function allowedGhArgs(args: readonly string[]): boolean {
  if (args.length !== 5) return false;
  const expected = prViewArgs(args[2]);
  return expected !== null && expected.every((part, index) => part === args[index]);
}

/**
 * baseRefOid and headRefOid from `gh pr view --json`.
 * A missing field, a branch name, or anything that is not a commit sha is an error.
 */
export function parsePrOids(stdout: string): { ok: true; base: string; head: string } | { ok: false; error: string } {
  let data: unknown;
  try {
    data = JSON.parse(stdout);
  } catch {
    return { ok: false, error: "gh pr view did not return JSON" };
  }
  if (!data || typeof data !== "object" || Array.isArray(data)) {
    return { ok: false, error: "gh pr view did not return baseRefOid and headRefOid" };
  }
  const record = data as Record<string, unknown>;
  const base = record.baseRefOid;
  const head = record.headRefOid;
  if (typeof base !== "string" || !isCommitSha(base) || typeof head !== "string" || !isCommitSha(head)) {
    return { ok: false, error: "gh pr view did not return baseRefOid and headRefOid" };
  }
  return { ok: true, base, head };
}

export function readCompareForm(value: unknown): CompareForm | null {
  if (!value || typeof value !== "object") return null;
  const item = value as Record<string, unknown>;
  const pr = typeof item.pr === "string" ? item.pr.trim() : "";
  return { base: readSide(item.base), head: readSide(item.head), pr };
}

/**
 * A pull request number, when present, is the whole comparison.
 * Otherwise both sides are required. A worktree or branch side is the commit
 * it has checked out, not its uncommitted files.
 */
export function planCompare(form: CompareForm, inventory: Inventory | null): ComparePlan {
  const pr = form.pr.trim();
  if (pr) {
    if (!PR.test(pr)) return { ok: false, error: "pr must be a pull request number" };
    return { ok: true, mode: "pr", number: pr };
  }
  if (!form.base || !form.head) return { ok: false, error: "Choose two sides." };
  const base = resolveSide(form.base, inventory);
  if ("error" in base) return { ok: false, error: base.error };
  const head = resolveSide(form.head, inventory);
  if ("error" in head) return { ok: false, error: head.error };
  return { ok: true, mode: "refs", base, head };
}

function readSide(value: unknown): SideChoice | null {
  if (!value || typeof value !== "object") return null;
  const item = value as Record<string, unknown>;
  if (item.kind !== "worktree" && item.kind !== "branch" && item.kind !== "commit") return null;
  if (typeof item.value !== "string") return null;
  return { kind: item.kind, value: item.value };
}

function resolveSide(side: SideChoice, inventory: Inventory | null): ResolvedSide | { error: string } {
  if (side.kind === "commit") {
    const rev = side.value.trim();
    if (!rev) return { error: "Enter a commit." };
    if (!safeRef(rev)) return { error: `unknown ref ${rev}` };
    return { ref: rev, label: isCommitSha(rev) ? rev.slice(0, 12) : rev };
  }
  if (!inventory) return { error: "Could not list worktrees." };
  if (side.kind === "worktree") {
    const found = inventory.worktrees.find((worktree) => path.resolve(worktree.path) === path.resolve(side.value));
    if (!found) return { error: `unknown worktree ${side.value}` };
    if (!isCommitSha(found.head)) return { error: `unknown ref ${found.head}` };
    return { ref: found.head, label: found.lane || found.branch || "detached" };
  }
  const branch = inventory.branches.find((item) => item.name === side.value);
  if (!branch || !usableRef(branch.name) || !isCommitSha(branch.head)) {
    return { error: side.value ? `unknown ref ${side.value}` : "Choose a branch." };
  }
  return { ref: branch.head, label: branch.name };
}

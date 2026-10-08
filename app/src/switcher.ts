import path from "node:path";

export interface WorktreeInfo {
  path: string;
  branch: string | null;
  head: string;
  lane: string | null;
  hasModel: boolean;
  modelComplete: boolean;
  current: boolean;
}

export interface BranchInfo {
  name: string;
  head: string;
  lane: string | null;
  hasRefModel: boolean;
  current: boolean;
}

export interface Inventory {
  worktrees: WorktreeInfo[];
  branches: BranchInfo[];
}

/** A remote-tracking branch, listed only after the user fetches. */
export interface RemoteRef {
  name: string;
  head: string;
}

export type Target =
  | { kind: "worktree"; path: string; branch: string | null; lane: string | null; head: string }
  | { kind: "branch"; name: string; head: string }
  | { kind: "remote"; name: string; head: string }
  | { kind: "compare"; base: string; head: string; label: string };

export interface SwitcherEntry {
  key: string;
  group: "worktree" | "branch" | "remote";
  label: string;
  detail: string;
  model: string;
  selected: boolean;
  target: Target;
}

export function samePath(a: string, b: string): boolean {
  return path.resolve(a) === path.resolve(b);
}

/** A ref we will pass as one argv element to `cbi --ref`. */
export function usableRef(name: string): boolean {
  if (!name || name.startsWith("-") || name.startsWith("/") || name.endsWith("/") || name.endsWith(".lock")) return false;
  if (name.includes("..") || name.includes("//") || name.includes("@{")) return false;
  return !/[\s\u0000-\u001f~^:?*[\\]/.test(name);
}

export function keyOf(target: Target): string {
  if (target.kind === "worktree") return `worktree:${target.path}`;
  if (target.kind === "branch") return `branch:${target.name}`;
  if (target.kind === "compare") return `compare:${target.base}..${target.head}`;
  return `remote:${target.name}`;
}

export function refOf(target: Target): string | null {
  if (target.kind === "branch" || target.kind === "remote") return target.name;
  return null;
}

export function readOnlyTarget(target: Target): boolean {
  return target.kind !== "worktree";
}

/** Git branch name shown in the top bar. Detached worktrees say "detached". */
export function branchOf(target: Target): string {
  if (target.kind === "worktree") return target.branch || "detached";
  if (target.kind === "compare") return "";
  return target.name;
}

/** Lane name for a worktree, the comparison label, otherwise the branch or remote ref. */
export function labelOf(target: Target): string {
  if (target.kind === "worktree") return target.lane || target.branch || "detached";
  if (target.kind === "compare") return target.label;
  return target.name;
}

/** `cbi prime` has no `--ref`. Tasks on a commit are reached with `cbi tasks --ref`. */
export function refInstruction(repo: string, ref: string): string {
  return `run \`cbi tasks --ref ${ref}\` in ${repo} and complete the tasks`;
}

export function formatScanned(iso: string | null, stale: boolean): string {
  const match = iso ? /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/.exec(iso) : null;
  let text = match ? `scanned ${match[1]} ${match[2]}` : iso ? "scanned" : "";
  if (stale) text = text ? `${text} · tasks waiting` : "tasks waiting";
  return text;
}

function textOrNull(value: unknown): string | null {
  return typeof value === "string" && value ? value : null;
}

function asWorktree(row: unknown): WorktreeInfo | null {
  if (!row || typeof row !== "object") return null;
  const item = row as Record<string, unknown>;
  if (typeof item.path !== "string" || !item.path) return null;
  if (typeof item.head !== "string" || !item.head) return null;
  return {
    path: item.path,
    branch: textOrNull(item.branch),
    head: item.head,
    lane: textOrNull(item.lane),
    hasModel: item.has_model === true,
    modelComplete: item.model_complete === true,
    current: item.current === true,
  };
}

function asBranch(row: unknown): BranchInfo | null {
  if (!row || typeof row !== "object") return null;
  const item = row as Record<string, unknown>;
  if (typeof item.name !== "string" || !item.name) return null;
  if (typeof item.head !== "string" || !item.head) return null;
  return {
    name: item.name,
    head: item.head,
    lane: textOrNull(item.lane),
    hasRefModel: item.has_ref_model === true,
    current: item.current === true,
  };
}

/** `cbi worktrees --json`. Null when the payload is not that object. */
export function parseInventory(text: string): Inventory | null {
  try {
    const parsed = JSON.parse(text) as { worktrees?: unknown; branches?: unknown };
    if (!parsed || typeof parsed !== "object" || !Array.isArray(parsed.worktrees) || !Array.isArray(parsed.branches)) return null;
    return {
      worktrees: parsed.worktrees.map(asWorktree).filter((row): row is WorktreeInfo => row !== null),
      branches: parsed.branches.map(asBranch).filter((row): row is BranchInfo => row !== null),
    };
  } catch {
    return null;
  }
}

export function worktreeTarget(worktree: WorktreeInfo): Target {
  return {
    kind: "worktree",
    path: worktree.path,
    branch: worktree.branch,
    lane: worktree.lane,
    head: worktree.head,
  };
}

function checkoutOf(inventory: Inventory, branch: string): WorktreeInfo | null {
  const matches = inventory.worktrees.filter((worktree) => worktree.branch === branch);
  return matches.find((worktree) => worktree.current) ?? matches[0] ?? null;
}

/**
 * The worktree that contains folder. Paths should already be realpaths when
 * the caller has them; this also accepts a file inside the worktree.
 */
export function worktreeForFolder(inventory: Inventory, folder: string): WorktreeInfo | null {
  const picked = path.resolve(folder);
  let best: WorktreeInfo | null = null;
  let bestLen = -1;
  for (const worktree of inventory.worktrees) {
    const root = path.resolve(worktree.path);
    if (picked !== root && !picked.startsWith(root + path.sep)) continue;
    if (root.length > bestLen) {
      best = worktree;
      bestLen = root.length;
    }
  }
  return best;
}

export function branchHead(inventory: Inventory, name: string): string | null {
  return inventory.branches.find((branch) => branch.name === name)?.head ?? null;
}

/** Restore a saved key. A branch that is now checked out opens its worktree. */
export function targetFromKey(key: string, inventory: Inventory): Target | null {
  if (key.startsWith("worktree:")) {
    const found = inventory.worktrees.find((worktree) => samePath(worktree.path, key.slice("worktree:".length)));
    return found ? worktreeTarget(found) : null;
  }
  if (key.startsWith("branch:")) {
    const name = key.slice("branch:".length);
    const branch = inventory.branches.find((item) => item.name === name);
    if (!branch || !usableRef(name)) return null;
    const checkout = checkoutOf(inventory, name);
    return checkout ? worktreeTarget(checkout) : { kind: "branch", name, head: branch.head };
  }
  if (key.startsWith("remote:")) {
    const name = key.slice("remote:".length);
    if (!usableRef(name)) return null;
    return { kind: "remote", name, head: "" };
  }
  return null;
}

/**
 * A folder the user picked inside a linked worktree opens that worktree.
 * Opening the main worktree (the recent list, or the repo root) restores the
 * last selection, then the main worktree.
 */
export function initialTarget(opts: {
  inventory: Inventory | null;
  main: string;
  picked: string;
  branch: string | null;
  lastKey: string | null;
}): Target {
  const fallback: Target = {
    kind: "worktree",
    path: opts.main,
    branch: opts.branch,
    lane: opts.branch,
    head: "",
  };
  if (!opts.inventory) return fallback;
  const pickedWt = worktreeForFolder(opts.inventory, opts.picked);
  const mainWt = worktreeForFolder(opts.inventory, opts.main) ?? opts.inventory.worktrees.find((worktree) => worktree.current) ?? null;
  if (pickedWt && (!mainWt || !samePath(pickedWt.path, mainWt.path))) return worktreeTarget(pickedWt);
  if (opts.lastKey) {
    const restored = targetFromKey(opts.lastKey, opts.inventory);
    if (restored) return restored;
  }
  if (mainWt) return worktreeTarget(mainWt);
  if (pickedWt) return worktreeTarget(pickedWt);
  return fallback;
}

function worktreeModel(worktree: WorktreeInfo): string {
  if (!worktree.hasModel) return "not scanned";
  return worktree.modelComplete ? "map complete" : "tasks waiting";
}

function branchModel(branch: BranchInfo): string {
  return branch.hasRefModel ? "mapped" : "not scanned";
}

/**
 * Worktrees, then local branches, then remote branches when `remotes` is not
 * null. Null means the user has not fetched in this session. A branch that is
 * checked out in a worktree selects that worktree: its working tree, not the
 * commit's ref model.
 */
export function buildEntries(inventory: Inventory, selectedKey: string | null, remotes: RemoteRef[] | null): SwitcherEntry[] {
  const entries: SwitcherEntry[] = [];
  for (const worktree of inventory.worktrees) {
    const target = worktreeTarget(worktree);
    const label = worktree.lane || worktree.branch || "detached";
    const detail = [worktree.branch && worktree.branch !== label ? worktree.branch : "", worktreeModel(worktree)].filter(Boolean).join(" · ");
    const key = keyOf(target);
    entries.push({
      key,
      group: "worktree",
      label,
      detail,
      model: worktreeModel(worktree),
      selected: key === selectedKey,
      target,
    });
  }
  for (const branch of inventory.branches) {
    if (!usableRef(branch.name)) continue;
    const checkout = checkoutOf(inventory, branch.name);
    const target: Target = checkout ? worktreeTarget(checkout) : { kind: "branch", name: branch.name, head: branch.head };
    const key = `branch:${branch.name}`;
    entries.push({
      key,
      group: "branch",
      label: branch.name,
      detail: checkout ? "checked out" : branchModel(branch),
      model: checkout ? "" : branchModel(branch),
      selected: key === selectedKey,
      target,
    });
  }
  if (remotes) {
    for (const remote of remotes) {
      if (!usableRef(remote.name) || remote.name.endsWith("/HEAD")) continue;
      const key = `remote:${remote.name}`;
      entries.push({
        key,
        group: "remote",
        label: remote.name,
        detail: remote.head.slice(0, 12),
        model: "",
        selected: key === selectedKey,
        target: { kind: "remote", name: remote.name, head: remote.head },
      });
    }
  }
  return entries;
}

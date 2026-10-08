import fs from "node:fs";
import path from "node:path";
import type { ProjectSnapshot } from "./project-cache";
import type { Recent, TaskState } from "./types";

const TASK_STATES: readonly TaskState[] = ["complete", "waiting", "unscanned", "missing", "unknown"];

function asTaskState(value: unknown): TaskState | null {
  return typeof value === "string" && (TASK_STATES as readonly string[]).includes(value) ? value as TaskState : null;
}

export function compareRecents(a: Recent, b: Recent): number {
  if (a.pinned !== b.pinned) return a.pinned ? -1 : 1;
  if (a.lastOpened !== b.lastOpened) return a.lastOpened < b.lastOpened ? 1 : -1;
  if (a.path === b.path) return 0;
  return a.path < b.path ? -1 : 1;
}

function asRecent(value: unknown): Recent | null {
  if (!value || typeof value !== "object") return null;
  const item = value as Record<string, unknown>;
  if (typeof item.path !== "string" || !item.path) return null;
  const displayName = typeof item.displayName === "string" && item.displayName.trim()
    ? item.displayName
    : path.basename(item.path);
  const cachedTaskCount = typeof item.cachedTaskCount === "number" && Number.isFinite(item.cachedTaskCount)
    ? item.cachedTaskCount
    : null;
  return {
    path: item.path,
    displayName,
    pinned: item.pinned === true,
    lastOpened: typeof item.lastOpened === "string" ? item.lastOpened : "",
    lastView: typeof item.lastView === "string" ? item.lastView : "",
    cachedBranch: typeof item.cachedBranch === "string" ? item.cachedBranch : item.cachedBranch === null ? null : undefined,
    cachedTaskState: asTaskState(item.cachedTaskState),
    cachedTaskCount,
    cachedMissing: item.cachedMissing === true ? true : item.cachedMissing === false ? false : undefined,
  };
}

export function readRecents(json: string): Recent[] {
  try {
    const parsed = JSON.parse(json) as { projects?: unknown };
    if (!parsed || !Array.isArray(parsed.projects)) return [];
    return parsed.projects.map(asRecent).filter((item): item is Recent => item !== null).sort(compareRecents);
  } catch {
    return [];
  }
}

function writeJson(file: string, value: unknown) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const tmp = `${file}.tmp`;
  fs.writeFileSync(tmp, `${JSON.stringify(value, null, 2)}\n`);
  fs.renameSync(tmp, file);
}

/** Recent projects in the app's userData. Nothing here is written into the repository. */
export class RecentsStore {
  constructor(private readonly file: string) {}

  list(): Recent[] {
    try {
      return readRecents(fs.readFileSync(this.file, "utf8"));
    } catch {
      return [];
    }
  }

  get(projectPath: string): Recent | null {
    return this.list().find((item) => item.path === projectPath) ?? null;
  }

  private save(projects: Recent[]) {
    writeJson(this.file, { projects: projects.slice().sort(compareRecents) });
  }

  /** Record an open. Keeps pin, display name and last view when the path is already known. */
  open(projectPath: string, now = new Date().toISOString()): Recent {
    const prev = this.list().find((item) => item.path === projectPath);
    const item: Recent = prev
      ? { ...prev, lastOpened: now }
      : {
          path: projectPath,
          displayName: path.basename(projectPath),
          pinned: false,
          lastOpened: now,
          lastView: "",
        };
    const rest = this.list().filter((entry) => entry.path !== projectPath);
    this.save([item, ...rest]);
    return item;
  }

  setPinned(projectPath: string, pinned: boolean) {
    this.save(this.list().map((item) => (item.path === projectPath ? { ...item, pinned } : item)));
  }

  rename(projectPath: string, displayName: string) {
    const name = displayName.trim();
    if (!name) throw new Error("The display name is empty.");
    if (name.length > 200) throw new Error("The display name is too long.");
    this.save(this.list().map((item) => (item.path === projectPath ? { ...item, displayName: name } : item)));
  }

  remove(projectPath: string) {
    this.save(this.list().filter((item) => item.path !== projectPath));
  }

  /**
   * Point a missing entry at a new path. When that path is already listed, the
   * missing entry is dropped and the existing one is kept.
   */
  relocate(from: string, to: string) {
    if (from === to) return;
    const all = this.list();
    if (!all.some((item) => item.path === from)) return;
    if (all.some((item) => item.path === to)) {
      this.save(all.filter((item) => item.path !== from));
      return;
    }
    this.save(all.map((item) => (item.path === from ? { ...item, path: to } : item)));
  }

  setLastView(projectPath: string, hash: string) {
    const all = this.list();
    if (!all.some((item) => item.path === projectPath)) return;
    this.save(all.map((item) => (item.path === projectPath ? { ...item, lastView: hash } : item)));
  }

  /** Remember the Projects-row fields. Ignored when the path is not listed. */
  setSnapshot(projectPath: string, snapshot: ProjectSnapshot) {
    const all = this.list();
    if (!all.some((item) => item.path === projectPath)) return;
    this.save(all.map((item) => (item.path === projectPath ? { ...item, ...snapshot } : item)));
  }
}

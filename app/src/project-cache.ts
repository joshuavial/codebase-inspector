import type { Recent, RecentView, TaskState } from "./types";

/** What the Projects list can draw without asking git or cbi. */
export interface ProjectSnapshot {
  cachedBranch: string | null;
  cachedTaskState: TaskState;
  cachedTaskCount: number;
  cachedMissing: boolean;
}

export function viewFromCache(item: Recent, refreshing = false): RecentView {
  const missing = item.cachedMissing === true;
  const taskState: TaskState = missing ? "missing" : (item.cachedTaskState ?? "unknown");
  return {
    path: item.path,
    displayName: item.displayName,
    pinned: item.pinned,
    lastOpened: item.lastOpened,
    lastView: item.lastView,
    missing,
    branch: missing ? null : (item.cachedBranch ?? null),
    taskState,
    taskCount: missing ? 0 : (item.cachedTaskCount ?? 0),
    refreshing,
  };
}


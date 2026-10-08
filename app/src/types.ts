export interface Recent {
  path: string;
  displayName: string;
  pinned: boolean;
  lastOpened: string;
  lastView: string;
  /** Last known branch, task state and folder check. Absent until a refresh has stored them. */
  cachedBranch?: string | null;
  cachedTaskState?: TaskState | null;
  cachedTaskCount?: number | null;
  cachedMissing?: boolean;
}

export type TaskState = "complete" | "waiting" | "unscanned" | "missing" | "unknown";

export interface RecentView extends Recent {
  missing: boolean;
  branch: string | null;
  taskState: TaskState;
  taskCount: number;
  refreshing?: boolean;
}

export type Phase = "init" | "scan" | "build" | "status" | "ready" | "error";

export interface Progress {
  phase: Phase;
  line?: string;
  error?: string;
  /** A short strip. The map stage stays on screen. */
  compact?: boolean;
}

export interface ToastPayload {
  kind: "update" | "error";
  message: string;
  action?: string;
  detail?: string;
}

export interface StatusJson {
  scanned_at: string | null;
  nodes: Record<string, number>;
  open_tasks: Record<string, number>;
}

export interface ProjectInfo {
  path: string;
  displayName: string;
  branch: string;
  versionLabel?: string;
  readOnly?: boolean;
  statusLine?: string;
  comparing?: boolean;
  backLabel?: string;
  /** A built viewer is about to show. No progress strip. */
  instant?: boolean;
  /** Hide the stage behind the progress log. Comparison builds still use this. */
  cover?: boolean;
}

export interface SwitcherRow {
  key: string;
  group: "worktree" | "branch" | "remote";
  label: string;
  detail: string;
  model: string;
  selected: boolean;
}

export interface VersionList {
  entries: SwitcherRow[];
  fetched: boolean;
  fetching: boolean;
  error: string | null;
}

export interface ProjectState extends ProjectInfo {
  tasks: Record<string, number>;
  instruction: string;
}

export interface CbiInfo {
  setting: string | null;
  resolved: string | null;
  error: string | null;
}

export interface StageBounds {
  x: number;
  y: number;
  width: number;
  height: number;
}

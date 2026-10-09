import { createHash } from "node:crypto";
import path from "node:path";
import { samePath, usableRef } from "./switcher";

/** A viewer that is already on disk, so the window can show it before any scan. */
export interface InstantOpen {
  index: string;
  cwd: string;
  ref: string | null;
  kind: "worktree" | "branch";
  branchName: string | null;
  commit: string | null;
}

/**
 * The built viewer for this click, or null when the project has never been built.
 * A folder that is not the main checkout only uses its own viewer: the main map
 * is a different worktree. A saved branch needs its commit so the ref viewer can be named.
 */
export function instantOpen(opts: {
  project: string;
  picked: string;
  lastKey: string | null;
  branchCommit: string | null;
  exists: (file: string) => boolean;
}): InstantOpen | null {
  const project = path.resolve(opts.project);
  const picked = path.resolve(opts.picked);
  if (!samePath(picked, project)) {
    const lane = path.join(picked, ".cbi", "viewer", "index.html");
    if (opts.exists(lane)) {
      return { index: lane, cwd: picked, ref: null, kind: "worktree", branchName: null, commit: null };
    }
    return null;
  }
  const key = opts.lastKey;
  if (key?.startsWith("worktree:")) {
    const cwd = key.slice("worktree:".length);
    const index = path.join(cwd, ".cbi", "viewer", "index.html");
    if (cwd && opts.exists(index)) {
      return { index, cwd, ref: null, kind: "worktree", branchName: null, commit: null };
    }
  }
  if (key?.startsWith("branch:") && opts.branchCommit && /^[0-9a-f]{40}$/.test(opts.branchCommit)) {
    const name = key.slice("branch:".length);
    const index = path.join(project, ".cbi", "refs", opts.branchCommit, "viewer", "index.html");
    if (usableRef(name) && opts.exists(index)) {
      return { index, cwd: project, ref: name, kind: "branch", branchName: name, commit: opts.branchCommit };
    }
  }
  const own = path.join(project, ".cbi", "viewer", "index.html");
  if (opts.exists(own)) {
    return { index: own, cwd: project, ref: null, kind: "worktree", branchName: null, commit: null };
  }
  return null;
}

/** Read-only. The ref is one argv element and cannot start with a dash. */
export function verifyCommitArgv(ref: string): string[] | null {
  if (!usableRef(ref)) return null;
  return ["rev-parse", "--verify", "--end-of-options", ref];
}

/** The commit directory of a ref viewer, when the path is one. */
export function commitFromViewer(index: string): string | null {
  const match = index.match(/[/\\]\.cbi[/\\]refs[/\\]([0-9a-f]{40})[/\\]viewer[/\\]index\.html$/);
  return match?.[1] ?? null;
}

export function viewerForTarget(opts: {
  cwd: string;
  project: string;
  ref: string | null;
  head: string;
  exists: (file: string) => boolean;
}): string | null {
  if (opts.ref) {
    if (!/^[0-9a-f]{40}$/.test(opts.head)) return null;
    const index = path.join(opts.project, ".cbi", "refs", opts.head, "viewer", "index.html");
    return opts.exists(index) ? index : null;
  }
  const index = path.join(opts.cwd, ".cbi", "viewer", "index.html");
  return opts.exists(index) ? index : null;
}

/** SQLite URI. A Windows drive letter is not encoded: file:///C:/repo/.cbi/model.db. */
export function fileUri(db: string): string {
  const normalized = db.replace(/\\/g, "/");
  const encoded = normalized.split("/").map((part) => /^[A-Za-z]:$/.test(part) ? part : encodeURIComponent(part)).join("/");
  const prefix = /^[A-Za-z]:/.test(encoded) ? "file:///" : "file:";
  return `${prefix}${encoded}?immutable=1`;
}

/** `sqlite3` argv. immutable so a status read does not create or touch the wal shared-memory file. */
export function sqliteArgs(db: string, sql: string): string[] {
  return ["-batch", "-noheader", "-separator", "|", fileUri(db), sql];
}

export function statusQuery(): string {
  return [
    "SELECT 'scanned_at', ifnull((SELECT value FROM meta WHERE key = 'scanned_at'), '');",
    "SELECT 'task', kind, count(*) FROM tasks WHERE state = 'open' GROUP BY kind ORDER BY kind;",
  ].join(" ");
}

export function fileStateQuery(): string {
  return "SELECT path || char(31) || content_hash FROM file_state;";
}

export function parseStatusTable(text: string): { scanned_at: string | null; open_tasks: Record<string, number> } {
  const open_tasks: Record<string, number> = {};
  let scanned_at: string | null = null;
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (!line) continue;
    const parts = line.split("|");
    if (parts[0] === "scanned_at") {
      const value = parts.slice(1).join("|");
      scanned_at = value || null;
    } else if (parts[0] === "task" && parts[1]) {
      const count = Number(parts[2]);
      if (Number.isFinite(count)) open_tasks[parts[1]] = count;
    }
  }
  return { scanned_at, open_tasks };
}

export function parseFileStates(text: string): Map<string, string> {
  const states = new Map<string, string>();
  for (const line of text.split("\n")) {
    if (!line) continue;
    const at = line.lastIndexOf("\x1f");
    if (at <= 0) continue;
    states.set(line.slice(0, at), line.slice(at + 1));
  }
  return states;
}

/** Added, removed and rehashed paths. A path whose hash is unchanged does not count. */
export function countChangedFiles(before: ReadonlyMap<string, string>, after: ReadonlyMap<string, string>): number {
  let changed = 0;
  for (const [file, hash] of after) {
    if (before.get(file) !== hash) changed += 1;
  }
  for (const file of before.keys()) {
    if (!after.has(file)) changed += 1;
  }
  return changed;
}

/** A comparison build writes an object. A normal build writes null. */
export function isCompareScript(source: string): boolean {
  const payload = scriptPayload(source);
  return Boolean(payload && typeof payload === "object");
}

/** Parse `cbiLoad("name", <json>);`. Null when the script is not that shape. */
export function scriptPayload(source: string): unknown | null {
  const open = source.indexOf("cbiLoad(");
  if (open < 0) return null;
  const comma = source.indexOf(",", open);
  if (comma < 0) return null;
  let body = source.slice(comma + 1).trim();
  if (body.endsWith(";")) body = body.slice(0, -1).trim();
  if (body.endsWith(")")) body = body.slice(0, -1).trim();
  try {
    return JSON.parse(body) as unknown;
  } catch {
    return null;
  }
}

/** Sort object keys and arrays of plain values so a rebuild's list order is not a new map. */
export function canonicalValue(value: unknown): unknown {
  if (Array.isArray(value)) {
    const items = value.map(canonicalValue);
    const plain = items.every((item) => item === null || item === undefined || ["string", "number", "boolean"].includes(typeof item));
    if (!plain) return items;
    return items.slice().sort((a, b) => {
      const left = JSON.stringify(a);
      const right = JSON.stringify(b);
      if (left < right) return -1;
      if (left > right) return 1;
      return 0;
    });
  }
  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    const out: Record<string, unknown> = {};
    for (const key of Object.keys(record).sort()) out[key] = canonicalValue(record[key]);
    return out;
  }
  return value;
}

/**
 * Hash of the map payloads. The same map with reordered plain lists hashes the same.
 * Empty input is an empty string so a missing viewer is not "the same" as a real one
 * only when the caller treats "" as not ready.
 */
export function payloadFingerprint(sources: string[]): string {
  const hash = createHash("sha1");
  let any = false;
  for (const source of sources) {
    const payload = scriptPayload(source);
    if (payload === null) {
      if (!source.trim()) continue;
      hash.update(source);
      hash.update("\0");
      any = true;
      continue;
    }
    hash.update(JSON.stringify(canonicalValue(payload)));
    hash.update("\0");
    any = true;
  }
  return any ? hash.digest("hex") : "";
}

import path from "node:path";
import type { MapResult } from "./map-project";
import type { Phase, StatusJson } from "./types";

export function isModelChange(filename: string | null): boolean {
  return filename === "model.db" || filename === "model.db-journal" || filename === "model.db-wal";
}

type Timer = ReturnType<typeof setTimeout>;

/**
 * Rebuilds the viewer when the model file changes.
 * The hash captured before the reload is the one loaded afterwards.
 */
export class ProjectSession {
  private watcher: { close(): void } | null = null;
  private timer: Timer | null = null;
  private refreshing = false;
  private queued = false;
  private stopped = false;
  private root: string | null = null;
  private cbi: string | null = null;
  private viewerIndex = "";
  hash = "";
  idle: Promise<void> = Promise.resolve();

  constructor(private readonly deps: {
    rebuild: (root: string, cbi: string) => Promise<MapResult>;
    watch: (dir: string, onName: (name: string | null) => void) => { close(): void };
    loadViewer: (indexHtml: string, hash: string) => Promise<void>;
    onStatus: (status: StatusJson) => void;
    onProgress: (phase: Phase, error?: string) => void;
    debounceMs?: number;
    setTimer?: (fn: () => void, ms: number) => Timer;
    clearTimer?: (id: Timer) => void;
  }) {}

  noteHash(hash: string) {
    this.hash = hash;
  }

  /**
   * `root` is the working tree `cbi` runs in. `modelDir` defaults to `<root>/.cbi`
   * and is `<root>/.cbi/refs/<sha>` for a branch view.
   */
  startWatch(root: string, cbi: string, extra?: { modelDir?: string; viewerIndex?: string }) {
    this.stopWatch();
    this.stopped = false;
    this.root = root;
    this.cbi = cbi;
    const modelDir = extra?.modelDir ?? path.join(root, ".cbi");
    this.viewerIndex = extra?.viewerIndex ?? path.join(modelDir, "viewer", "index.html");
    this.watcher = this.deps.watch(modelDir, (name) => this.notify(name));
  }

  notify(name: string | null) {
    if (this.stopped || !isModelChange(name)) return;
    const setTimer = this.deps.setTimer ?? setTimeout;
    const clearTimer = this.deps.clearTimer ?? clearTimeout;
    if (this.timer) clearTimer(this.timer);
    this.timer = setTimer(() => {
      this.timer = null;
      if (this.stopped) return;
      if (this.refreshing) {
        this.queued = true;
        return;
      }
      this.idle = this.refresh();
    }, this.deps.debounceMs ?? 400);
  }

  private async refresh() {
    if (this.refreshing) {
      this.queued = true;
      return;
    }
    if (!this.root || !this.cbi) return;
    this.refreshing = true;
    const hash = this.hash;
    const root = this.root;
    const cbi = this.cbi;
    try {
      this.deps.onProgress("build");
      const result = await this.deps.rebuild(root, cbi);
      if (this.stopped) return;
      if (!result.ok) {
        this.deps.onProgress("error", result.error);
        return;
      }
      const index = result.viewer || this.viewerIndex || path.join(root, ".cbi", "viewer", "index.html");
      await this.deps.loadViewer(index, hash.replace(/^#/, ""));
      if (this.stopped) return;
      this.deps.onStatus(result.status);
      this.deps.onProgress("ready");
    } catch (err) {
      if (!this.stopped) this.deps.onProgress("error", err instanceof Error ? err.message : String(err));
    } finally {
      this.refreshing = false;
      if (this.queued && !this.stopped) {
        this.queued = false;
        this.idle = this.refresh();
      }
    }
  }

  stop() {
    this.stopped = true;
    this.queued = false;
    this.stopWatch();
  }

  private stopWatch() {
    if (this.timer) {
      (this.deps.clearTimer ?? clearTimeout)(this.timer);
      this.timer = null;
    }
    this.watcher?.close();
    this.watcher = null;
  }
}

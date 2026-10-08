type Timer = ReturnType<typeof setTimeout>;

/** A file-watch name under .git or .cbi. A scan writes .cbi, so those events must not schedule another scan. */
export function watchIgnored(name: string | null): boolean {
  if (!name) return true;
  return name.split(/[/\\]/).some((part) => part === ".git" || part === ".cbi");
}

export const RESCAN_DEBOUNCE_MS = 800;
export const BRANCH_POLL_MS = 30_000;

/**
 * Debounced watch of one worktree. The caller scans and builds on fire.
 * Events during a scan collapse into one more scan.
 */
export class WorktreeWatch {
  private watcher: { close(): void } | null = null;
  private dir: string | null = null;
  private timer: Timer | null = null;
  private running = false;
  private queued = false;
  private stopped = false;
  private rearmTimer: Timer | null = null;
  /** Nameless events during and just after a scan are our own .cbi writes. */
  private anonymousUntil = 0;
  idle: Promise<void> = Promise.resolve();

  constructor(private readonly deps: {
    watch: (dir: string, onName: (name: string | null) => void) => { close(): void };
    onFire: () => Promise<void> | void;
    debounceMs?: number;
    rearmDelayMs?: number;
    setTimer?: (fn: () => void, ms: number) => Timer;
    clearTimer?: (id: Timer) => void;
  }) {}

  start(dir: string) {
    this.stop();
    this.stopped = false;
    this.dir = dir;
    this.arm();
  }

  /**
   * Open the directory watch again without dropping a scan that is already
   * running. On macOS, opening a new watch in the same turn as closing the
   * old one often drops every later event, so the new watch waits briefly.
   */
  rearm(delayMs?: number) {
    if (this.stopped || !this.dir) return;
    this.watcher?.close();
    this.watcher = null;
    if (this.rearmTimer) (this.deps.clearTimer ?? clearTimeout)(this.rearmTimer);
    const dir = this.dir;
    const setTimer = this.deps.setTimer ?? setTimeout;
    this.rearmTimer = setTimer(() => {
      this.rearmTimer = null;
      if (this.stopped || this.dir !== dir || this.watcher) return;
      this.arm();
    }, delayMs ?? this.deps.rearmDelayMs ?? 300);
  }

  private arm() {
    if (!this.dir) return;
    this.watcher = this.deps.watch(this.dir, (name) => this.notify(name));
  }

  notify(name: string | null) {
    if (this.stopped) return;
    if (!name) {
      if (this.running || Date.now() < this.anonymousUntil) return;
    } else if (watchIgnored(name)) return;
    const setTimer = this.deps.setTimer ?? setTimeout;
    const clearTimer = this.deps.clearTimer ?? clearTimeout;
    if (this.timer) clearTimer(this.timer);
    this.timer = setTimer(() => {
      this.timer = null;
      if (this.stopped) return;
      if (this.running) {
        this.queued = true;
        return;
      }
      this.idle = this.fire();
    }, this.deps.debounceMs ?? RESCAN_DEBOUNCE_MS);
  }

  private async fire() {
    if (this.running || this.stopped) return;
    this.running = true;
    this.anonymousUntil = Date.now() + 1000;
    try {
      await this.deps.onFire();
    } finally {
      this.running = false;
      this.anonymousUntil = Date.now() + 1000;
      if (this.queued && !this.stopped) {
        this.queued = false;
        this.idle = this.fire();
      }
    }
  }

  stop() {
    this.stopped = true;
    this.queued = false;
    const clearTimer = this.deps.clearTimer ?? clearTimeout;
    if (this.timer) {
      clearTimer(this.timer);
      this.timer = null;
    }
    if (this.rearmTimer) {
      clearTimer(this.rearmTimer);
      this.rearmTimer = null;
    }
    this.watcher?.close();
    this.watcher = null;
    this.dir = null;
  }
}

/**
 * While a branch view is open, poll its head. `onMove` runs only when the
 * commit changes. The next poll waits until that rescan settles.
 */
export class BranchPoll {
  private timer: Timer | null = null;
  private stopped = false;
  private head = "";
  settled: Promise<void> = Promise.resolve();

  constructor(private readonly deps: {
    intervalMs?: number;
    head: () => Promise<string | null>;
    onMove: (head: string) => Promise<void> | void;
    setTimer?: (fn: () => void, ms: number) => Timer;
    clearTimer?: (id: Timer) => void;
  }) {}

  start(head: string) {
    this.stop();
    this.stopped = false;
    this.head = head;
    this.arm();
  }

  private arm() {
    const setTimer = this.deps.setTimer ?? setTimeout;
    this.timer = setTimer(() => {
      this.timer = null;
      this.settled = this.tick();
    }, this.deps.intervalMs ?? BRANCH_POLL_MS);
  }

  private async tick() {
    if (this.stopped) return;
    let head: string | null = null;
    try {
      head = await this.deps.head();
    } catch {
      head = null;
    }
    if (this.stopped) return;
    if (head && head !== this.head) {
      this.head = head;
      try {
        await this.deps.onMove(head);
      } catch {
        // The caller reports a failed rescan. Keep polling.
      }
    }
    if (!this.stopped) this.arm();
  }

  stop() {
    this.stopped = true;
    if (this.timer) {
      (this.deps.clearTimer ?? clearTimeout)(this.timer);
      this.timer = null;
    }
  }
}

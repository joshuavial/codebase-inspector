import { execFileSync } from "node:child_process";
import { app, BrowserWindow, Menu, WebContentsView, clipboard, dialog, ipcMain, nativeTheme, webContents } from "electron";
import fs from "node:fs";
import path from "node:path";
import { findCbi, isExecutable, readSetting, writeSetting } from "./cbi-bin";
import {
  commitFromViewer,
  countChangedFiles,
  fileStateQuery,
  instantOpen,
  isCompareScript,
  parseFileStates,
  parseStatusTable,
  payloadFingerprint,
  statusQuery,
  verifyCommitArgv,
  viewerForTarget,
} from "./fast-open";
import { querySqlite } from "./model-read";
import { viewFromCache, type ProjectSnapshot } from "./project-cache";
import { errorToast, updateToast } from "./toast";
import { describeEditor, EditorError, launchEditor, normalizeChoice, planViewerOpen, readEditorSettings, refEditorContext, writeEditorSettings } from "./editor";
import { dockIcon, windowIcon } from "./icon";
import { isCommitSha, parsePrOids, planCompare, prViewArgs, readCompareForm } from "./compare";
import { linkFromArgv, validateOpen, verifyRef, viewerLocation } from "./deeplink";
import { revealFor, revealWindow } from "./reveal";
import { assertRemoteArgv, FETCH_ARGV, parseRemoteRefs, REMOTES_ARGV } from "./git-remotes";
import { agentInstruction, mapCompare, mapVersion, modelHome, rebuildViewer, taskSummary } from "./map-project";
import { resolveProject } from "./project";
import { commandExecutable } from "./which";
import { RecentsStore } from "./recents";
import { BranchPoll, WorktreeWatch } from "./rescan";
import { ProjectSession } from "./session";
import { runProcess, type KillSlot } from "./spawn";
import {
  branchOf,
  buildEntries,
  formatScanned,
  initialTarget,
  keyOf,
  labelOf,
  parseInventory,
  readOnlyTarget,
  refInstruction,
  refOf,
  samePath,
  targetFromKey,
  usableRef,
  worktreeTarget,
  type Inventory,
  type RemoteRef,
  type SwitcherEntry,
  type Target,
} from "./switcher";
import type { CbiInfo, Phase, Progress, ProjectInfo, ProjectState, StageBounds, StatusJson } from "./types";
import { CAPTURE_VIEW_JS, parseCaptured, restoreScript, ViewStore, type SavedView } from "./view-state";
import { sameViewer, sameViewerFile } from "./viewer-load";

const SCAN_TIMEOUT_MS = 10 * 60 * 1000;
const STATUS_TIMEOUT_MS = 20_000;
const FETCH_TIMEOUT_MS = 60_000;

// Tests and smoke set CBI_HEADLESS=1. Accessory skips the dock. hide() gives
// focus back when macOS has already activated the process.
const headless = process.env.CBI_HEADLESS === "1";
function yieldFocus() {
  if (!headless || process.platform !== "darwin" || !app.isReady()) return;
  app.hide();
}
if (headless && process.platform === "darwin") app.setActivationPolicy("accessory");
if (headless) {
  app.on("activate", () => yieldFocus());
  app.on("browser-window-created", (_event, created) => {
    // focusable:false on Linux pins the window above every workspace.
    if (process.platform === "darwin") created.setFocusable(false);
    created.on("show", () => {
      created.hide();
      yieldFocus();
    });
  });
}

app.setName("Codebase Inspector");
if (process.env.CBI_APP_USER_DATA) app.setPath("userData", path.resolve(process.env.CBI_APP_USER_DATA));

interface OpenVersion {
  project: string;
  displayName: string;
  key: string;
  target: Target;
  cwd: string;
  ref: string | null;
  cbi: string;
  viewerIndex: string;
  modelDir: string;
  head: string;
  /** False for a ref opened from a link: the worktree is not watched. */
  watchModel?: boolean;
}

let win: BrowserWindow | null = null;
let viewer: WebContentsView | null = null;
let session: ProjectSession | null = null;
let generation = 0;
let rescanEpoch = 0;
let reloading = false;
let viewerWanted = false;
let switcherOpen = false;
let compareOpen = false;
/** The view to restore when a comparison closes. A second comparison keeps the first one. */
let comparisonReturn: Target | null = null;
let stageBounds: StageBounds = { x: 0, y: 0, width: 0, height: 0 };
let shown: ProjectState | null = null;
let version: OpenVersion | null = null;
let inventory: Inventory | null = null;
let remotes: RemoteRef[] | null = null;
let choices: SwitcherEntry[] = [];
let versionError: string | null = null;
let fetching = false;
let openProject: string | null = null;
let treeWatch: WorktreeWatch | null = null;
let headPoll: BranchPoll | null = null;
let rescanTail: Promise<void> = Promise.resolve();
const scanSlot: KillSlot = { kill: null };
let shownFingerprint = "";
let fingerprintReady = false;
let shownFiles: Map<string, string> = new Map();
let pendingUpdate: { index: string; fingerprint: string } | null = null;
let shownReady: Promise<void> = Promise.resolve();
let releaseShown: () => void = () => {};
const refreshingRows = new Set<string>();
let refreshGen = 0;

function holdShown() {
  releaseShown();
  shownReady = new Promise((resolve) => {
    releaseShown = resolve;
  });
}

function flushShown() {
  releaseShown();
  releaseShown = () => {};
  shownReady = Promise.resolve();
}

function store(): RecentsStore {
  return new RecentsStore(path.join(app.getPath("userData"), "recents.json"));
}

function viewStore(): ViewStore {
  return new ViewStore(path.join(app.getPath("userData"), "views.json"));
}

function settingsPath(): string {
  return path.join(app.getPath("userData"), "settings.json");
}

function editorSettingsPath(): string {
  return path.join(app.getPath("userData"), "editor.json");
}

function lookupCbi() {
  const setting = readSetting(settingsPath()).cbiPath;
  return findCbi({
    envOverride: process.env.CBI_BIN ?? null,
    setting,
    pathEnv: process.env.PATH ?? "",
    home: app.getPath("home"),
    isExecutable,
  });
}

function cbiInfo(): CbiInfo {
  const found = lookupCbi();
  return {
    setting: readSetting(settingsPath()).cbiPath,
    resolved: found.ok ? found.path : null,
    error: found.ok ? null : found.error,
  };
}

function send(channel: string, payload: unknown) {
  if (!win || win.isDestroyed()) return;
  win.webContents.send(channel, payload);
}

function trace(message: string) {
  const file = process.env.CBI_OPEN_TRACE;
  if (!file) return;
  try {
    fs.appendFileSync(file, `${Date.now()} ${message}\n`);
  } catch {
    // A trace file is only for measuring an open. A failed write does not change it.
  }
}

function sendProgress(progress: Progress) {
  send("progress", progress);
}

function parseStatus(stdout: string): StatusJson | null {
  try {
    const status = JSON.parse(stdout) as StatusJson;
    if (!status || typeof status !== "object" || !status.open_tasks || typeof status.open_tasks !== "object" || Array.isArray(status.open_tasks)) {
      return null;
    }
    return status;
  } catch {
    return null;
  }
}

function tasksWaiting(tasks: Record<string, number>): boolean {
  return Object.values(tasks).some((n) => typeof n === "number" && n > 0);
}

function runCbi(bin: string, args: string[], cwd: string, onLine: (line: string) => void, timeoutMs: number, slot?: KillSlot) {
  const label = args[0] ?? "cbi";
  trace(`cbi ${label} start`);
  return runProcess(bin, args, cwd, onLine, timeoutMs, undefined, slot).then((run) => {
    trace(`cbi ${label} end ${run.code}`);
    return run;
  });
}

function normalizeInventory(parsed: Inventory): Inventory {
  return {
    branches: parsed.branches,
    worktrees: parsed.worktrees.map((worktree) => {
      try {
        return { ...worktree, path: fs.realpathSync(worktree.path) };
      } catch {
        return worktree;
      }
    }),
  };
}

async function loadInventory(main: string, cbi: string): Promise<Inventory | null> {
  const run = await runCbi(cbi, ["worktrees", "--json"], main, () => undefined, STATUS_TIMEOUT_MS);
  if (run.code !== 0) return null;
  const parsed = parseInventory(run.stdout);
  return parsed ? normalizeInventory(parsed) : null;
}

function publishVersions() {
  const selected = version?.key ?? null;
  choices = inventory ? buildEntries(inventory, selected, remotes) : [];
  send("versions", {
    entries: choices.map(({ key, group, label, detail, model, selected: on }) => ({
      key,
      group,
      label,
      detail,
      model,
      selected: on,
    })),
    fetched: remotes !== null,
    fetching,
    error: versionError,
  });
}

function publishProject() {
  if (shown) send("project", shown);
}

function cachedViews() {
  return store().list().map((item) => viewFromCache(item, refreshingRows.has(item.path)));
}

function publishRecents() {
  send("recents", cachedViews());
}

async function projectSnapshot(projectPath: string): Promise<ProjectSnapshot> {
  if (!fs.existsSync(projectPath)) {
    return { cachedBranch: null, cachedTaskState: "missing", cachedTaskCount: 0, cachedMissing: true };
  }
  const resolved = resolveProject(projectPath);
  if (!resolved.ok) {
    if (resolved.error.includes("git was not found")) {
      return { cachedBranch: null, cachedTaskState: "unknown", cachedTaskCount: 0, cachedMissing: false };
    }
    return { cachedBranch: null, cachedTaskState: "missing", cachedTaskCount: 0, cachedMissing: true };
  }
  const db = path.join(resolved.main, ".cbi", "model.db");
  if (!fs.existsSync(db)) {
    return { cachedBranch: resolved.branch, cachedTaskState: "unscanned", cachedTaskCount: 0, cachedMissing: false };
  }
  const status = await readCheapStatus(db);
  const summary = taskSummary({ folderExists: true, modelExists: true, status });
  return {
    cachedBranch: resolved.branch,
    cachedTaskState: summary.taskState,
    cachedTaskCount: summary.taskCount,
    cachedMissing: false,
  };
}

async function refreshRecents() {
  const gen = ++refreshGen;
  for (const item of store().list()) {
    if (gen !== refreshGen) return;
    await new Promise((resolve) => setTimeout(resolve, 0));
    if (gen !== refreshGen) return;
    refreshingRows.add(item.path);
    publishRecents();
    try {
      const snapshot = await projectSnapshot(item.path);
      if (gen !== refreshGen) return;
      store().setSnapshot(item.path, snapshot);
    } finally {
      refreshingRows.delete(item.path);
      if (gen === refreshGen) publishRecents();
    }
  }
}

async function pushRecents() {
  publishRecents();
  void refreshRecents();
}

function applyBounds() {
  if (!viewer || viewer.webContents.isDestroyed()) return;
  // The child view paints over the window, so the menu has to hide it while open.
  if (!viewerWanted || switcherOpen || compareOpen || stageBounds.width < 2 || stageBounds.height < 2) {
    viewer.setVisible(false);
    return;
  }
  viewer.setBounds({
    x: Math.round(stageBounds.x),
    y: Math.round(stageBounds.y),
    width: Math.round(stageBounds.width),
    height: Math.round(stageBounds.height),
  });
  viewer.setVisible(true);
}

let loadToken = 0;
let currentLoad: { token: number; succeed: () => void; fail: (err: Error) => void } | null = null;

function loadViewer(index: string, hash: string): Promise<void> {
  const contents = viewer?.webContents;
  if (!contents || contents.isDestroyed()) return Promise.reject(new Error("The viewer is not open."));
  currentLoad?.succeed();
  const token = ++loadToken;
  reloading = true;
  viewerWanted = true;
  return new Promise((resolve, reject) => {
    const bareHash = hash.replace(/^#/, "");
    // Same path, new bytes: comparison overwrites the worktree viewer. reloadIgnoringCache
    // is what drops the cached diff.js. The hash is applied afterwards.
    let fixHash = false;
    let bustCache = false;
    const finish = (err?: Error) => {
      if (currentLoad?.token !== token) return;
      contents.removeListener("did-finish-load", onLoad);
      contents.removeListener("did-fail-load", onFail);
      contents.removeListener("did-navigate-in-page", onInPage);
      currentLoad = null;
      reloading = false;
      // A viewer load can drop the macOS recursive watch. A cache-busting reload keeps
      // dropping watches opened in the next few hundred milliseconds, so that one waits longer.
      const watch = treeWatch;
      const reopen = () => watch?.rearm(bustCache ? 1500 : undefined);
      if (!err && fixHash) {
        fixHash = false;
        const next = bareHash ? `#${bareHash}` : "";
        void contents.executeJavaScript(`location.hash = ${JSON.stringify(next)}`).finally(reopen);
      } else if (!err) {
        reopen();
      }
      if (err) reject(err);
      else resolve();
    };
    currentLoad = { token, succeed: () => finish(), fail: (err) => finish(err) };
    const onLoad = () => finish();
    const onFail = (_event: Electron.Event, code: number, desc: string) => {
      if (code === -3) return;
      finish(new Error(desc || `Could not load the viewer (${code}).`));
    };
    // Changing only the hash does not emit did-finish-load, and the load can drop the directory watch.
    const onInPage = (_event: Electron.Event, url: string) => {
      if (!sameViewerFile(url, index)) return;
      if (!sameViewer(url, index, bareHash)) return;
      if (!contents.isLoadingMainFrame()) finish();
      else setTimeout(() => {
        if (currentLoad?.token === token && !contents.isLoadingMainFrame()) finish();
      }, 100);
    };
    contents.on("did-finish-load", onLoad);
    contents.on("did-fail-load", onFail);
    contents.on("did-navigate-in-page", onInPage);
    if (sameViewerFile(contents.getURL(), index)) {
      bustCache = true;
      fixHash = !sameViewer(contents.getURL(), index, bareHash);
      contents.reloadIgnoringCache();
    } else {
      void contents.loadFile(index, bareHash ? { hash: bareHash } : {});
    }
  });
}

async function captureCurrent() {
  const current = version;
  const contents = viewer?.webContents;
  if (!current || !contents || contents.isDestroyed()) return;
  let url = "";
  try {
    url = contents.getURL();
  } catch {
    return;
  }
  if (!url.includes("/.cbi/") || !url.includes("index.html")) return;
  let text = "";
  try {
    text = String(await contents.executeJavaScript(CAPTURE_VIEW_JS));
  } catch {
    return;
  }
  const saved = parseCaptured(text);
  if (!saved) return;
  viewStore().set(current.project, current.key, saved);
  if (version?.key === current.key) session?.noteHash(saved.hash);
  // A comparison is not the project's last view. Reopening the project returns to the worktree or branch.
  if (current.target.kind !== "compare") store().setLastView(current.project, saved.hash);
}

async function applyDrawer(view: SavedView) {
  const contents = viewer?.webContents;
  if (!contents || contents.isDestroyed()) return;
  if (!view.sections.length && !view.drawerHidden) return;
  try {
    await contents.executeJavaScript(restoreScript(view));
  } catch {
    // The hash is already loaded. A missing drawer does not fail the open.
  }
}

function savedViewFor(project: string, key: string, target: Target): SavedView {
  const saved = viewStore().get(project, key);
  if (saved.hash || target.kind !== "worktree" || path.resolve(target.path) !== path.resolve(project)) return saved;
  const last = store().get(project)?.lastView ?? "";
  return last ? { ...saved, hash: last } : saved;
}

function rememberHash(url: string) {
  if (reloading || !shown || !version) return;
  let hash = "";
  try {
    hash = new URL(url).hash;
  } catch {
    return;
  }
  if (hash === "#") hash = "";
  session?.noteHash(hash);
  if (version.target.kind !== "compare") store().setLastView(shown.path, hash);
  viewStore().updateHash(version.project, version.key, hash);
}

function stopFreshness() {
  treeWatch?.stop();
  treeWatch = null;
  headPoll?.stop();
  headPoll = null;
}

function stopWork() {
  generation += 1;
  rescanEpoch += 1;
  scanSlot.kill?.();
  session?.stop();
  session = null;
  stopFreshness();
  version = null;
  viewerWanted = false;
  switcherOpen = false;
  compareOpen = false;
  pendingUpdate = null;
  shownFingerprint = "";
  fingerprintReady = false;
  shownFiles = new Map();
  flushShown();
  send("toast", null);
  applyBounds();
}

function noteUnwatched() {
  if (!shown) return;
  if ((shown.statusLine ?? "").includes("not watching for changes")) return;
  shown = {
    ...shown,
    statusLine: shown.statusLine ? `${shown.statusLine} · not watching for changes` : "not watching for changes",
  };
  publishProject();
}

function makeSession(): ProjectSession {
  return new ProjectSession({
    rebuild: (root, cbi) => rebuildViewer({
      root,
      cbi,
      ref: version?.ref ?? null,
      run: (bin, args, cwd, onLine) => runCbi(bin, args, cwd, onLine, SCAN_TIMEOUT_MS, scanSlot),
      onPhase: () => undefined,
      onLine: () => undefined,
    }),
    // A directory watch on macOS does not report writes to a file that is already there.
    watch: (dir, onName) => {
      const watcher = fs.watch(path.join(dir, "model.db"), { persistent: true }, () => onName("model.db"));
      watcher.on("error", () => undefined);
      return watcher;
    },
    loadViewer: async (file) => {
      if (!version) return;
      await offerBuilt(file, modelDbPath(version.cwd, version.project, version.ref, version.head));
    },
    onStatus: (status) => {
      if (!shown || !version) return;
      shown = {
        ...shown,
        tasks: status.open_tasks,
        statusLine: formatScanned(status.scanned_at, tasksWaiting(status.open_tasks)),
        instruction: version.ref ? refInstruction(version.project, version.ref) : agentInstruction(version.cwd),
      };
      publishProject();
    },
    onProgress: (_phase: Phase, error?: string) => {
      if (error) send("toast", errorToast(error));
    },
  });
}

function watchName(name: string | Buffer | null): string | null {
  if (typeof name === "string") return name;
  if (name) return name.toString();
  return null;
}

function startFreshness() {
  stopFreshness();
  // A comparison viewer shares the worktree viewer path. A watch rebuild would drop the diff.
  if (!version || version.target.kind === "remote" || version.target.kind === "compare") return;
  const watched = version;
  const gen = generation;
  const epoch = rescanEpoch;
  if (watched.target.kind === "branch") {
    const name = watched.target.name;
    headPoll = new BranchPoll({
      head: async () => {
        if (scanSlot.kill || gen !== generation || !version || version.key !== watched.key) return version?.head ?? null;
        const found = lookupCbi();
        if (!found.ok) return null;
        const listed = await loadInventory(watched.project, found.path);
        if (gen !== generation || !version || version.key !== watched.key || !listed) return null;
        inventory = listed;
        publishVersions();
        return listed.branches.find((branch) => branch.name === name)?.head ?? null;
      },
      onMove: (head) => {
        if (!version || version.key !== watched.key) return;
        version = { ...version, head, target: { ...version.target, head } };
        return requestRescan(gen, watched.key);
      },
    });
    headPoll.start(watched.head);
    return;
  }
  treeWatch = new WorktreeWatch({
    watch: (dir, onName) => {
      const subs: { close(): void }[] = [];
      const arm = (recursive: boolean) => {
        try {
          const watcher = fs.watch(dir, { recursive, persistent: true }, (_event, name) => onName(watchName(name)));
          watcher.on("error", () => noteUnwatched());
          subs.push(watcher);
        } catch {
          // The recursive watch is the one macOS can refuse. The flat watch still covers the root.
        }
      };
      // A flat watch sees files in the root. The recursive watch sees nested files, and on macOS it sometimes drops an event.
      arm(false);
      arm(true);
      if (subs.length === 0) {
        noteUnwatched();
        return { close() {} };
      }
      return { close() { for (const watcher of subs) watcher.close(); } };
    },
    onFire: () => {
      if (gen !== generation || rescanEpoch !== epoch || !version || version.key !== watched.key) return;
      return requestRescan(gen, watched.key);
    },
  });
  treeWatch.start(watched.cwd);
}

function viewerFile(mapped: { viewer: string; commit: string | null }, cwd: string, project: string, ref: string | null): string | null {
  if (mapped.viewer && fs.existsSync(mapped.viewer)) return path.resolve(mapped.viewer);
  const fallback = ref && mapped.commit
    ? path.join(project, ".cbi", "refs", mapped.commit, "viewer", "index.html")
    : path.join(cwd, ".cbi", "viewer", "index.html");
  return fs.existsSync(fallback) ? fallback : null;
}

function modelDbPath(cwd: string, project: string, ref: string | null, head: string): string {
  if (ref && /^[0-9a-f]{40}$/.test(head)) return path.join(project, ".cbi", "refs", head, "model.db");
  return path.join(cwd, ".cbi", "model.db");
}

async function readCheapStatus(db: string): Promise<StatusJson | null> {
  const text = await querySqlite(db, statusQuery());
  if (text === null) return null;
  const parsed = parseStatusTable(text);
  return { scanned_at: parsed.scanned_at, nodes: {}, open_tasks: parsed.open_tasks };
}

async function readFileStates(db: string): Promise<Map<string, string>> {
  const text = await querySqlite(db, fileStateQuery());
  if (text === null) return new Map();
  return parseFileStates(text);
}

async function fingerprintViewer(index: string): Promise<string> {
  const dir = path.dirname(index);
  const sources: string[] = [];
  for (const name of ["data/concepts.js", "data/tree.js", "data/diff.js"]) {
    try {
      sources.push(await fs.promises.readFile(path.join(dir, name), "utf8"));
    } catch {
      sources.push("");
    }
  }
  return payloadFingerprint(sources);
}

async function rememberShown(index: string, db: string) {
  shownFingerprint = await fingerprintViewer(index);
  shownFiles = await readFileStates(db);
  fingerprintReady = shownFingerprint !== "";
}

async function offerBuilt(index: string, db: string) {
  if (!fingerprintReady || !version) return;
  const next = await fingerprintViewer(index);
  if (!version) return;
  const toast = updateToast(countChangedFiles(shownFiles, await readFileStates(db)), shownFingerprint, next);
  if (!toast || !version) return;
  pendingUpdate = { index, fingerprint: next };
  send("toast", toast);
}

async function acceptUpdate() {
  const pending = pendingUpdate;
  const current = version;
  if (!pending || !current) return;
  pendingUpdate = null;
  send("toast", null);
  await captureCurrent();
  if (!version || version.key !== current.key) return;
  const saved = viewStore().get(current.project, current.key);
  try {
    await loadViewer(pending.index, saved.hash.replace(/^#/, ""));
  } catch (err) {
    send("toast", errorToast(err instanceof Error ? err.message : String(err)));
    return;
  }
  if (!version || version.key !== current.key) return;
  await applyDrawer(saved);
  shownFingerprint = pending.fingerprint;
  version = { ...version, viewerIndex: pending.index, modelDir: modelHome(pending.index) };
  shownFiles = await readFileStates(modelDbPath(version.cwd, version.project, version.ref, version.head));
  fingerprintReady = shownFingerprint !== "";
}

function rememberSnapshot(project: string, branch: string, status: StatusJson) {
  const summary = taskSummary({ folderExists: true, modelExists: true, status });
  store().setSnapshot(project, {
    cachedBranch: branch && branch !== "detached" ? branch : null,
    cachedTaskState: summary.taskState,
    cachedTaskCount: summary.taskCount,
    cachedMissing: false,
  });
  publishRecents();
}

async function applyCheapStatus(gen: number, db: string) {
  const status = await readCheapStatus(db);
  if (gen !== generation || !status || !shown || !version) return;
  shown = {
    ...shown,
    tasks: status.open_tasks,
    statusLine: formatScanned(status.scanned_at, tasksWaiting(status.open_tasks)),
    instruction: version.ref ? refInstruction(version.project, version.ref) : agentInstruction(version.cwd),
  };
  publishProject();
  rememberSnapshot(version.project, branchOf(version.target), status);
}

function adoptInventory(listed: Inventory) {
  inventory = listed;
  versionError = null;
  if (version) {
    const fresh = targetFromKey(version.key, listed);
    if (fresh && keyOf(fresh) === version.key) {
      version = { ...version, target: fresh, head: fresh.head || version.head };
      if (shown) {
        shown = {
          ...shown,
          branch: branchOf(fresh),
          versionLabel: labelOf(fresh),
          readOnly: readOnlyTarget(fresh),
        };
        publishProject();
      }
    }
  }
  publishVersions();
}

function verifyCommit(repo: string, ref: string): string | null {
  const args = verifyCommitArgv(ref);
  if (!args) return null;
  try {
    const sha = execFileSync(commandExecutable("git"), args, {
      cwd: repo,
      encoding: "utf8",
      timeout: 15_000,
      shell: false,
      stdio: ["ignore", "pipe", "pipe"],
    }).trim();
    return /^[0-9a-f]{40}$/.test(sha) ? sha : null;
  } catch {
    return null;
  }
}

function viewerIsCompare(index: string): boolean {
  try {
    return isCompareScript(fs.readFileSync(path.join(path.dirname(index), "data", "diff.js"), "utf8"));
  } catch {
    return false;
  }
}

/** Scan and build behind the map. A different build becomes a toast; the viewer stays until Show. */
async function rescan(gen: number, key: string) {
  if (gen !== generation || !version || version.key !== key) return;
  const epoch = rescanEpoch;
  const current = version;
  const db = modelDbPath(current.cwd, current.project, current.ref, current.head);
  const before = new Map(shownFiles);
  await captureCurrent();
  if (gen !== generation || rescanEpoch !== epoch || !version || version.key !== key) return;
  session?.stop();
  session = null;
  if (gen !== generation || rescanEpoch !== epoch) return;

  let failed = "";
  try {
    const mapped = await mapVersion({
      root: current.cwd,
      cbi: current.cbi,
      needsInit: false,
      ref: current.ref,
      run: (bin, args, cwd, onLine) => runCbi(bin, args, cwd, onLine, SCAN_TIMEOUT_MS, scanSlot),
      onPhase: () => undefined,
      onLine: () => undefined,
    });
    if (gen !== generation || rescanEpoch !== epoch || !version || version.key !== key) return;
    if (!mapped.ok) {
      failed = mapped.error;
    } else {
      const index = viewerFile(mapped, current.cwd, current.project, current.ref);
      if (!index) {
        failed = "cbi build did not write the viewer.";
      } else {
        const head = mapped.commit || version.head;
        version = {
          ...version,
          head,
          target: { ...version.target, head },
        };
        if (shown) {
          shown = {
            ...shown,
            statusLine: formatScanned(mapped.status.scanned_at, tasksWaiting(mapped.status.open_tasks)),
            tasks: mapped.status.open_tasks,
            instruction: version.ref ? refInstruction(version.project, version.ref) : agentInstruction(version.cwd),
          };
          publishProject();
        }
        rememberSnapshot(version.project, branchOf(version.target), mapped.status);
        if (fingerprintReady) {
          const next = await fingerprintViewer(index);
          const toast = updateToast(countChangedFiles(before, await readFileStates(db)), shownFingerprint, next);
          if (toast && gen === generation && rescanEpoch === epoch && version?.key === key) {
            pendingUpdate = { index, fingerprint: next };
            send("toast", toast);
          }
        }
        const listed = await loadInventory(current.project, current.cbi);
        if (gen === generation && rescanEpoch === epoch && listed) adoptInventory(listed);
      }
    }
  } catch (err) {
    if (gen !== generation || rescanEpoch !== epoch) return;
    failed = err instanceof Error ? err.message : String(err);
  } finally {
    const still = gen === generation && rescanEpoch === epoch && version?.key === key;
    if (still && failed) send("toast", errorToast(failed));
    if (still && version && optsWatch(version)) {
      session = makeSession();
      session.noteHash(viewStore().get(version.project, version.key).hash);
      try {
        session.startWatch(version.cwd, version.cbi, { modelDir: version.modelDir, viewerIndex: version.viewerIndex });
      } catch {
        noteUnwatched();
      }
    }
  }
}

function optsWatch(current: OpenVersion): boolean {
  return current.watchModel !== false;
}

function requestRescan(gen: number, key: string): Promise<void> {
  const run = rescanTail.then(async () => {
    await shownReady;
    return rescan(gen, key);
  });
  rescanTail = run.then(() => undefined, () => undefined);
  return run;
}

async function beginNavigation(): Promise<number> {
  const gen = ++generation;
  rescanEpoch += 1;
  scanSlot.kill?.();
  pendingUpdate = null;
  fingerprintReady = false;
  flushShown();
  send("toast", null);
  await captureCurrent();
  if (gen !== generation) return gen;
  session?.stop();
  session = null;
  stopFreshness();
  version = null;
  viewerWanted = false;
  switcherOpen = false;
  applyBounds();
  return gen;
}

async function showStart() {
  const gen = generation;
  await captureCurrent();
  if (gen !== generation) return;
  stopWork();
  comparisonReturn = null;
  shown = null;
  send("project", null);
  publishVersions();
}

async function loadVersion(gen: number, opts: {
  project: string;
  displayName: string;
  target: Target;
  cbi: string;
  hash?: string;
  trustRef?: boolean;
  watch?: boolean;
  /** Full-screen progress. Leaving a comparison uses this, because that file is the diff. */
  cover?: boolean;
}) {
  if (gen !== generation) return;
  comparisonReturn = null;
  const target = opts.target;
  const ref = refOf(target);
  if (ref && !opts.trustRef && !usableRef(ref)) {
    sendProgress({ phase: "error", error: "That ref cannot be scanned." });
    return;
  }
  const cwd = target.kind === "worktree" ? target.path : opts.project;
  const key = keyOf(target);
  const builtRaw = viewerForTarget({
    cwd,
    project: opts.project,
    ref,
    head: target.head,
    exists: (file) => fs.existsSync(file),
  });
  const built = builtRaw && !viewerIsCompare(builtRaw) ? builtRaw : null;
  const compact = opts.cover !== true;
  const info: ProjectInfo = {
    path: opts.project,
    displayName: opts.displayName,
    branch: branchOf(target),
    versionLabel: labelOf(target),
    readOnly: readOnlyTarget(target),
    instant: Boolean(built),
    cover: !built && opts.cover === true,
  };
  send("opening", info);
  if (built) {
    await showBuilt(gen, { ...opts, target, cwd, ref, key, index: built });
    return;
  }
  sendProgress({ phase: "scan", compact });
  const mapped = await mapVersion({
    root: cwd,
    cbi: opts.cbi,
    needsInit: !fs.existsSync(path.join(cwd, ".cbi", "ignore")),
    ref,
    run: (bin, args, dir, onLine) => runCbi(bin, args, dir, onLine, SCAN_TIMEOUT_MS, scanSlot),
    onPhase: (phase) => {
      if (gen === generation) sendProgress({ phase, compact });
    },
    onLine: (phase, line) => {
      if (gen === generation) sendProgress({ phase, line, compact });
    },
  });
  if (gen !== generation) return;
  if (!mapped.ok) {
    sendProgress({ phase: "error", error: mapped.error, compact });
    return;
  }
  const index = viewerFile(mapped, cwd, opts.project, ref);
  if (!index) {
    sendProgress({ phase: "error", error: "cbi build did not write the viewer.", compact });
    return;
  }
  const head = mapped.commit || target.head;
  const saved = savedViewFor(opts.project, key, target);
  const hash = opts.hash ?? saved.hash;
  version = {
    project: opts.project,
    displayName: store().get(opts.project)?.displayName ?? opts.displayName,
    key,
    target: { ...target, head },
    cwd,
    ref,
    cbi: opts.cbi,
    viewerIndex: index,
    modelDir: modelHome(index),
    head,
    watchModel: opts.watch !== false,
  };
  shown = {
    path: opts.project,
    displayName: version.displayName,
    branch: branchOf(version.target),
    versionLabel: labelOf(version.target),
    readOnly: readOnlyTarget(version.target),
    statusLine: formatScanned(mapped.status.scanned_at, tasksWaiting(mapped.status.open_tasks)),
    tasks: mapped.status.open_tasks,
    instruction: ref ? refInstruction(opts.project, ref) : agentInstruction(cwd),
  };
  session = makeSession();
  session.noteHash(hash);
  holdShown();
  startFreshness();
  try {
    await loadViewer(index, hash.replace(/^#/, ""));
  } catch (err) {
    if (gen !== generation) return;
    flushShown();
    stopFreshness();
    version = null;
    sendProgress({ phase: "error", error: err instanceof Error ? err.message : String(err), compact });
    return;
  }
  if (gen !== generation || !version) {
    flushShown();
    return;
  }
  await applyDrawer({ ...saved, hash });
  applyBounds();
  await rememberShown(index, modelDbPath(cwd, opts.project, ref, head));
  flushShown();
  if (gen !== generation || !version) return;
  if (opts.watch !== false) {
    try {
      session.startWatch(cwd, opts.cbi, { modelDir: version.modelDir, viewerIndex: index });
    } catch (err) {
      send("toast", errorToast(err instanceof Error ? err.message : "Could not watch the model."));
    }
  }
  if (gen !== generation) return;
  viewStore().setLastKey(opts.project, key);
  rememberSnapshot(opts.project, branchOf(version.target), mapped.status);
  const listed = await loadInventory(opts.project, opts.cbi);
  if (gen !== generation) return;
  if (listed) adoptInventory(listed);
  publishProject();
  sendProgress({ phase: "ready" });
}

async function showBuilt(gen: number, opts: {
  project: string;
  displayName: string;
  target: Target;
  cbi: string;
  hash?: string;
  watch?: boolean;
  cwd: string;
  ref: string | null;
  key: string;
  index: string;
}) {
  const saved = savedViewFor(opts.project, opts.key, opts.target);
  const hash = opts.hash ?? saved.hash;
  const cached = store().get(opts.project);
  version = {
    project: opts.project,
    displayName: store().get(opts.project)?.displayName ?? opts.displayName,
    key: opts.key,
    target: opts.target,
    cwd: opts.cwd,
    ref: opts.ref,
    cbi: opts.cbi,
    viewerIndex: opts.index,
    modelDir: modelHome(opts.index),
    head: opts.target.head,
    watchModel: opts.watch !== false,
  };
  shown = {
    path: opts.project,
    displayName: version.displayName,
    branch: branchOf(opts.target),
    versionLabel: labelOf(opts.target),
    readOnly: readOnlyTarget(opts.target),
    statusLine: cached?.cachedTaskState === "waiting" ? "tasks waiting" : "",
    tasks: {},
    instruction: opts.ref ? refInstruction(opts.project, opts.ref) : agentInstruction(opts.cwd),
    instant: true,
  };
  publishProject();
  const db = modelDbPath(opts.cwd, opts.project, opts.ref, opts.target.head);
  const statusPromise = applyCheapStatus(gen, db);
  holdShown();
  startFreshness();
  trace("viewer load start");
  try {
    await loadViewer(opts.index, hash.replace(/^#/, ""));
  } catch (err) {
    flushShown();
    if (gen !== generation) return;
    stopFreshness();
    version = null;
    sendProgress({ phase: "error", error: err instanceof Error ? err.message : String(err), compact: true });
    return;
  }
  if (gen !== generation || !version) {
    flushShown();
    return;
  }
  trace("viewer load end");
  await applyDrawer({ ...saved, hash });
  applyBounds();
  await statusPromise;
  if (gen !== generation || !version) {
    flushShown();
    return;
  }
  trace("cheap status");
  viewStore().setLastKey(opts.project, opts.key);
  sendProgress({ phase: "ready" });
  trace("ready");
  void (async () => {
    await rememberShown(opts.index, db);
    flushShown();
    if (gen !== generation || !version || version.key !== opts.key) return;
    if (!inventory) {
      const listed = await loadInventory(opts.project, opts.cbi);
      if (gen === generation && version?.key === opts.key && listed) adoptInventory(listed);
    }
    if (gen !== generation || !version || version.key !== opts.key) return;
    await requestRescan(gen, opts.key);
  })();
}

function pickedFolder(input: string): string {
  try {
    const st = fs.statSync(input);
    const folder = st.isFile() ? path.dirname(input) : input;
    return fs.realpathSync(folder);
  } catch {
    return path.resolve(input);
  }
}

function focusWindow() {
  revealWindow(win, revealFor(headless, false));
}

function revealLink() {
  revealWindow(win, revealFor(headless, true));
}

function refuse(message: string) {
  revealLink();
  send("open-error", message);
  if (shown) sendProgress({ phase: "error", error: message });
}

async function openFolder(input: string) {
  const gen = await beginNavigation();
  if (gen !== generation) return;
  trace("open start");
  const resolved = resolveProject(input);
  trace("git resolve");
  if (gen !== generation) return;
  if (!resolved.ok) {
    send("open-error", resolved.error);
    return;
  }
  const recent = store().open(resolved.main);
  publishRecents();
  const found = lookupCbi();
  if (!found.ok) {
    send("open-error", found.error);
    return;
  }
  if (openProject !== resolved.main) {
    remotes = null;
    inventory = null;
    versionError = null;
    openProject = resolved.main;
  }
  const picked = pickedFolder(input);
  const lastKey = viewStore().lastKey(resolved.main);
  let branchCommit: string | null = null;
  if (path.resolve(picked) === path.resolve(resolved.main) && lastKey?.startsWith("branch:")) {
    branchCommit = verifyCommit(resolved.main, lastKey.slice("branch:".length));
  }
  const instant = instantOpen({
    project: resolved.main,
    picked,
    lastKey,
    branchCommit,
    exists: (file) => fs.existsSync(file),
  });
  let target: Target;
  if (instant?.kind === "branch" && instant.branchName && instant.commit) {
    target = { kind: "branch", name: instant.branchName, head: instant.commit };
  } else if (instant) {
    const branch = instant.cwd === resolved.main ? (recent.cachedBranch || resolved.branch) : resolved.branch;
    target = { kind: "worktree", path: instant.cwd, branch, lane: branch, head: "" };
  } else {
    send("opening", {
      path: resolved.main,
      displayName: recent.displayName,
      branch: recent.cachedBranch || resolved.branch,
    });
    sendProgress({ phase: "scan", compact: true });
    const listed = await loadInventory(resolved.main, found.path);
    if (gen !== generation) return;
    if (listed) inventory = listed;
    else versionError = "Could not list worktrees.";
    target = initialTarget({
      inventory,
      main: resolved.main,
      picked,
      branch: resolved.branch,
      lastKey,
    });
    publishVersions();
  }
  await loadVersion(gen, {
    project: resolved.main,
    displayName: recent.displayName,
    target,
    cbi: found.path,
  });
}

async function selectVersion(key: string) {
  const choice = choices.find((entry) => entry.key === key);
  if (!choice || !openProject) return;
  let target = choice.target;
  if (inventory && !choice.key.startsWith("remote:")) {
    const fresh = targetFromKey(choice.key, inventory);
    if (fresh) target = fresh;
  }
  if (version && keyOf(target) === version.key) return;
  const project = openProject;
  const displayName = shown?.displayName ?? store().get(project)?.displayName ?? path.basename(project);
  const found = lookupCbi();
  if (!found.ok) {
    send("open-error", found.error);
    return;
  }
  const gen = await beginNavigation();
  await loadVersion(gen, { project, displayName, target, cbi: found.path });
}

async function refreshVersions() {
  if (!openProject) return;
  const found = lookupCbi();
  if (!found.ok) {
    versionError = found.error;
    publishVersions();
    return;
  }
  const listed = await loadInventory(openProject, found.path);
  if (!listed) {
    versionError = "Could not list worktrees.";
    publishVersions();
    return;
  }
  inventory = listed;
  versionError = null;
  publishVersions();
}

/** User-started `git fetch --prune`, then a read of remote-tracking refs. No other git writes. */
async function fetchRemotes() {
  if (!openProject || fetching) return;
  const project = openProject;
  const gen = generation;
  fetching = true;
  versionError = null;
  publishVersions();
  try {
    assertRemoteArgv(FETCH_ARGV);
    const run = await runProcess("git", [...FETCH_ARGV], project, () => undefined, FETCH_TIMEOUT_MS);
    if (openProject !== project || gen !== generation) return;
    if (run.code !== 0) {
      versionError = (run.stderr || run.stdout || "git fetch failed.").trim();
      return;
    }
    assertRemoteArgv(REMOTES_ARGV);
    const listed = await runProcess("git", [...REMOTES_ARGV], project, () => undefined, STATUS_TIMEOUT_MS);
    if (openProject !== project || gen !== generation) return;
    if (listed.code !== 0) {
      versionError = (listed.stderr || "Could not list remote branches.").trim();
      return;
    }
    remotes = parseRemoteRefs(listed.stdout);
    versionError = null;
    const openRemote = version?.target.kind === "remote" ? version.target : null;
    const moved = openRemote ? remotes.find((item) => item.name === openRemote.name) : undefined;
    publishVersions();
    if (moved && version && moved.head !== version.head) {
      version = { ...version, head: moved.head, target: { ...version.target, head: moved.head } };
      await requestRescan(generation, version.key);
    }
  } catch (err) {
    if (openProject === project) versionError = err instanceof Error ? err.message : String(err);
  } finally {
    fetching = false;
    if (openProject === project) publishVersions();
  }
}

function targetForLink(opened: { cwd: string; branch: string; refArgs: string[] }): Target {
  if (opened.refArgs.length === 0) {
    const found = inventory?.worktrees.find((worktree) => samePath(worktree.path, opened.cwd));
    if (found) return worktreeTarget(found);
    const branch = opened.branch === "detached" ? null : opened.branch;
    return { kind: "worktree", path: opened.cwd, branch, lane: branch, head: "" };
  }
  const name = opened.refArgs[opened.refArgs.length - 1] ?? opened.branch;
  const local = inventory?.branches.some((branch) => branch.name === name) ?? false;
  if (local || !name.includes("/")) return { kind: "branch", name, head: "" };
  return { kind: "remote", name, head: "" };
}

function refLabel(ref: string): string {
  return isCommitSha(ref) ? ref.slice(0, 12) : ref;
}

/** Last worktree or branch for this project, or the main worktree when nothing has been opened. */
function fallbackTarget(project: string): Target {
  if (inventory) {
    return initialTarget({
      inventory,
      main: project,
      picked: project,
      branch: null,
      lastKey: viewStore().lastKey(project),
    });
  }
  return { kind: "worktree", path: project, branch: null, lane: null, head: "" };
}

function currentReturn(project: string): Target {
  if (version?.project === project && version.target.kind !== "compare") return version.target;
  if (version?.project === project && comparisonReturn) return comparisonReturn;
  return fallbackTarget(project);
}

function ghFailure(stderr: string, stdout: string): string {
  const detail = (stderr || stdout).trim();
  if (detail.includes("ENOENT")) return "gh is not on PATH";
  return detail || "gh failed";
}

interface CompareLoad {
  project: string;
  displayName: string;
  cbi: string;
  base: string;
  head: string;
  label: string;
  node: string | null;
  returnTo: Target;
}

/**
 * Scan both commits and show `cbi build --compare`. Does not watch the worktree:
 * a rebuild without `--compare` would replace the diff viewer.
 * `comparisonReturn` is set before the first await so Back works during the build.
 */
async function loadComparison(gen: number, opts: CompareLoad): Promise<{ ok: true } | { ok: false; error: string }> {
  if (gen !== generation) return { ok: true };
  if (!comparisonReturn) comparisonReturn = opts.returnTo;
  const backTarget = comparisonReturn;
  const target: Target = { kind: "compare", base: opts.base, head: opts.head, label: opts.label };
  const key = keyOf(target);
  send("opening", {
    path: opts.project,
    displayName: opts.displayName,
    branch: "",
    versionLabel: opts.label,
    readOnly: true,
    comparing: true,
    backLabel: labelOf(backTarget),
    cover: true,
  });
  const mapped = await mapCompare({
    root: opts.project,
    cbi: opts.cbi,
    needsInit: !fs.existsSync(path.join(opts.project, ".cbi", "ignore")),
    base: opts.base,
    head: opts.head,
    run: (bin, args, dir, onLine) => runCbi(bin, args, dir, onLine, SCAN_TIMEOUT_MS, scanSlot),
    onPhase: (phase) => {
      if (gen === generation) sendProgress({ phase });
    },
    onLine: (phase, line) => {
      if (gen === generation) sendProgress({ phase, line });
    },
  });
  if (gen !== generation) return { ok: true };
  if (!mapped.ok) {
    sendProgress({ phase: "error", error: mapped.error });
    return { ok: false, error: mapped.error };
  }
  const printed = mapped.viewer && fs.existsSync(mapped.viewer) ? path.resolve(mapped.viewer) : "";
  const index = printed || path.join(opts.project, ".cbi", "viewer", "index.html");
  if (!fs.existsSync(index)) {
    const error = "cbi build did not write the viewer.";
    sendProgress({ phase: "error", error });
    return { ok: false, error };
  }
  const saved = viewStore().get(opts.project, key);
  const bare = saved.hash.replace(/^#/, "");
  const hash = opts.node ? viewerLocation(opts.node, bare || null) : saved.hash;
  if (opts.node) viewStore().updateHash(opts.project, key, hash.startsWith("#") ? hash : `#${hash}`);
  version = {
    project: opts.project,
    displayName: store().get(opts.project)?.displayName ?? opts.displayName,
    key,
    target,
    cwd: opts.project,
    ref: null,
    cbi: opts.cbi,
    viewerIndex: index,
    modelDir: modelHome(index),
    head: opts.head,
  };
  shown = {
    path: opts.project,
    displayName: version.displayName,
    branch: "",
    versionLabel: opts.label,
    readOnly: true,
    comparing: true,
    backLabel: labelOf(backTarget),
    statusLine: formatScanned(mapped.status.scanned_at, tasksWaiting(mapped.status.open_tasks)),
    tasks: mapped.status.open_tasks,
    instruction: refInstruction(opts.project, opts.head),
  };
  try {
    await loadViewer(index, hash.replace(/^#/, ""));
  } catch (err) {
    if (gen !== generation) return { ok: true };
    version = null;
    const error = err instanceof Error ? err.message : String(err);
    sendProgress({ phase: "error", error });
    return { ok: false, error };
  }
  if (gen !== generation) return { ok: true };
  await applyDrawer({ ...saved, hash });
  applyBounds();
  const listed = await loadInventory(opts.project, opts.cbi);
  if (gen !== generation) return { ok: true };
  if (listed) {
    inventory = listed;
    versionError = null;
  }
  publishVersions();
  publishProject();
  sendProgress({ phase: "ready" });
  void pushRecents();
  return { ok: true };
}

async function openCompareLink(opened: { project: string; node: string | null; compare: { base: string; head: string; baseSha: string; headSha: string } }) {
  const found = lookupCbi();
  if (!found.ok) {
    refuse(found.error);
    return;
  }
  const sides = opened.compare;
  if (!isCommitSha(sides.baseSha) || !isCommitSha(sides.headSha)) {
    refuse("unknown ref");
    return;
  }
  const recent = store().open(opened.project);
  void pushRecents();
  if (openProject !== opened.project) {
    remotes = null;
    inventory = null;
    versionError = null;
    comparisonReturn = null;
    openProject = opened.project;
  }
  const listed = await loadInventory(opened.project, found.path);
  if (openProject !== opened.project) return;
  if (listed) inventory = listed;
  else if (!inventory) versionError = "Could not list worktrees.";
  const returnTo = currentReturn(opened.project);
  if (!comparisonReturn) comparisonReturn = returnTo;
  const gen = await beginNavigation();
  if (gen !== generation || openProject !== opened.project) return;
  publishVersions();
  await loadComparison(gen, {
    project: opened.project,
    displayName: recent.displayName,
    cbi: found.path,
    base: sides.baseSha,
    head: sides.headSha,
    label: `${refLabel(sides.base)}..${refLabel(sides.head)}`,
    node: opened.node,
    returnTo,
  });
  revealLink();
}

async function startCompare(spec: unknown): Promise<{ ok: true } | { ok: false; error: string }> {
  if (!openProject) return { ok: false, error: "Open a project first." };
  const project = openProject;
  const started = generation;
  const form = readCompareForm(spec);
  if (!form) return { ok: false, error: "Choose two sides." };
  const plan = planCompare(form, inventory);
  if (!plan.ok) return plan;

  let baseRef = "";
  let headRef = "";
  let label = "";
  if (plan.mode === "pr") {
    const args = prViewArgs(plan.number);
    if (!args) return { ok: false, error: "pr must be a pull request number" };
    const run = await runProcess("gh", args, project, () => undefined, STATUS_TIMEOUT_MS);
    if (openProject !== project || started !== generation) return { ok: true };
    if (run.code !== 0) return { ok: false, error: ghFailure(run.stderr, run.stdout) };
    const oids = parsePrOids(run.stdout);
    if (!oids.ok) return oids;
    baseRef = oids.base;
    headRef = oids.head;
    label = `PR ${plan.number}`;
  } else {
    baseRef = plan.base.ref;
    headRef = plan.head.ref;
    label = `${plan.base.label}..${plan.head.label}`;
  }

  const baseCommit = verifyRef(project, baseRef);
  if (!baseCommit.ok) return baseCommit;
  const headCommit = verifyRef(project, headRef);
  if (!headCommit.ok) return headCommit;
  if (!isCommitSha(baseCommit.sha) || !isCommitSha(headCommit.sha)) return { ok: false, error: "unknown ref" };
  if (openProject !== project || started !== generation) return { ok: true };

  const found = lookupCbi();
  if (!found.ok) return { ok: false, error: found.error };
  const returnTo = currentReturn(project);
  if (!comparisonReturn) comparisonReturn = returnTo;
  const displayName = shown?.displayName ?? store().get(project)?.displayName ?? path.basename(project);
  const gen = await beginNavigation();
  if (gen !== generation || openProject !== project) return { ok: true };
  return loadComparison(gen, {
    project,
    displayName,
    cbi: found.path,
    base: baseCommit.sha,
    head: headCommit.sha,
    label,
    node: null,
    returnTo,
  });
}

async function leaveCompare() {
  const project = openProject;
  if (!project) return;
  const target = comparisonReturn ?? fallbackTarget(project);
  const found = lookupCbi();
  if (!found.ok) {
    send("open-error", found.error);
    return;
  }
  const displayName = shown?.displayName ?? store().get(project)?.displayName ?? path.basename(project);
  const gen = await beginNavigation();
  if (gen !== generation || openProject !== project) return;
  await loadVersion(gen, { project, displayName, target, cbi: found.path, cover: true });
}

let acceptingLinks = false;
const pendingLinks: string[] = [];

function enqueueLink(raw: string) {
  if (!acceptingLinks) pendingLinks.push(raw);
  else void handleDeepLink(raw);
}

function flushLinks() {
  acceptingLinks = true;
  if (pendingLinks.length === 0) {
    const initial = linkFromArgv(process.argv);
    if (initial) pendingLinks.push(initial);
  }
  for (const link of pendingLinks.splice(0)) void handleDeepLink(link);
}

async function handleDeepLink(raw: string) {
  revealLink();
  const result = validateOpen(raw);
  if (!result.ok) {
    refuse(result.error);
    return;
  }
  const opened = result.opened;
  if (opened.compare) {
    await openCompareLink({ project: opened.project, node: opened.node, compare: opened.compare });
    return;
  }
  const same = Boolean(
    version &&
    version.ref === null &&
    opened.refArgs.length === 0 &&
    shown?.path === opened.project &&
    samePath(version.cwd, opened.cwd) &&
    fs.existsSync(opened.viewerIndex),
  );
  const bare = viewerLocation(opened.node, same ? (session?.hash ?? "") : null);
  const stored = bare ? `#${bare}` : "";
  if (same && version) {
    store().open(opened.project);
    void pushRecents();
    session?.noteHash(stored);
    viewStore().updateHash(version.project, version.key, stored);
    store().setLastView(opened.project, stored);
    try {
      await loadViewer(opened.viewerIndex, bare);
    } catch (err) {
      sendProgress({ phase: "error", error: err instanceof Error ? err.message : String(err) });
      return;
    }
    applyBounds();
    revealLink();
    return;
  }
  const found = lookupCbi();
  if (!found.ok) {
    refuse(found.error);
    return;
  }
  const recent = store().open(opened.project);
  if (openProject !== opened.project) {
    remotes = null;
    inventory = null;
    versionError = null;
    openProject = opened.project;
  }
  if (!fs.existsSync(opened.viewerIndex)) {
    const listed = await loadInventory(opened.project, found.path);
    if (listed) inventory = listed;
    else if (!inventory) versionError = "Could not list worktrees.";
  }
  let target = targetForLink(opened);
  const sha = commitFromViewer(opened.viewerIndex);
  if (sha && (target.kind === "branch" || target.kind === "remote")) target = { ...target, head: sha };
  const gen = await beginNavigation();
  if (gen !== generation) return;
  publishVersions();
  await loadVersion(gen, {
    project: opened.project,
    displayName: recent.displayName,
    target,
    cbi: found.path,
    hash: stored,
    trustRef: opened.refArgs.length > 0,
    watch: opened.watch,
  });
  revealLink();
}

// The stock Edit > Copy accelerator handles Cmd/Ctrl+C in the main process, so the
// map never sees it. This item asks the focused page to copy the agent block, and
// falls back to a normal copy when that page has a text selection or is not the map.
function installEditMenu(): void {
  const copy: Electron.MenuItemConstructorOptions = {
    label: "Copy",
    accelerator: "CommandOrControl+C",
    click: () => { void routeFocusedCopy(); },
  };
  const edit: Electron.MenuItemConstructorOptions = {
    label: "Edit",
    submenu: [
      { role: "undo" },
      { role: "redo" },
      { type: "separator" },
      { role: "cut" },
      copy,
      { role: "paste" },
      ...(process.platform === "darwin"
        ? [{ role: "pasteAndMatchStyle" as const }, { role: "delete" as const }, { role: "selectAll" as const }]
        : [{ role: "delete" as const }, { type: "separator" as const }, { role: "selectAll" as const }]),
    ],
  };
  const template: Electron.MenuItemConstructorOptions[] = [
    ...(process.platform === "darwin" ? [{ role: "appMenu" as const }] : []),
    { role: "fileMenu" },
    edit,
    { role: "viewMenu" },
    { role: "windowMenu" },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

async function routeFocusedCopy(): Promise<void> {
  const contents = webContents.getFocusedWebContents();
  if (!contents || contents.isDestroyed()) return;
  let handled = false;
  try {
    handled = Boolean(await contents.executeJavaScript("typeof cbiCopy === 'function' ? cbiCopy() : false"));
  } catch {
    handled = false;
  }
  if (!handled && !contents.isDestroyed()) contents.copy();
}

function createWindow(fromLink = false) {
  const how = revealFor(headless, fromLink);
  const icon = windowIcon(app.getAppPath());
  const quiet = { backgroundThrottling: false as const };
  win = new BrowserWindow({
    width: 1200,
    height: 800,
    minWidth: 800,
    minHeight: 560,
    title: "Codebase Inspector",
    icon,
    show: how === "focus",
    focusable: !(headless && process.platform === "darwin"),
    backgroundColor: nativeTheme.shouldUseDarkColors ? "#161719" : "#f6f6f3",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      ...(headless ? quiet : {}),
    },
  });
  const dock = dockIcon(app.getAppPath(), app.isPackaged);
  if (!headless && process.platform === "darwin" && dock) app.dock?.setIcon(dock);
  viewer = new WebContentsView({
    webPreferences: {
      preload: path.join(__dirname, "viewer-preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      ...(headless ? quiet : {}),
    },
  });
  win.contentView.addChildView(viewer);
  viewer.setVisible(false);
  // The map is a separate page, so its Copy for agent button writes the clipboard itself.
  viewer.webContents.session.setPermissionRequestHandler((_webContents, permission, callback) => {
    callback(permission === "clipboard-sanitized-write");
  });
  viewer.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  viewer.webContents.on("will-navigate", (event, url) => {
    if (!url.startsWith("file:")) event.preventDefault();
  });
  viewer.webContents.on("did-navigate-in-page", (_event, url) => rememberHash(url));

  win.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  win.webContents.on("will-navigate", (event) => event.preventDefault());
  win.on("closed", () => {
    stopWork();
    win = null;
    viewer = null;
  });
  void win.loadFile(path.join(__dirname, "index.html"));
  if (how === "inactive") revealWindow(win, "inactive");
}

function registerIpc() {
  ipcMain.handle("pick-folder", async () => {
    // The smoke test sets this so it can click Open folder without a system dialog.
    if (process.env.CBI_PICK_FOLDER) return process.env.CBI_PICK_FOLDER;
    if (!win) return null;
    const result = await dialog.showOpenDialog(win, { title: "Open a repository", properties: ["openDirectory"] });
    return result.canceled ? null : result.filePaths[0] ?? null;
  });
  ipcMain.handle("open-path", async (_event, input: unknown) => {
    if (typeof input === "string" && input) await openFolder(input);
  });
  ipcMain.on("dropped-path", (_event, input: unknown) => {
    if (typeof input === "string" && input) void openFolder(input);
  });
  ipcMain.handle("list-recents", () => {
    const views = cachedViews();
    setTimeout(() => { void refreshRecents(); }, 0);
    return views;
  });
  ipcMain.handle("toast-action", () => acceptUpdate());
  ipcMain.on("toast-dismiss", () => {
    pendingUpdate = null;
    send("toast", null);
  });
  ipcMain.handle("pin", async (_event, projectPath: unknown, pinned: unknown) => {
    if (typeof projectPath !== "string" || typeof pinned !== "boolean") return;
    store().setPinned(projectPath, pinned);
    publishRecents();
  });
  ipcMain.handle("rename", async (_event, projectPath: unknown, name: unknown) => {
    if (typeof projectPath !== "string" || typeof name !== "string") return;
    try {
      store().rename(projectPath, name);
    } catch (err) {
      send("open-error", err instanceof Error ? err.message : String(err));
      return;
    }
    if (shown?.path === projectPath) {
      shown = { ...shown, displayName: name.trim() };
      if (version?.project === projectPath) version = { ...version, displayName: name.trim() };
      publishProject();
    }
    publishRecents();
  });
  ipcMain.handle("remove", async (_event, projectPath: unknown) => {
    if (typeof projectPath !== "string") return;
    store().remove(projectPath);
    if (shown?.path === projectPath) await showStart();
    publishRecents();
  });
  ipcMain.handle("relocate", async (_event, projectPath: unknown) => {
    if (!win || typeof projectPath !== "string") return;
    const picked = await dialog.showOpenDialog(win, { title: "Locate the repository", properties: ["openDirectory"] });
    if (picked.canceled || !picked.filePaths[0]) return;
    const resolved = resolveProject(picked.filePaths[0]);
    if (!resolved.ok) {
      send("open-error", resolved.error);
      return;
    }
    store().relocate(projectPath, resolved.main);
    publishRecents();
    void refreshRecents();
  });
  ipcMain.handle("get-cbi", () => cbiInfo());
  ipcMain.handle("get-editor", () => describeEditor(readEditorSettings(editorSettingsPath())));
  ipcMain.handle("set-editor", (_event, input: unknown) => {
    const body = input && typeof input === "object" ? input as { editor?: unknown; template?: unknown } : {};
    const choice = typeof body.editor === "string" ? body.editor : "";
    const template = typeof body.template === "string" ? body.template : "";
    const current = readEditorSettings(editorSettingsPath());
    try {
      const next = normalizeChoice(choice, template);
      writeEditorSettings(editorSettingsPath(), {
        editor: next.editor,
        template: next.editor === "custom" ? next.template : template || current.template,
      });
    } catch (err) {
      const message = err instanceof EditorError ? err.message : String(err);
      return { ok: false, error: message, ...describeEditor(readEditorSettings(editorSettingsPath())) };
    }
    return { ok: true, ...describeEditor(readEditorSettings(editorSettingsPath())) };
  });
  ipcMain.handle("open-in-editor", (_event, payload: unknown) => {
    const body = payload && typeof payload === "object" ? payload as { file?: unknown; line?: unknown } : {};
    if (typeof body.file !== "string" || !body.file) return { ok: false, error: "This item has no file." };
    if (!version) return { ok: false, error: "No project is open." };
    const settings = readEditorSettings(editorSettingsPath());
    const ref = refEditorContext(version.target);
    const planned = planViewerOpen({
      file: body.file,
      line: typeof body.line === "number" ? body.line : 1,
      project: version.project,
      targetKind: version.target.kind,
      targetPath: version.target.kind === "worktree" ? version.target.path : null,
      editor: settings.editor,
      template: settings.template,
      pathEnv: process.env.PATH ?? "",
      home: app.getPath("home"),
      isExecutable,
      repo: version.project,
      branch: ref.branch,
      sha: ref.sha,
    });
    if (!planned.ok) return planned;
    try {
      launchEditor(planned.argv);
    } catch (err) {
      return { ok: false, error: err instanceof Error ? err.message : String(err) };
    }
    return planned.notice ? { ok: true, notice: planned.notice } : { ok: true };
  });
  ipcMain.handle("set-cbi", async (_event, cbiPath: unknown) => {
    if (cbiPath !== null && typeof cbiPath !== "string") return cbiInfo();
    const trimmed = typeof cbiPath === "string" ? cbiPath.trim() : "";
    writeSetting(settingsPath(), { cbiPath: trimmed || null });
    publishRecents();
    return cbiInfo();
  });
  ipcMain.handle("browse-cbi", async () => {
    if (!win) return null;
    const result = await dialog.showOpenDialog(win, { title: "Choose the cbi executable", properties: ["openFile"] });
    if (result.canceled || !result.filePaths[0]) return null;
    writeSetting(settingsPath(), { cbiPath: result.filePaths[0] });
    publishRecents();
    return cbiInfo();
  });
  ipcMain.handle("copy", (_event, text: unknown) => {
    if (typeof text === "string") clipboard.writeText(text);
  });
  ipcMain.handle("back", async () => {
    await showStart();
    await pushRecents();
  });
  ipcMain.handle("select-version", async (_event, key: unknown) => {
    if (typeof key === "string" && key) await selectVersion(key);
  });
  ipcMain.handle("refresh-versions", () => refreshVersions());
  ipcMain.handle("fetch-remotes", () => fetchRemotes());
  ipcMain.handle("start-compare", (_event, form: unknown) => startCompare(form));
  ipcMain.handle("leave-compare", () => leaveCompare());
  ipcMain.on("compare-open", (_event, open: unknown) => {
    compareOpen = open === true;
    applyBounds();
  });
  ipcMain.on("switcher-open", (_event, open: unknown) => {
    switcherOpen = open === true;
    applyBounds();
  });
  ipcMain.on("viewer-bounds", (_event, bounds: unknown) => {
    if (!bounds || typeof bounds !== "object") return;
    const rect = bounds as StageBounds;
    if ([rect.x, rect.y, rect.width, rect.height].some((n) => typeof n !== "number" || Number.isNaN(n))) return;
    stageBounds = rect;
    applyBounds();
  });
}

if (process.env.CBI_SKIP_PROTOCOL !== "1") {
  // Dev Electron is `process.defaultApp`; the packaged app registers itself.
  if (process.defaultApp && process.argv.length >= 2) {
    app.setAsDefaultProtocolClient("cbi", process.execPath, [path.resolve(process.argv[1])]);
  } else {
    app.setAsDefaultProtocolClient("cbi");
  }
}

const singleInstance = app.requestSingleInstanceLock();
if (!singleInstance) {
  app.quit();
} else {
  app.on("open-url", (event, url) => {
    event.preventDefault();
    enqueueLink(url);
  });
  // Windows and Linux put a cbi:// URL in argv, on first launch and on
  // second-instance. macOS uses open-url. electron-builder `protocols`
  // registers the scheme, including the Windows registry entry.
  app.on("second-instance", (_event, argv) => {
    const found = linkFromArgv(argv);
    if (!win || win.isDestroyed()) createWindow(found !== null);
    if (found) {
      enqueueLink(found);
      revealLink();
      return;
    }
    // No link: the user launched the app again.
    focusWindow();
  });
  app.whenReady().then(() => {
    installEditMenu();
    registerIpc();
    const fromLink = pendingLinks.length > 0 || linkFromArgv(process.argv) !== null;
    createWindow(fromLink);
    flushLinks();
    yieldFocus();
    // Dock, the app icon, and the menu bar. A link does not come through here
    // when `open -g` launched the process. Headless never shows a window.
    app.on("activate", () => {
      if (headless) return;
      if (BrowserWindow.getAllWindows().length === 0) createWindow(false);
      else focusWindow();
    });
  });
}

app.on("window-all-closed", () => {
  app.quit();
});

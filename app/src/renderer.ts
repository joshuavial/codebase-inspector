interface ProjectInfo {
  path: string;
  displayName: string;
  branch: string;
  versionLabel?: string;
  readOnly?: boolean;
  statusLine?: string;
  comparing?: boolean;
  backLabel?: string;
  instant?: boolean;
  cover?: boolean;
}

interface SwitcherRow {
  key: string;
  group: "worktree" | "branch" | "remote";
  label: string;
  detail: string;
  model: string;
  selected: boolean;
}

interface VersionList {
  entries: SwitcherRow[];
  fetched: boolean;
  fetching: boolean;
  error: string | null;
}

interface ProjectState extends ProjectInfo {
  tasks: Record<string, number>;
  instruction: string;
}

interface RecentView {
  path: string;
  displayName: string;
  pinned: boolean;
  lastOpened: string;
  missing: boolean;
  branch: string | null;
  taskState: "complete" | "waiting" | "unscanned" | "missing" | "unknown";
  taskCount: number;
  refreshing?: boolean;
}

interface Progress {
  phase: "init" | "scan" | "build" | "status" | "ready" | "error";
  line?: string;
  error?: string;
  compact?: boolean;
}

interface ToastPayload {
  kind: "update" | "error";
  message: string;
  action?: string;
  detail?: string;
}

interface CbiInfo {
  setting: string | null;
  resolved: string | null;
  error: string | null;
}

interface EditorSetting {
  editor: string;
  template: string;
  command: string;
  ok?: boolean;
  error?: string;
}

interface StageBounds {
  x: number;
  y: number;
  width: number;
  height: number;
}

type UpdateNotice =
  | { kind: "available"; message: string; notesUrl: string; downloadUrl: string; version: string }
  | { kind: "info"; message: string };

interface CbiApi {
  pickFolder(): Promise<string | null>;
  openPath(projectPath: string): Promise<void>;
  listRecents(): Promise<RecentView[]>;
  pin(projectPath: string, pinned: boolean): Promise<void>;
  rename(projectPath: string, name: string): Promise<void>;
  remove(projectPath: string): Promise<void>;
  relocate(projectPath: string): Promise<void>;
  getCbi(): Promise<CbiInfo>;
  setCbiPath(cbiPath: string | null): Promise<CbiInfo>;
  getEditor(): Promise<EditorSetting>;
  setEditor(settings: { editor: string; template: string }): Promise<EditorSetting>;
  browseCbi(): Promise<CbiInfo | null>;
  copy(text: string): Promise<void>;
  back(): Promise<void>;
  startCompare(form: unknown): Promise<{ ok: true } | { ok: false; error: string }>;
  leaveCompare(): Promise<void>;
  setCompareOpen(open: boolean): void;
  selectVersion(key: string): Promise<void>;
  refreshVersions(): Promise<void>;
  fetchRemotes(): Promise<void>;
  setSwitcherOpen(open: boolean): void;
  setViewerBounds(bounds: StageBounds): void;
  onProgress(cb: (progress: Progress) => void): () => void;
  onOpening(cb: (info: ProjectInfo) => void): () => void;
  onProject(cb: (state: ProjectState | null) => void): () => void;
  onRecents(cb: (items: RecentView[]) => void): () => void;
  onError(cb: (message: string) => void): () => void;
  onVersions(cb: (list: VersionList) => void): () => void;
  onToast(cb: (toast: ToastPayload | null) => void): () => void;
  acceptToast(): Promise<void>;
  dismissToast(): void;
  onUpdateBanner(cb: (notice: UpdateNotice | null) => void): () => void;
  openUpdate(which: "notes" | "download"): Promise<void>;
  skipUpdate(): Promise<void>;
  dismissUpdate(): Promise<void>;
  getUpdateSetting(): Promise<boolean>;
  setUpdateSetting(auto: boolean): Promise<boolean>;
}

interface Window {
  cbi: CbiApi;
}

function must<T extends HTMLElement>(id: string): T {
  const el = document.getElementById(id);
  if (!el) throw new Error(`missing #${id}`);
  return el as T;
}

const start = must<HTMLElement>("start");
const project = must<HTMLElement>("project");
const startError = must<HTMLElement>("start-error");
const recents = must<HTMLElement>("recents");
const recentsEmpty = must<HTMLElement>("recents-empty");
const cbiUsing = must<HTMLElement>("cbi-using");
const cbiError = must<HTMLElement>("cbi-error");
const cbiPath = must<HTMLInputElement>("cbi-path");
const editorChoice = must<HTMLSelectElement>("editor-choice");
const editorTemplate = must<HTMLInputElement>("editor-template");
const editorCustomRow = must<HTMLElement>("editor-custom-row");
const editorPreset = must<HTMLElement>("editor-preset");
const editorError = must<HTMLElement>("editor-error");
const projectName = must<HTMLElement>("project-name");
const projectPath = must<HTMLElement>("project-path");
const versionLabel = must<HTMLElement>("version-label");
const branch = must<HTMLElement>("branch");
const switcher = must<HTMLButtonElement>("switcher");
const switcherWrap = must<HTMLElement>("switcher-wrap");
const switcherPanel = must<HTMLElement>("switcher-panel");
const switcherWorktrees = must<HTMLElement>("switcher-worktrees");
const switcherBranches = must<HTMLElement>("switcher-branches");
const switcherRemotes = must<HTMLElement>("switcher-remotes");
const switcherError = must<HTMLElement>("switcher-error");
const fetchRemotes = must<HTMLButtonElement>("fetch-remotes");
const compareWrap = must<HTMLElement>("compare-wrap");
const compareOpen = must<HTMLButtonElement>("compare-open");
const comparePanel = must<HTMLElement>("compare-panel");
const compareBase = must<HTMLSelectElement>("compare-base");
const compareHead = must<HTMLSelectElement>("compare-head");
const compareBaseRev = must<HTMLInputElement>("compare-base-rev");
const compareHeadRev = must<HTMLInputElement>("compare-head-rev");
const comparePr = must<HTMLInputElement>("compare-pr");
const compareError = must<HTMLElement>("compare-error");
const compareBack = must<HTMLButtonElement>("compare-back");
const readOnly = must<HTMLElement>("readonly");
const scanned = must<HTMLElement>("scanned");
const tasks = must<HTMLElement>("tasks");
const taskCounts = must<HTMLElement>("task-counts");
const instruction = must<HTMLElement>("instruction");
const copy = must<HTMLButtonElement>("copy");
const progress = must<HTMLElement>("progress");
const stage = must<HTMLElement>("stage");
const toast = must<HTMLElement>("toast");
const toastMessage = must<HTMLElement>("toast-message");
const toastAction = must<HTMLButtonElement>("toast-action");
const toastDetails = must<HTMLButtonElement>("toast-details");
const toastDetail = must<HTMLElement>("toast-detail");
const updateBanner = must<HTMLElement>("update-banner");
const updateMessage = must<HTMLElement>("update-message");
const updateNotes = must<HTMLButtonElement>("update-notes");
const updateDownload = must<HTMLButtonElement>("update-download");
const updateSkip = must<HTMLButtonElement>("update-skip");
const updateDismiss = must<HTMLButtonElement>("update-dismiss");
const checkUpdates = must<HTMLInputElement>("check-updates");

let progressPhase = "";

function showError(message: string) {
  startError.hidden = false;
  startError.textContent = message;
}

function clearError() {
  startError.hidden = true;
  startError.textContent = "";
}

function showChrome(info: ProjectInfo) {
  clearError();
  start.hidden = true;
  project.hidden = false;
  projectName.textContent = info.displayName;
  projectPath.textContent = info.path;
  projectPath.title = info.path;
  showVersion(info);
  document.title = info.displayName;
  tasks.hidden = true;
  progressPhase = "";
  progress.textContent = "";
  if (info.instant) {
    project.classList.remove("working");
    progress.classList.remove("compact");
    progress.hidden = true;
  } else if (info.cover) {
    project.classList.add("working");
    progress.classList.remove("compact");
    progress.hidden = false;
  } else {
    project.classList.remove("working");
    progress.classList.add("compact");
    progress.hidden = false;
  }
  reportBounds();
}

function showVersion(info: ProjectInfo) {
  const label = info.versionLabel || info.branch;
  versionLabel.textContent = label;
  versionLabel.hidden = !label || label === info.branch;
  branch.textContent = info.branch;
  branch.hidden = !info.branch;
  readOnly.hidden = !info.readOnly;
  scanned.textContent = info.statusLine ?? "";
  scanned.classList.toggle("stale", (info.statusLine ?? "").includes("tasks waiting"));
  compareBack.hidden = info.comparing !== true;
  compareBack.title = info.backLabel ? `Back to ${info.backLabel}` : "Back";
}

function showStart() {
  closeSwitcher();
  closeCompare();
  project.hidden = true;
  project.classList.remove("working");
  progress.classList.remove("compact");
  toast.hidden = true;
  start.hidden = false;
  document.title = "Codebase Inspector";
  reportBounds();
}

function taskLabel(item: RecentView): string {
  if (item.missing) return "folder missing";
  if (item.taskState === "waiting") return item.taskCount === 1 ? "1 task waiting" : `${item.taskCount} tasks waiting`;
  if (item.taskState === "complete") return "map complete";
  if (item.taskState === "unscanned") return "not scanned";
  return "tasks unknown";
}

function opened(iso: string): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return `opened ${date.toLocaleString()}`;
}

function renderRecents(items: RecentView[]) {
  recents.replaceChildren();
  recentsEmpty.hidden = items.length > 0;
  for (const item of items) {
    const li = document.createElement("li");
    li.dataset.path = item.path;
    li.dataset.name = item.displayName;
    if (item.missing) li.classList.add("missing");
    const name = document.createElement("button");
    name.type = "button";
    name.className = "name";
    name.dataset.act = "open";
    if (item.pinned) {
      const pin = document.createElement("span");
      pin.className = "pin";
      pin.textContent = "pinned";
      name.append(pin);
    }
    name.append(document.createTextNode(item.displayName));
    const meta = document.createElement("div");
    meta.className = "meta";
    const bits = [item.branch, taskLabel(item), opened(item.lastOpened)].filter(Boolean);
    meta.textContent = bits.join(" · ");
    if (item.refreshing) {
      const spin = document.createElement("span");
      spin.className = "row-spinner";
      spin.setAttribute("role", "status");
      spin.setAttribute("aria-label", "Refreshing");
      meta.prepend(spin);
    }
    const pathEl = document.createElement("div");
    pathEl.className = "path";
    pathEl.textContent = item.path;
    const actions = document.createElement("div");
    actions.className = "actions";
    const pin = actionButton(item.pinned ? "Unpin" : "Pin", "pin");
    pin.dataset.pinned = item.pinned ? "true" : "false";
    actions.append(pin, actionButton("Rename", "rename"));
    if (item.missing) actions.append(actionButton("Relocate", "relocate"));
    actions.append(actionButton("Remove", "remove"));
    li.append(name, meta, pathEl, actions);
    recents.append(li);
  }
}

function actionButton(label: string, act: string): HTMLButtonElement {
  const button = document.createElement("button");
  button.type = "button";
  button.dataset.act = act;
  button.textContent = label;
  return button;
}

function renderTasks(state: ProjectState) {
  projectName.textContent = state.displayName;
  taskCounts.replaceChildren();
  const kinds = Object.keys(state.tasks).filter((kind) => state.tasks[kind] > 0).sort();
  tasks.hidden = kinds.length === 0;
  for (const kind of kinds) {
    const li = document.createElement("li");
    li.textContent = `${kind}  ${state.tasks[kind]}`;
    taskCounts.append(li);
  }
  instruction.textContent = state.instruction;
  reportBounds();
}

function renderCbi(info: CbiInfo) {
  cbiPath.value = info.setting ?? "";
  if (info.resolved) {
    cbiUsing.hidden = false;
    cbiUsing.textContent = `Using ${info.resolved}`;
  } else {
    cbiUsing.hidden = true;
    cbiUsing.textContent = "";
  }
  cbiError.hidden = !info.error;
  cbiError.textContent = info.error ?? "";
}

function renderUpdate(notice: UpdateNotice | null) {
  if (!notice) {
    updateBanner.hidden = true;
  } else {
    updateBanner.hidden = false;
    updateMessage.textContent = notice.message;
    const available = notice.kind === "available";
    updateNotes.hidden = !available;
    updateDownload.hidden = !available;
    updateSkip.hidden = !available;
    updateDismiss.hidden = available;
  }
  if (!project.hidden) reportBounds();
}

function renderToast(payload: ToastPayload | null) {
  if (!payload) {
    toast.hidden = true;
    toastDetail.hidden = true;
    reportBounds();
    return;
  }
  toast.hidden = false;
  toastMessage.textContent = payload.message;
  const show = payload.kind === "update" && Boolean(payload.action);
  toastAction.hidden = !show;
  toastAction.textContent = payload.action || "Show";
  toastDetails.hidden = payload.kind !== "error" || !payload.detail;
  toastDetail.hidden = true;
  toastDetail.textContent = payload.detail ?? "";
  reportBounds();
}

function appendProgress(progressEvent: Progress) {
  if (progressEvent.phase === "ready") {
    progress.hidden = true;
    progress.classList.remove("compact");
    project.classList.remove("working");
    reportBounds();
    return;
  }
  if (progressEvent.compact) {
    project.classList.remove("working");
    progress.classList.add("compact");
  } else if (!progress.classList.contains("compact")) {
    project.classList.add("working");
  }
  progress.hidden = false;
  if (progressEvent.error) {
    progress.textContent += `${progress.textContent ? "\n" : ""}${progressEvent.error}`;
  } else {
    if (progressEvent.phase !== progressPhase) {
      progressPhase = progressEvent.phase;
      const label: Partial<Record<Progress["phase"], string>> = {
        init: "Running cbi init",
        scan: "Running cbi scan",
        build: "Running cbi build",
        status: "Reading cbi status",
      };
      const text = label[progressEvent.phase];
      if (text) progress.textContent += `${progress.textContent ? "\n" : ""}${text}`;
    }
    if (progressEvent.line) progress.textContent += `\n${progressEvent.line}`;
  }
  progress.scrollTop = progress.scrollHeight;
  reportBounds();
}

function reportBounds() {
  const rect = stage.getBoundingClientRect();
  window.cbi.setViewerBounds({
    x: rect.x,
    y: rect.y,
    width: rect.width,
    height: rect.height,
  });
}

function beginRename(row: HTMLElement, projectPath: string, current: string) {
  const name = row.querySelector(".name");
  if (!name) return;
  const input = document.createElement("input");
  input.value = current;
  input.setAttribute("aria-label", "Display name");
  name.replaceWith(input);
  input.focus();
  input.select();
  let done = false;
  const finish = (save: boolean) => {
    if (done) return;
    done = true;
    const next = input.value.trim();
    if (save && next && next !== current) void window.cbi.rename(projectPath, next);
    else void window.cbi.listRecents().then(renderRecents);
  };
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") finish(true);
    if (event.key === "Escape") finish(false);
  });
  input.addEventListener("blur", () => finish(true));
}

must<HTMLButtonElement>("open").addEventListener("click", async () => {
  clearError();
  const folder = await window.cbi.pickFolder();
  if (folder) await window.cbi.openPath(folder);
});

start.addEventListener("dragover", () => start.classList.add("drag"));
start.addEventListener("dragleave", () => start.classList.remove("drag"));
start.addEventListener("drop", () => start.classList.remove("drag"));

recents.addEventListener("click", (event) => {
  const button = (event.target as HTMLElement).closest("button");
  const row = button?.closest("li");
  if (!button || !row) return;
  const projectPath = row.dataset.path;
  if (!projectPath) return;
  const act = button.dataset.act;
  if (act === "open") {
    if (row.classList.contains("missing")) return;
    void window.cbi.openPath(projectPath);
  } else if (act === "pin") {
    void window.cbi.pin(projectPath, button.dataset.pinned !== "true");
  } else if (act === "rename") {
    beginRename(row, projectPath, row.dataset.name ?? "");
  } else if (act === "remove") {
    void window.cbi.remove(projectPath);
  } else if (act === "relocate") {
    void window.cbi.relocate(projectPath);
  }
});

must<HTMLButtonElement>("back").addEventListener("click", () => {
  void window.cbi.back();
});

copy.addEventListener("click", async () => {
  await window.cbi.copy(instruction.textContent ?? "");
  copy.textContent = "Copied";
  setTimeout(() => { copy.textContent = "Copy"; }, 1500);
});

must<HTMLButtonElement>("cbi-save").addEventListener("click", async () => {
  renderCbi(await window.cbi.setCbiPath(cbiPath.value.trim() || null));
});

must<HTMLButtonElement>("cbi-browse").addEventListener("click", async () => {
  const info = await window.cbi.browseCbi();
  if (info) renderCbi(info);
});

function showEditorForm() {
  const custom = editorChoice.value === "custom";
  editorCustomRow.hidden = !custom;
  const command = editorChoice.selectedOptions[0]?.dataset.command ?? "";
  editorPreset.hidden = custom || !command;
  editorPreset.textContent = command;
}

function renderEditor(info: EditorSetting) {
  const known = ["vscode", "cursor", "none", "custom"];
  editorChoice.value = known.includes(info.editor) ? info.editor : "vscode";
  editorTemplate.value = info.template ?? "";
  showEditorForm();
  const error = info.ok === false ? info.error ?? "" : "";
  editorError.hidden = !error;
  editorError.textContent = error;
}

editorChoice.addEventListener("change", showEditorForm);
must<HTMLButtonElement>("editor-save").addEventListener("click", async () => {
  renderEditor(await window.cbi.setEditor({ editor: editorChoice.value, template: editorTemplate.value }));
});

new ResizeObserver(() => reportBounds()).observe(stage);

window.cbi.onOpening(showChrome);
window.cbi.onProject((state) => {
  if (!state) {
    showStart();
    return;
  }
  if (project.hidden) showChrome(state);
  else {
    projectName.textContent = state.displayName;
    projectPath.textContent = state.path;
    projectPath.title = state.path;
    showVersion(state);
    document.title = state.displayName;
  }
  renderTasks(state);
  if (state.comparing) closeCompare();
});
window.cbi.onProgress(appendProgress);
window.cbi.onRecents(renderRecents);
window.cbi.onError(showError);
window.cbi.onToast(renderToast);
window.cbi.onUpdateBanner(renderUpdate);

updateNotes.addEventListener("click", () => {
  void window.cbi.openUpdate("notes");
});
updateDownload.addEventListener("click", () => {
  void window.cbi.openUpdate("download");
});
updateSkip.addEventListener("click", () => {
  void window.cbi.skipUpdate();
});
updateDismiss.addEventListener("click", () => {
  void window.cbi.dismissUpdate();
});
checkUpdates.addEventListener("change", () => {
  void window.cbi.setUpdateSetting(checkUpdates.checked);
});

toastAction.addEventListener("click", () => {
  void window.cbi.acceptToast();
});

toastDetails.addEventListener("click", () => {
  toastDetail.hidden = !toastDetail.hidden;
  reportBounds();
});

must<HTMLButtonElement>("toast-dismiss").addEventListener("click", () => {
  window.cbi.dismissToast();
});

let versions: VersionList = { entries: [], fetched: false, fetching: false, error: null };

function renderGroup(container: HTMLElement, title: string, rows: SwitcherRow[], empty: string) {
  container.replaceChildren();
  if (!rows.length && !empty) {
    container.hidden = true;
    return;
  }
  container.hidden = false;
  const heading = document.createElement("h2");
  heading.textContent = title;
  container.append(heading);
  if (!rows.length) {
    const note = document.createElement("p");
    note.id = "switcher-empty";
    note.textContent = empty;
    container.append(note);
    return;
  }
  for (const row of rows) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "row";
    button.setAttribute("role", "option");
    button.dataset.key = row.key;
    button.setAttribute("aria-label", row.label);
    button.setAttribute("aria-selected", row.selected ? "true" : "false");
    if (row.selected) button.classList.add("selected");
    const name = document.createElement("span");
    name.textContent = row.label;
    const detail = document.createElement("span");
    detail.className = "detail";
    detail.textContent = [row.detail, row.selected ? "showing" : ""].filter(Boolean).join(" · ");
    button.append(name, detail);
    container.append(button);
  }
}

function renderSwitcher() {
  fillSide(compareBase);
  fillSide(compareHead);
  renderGroup(switcherWorktrees, "Worktrees", versions.entries.filter((row) => row.group === "worktree"), "");
  renderGroup(switcherBranches, "Branches", versions.entries.filter((row) => row.group === "branch"), "");
  renderGroup(switcherRemotes, "Remote branches", versions.fetched ? versions.entries.filter((row) => row.group === "remote") : [], versions.fetched ? "No remote branches." : "");
  if (!versions.fetched) switcherRemotes.hidden = true;
  switcherError.hidden = !versions.error;
  switcherError.textContent = versions.error ?? "";
  fetchRemotes.disabled = versions.fetching;
  fetchRemotes.textContent = versions.fetching ? "Fetching…" : "Fetch remote branches";
}

function closeSwitcher() {
  if (switcherPanel.hidden) return;
  switcherPanel.hidden = true;
  switcher.setAttribute("aria-expanded", "false");
  window.cbi.setSwitcherOpen(false);
}

function openSwitcher() {
  closeCompare();
  switcherPanel.hidden = false;
  switcher.setAttribute("aria-expanded", "true");
  window.cbi.setSwitcherOpen(true);
  void window.cbi.refreshVersions();
}

function fillSide(select: HTMLSelectElement) {
  const current = select.value;
  select.replaceChildren();
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = "Choose";
  select.append(placeholder);
  for (const row of versions.entries) {
    if (row.group === "remote") continue;
    const option = document.createElement("option");
    option.value = row.key;
    option.textContent = row.label;
    select.append(option);
  }
  const commit = document.createElement("option");
  commit.value = "commit";
  commit.textContent = "Commit";
  select.append(commit);
  for (let i = 0; i < select.options.length; i += 1) {
    if (select.options[i]?.value === current) {
      select.value = current;
      break;
    }
  }
}

function showRev(select: HTMLSelectElement, input: HTMLInputElement) {
  input.hidden = select.value !== "commit";
}

function sideFrom(select: HTMLSelectElement, input: HTMLInputElement): { kind: string; value: string } | null {
  if (!select.value) return null;
  if (select.value === "commit") return { kind: "commit", value: input.value.trim() };
  const split = select.value.indexOf(":");
  if (split < 1) return null;
  const kind = select.value.slice(0, split);
  if (kind !== "worktree" && kind !== "branch") return null;
  return { kind, value: select.value.slice(split + 1) };
}

function closeCompare() {
  if (comparePanel.hidden) return;
  comparePanel.hidden = true;
  compareOpen.setAttribute("aria-expanded", "false");
  window.cbi.setCompareOpen(false);
}

function openCompare() {
  closeSwitcher();
  fillSide(compareBase);
  fillSide(compareHead);
  showRev(compareBase, compareBaseRev);
  showRev(compareHead, compareHeadRev);
  compareError.hidden = true;
  compareError.textContent = "";
  comparePanel.hidden = false;
  compareOpen.setAttribute("aria-expanded", "true");
  window.cbi.setCompareOpen(true);
}

switcher.addEventListener("click", () => {
  if (switcherPanel.hidden) openSwitcher();
  else closeSwitcher();
});

switcherPanel.addEventListener("click", (event) => {
  const button = (event.target as HTMLElement).closest("button.row");
  if (!button) return;
  const key = (button as HTMLButtonElement).dataset.key;
  if (!key) return;
  closeSwitcher();
  void window.cbi.selectVersion(key);
});

fetchRemotes.addEventListener("click", () => {
  void window.cbi.fetchRemotes();
});

compareOpen.addEventListener("click", () => {
  if (comparePanel.hidden) openCompare();
  else closeCompare();
});

compareBase.addEventListener("change", () => showRev(compareBase, compareBaseRev));
compareHead.addEventListener("change", () => showRev(compareHead, compareHeadRev));

must<HTMLButtonElement>("compare-go").addEventListener("click", async () => {
  compareError.hidden = true;
  const result = await window.cbi.startCompare({
    base: sideFrom(compareBase, compareBaseRev),
    head: sideFrom(compareHead, compareHeadRev),
    pr: comparePr.value.trim(),
  });
  if (!result.ok) {
    compareError.hidden = false;
    compareError.textContent = result.error;
    return;
  }
  closeCompare();
});

compareBack.addEventListener("click", () => {
  closeCompare();
  void window.cbi.leaveCompare();
});

document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  closeSwitcher();
  closeCompare();
});

document.addEventListener("mousedown", (event) => {
  const target = event.target as Node;
  if (!switcherPanel.hidden && !switcherWrap.contains(target)) closeSwitcher();
  if (!comparePanel.hidden && !compareWrap.contains(target)) closeCompare();
});

window.cbi.onVersions((list) => {
  versions = list;
  renderSwitcher();
});

void window.cbi.listRecents().then(renderRecents);
void window.cbi.getCbi().then(renderCbi);
void window.cbi.getEditor().then(renderEditor).catch(() => undefined);
void window.cbi.getUpdateSetting().then((auto) => {
  checkUpdates.checked = auto !== false;
}).catch(() => undefined);

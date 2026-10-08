import { contextBridge, ipcRenderer, webUtils } from "electron";
import type { CbiInfo, Progress, ProjectInfo, ProjectState, RecentView, StageBounds, ToastPayload, VersionList } from "./types";

document.addEventListener("dragover", (event) => {
  event.preventDefault();
  if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
});

document.addEventListener("drop", (event) => {
  event.preventDefault();
  const file = event.dataTransfer?.files?.[0];
  if (!file) return;
  ipcRenderer.send("dropped-path", webUtils.getPathForFile(file));
});

function subscribe<T>(channel: string, cb: (payload: T) => void): () => void {
  const listener = (_event: unknown, payload: T) => cb(payload);
  ipcRenderer.on(channel, listener);
  return () => ipcRenderer.removeListener(channel, listener);
}

contextBridge.exposeInMainWorld("cbi", {
  pickFolder: (): Promise<string | null> => ipcRenderer.invoke("pick-folder"),
  openPath: (projectPath: string): Promise<void> => ipcRenderer.invoke("open-path", projectPath),
  listRecents: (): Promise<RecentView[]> => ipcRenderer.invoke("list-recents"),
  pin: (projectPath: string, pinned: boolean): Promise<void> => ipcRenderer.invoke("pin", projectPath, pinned),
  rename: (projectPath: string, name: string): Promise<void> => ipcRenderer.invoke("rename", projectPath, name),
  remove: (projectPath: string): Promise<void> => ipcRenderer.invoke("remove", projectPath),
  relocate: (projectPath: string): Promise<void> => ipcRenderer.invoke("relocate", projectPath),
  getCbi: (): Promise<CbiInfo> => ipcRenderer.invoke("get-cbi"),
  setCbiPath: (cbiPath: string | null): Promise<CbiInfo> => ipcRenderer.invoke("set-cbi", cbiPath),
  getEditor: (): Promise<{ editor: string; template: string; command: string }> => ipcRenderer.invoke("get-editor"),
  setEditor: (settings: { editor: string; template: string }): Promise<{ ok: boolean; error?: string; editor: string; template: string; command: string }> => ipcRenderer.invoke("set-editor", settings),
  browseCbi: (): Promise<CbiInfo | null> => ipcRenderer.invoke("browse-cbi"),
  copy: (text: string): Promise<void> => ipcRenderer.invoke("copy", text),
  back: (): Promise<void> => ipcRenderer.invoke("back"),
  startCompare: (form: unknown): Promise<{ ok: true } | { ok: false; error: string }> => ipcRenderer.invoke("start-compare", form),
  leaveCompare: (): Promise<void> => ipcRenderer.invoke("leave-compare"),
  setCompareOpen: (open: boolean): void => ipcRenderer.send("compare-open", open),
  selectVersion: (key: string): Promise<void> => ipcRenderer.invoke("select-version", key),
  refreshVersions: (): Promise<void> => ipcRenderer.invoke("refresh-versions"),
  fetchRemotes: (): Promise<void> => ipcRenderer.invoke("fetch-remotes"),
  setSwitcherOpen: (open: boolean): void => ipcRenderer.send("switcher-open", open),
  setViewerBounds: (bounds: StageBounds): void => ipcRenderer.send("viewer-bounds", bounds),
  onProgress: (cb: (progress: Progress) => void) => subscribe("progress", cb),
  onOpening: (cb: (info: ProjectInfo) => void) => subscribe("opening", cb),
  onProject: (cb: (state: ProjectState | null) => void) => subscribe("project", cb),
  onRecents: (cb: (items: RecentView[]) => void) => subscribe("recents", cb),
  onError: (cb: (message: string) => void) => subscribe("open-error", cb),
  onVersions: (cb: (list: VersionList) => void) => subscribe("versions", cb),
  onToast: (cb: (toast: ToastPayload | null) => void) => subscribe("toast", cb),
  acceptToast: (): Promise<void> => ipcRenderer.invoke("toast-action"),
  dismissToast: (): void => ipcRenderer.send("toast-dismiss"),
});

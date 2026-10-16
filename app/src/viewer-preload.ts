import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("cbiOpenInEditor", (payload: unknown) => ipcRenderer.invoke("open-in-editor", payload));

contextBridge.exposeInMainWorld("cbiReportBug", (error: string) => ipcRenderer.invoke("report-bug", { error, view: "Map" }));

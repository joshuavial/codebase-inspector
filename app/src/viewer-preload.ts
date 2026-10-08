import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("cbiOpenInEditor", (payload: unknown) => ipcRenderer.invoke("open-in-editor", payload));

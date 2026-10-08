import path from "node:path";
import { fileURLToPath } from "node:url";

/** True when the URL is this viewer file, ignoring the hash. */
export function sameViewerFile(currentUrl: string, index: string): boolean {
  try {
    const url = new URL(currentUrl);
    if (url.protocol !== "file:") return false;
    url.hash = "";
    return path.resolve(fileURLToPath(url)) === path.resolve(index);
  } catch {
    return false;
  }
}

/** True when the viewer is already showing this file and hash, so a load would be a no-op. */
export function sameViewer(currentUrl: string, index: string, hash: string): boolean {
  if (!sameViewerFile(currentUrl, index)) return false;
  const url = new URL(currentUrl);
  const currentHash = url.hash === "#" ? "" : url.hash.replace(/^#/, "");
  return currentHash === hash.replace(/^#/, "");
}

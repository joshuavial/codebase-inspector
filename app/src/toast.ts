/** A quiet note that a background build is ready. The map stays as it is until Show. */
export interface UpdateToast {
  kind: "update";
  message: string;
  action: "Show";
}

/** A failed background scan. Detail is the command output; the line is the short form. */
export interface ErrorToast {
  kind: "error";
  message: string;
  detail: string;
}

export type Toast = UpdateToast | ErrorToast;

/**
 * Null when the built map is the one already on screen.
 * A reordered list is not a difference: the caller passes fingerprints that already ignore that.
 */
export function updateToast(filesChanged: number, shown: string, next: string): UpdateToast | null {
  if (!shown || !next || shown === next) return null;
  const count = Math.max(0, Math.floor(filesChanged));
  const message = count === 1
    ? "Map updated: 1 file changed."
    : count > 1
      ? `Map updated: ${count} files changed.`
      : "Map updated.";
  return { kind: "update", message, action: "Show" };
}

export function errorToast(error: string): ErrorToast {
  const detail = error.trim() || "Scan failed.";
  const first = detail.split("\n").map((line) => line.trim()).find(Boolean) || "Scan failed.";
  const message = first.length > 180 ? `${first.slice(0, 179)}…` : first;
  return { kind: "error", message, detail };
}

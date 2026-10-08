import path from "node:path";

/** Window icon. The PNG is packed with the app; the icns is the bundle icon. */
export function windowIcon(appPath: string): string {
  return path.join(appPath, "build", "icon.png");
}

/**
 * Dock icon in dev only. A packaged app keeps the icon macOS registered
 * for the bundle when the app is launched from the place it is installed.
 */
export function dockIcon(appPath: string, packaged: boolean): string | null {
  if (packaged) return null;
  return windowIcon(appPath);
}

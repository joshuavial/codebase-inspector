import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

/**
 * Look up `cbi`, `git` and the other tools the app spawns.
 * `process.platform` is awkward to patch, so every function takes `platform`
 * and defaults to the host. Tests pass `"win32"` or `"linux"`.
 */

const cache = new Map<string, string>();

export function commandNames(name: string, platform: string = process.platform): string[] {
  if (platform !== "win32") return [name];
  if (name === "code" || name === "cursor") return [`${name}.cmd`, `${name}.exe`, name];
  return [`${name}.exe`, `${name}.cmd`, name];
}

export function pathSeparator(platform: string = process.platform): string {
  return platform === "win32" ? ";" : ":";
}

export function joinCommand(dir: string, filename: string, platform: string = process.platform): string {
  const base = platform === "win32" ? path.win32 : path.posix;
  return base.join(dir, filename);
}

export function canRun(file: string): boolean {
  try {
    if (!fs.statSync(file).isFile()) return false;
    fs.accessSync(file, fs.constants.X_OK);
    return true;
  } catch {
    return false;
  }
}

/** First line from `where`. A missing command is null. */
export function whereCommand(name: string): string | null {
  try {
    const out = execFileSync("where", [name], {
      encoding: "utf8",
      timeout: 5000,
      shell: false,
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"],
    });
    const line = out.split(/\r?\n/).map((part) => part.trim()).find(Boolean);
    return line || null;
  } catch {
    return null;
  }
}

export function findOnPath(name: string, opts: {
  pathEnv?: string | null;
  platform?: string;
  isExecutable?: (file: string) => boolean;
  where?: ((name: string) => string | null) | null;
  extra?: string[];
}): string | null {
  const platform = opts.platform ?? process.platform;
  const check = opts.isExecutable ?? canRun;
  for (const dir of (opts.pathEnv ?? "").split(pathSeparator(platform))) {
    if (!dir) continue;
    for (const filename of commandNames(name, platform)) {
      const candidate = joinCommand(dir, filename, platform);
      if (check(candidate)) return candidate;
    }
  }
  for (const extra of opts.extra ?? []) {
    if (check(extra)) return extra;
  }
  if (platform !== "win32") return null;
  // A test on macOS that passes platform "win32" and omits `where` must not spawn `where`.
  const lookup = opts.where === undefined
    ? (process.platform === "win32" ? whereCommand : null)
    : opts.where;
  if (!lookup) return null;
  const found = lookup(name);
  return found && check(found) ? found : null;
}

/**
 * Absolute path when one is on PATH, otherwise the bare name so the spawn
 * still reports ENOENT. Cached for the process PATH. Pass pathEnv or where
 * to skip the cache.
 */
export function commandExecutable(name: string, opts: {
  pathEnv?: string | null;
  platform?: string;
  isExecutable?: (file: string) => boolean;
  where?: ((name: string) => string | null) | null;
} = {}): string {
  const platform = opts.platform ?? process.platform;
  const pathEnv = opts.pathEnv ?? process.env.PATH ?? "";
  const isolated = opts.pathEnv != null || opts.platform != null || opts.isExecutable != null || opts.where !== undefined;
  const key = `${platform}\0${pathEnv}\0${name}`;
  if (!isolated) {
    const hit = cache.get(key);
    if (hit) return hit;
  }
  const found = findOnPath(name, {
    pathEnv,
    platform,
    isExecutable: opts.isExecutable,
    where: opts.where,
  });
  const value = found ?? name;
  if (!isolated) cache.set(key, value);
  return value;
}

export function clearCommandCache() {
  cache.clear();
}

export function missingGit(platform: string = process.platform): string {
  if (platform === "win32") {
    return "git was not found on PATH. Install Git for Windows, or set PATH so this app can see git.";
  }
  if (platform === "linux") {
    return "git was not found on PATH. Install git, or set PATH so this app can see git.";
  }
  return "git was not found on PATH. Install the Xcode command line tools, or set PATH so this app can see git.";
}

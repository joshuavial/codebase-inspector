import fs from "node:fs";
import path from "node:path";

export const INSTALL_HINT = [
  "Install the CLI from a checkout of codebase-inspector:",
  "",
  "  uv tool install .",
  "",
  "That puts cbi on your PATH, usually at ~/.local/bin/cbi.",
  "This app looks on PATH and in ~/.local/bin.",
  "An app opened from Finder does not inherit your shell PATH,",
  "so if cbi lives somewhere else, set its path here.",
].join("\n");

export interface Settings {
  cbiPath: string | null;
}

export function readSetting(file: string): Settings {
  try {
    const parsed = JSON.parse(fs.readFileSync(file, "utf8")) as { cbiPath?: unknown };
    const cbiPath = typeof parsed.cbiPath === "string" && parsed.cbiPath.trim() ? parsed.cbiPath : null;
    return { cbiPath };
  } catch {
    return { cbiPath: null };
  }
}

export function writeSetting(file: string, settings: Settings) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const tmp = `${file}.tmp`;
  fs.writeFileSync(tmp, `${JSON.stringify({ cbiPath: settings.cbiPath }, null, 2)}\n`);
  fs.renameSync(tmp, file);
}

export function isExecutable(file: string): boolean {
  try {
    if (!fs.statSync(file).isFile()) return false;
    fs.accessSync(file, fs.constants.X_OK);
    return true;
  } catch {
    return false;
  }
}

export type FindCbiResult = { ok: true; path: string } | { ok: false; error: string };

/**
 * CBI_BIN, then the saved setting, then PATH, then ~/.local/bin/cbi
 * (where `uv tool install` puts it). A set path that is not executable is an
 * error, so a typo is not silently replaced by another binary.
 */
export function findCbi(opts: {
  envOverride?: string | null;
  setting?: string | null;
  pathEnv?: string | null;
  home: string;
  isExecutable: (file: string) => boolean;
}): FindCbiResult {
  if (opts.envOverride) {
    if (opts.isExecutable(opts.envOverride)) return { ok: true, path: opts.envOverride };
    return { ok: false, error: `CBI_BIN is set to ${opts.envOverride}, but that file is not executable.\n\n${INSTALL_HINT}` };
  }
  if (opts.setting) {
    if (opts.isExecutable(opts.setting)) return { ok: true, path: opts.setting };
    return { ok: false, error: `The cbi path in settings is ${opts.setting}, but that file is not executable.\n\n${INSTALL_HINT}` };
  }
  for (const dir of (opts.pathEnv ?? "").split(":")) {
    if (!dir) continue;
    const candidate = path.join(dir, "cbi");
    if (opts.isExecutable(candidate)) return { ok: true, path: candidate };
  }
  const local = path.join(opts.home, ".local", "bin", "cbi");
  if (opts.isExecutable(local)) return { ok: true, path: local };
  return { ok: false, error: `cbi was not found.\n\n${INSTALL_HINT}` };
}

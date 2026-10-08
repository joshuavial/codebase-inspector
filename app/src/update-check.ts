/**
 * Check GitHub for a newer release and describe the banner.
 *
 * macOS builds are unsigned, so the app cannot install an update itself.
 * Callers only open the release page, or the asset for this machine, in the browser.
 */

import fs from "node:fs";
import http from "node:http";
import https from "node:https";
import path from "node:path";

export const RELEASES_URL = "https://api.github.com/repos/joshuavial/codebase-inspector/releases/latest";
export const DAY_MS = 24 * 60 * 60 * 1000;
export const TIMEOUT_MS = 5_000;

const SEMVER = /^v?(\d+)\.(\d+)\.(\d+)$/;

export interface UpdateAsset {
  name: string;
  url: string;
}

export interface UpdateRelease {
  version: string;
  htmlUrl: string;
  assets: UpdateAsset[];
}

export interface UpdateState {
  etag: string | null;
  checkedAt: number;
  release: UpdateRelease | null;
  skipped: string | null;
  shownAt: number | null;
  shownVersion: string | null;
  auto: boolean;
}

export interface UpdateBanner {
  message: string;
  notesUrl: string;
  downloadUrl: string;
  version: string;
}

export interface FetchResponse {
  status: number;
  etag: string | null;
  json: unknown;
}

export type ReleaseFetch = (
  url: string,
  headers: Record<string, string>,
  timeoutMs: number,
) => Promise<FetchResponse>;

export interface CheckResult {
  state: UpdateState;
  banner: UpdateBanner | null;
  /** Set on a manual check that has nothing to show. */
  message: string | null;
}

export function emptyState(): UpdateState {
  return {
    etag: null,
    checkedAt: 0,
    release: null,
    skipped: null,
    shownAt: null,
    shownVersion: null,
    auto: true,
  };
}

export function semver(text: string): [number, number, number] | null {
  const match = SEMVER.exec(text.trim());
  if (!match) return null;
  return [Number(match[1]), Number(match[2]), Number(match[3])];
}

export function isNewer(latest: string, current: string): boolean {
  const found = semver(latest);
  const have = semver(current);
  if (!found || !have) return false;
  for (let i = 0; i < 3; i += 1) {
    if (found[i] !== have[i]) return found[i] > have[i];
  }
  return false;
}

function versionOf(tag: string): string | null {
  const parts = semver(tag);
  if (!parts) return null;
  return `${parts[0]}.${parts[1]}.${parts[2]}`;
}

/** A stable release, "ignore" for a draft or prerelease, or null when the body is unusable. */
export function releaseFromApi(body: unknown): UpdateRelease | "ignore" | null {
  if (!body || typeof body !== "object") return null;
  const record = body as Record<string, unknown>;
  if (record.draft === true || record.prerelease === true) return "ignore";
  if (typeof record.tag_name !== "string") return null;
  const version = versionOf(record.tag_name);
  if (!version) return null;
  const htmlUrl = typeof record.html_url === "string" && record.html_url.startsWith("https://")
    ? record.html_url
    : `https://github.com/joshuavial/codebase-inspector/releases/tag/v${version}`;
  const assets: UpdateAsset[] = [];
  if (Array.isArray(record.assets)) {
    for (const asset of record.assets) {
      if (!asset || typeof asset !== "object") continue;
      const row = asset as Record<string, unknown>;
      if (typeof row.name !== "string" || typeof row.browser_download_url !== "string") continue;
      if (!/^https?:\/\//.test(row.browser_download_url)) continue;
      assets.push({ name: row.name, url: row.browser_download_url });
    }
  }
  return { version, htmlUrl, assets };
}

function hasWord(name: string, word: string): boolean {
  const escaped = word.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp(`(?:^|[^a-z0-9])${escaped}(?:[^a-z0-9]|$)`, "i").test(name);
}

function archOf(name: string): string | null {
  if (hasWord(name, "arm64") || hasWord(name, "aarch64")) return "arm64";
  if (hasWord(name, "x86_64") || hasWord(name, "amd64") || hasWord(name, "x64")) return "x64";
  if (hasWord(name, "ia32") || hasWord(name, "i386") || hasWord(name, "x86")) return "ia32";
  return null;
}

function platformOf(name: string): string | null {
  const lower = name.toLowerCase();
  if (["darwin", "macos", "osx", "mac"].some((word) => hasWord(lower, word))) return "darwin";
  if (["windows", "win32", "win"].some((word) => hasWord(lower, word))) return "win32";
  if (hasWord(lower, "linux")) return "linux";
  if (lower.endsWith(".dmg") || lower.endsWith(".pkg")) return "darwin";
  if (lower.endsWith(".exe") || lower.endsWith(".msi")) return "win32";
  if (lower.endsWith(".appimage") || lower.endsWith(".deb") || lower.endsWith(".rpm")) return "linux";
  return null;
}

const PREFER: Record<string, string[]> = {
  darwin: [".dmg", ".zip", ".pkg"],
  win32: [".exe", ".msi", ".zip"],
  linux: [".appimage", ".deb", ".rpm"],
};

/** The asset for this OS and arch, or the release page when none matches. */
export function downloadUrl(release: UpdateRelease, platform: string, arch: string): string {
  const matches = release.assets.filter((asset) => platformOf(asset.name) === platform && archOf(asset.name) === arch);
  if (!matches.length) return release.htmlUrl;
  const prefer = PREFER[platform] ?? [];
  for (const ext of prefer) {
    const found = matches.find((asset) => asset.name.toLowerCase().endsWith(ext));
    if (found) return found.url;
  }
  return matches[0]?.url ?? release.htmlUrl;
}

function cloneState(state: UpdateState): UpdateState {
  return {
    ...state,
    release: state.release
      ? { ...state.release, assets: state.release.assets.map((asset) => ({ ...asset })) }
      : null,
  };
}

function storedRelease(value: unknown): UpdateRelease | null {
  if (!value || typeof value !== "object") return null;
  const record = value as Record<string, unknown>;
  if (typeof record.version !== "string" || !semver(record.version)) return null;
  if (typeof record.htmlUrl !== "string" || !record.htmlUrl.startsWith("https://")) return null;
  const assets: UpdateAsset[] = [];
  if (Array.isArray(record.assets)) {
    for (const asset of record.assets) {
      if (!asset || typeof asset !== "object") continue;
      const row = asset as Record<string, unknown>;
      if (typeof row.name === "string" && typeof row.url === "string") assets.push({ name: row.name, url: row.url });
    }
  }
  return { version: record.version, htmlUrl: record.htmlUrl, assets };
}

export function readState(file: string): UpdateState {
  try {
    const parsed = JSON.parse(fs.readFileSync(file, "utf8")) as Record<string, unknown>;
    const state = emptyState();
    if (typeof parsed.etag === "string") state.etag = parsed.etag;
    if (typeof parsed.checkedAt === "number") state.checkedAt = parsed.checkedAt;
    if (typeof parsed.skipped === "string") state.skipped = parsed.skipped;
    if (typeof parsed.shownAt === "number") state.shownAt = parsed.shownAt;
    if (typeof parsed.shownVersion === "string") state.shownVersion = parsed.shownVersion;
    if (typeof parsed.auto === "boolean") state.auto = parsed.auto;
    state.release = storedRelease(parsed.release);
    return state;
  } catch {
    return emptyState();
  }
}

export function writeState(file: string, state: UpdateState): void {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const tmp = `${file}.tmp`;
  fs.writeFileSync(tmp, `${JSON.stringify(state, null, 2)}\n`);
  fs.renameSync(tmp, file);
}

export function skipRelease(state: UpdateState, version: string): UpdateState {
  return { ...cloneState(state), skipped: version };
}

export function setAutoCheck(state: UpdateState, auto: boolean): UpdateState {
  return { ...cloneState(state), auto };
}

function bannerFor(state: UpdateState, opts: {
  current: string;
  now: number;
  manual: boolean;
  platform: string;
  arch: string;
}): UpdateBanner | null {
  const release = state.release;
  if (!release || !isNewer(release.version, opts.current)) return null;
  if (!opts.manual && state.skipped === release.version) return null;
  if (
    !opts.manual
    && state.shownVersion === release.version
    && state.shownAt != null
    && opts.now - state.shownAt < DAY_MS
  ) {
    return null;
  }
  return {
    message: `Codebase Inspector ${release.version} is available`,
    notesUrl: release.htmlUrl,
    downloadUrl: downloadUrl(release, opts.platform, opts.arch),
    version: release.version,
  };
}

export async function runCheck(opts: {
  current: string;
  state: UpdateState;
  now: number;
  manual: boolean;
  platform: string;
  arch: string;
  url: string;
  fetch: ReleaseFetch;
  timeoutMs?: number;
}): Promise<CheckResult> {
  const state = cloneState(opts.state);
  if (!opts.manual && !state.auto) return { state, banner: null, message: null };
  const headers: Record<string, string> = {
    "User-Agent": `codebase-inspector/${opts.current}`,
    Accept: "application/vnd.github+json",
  };
  if (state.etag) headers["If-None-Match"] = state.etag;
  let response: FetchResponse | null = null;
  let failed = false;
  try {
    response = await opts.fetch(opts.url, headers, opts.timeoutMs ?? TIMEOUT_MS);
  } catch {
    failed = true;
  }
  if (!failed && response) {
    if (response.status === 304) {
      state.checkedAt = opts.now;
      if (response.etag) state.etag = response.etag;
    } else if (response.status === 404) {
      state.checkedAt = opts.now;
      state.etag = response.etag;
      state.release = null;
    } else if (response.status === 200) {
      const parsed = releaseFromApi(response.json);
      if (parsed === null) {
        failed = true;
      } else {
        state.checkedAt = opts.now;
        if (response.etag) state.etag = response.etag;
        if (parsed !== "ignore") state.release = parsed;
      }
    } else {
      failed = true;
    }
  }
  const banner = bannerFor(state, opts);
  let message: string | null = null;
  if (opts.manual && !banner) {
    message = failed ? "Could not check for updates." : "You're up to date";
  }
  if (banner) {
    state.shownAt = opts.now;
    state.shownVersion = banner.version;
  }
  return { state, banner, message };
}

function headerValue(value: string | string[] | undefined): string | null {
  return typeof value === "string" ? value : null;
}

function requestOnce(url: string, headers: Record<string, string>, timeoutMs: number, redirects: number): Promise<FetchResponse> {
  return new Promise((resolve, reject) => {
    let settled = false;
    const fail = (err: Error) => {
      if (settled) return;
      settled = true;
      reject(err);
    };
    let parsed: URL;
    try {
      parsed = new URL(url);
    } catch (err) {
      fail(err instanceof Error ? err : new Error(String(err)));
      return;
    }
    const lib = parsed.protocol === "http:" ? http : https;
    const req = lib.request(parsed, { method: "GET", headers, timeout: timeoutMs }, (res) => {
      const status = res.statusCode ?? 0;
      const location = headerValue(res.headers.location);
      if (status >= 300 && status < 400 && location && redirects < 3) {
        res.resume();
        settled = true;
        const next = new URL(location, parsed).toString();
        resolve(requestOnce(next, headers, timeoutMs, redirects + 1));
        return;
      }
      const chunks: Buffer[] = [];
      res.on("data", (chunk: Buffer) => chunks.push(chunk));
      res.on("error", fail);
      res.on("end", () => {
        if (settled) return;
        settled = true;
        const etag = headerValue(res.headers.etag);
        if (status === 304) {
          resolve({ status, etag, json: null });
          return;
        }
        const text = Buffer.concat(chunks).toString("utf8");
        let json: unknown = null;
        if (text) {
          try {
            json = JSON.parse(text) as unknown;
          } catch {
            json = null;
          }
        }
        resolve({ status, etag, json });
      });
    });
    req.on("timeout", () => req.destroy(new Error("timeout")));
    req.on("error", fail);
    req.end();
  });
}

export function fetchRelease(url: string, headers: Record<string, string>, timeoutMs: number): Promise<FetchResponse> {
  return requestOnce(url, headers, timeoutMs, 0);
}

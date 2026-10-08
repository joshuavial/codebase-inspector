import assert from "node:assert/strict";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { after, test } from "node:test";
import {
  DAY_MS,
  RELEASES_URL,
  downloadUrl,
  emptyState,
  fetchRelease,
  isNewer,
  readState,
  releaseFromApi,
  runCheck,
  setAutoCheck,
  skipRelease,
  writeState,
  type FetchResponse,
  type UpdateRelease,
  type UpdateState,
} from "./update-check";

const NOW = 1_700_000_000_000;
const NOTES = "https://github.com/joshuavial/codebase-inspector/releases/tag/v0.2.0";
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "cbi-update-"));
after(() => fs.rmSync(tmp, { recursive: true, force: true }));

function apiRelease(version = "0.2.0", extra: Record<string, unknown> = {}) {
  return {
    tag_name: `v${version}`,
    html_url: `https://github.com/joshuavial/codebase-inspector/releases/tag/v${version}`,
    draft: false,
    prerelease: false,
    assets: [
      { name: "Codebase-Inspector-0.2.0-mac-arm64.zip", browser_download_url: "https://example.com/mac.zip" },
      { name: "Codebase-Inspector-0.2.0-mac-arm64.dmg", browser_download_url: "https://example.com/mac.dmg" },
      { name: "Codebase-Inspector-0.2.0-linux-x64.AppImage", browser_download_url: "https://example.com/linux.AppImage" },
      { name: "Codebase-Inspector-0.2.0-win-x64.exe", browser_download_url: "https://example.com/win.exe" },
    ],
    ...extra,
  };
}

function respond(status: number, json: unknown, etag = '"e"'): FetchResponse {
  return { status, etag, json };
}

async function check(opts: {
  current?: string;
  state?: UpdateState;
  now?: number;
  manual?: boolean;
  platform?: string;
  arch?: string;
  status?: number;
  json?: unknown;
  fail?: boolean;
  etag?: string;
} = {}) {
  const seen: { url: string; headers: Record<string, string>; timeoutMs: number }[] = [];
  const fetch = async (url: string, headers: Record<string, string>, timeoutMs: number) => {
    seen.push({ url, headers, timeoutMs });
    if (opts.fail) throw new Error("offline");
    if (headers["If-None-Match"] && opts.json === undefined && opts.status === undefined) {
      return respond(304, null, headers["If-None-Match"]);
    }
    return respond(opts.status ?? 200, opts.json === undefined ? apiRelease() : opts.json, opts.etag ?? '"e"');
  };
  const result = await runCheck({
    current: opts.current ?? "0.1.0",
    state: opts.state ?? emptyState(),
    now: opts.now ?? NOW,
    manual: opts.manual ?? false,
    platform: opts.platform ?? "darwin",
    arch: opts.arch ?? "arm64",
    url: RELEASES_URL,
    fetch,
    timeoutMs: 50,
  });
  return { result, seen };
}

test("a newer release becomes a banner and prefers the asset for this machine", async () => {
  const { result, seen } = await check();
  assert.equal(result.banner?.message, "Codebase Inspector 0.2.0 is available");
  assert.equal(result.banner?.notesUrl, NOTES);
  assert.equal(result.banner?.downloadUrl, "https://example.com/mac.dmg");
  assert.equal(result.banner?.version, "0.2.0");
  assert.equal(result.message, null);
  assert.equal(seen[0]?.url, RELEASES_URL);
  assert.equal(seen[0]?.headers["User-Agent"], "codebase-inspector/0.1.0");
  assert.equal(seen[0]?.headers.Accept, "application/vnd.github+json");
  assert.equal(seen[0]?.headers.Authorization, undefined);
  assert.equal(seen[0]?.timeoutMs, 50);
});

test("the same version and an older version are not updates", async () => {
  const same = await check({ current: "0.2.0", manual: true });
  assert.equal(same.result.banner, null);
  assert.equal(same.result.message, "You're up to date");
  const older = await check({ current: "0.3.0", manual: true, json: apiRelease("0.2.0") });
  assert.equal(older.result.banner, null);
  assert.equal(older.result.message, "You're up to date");
  assert.equal(isNewer("0.10.0", "0.9.0"), true);
  assert.equal(isNewer("0.2.0", "0.2.0"), false);
});

test("a prerelease or a draft is ignored", async () => {
  for (const flag of ["prerelease", "draft"] as const) {
    const { result } = await check({ manual: true, json: apiRelease("9.0.0", { [flag]: true }) });
    assert.equal(result.banner, null);
    assert.equal(result.state.release, null);
    assert.equal(result.message, "You're up to date");
  }
  assert.equal(releaseFromApi(apiRelease("1.2.3", { draft: true })), "ignore");
});

test("skip remembers that version and a later one still shows", async () => {
  const first = await check();
  assert.ok(first.result.banner);
  const skipped = skipRelease(first.result.state, "0.2.0");
  const quiet = await check({ state: skipped, now: NOW + 1 });
  assert.equal(quiet.result.banner, null);
  const asked = await check({ state: skipped, manual: true, now: NOW + 2 });
  assert.equal(asked.result.banner?.version, "0.2.0");
  const later = await check({
    state: skipped,
    now: NOW + 3,
    json: apiRelease("0.3.0"),
  });
  assert.equal(later.result.banner?.message, "Codebase Inspector 0.3.0 is available");
});

test("an automatic banner shows at most once a day", async () => {
  const first = await check();
  assert.ok(first.result.banner);
  const again = await check({ state: first.result.state, now: NOW + 60_000 });
  assert.equal(again.result.banner, null);
  assert.equal(again.seen[0]?.headers["If-None-Match"], '"e"');
  const tomorrow = await check({ state: again.result.state, now: NOW + DAY_MS });
  assert.equal(tomorrow.result.banner?.version, "0.2.0");
});

test("an API error fails silently unless the check was asked for", async () => {
  const auto = await check({ status: 500, json: { message: "no" } });
  assert.equal(auto.result.banner, null);
  assert.equal(auto.result.message, null);
  const manual = await check({ status: 500, json: { message: "no" }, manual: true });
  assert.equal(manual.result.banner, null);
  assert.equal(manual.result.message, "Could not check for updates.");
});

test("offline fails silently unless the check was asked for", async () => {
  const auto = await check({ fail: true });
  assert.equal(auto.result.banner, null);
  assert.equal(auto.result.message, null);
  const manual = await check({ fail: true, manual: true });
  assert.equal(manual.result.banner, null);
  assert.equal(manual.result.message, "Could not check for updates.");
});

test("a 304 keeps the cached release", async () => {
  const first = await check();
  const aged: UpdateState = { ...first.result.state, shownAt: NOW - DAY_MS - 1 };
  const second = await check({ state: aged, now: NOW });
  assert.equal(second.seen[0]?.headers["If-None-Match"], '"e"');
  assert.equal(second.result.banner?.version, "0.2.0");
  assert.equal(second.result.state.release?.version, "0.2.0");
});

test("automatic checks stay off when the setting is off, and a manual check still runs", async () => {
  const off = setAutoCheck(emptyState(), false);
  const auto = await check({ state: off });
  assert.equal(auto.seen.length, 0);
  assert.equal(auto.result.banner, null);
  const manual = await check({ state: off, manual: true, current: "0.2.0" });
  assert.equal(manual.seen.length, 1);
  assert.equal(manual.result.message, "You're up to date");
});

test("an asset is chosen for the OS and arch, otherwise the release page", () => {
  const release = releaseFromApi(apiRelease());
  assert.notEqual(release, "ignore");
  if (release === "ignore" || !release) return;
  assert.equal(downloadUrl(release, "darwin", "arm64"), "https://example.com/mac.dmg");
  assert.equal(downloadUrl(release, "linux", "x64"), "https://example.com/linux.AppImage");
  assert.equal(downloadUrl(release, "win32", "x64"), "https://example.com/win.exe");
  assert.equal(downloadUrl(release, "darwin", "x64"), release.htmlUrl);
  const bare: UpdateRelease = {
    version: "0.2.0",
    htmlUrl: "https://example.com/r",
    assets: [{ name: "app-x86_64.tar.gz", url: "https://example.com/a" }],
  };
  assert.equal(downloadUrl(bare, "linux", "x64"), bare.htmlUrl);
  const x64: UpdateRelease = {
    version: "0.2.0",
    htmlUrl: "https://example.com/r",
    assets: [{ name: "app-linux-x86_64.tar.gz", url: "https://example.com/a" }],
  };
  assert.equal(downloadUrl(x64, "linux", "ia32"), x64.htmlUrl);
  assert.equal(downloadUrl(x64, "linux", "x64"), "https://example.com/a");
});

test("the saved check defaults to on and a damaged file is ignored", () => {
  const file = path.join(tmp, "update-check.json");
  assert.equal(readState(file).auto, true);
  const state = setAutoCheck(emptyState(), false);
  state.skipped = "0.2.0";
  writeState(file, state);
  const read = readState(file);
  assert.equal(read.auto, false);
  assert.equal(read.skipped, "0.2.0");
  fs.writeFileSync(file, "{");
  assert.equal(readState(file).auto, true);
  assert.equal(readState(file).skipped, null);
});

function listen(handler: http.RequestListener): Promise<{ url: string; close: () => Promise<void> }> {
  const server = http.createServer(handler);
  return new Promise((resolve) => {
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      if (!address || typeof address === "string") throw new Error("no port");
      resolve({
        url: `http://127.0.0.1:${address.port}`,
        close: () => new Promise((done) => server.close(() => done())),
      });
    });
  });
}

test("fetch follows a redirect and honours an etag", async () => {
  const body = JSON.stringify(apiRelease());
  const server = await listen((req, res) => {
    if (req.url === "/go") {
      res.writeHead(302, { Location: "/latest" });
      res.end();
      return;
    }
    if (req.headers["if-none-match"] === '"rel"') {
      res.writeHead(304, { ETag: '"rel"' });
      res.end();
      return;
    }
    assert.match(String(req.headers["user-agent"]), /^codebase-inspector\//);
    res.writeHead(200, { ETag: '"rel"', "Content-Type": "application/json" });
    res.end(body);
  });
  try {
    const got = await fetchRelease(`${server.url}/go`, { "User-Agent": "codebase-inspector/0.1.0" }, 2_000);
    assert.equal(got.status, 200);
    assert.equal(got.etag, '"rel"');
    assert.equal((got.json as { tag_name: string }).tag_name, "v0.2.0");
    const again = await fetchRelease(`${server.url}/latest`, {
      "User-Agent": "codebase-inspector/0.1.0",
      "If-None-Match": '"rel"',
    }, 2_000);
    assert.equal(again.status, 304);
    assert.equal(again.json, null);
    assert.equal(again.etag, '"rel"');
  } finally {
    await server.close();
  }
});

test("fetch gives up when the server does not answer", async () => {
  const server = await listen(() => undefined);
  try {
    await assert.rejects(fetchRelease(server.url, { "User-Agent": "codebase-inspector/0.1.0" }, 150));
  } finally {
    await server.close();
  }
});

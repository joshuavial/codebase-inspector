// ponytail: even hidden, a launched Electron can take focus on macOS; run it in CI, not on a working Mac.
if (process.platform === "darwin" && !process.env.CI) {
  console.error("Electron smoke runs only in CI on macOS (CI=1); it can take the focus of whoever is using this Mac.");
  process.exit(1);
}
// main.ts keeps every window hidden when this is set. Do not launch without it.
process.env.CBI_HEADLESS = "1";

import { execFileSync } from "node:child_process";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { _electron as electron } from "playwright-core";

const appRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const worktree = path.resolve(appRoot, "..");
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "cbi-update-smoke-"));
const fixture = path.join(tmp, "fixture-app");
const userData = path.join(tmp, "user-data");
const wrapper = path.join(tmp, "cbi");
const statePath = path.join(userData, "update-check.json");
const ETAG = '"rel"';
const requests = [];

function git(cwd, args) {
  execFileSync("git", args, { cwd, stdio: "pipe" });
}

function shellQuote(value) {
  return `'${value.replaceAll("'", `'\\''`)}'`;
}

function fail(message) {
  const saved = fs.existsSync(statePath) ? fs.readFileSync(statePath, "utf8") : "(no update-check.json)";
  throw new Error(`${message}\nupdate-check.json: ${saved}\nrequests: ${JSON.stringify(requests, null, 2)}`);
}

const release = {
  tag_name: "v0.2.0",
  html_url: "https://github.com/joshuavial/codebase-inspector/releases/tag/v0.2.0",
  draft: false,
  prerelease: false,
  assets: [
    {
      name: "Codebase-Inspector-0.2.0-arm64.dmg",
      browser_download_url: "https://example.com/Codebase-Inspector-0.2.0-arm64.dmg",
    },
  ],
};

const server = http.createServer((req, res) => {
  const match = req.headers["if-none-match"] ?? "";
  requests.push({
    url: req.url ?? "",
    ua: req.headers["user-agent"] ?? "",
    auth: req.headers.authorization ?? "",
    inm: match,
  });
  if (match === ETAG) {
    res.writeHead(304, { ETag: ETAG });
    res.end();
    return;
  }
  res.writeHead(200, { ETag: ETAG, "Content-Type": "application/json" });
  res.end(JSON.stringify(release));
});

await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const address = server.address();
const updateUrl = address && typeof address !== "string"
  ? `http://127.0.0.1:${address.port}/repos/joshuavial/codebase-inspector/releases/latest`
  : "";

let app;

try {
if (!updateUrl) fail("update server did not bind");

fs.mkdirSync(fixture, { recursive: true });
fs.writeFileSync(path.join(fixture, "package.json"), `${JSON.stringify({
  name: "fixture-app",
  bin: { "fixture-cli": "bin.js" },
}, null, 2)}\n`);
fs.writeFileSync(path.join(fixture, "bin.js"), "console.log('fixture');\n");
fs.writeFileSync(path.join(fixture, "README.md"), "# Fixture\n");
git(fixture, ["init", "-q", "-b", "main"]);
git(fixture, ["config", "user.email", "t@example.com"]);
git(fixture, ["config", "user.name", "t"]);
git(fixture, ["add", "package.json", "bin.js", "README.md"]);
git(fixture, ["commit", "-q", "-m", "init"]);
fs.writeFileSync(wrapper, `#!/bin/sh
exec uv run --project ${shellQuote(worktree)} cbi "$@"
`);
fs.chmodSync(wrapper, 0o755);
execFileSync(wrapper, ["init"], { cwd: fixture, stdio: "pipe", timeout: 60_000 });
execFileSync(wrapper, ["scan"], { cwd: fixture, stdio: "pipe", timeout: 60_000 });
execFileSync(wrapper, ["build"], { cwd: fixture, stdio: "pipe", timeout: 60_000 });

const env = { ...process.env };
delete env.CBI_NO_UPDATE_CHECK;
env.CBI_BIN = wrapper;
env.CBI_APP_USER_DATA = userData;
env.CBI_PICK_FOLDER = fixture;
env.CBI_SKIP_PROTOCOL = "1";
env.CBI_UPDATE_URL = updateUrl;

function launch() {
  return electron.launch({ args: [appRoot], env });
}

async function viewerEval(code) {
  let last = "no viewer";
  for (let attempt = 0; attempt < 20; attempt += 1) {
    try {
      const result = await app.evaluate(async ({ BrowserWindow }, source) => {
        const win = BrowserWindow.getAllWindows()[0];
        if (!win) return { error: "no window" };
        const views = win.contentView?.children ?? [];
        const urls = [];
        for (const view of views) {
          const wc = view.webContents;
          if (!wc || wc.isLoading()) continue;
          const url = wc.getURL();
          urls.push(url);
          if (url.includes("/.cbi/") && url.includes("/viewer/index.html")) {
            try {
              return { value: await wc.executeJavaScript(source) };
            } catch (err) {
              return { error: `execute ${err instanceof Error ? err.message : String(err)}`, url };
            }
          }
        }
        return { error: "no viewer", urls };
      }, code);
      if (!result?.error) return result?.value;
      last = `${result.error} ${result.url ?? ""} ${JSON.stringify(result.urls ?? [])}`;
    } catch (err) {
      last = err instanceof Error ? err.message : String(err);
    }
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  fail(last);
}

async function waitDiagram(page) {
  const started = Date.now();
  let diagram = "";
  while (Date.now() - started < 60_000) {
    diagram = await viewerEval("document.getElementById('diagram') ? document.getElementById('diagram').textContent : ''") ?? "";
    if (diagram.includes("fixture-cli")) return;
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  fail(`diagram did not show fixture-cli: ${diagram}`);
}

async function openMap(page) {
  await page.getByRole("button", { name: "Open folder" }).click();
  await page.locator("#project-name", { hasText: "fixture-app" }).waitFor();
  await waitDiagram(page);
}

async function waitBanner(page, visible) {
  await page.locator("#update-banner").waitFor({ state: visible ? "visible" : "hidden" });
}

async function waitSkipped() {
  const started = Date.now();
  while (Date.now() - started < 10_000) {
    if (fs.existsSync(statePath)) {
      const saved = JSON.parse(fs.readFileSync(statePath, "utf8"));
      if (saved.skipped === "0.2.0") return;
    }
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  fail("skip was not remembered");
}

async function clickCheckForUpdates() {
  const clicked = await app.evaluate(({ Menu }) => {
    const item = Menu.getApplicationMenu()?.getMenuItemById("check-for-updates");
    if (!item || typeof item.click !== "function") return false;
    item.click(item, null, null);
    return true;
  });
  if (!clicked) fail("Check for updates menu item did not run");
}

  app = await launch();
  const page = await app.firstWindow();
  page.setDefaultTimeout(60_000);
  page.on("console", (msg) => console.log(`page ${msg.type()}: ${msg.text()}`));
  page.on("pageerror", (err) => console.log(`page error: ${err}`));
  app.process().stdout?.on("data", (chunk) => process.stdout.write(chunk));
  app.process().stderr?.on("data", (chunk) => process.stderr.write(chunk));

  const auto = page.locator("#check-updates");
  if (!(await auto.isChecked())) fail("automatic checks default off");
  const label = await page.locator("#update-auto").innerText();
  if (!label.includes("Check for updates automatically")) fail(`setting label: ${label}`);

  await openMap(page);
  await waitBanner(page, true);
  const text = await page.locator("#update-message").innerText();
  if (text !== "Codebase Inspector 0.2.0 is available") fail(`banner text: ${text}`);
  await page.getByRole("button", { name: "Release notes" }).waitFor();
  await page.getByRole("button", { name: "Download" }).waitFor();
  await page.locator("#update-skip").click();
  await waitBanner(page, false);
  await waitSkipped();

  await clickCheckForUpdates();
  await waitBanner(page, true);
  const again = await page.locator("#update-message").innerText();
  if (again !== "Codebase Inspector 0.2.0 is available") fail(`manual banner text: ${again}`);
  await page.locator("#update-skip").click();
  await waitBanner(page, false);

  await app.close();
  app = null;
  const before = requests.length;
  app = await launch();
  const reopened = await app.firstWindow();
  reopened.setDefaultTimeout(60_000);
  await openMap(reopened);
  const started = Date.now();
  while (requests.length <= before && Date.now() - started < 15_000) {
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  if (requests.length <= before) fail("relaunch did not check");
  await new Promise((resolve) => setTimeout(resolve, 400));
  if (await reopened.locator("#update-banner").isVisible()) fail("banner showed for a skipped version");

  if (!requests.length || !requests.every((row) => row.ua.startsWith("codebase-inspector/"))) {
    fail("missing User-Agent");
  }
  if (requests.some((row) => row.auth)) fail("update check sent Authorization");
  if (requests[0].inm) fail(`first request sent If-None-Match: ${requests[0].inm}`);
  if (!requests.slice(1).every((row) => row.inm === ETAG)) fail("a later request missed If-None-Match");

  console.log("update smoke ok");
} finally {
  if (app) await app.close();
  server.closeAllConnections?.();
  await new Promise((resolve) => server.close(resolve));
  fs.rmSync(tmp, { recursive: true, force: true });
}

// ponytail: even hidden, a launched Electron can take focus on macOS; run it in CI, not on a working Mac.
if (process.platform === "darwin" && !process.env.CI) {
  console.error("Electron smoke runs only in CI on macOS (CI=1); it can take the focus of whoever is using this Mac.");
  process.exit(1);
}
// main.ts keeps every window hidden when this is set. Do not launch without it.
process.env.CBI_HEADLESS = "1";

import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { _electron as electron } from "playwright-core";

const appRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const worktree = path.resolve(appRoot, "..");
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "cbi-smoke-"));
const fixture = path.join(tmp, "fixture-app");
const laneDir = path.join(tmp, "fixture-lane");
const userData = path.join(tmp, "user-data");
const wrapper = path.join(tmp, "cbi");
const scanLog = path.join(tmp, "scan.log");
const slowFlag = path.join(tmp, "slow-scan");

function git(cwd, args) {
  execFileSync("git", args, { cwd, stdio: "pipe" });
}

function gitOut(cwd, args) {
  return execFileSync("git", args, { cwd, encoding: "utf8" });
}

function shellQuote(value) {
  return `'${value.replaceAll("'", `'\\''`)}'`;
}

function writePkg(dir, binName) {
  const pkg = JSON.parse(fs.readFileSync(path.join(dir, "package.json"), "utf8"));
  pkg.bin = { [binName]: "bin.js" };
  fs.writeFileSync(path.join(dir, "package.json"), `${JSON.stringify(pkg, null, 2)}\n`);
}

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
git(fixture, ["checkout", "-q", "-b", "side"]);
writePkg(fixture, "side-cli");
git(fixture, ["add", "package.json"]);
git(fixture, ["commit", "-q", "-m", "side"]);
git(fixture, ["checkout", "-q", "main"]);
git(fixture, ["worktree", "add", "-q", "-b", "lane", laneDir]);
writePkg(laneDir, "lane-cli");
git(laneDir, ["add", "package.json"]);
git(laneDir, ["commit", "-q", "-m", "lane"]);
git(fixture, ["config", "--local", "cbi.worktree.fixture-lane.branch", "lane"]);
fs.writeFileSync(wrapper, `#!/bin/sh
if [ "$1" = "scan" ] && [ -f ${shellQuote(slowFlag)} ]; then
  echo "start $PWD" >> ${shellQuote(scanLog)}
  sleep 3
  uv run --project ${shellQuote(worktree)} cbi "$@"
  code=$?
  echo "end $PWD $code" >> ${shellQuote(scanLog)}
  exit $code
fi
exec uv run --project ${shellQuote(worktree)} cbi "$@"
`);
fs.chmodSync(wrapper, 0o755);
execFileSync(wrapper, ["init"], { cwd: fixture, stdio: "pipe", timeout: 60_000 });
execFileSync(wrapper, ["scan"], { cwd: fixture, stdio: "pipe", timeout: 60_000 });
execFileSync(wrapper, ["build"], { cwd: fixture, stdio: "pipe", timeout: 60_000 });
fs.writeFileSync(slowFlag, "1");

function scanCounts() {
  const text = fs.existsSync(scanLog) ? fs.readFileSync(scanLog, "utf8") : "";
  const lines = text.split("\n");
  return {
    text,
    starts: lines.filter((line) => line.startsWith("start ")).length,
    ends: lines.filter((line) => line.startsWith("end ")).length,
  };
}

function repoSnapshot() {
  return [
    gitOut(fixture, ["status", "--porcelain"]),
    gitOut(laneDir, ["status", "--porcelain"]),
    gitOut(fixture, ["worktree", "list", "--porcelain"]),
    gitOut(fixture, ["for-each-ref"]),
    gitOut(fixture, ["rev-parse", "HEAD"]),
    gitOut(fixture, ["rev-parse", "--abbrev-ref", "HEAD"]),
    gitOut(laneDir, ["rev-parse", "HEAD"]),
    gitOut(laneDir, ["rev-parse", "--abbrev-ref", "HEAD"]),
    gitOut(fixture, ["stash", "list"]),
  ].join("\n---\n");
}

const beforeGit = repoSnapshot();
const fixtureReal = fs.realpathSync(fixture);
const laneReal = fs.realpathSync(laneDir);
let app;

try {
  app = await electron.launch({
    args: [appRoot],
    env: {
      ...process.env,
      CBI_BIN: wrapper,
      CBI_APP_USER_DATA: userData,
      CBI_PICK_FOLDER: fixture,
      CBI_SKIP_PROTOCOL: "1",
      CBI_HEADLESS: "1",
      CBI_NO_UPDATE_CHECK: "1",
    },
  });
  const page = await app.firstWindow();
  page.setDefaultTimeout(90_000);
  page.on("console", (msg) => console.log(`page ${msg.type()}: ${msg.text()}`));
  page.on("pageerror", (err) => console.log(`page error: ${err}`));
  app.process().stdout?.on("data", (chunk) => process.stdout.write(chunk));
  app.process().stderr?.on("data", (chunk) => process.stderr.write(chunk));

  async function assertHidden(where) {
    const states = await app.evaluate(({ BrowserWindow }) => {
      return BrowserWindow.getAllWindows().map((win) => ({
        visible: win.isVisible(),
        focused: win.isFocused(),
      }));
    });
    if (states.length === 0) throw new Error(`${where}: no window`);
    if (states.some((state) => state.visible || state.focused)) {
      throw new Error(`${where}: window was shown ${JSON.stringify(states)}`);
    }
  }

  async function viewerEval(code) {
    let last = "no viewer";
    for (let attempt = 0; attempt < 10; attempt += 1) {
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
    throw new Error(last);
  }

  async function waitDiagram(text, timeout = 60_000) {
    const started = Date.now();
    let diagram = "";
    while (Date.now() - started < timeout) {
      diagram = await viewerEval("document.getElementById('diagram') ? document.getElementById('diagram').textContent : ''") ?? "";
      if (diagram.includes(text)) return;
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
    throw new Error(`diagram did not show ${text}: ${diagram}`);
  }

  async function openSwitcher() {
    if (await page.locator("#switcher-panel").isHidden()) await page.locator("#switcher").click();
    await page.locator("#switcher-panel").waitFor({ state: "visible" });
  }

  await assertHidden("launch");

  await page.getByRole("button", { name: "Open folder" }).click();
  await page.locator("#project-name", { hasText: "fixture-app" }).waitFor();
  await page.locator("#branch", { hasText: "main" }).waitFor();
  await waitDiagram("fixture-cli", 2_500);
  const racedAt = Date.now();
  let early = scanCounts();
  while (Date.now() - racedAt < 4_000) {
    early = scanCounts();
    if (early.ends > 0) throw new Error(`scan finished before the map: ${early.text}`);
    if (early.starts > 0) break;
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  if (early.starts < 1) throw new Error(`background scan did not start: ${early.text}`);
  if (early.ends > 0) throw new Error(`scan finished before the map: ${early.text}`);
  const openedAt = Date.now();
  while (Date.now() - openedAt < 30_000) {
    if (scanCounts().ends >= 1) break;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  if (scanCounts().ends < 1) throw new Error(`opening scan did not finish: ${scanCounts().text}`);
  await page.locator("#instruction").waitFor();
  const instruction = await page.locator("#instruction").innerText();
  if (!instruction.includes(fixtureReal)) throw new Error(`instruction does not name the repo: ${instruction}`);
  if (!instruction.includes("run `cbi prime`")) throw new Error(`instruction text changed: ${instruction}`);
  await waitDiagram("fixture-cli");

  const hash = await viewerEval(`
    const node = document.querySelector("#diagram g.node");
    if (node) node.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    location.hash
  `);
  if (!hash || hash === "#") throw new Error(`click did not set a hash: ${hash}`);

  const recentsPath = path.join(userData, "recents.json");
  const savedAt = Date.now();
  let saved = "";
  while (Date.now() - savedAt < 10_000) {
    saved = fs.existsSync(recentsPath) ? fs.readFileSync(recentsPath, "utf8") : "";
    if (saved.includes(hash)) break;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  if (!saved.includes(hash)) throw new Error(`last view was not stored: ${hash}`);

  await viewerEval("window.__cbiStamp = 1; 1");
  execFileSync(wrapper, ["scan"], { cwd: fixture, stdio: "pipe", timeout: 60_000 });

  const reloadedAt = Date.now();
  let stamp = 1;
  while (Date.now() - reloadedAt < 8_000) {
    stamp = await viewerEval("window.__cbiStamp || 0");
    if (stamp !== 1) break;
    await new Promise((resolve) => setTimeout(resolve, 300));
  }
  if (stamp !== 1) throw new Error("the viewer reloaded after a scan that did not change the map");
  if (await page.locator("#toast").isVisible()) throw new Error("a quiet scan offered a new map");

  const drawer = await viewerEval(`(() => {
    try {
      const details = document.querySelector("#drawer details");
      if (!details) return null;
      details.open = !details.open;
      const summary = details.querySelector("summary");
      return { title: summary && summary.textContent ? String(summary.textContent) : "", open: details.open === true };
    } catch (err) {
      return { thrown: String(err) };
    }
  })()`);
  if (drawer?.title) drawer.title = drawer.title.replace(/\s*\(\d+\)\s*$/, "").trim();
  if (!drawer?.title) {
    const dump = await viewerEval("document.getElementById('drawer') ? document.getElementById('drawer').textContent : ''");
    throw new Error(`drawer has no section to remember: ${dump}`);
  }

  await openSwitcher();
  if (await page.locator("#switcher-remotes").isVisible()) throw new Error("remote branches are listed before fetch");
  const fetchLabel = await page.locator("#fetch-remotes").innerText();
  if (fetchLabel !== "Fetch remote branches") throw new Error(`fetch button label: ${fetchLabel}`);
  await page.locator("#switcher-worktrees").getByRole("option", { name: "fixture-lane", exact: true }).click();
  await page.locator("#branch", { hasText: "lane" }).waitFor();
  await page.locator("#version-label", { hasText: "fixture-lane" }).waitFor();
  await page.locator("#readonly").waitFor({ state: "hidden" });
  await page.locator("#instruction", { hasText: laneReal }).waitFor();
  await waitDiagram("lane-cli");

  await openSwitcher();
  await page.locator("#switcher-branches").getByRole("option", { name: "side", exact: true }).click();
  await page.locator("#branch", { hasText: "side" }).waitFor();
  await page.locator("#readonly").waitFor({ state: "visible" });
  await page.locator("#instruction", { hasText: "cbi tasks --ref side" }).waitFor();
  await waitDiagram("side-cli");

  await openSwitcher();
  await page.locator("#switcher-worktrees").getByRole("option", { name: "main", exact: true }).click();
  await page.locator("#branch", { hasText: "main" }).waitFor();
  await page.locator("#instruction", { hasText: "run `cbi prime`" }).waitFor();
  await page.locator("#readonly").waitFor({ state: "hidden" });
  await waitDiagram("fixture-cli");

  const backAt = Date.now();
  let restoredHash = "";
  let restoredOpen = null;
  while (Date.now() - backAt < 10_000) {
    restoredHash = await viewerEval("location.hash") ?? "";
    restoredOpen = await viewerEval(`(() => {
      const sections = [];
      for (const details of document.querySelectorAll("#drawer details")) {
        const summary = details.querySelector("summary");
        sections.push({ title: summary && summary.textContent ? summary.textContent : "", open: details.open });
      }
      return sections;
    })()`);
    if (Array.isArray(restoredOpen)) {
      const match = restoredOpen.find((section) => section.title.replace(/\s*\(\d+\)\s*$/, "").trim() === drawer.title);
      restoredOpen = match ? match.open : null;
    }
    if (restoredHash === hash && restoredOpen === drawer.open) break;
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  if (restoredHash !== hash) throw new Error(`hash not restored: before ${hash} after ${restoredHash}`);
  if (restoredOpen !== drawer.open) throw new Error(`drawer section ${drawer.title} open ${restoredOpen}, wanted ${drawer.open}`);

  const nodeId = await viewerEval(`
    const node = document.querySelector("#diagram [data-id]");
    node ? node.getAttribute("data-id") : ""
  `);
  if (!nodeId || !nodeId.includes("deployable:")) throw new Error(`diagram has no deployable id: ${nodeId}`);
  const link = `cbi://open?${new URLSearchParams({ repo: fixtureReal, ref: fixtureReal, node: nodeId })}`;
  await app.evaluate(({ app }, url) => {
    app.emit("open-url", { preventDefault() {} }, url);
  }, link);

  const landedAt = Date.now();
  let landed = { hash: "", decoded: "", title: "", back: "" };
  while (Date.now() - landedAt < 20_000) {
    const raw = await viewerEval(`JSON.stringify({
      hash: location.hash,
      decoded: decodeURIComponent(location.hash),
      title: document.querySelector("#drawer h2") ? document.querySelector("#drawer h2").textContent : "",
      back: document.querySelector("#crumbs button.back") ? document.querySelector("#crumbs button.back").textContent : "",
    })`);
    landed = JSON.parse(raw);
    if (landed.decoded.includes(nodeId) && landed.back.includes("Back") && landed.title) break;
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  if (!landed.decoded.includes(nodeId)) throw new Error(`open-url did not land on ${nodeId}: ${JSON.stringify(landed)}`);
  if (!landed.back.includes("Back")) throw new Error(`back chip missing: ${JSON.stringify(landed)}`);
  await assertHidden("deep link");
  // The hash change opens the directory watch again. A write in that same moment is easy to miss.
  await new Promise((resolve) => setTimeout(resolve, 1500));

  const mainSha = gitOut(fixture, ["rev-parse", "main"]).trim();
  const sideSha = gitOut(fixture, ["rev-parse", "side"]).trim();
  const compareLink = `cbi://open?${new URLSearchParams({ repo: fixtureReal, compare: `${mainSha}..${sideSha}` })}`;
  await app.evaluate(({ app }, url) => {
    app.emit("open-url", { preventDefault() {} }, url);
  }, compareLink);

  const compareAt = Date.now();
  let changes = "";
  let headBase = false;
  while (Date.now() - compareAt < 90_000) {
    try {
      changes = await viewerEval(`(() => {
        const panel = document.getElementById("changes");
        if (!panel || panel.hidden) return "";
        return panel.textContent || "";
      })()`) ?? "";
      headBase = await viewerEval(`(() => {
        const bar = document.getElementById("compare");
        return !!(bar && !bar.hidden);
      })()`) === true;
    } catch {
      changes = "";
      headBase = false;
    }
    if (changes.includes("Changes") && headBase) break;
    await new Promise((resolve) => setTimeout(resolve, 300));
  }
  if (!changes.includes("Changes") || !headBase) {
    throw new Error(`compare link did not open the changes panel: ${JSON.stringify({ changes, headBase })}`);
  }
  if (!(await page.locator("#compare-back").isVisible())) throw new Error("compare back chip hidden");

  await page.locator("#compare-back").click();
  await page.locator("#branch", { hasText: "main" }).waitFor();
  await page.locator("#compare-back").waitFor({ state: "hidden" });
  const leftAt = Date.now();
  let leftChanges = "visible";
  let leftText = "";
  while (Date.now() - leftAt < 90_000) {
    try {
      leftChanges = await viewerEval(`(() => {
        const panel = document.getElementById("changes");
        return panel && !panel.hidden ? "visible" : "hidden";
      })()`) ?? "visible";
      leftText = await viewerEval("document.getElementById('diagram') ? document.getElementById('diagram').textContent : ''") ?? "";
    } catch {
      leftChanges = "visible";
      leftText = "";
    }
    if (leftChanges === "hidden" && leftText.includes("fixture-cli")) break;
    await new Promise((resolve) => setTimeout(resolve, 300));
  }
  if (leftChanges !== "hidden" || !leftText.includes("fixture-cli")) {
    const progress = await page.locator("#progress").innerText().catch(() => "");
    const scanned = await page.locator("#scanned").innerText().catch(() => "");
    throw new Error(`did not leave the comparison: ${JSON.stringify({ leftChanges, leftText: leftText.slice(0, 180), progress, scanned })}`);
  }
  // The comparison reload rearms the worktree watch. A write in that moment is easy to miss.
  await new Promise((resolve) => setTimeout(resolve, 2500));

  await assertHidden("compare link");

  const afterGit = repoSnapshot();
  if (afterGit !== beforeGit) throw new Error(`git state changed:\n${afterGit}`);

  await viewerEval("window.__cbiStamp = 1; 1");
  // A README edit does not change the map payload. A source line does.
  const source = path.join(fixture, "bin.js");
  fs.appendFileSync(source, "\nconsole.log('edit');\n");
  const editedAt = Date.now();
  let editedStamp = 1;
  let toastText = "";
  let writes = 1;
  while (Date.now() - editedAt < 45_000) {
    editedStamp = await viewerEval("window.__cbiStamp || 0");
    toastText = await page.locator("#toast-message").textContent().catch(() => "") ?? "";
    if (editedStamp !== 1) throw new Error("the viewer reloaded before Show");
    if (toastText.includes("Map updated")) break;
    // macOS sometimes drops one directory event. A later write has to be seen.
    if (writes < 8 && Date.now() - editedAt > writes * 4_000) {
      writes += 1;
      fs.appendFileSync(source, "\nconsole.log('edit');\n");
    }
    await new Promise((resolve) => setTimeout(resolve, 300));
  }
  if (!toastText.includes("Map updated")) throw new Error(`no map-updated toast after a file change: ${toastText}`);
  if (editedStamp !== 1) throw new Error("the viewer reloaded before Show");
  const hashBeforeShow = await viewerEval("location.hash") ?? "";
  await page.locator("#toast-action").click();
  const shownAt = Date.now();
  let editedHash = hashBeforeShow;
  while (Date.now() - shownAt < 20_000) {
    editedStamp = await viewerEval("window.__cbiStamp || 0");
    editedHash = await viewerEval("location.hash") ?? "";
    const editedText = await viewerEval("document.getElementById('diagram') ? document.getElementById('diagram').textContent : ''") ?? "";
    if (editedStamp === 0 && editedHash === hashBeforeShow && editedText.includes("fixture-cli")) break;
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  if (editedStamp !== 0) throw new Error("Show did not reload the viewer");
  if (editedHash !== hashBeforeShow) throw new Error(`hash not kept across Show: before ${hashBeforeShow} after ${editedHash}`);
  if (hashBeforeShow !== landed.hash) throw new Error(`hash changed before the file edit: before ${landed.hash} after ${hashBeforeShow}`);

  console.log("smoke ok");
} finally {
  if (app) await app.close();
  fs.rmSync(tmp, { recursive: true, force: true });
}

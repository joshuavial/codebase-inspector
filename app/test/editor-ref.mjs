// ponytail: even hidden, a launched Electron can take focus on macOS; run it in CI, not on a working Mac.
if (process.platform === "darwin" && !process.env.CI) {
  console.error("Electron smoke runs only in CI on macOS (CI=1); it can take the focus of whoever is using this Mac.");
  process.exit(1);
}
// A ref view with no checkout opens a read-only snapshot. Assert the argv.
// The fake `code` on PATH records a launch; dry-run must leave that file empty.
// main.ts keeps every window hidden when this is set.
process.env.CBI_HEADLESS = "1";

import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { _electron as electron } from "playwright-core";

const appRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const worktree = path.resolve(appRoot, "..");
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "cbi-editor-ref-"));
const fixture = path.join(tmp, "hq");
const userData = path.join(tmp, "user-data");
const cache = path.join(tmp, "snapshots");
const binDir = path.join(tmp, "bin");
const wrapper = path.join(tmp, "cbi");
const argvLog = path.join(tmp, "argv.log");
const launched = path.join(tmp, "launched");
const sideText = "def arrears():\n    return 1\n";

function git(cwd, args) {
  execFileSync("git", args, { cwd, stdio: "pipe" });
}

function gitOut(cwd, args) {
  return execFileSync("git", args, { cwd, encoding: "utf8" });
}

function shellQuote(value) {
  return `'${value.replaceAll("'", `'\\''`)}'`;
}

fs.mkdirSync(path.join(fixture, "src"), { recursive: true });
fs.writeFileSync(path.join(fixture, "README.md"), "# hq\n");
git(fixture, ["init", "-q", "-b", "main"]);
git(fixture, ["config", "user.email", "t@example.com"]);
git(fixture, ["config", "user.name", "t"]);
git(fixture, ["add", "README.md"]);
git(fixture, ["commit", "-q", "-m", "main"]);
git(fixture, ["checkout", "-q", "-b", "side"]);
fs.writeFileSync(path.join(fixture, "src", "pay.py"), sideText);
git(fixture, ["add", "src/pay.py"]);
git(fixture, ["commit", "-q", "-m", "side"]);
const sha = gitOut(fixture, ["rev-parse", "HEAD"]).trim();
git(fixture, ["checkout", "-q", "main"]);

fs.mkdirSync(binDir, { recursive: true });
fs.writeFileSync(path.join(binDir, "code"), `#!/bin/sh
printf '%s\\n' "$@" >> ${shellQuote(launched)}
`);
fs.chmodSync(path.join(binDir, "code"), 0o755);
fs.writeFileSync(wrapper, `#!/bin/sh
exec uv run --project ${shellQuote(worktree)} cbi "$@"
`);
fs.chmodSync(wrapper, 0o755);

function cbi(args) {
  execFileSync(wrapper, args, { cwd: fixture, stdio: "pipe", timeout: 120_000 });
}

cbi(["init"]);
const refHome = path.join(fixture, ".cbi", "refs", sha);
fs.mkdirSync(refHome, { recursive: true });
fs.writeFileSync(path.join(refHome, "concepts.json"), `${JSON.stringify({
  concepts: [{
    id: "billing", name: "Billing", summary: "Arrears.", role: "service", files: ["src/pay.py"],
  }],
}, null, 2)}\n`);
cbi(["scan", "--ref", "side"]);
cbi(["build", "--ref", "side"]);
cbi(["scan"]);
cbi(["build"]);

const concepts = fs.readFileSync(path.join(refHome, "viewer", "data", "concepts.js"), "utf8");
if (!concepts.includes("arrears")) throw new Error("ref map has no arrears symbol");
if (fs.existsSync(path.join(fixture, "src", "pay.py"))) throw new Error("main checkout still has src/pay.py");

function repoSnapshot() {
  return [
    gitOut(fixture, ["status", "--porcelain"]),
    gitOut(fixture, ["worktree", "list", "--porcelain"]),
    gitOut(fixture, ["rev-parse", "HEAD"]),
    gitOut(fixture, ["rev-parse", "--abbrev-ref", "HEAD"]),
  ].join("\n---\n");
}

const beforeGit = repoSnapshot();
let app;

try {
  app = await electron.launch({
    args: [appRoot],
    env: {
      ...process.env,
      PATH: `${binDir}${path.delimiter}${process.env.PATH ?? ""}`,
      CBI_BIN: wrapper,
      CBI_APP_USER_DATA: userData,
      CBI_PICK_FOLDER: fixture,
      CBI_SKIP_PROTOCOL: "1",
      CBI_NO_UPDATE_CHECK: "1",
      CBI_SNAPSHOT_DIR: cache,
      CBI_EDITOR_DRY_RUN: argvLog,
      CBI_HEADLESS: "1",
    },
  });
  const page = await app.firstWindow();
  const shown = await app.evaluate(({ BrowserWindow }) => {
    return BrowserWindow.getAllWindows().map((win) => win.isVisible() || win.isFocused());
  });
  if (shown.some(Boolean)) throw new Error(`window was shown ${JSON.stringify(shown)}`);
  page.setDefaultTimeout(60_000);
  page.on("console", (msg) => console.log(`page ${msg.type()}: ${msg.text()}`));
  page.on("pageerror", (err) => console.log(`page error: ${err}`));
  app.process().stdout?.on("data", (chunk) => process.stdout.write(chunk));
  app.process().stderr?.on("data", (chunk) => process.stderr.write(chunk));

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
    throw new Error(last);
  }

  async function waitDiagram(text, timeout = 30_000) {
    const started = Date.now();
    let diagram = "";
    while (Date.now() - started < timeout) {
      diagram = await viewerEval("document.getElementById('diagram') ? document.getElementById('diagram').textContent : ''") ?? "";
      if (diagram.includes(text)) return;
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
    throw new Error(`diagram did not show ${text}: ${diagram}`);
  }

  await page.getByRole("button", { name: "Open folder" }).click();
  await page.locator("#project-name", { hasText: "hq" }).waitFor();
  await page.locator("#branch", { hasText: "main" }).waitFor();
  if (await page.locator("#switcher-panel").isHidden()) await page.locator("#switcher").click();
  await page.locator("#switcher-branches").getByRole("option", { name: "side", exact: true }).click();
  await page.locator("#branch", { hasText: "side" }).waitFor();
  await page.locator("#readonly").waitFor({ state: "visible" });
  await waitDiagram("Billing");
  await viewerEval("location.hash = 'c=billing'");
  await waitDiagram("arrears");
  const clicked = await viewerEval(`(() => {
    const node = [...document.querySelectorAll("#diagram [data-id]")].find((item) => (item.textContent || "").includes("arrears"));
    if (!node) return "";
    node.dispatchEvent(new MouseEvent("dblclick", { bubbles: true }));
    return node.getAttribute("data-id") || "";
  })()`);
  if (!clicked || !clicked.includes("arrears")) throw new Error(`no arrears node: ${clicked}`);

  const started = Date.now();
  let toast = "";
  while (Date.now() - started < 10_000) {
    toast = await viewerEval("(() => { const node = document.getElementById('toast'); return node && !node.hidden ? node.textContent : ''; })()") ?? "";
    if (toast.includes("read-only copy")) break;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  const expected = `Opened a read-only copy from side (${sha.slice(0, 7)}); not checked out locally.`;
  if (toast !== expected) throw new Error(`toast ${JSON.stringify(toast)} != ${JSON.stringify(expected)}`);

  const raw = fs.existsSync(argvLog) ? fs.readFileSync(argvLog, "utf8").trim() : "";
  const lines = raw ? raw.split("\n") : [];
  if (lines.length !== 1) throw new Error(`argv log ${JSON.stringify(raw)}`);
  const argv = JSON.parse(lines[0]);
  if (argv[0] !== path.join(binDir, "code")) throw new Error(`editor ${argv[0]}`);
  if (!argv.includes("--goto")) throw new Error(`argv ${JSON.stringify(argv)}`);
  const goto = argv[argv.indexOf("--goto") + 1];
  const colon = goto.lastIndexOf(":");
  const file = goto.slice(0, colon);
  const line = goto.slice(colon + 1);
  if (line !== "1") throw new Error(`line ${goto}`);
  if (!file.endsWith(`${path.sep}src${path.sep}pay.py`)) throw new Error(`file ${file}`);
  if (!file.startsWith(cache + path.sep)) throw new Error(`snapshot not in cache: ${file}`);
  const folder = path.basename(path.dirname(path.dirname(file)));
  if (folder !== `hq@side-${sha.slice(0, 12)}`) throw new Error(`folder ${folder}`);
  if (fs.readFileSync(file, "utf8") !== sideText) throw new Error("snapshot bytes differ");
  if ((fs.statSync(file).mode & 0o777) !== 0o444) throw new Error(`mode ${fs.statSync(file).mode.toString(8)}`);
  if (fs.existsSync(launched)) throw new Error(`code was launched: ${fs.readFileSync(launched, "utf8")}`);
  if (repoSnapshot() !== beforeGit) throw new Error("git state changed");
  if (fs.existsSync(path.join(fixture, "src", "pay.py"))) throw new Error("wrote inside the checkout");
  console.log("editor-ref ok");
} finally {
  if (app) await app.close();
}

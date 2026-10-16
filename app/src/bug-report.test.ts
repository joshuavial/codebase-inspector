import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { test } from "node:test";
import { ISSUE_URL, reportBug, reportBugItem } from "./bug-report";

test("Help item starts a report on click", () => {
  let clicks = 0;
  const item = reportBugItem(() => { clicks++; });
  assert.equal(item.label, "Report a bug…");
  assert.equal(item.id, "report-bug");
  item.click();
  assert.equal(clicks, 1);
  const main = fs.readFileSync(path.join(process.cwd(), "src/main.ts"), "utf8");
  assert.match(main, /label: "Help", submenu: \[\s*reportBugItem/);
  assert.match(main, /open: openExternalUrl/);
});

test("report uses Python's public draft and fixed view rather than project names", async () => {
  const opened: string[] = [];
  const url = `${ISSUE_URL}?template=bug_report.yml&happened=Layout+failed`;
  await reportBug({ appVersion: "0.1.0", view: "Map", error: "Layout failed: /private/repo", open: u => opened.push(u),
    run: async args => {
      assert.deepEqual(args, ["bug", "--print", "--app-version", "0.1.0", "--view", "Map", "--error=Layout failed: /private/repo"]);
      return { code: 0, stdout: url + "\n" };
    } });
  assert.deepEqual(opened, [url]);
});

test("missing or older cbi opens a minimal draft without raw error or process output", async () => {
  for (const run of [async () => { throw new Error("/private/repo"); },
    async () => ({ code: 1, stdout: "private model contents" }),
    async () => ({ code: 0, stdout: "https://other.example/?template=bug_report.yml" })]) {
    let opened = "";
    await reportBug({ appVersion: "0.1.0", view: "Mapping", error: "secret", run, open: u => { opened = u; } });
    const url = new URL(opened);
    assert.equal(url.origin + url.pathname, ISSUE_URL);
    assert.equal(url.searchParams.get("template"), "bug_report.yml");
    assert.match(url.searchParams.get("environment")!, /Python: unavailable/);
    assert.equal(url.searchParams.has("happened"), false);
    assert.ok(!opened.includes("secret"));
  }
});

// Execute the actual viewer error renderer with a small DOM, without Electron.
function errorState(message: string, desktop = true) {
  class Element {
    children: Element[] = [];
    textContent = "";
    attrs: Record<string, string> = {};
    listeners: Record<string, (event: { preventDefault(): void }) => void> = {};
    append(...nodes: Element[]) { this.children.push(...nodes); }
    replaceChildren() { this.children = []; }
    setAttribute(k: string, v: string) { this.attrs[k] = v; }
    addEventListener(k: string, fn: (event: { preventDefault(): void }) => void) { this.listeners[k] = fn; }
  }
  const svg = new Element();
  const reports: string[] = [];
  const source = fs.readFileSync(path.join(process.cwd(), "../src/cbi/viewer/app.js"), "utf8");
  const body = source.slice(source.indexOf("function empty(msg)"), source.indexOf("function setStage(mode)"));
  const context = vm.createContext({ setStage() {}, document: { getElementById: () => svg },
    svgEl: (_tag: string, attrs: Record<string, string>) => Object.assign(new Element(), { attrs }),
    window: desktop ? { cbiReportBug: (text: string) => reports.push(text) } : {},
    fit() {}, loadTreeAfterPaint() {}, location: { search: "" }, URLSearchParams });
  vm.runInContext(body, context);
  context.message = message;
  vm.runInContext("empty(message)", context);
  return { svg, reports };
}

test("map failure link passes the displayed error through the desktop bridge", () => {
  const error = "Layout failed: /Users/fake/repo/main.py";
  const { svg, reports } = errorState(error);
  const link = svg.children[1];
  assert.equal(link.children[0].textContent, "Report a bug…");
  let prevented = false;
  link.listeners.click({ preventDefault() { prevented = true; } });
  assert.equal(prevented, true);
  assert.deepEqual(reports, [error]);
});

test("empty maps and standalone viewers do not show a desktop action", () => {
  assert.equal(errorState("No concepts yet").svg.children.length, 1);
  assert.equal(errorState("Layout failed", false).svg.children.length, 1);
});

test("mapping failure action forwards the error and disappears when ready", () => {
  class Element {
    hidden = false;
    textContent = "";
    children: Element[] = [];
    scrollTop = 0;
    scrollHeight = 1;
    classList = { remove() {}, add() {}, contains: () => false };
    listeners: Record<string, () => void> = {};
    append(...nodes: Element[]) { this.children.push(...nodes); }
    addEventListener(k: string, fn: () => void) { this.listeners[k] = fn; }
  }
  const progress = new Element();
  const reports: string[] = [];
  const source = fs.readFileSync(path.join(process.cwd(), "src/renderer.ts"), "utf8");
  // Use TypeScript's own compiler so the production renderer runs as written.
  const ts: typeof import("typescript") = require("typescript");
  const body = source.slice(source.indexOf("function appendProgress("), source.indexOf("function reportBounds()"));
  const js = ts.transpile(body, { target: ts.ScriptTarget.ES2022 });
  const context = vm.createContext({ progress, progressPhase: "", project: new Element(), reportBounds() {},
    document: { createElement: () => new Element(), createTextNode: () => new Element() },
    window: { cbi: { reportBug: (error: string) => { reports.push(error); } } } });
  vm.runInContext(js + '\nappendProgress({ phase: "error", error: "Scan failed: /private/repo" });', context);
  assert.equal(progress.children[1].textContent, "Report a bug…");
  progress.children[1].listeners.click();
  assert.deepEqual(reports, ["Scan failed: /private/repo"]);
  vm.runInContext('appendProgress({ phase: "ready" });', context);
  assert.equal(progress.hidden, true);
});

test("long diagnostics fit process arguments and keep a trimming marker", async () => {
  await reportBug({ appVersion: "0.1.0", view: "Map", error: "x".repeat(20000), open() {},
    run: async args => {
      assert.ok(args.at(-1)!.length < 8100);
      assert.ok(args.at(-1)!.endsWith("\n[trimmed]"));
      return { code: 1, stdout: "" };
    } });
});

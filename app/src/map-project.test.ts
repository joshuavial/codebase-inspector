import assert from "node:assert/strict";
import path from "node:path";
import { test } from "node:test";
import { agentInstruction, commandSteps, compareSteps, mapCompare, mapProject, mapVersion, modelHome, rebuildViewer, taskSummary, type Runner } from "./map-project";

function fakeRun(script: Record<string, { code?: number; stdout?: string; stderr?: string }>): { run: Runner; calls: string[][] } {
  const calls: string[][] = [];
  const run: Runner = async (bin, args, cwd, onLine) => {
    calls.push([bin, cwd, ...args]);
    const step = script[args[0]] ?? { code: 1, stderr: `unexpected ${args[0]}` };
    if (args[0] !== "status") onLine(`${args[0]} line`);
    return { code: step.code ?? 0, stdout: step.stdout ?? "", stderr: step.stderr ?? "" };
  };
  return { run, calls };
}

const status = JSON.stringify({ scanned_at: "t", nodes: { cli: 1 }, open_tasks: { "summarise-files": 2, "confirm-structure": 1 } });

test("the agent instruction names the project path", () => {
  assert.equal(agentInstruction("/repos/app"), "run `cbi prime` in /repos/app and complete the tasks");
});

test("task state follows the folder, the model and open tasks", () => {
  const open = { scanned_at: null, nodes: {}, open_tasks: { "summarise-files": 2, "confirm-structure": 1 } };
  assert.deepEqual(taskSummary({ folderExists: false, modelExists: false, status: null }), { taskState: "missing", taskCount: 0 });
  assert.deepEqual(taskSummary({ folderExists: true, modelExists: false, status: null }), { taskState: "unscanned", taskCount: 0 });
  assert.deepEqual(taskSummary({ folderExists: true, modelExists: true, status: null }), { taskState: "unknown", taskCount: 0 });
  assert.deepEqual(taskSummary({ folderExists: true, modelExists: true, status: open }), { taskState: "waiting", taskCount: 3 });
  assert.deepEqual(taskSummary({ folderExists: true, modelExists: true, status: { ...open, open_tasks: {} } }), { taskState: "complete", taskCount: 0 });
});

test("a new project runs init, scan, build and status with a fixed argv", async () => {
  const { run, calls } = fakeRun({ init: {}, scan: {}, build: {}, status: { stdout: status } });
  const phases: string[] = [];
  const lines: string[] = [];
  const result = await mapProject({
    root: "/repos/app",
    cbi: "/bin/cbi",
    needsInit: true,
    run,
    onPhase: (phase) => phases.push(phase),
    onLine: (phase, line) => lines.push(`${phase}:${line}`),
  });
  assert.equal(result.ok, true);
  if (!result.ok) return;
  assert.deepEqual(result.status.open_tasks, { "summarise-files": 2, "confirm-structure": 1 });
  assert.deepEqual(calls, [
    ["/bin/cbi", "/repos/app", "init"],
    ["/bin/cbi", "/repos/app", "scan"],
    ["/bin/cbi", "/repos/app", "build"],
    ["/bin/cbi", "/repos/app", "status", "--json"],
  ]);
  assert.deepEqual(phases, ["init", "scan", "build", "status"]);
  assert.deepEqual(lines, ["init:init line", "scan:scan line", "build:build line"]);
});

test("an initialised project is not initialised again", async () => {
  const { run, calls } = fakeRun({ scan: {}, build: {}, status: { stdout: status } });
  const result = await mapProject({
    root: "/repos/app",
    cbi: "/bin/cbi",
    needsInit: false,
    run,
    onPhase: () => undefined,
    onLine: () => undefined,
  });
  assert.equal(result.ok, true);
  assert.deepEqual(calls.map((call) => call[2]), ["scan", "build", "status"]);
});

test("a failed scan does not build", async () => {
  const { run, calls } = fakeRun({ scan: { code: 1, stderr: "not initialised" } });
  const result = await mapProject({
    root: "/repos/app",
    cbi: "/bin/cbi",
    needsInit: false,
    run,
    onPhase: () => undefined,
    onLine: () => undefined,
  });
  assert.deepEqual(result, { ok: false, error: "cbi scan failed.\nnot initialised" });
  assert.deepEqual(calls.map((call) => call[2]), ["scan"]);
});

test("status that is not JSON is an error", async () => {
  const { run } = fakeRun({ scan: {}, build: {}, status: { stdout: "nope" } });
  const result = await mapProject({
    root: "/repos/app",
    cbi: "/bin/cbi",
    needsInit: false,
    run,
    onPhase: () => undefined,
    onLine: () => undefined,
  });
  assert.equal(result.ok, false);
});

test("mapping commands never include a git verb, and a ref stays one argument", () => {
  const steps = commandSteps({ needsInit: true, ref: "origin/feature" });
  assert.deepEqual(steps.map((step) => step.args), [
    ["init"],
    ["scan", "--ref", "origin/feature"],
    ["build", "--ref", "origin/feature"],
    ["status", "--json", "--ref", "origin/feature"],
  ]);
  const flat = steps.flatMap((step) => step.args);
  for (const verb of ["checkout", "switch", "stash", "reset", "clean", "fetch", "worktree"]) {
    assert.equal(flat.includes(verb), false);
  }
  assert.deepEqual(commandSteps({ needsInit: false, ref: "side", rebuild: true }).map((step) => step.args), [
    ["build", "--ref", "side"],
    ["status", "--json", "--ref", "side"],
  ]);
});

test("a branch map passes --ref and records the commit and the viewer path", async () => {
  const sha = "c".repeat(40);
  const root = path.resolve("/repos/app");
  const viewer = path.join(root, ".cbi", "refs", sha, "viewer", "index.html");
  const { run, calls } = fakeRun({
    scan: { stdout: `${sha}\nscanned in 0.1 s\n` },
    build: { stdout: `${viewer}\n` },
    status: { stdout: status },
  });
  const result = await mapVersion({
    root,
    cbi: "/bin/cbi",
    needsInit: false,
    ref: "side",
    run,
    onPhase: () => undefined,
    onLine: () => undefined,
  });
  assert.equal(result.ok, true);
  if (!result.ok) return;
  assert.equal(result.commit, sha);
  assert.equal(result.viewer, viewer);
  assert.equal(modelHome(viewer), path.join(root, ".cbi", "refs", sha));
  assert.deepEqual(calls.map((call) => call.slice(2)), [
    ["scan", "--ref", "side"],
    ["build", "--ref", "side"],
    ["status", "--json", "--ref", "side"],
  ]);
});

test("a model change rebuilds the viewer and does not scan", async () => {
  const { run, calls } = fakeRun({ build: {}, status: { stdout: status } });
  const result = await rebuildViewer({
    root: "/repos/app",
    cbi: "/bin/cbi",
    run,
    onPhase: () => undefined,
    onLine: () => undefined,
  });
  assert.equal(result.ok, true);
  assert.deepEqual(calls.map((call) => call.slice(2)), [["build"], ["status", "--json"]]);
});

test("a comparison scans both commits and builds with --compare", async () => {
  const base = "a".repeat(40);
  const head = "b".repeat(40);
  const viewer = "/repos/app/.cbi/viewer/index.html";
  assert.equal(compareSteps({ needsInit: false, base: "main", head: "side" }), null);
  const steps = compareSteps({ needsInit: true, base, head });
  assert.ok(steps);
  assert.deepEqual(steps.map((step) => step.args), [
    ["init"],
    ["scan", "--ref", base],
    ["scan", "--ref", head],
    ["build", "--compare", `${base}..${head}`],
    ["status", "--json", "--ref", head],
  ]);
  const flat = steps.flatMap((step) => step.args);
  for (const verb of ["checkout", "switch", "stash", "reset", "clean", "fetch", "worktree"]) {
    assert.equal(flat.includes(verb), false);
  }
  const { run, calls } = fakeRun({
    scan: { stdout: `${head}\nscanned\n` },
    build: { stdout: `${viewer}\n` },
    status: { stdout: status },
  });
  const result = await mapCompare({
    root: "/repos/app",
    cbi: "/bin/cbi",
    needsInit: false,
    base,
    head,
    run,
    onPhase: () => undefined,
    onLine: () => undefined,
  });
  assert.equal(result.ok, true);
  if (!result.ok) return;
  assert.equal(result.viewer, viewer);
  assert.deepEqual(calls.map((call) => call.slice(2)), [
    ["scan", "--ref", base],
    ["scan", "--ref", head],
    ["build", "--compare", `${base}..${head}`],
    ["status", "--json", "--ref", head],
  ]);
});

test("a ref model rebuilds with --ref and does not scan", async () => {
  const { run, calls } = fakeRun({ build: { stdout: "/repos/app/.cbi/refs/abc/viewer/index.html\n" }, status: { stdout: status } });
  const result = await rebuildViewer({
    root: "/repos/app",
    cbi: "/bin/cbi",
    ref: "side",
    run,
    onPhase: () => undefined,
    onLine: () => undefined,
  });
  assert.equal(result.ok, true);
  assert.deepEqual(calls.map((call) => call.slice(2)), [
    ["build", "--ref", "side"],
    ["status", "--json", "--ref", "side"],
  ]);
});

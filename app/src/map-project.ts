import path from "node:path";
import type { RunResult } from "./spawn";
import type { Phase, StatusJson, TaskState } from "./types";

export type { RunResult };

export type Runner = (
  bin: string,
  args: string[],
  cwd: string,
  onLine: (line: string) => void,
) => Promise<RunResult>;

export type MapResult =
  | { ok: true; status: StatusJson; viewer: string; commit: string | null }
  | { ok: false; error: string };

/** The model directory that owns a viewer index: `.cbi` or `.cbi/refs/<sha>`. */
export function modelHome(viewerIndex: string): string {
  return path.resolve(viewerIndex, "..", "..");
}

export function agentInstruction(projectPath: string): string {
  return `run \`cbi prime\` in ${projectPath} and complete the tasks`;
}

export function taskSummary(opts: {
  folderExists: boolean;
  modelExists: boolean;
  status: StatusJson | null;
}): { taskState: TaskState; taskCount: number } {
  if (!opts.folderExists) return { taskState: "missing", taskCount: 0 };
  if (!opts.modelExists) return { taskState: "unscanned", taskCount: 0 };
  if (!opts.status) return { taskState: "unknown", taskCount: 0 };
  const taskCount = Object.values(opts.status.open_tasks).reduce((sum, n) => sum + (typeof n === "number" ? n : 0), 0);
  return { taskState: taskCount > 0 ? "waiting" : "complete", taskCount };
}

interface Step {
  phase: "init" | "scan" | "build" | "status";
  args: string[];
}

function failure(step: Step, result: RunResult): string {
  const detail = (result.stderr || result.stdout).trim();
  return detail ? `cbi ${step.args[0]} failed.\n${detail}` : `cbi ${step.args[0]} failed.`;
}

/** Fixed argv for a worktree map, a `cbi --ref` map, or a viewer rebuild. No git commands. */
export function commandSteps(opts: { needsInit: boolean; ref?: string | null; rebuild?: boolean }): Step[] {
  const ref = opts.ref ? ["--ref", opts.ref] : [];
  const steps: Step[] = [];
  if (!opts.rebuild && opts.needsInit) steps.push({ phase: "init", args: ["init"] });
  if (!opts.rebuild) steps.push({ phase: "scan", args: ["scan", ...ref] });
  steps.push({ phase: "build", args: ["build", ...ref] }, { phase: "status", args: ["status", "--json", ...ref] });
  return steps;
}

function lastLine(text: string): string {
  const lines = text.trim().split("\n").filter(Boolean);
  return lines[lines.length - 1] ?? "";
}

async function runSteps(
  opts: {
    root: string;
    cbi: string;
    run: Runner;
    onPhase: (phase: Phase) => void;
    onLine: (phase: Phase, line: string) => void;
  },
  steps: Step[],
): Promise<MapResult> {
  let statusOut = "";
  let viewer = "";
  let commit: string | null = null;
  for (const step of steps) {
    opts.onPhase(step.phase);
    const result = await opts.run(opts.cbi, step.args, opts.root, (line) => {
      if (step.phase !== "status") opts.onLine(step.phase, line);
    });
    if (result.code !== 0) return { ok: false, error: failure(step, result) };
    if (step.args[0] === "build") viewer = lastLine(result.stdout);
    if (step.args[0] === "scan" && step.args.includes("--ref")) {
      commit = result.stdout.split("\n").map((line) => line.trim()).find((line) => /^[0-9a-f]{40}$/.test(line)) ?? null;
    }
    if (step.phase === "status") statusOut = result.stdout;
  }
  try {
    const status = JSON.parse(statusOut) as StatusJson;
    if (!status || typeof status !== "object" || !status.open_tasks || typeof status.open_tasks !== "object" || Array.isArray(status.open_tasks)) {
      return { ok: false, error: "cbi status did not return task counts." };
    }
    return { ok: true, status, viewer, commit };
  } catch {
    return { ok: false, error: "cbi status did not return JSON." };
  }
}

/** init (when .cbi/ignore is missing), then scan, build and status. */
export function mapProject(opts: {
  root: string;
  cbi: string;
  needsInit: boolean;
  run: Runner;
  onPhase: (phase: Phase) => void;
  onLine: (phase: Phase, line: string) => void;
}): Promise<MapResult> {
  return runSteps(opts, commandSteps({ needsInit: opts.needsInit }));
}

/** Scan and build one worktree, or one ref when `ref` is set. The ref is a single argv element. */
export function mapVersion(opts: {
  root: string;
  cbi: string;
  needsInit: boolean;
  ref: string | null;
  run: Runner;
  onPhase: (phase: Phase) => void;
  onLine: (phase: Phase, line: string) => void;
}): Promise<MapResult> {
  return runSteps(opts, commandSteps({ needsInit: opts.needsInit, ref: opts.ref }));
}

const COMMIT = /^[0-9a-f]{40}$/;

/**
 * Scan both commits (a stored ref model is reused), then build the comparison
 * viewer. The refs are full shas, so the argv cannot be a branch name or a flag.
 * Returns null when either side is not a sha.
 */
export function compareSteps(opts: { needsInit: boolean; base: string; head: string }): Step[] | null {
  if (!COMMIT.test(opts.base) || !COMMIT.test(opts.head)) return null;
  const steps: Step[] = [];
  if (opts.needsInit) steps.push({ phase: "init", args: ["init"] });
  const refs = opts.base === opts.head ? [opts.base] : [opts.base, opts.head];
  for (const ref of refs) steps.push({ phase: "scan", args: ["scan", "--ref", ref] });
  steps.push(
    { phase: "build", args: ["build", "--compare", `${opts.base}..${opts.head}`] },
    { phase: "status", args: ["status", "--json", "--ref", opts.head] },
  );
  return steps;
}

/** Scan both sides and write the `cbi build --compare` viewer. */
export function mapCompare(opts: {
  root: string;
  cbi: string;
  needsInit: boolean;
  base: string;
  head: string;
  run: Runner;
  onPhase: (phase: Phase) => void;
  onLine: (phase: Phase, line: string) => void;
}): Promise<MapResult> {
  const steps = compareSteps({ needsInit: opts.needsInit, base: opts.base, head: opts.head });
  if (!steps) return Promise.resolve({ ok: false, error: "That ref cannot be scanned." });
  return runSteps(opts, steps);
}

/** Rebuild the viewer after the model changes. Does not scan again. */
export function rebuildViewer(opts: {
  root: string;
  cbi: string;
  ref?: string | null;
  run: Runner;
  onPhase: (phase: Phase) => void;
  onLine: (phase: Phase, line: string) => void;
}): Promise<MapResult> {
  return runSteps(opts, commandSteps({ needsInit: false, ref: opts.ref, rebuild: true }));
}

import { spawn, type ChildProcess } from "node:child_process";

export interface RunResult {
  code: number;
  stdout: string;
  stderr: string;
}

export interface SpawnOptions {
  cwd: string;
  shell: false;
  env: NodeJS.ProcessEnv;
}

export type SpawnFn = (bin: string, args: readonly string[], opts: SpawnOptions) => ChildProcess;

export interface KillSlot {
  kill: (() => void) | null;
}

function takeLines(buf: string, onLine: (line: string) => void): string {
  let rest = buf;
  let nl = rest.indexOf("\n");
  while (nl >= 0) {
    const line = rest.slice(0, nl);
    rest = rest.slice(nl + 1);
    if (line) onLine(line);
    nl = rest.indexOf("\n");
  }
  return rest;
}

/** Run an executable with a fixed argv list. Never uses a shell. */
export function runProcess(
  bin: string,
  args: readonly string[],
  cwd: string,
  onLine: (line: string) => void,
  timeoutMs: number,
  spawnFn: SpawnFn = spawn as unknown as SpawnFn,
  slot?: KillSlot,
): Promise<RunResult> {
  return new Promise((resolve) => {
    const child = spawnFn(bin, args, {
      cwd,
      shell: false,
      env: { ...process.env, PYTHONUNBUFFERED: "1" },
    });
    let stdout = "";
    let stderr = "";
    let settled = false;
    const finish = (code: number) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (slot && slot.kill === kill) slot.kill = null;
      resolve({ code, stdout, stderr });
    };
    const kill = () => {
      child.kill();
    };
    if (slot) slot.kill = kill;
    const timer = setTimeout(() => {
      kill();
      stderr += `\nTimed out after ${timeoutMs} ms.`;
      finish(1);
    }, timeoutMs);
    timer.unref?.();
    if (!child.stdout || !child.stderr) {
      kill();
      stderr += "The process produced no output streams.";
      finish(1);
      return;
    }
    let outBuf = "";
    let errBuf = "";
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk: string) => {
      stdout += chunk;
      outBuf = takeLines(outBuf + chunk, onLine);
    });
    child.stderr.on("data", (chunk: string) => {
      stderr += chunk;
      errBuf = takeLines(errBuf + chunk, onLine);
    });
    child.stdout.on("end", () => {
      if (outBuf) onLine(outBuf);
      outBuf = "";
    });
    child.stderr.on("end", () => {
      if (errBuf) onLine(errBuf);
      errBuf = "";
    });
    child.on("error", (err) => {
      stderr += err.message;
      finish(1);
    });
    child.on("close", (code) => finish(code ?? 1));
  });
}

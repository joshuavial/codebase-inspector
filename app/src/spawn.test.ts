import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { test } from "node:test";
import { runProcess, type SpawnFn } from "./spawn";

test("a process is spawned with the given argv and no shell", async () => {
  let seen: { bin: string; args: readonly string[]; shell: boolean } | null = null;
  const fake: SpawnFn = (bin, args, opts) => {
    seen = { bin, args, shell: opts.shell };
    return spawn(process.execPath, ["-e", "process.exit(0)"], { cwd: opts.cwd, shell: false });
  };
  const result = await runProcess("/usr/local/bin/cbi", ["scan", "--json"], process.cwd(), () => undefined, 5_000, fake);
  assert.equal(result.code, 0);
  assert.deepEqual(seen, { bin: "/usr/local/bin/cbi", args: ["scan", "--json"], shell: false });
});

test("stdout and stderr are streamed and the exit code is kept", async () => {
  const lines: string[] = [];
  const script = "process.stdout.write('hello\\n'); process.stderr.write('warn\\n'); process.exit(3)";
  const result = await runProcess(process.execPath, ["-e", script], process.cwd(), (line) => lines.push(line), 5_000);
  assert.equal(result.code, 3);
  assert.equal(result.stdout, "hello\n");
  assert.equal(result.stderr, "warn\n");
  assert.deepEqual(lines.sort(), ["hello", "warn"]);
});

test("an argument with a space stays one argument", async () => {
  const script = "process.stdout.write(process.argv[1])";
  const result = await runProcess(process.execPath, ["-e", script, "one two"], process.cwd(), () => undefined, 5_000);
  assert.equal(result.stdout, "one two");
});

test("a hung process is killed at the timeout", async () => {
  const result = await runProcess(process.execPath, ["-e", "setInterval(() => {}, 1000)"], process.cwd(), () => undefined, 200);
  assert.notEqual(result.code, 0);
  assert.match(result.stderr, /Timed out/);
});

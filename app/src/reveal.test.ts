import assert from "node:assert/strict";
import { test } from "node:test";
import { revealFor, revealWindow, type Reveal, type RevealTarget } from "./reveal";

function fake(opts: { minimized?: boolean; destroyed?: boolean } = {}): RevealTarget & { calls: string[] } {
  const calls: string[] = [];
  return {
    calls,
    isDestroyed: () => opts.destroyed === true,
    isMinimized: () => opts.minimized === true,
    restore: () => { calls.push("restore"); },
    show: () => { calls.push("show"); },
    focus: () => { calls.push("focus"); },
    showInactive: () => { calls.push("showInactive"); },
  };
}

test("a CLI or deep link shows the window inactive and does not focus it", () => {
  const win = fake();
  revealWindow(win, revealFor(false, true));
  assert.deepEqual(win.calls, ["showInactive"]);
});

test("a dock, app, or menu activation focuses the window", () => {
  const win = fake();
  revealWindow(win, revealFor(false, false));
  assert.deepEqual(win.calls, ["show", "focus"]);
});

test("headless never shows a window", () => {
  for (const fromLink of [true, false]) {
    const win = fake();
    revealWindow(win, revealFor(true, fromLink));
    assert.deepEqual(win.calls, []);
  }
});

test("a minimized window is restored only when the user activates the app", () => {
  const linked = fake({ minimized: true });
  revealWindow(linked, revealFor(false, true));
  assert.deepEqual(linked.calls, ["showInactive"]);

  const activated = fake({ minimized: true });
  revealWindow(activated, revealFor(false, false));
  assert.deepEqual(activated.calls, ["restore", "show", "focus"]);
});

test("a missing or destroyed window is left alone", () => {
  const destroyed = fake({ destroyed: true });
  for (const how of ["hidden", "inactive", "focus"] as Reveal[]) revealWindow(destroyed, how);
  assert.deepEqual(destroyed.calls, []);
  revealWindow(null, "focus");
});

/** How a window is allowed to appear. */
export type Reveal = "hidden" | "inactive" | "focus";

/**
 * Headless (tests and smoke) never shows a window.
 * A CLI or deep link shows it without focusing.
 * A dock click, the app icon, or a menu may focus.
 */
export function revealFor(headless: boolean, fromLink: boolean): Reveal {
  if (headless) return "hidden";
  if (fromLink) return "inactive";
  return "focus";
}

export interface RevealTarget {
  isDestroyed(): boolean;
  isMinimized(): boolean;
  restore(): void;
  show(): void;
  focus(): void;
  showInactive(): void;
}

/**
 * Apply `how`. Hidden does nothing. Inactive never calls `show`, `focus`, or
 * `restore`: `restore` deminiaturizes by making the window key.
 */
export function revealWindow(win: RevealTarget | null, how: Reveal): void {
  if (how === "hidden" || !win || win.isDestroyed()) return;
  if (how === "inactive") {
    win.showInactive();
    return;
  }
  if (win.isMinimized()) win.restore();
  win.show();
  win.focus();
}

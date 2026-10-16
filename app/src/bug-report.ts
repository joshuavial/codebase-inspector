import os from "node:os";

export const ISSUE_URL = "https://github.com/joshuavial/codebase-inspector/issues/new";
export type BugView = "Help menu" | "Map" | "Mapping";

export function reportBugItem(report: () => void) {
  return { id: "report-bug", label: "Report a bug…", click: report };
}

/** Python owns sanitising diagnostics and collecting its runtime version. */
export async function reportBug(opts: {
  appVersion: string;
  view: BugView;
  error?: string;
  run: (args: string[]) => Promise<{ code: number; stdout: string }>;
  open: (url: string) => void;
}) {
  const args = ["bug", "--print", "--app-version", opts.appVersion, "--view", opts.view];
  if (opts.error) {
    const error = opts.error.length > 8000 ? opts.error.slice(0, 8000) + "\n[trimmed]" : opts.error;
    args.push(`--error=${error}`);
  }
  try {
    const result = await opts.run(args);
    const url = result.stdout.trim();
    const parsed = new URL(url);
    if (result.code === 0 && url.length < 8000 &&
        parsed.origin + parsed.pathname === ISSUE_URL && parsed.searchParams.get("template") === "bug_report.yml") {
      opts.open(url);
      return;
    }
  } catch {
    // Reporting must still work when cbi is missing or predates this command.
  }
  const environment = ["cbi: unavailable", `App: ${opts.appVersion}`, `OS: ${os.type()} ${os.release()}`,
    `Architecture: ${os.arch()}`, "Python: unavailable", `Command or view: ${opts.view}`].join("\n");
  const fields = new URLSearchParams({ template: "bug_report.yml", environment });
  opts.open(`${ISSUE_URL}?${fields}`);
}

import { execFile } from "node:child_process";
import { sqliteArgs } from "./fast-open";
import { commandExecutable } from "./which";

/** Read one query from a model database. Null when sqlite3 is missing or the file cannot be read. */
export function querySqlite(db: string, sql: string): Promise<string | null> {
  if (!db || db.includes("\0")) return Promise.resolve(null);
  return new Promise((resolve) => {
    execFile(
      commandExecutable("sqlite3"),
      sqliteArgs(db, sql),
      { timeout: 5000, maxBuffer: 32 * 1024 * 1024, encoding: "utf8", shell: false },
      (err, stdout) => {
        if (err) resolve(null);
        else resolve(stdout);
      },
    );
  });
}

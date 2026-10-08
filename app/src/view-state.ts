import fs from "node:fs";
import path from "node:path";

export interface DrawerSection {
  title: string;
  open: boolean;
}

export interface SavedView {
  hash: string;
  sections: DrawerSection[];
  drawerHidden: boolean;
}

interface Bucket {
  lastKey: string;
  views: Record<string, SavedView>;
}

interface FileShape {
  projects: Record<string, Bucket>;
}

export function emptyView(): SavedView {
  return { hash: "", sections: [], drawerHidden: false };
}

/** "Files (3)" and "Integration points (12)" share a title across rescans. */
export function sectionTitle(summary: string): string {
  return summary.replace(/\s*\(\d+\)\s*$/, "").trim();
}

export function parseCaptured(text: string): SavedView | null {
  try {
    const value = JSON.parse(text) as { hash?: unknown; drawerHidden?: unknown; sections?: unknown };
    if (!value || typeof value !== "object" || typeof value.hash !== "string" || !Array.isArray(value.sections)) return null;
    const sections: DrawerSection[] = [];
    for (const item of value.sections) {
      if (!item || typeof item !== "object") continue;
      const section = item as { title?: unknown; open?: unknown };
      if (typeof section.title !== "string" || !section.title.trim()) continue;
      sections.push({ title: sectionTitle(section.title), open: section.open === true });
    }
    return { hash: value.hash, sections, drawerHidden: value.drawerHidden === true };
  } catch {
    return null;
  }
}

/** Read the viewer hash and which drawer sections are open. Returns JSON. */
export const CAPTURE_VIEW_JS = `(() => {
  const title = (node) => (node && node.textContent ? node.textContent : "").replace(/\\s*\\(\\d+\\)\\s*$/, "").trim();
  const sections = [];
  const drawer = document.querySelector("#drawer");
  if (drawer) {
    for (const details of drawer.querySelectorAll("details")) {
      const name = title(details.querySelector("summary"));
      if (name) sections.push({ title: name, open: details.open === true });
    }
  }
  return JSON.stringify({
    hash: location.hash === "#" ? "" : location.hash,
    drawerHidden: document.body.classList.contains("no-drawer"),
    sections,
  });
})()`;

/** Apply a saved drawer after the viewer has rendered this hash. */
export function restoreScript(view: SavedView): string {
  const payload = JSON.stringify({
    drawerHidden: view.drawerHidden,
    sections: view.sections.map((section) => ({ title: sectionTitle(section.title), open: section.open })),
  });
  return `(() => {
    const wanted = ${payload};
    document.body.classList.toggle("no-drawer", wanted.drawerHidden === true);
    const title = (node) => (node && node.textContent ? node.textContent : "").replace(/\\s*\\(\\d+\\)\\s*$/, "").trim();
    const drawer = document.querySelector("#drawer");
    if (!drawer) return false;
    for (const details of drawer.querySelectorAll("details")) {
      const name = title(details.querySelector("summary"));
      const match = wanted.sections.find((section) => section.title === name);
      if (match) details.open = match.open === true;
    }
    return true;
  })()`;
}

function asView(value: unknown): SavedView | null {
  if (!value || typeof value !== "object") return null;
  const view = value as { hash?: unknown; drawerHidden?: unknown; sections?: unknown };
  if (typeof view.hash !== "string" || !Array.isArray(view.sections)) return null;
  return parseCaptured(JSON.stringify(view));
}

function readFile(json: string): FileShape {
  try {
    const parsed = JSON.parse(json) as { projects?: unknown };
    if (!parsed || typeof parsed !== "object" || !parsed.projects || typeof parsed.projects !== "object") return { projects: {} };
    const projects: Record<string, Bucket> = {};
    for (const [project, bucket] of Object.entries(parsed.projects as Record<string, unknown>)) {
      if (!bucket || typeof bucket !== "object") continue;
      const item = bucket as { lastKey?: unknown; views?: unknown };
      const views: Record<string, SavedView> = {};
      if (item.views && typeof item.views === "object") {
        for (const [key, view] of Object.entries(item.views as Record<string, unknown>)) {
          const saved = asView(view);
          if (saved) views[key] = saved;
        }
      }
      projects[project] = { lastKey: typeof item.lastKey === "string" ? item.lastKey : "", views };
    }
    return { projects };
  } catch {
    return { projects: {} };
  }
}

function writeFile(file: string, value: FileShape) {
  const body = `${JSON.stringify(value, null, 2)}\n`;
  fs.mkdirSync(path.dirname(file), { recursive: true });
  // A shared `.tmp` name in the temp directory can vanish between the write and the rename.
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const tmp = `${file}.${process.pid}.${attempt}.tmp`;
    try {
      fs.writeFileSync(tmp, body);
      fs.renameSync(tmp, file);
      return;
    } catch (err) {
      fs.rmSync(tmp, { force: true });
      if (attempt === 2) throw err;
    }
  }
}

/**
 * Per worktree and per branch view state, in the app's userData.
 * Nothing here is written into the repository.
 */
export class ViewStore {
  constructor(private readonly file: string) {}

  private read(): FileShape {
    try {
      return readFile(fs.readFileSync(this.file, "utf8"));
    } catch {
      return { projects: {} };
    }
  }

  private save(data: FileShape) {
    writeFile(this.file, data);
  }

  get(project: string, key: string): SavedView {
    return this.read().projects[project]?.views[key] ?? emptyView();
  }

  set(project: string, key: string, view: SavedView) {
    const data = this.read();
    const bucket = data.projects[project] ?? { lastKey: "", views: {} };
    bucket.views[key] = {
      hash: view.hash,
      drawerHidden: view.drawerHidden,
      sections: view.sections.map((section) => ({ title: sectionTitle(section.title), open: section.open })),
    };
    data.projects[project] = bucket;
    this.save(data);
  }

  /** Keep the hash current as the viewer navigates, without clearing drawer sections. */
  updateHash(project: string, key: string, hash: string) {
    const data = this.read();
    const bucket = data.projects[project] ?? { lastKey: "", views: {} };
    const prev = bucket.views[key] ?? emptyView();
    bucket.views[key] = { ...prev, hash };
    data.projects[project] = bucket;
    this.save(data);
  }

  lastKey(project: string): string | null {
    const key = this.read().projects[project]?.lastKey ?? "";
    return key || null;
  }

  setLastKey(project: string, key: string) {
    const data = this.read();
    const bucket = data.projects[project] ?? { lastKey: "", views: {} };
    bucket.lastKey = key;
    data.projects[project] = bucket;
    this.save(data);
  }
}

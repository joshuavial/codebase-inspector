import { copyFileSync, mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const app = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const dist = path.join(app, "dist");
mkdirSync(dist, { recursive: true });
for (const name of ["index.html", "style.css"]) {
  copyFileSync(path.join(app, "src", name), path.join(dist, name));
}

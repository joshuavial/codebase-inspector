// Open one file in the editor. The desktop app injects window.cbiOpenInEditor
// and runs the command itself. A static viewer, which cannot run a command,
// follows the editor URL scheme. data/editor.js sets which scheme, via cbiSetEditor.
// Grey nodes are one file too: double-click opens them. Go to still jumps.

let EDITOR = { editor: "vscode", root: "" };

function cbiSetEditor(value) {
  if (value && typeof value === "object") EDITOR = value;
}

function projectRoot() {
  if (EDITOR.root) return String(EDITOR.root).replace(/\/+$/, "");
  try {
    if (location.protocol !== "file:") return "";
    const file = decodeURIComponent(location.pathname);
    const at = file.indexOf("/.cbi/");
    if (at > 0) return file.slice(0, at);
  } catch (e) { /* opened from somewhere that is not a built viewer */ }
  return "";
}

// vscode://file/<abs path>:<line> and the same shape for Cursor. none has no URL.
function editorHref(file, line) {
  const name = EDITOR.editor || "vscode";
  if (name === "none") return "";
  const scheme = name === "cursor" ? "cursor" : "vscode";
  const n = Number(line) > 0 ? Number(line) : 1;
  const rel = String(file || "").replace(/^\/+/, "");
  const root = projectRoot();
  const abs = root ? `${root}/${rel}` : (rel.startsWith("/") ? rel : `/${rel}`);
  const encoded = abs.split("/").map((part) => encodeURIComponent(part)).join("/");
  return `${scheme}://file${encoded}:${n}`;
}
window.cbiEditorHref = editorHref;

let editorToastTimer = 0;
function toast(message) {
  let node = document.getElementById("toast");
  if (!node) {
    node = document.createElement("div");
    node.id = "toast";
    node.setAttribute("role", "status");
    document.body.append(node);
  }
  node.textContent = message;
  node.hidden = false;
  clearTimeout(editorToastTimer);
  editorToastTimer = setTimeout(() => { node.hidden = true; }, 4200);
}

// A static ref view cannot run git or open a file that is not on disk.
function isRefView() {
  return !!(EDITOR && EDITOR.sha) && typeof window.cbiOpenInEditor !== "function";
}

function editorLabel() {
  return isRefView() ? "Copy git show command" : "Open in editor";
}

function gitShowCommand(file) {
  const rel = String(file || "").replace(/^\/+/, "");
  return "git show " + EDITOR.sha + ":" + rel;
}

function copyText(text) {
  const done = () => toast("Copied git show command");
  const fallback = () => {
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.left = "-9999px";
    document.body.append(area);
    area.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
    area.remove();
    toast(ok ? "Copied git show command" : "Copy failed");
  };
  if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(done, fallback);
  else fallback();
}

function openInEditor(file, line) {
  const rel = String(file || "").replace(/^\/+/, "");
  const n = Number(line) > 0 ? Number(line) : 1;
  if (!rel) return;
  const host = window.cbiOpenInEditor;
  if (typeof host === "function") {
    Promise.resolve(host({ file: rel, line: n })).then((res) => {
      if (res && res.notice) toast(String(res.notice));
      else if (res && res.ok === false && res.error) toast(String(res.error));
    }, () => toast("Could not open the editor."));
    return;
  }
  if (EDITOR && EDITOR.sha) {
    copyText(gitShowCommand(rel));
    return;
  }
  const url = editorHref(rel, n);
  if (!url) { toast("No editor is configured."); return; }
  const link = document.createElement("a");
  link.href = url;
  link.hidden = true;
  document.body.append(link);
  link.click();
}

function editorButton(file, line) {
  if (!file) return null;
  const button = document.createElement("button");
  button.type = "button";
  button.className = "action";
  button.textContent = editorLabel();
  button.onclick = () => openInEditor(file, line || 1);
  return button;
}

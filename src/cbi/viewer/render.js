// Headless capture. app.js draws and paints chg-* marks from data/diff.js.
// This file sets the view hash, then copies the SVG out once the diagram is fitted.

const SVG_NS = "http://www.w3.org/2000/svg";
const KEY = [
  ["added", "Added", (marks) => marks.has("added") || marks.has("new")],
  ["removed", "Removed", (marks) => marks.has("removed")],
  ["changed", "Changed", (marks) => marks.has("changed") || marks.has("provisional") || marks.has("volume") || marks.has("mechanism")],
];

window.cbiRender = true;
let finished = false;
window.addEventListener("error", (ev) => {
  document.title = "cbi-render-failed";
  const out = document.getElementById("svg-out");
  if (out && !out.textContent) out.textContent = String(ev.message || ev.error || "error");
});

const origLoad = window.cbiLoad;
window.cbiLoad = function (name, value) {
  if (name === "view") {
    const params = new URLSearchParams();
    if (value && value.focus) params.set("c", value.focus);
    if (value && value.side === "base") params.set("side", "base");
    const hash = params.toString();
    if (hash) history.replaceState(null, "", "#" + hash);
    return;
  }
  return origLoad(name, value);
};
window.cbiOnDiagram = finish;

function finish(svg) {
  if (finished) return;
  finished = true;
  const failed = !!svg.querySelector("text.empty");
  if (!failed) {
    try { drawKey(svg); }
    catch (err) {
      document.getElementById("svg-out").textContent = String(err && err.message || err);
      document.title = "cbi-render-failed";
      return;
    }
  }
  if (!svg.getAttribute("xmlns")) svg.setAttribute("xmlns", SVG_NS);
  embedStyle(svg);
  // A label can contain the script closer. The dump keeps the markup in one element.
  const markup = svg.outerHTML.replace(/<\/script/gi, "<\\/script");
  document.getElementById("svg-out").textContent = markup;
  document.title = failed ? "cbi-render-failed" : "cbi-render-ready";
}

function embedStyle(svg) {
  const css = ["cbi-viewer-css", "cbi-render-style"].map((id) => {
    const el = document.getElementById(id);
    return el ? el.textContent : "";
  }).join("\n");
  const style = document.createElementNS(SVG_NS, "style");
  style.textContent = css;
  svg.insertBefore(style, svg.firstChild);
}

function visibleMarks(svg) {
  const marks = new Set();
  for (const el of svg.querySelectorAll("[class]")) {
    for (const cls of el.getAttribute("class").split(/\s+/)) {
      if (cls.startsWith("chg-")) marks.add(cls.slice(4));
    }
  }
  return marks;
}

const KEY_PAD = 16;
const KEY_BG = { x: -8, y: -2, height: 26 };

// The key sits in a band under the camera. Its painted bounds, including the background
// stroke, stay inside the viewBox by KEY_PAD on the left, right and bottom.
function keyFrame(box, keyWidth, keyHeight) {
  const height = keyHeight == null ? KEY_BG.height : keyHeight;
  const localLeft = KEY_BG.x, localTop = KEY_BG.y;
  const localRight = KEY_BG.x + keyWidth, localBottom = KEY_BG.y + height;
  const tx = box.x + KEY_PAD - localLeft;
  const ty = box.y + box.height + KEY_PAD - localTop;
  const visualLeft = tx + localLeft, visualTop = ty + localTop;
  const visualRight = tx + localRight, visualBottom = ty + localBottom;
  const width = Math.max(box.width, visualRight + KEY_PAD - box.x);
  const frameH = visualBottom + KEY_PAD - box.y;
  return {
    transform: `translate(${tx},${ty})`,
    viewBox: `${box.x} ${box.y} ${width} ${frameH}`,
    x: box.x, y: box.y, width, height: frameH,
    key: { x: visualLeft, y: visualTop, width: visualRight - visualLeft, height: visualBottom - visualTop },
  };
}

function drawKey(svg) {
  const marks = visibleMarks(svg);
  const items = KEY.filter(([, , show]) => show(marks));
  if (!items.length) items.push(["none", "No changes"]);
  const box = svg.viewBox.baseVal;
  const g = document.createElementNS(SVG_NS, "g");
  g.setAttribute("class", "compact-key");
  let x = 0;
  const parts = [];
  for (const [mark, label] of items) {
    const sw = document.createElementNS(SVG_NS, "rect");
    sw.setAttribute("class", "swatch chg-" + mark);
    sw.setAttribute("x", x);
    sw.setAttribute("y", 5);
    sw.setAttribute("width", 18);
    sw.setAttribute("height", 12);
    sw.setAttribute("rx", 2);
    const text = document.createElementNS(SVG_NS, "text");
    text.setAttribute("x", x + 24);
    text.setAttribute("y", 16);
    text.textContent = label;
    parts.push(sw, text);
    x += 24 + label.length * 7 + 18;
  }
  const bg = document.createElementNS(SVG_NS, "rect");
  bg.setAttribute("class", "key-bg");
  bg.setAttribute("x", KEY_BG.x);
  bg.setAttribute("y", KEY_BG.y);
  bg.setAttribute("width", x);
  bg.setAttribute("height", KEY_BG.height);
  bg.setAttribute("rx", 6);
  g.append(bg, ...parts);
  const frame = keyFrame({ x: box.x, y: box.y, width: box.width, height: box.height }, x, KEY_BG.height);
  g.setAttribute("transform", frame.transform);
  svg.append(g);
  svg.setAttribute("viewBox", frame.viewBox);
}

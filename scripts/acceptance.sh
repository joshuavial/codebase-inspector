#!/usr/bin/env bash
# Acceptance checkpoint for one repo. The repo is not written: the model goes to <out dir>.
# Usage: scripts/acceptance.sh <repo> <out dir>
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: scripts/acceptance.sh <repo> <out dir>" >&2
  exit 2
fi

REPO=$(cd "$1" && pwd)
mkdir -p "$2"
OUT=$(cd "$2" && pwd)
CBI=$(cd "$(dirname "$0")/.." && pwd)

python3 -c 'import os, sys
out, repo = (os.path.realpath(p) for p in sys.argv[1:])
sys.exit(0 if out != repo and not out.startswith(repo + os.sep) else 1)' "$OUT" "$REPO" \
  || { echo "out dir must be outside the repo ($OUT is inside $REPO)" >&2; exit 2; }
git -C "$REPO" rev-parse --is-inside-work-tree >/dev/null

fail=0
finish() {
  local rc=$?
  set +e
  git_snap >"$OUT/git-after.txt"
  if cmp -s "$OUT/git-before.txt" "$OUT/git-after.txt"; then
    echo "PASS repo unchanged"
  else
    echo "FAIL repo changed"
    diff -u "$OUT/git-before.txt" "$OUT/git-after.txt" | head -n 80
    fail=1
  fi
  if [[ $rc -ne 0 ]]; then fail=1; fi
  exit "$fail"
}
trap finish EXIT

git_snap() {
  git -C "$REPO" status --porcelain=v1
  echo "---WORKTREES---"
  git -C "$REPO" worktree list --porcelain
  echo "---REFS---"
  git -C "$REPO" show-ref
  echo "---STASH---"
  git -C "$REPO" stash list
}

cbi() {
  (cd "$REPO" && uv run --project "$CBI" cbi "$@")
}

wall() {
  local label=$1
  shift
  local start rc
  start=$(python3 -c 'import time; print(f"{time.time():.6f}")')
  set +e
  "$@"
  rc=$?
  set -e
  python3 -c 'import sys, time; print(f"WALL {sys.argv[1]}: {time.time()-float(sys.argv[2]):.3f} s")' "$label" "$start"
  return "$rc"
}

echo "== git before =="
git_snap >"$OUT/git-before.txt"

echo "== init =="
cbi init --out "$OUT" | tee "$OUT/init.txt"

echo "== cold scan =="
wall cold cbi scan --out "$OUT" | tee "$OUT/cold-scan.txt"

echo "== no-change rescan =="
wall rescan cbi scan --out "$OUT" | tee "$OUT/rescan.txt"

echo "== status =="
cbi status --out "$OUT" | tee "$OUT/status.txt"

echo "== inventory =="
python3 - "$OUT/model.db" "$OUT/needles.json" <<'PY' | tee "$OUT/inventory.txt"
import json, sqlite3, sys
from collections import Counter

db, dest = sys.argv[1:]
conn = sqlite3.connect(db)

def section(title, rows):
    print(f"## {title}")
    if not rows:
        print("(none)")
    for row in rows:
        print("  " + "  ".join("" if c is None else str(c) for c in row))

section("workspaces", conn.execute(
    "SELECT name, path, json_extract(attrs, '$.initialised'), json_extract(attrs, '$.drift') "
    "FROM nodes WHERE kind = 'workspace' ORDER BY path, name").fetchall())
section("doc collections", conn.execute(
    "SELECT path, name FROM nodes WHERE display_kind = 'doc collection' ORDER BY path").fetchall())
section("symlinks", conn.execute(
    "SELECT path FROM nodes WHERE display_kind = 'symlink' ORDER BY path").fetchall())
section("deployables", conn.execute(
    "SELECT name, display_kind, json_extract(attrs, '$.entry_points'), path "
    "FROM nodes WHERE kind = 'deployable' ORDER BY name").fetchall())
section("packages", conn.execute(
    "SELECT display_kind, name, path FROM nodes WHERE kind = 'package' ORDER BY display_kind, name").fetchall())
section("externals", conn.execute(
    "SELECT name, display_kind, path FROM nodes WHERE kind = 'external' ORDER BY name").fetchall())

names = [r[0] for r in conn.execute("SELECT name FROM nodes") if r[0]]
low = [n.lower() for n in names]

def pick(kind):
    rows = [r[0] for r in conn.execute("SELECT name FROM nodes WHERE display_kind = ?", (kind,)) if r[0]]
    counts = Counter(rows)
    uniq = [n for n, c in counts.items() if c == 1 and n.isprintable() and "\n" not in n]
    singles = [n for n in uniq if " " not in n and 8 <= len(n) <= 48]
    singles.sort(key=len, reverse=True)
    pool = singles or sorted(uniq, key=len, reverse=True)
    for name in pool:
        needle = name.lower()
        if not any(other.startswith(needle) and other != needle for other in low):
            return name
    return pool[0] if pool else None

needles = {}
for kind in ("class", "function", "test case", "doc", "folder"):
    name = pick(kind)
    needles[kind] = name
    print(f"NEEDLE {kind}: {name if name else 'MISSING'}")
json.dump(needles, open(dest, "w"))
PY

echo "== cbi search =="
python3 -c 'import json,sys; d=json.load(open(sys.argv[1]));
[print(k+"\t"+(v or "")) for k,v in d.items()]' "$OUT/needles.json" >"$OUT/needle-lines.txt"
while IFS=$'\t' read -r kind name; do
  if [[ -z $name ]]; then
    echo "FAIL cbi search $kind: missing"
    fail=1
    continue
  fi
  cbi search --out "$OUT" --kind "$kind" --limit 12 "$name" >"$OUT/search-${kind// /-}.txt" || fail=1
  if grep -F -q "$name" "$OUT/search-${kind// /-}.txt"; then
    echo "PASS cbi search $kind: $name"
  else
    echo "FAIL cbi search $kind: $name"
    fail=1
  fi
done <"$OUT/needle-lines.txt"

echo "== hotspots =="
cbi hotspots --out "$OUT" --limit 5 | tee "$OUT/hotspots.txt"

echo "== cycles =="
cbi cycles --out "$OUT" | tee "$OUT/cycles.txt"

echo "== orphans =="
set +o pipefail
cbi orphans --out "$OUT" | head | tee "$OUT/orphans.txt" || true
set -o pipefail

echo "== build =="
wall build cbi build --out "$OUT" | tee "$OUT/build.txt"
index=$(grep -E 'index\.html$' "$OUT/build.txt" | tail -1)
if [[ ! -f $index ]]; then
  echo "FAIL viewer was not written" >&2
  fail=1
else
  echo "== viewer =="
  if ! uv run --with playwright python - "$OUT" "$index" <<'PY' | tee "$OUT/viewer.txt"; then
import json, sys
from pathlib import Path
from playwright.sync_api import sync_playwright

out, index = Path(sys.argv[1]), Path(sys.argv[2])
needles = json.loads((out / "needles.json").read_text())
failed = False
init = """
window.__cbiPaint = null;
const mark = () => {
  if (window.__cbiPaint != null || !document.querySelector) return;
  if (document.querySelector("#diagram .node")) window.__cbiPaint = performance.now();
};
const arm = () => {
  const root = document.documentElement;
  if (!root || root.nodeType !== 1) return false;
  if (!window.__cbiArmed) {
    window.__cbiArmed = true;
    new MutationObserver(mark).observe(root, {childList: true, subtree: true});
  }
  mark();
  return true;
};
if (!arm()) {
  const timer = setInterval(() => { if (arm()) clearInterval(timer); }, 0);
}
"""
with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    page = browser.new_page(viewport={"width": 1280, "height": 800})
    errors = []
    page.add_init_script(init)
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.goto(index.resolve().as_uri())
    page.wait_for_function("() => document.querySelectorAll('#diagram .node').length > 0", timeout=30000)
    paint = page.evaluate("() => window.__cbiPaint")
    print(f"FIRST_PAINT_MS {paint if paint is not None else 'MISSING'}")
    if paint is None:
        failed = True
    drill = page.evaluate("""() => {
      const before = document.getElementById('crumbs').textContent;
      for (const name of document.querySelectorAll('#diagram .name')) {
        const t0 = performance.now();
        name.dispatchEvent(new MouseEvent('click', {bubbles: true}));
        const ms = performance.now() - t0;
        const after = document.getElementById('crumbs').textContent;
        if (after !== before) return {ms, before, after};
      }
      return {ms: null, before, after: document.getElementById('crumbs').textContent};
    }""")
    if drill["ms"] is None:
        print("DRILL_MS MISSING")
        failed = True
    else:
        print(f"DRILL_MS {drill['ms']:.1f}")
    print(f"DRILL_CRUMBS {drill['before']} -> {drill['after']}")
    page.wait_for_function("() => document.documentElement.dataset.cbiTree === '1'", timeout=180000)
    for kind, name in needles.items():
        if not name:
            print(f"SEARCH {kind} MISSING")
            failed = True
            continue
        result = page.evaluate("""(needle) => {
          const q = document.getElementById('q');
          const t0 = performance.now();
          q.value = needle;
          q.dispatchEvent(new Event('input'));
          const ms = performance.now() - t0;
          const text = [...document.querySelectorAll('#hits li')].map((li) => li.innerText).join('\\n');
          q.value = '';
          q.dispatchEvent(new Event('input'));
          return {ms, text};
        }""", name)
        ok = name in result["text"]
        print(f"SEARCH_MS {result['ms']:.1f} {kind} {'PASS' if ok else 'FAIL'} {name}")
        if not ok:
            print(result["text"][:400])
            failed = True
    if errors:
        print("PAGE_ERRORS")
        print("\n".join(errors))
        failed = True
    browser.close()
sys.exit(1 if failed else 0)
PY
    fail=1
  fi
fi

echo "== budgets =="
  python3 - "$OUT" <<'PY' || fail=1
import re, sys
from pathlib import Path
out = Path(sys.argv[1])
def grab(path, pattern):
    text = path.read_text(errors="replace") if path.exists() else ""
    found = re.search(pattern, text)
    return float(found.group(1)) if found else None
cold = grab(out / "cold-scan.txt", r"^scanned in ([0-9.]+) s")
rescan = grab(out / "rescan.txt", r"^no changes since the last scan in ([0-9.]+) s")
viewer = (out / "viewer.txt").read_text(errors="replace") if (out / "viewer.txt").exists() else ""
paint = re.search(r"FIRST_PAINT_MS ([0-9.]+)", viewer)
drill = re.search(r"DRILL_MS ([0-9.]+)", viewer)
searches = [float(m) for m in re.findall(r"^SEARCH_MS ([0-9.]+) ", viewer, re.M)]
checks = [
    ("cold scan", cold, 60),
    ("no-change rescan", rescan, 10),
    ("first paint", (float(paint.group(1)) / 1000) if paint else None, 2),
    ("drill", (float(drill.group(1)) / 1000) if drill else None, 0.2),
]
for label, value, limit in checks:
    if value is None:
        print(f"FAIL {label}: missing")
        sys.exit(1)
    mark = "PASS" if value < limit else "FAIL"
    unit = "s"
    print(f"{mark} {label}: {value:.3f} {unit} < {limit:g} {unit}")
    if mark == "FAIL":
        sys.exit(1)
if not searches:
    print("FAIL search: missing")
    sys.exit(1)
worst = max(searches)
mark = "PASS" if worst < 200 else "FAIL"
print(f"{mark} search: {worst:.1f} ms < 200 ms")
if mark == "FAIL":
    sys.exit(1)
PY

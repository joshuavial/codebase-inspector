#!/usr/bin/env python3
"""Smoke comparison mode from file:// with Playwright.

Run from the repo (installs nothing into the project):

    uvx --from playwright python scripts/smoke_compare.py

Chromium has to be present for that Playwright. If launch fails:

    uvx --from playwright playwright install chromium

The fixture is a two-commit git repo mapped with this worktree's cbi.
Screenshots land in /tmp/cbi-p29-smoke.
"""

import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = Path("/tmp/cbi-p29-smoke")

BASE_FILES = {
    "src/app.py": "def run():\n    return 1\n",
    "src/ui.tsx": "export function Board() {\n  return <main>Hi</main>;\n}\n",
    "src/old.py": "def legacy():\n    return 0\n",
}
HEAD_FILES = {
    "src/app.py": "def run():\n    return 2\n",
    "src/ui.tsx": "export function Board() {\n  return <main>Hello</main>;\n}\n",
    "src/billing.py": "def charge():\n    return 1\n",
}


def concepts(body):
    return json.dumps(body)


def base_concepts():
    return concepts({
        "summary": "fixture",
        "concepts": [
            {"id": "app", "name": "App", "summary": "The process.", "role": "app", "files": ["src/app.py"]},
            {"id": "ui", "name": "UI", "summary": "The window.", "role": "ui", "files": ["src/ui.tsx"]},
            {"id": "legacy", "name": "Legacy", "summary": "Going away.", "role": "core", "files": ["src/old.py"]},
        ],
        "externals": [],
        "relationships": [],
    })


def head_concepts():
    return concepts({
        "summary": "fixture",
        "concepts": [
            {"id": "app", "name": "App", "summary": "The process.", "role": "app", "files": ["src/app.py"]},
            {"id": "ui", "name": "UI", "summary": "The window.", "role": "ui", "files": ["src/ui.tsx"]},
            {"id": "billing", "name": "Billing", "summary": "Takes payment.", "role": "service", "files": ["src/billing.py"]},
        ],
        "externals": [{"id": "stripe", "name": "Stripe", "summary": "Cards.", "kind": "saas"}],
        "relationships": [{
            "from": "billing", "to": "stripe", "label": "charges", "mechanism": "HTTP", "at": "src/billing.py:charge",
        }],
    })


def git(cwd, *args):
    subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@example.com", "-c", "commit.gpgsign=false", *args],
        cwd=cwd, check=True, capture_output=True, text=True,
    )


def cbi(cwd, *args):
    subprocess.run(["uv", "run", "--project", str(ROOT), "cbi", *args], cwd=cwd, check=True)


def write_tree(root, files):
    keep = set(files)
    for path in root.rglob("*"):
        if not path.is_file() or ".git" in path.parts or ".cbi" in path.parts:
            continue
        rel = path.relative_to(root).as_posix()
        if rel not in keep:
            path.unlink()
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    git(root, "add", "src")
    git(root, "commit", "-q", "-m", "fixture")


def seed(root, sha, text):
    home = root / ".cbi" / "refs" / sha
    home.mkdir(parents=True, exist_ok=True)
    (home / "concepts.json").write_text(text)


def decorate(db, screen_text, provisional):
    conn = sqlite3.connect(db)
    board = conn.execute("SELECT id FROM nodes WHERE name = 'Board' AND kind = 'symbol'").fetchone()
    if not board:
        raise SystemExit(f"no Board symbol in {db}")
    root = {"device": "phone", "root": {"layout": "column", "component": board[0], "text": screen_text}}
    conn.execute(
        "INSERT INTO nodes (id, parent_id, kind, display_kind, name, attrs) VALUES (?,?,?,?,?,?)",
        ("screen:home", "ui", "screen", "screen", "Home", json.dumps(root)),
    )
    if provisional:
        raw = conn.execute("SELECT attrs FROM nodes WHERE id = 'ui'").fetchone()[0]
        attrs = json.loads(raw)
        attrs["provisional"] = True
        conn.execute("UPDATE nodes SET attrs = ? WHERE id = 'ui'", (json.dumps(attrs),))
    conn.commit()
    conn.close()


def build_fixture():
    repo = OUT / "repo"
    if repo.exists():
        shutil.rmtree(repo)
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    write_tree(repo, BASE_FILES)
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    write_tree(repo, HEAD_FILES)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    cbi(repo, "init")
    seed(repo, base, base_concepts())
    seed(repo, head, head_concepts())
    cbi(repo, "build", "--compare", f"{base}..{head}")
    decorate(repo / ".cbi" / "refs" / base / "model.db", "Hi", False)
    decorate(repo / ".cbi" / "refs" / head / "model.db", "Hello", True)
    cbi(repo, "build", "--compare", f"{base}..{head}")
    index = repo / ".cbi" / "viewer" / "index.html"
    if not index.is_file():
        raise SystemExit(f"viewer was not written: {index}")
    return index


def check(name, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        raise SystemExit(1)


def names(page):
    return page.evaluate("() => [...document.querySelectorAll('#diagram .name')].map((n) => n.textContent)")


def wait_name(page, text):
    page.wait_for_function(
        """(needle) => [...document.querySelectorAll('#diagram .name')].some((n) => n.textContent === needle)""",
        arg=text, timeout=30000,
    )


def smoke(page, index):
    errors = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.goto(index.resolve().as_uri())
    wait_name(page, "Billing")
    if errors:
        raise SystemExit("page error on load:\n" + "\n".join(errors))
    page.screenshot(path=str(OUT / "top.png"))

    added = page.locator("#diagram g.node.chg-added").filter(has_text="Billing")
    removed = page.locator("#diagram g.node.chg-removed").filter(has_text="Legacy")
    changed = page.locator("#diagram g.node.chg-changed").filter(has_text="App")
    provisional = page.locator("#diagram g.node.chg-provisional").filter(has_text="UI")
    check("added concept mark", added.count() == 1)
    check("removed concept mark", removed.count() == 1)
    check("changed concept mark", changed.count() == 1)
    check("provisional mark", provisional.count() == 1, " ".join(provisional.first.get_attribute("class").split()))
    check("new integration mark", page.locator("#diagram .edge.chg-new").count() >= 1)
    pill = page.locator("#legend .key-pill")
    if pill.count():
        pill.click()
    key = page.locator("#legend").inner_text()
    check("key lists the marks", all(word in key for word in ("Added", "Removed", "Changed", "Provisional", "New line")), key)

    page.locator("#changes button.link").filter(has_text="run").first.click()
    page.wait_for_selector("#drawer .diff-add")
    page.wait_for_selector("#drawer .diff-del")
    diff_add = page.locator("#drawer .diff-add").inner_text()
    diff_del = page.locator("#drawer .diff-del").inner_text()
    check("code diff shows the new line", "return 2" in diff_add, diff_add)
    check("code diff shows the old line", "return 1" in diff_del, diff_del)
    text_node = page.evaluate(
        """() => {
          const row = document.querySelector('#drawer .diff-add');
          return row.childNodes.length === 1 && row.childNodes[0].nodeType === Node.TEXT_NODE;
        }"""
    )
    check("code diff is text", text_node)
    chip = page.locator("#crumbs .back").inner_text()
    check("panel link leaves a Back chip", chip.startswith("← Back to"), chip)
    page.screenshot(path=str(OUT / "function.png"))
    page.keyboard.press("Backspace")
    page.wait_for_function("() => !location.hash.includes('run')")
    wait_name(page, "Billing")
    check("Back returns to the map", "Billing" in names(page) and "run" not in page.evaluate("() => location.hash"))

    page.locator('#compare button[data-side="base"]').click()
    page.wait_for_function("() => location.hash.includes('side=base')")
    page.wait_for_function(
        """() => ![...document.querySelectorAll('#diagram .name')].some((n) => n.textContent === 'Billing')"""
    )
    wait_name(page, "Legacy")
    check("base hides the added concept", "Billing" not in names(page) and "Legacy" in names(page), " ".join(names(page)))
    page.locator('#compare button[data-side="head"]').click()
    page.wait_for_function("() => !location.hash.includes('side=base')")
    wait_name(page, "Billing")
    check("head restores the added concept", "Billing" in names(page))

    page.locator("#diagram g.node").filter(has_text="UI").first.click()
    page.wait_for_selector(".sketch-pair .when")
    pair = page.locator(".sketch-pair").inner_text()
    folded = pair.lower()
    check("wireframe before and after", "before" in folded and "after" in folded and "hi" in folded and "hello" in folded, pair.replace("\n", " | "))
    page.screenshot(path=str(OUT / "sketch.png"))

    page.set_viewport_size({"width": 800, "height": 700})
    page.wait_for_timeout(300)
    closed = page.evaluate("() => getComputedStyle(document.getElementById('changes')).display === 'none'")
    check("narrow map hides the changes panel", closed)
    page.locator("#chg-toggle").click()
    page.wait_for_function("() => document.body.classList.contains('changes-open')")
    opened = page.evaluate("() => getComputedStyle(document.getElementById('changes')).display !== 'none'")
    check("narrow changes toggle opens the panel", opened)
    if errors:
        raise SystemExit("page error during smoke:\n" + "\n".join(errors))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    index = build_fixture()
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1400, "height": 900}, device_scale_factor=1)
        smoke(page, index)
        browser.close()
    print(f"screenshots in {OUT}")


if __name__ == "__main__":
    sys.exit(main() or 0)

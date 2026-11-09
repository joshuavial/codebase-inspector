"""Double-click opens a file and a concept still drills. The editor is not launched."""

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from cbi import build


def _viewer():
    path = Path(__file__).with_name("test_viewer.py")
    spec = importlib.util.spec_from_file_location("cbi_test_viewer_page", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_fixture = _viewer()
concept_model = _fixture.concept_model
API, APP, FN, UI = _fixture.API, _fixture.APP, _fixture.FN, _fixture.UI

DRIVER = r"""
import json
import sys
from pathlib import Path
from urllib.parse import quote
from playwright.sync_api import sync_playwright

index, fn, app, api, ui, project = sys.argv[1:]
errors = []

def css(node_id):
    return "[data-id=" + json.dumps(node_id) + "]"

def enc(part):
    return quote(part, safe="-_.!~*'()")

with sync_playwright() as p:
    try:
        browser = p.chromium.launch(headless=True)
    except Exception:
        browser = p.chromium.launch(channel="chrome", headless=True)
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.add_init_script(
        "window.__opened = [];"
        "window.cbiOpenInEditor = (payload) => { window.__opened.push(payload); return { ok: true }; };"
    )
    page.goto(Path(index).resolve().as_uri())
    page.wait_for_selector(css(app), timeout=20000)

    def dump(label):
        state = page.evaluate(
            "() => ({ hash: location.hash,"
            " ids: [...document.querySelectorAll('[data-id]')].map((n) => n.getAttribute('data-id')),"
            " names: [...document.querySelectorAll('#diagram .name')].map((n) => n.textContent) })"
        )
        raise SystemExit(label + " " + json.dumps(state) + " errors " + json.dumps(errors))

    page.evaluate("(id) => { location.hash = new URLSearchParams({c: id}).toString(); }", api)
    try:
        page.wait_for_selector(css(fn), state="attached", timeout=20000)
    except Exception:
        dump("function missing")
    page.locator(css(fn)).dblclick(force=True)
    page.wait_for_function("() => window.__opened.length === 1", timeout=5000)
    opened = page.evaluate("() => window.__opened")
    if opened != [{"file": "a.ts", "line": 1}]:
        raise SystemExit("function open " + json.dumps(opened))
    if "Open in editor" not in page.locator("#drawer").inner_text():
        raise SystemExit("drawer missing Open in editor")
    page.evaluate("() => { window.__opened = []; location.hash = ''; }")
    page.wait_for_selector(css(app), timeout=20000)
    page.locator(css(app)).dblclick()
    page.wait_for_function(
        "(id) => new URLSearchParams(location.hash.slice(1)).get('c') === id",
        arg=app,
        timeout=5000,
    )
    page.wait_for_selector(css(api), state="attached", timeout=20000)
    if page.evaluate("() => window.__opened"):
        raise SystemExit("concept double-click opened a file")
    page.evaluate(
        "(id) => { window.__opened = []; location.hash = new URLSearchParams({c: id, v: 'code'}).toString(); }",
        ui,
    )
    try:
        page.wait_for_selector(css(fn), state="attached", timeout=20000)
    except Exception:
        dump("ghost missing")
    page.locator(css(fn)).dblclick(force=True)
    page.wait_for_function("() => window.__opened.length === 1", timeout=5000)
    opened = page.evaluate("() => window.__opened")
    if opened != [{"file": "a.ts", "line": 1}]:
        raise SystemExit("ghost open " + json.dumps(opened))
    focus = page.evaluate("() => new URLSearchParams(location.hash.slice(1)).get('c')")
    if focus != ui:
        raise SystemExit("ghost double-click changed concept to " + str(focus))
    if "Go to" not in page.locator("#drawer").inner_text():
        raise SystemExit("ghost drawer lost Go to")
    href = page.evaluate("() => window.cbiEditorHref('a.ts', 1)")
    root = Path(project).resolve().as_posix()
    encoded = "/".join(enc(part) for part in (root + "/a.ts").split("/"))
    expected = "vscode://file" + encoded + ":1"
    if href != expected:
        raise SystemExit("href " + href + " != " + expected)
    browser.close()
if errors:
    raise SystemExit("page errors:\n" + "\n".join(errors))
print("ok")
"""


def _playwright_python():
    try:
        from conftest import find_playwright_runner
        runner, _ = find_playwright_runner()
        return runner[0] if runner and len(runner) == 1 else None
    except Exception:
        return None


def test_double_click_opens_a_function_and_a_concept_drills(tmp_path, playwright_runner, check_playwright):
    conn = concept_model(tmp_path)
    project = tmp_path / "proj"
    project.mkdir()
    viewer = build.build(conn, tmp_path / "viewer", project=project)
    script = tmp_path / "drive_editor.py"
    script.write_text(DRIVER)
    proc = subprocess.run(
        playwright_runner + [str(script), str(viewer), FN, APP, API, UI, str(project)],
        capture_output=True, text=True, timeout=60,
    )
    check_playwright(proc)
    assert "ok" in proc.stdout


REF_DRIVER = r"""
import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

index, fn, api, sha = sys.argv[1:]
errors = []

def css(node_id):
    return "[data-id=" + json.dumps(node_id) + "]"

with sync_playwright() as p:
    try:
        browser = p.chromium.launch(headless=True)
    except Exception:
        browser = p.chromium.launch(channel="chrome", headless=True)
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.add_init_script(
        "window.__copied = [];"
        "Object.defineProperty(navigator, 'clipboard', { configurable: true, value: {"
        "  writeText: (text) => { window.__copied.push(String(text)); return Promise.resolve(); }"
        "} });"
    )
    page.goto(Path(index).resolve().as_uri())
    page.evaluate("(id) => { location.hash = new URLSearchParams({c: id}).toString(); }", api)
    page.wait_for_selector(css(fn), state="attached", timeout=20000)
    page.locator(css(fn)).dblclick(force=True)
    page.wait_for_function("() => window.__copied.length === 1", timeout=5000)
    copied = page.evaluate("() => window.__copied")
    expected = "git show " + sha + ":a.ts"
    if copied != [expected]:
        raise SystemExit("copied " + json.dumps(copied))
    drawer = page.locator("#drawer").inner_text()
    if "Copy git show command" not in drawer:
        raise SystemExit("drawer " + drawer)
    if "Open in editor" in drawer:
        raise SystemExit("ref drawer still says Open in editor")
    toast = page.locator("#toast").inner_text()
    if toast != "Copied git show command":
        raise SystemExit("toast " + toast)
    browser.close()
if errors:
    raise SystemExit("page errors:\n" + "\n".join(errors))
print("ok")
"""


def test_ref_view_copies_the_git_show_command(tmp_path, playwright_runner, check_playwright):
    conn = concept_model(tmp_path)
    project = tmp_path / "proj"
    project.mkdir()
    sha = "b" * 40
    viewer = build.build(conn, tmp_path / "viewer", project=project, ref_sha=sha)
    script = tmp_path / "drive_ref.py"
    script.write_text(REF_DRIVER)
    proc = subprocess.run(
        playwright_runner + [str(script), str(viewer), FN, API, sha],
        capture_output=True, text=True, timeout=60,
    )
    check_playwright(proc)
    assert "ok" in proc.stdout

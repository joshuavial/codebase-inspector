"""Top-level system tabs and the database viewer in a headless browser."""

import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from cbi import build, render
from cbi.cli import main


FIXTURE = Path(__file__).parent / "fixtures" / "data" / "system"


def _playwright_python():
    seen = []
    for exe in ("/opt/homebrew/bin/python3", "/usr/local/bin/python3", "/usr/bin/python3",
                shutil.which("python3"), sys.executable):
        if not exe or exe in seen or not Path(exe).is_file():
            continue
        seen.append(exe)
        if subprocess.run([exe, "-c", "import playwright"], capture_output=True).returncode == 0:
            return exe
    return None


def _viewer(make_repo, monkeypatch, capsys, with_history=False):
    root = make_repo({path.relative_to(FIXTURE).as_posix(): path.read_text()
                      for path in FIXTURE.rglob("*") if path.is_file()}, name="system-viewer")
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    capsys.readouterr()
    conn = sqlite3.connect(root / ".cbi/model.db")
    ws = "local:system-viewer"
    concept = ws + ":concept:data"
    conn.execute(
        "INSERT INTO nodes (id, parent_id, kind, display_kind, name, workspace_id, summary, attrs) "
        "VALUES (?, ?, 'concept', 'service', 'Data service', ?, 'Lists accounts.', ?)",
        (concept, ws, ws, json.dumps({"role": "service", "order": 0})))
    service = conn.execute("SELECT id FROM nodes WHERE path = 'service.py' AND kind = 'file'").fetchone()[0]
    conn.execute(
        "INSERT INTO edges (src, dst, kind, source, confidence, weight) VALUES (?, ?, 'owns', 'fixture', 1, 1)",
        (concept, service))
    conn.execute("UPDATE nodes SET summary = 'Lists customer accounts.' WHERE name = 'accounts' AND kind = 'symbol'")
    conn.commit()
    timeline = None
    if with_history:
        model = build.concept_view(conn, root)
        entries = []
        for index in range(2):
            sha = str(index + 1) * 40
            entries.append({
                "sha": sha, "base": "0" * 40, "date": f"2026-10-0{index + 1}T08:00:00+13:00",
                "author": "Test Author", "change_count": index + 1, "text": "Fixture history.",
                "model": model,
                "diff": {
                    "base": "0" * 40, "head": sha, "provisional": [], "sources": {},
                    "changes": {"groups": []},
                    "removed": {"concepts": [], "relationships": [], "externals": []},
                },
            })
        timeline = {"entries": entries}
    return build.build(conn, root / ".cbi/viewer", root, history=timeline), root


DRIVER = r'''
import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

index, database_png, endpoint_png = sys.argv[1:]
errors = []
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1500, "height": 920})
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.goto(Path(index).resolve().as_uri() + "#tab=database")
    table = "local:system-viewer:table:accounts"
    page.wait_for_selector('[data-id=' + json.dumps(table) + ']', timeout=20000)
    tabs = page.locator("#system-tabs button")
    if tabs.count() != 3 or tabs.filter(has_text="Database").get_attribute("class") != "on":
        raise SystemExit("tabs not ready")
    before = page.locator("#diagram").get_attribute("viewBox")
    page.dispatch_event("#stage", "wheel", {"deltaX": 45, "deltaY": 20})
    after_pan = page.locator("#diagram").get_attribute("viewBox")
    if before == after_pan:
        raise SystemExit("database did not pan")
    page.locator("#zin").click()
    after_zoom = page.locator("#diagram").get_attribute("viewBox")
    if after_zoom == after_pan:
        raise SystemExit("database did not zoom")
    page.locator('[data-id=' + json.dumps(table) + ']').click()
    page.wait_for_function("() => new URLSearchParams(location.hash.slice(1)).has('table')")
    drawer = page.locator("#drawer").inner_text()
    for wanted in ("accounts", "id", "email", "reads", "list_accounts"):
        if wanted not in drawer.lower():
            raise SystemExit("drawer missing " + wanted + ": " + drawer)
    page.screenshot(path=database_png)
    page.locator("#drawer button", has_text="list_accounts").click()
    page.wait_for_function("() => new URLSearchParams(location.hash.slice(1)).get('fromtab') === 'database'")
    if "Back to Database" not in page.locator("#crumbs").inner_text():
        raise SystemExit("database return chip missing")
    page.locator("#crumbs button", has_text="Back to Database").click()
    page.wait_for_function("() => new URLSearchParams(location.hash.slice(1)).get('tab') === 'database'")
    page.keyboard.press("Escape")
    page.wait_for_function("() => !new URLSearchParams(location.hash.slice(1)).has('table')")
    page.locator("#system-tabs button", has_text="API endpoints").click()
    page.wait_for_selector(".endpoint-row", timeout=20000)
    if page.locator(".endpoint-row").count() != 2:
        raise SystemExit("endpoint list did not include matched and unmatched routes")
    page.locator('select[aria-label="Filter endpoint method"]').select_option("POST")
    page.wait_for_function("() => document.querySelectorAll('.endpoint-row').length === 1")
    if "POST" not in page.locator(".endpoint-row").inner_text():
        raise SystemExit("method filter did not keep POST")
    page.locator('select[aria-label="Filter endpoint method"]').select_option("")
    page.wait_for_function("() => document.querySelectorAll('.endpoint-row').length === 2")
    page.locator('input[aria-label="Filter API endpoints"]').fill("lists customer")
    page.keyboard.press("Enter")
    page.wait_for_function("() => document.querySelectorAll('.endpoint-row').length === 1")
    page.locator(".endpoint-row").click()
    page.wait_for_function("() => new URLSearchParams(location.hash.slice(1)).has('endpoint')")
    drawer = page.locator("#drawer").inner_text().lower()
    for wanted in ("lists customer accounts", "handler", "called by", "calls", "tables", "accounts"):
        if wanted not in drawer:
            raise SystemExit("endpoint drawer missing " + wanted + ": " + drawer)
    page.screenshot(path=endpoint_png)
    page.locator("#drawer button", has_text="accounts").last.click()
    page.wait_for_function("() => new URLSearchParams(location.hash.slice(1)).get('fromtab') === 'endpoints'")
    if "Back to API endpoints" not in page.locator("#crumbs").inner_text():
        raise SystemExit("endpoint return chip missing from database")
    page.locator("#crumbs button", has_text="Back to API endpoints").click()
    page.wait_for_function("() => new URLSearchParams(location.hash.slice(1)).has('endpoint')")
    page.locator("#drawer button", has_text="list_accounts").last.click()
    page.wait_for_function("() => new URLSearchParams(location.hash.slice(1)).get('fromtab') === 'endpoints'")
    page.locator("#crumbs button", has_text="Back to API endpoints").click()
    page.wait_for_function("() => new URLSearchParams(location.hash.slice(1)).has('endpoint')")
    page.keyboard.press("Escape")
    page.wait_for_function("() => !new URLSearchParams(location.hash.slice(1)).has('endpoint')")
    browser.close()
if errors:
    raise SystemExit("page errors: " + json.dumps(errors))
print("ok")
'''

LARGE_DRIVER = r'''
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

index = sys.argv[1]
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1600, "height": 1000})
    page.goto(Path(index).resolve().as_uri() + "?render=1#tab=database")
    page.wait_for_function("() => document.title === 'cbi-viewer-ready'", timeout=60000)
    if int(page.locator("#diagram").get_attribute("data-database-groups") or "0") < 2:
        raise SystemExit("large schema was not grouped")
    boxes = page.locator(".db-table .name").evaluate_all(
        "els => els.map(el => el.getBoundingClientRect().height).filter(Boolean)")
    if len(boxes) != 92 or min(boxes) < 8:
        diagram = page.locator("#diagram")
        raise SystemExit("table names are not legible at fit: " + repr((
            len(boxes), min(boxes or [0]), diagram.get_attribute("data-layout"),
            diagram.get_attribute("viewBox"))))
    browser.close()
'''


HISTORY_DRIVER = r'''
import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

index = sys.argv[1]
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1500, "height": 920})
    page.goto(Path(index).resolve().as_uri())
    page.wait_for_selector("#timeline:not([hidden])", timeout=20000)
    if not page.locator("#compare").is_hidden():
        raise SystemExit("comparison controls shown during history replay")
    page.locator("#history-scrub").fill("0")
    page.wait_for_function("() => document.querySelector('#history-entry').innerText.includes('111111111111')")

    page.locator("#system-tabs button", has_text="Database").click()
    page.wait_for_selector(".db-table", timeout=20000)
    if not page.locator("#timeline").is_hidden() or not page.locator("#history-back").is_hidden():
        raise SystemExit("history controls shown on database tab")
    page.locator("#system-tabs button", has_text="Concept map").click()
    page.wait_for_selector("#timeline:not([hidden])")
    if "111111111111" not in page.locator("#history-entry").inner_text():
        raise SystemExit("history replay selection was lost across tabs")

    page.locator("#history-entry button", has_text="Open comparison").click()
    page.wait_for_selector("#history-back:not([hidden])")
    if not page.locator("#timeline").is_hidden() or page.locator("#compare").is_hidden():
        raise SystemExit("history comparison chrome is inconsistent")
    page.locator("#system-tabs button", has_text="API endpoints").click()
    page.wait_for_selector(".endpoint-row", timeout=20000)
    if not page.locator("#timeline").is_hidden() or not page.locator("#history-back").is_hidden():
        raise SystemExit("history comparison controls shown on endpoint tab")
    page.keyboard.press("Backspace")
    page.wait_for_selector("#history-back:not([hidden])")
    if page.locator("#system-tabs button", has_text="Concept map").get_attribute("class") != "on":
        raise SystemExit("Backspace did not return to concept comparison")
    page.locator("#history-back").click()
    page.wait_for_selector("#timeline:not([hidden])")

    page.locator("#system-tabs button", has_text="Database").click()
    page.wait_for_selector(".db-table", timeout=20000)
    page.keyboard.press("Backspace")
    page.wait_for_selector("#timeline:not([hidden])")
    if page.locator("#history-scrub").input_value() != "0":
        raise SystemExit("history replay selection was lost after Backspace")

    page.locator("#system-tabs button", has_text="Database").click()
    table = "local:system-viewer:table:accounts"
    page.locator('[data-id=' + json.dumps(table) + ']').click()
    page.wait_for_function("() => new URLSearchParams(location.hash.slice(1)).has('table')")
    page.keyboard.press("Escape")
    page.wait_for_function("() => !new URLSearchParams(location.hash.slice(1)).has('table')")
    browser.close()
'''


def test_database_tab_pan_zoom_drawer_and_two_way_jump(make_repo, monkeypatch, capsys, tmp_path):
    exe = _playwright_python()
    if not exe:
        pytest.skip("playwright is not installed for this python")
    viewer, _root = _viewer(make_repo, monkeypatch, capsys)
    script = tmp_path / "drive_database.py"
    script.write_text(DRIVER)
    png = tmp_path / "database.png"
    endpoint_png = tmp_path / "endpoints.png"
    proc = subprocess.run([exe, str(script), str(viewer), str(png), str(endpoint_png)], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert png.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert endpoint_png.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_history_replay_and_comparison_survive_system_tab_navigation(make_repo, monkeypatch, capsys, tmp_path):
    exe = _playwright_python()
    if not exe:
        pytest.skip("playwright is not installed for this python")
    viewer, _root = _viewer(make_repo, monkeypatch, capsys, with_history=True)
    script = tmp_path / "drive_history_tabs.py"
    script.write_text(HISTORY_DRIVER)
    proc = subprocess.run([exe, str(script), str(viewer)], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_database_capture_uses_cbi_render_path_when_chrome_is_installed(make_repo, monkeypatch, capsys, tmp_path):
    if render.find_chrome() is None:
        pytest.skip("no system Chrome or Chromium")
    viewer, _root = _viewer(make_repo, monkeypatch, capsys)
    png = render.viewer_png(viewer, "tab=database", tmp_path / "database-render.png")
    assert png.read_bytes().startswith(b"\x89PNG\r\n\x1a\n") and png.stat().st_size > 1000
    endpoint_png = render.viewer_png(viewer, "tab=endpoints", tmp_path / "endpoints-render.png")
    assert endpoint_png.read_bytes().startswith(b"\x89PNG\r\n\x1a\n") and endpoint_png.stat().st_size > 1000


def test_large_database_groups_and_keeps_table_names_legible(make_repo, monkeypatch, capsys, tmp_path):
    exe = _playwright_python()
    if not exe:
        pytest.skip("playwright is not installed for this python")
    statements = []
    for prefix, count in (("core", 52), ("billing", 23)):
        for index in range(count):
            foreign = f", previous_id INTEGER REFERENCES {prefix}_{index - 1}(id)" if index else ""
            statements.append(f"CREATE TABLE {prefix}_{index} (id INTEGER PRIMARY KEY{foreign});")
    for index in range(17):
        statements.append(f"CREATE TABLE lookup_{index} (id INTEGER PRIMARY KEY);")
    root = make_repo({"migrations/001.sql": "\n".join(statements)}, name="large-schema")
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    capsys.readouterr()
    assert main(["build"]) == 0
    viewer = Path(capsys.readouterr().out.strip())
    script = tmp_path / "drive_large_database.py"
    script.write_text(LARGE_DRIVER)
    proc = subprocess.run([exe, str(script), str(viewer)], capture_output=True, text=True, timeout=90)
    assert proc.returncode == 0, proc.stdout + proc.stderr

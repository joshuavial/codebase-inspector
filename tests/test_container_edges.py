"""Relationships that end on a container are drawn beside it, matching the drawer."""

import json
from pathlib import Path

import pytest

from conftest import run_playwright

from cbi import build, store
from cbi.cli import main

WS = "local:repo"
BOX = f"{WS}:concept:box"
LEFT = f"{WS}:concept:left"
RIGHT = f"{WS}:concept:right"
CALLER = f"{WS}:concept:caller"
NEIGHBOUR = f"{WS}:concept:neighbour"
SINK = f"{WS}:concept:sink"
FILE_LEFT = f"{WS}:left.ts"
FILE_RIGHT = f"{WS}:right.ts"
FILE_CALL = f"{WS}:call.ts"
ALPHA = f"{FILE_LEFT}#alpha"
BETA = f"{FILE_RIGHT}#beta"
GO = f"{FILE_CALL}#go"
FOLDER_CBI = f"{WS}:group:src/cbi"
FOLDER_PARSE = f"{WS}:group:src/cbi/parse"
FILE_INIT = f"{WS}:src/cbi/parse/__init__.py"
FILE_CSHARP = f"{WS}:src/cbi/parse/csharp.py"
FILE_GRAPH = f"{WS}:src/cbi/graph.py"

# Playwright is not a project dependency. The checker runs under uvx, same as scripts/smoke_viewer.py.
_CHECK = r"""
import json, sys
from pathlib import Path
from playwright.sync_api import sync_playwright

index, focus = sys.argv[1:]
url = Path(index).resolve().as_uri() + "#c=" + focus
with sync_playwright() as p:
    try:
        browser = p.chromium.launch(headless=True)
    except Exception:
        browser = p.chromium.launch(channel="chrome", headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    errors = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.goto(url)
    page.wait_for_function(
        "() => document.querySelectorAll('#diagram [data-lane]').length >= 3",
        timeout=30000,
    )
    page.wait_for_timeout(400)
    info = page.evaluate(
        '''() => {
          const head = (name) => {
            const h = [...document.querySelectorAll("#drawer h3")].find((n) => n.textContent.startsWith(name));
            if (!h) return 0;
            const m = h.textContent.match(/\\((\\d+)\\)/);
            return m ? Number(m[1]) : 0;
          };
          const box = (n) => n.getBoundingClientRect();
          const boundary = box(document.querySelector("#diagram .boundary"));
          const lane = (side) => [...document.querySelectorAll('#diagram [data-lane="' + side + '"]')];
          const ins = lane("in"), outs = lane("out");
          const stated = document.querySelectorAll("#diagram .edge.stated").length;
          const badge = [...document.querySelectorAll("#diagram .edge.port .count text")].map((n) => n.textContent);
          const key = document.querySelector("#legend").innerText;
          const dots = [...document.querySelectorAll("#drawer .dot")].map((n) => n.className);
          const probe = document.createElement("span");
          probe.className = "dot role-data";
          document.querySelector("#drawer").append(probe);
          legendFromDiagram(document.getElementById("diagram"));
          const keyWithData = document.querySelector("#legend").innerText;
          probe.remove();
          legendFromDiagram(document.getElementById("diagram"));
          return {
            usedBy: head("Used by"), uses: head("Uses"),
            laneIn: ins.length, laneOut: outs.length, stated, badge,
            incomingInside: ins.some((n) => box(n).right > boundary.left + 2),
            outgoingInside: outs.some((n) => box(n).left < boundary.right - 2),
            crumbs: document.querySelector("#crumbs").innerText,
            key, dots, keyWithData,
          };
        }'''
    )
    caller = page.locator("#drawer ul.usage li").filter(has_text="Caller")
    caller.hover()
    page.wait_for_function(
        "() => { const p = document.querySelector('#usage-pop'); return p && !p.hidden && p.innerText.includes('reads the model'); }"
    )
    info["hover"] = page.locator("#usage-pop").inner_text()
    info["hoverLinked"] = page.locator("#diagram .linked").count()
    page.locator("#drawer ul.usage li").filter(has_text="Neighbour").locator("button").focus()
    page.wait_for_function(
        "() => { const p = document.querySelector('#usage-pop'); return p && !p.hidden && p.innerText.includes('states a link'); }"
    )
    info["focus"] = page.locator("#usage-pop").inner_text()
    info["focusLinked"] = page.locator("#diagram .linked").count()
    browser.close()
if errors:
    print("\n".join(errors))
    sys.exit(1)
print(json.dumps(info))
"""


def _node(conn, **kw):
    kw.setdefault("display_kind", kw.get("kind", "node"))
    attrs = kw.get("attrs")
    conn.execute(
        "INSERT INTO nodes (id, parent_id, kind, display_kind, name, workspace_id, path, "
        "start_line, end_line, signature, summary, attrs) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (kw["id"], kw.get("parent_id"), kw["kind"], kw["display_kind"], kw["name"], kw.get("workspace_id", WS),
         kw.get("path"), kw.get("start_line"), kw.get("end_line"), kw.get("signature"), kw.get("summary"),
         json.dumps(attrs) if attrs is not None else None),
    )


def _edge(conn, src, dst, kind, attrs=None, ordinal=0):
    conn.execute(
        "INSERT INTO edges (src, dst, kind, source, confidence, weight, ordinal, attrs) VALUES (?,?,?,?,?,?,?,?)",
        (src, dst, kind, "fixture", 1, 1, ordinal, json.dumps(attrs) if attrs else None),
    )


def _model(tmp_path):
    conn = store.open_db(tmp_path / "model.db")
    _node(conn, id=WS, kind="workspace", display_kind="workspace", name="fixture", parent_id=None, workspace_id=None)
    _node(conn, id=BOX, parent_id=WS, kind="concept", display_kind="core logic", name="Box",
          summary="The container.", attrs={"role": "core"})
    _node(conn, id=LEFT, parent_id=BOX, kind="concept", display_kind="core logic", name="Left",
          summary="Left child.", attrs={"role": "core"})
    _node(conn, id=RIGHT, parent_id=BOX, kind="concept", display_kind="core logic", name="Right",
          summary="Right child.", attrs={"role": "core"})
    _node(conn, id=CALLER, parent_id=WS, kind="concept", display_kind="service", name="Caller",
          summary="Calls in.", attrs={"role": "service"})
    _node(conn, id=NEIGHBOUR, parent_id=WS, kind="concept", display_kind="service", name="Neighbour",
          summary="States a link.", attrs={"role": "service"})
    _node(conn, id=SINK, parent_id=WS, kind="concept", display_kind="service", name="Sink",
          summary="Stated outgoing.", attrs={"role": "service"})
    _node(conn, id=FILE_LEFT, parent_id=WS, kind="file", display_kind="source file", name="left.ts", path="left.ts")
    _node(conn, id=FILE_RIGHT, parent_id=WS, kind="file", display_kind="source file", name="right.ts", path="right.ts")
    _node(conn, id=FILE_CALL, parent_id=WS, kind="file", display_kind="source file", name="call.ts", path="call.ts")
    _node(conn, id=ALPHA, parent_id=FILE_LEFT, kind="symbol", display_kind="function", name="alpha", path="left.ts",
          start_line=1, end_line=3, signature="function alpha()")
    _node(conn, id=BETA, parent_id=FILE_RIGHT, kind="symbol", display_kind="function", name="beta", path="right.ts",
          start_line=1, end_line=3, signature="function beta()")
    _node(conn, id=GO, parent_id=FILE_CALL, kind="symbol", display_kind="function", name="go", path="call.ts",
          start_line=1, end_line=3, signature="function go()")
    for src, dst in ((LEFT, FILE_LEFT), (RIGHT, FILE_RIGHT), (CALLER, FILE_CALL)):
        _edge(conn, src, dst, "owns")
    _edge(conn, GO, ALPHA, "calls")
    _edge(conn, CALLER, BOX, "relates", {"label": "reads the model"})
    _edge(conn, CALLER, BOX, "relates", {"label": "watches"}, ordinal=1)
    _edge(conn, NEIGHBOUR, BOX, "relates", {"label": "states a link"})
    _edge(conn, BOX, SINK, "relates", {"label": "publishes"})
    conn.commit()
    return conn


def _folder_model(tmp_path):
    conn = store.open_db(tmp_path / "model.db")
    _node(conn, id=WS, kind="workspace", display_kind="workspace", name="fixture", parent_id=None, workspace_id=None)
    _node(conn, id=FOLDER_CBI, parent_id=WS, kind="group", display_kind="folder", name="cbi", path="src/cbi")
    _node(conn, id=FOLDER_PARSE, parent_id=FOLDER_CBI, kind="group", display_kind="folder", name="parse", path="src/cbi/parse")
    _node(conn, id=FILE_INIT, parent_id=FOLDER_PARSE, kind="file", display_kind="source file",
          name="__init__.py", path="src/cbi/parse/__init__.py", attrs={"role": "code"})
    _node(conn, id=FILE_CSHARP, parent_id=FOLDER_PARSE, kind="file", display_kind="source file",
          name="csharp.py", path="src/cbi/parse/csharp.py", attrs={"role": "code"})
    _node(conn, id=FILE_GRAPH, parent_id=FOLDER_CBI, kind="file", display_kind="source file",
          name="graph.py", path="src/cbi/graph.py", attrs={"role": "code"})
    _edge(conn, FILE_INIT, FILE_CSHARP, "imports")
    conn.commit()
    return conn


def test_container_relationships_match_the_drawer(tmp_path, playwright_runner, check_playwright):
    index = build.build(_model(tmp_path), tmp_path / "viewer")
    script = tmp_path / "check_view.py"
    script.write_text(_CHECK)
    proc = run_playwright(
        playwright_runner, script, index, BOX, timeout=180,
    )
    check_playwright(proc)
    info = json.loads(proc.stdout)
    assert info["crumbs"].endswith("Box")
    assert info["usedBy"] == info["laneIn"] == 2
    assert info["uses"] == info["laneOut"] == 1
    assert info["stated"] >= 2
    assert "2" in info["badge"]
    assert info["incomingInside"] is False
    assert info["outgoingInside"] is False
    roles = {
        "ui": "Interface", "app": "App or process", "service": "Service",
        "core": "Core logic", "data": "Data and model",
        "platform": "Platform service", "cli": "CLI tool", "saas": "SaaS or API",
        "terminal": "Terminal or OS", "storage": "Storage",
    }
    assert "Service" in info["key"] and "Core logic" in info["key"]
    assert "Data and model" not in info["key"]
    assert "Data and model" in info["keyWithData"]
    for cls in info["dots"]:
        for token in cls.split():
            if token.startswith("role-") or token.startswith("kind-"):
                label = roles[token.split("-", 1)[1]]
                assert label in info["key"], (cls, label, info["key"])
    hover, focus = info["hover"], info["focus"]
    assert "reads the model" in hover and "watches" in hover
    assert "1 resolved call" in hover
    assert "go → alpha" in hover and "call.ts:1" in hover
    assert info["hoverLinked"] > 0
    assert "states a link" in focus and "stated by the concept map" in focus
    assert info["focusLinked"] > 0


def test_deps_forbid_json_clean_architecture(tmp_path, capsys):
    conn = _model(tmp_path)
    conn.execute("UPDATE nodes SET attrs = json_set(coalesce(attrs, '{}'), '$.role', 'code') WHERE kind = 'file'")
    conn.commit()
    conn.close()

    code = main(["deps", "--out", str(tmp_path), "--level", "concept", "--forbid", "Caller:Left", "--json"])
    assert code == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["level"] == "concept"
    assert data["include_tests"] is False
    assert data["passed"] is True
    assert len(data["rules"]) == 1
    assert data["rules"][0]["spec"] == "Caller:Left"
    assert data["rules"][0]["passed"] is True
    assert data["rules"][0]["violations"] == []


def test_deps_forbid_json_violation_detected(tmp_path, capsys):
    conn = _model(tmp_path)
    conn.execute("UPDATE nodes SET attrs = json_set(coalesce(attrs, '{}'), '$.role', 'code') WHERE kind = 'file'")
    _edge(conn, FILE_CALL, FILE_LEFT, "imports")
    conn.commit()
    conn.close()

    code = main(["deps", "--out", str(tmp_path), "--level", "concept", "--forbid", "Caller:Left", "--json"])
    assert code == 1
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["level"] == "concept"
    assert data["include_tests"] is False
    assert data["passed"] is False
    assert len(data["rules"]) == 1
    assert data["rules"][0]["spec"] == "Caller:Left"
    assert data["rules"][0]["passed"] is False
    assert data["rules"][0]["violations"] == [{"from": "call.ts", "to": "left.ts"}]


def test_cycles_fail_json_clean_codebase(tmp_path, capsys):
    conn = _model(tmp_path)
    conn.execute("UPDATE nodes SET attrs = json_set(coalesce(attrs, '{}'), '$.role', 'code') WHERE kind = 'file'")
    conn.commit()
    conn.close()

    code = main(["cycles", "--out", str(tmp_path), "--fail", "--json"])
    assert code == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["passed"] is True
    assert data["files"] == []
    assert data["folders"] == []
    assert data["packages"] == []

    code_text = main(["cycles", "--out", str(tmp_path), "--fail"])
    assert code_text == 0
    out_text = capsys.readouterr().out
    assert "file-import SCCs: 0 (0 memberships)" in out_text


def test_cycles_fail_json_violation_detected(tmp_path, capsys):
    conn = _model(tmp_path)
    conn.execute("UPDATE nodes SET attrs = json_set(coalesce(attrs, '{}'), '$.role', 'code') WHERE kind = 'file'")
    _edge(conn, FILE_LEFT, FILE_RIGHT, "imports")
    _edge(conn, FILE_RIGHT, FILE_LEFT, "imports")
    conn.commit()
    conn.close()

    # With --fail: exits 1 with passed: false
    code = main(["cycles", "--out", str(tmp_path), "--fail", "--json"])
    assert code == 1
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["passed"] is False
    assert len(data["files"]) == 1
    assert data["files"][0]["detail"] == "left.ts → right.ts → left.ts"

    # Standard cbi cycles without --fail: returns 0 for backwards compatibility
    code_compat = main(["cycles", "--out", str(tmp_path), "--json"])
    assert code_compat == 0
    data_compat = json.loads(capsys.readouterr().out)
    assert data_compat["passed"] is False
    assert len(data_compat["files"]) == 1

    # Text mode with --fail exits 1
    code_text_fail = main(["cycles", "--out", str(tmp_path), "--fail"])
    assert code_text_fail == 1
    out_text = capsys.readouterr().out
    assert "file-import SCCs: 1 (2 memberships)" in out_text

    # Text mode without --fail exits 0
    code_text_compat = main(["cycles", "--out", str(tmp_path)])
    assert code_text_compat == 0
    out_compat = capsys.readouterr().out
    assert "file-import SCCs: 1 (2 memberships)" in out_compat


def test_orphans_fail_json_clean_codebase(tmp_path, capsys):
    conn = _model(tmp_path)
    conn.execute("UPDATE nodes SET attrs = json_set(coalesce(attrs, '{}'), '$.role', 'code') WHERE kind = 'file'")
    _edge(conn, FILE_LEFT, FILE_RIGHT, "imports")
    _node(conn, id=f"{WS}:app", kind="deployable", display_kind="deployable", name="app",
          attrs={"entry_points": ["call.ts"]})
    conn.commit()
    conn.close()

    code = main(["orphans", "--out", str(tmp_path), "--fail", "--json"])
    assert code == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["passed"] is True
    assert data["unreferenced"] == []

    code_text = main(["orphans", "--out", str(tmp_path), "--fail"])
    assert code_text == 0
    out_text = capsys.readouterr().out
    assert "production code with no production importer or caller:\n  none" in out_text


def test_orphans_fail_json_violation_detected(tmp_path, capsys):
    conn = _model(tmp_path)
    conn.execute("UPDATE nodes SET attrs = json_set(coalesce(attrs, '{}'), '$.role', 'code') WHERE kind = 'file'")
    conn.commit()
    conn.close()

    # With --fail: exits 1 with passed: false
    code = main(["orphans", "--out", str(tmp_path), "--fail", "--json"])
    assert code == 1
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["passed"] is False
    assert len(data["unreferenced"]) > 0

    # Standard cbi orphans without --fail: returns 0 for backwards compatibility
    code_compat = main(["orphans", "--out", str(tmp_path), "--json"])
    assert code_compat == 0
    data_compat = json.loads(capsys.readouterr().out)
    assert data_compat["passed"] is False
    assert len(data_compat["unreferenced"]) > 0

    # Text mode with --fail exits 1
    code_text_fail = main(["orphans", "--out", str(tmp_path), "--fail"])
    assert code_text_fail == 1
    out_text = capsys.readouterr().out
    assert "production code with no production importer or caller:" in out_text

    # Text mode without --fail exits 0
    code_text_compat = main(["orphans", "--out", str(tmp_path)])
    assert code_text_compat == 0
    out_compat = capsys.readouterr().out
    assert "production code with no production importer or caller:" in out_compat


def test_deps_forbid_folder_child_internal_imports_not_flagged(tmp_path, capsys):
    conn = _folder_model(tmp_path)
    conn.close()

    # Clean case: internal child import (src/cbi/parse/__init__.py -> src/cbi/parse/csharp.py)
    # must not be classified as an import to the parent folder src/cbi.
    code = main(["deps", "--out", str(tmp_path), "--level", "folder", "--forbid", "src/cbi/parse:src/cbi", "--json"])
    assert code == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["level"] == "folder"
    assert data["passed"] is True
    assert len(data["rules"]) == 1
    assert data["rules"][0]["spec"] == "src/cbi/parse:src/cbi"
    assert data["rules"][0]["passed"] is True
    assert data["rules"][0]["violations"] == []

    # Text output reports 0 violations and exits 0
    code_text = main(["deps", "--out", str(tmp_path), "--level", "folder", "--forbid", "src/cbi/parse:src/cbi"])
    assert code_text == 0
    out_text = capsys.readouterr().out
    assert "no production imports from src/cbi/parse to src/cbi" in out_text


def test_deps_forbid_folder_true_violation_detected(tmp_path, capsys):
    conn = _folder_model(tmp_path)
    # Add a true cross-folder import: file in child folder imports file in parent folder
    _edge(conn, FILE_CSHARP, FILE_GRAPH, "imports")
    conn.commit()
    conn.close()

    # JSON output reports passed: false with the offending edge
    code = main(["deps", "--out", str(tmp_path), "--level", "folder", "--forbid", "src/cbi/parse:src/cbi", "--json"])
    assert code == 1
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["level"] == "folder"
    assert data["passed"] is False
    assert len(data["rules"]) == 1
    assert data["rules"][0]["spec"] == "src/cbi/parse:src/cbi"
    assert data["rules"][0]["passed"] is False
    assert data["rules"][0]["violations"] == [{"from": "src/cbi/parse/csharp.py", "to": "src/cbi/graph.py"}]

    # Text mode exits 1 and reports offending edge
    code_text = main(["deps", "--out", str(tmp_path), "--level", "folder", "--forbid", "src/cbi/parse:src/cbi"])
    assert code_text == 1
    out_text = capsys.readouterr().out
    assert "src/cbi/parse/csharp.py → src/cbi/graph.py" in out_text


def test_deps_forbid_folder_clean_codebase_repo(capsys):
    if not Path(".cbi/model.db").is_file():
        pytest.skip(".cbi/model.db not present")
    code = main(["deps", "--level", "folder", "--forbid", "src/cbi/parse:src/cbi", "--json"])
    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["passed"] is True
    assert data["rules"][0]["passed"] is True
    assert data["rules"][0]["violations"] == []

    code_text = main(["deps", "--level", "folder", "--forbid", "src/cbi/parse:src/cbi"])
    assert code_text == 0
    out_text = capsys.readouterr().out
    assert "no production imports from src/cbi/parse to src/cbi" in out_text





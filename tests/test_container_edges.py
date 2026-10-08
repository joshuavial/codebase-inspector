"""Relationships that end on a container are drawn beside it, matching the drawer."""

import json
import subprocess

from cbi import build, store

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

# Playwright is not a project dependency. The checker runs under uvx, same as scripts/smoke_viewer.py.
_CHECK = r"""
import json, sys
from pathlib import Path
from playwright.sync_api import sync_playwright

index, focus = sys.argv[1:]
url = Path(index).resolve().as_uri() + "#c=" + focus
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
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


def test_container_relationships_match_the_drawer(tmp_path):
    index = build.build(_model(tmp_path), tmp_path / "viewer")
    script = tmp_path / "check_view.py"
    script.write_text(_CHECK)
    proc = subprocess.run(
        ["uvx", "--from", "playwright", "python", str(script), str(index), BOX],
        capture_output=True, text=True, timeout=180,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
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

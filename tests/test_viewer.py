"""Concept viewer payload: relationship rollups, leaf symbols, and the no-concept fallback."""

import json

from cbi import build, store

WS = "local:repo"
APP = f"{WS}:concept:app"
API = f"{WS}:concept:api"
CORE = f"{WS}:concept:core"
UI = f"{WS}:concept:ui"
KEYCHAIN = f"{WS}:external:keychain"
OS = f"{WS}:external:os"
REDIS = f"{WS}:external:redis"
FILE_A = f"{WS}:a.ts"
FILE_B = f"{WS}:b.ts"
FILE_UI = f"{WS}:ui.tsx"
FILE_TEST = f"{WS}:a.test.ts"
FN = f"{FILE_A}#verify"
CLS = f"{FILE_B}#Store"
METHOD = f"{CLS}.load"
BOARD = f"{FILE_UI}#Board"
ENV = f"{WS}:env:API_TOKEN"
MOD_ENV = f"{WS}:env:LOG_LEVEL"
CASE = f"{FILE_TEST}#checks token"
METHOD_CASE = f"{FILE_TEST}#checks load"
NOISE = f"{FILE_TEST}#guess"


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


def _edge(conn, src, dst, kind, source="fixture", confidence=1, weight=1, attrs=None):
    conn.execute(
        "INSERT INTO edges (src, dst, kind, source, confidence, weight, attrs) VALUES (?,?,?,?,?,?,?)",
        (src, dst, kind, source, confidence, weight, json.dumps(attrs) if attrs else None),
    )


def concept_model(tmp_path):
    conn = store.open_db(tmp_path / "model.db")
    _node(conn, id=WS, kind="workspace", display_kind="workspace", name="fixture",
          summary='map </script> ok', parent_id=None, workspace_id=None)
    _node(conn, id=APP, parent_id=WS, kind="concept", display_kind="App or process", name="App",
          summary="The process.", attrs={"role": "app", "order": 1})
    _node(conn, id=API, parent_id=APP, kind="concept", display_kind="service", name="API",
          summary="Serves tokens.", attrs={"order": 0})
    _node(conn, id=CORE, parent_id=APP, kind="concept", display_kind="core logic", name="Store",
          summary="Holds devices.", attrs={"order": 1})
    _node(conn, id=UI, parent_id=WS, kind="concept", display_kind="interface", name="UI",
          summary="The window.", attrs={"order": 0})
    _node(conn, id=KEYCHAIN, parent_id=WS, kind="external", display_kind="Platform service", name="Keychain",
          summary="Secrets.", attrs={"kind": "platform"})
    _node(conn, id=OS, parent_id=WS, kind="external", display_kind="Terminal or OS", name="OS",
          summary="The machine.", attrs={"kind": "os"})
    _node(conn, id=REDIS, parent_id=WS, kind="external", display_kind="service", name="redis", summary="Image only.")
    _node(conn, id=FILE_A, parent_id=WS, kind="file", display_kind="source file", name="a.ts", path="a.ts")
    _node(conn, id=FILE_B, parent_id=WS, kind="file", display_kind="source file", name="b.ts", path="b.ts")
    _node(conn, id=FILE_UI, parent_id=WS, kind="file", display_kind="source file", name="ui.tsx", path="ui.tsx")
    _node(conn, id=FILE_TEST, parent_id=WS, kind="file", display_kind="test file", name="a.test.ts", path="a.test.ts")
    _node(conn, id=FN, parent_id=FILE_A, kind="symbol", display_kind="function", name="verify", path="a.ts",
          start_line=1, end_line=4, signature="function verify()")
    _node(conn, id=CLS, parent_id=FILE_B, kind="symbol", display_kind="class", name="Store", path="b.ts",
          start_line=1, end_line=20, signature="class Store")
    _node(conn, id=METHOD, parent_id=CLS, kind="symbol", display_kind="method", name="load", path="b.ts",
          start_line=4, end_line=8, signature="load()")
    _node(conn, id=BOARD, parent_id=FILE_UI, kind="symbol", display_kind="component", name="Board", path="ui.tsx",
          start_line=3, end_line=30, signature="function Board({ title, count = 1, children })",
          attrs={"reads": ["snapshot.tasks"]})
    _node(conn, id=CASE, parent_id=FILE_TEST, kind="test", display_kind="test case", name="checks token", path="a.test.ts")
    _node(conn, id=METHOD_CASE, parent_id=FILE_TEST, kind="test", display_kind="test case", name="checks load", path="a.test.ts")
    _node(conn, id=NOISE, parent_id=FILE_TEST, kind="test", display_kind="test case", name="guess", path="a.test.ts")
    _node(conn, id=ENV, parent_id=WS, kind="env", display_kind="env var", name="API_TOKEN",
          attrs={"declared_in": [".env.example", "compose"]})
    _node(conn, id=MOD_ENV, parent_id=WS, kind="env", display_kind="env var", name="LOG_LEVEL")
    _node(conn, id=f"{WS}:screen:board", parent_id=UI, kind="screen", display_kind="screen", name="Board",
          attrs={"device": "phone", "root": {"layout": "column", "component": "ui.tsx#Board", "text": "Hi {name}",
                                              "children": [{"layout": "row", "component": BOARD, "text": "rows"}]}})
    for src, dst in ((API, FILE_A), (API, FILE_TEST), (CORE, FILE_B), (UI, FILE_UI)):
        _edge(conn, src, dst, "owns")
    _edge(conn, FN, CLS, "calls", weight=2)
    _edge(conn, BOARD, FN, "calls", attrs={"via": "jsx"})
    _edge(conn, FILE_A, FILE_B, "imports")
    _edge(conn, FILE_TEST, FILE_A, "imports")  # test imports stay out of the rollup
    _edge(conn, CASE, FN, "tests")
    _edge(conn, METHOD_CASE, METHOD, "tests")
    _edge(conn, NOISE, FN, "tests", confidence=0.4)
    _edge(conn, FN, ENV, "reads_env", attrs={"default": "dev"})
    _edge(conn, FILE_A, MOD_ENV, "reads_env", attrs={"default": "info"})
    _edge(conn, API, CORE, "relates", attrs={"label": "reads", "basis": "imports"})
    _edge(conn, APP, CORE, "relates", attrs={"label": "uses"})
    _edge(conn, UI, CORE, "relates", attrs={"label": "no"})
    _edge(conn, API, KEYCHAIN, "relates", attrs={"label": "verifies tokens with", "mechanism": "security CLI",
                                                "at": "a.ts:verify", "integration": True})
    conn.executemany("INSERT INTO coverage_lines (file_id, line, hits, artifact) VALUES (?, ?, ?, ?)", [
        (FILE_A, 1, 1, "a.lcov"), (FILE_A, 2, 0, "a.lcov"), (FILE_A, 3, 2, "a.lcov"), (FILE_A, 9, 1, "a.lcov")])
    conn.execute("INSERT INTO results (test_node_id, status, duration_ms, artifact) VALUES (?, 'passed', 1, 'r.xml')", (CASE,))
    conn.commit()
    return conn


def _rel(payload, src, dst):
    return next(r for r in payload["relationships"] if r["from"] == src and r["to"] == dst)


def _leaf(payload, cid):
    found = []

    def walk(nodes):
        for node in nodes:
            found.append(node)
            walk(node.get("children") or [])

    walk(payload["concepts"])
    return next(node for node in found if node["id"] == cid)


def test_rollups_follow_leaves_and_ancestors(tmp_path):
    payload = build.concept_view(concept_model(tmp_path))
    direct = _rel(payload, API, CORE)
    assert direct["backing"] == "calls" and "evidence" not in direct
    assert {(c["kind"], c["src_name"], c["dst_name"], c["weight"], c.get("via")) for c in direct["code"]} == {
        ("calls", "verify", "Store", 2, None),
        ("imports", "a.ts", "b.ts", 1, None),
    }
    ancestor = _rel(payload, APP, CORE)
    assert {(c["kind"], c["src"], c["dst"]) for c in ancestor["code"]} == {
        ("calls", FN, CLS), ("imports", FILE_A, FILE_B),
    }
    stated = _rel(payload, UI, CORE)
    assert stated["backing"] == "stated" and "code" not in stated and "evidence" not in stated
    render = _rel(payload, UI, API) if any(r["from"] == UI and r["to"] == API for r in payload["relationships"]) else None
    assert render is None  # the jsx call is not a relates edge; it shows on the leaf
    ui = _leaf(payload, UI)
    assert [BOARD, FN, "renders"] in ui["calls"]
    assert ui["ghosts"][FN]["concept"] == API


def test_leaf_symbols_env_screen_and_externals(tmp_path):
    payload = build.concept_view(concept_model(tmp_path))
    assert [c["id"] for c in payload["concepts"]] == [UI, APP]
    assert [c["id"] for c in payload["concepts"][1]["children"]] == [API, CORE]
    assert payload["summary"] == "map </script> ok"
    api = _leaf(payload, API)
    verify = next(s for s in api["symbols"] if s["id"] == FN)
    assert verify["tests"] == ["checks token"] and verify["result"] == "pass" and verify["cov"] == 66.7
    assert verify["env"] == ["API_TOKEN"]
    assert api["tests"] == [{"file": "a.test.ts", "cases": 3}]
    assert api["files"] == ["a.ts"]
    assert api["importsOut"] == [{"concept": CORE, "files": ["b.ts"]}]
    assert api["importsIn"] == [] and api["reexports"] == []
    assert _leaf(payload, CORE)["importsIn"] == [{"concept": API, "files": ["b.ts"]}]
    env = {e["name"]: e for e in api["env"]}
    assert env["API_TOKEN"] == {"name": "API_TOKEN", "symbols": [FN], "default": "dev",
                                "declared": ".env.example, compose"}
    assert env["LOG_LEVEL"]["symbols"] == [] and env["LOG_LEVEL"]["default"] == "info"
    store_sym = next(s for s in _leaf(payload, CORE)["symbols"] if s["id"] == CLS)
    assert store_sym["tests"] == ["checks load"]
    board = next(s for s in _leaf(payload, UI)["symbols"] if s["id"] == BOARD)
    assert board["props"] == ["title", "count"] and board["reads"] == ["snapshot.tasks"]
    screen = payload["screens"][0]
    assert screen["device"] == "phone" and screen["root"]["component"] == BOARD
    assert screen["root"]["children"][0]["component"] == BOARD
    assert {e["id"]: e["kind"] for e in payload["externals"]} == {KEYCHAIN: "platform", OS: "terminal"}
    point = _rel(payload, API, KEYCHAIN)
    assert point["via"] == "security CLI" and point["at"] == "a.ts:verify" and "code" not in point


def test_concepts_replace_the_fallback(tmp_path):
    conn = concept_model(tmp_path)
    disk = f"{WS}:external:disk"
    _node(conn, id=f"{WS}:deployable:web", parent_id=WS, kind="deployable", display_kind="web app", name="web")
    _node(conn, id=disk, parent_id=WS, kind="external", display_kind="storage", name="Disk",
          summary="The database.", attrs={"kind": "storage"})
    _edge(conn, API, disk, "relates", attrs={"label": "stores in", "via": "SQL", "at": "a.ts:verify", "minor": True})
    conn.commit()
    payload = build.concept_view(conn)
    assert [c["name"] for c in payload["concepts"]] == ["UI", "App"]
    assert all(c["name"] != "web" for c in payload["concepts"])
    assert {e["id"]: e["kind"] for e in payload["externals"]}[disk] == "storage"
    stored = _rel(payload, API, disk)
    assert stored["via"] == "SQL" and stored["at"] == "a.ts:verify" and stored["minor"] is True


def test_stated_backing_reads_type_only_and_injection(tmp_path):
    conn = concept_model(tmp_path)
    log = f"{WS}:concept:log"
    audit = f"{WS}:audit.ts"
    append = f"{audit}#append"
    _node(conn, id=log, parent_id=APP, kind="concept", display_kind="service", name="Audit",
          summary="The log.", attrs={"order": 2})
    _node(conn, id=audit, parent_id=WS, kind="file", display_kind="source file", name="audit.ts", path="audit.ts")
    _node(conn, id=append, parent_id=audit, kind="symbol", display_kind="method", name="append", path="audit.ts",
          start_line=4, end_line=6, signature="append()")
    _edge(conn, log, audit, "owns")
    _edge(conn, API, log, "relates", attrs={"label": "records to"})
    _edge(conn, FILE_A, audit, "imports", attrs={"type_only": True, "names": ["AuditRecord"], "line": 2})
    _edge(conn, FILE_TEST, audit, "imports", attrs={"type_only": True, "names": ["SkipMe"], "line": 9})
    _edge(conn, FN, append, "calls", attrs={"via": "injection", "field": "audit", "type": "AuditWriter", "method": "append", "line": 3})
    _edge(conn, UI, log, "relates", attrs={"label": "reads"})
    _edge(conn, FILE_UI, audit, "imports")
    _edge(conn, CORE, log, "relates", attrs={"label": "mentions"})
    _edge(conn, METHOD, append, "calls", attrs={"via": "injection"})
    conn.commit()
    payload = build.concept_view(conn)
    stated = _rel(payload, API, log)
    assert stated["backing"] == "stated" and "code" not in stated
    assert stated["evidence"] == [
        {"kind": "type import", "names": ["AuditRecord"], "file": "a.ts", "line": 2, "symbol": None},
        {"kind": "injected", "field": "audit", "type": "AuditWriter", "method": "append",
         "file": "a.ts", "line": 3, "symbol": FN},
    ]
    assert [row[1] for row in _leaf(payload, API)["calls"] if row[1] == append] == []
    assert all(item["concept"] != log for item in _leaf(payload, API)["importsOut"])
    assert _rel(payload, UI, log)["backing"] == "imports" and "evidence" not in _rel(payload, UI, log)
    bare = _rel(payload, CORE, log)
    assert bare["backing"] == "stated" and "code" not in bare
    assert bare["evidence"] == [
        {"kind": "injected", "method": "append", "file": "b.ts", "line": 4, "symbol": CLS},
    ]


def test_entry_marker_reads_stored_attrs_and_hosts_is_a_layout_edge(tmp_path):
    conn = concept_model(tmp_path)
    conn.execute("UPDATE nodes SET attrs = ? WHERE id = ?", (
        json.dumps({"entry": True, "entry_file": "a.ts", "order": 0}), API))
    conn.execute("UPDATE nodes SET attrs = ? WHERE id = ?", (
        json.dumps({"role": "app", "entry": True, "order": 1}), APP))
    conn.execute("UPDATE nodes SET attrs = ? WHERE id = ?", (
        json.dumps({"entry": False, "entry_file": "ui.tsx", "order": 0}), UI))
    _edge(conn, FN, BOARD, "calls")
    _edge(conn, APP, UI, "relates", attrs={"label": "opens the window for", "kind": "hosts"})
    conn.commit()
    payload = build.concept_view(conn)
    api = _leaf(payload, API)
    app = next(c for c in payload["concepts"] if c["id"] == APP)
    assert api["entry"] is True and api["entry_file"] == "a.ts" and api["entryFiles"] == ["a.ts"]
    assert app["entry"] is True and "entryFiles" not in app
    ui = _leaf(payload, UI)
    assert "entry" not in ui and ui["entry_file"] == "ui.tsx" and ui["entryFiles"] == ["ui.tsx"]
    assert "entry" not in _leaf(payload, CORE)
    hosts = _rel(payload, APP, UI)
    assert hosts["kind"] == "hosts" and hosts["backing"] == "hosts"
    assert "code" not in hosts and "evidence" not in hosts
    assert "kind" not in _rel(payload, API, CORE)


def test_reexport_bridge_reads_source(tmp_path):
    conn = concept_model(tmp_path)
    (tmp_path / "a.ts").write_text('export { Store as DeviceStore } from "./b";\nexport type { X } from "./b";\n')
    payload = build.concept_view(conn, tmp_path)
    api = _leaf(payload, API)
    assert api["reexports"] == [{"name": "DeviceStore", "concept": CORE, "def": CLS}]
    assert api["ghosts"][CLS]["concept"] == CORE


def test_fallback_is_deployables_packages_and_externals(tmp_path):
    conn = store.open_db(tmp_path / "model.db")
    _node(conn, id=WS, kind="workspace", display_kind="workspace", name="plain", summary="No concepts yet.",
          parent_id=None, workspace_id=None)
    _node(conn, id=f"{WS}:deployable:web", parent_id=WS, kind="deployable", display_kind="web app", name="web",
          summary="The site.")
    _node(conn, id=f"{WS}:deployable:desktop", parent_id=WS, kind="deployable", display_kind="electron app",
          name="desktop", summary="The shell.")
    _node(conn, id=f"{WS}:package:lib", parent_id=WS, kind="package", display_kind="package", name="lib")
    _node(conn, id=f"{WS}:external:redis", parent_id=WS, kind="external", display_kind="service", name="redis")
    _node(conn, id=f"{WS}:service:postgres", parent_id=WS, kind="external", display_kind="service", name="postgres",
          attrs={"image": "postgres:16"})
    _node(conn, id=f"{WS}:src/", parent_id=WS, kind="group", display_kind="folder", name="src", path="src")
    _node(conn, id=f"{WS}:src/components/", parent_id=f"{WS}:src/", kind="group", display_kind="folder",
          name="components", path="src/components")
    _node(conn, id=f"{WS}:src/app.ts", parent_id=f"{WS}:src/", kind="file", display_kind="source file",
          name="app.ts", path="src/app.ts")
    _node(conn, id=f"{WS}:src/components/button.ts", parent_id=f"{WS}:src/components/", kind="file",
          display_kind="source file", name="button.ts", path="src/components/button.ts")
    _node(conn, id=f"{WS}:web.ts", parent_id=WS, kind="file", display_kind="source file", name="web.ts", path="web.ts")
    _node(conn, id=f"{WS}:web.ts#serve", parent_id=f"{WS}:web.ts", kind="symbol", display_kind="function",
          name="serve", path="web.ts")
    _node(conn, id=f"{WS}:env:PORT", parent_id=WS, kind="env", display_kind="env var", name="PORT",
          attrs={"declared_in": [".env.example"]})
    _edge(conn, f"{WS}:web.ts", f"{WS}:deployable:web", "part_of")
    _edge(conn, f"{WS}:src/app.ts", f"{WS}:deployable:desktop", "part_of")
    _edge(conn, f"{WS}:src/components/button.ts", f"{WS}:deployable:desktop", "part_of")
    _edge(conn, f"{WS}:src/components/button.ts", f"{WS}:package:lib", "part_of")
    _edge(conn, f"{WS}:web.ts#serve", f"{WS}:env:PORT", "reads_env", attrs={"default": "3000"})
    _edge(conn, f"{WS}:deployable:web", f"{WS}:package:lib", "depends_on")
    _edge(conn, f"{WS}:package:lib", f"{WS}:external:redis", "depends_on")
    conn.commit()
    payload = build.concept_view(conn)
    assert [c["id"] for c in payload["concepts"]] == [
        f"{WS}:deployable:desktop", f"{WS}:deployable:web", f"{WS}:package:lib",
    ]
    desktop = payload["concepts"][0]
    assert desktop["role"] == "app" and "flat" not in desktop
    src = desktop["children"][0]
    assert src["name"] == "src" and src["summary"] == "2 files" and src["files"] == ["src/app.ts"]
    assert src["children"][0]["name"] == "components" and src["children"][0]["flat"] is True
    assert src["children"][0]["files"] == ["src/components/button.ts"]
    assert src["id"] == f"{WS}:deployable:desktop#{WS}:src/"
    lib = payload["concepts"][2]
    assert lib["role"] == "core" and lib["summary"] == "package"
    assert lib["children"][0]["children"][0]["files"] == ["src/components/button.ts"]
    assert payload["concepts"][1]["role"] == "ui" and payload["concepts"][1]["flat"] is True
    assert payload["concepts"][1]["files"] == ["web.ts"]
    assert payload["externals"] == [
        {"id": f"{WS}:service:postgres", "name": "postgres", "summary": "", "kind": "service"},
        {"id": f"{WS}:external:redis", "name": "redis", "summary": "", "kind": "service"},
    ]
    assert [(r["from"], r["to"], r["label"]) for r in payload["relationships"]] == [
        (f"{WS}:deployable:desktop", f"{WS}:package:lib", "includes"),
        (f"{WS}:deployable:web", f"{WS}:package:lib", "depends on"),
        (f"{WS}:package:lib", f"{WS}:external:redis", "depends on"),
    ]
    assert payload["relationships"][0]["basis"] == "part_of"
    assert payload["screens"] == [] and payload["workspace"] == "plain"
    web = next(c for c in payload["concepts"] if c["name"] == "web")
    assert web["env"] == [{"name": "PORT", "symbols": [f"{WS}:web.ts#serve"], "default": "3000",
                            "declared": ".env.example"}]
    assert next(c for c in payload["concepts"] if c["name"] == "lib")["env"] == []


def test_build_writes_both_data_files(tmp_path):
    conn = concept_model(tmp_path)
    viewer = build.build(conn, tmp_path / "viewer")
    text = (viewer.parent / "data" / "concepts.js").read_text()
    assert text.startswith('cbiLoad("concepts", ') and "</script>" not in text and "\\u003c/script>" in text
    tree = (viewer.parent / "data" / "tree.js").read_text()
    assert tree.startswith('cbiLoad("tree", ') and FN in tree
    html = viewer.read_text()
    assert html.index("app.js") < html.index("data/diff.js") < html.index("data/concepts.js") < html.index("data/context.js")
    assert "data/tree.js" not in html
    assert (viewer.parent / "data" / "diff.js").read_text() == 'cbiLoad("diff", null);\n'
    app = (viewer.parent / "app.js").read_text(encoding="utf-8")
    assert "innerHTML" not in app
    assert "function loadTreeAfterPaint" in app and 's.src = "data/tree.js"' in app
    assert "window.cbiOnDiagram" in app and "window.cbiRender" in app
    assert "zoomInto" not in app
    assert 'display_kind === "test case"' in app and 'display_kind === "doc"' in app
    assert 'display_kind === "folder"' in app
    assert (viewer.parent / "vendor" / "elk.bundled.js").stat().st_size > 1_000_000

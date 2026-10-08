"""data/diff.js: the change list, removed concepts, and changed function source."""

import json
from pathlib import Path

from cbi import build, diff, store
from cbi.cli import main

WS = "local:repo"
APP = "app"
UI = "ui"
LEGACY = "legacy"
BILLING = "billing"
STRIPE = "stripe"
FILE_APP = f"{WS}:src/app.py"
FILE_UI = f"{WS}:src/ui.tsx"
FILE_OLD = f"{WS}:src/old.py"
FILE_BILL = f"{WS}:src/billing.py"
FILE_STORE = f"{WS}:src/store.py"
RUN = f"{FILE_APP}#run"
BOARD = f"{FILE_UI}#Board"
OLD = f"{FILE_OLD}#legacy"
CHARGE = f"{FILE_BILL}#charge"
STORE = f"{FILE_STORE}#Store"
LOAD = f"{STORE}.load"
SCREEN = "screen:home"


def _node(conn, **kw):
    attrs = kw.get("attrs")
    conn.execute(
        "INSERT INTO nodes (id, parent_id, kind, display_kind, name, workspace_id, path, "
        "start_line, end_line, signature, summary, content_hash, attrs) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (kw["id"], kw.get("parent_id"), kw["kind"], kw["display_kind"], kw["name"], kw.get("workspace_id", WS),
         kw.get("path"), kw.get("start_line"), kw.get("end_line"), kw.get("signature"), kw.get("summary"),
         kw.get("content_hash"), json.dumps(attrs) if attrs is not None else None),
    )


def _edge(conn, src, dst, kind, attrs=None):
    conn.execute(
        "INSERT INTO edges (src, dst, kind, source, confidence, weight, attrs) VALUES (?,?,?,?,?,?,?)",
        (src, dst, kind, "fixture", 1, 1, json.dumps(attrs) if attrs else None),
    )


def _common(conn, run_hash, board_hash, load_hash, ui_attrs):
    _node(conn, id=WS, kind="workspace", display_kind="workspace", name="fixture", summary="map", parent_id=None, workspace_id=None)
    _node(conn, id=APP, parent_id=WS, kind="concept", display_kind="App or process", name="App", summary="The process.", attrs={"role": "app"})
    _node(conn, id=UI, parent_id=WS, kind="concept", display_kind="interface", name="UI", summary="The window.", attrs=ui_attrs)
    _node(conn, id=FILE_APP, parent_id=WS, kind="file", display_kind="source file", name="app.py", path="src/app.py")
    _node(conn, id=FILE_UI, parent_id=WS, kind="file", display_kind="source file", name="ui.tsx", path="src/ui.tsx")
    _node(conn, id=FILE_STORE, parent_id=WS, kind="file", display_kind="source file", name="store.py", path="src/store.py")
    _node(conn, id=RUN, parent_id=FILE_APP, kind="symbol", display_kind="function", name="run", path="src/app.py",
          start_line=1, end_line=2, signature="def run()", content_hash=run_hash)
    _node(conn, id=BOARD, parent_id=FILE_UI, kind="symbol", display_kind="component", name="Board", path="src/ui.tsx",
          start_line=1, end_line=3, signature="function Board()", content_hash=board_hash)
    _node(conn, id=STORE, parent_id=FILE_STORE, kind="symbol", display_kind="class", name="Store", path="src/store.py",
          start_line=1, end_line=3, signature="class Store", content_hash="class")
    _node(conn, id=LOAD, parent_id=STORE, kind="symbol", display_kind="method", name="load", path="src/store.py",
          start_line=2, end_line=3, signature="def load(self)", content_hash=load_hash)
    _node(conn, id=SCREEN, parent_id=UI, kind="screen", display_kind="screen", name="Home",
          attrs={"device": "phone", "root": {"layout": "column", "component": BOARD, "text": "Hi" if run_hash == "run-base" else "Hello"}})
    _edge(conn, APP, FILE_APP, "owns")
    _edge(conn, UI, FILE_UI, "owns")
    _edge(conn, APP, FILE_STORE, "owns")


def _models(tmp_path):
    base_root, head_root = tmp_path / "base", tmp_path / "head"
    for root, body in ((base_root, "return 1"), (head_root, "return 1 < 2")):
        (root / "src").mkdir(parents=True)
        (root / "src" / "app.py").write_text(f"def run():\n    {body}\n")
        (root / "src" / "store.py").write_text("class Store:\n    def load(self):\n        return 1\n")
        (root / "src" / "ui.tsx").write_text("export function Board() {\n  return <div>Hi</div>;\n}\n")
    (head_root / "src" / "store.py").write_text("class Store:\n    def load(self):\n        return 2\n")
    (head_root / "src" / "ui.tsx").write_text("export function Board() {\n  return <div>Hello</div>;\n}\n")
    base, head = store.open_db(tmp_path / "base.db"), store.open_db(tmp_path / "head.db")
    _common(base, "run-base", "board-base", "load-base", {"role": "ui"})
    _common(head, "run-head", "board-head", "load-head", {"role": "ui", "provisional": True})
    _node(base, id=LEGACY, parent_id=WS, kind="concept", display_kind="core logic", name="Legacy", summary="Going away.", attrs={"role": "core"})
    _node(base, id=FILE_OLD, parent_id=WS, kind="file", display_kind="source file", name="old.py", path="src/old.py")
    _node(base, id=OLD, parent_id=FILE_OLD, kind="symbol", display_kind="function", name="legacy", path="src/old.py",
          start_line=1, end_line=2, signature="def legacy()", content_hash="old")
    _edge(base, LEGACY, FILE_OLD, "owns")
    _edge(base, APP, LEGACY, "relates", attrs={"label": "calls"})
    _node(head, id=BILLING, parent_id=WS, kind="concept", display_kind="service", name="Billing", summary="Takes payment.", attrs={"role": "service"})
    _node(head, id=STRIPE, parent_id=WS, kind="external", display_kind="SaaS or API", name="Stripe", summary="Cards.", attrs={"kind": "saas"})
    _node(head, id=FILE_BILL, parent_id=WS, kind="file", display_kind="source file", name="billing.py", path="src/billing.py")
    _node(head, id=CHARGE, parent_id=FILE_BILL, kind="symbol", display_kind="function", name="charge", path="src/billing.py",
          start_line=1, end_line=2, signature="def charge()", content_hash="charge")
    _edge(head, BILLING, FILE_BILL, "owns")
    _edge(head, BILLING, STRIPE, "relates", attrs={"label": "charges", "mechanism": "HTTP", "at": "src/billing.py:charge", "integration": True})
    base.commit()
    head.commit()
    return base, head, base_root, head_root


def _payload(text):
    prefix = 'cbiLoad("diff", '
    assert text.startswith(prefix) and text.endswith(");\n") and "<" not in text
    return json.loads(text[len(prefix):-3])


def test_compare_build_writes_diff_js(tmp_path):
    base, head, base_root, head_root = _models(tmp_path)
    changes = diff.compare(base, head)
    viewer = build.build(head, tmp_path / "viewer", head_root, compare={
        "base": base, "base_root": base_root, "changes": changes, "base_label": "aaa", "head_label": "bbb",
    })
    payload = _payload((viewer.parent / "data" / "diff.js").read_text())
    assert payload["base"] == "aaa" and payload["head"] == "bbb"
    kinds = {change["kind"] for group in payload["changes"]["groups"] for change in group["changes"]}
    assert {"concept-added", "concept-removed", "symbol-changed", "integration-added"} <= kinds
    removed = {node["id"] for node in payload["removed"]["concepts"]}
    assert LEGACY in removed and BILLING not in removed
    assert any(rel["from"] == APP and rel["to"] == LEGACY for rel in payload["removed"]["relationships"])
    assert payload["sources"][RUN] == {"base": "def run():\n    return 1", "head": "def run():\n    return 1 < 2"}
    assert "return 2" in payload["sources"][LOAD]["head"] and "return 1" in payload["sources"][LOAD]["base"]
    assert BOARD not in payload["sources"]
    assert payload["provisional"] == [UI]
    assert payload["screens"] and payload["screens"][0]["id"] == SCREEN
    assert payload["screens"][0]["root"]["text"] == "Hi"
    assert "\\u003c" in (viewer.parent / "data" / "diff.js").read_text()
    plain = build.build(head, tmp_path / "plain")
    assert (plain.parent / "data" / "diff.js").read_text() == 'cbiLoad("diff", null);\n'


def test_compare_flag_rejects_a_bad_range(capsys):
    assert main(["build", "--compare", "a...b"]) == 2
    assert "base..head" in capsys.readouterr().err


def test_compare_flag_rejects_ref(capsys):
    assert main(["build", "--compare", "a..b", "--ref", "HEAD"]) == 2
    assert "not both" in capsys.readouterr().err

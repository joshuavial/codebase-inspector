"""sketch-screens: gates, checks, screens.json on scan, show and rescan."""

import json
import sqlite3
import subprocess
from pathlib import Path

from cbi import build, screens
from cbi.cli import main

FILES = {
    "package.json": '{"name":"demo","main":"main.tsx"}\n',
    "README.md": "# Demo\n",
    "main.tsx": (
        'import { createRoot } from "react-dom/client";\n'
        'import { App } from "./App";\n'
        'createRoot(document.getElementById("root")!).render(<App />);\n'
    ),
    "App.tsx": (
        'import { Board } from "./Board";\n'
        'import { Badge } from "./Badge";\n'
        "export function App() { return <div><Board /><Badge /></div>; }\n"
    ),
    "Board.tsx": "export function Board() { return <section>Hello</section>; }\n",
    "Badge.tsx": "export function Badge() { return <span>new</span>; }\n",
    "twin/Badge.tsx": "export function Badge() { return <i>2</i>; }\n",
    "phone/state.ts": (
        'export type Tab = "now" | "messages";\n'
        "export const TABS: { id: Tab; label: string }[] = [\n"
        '  { id: "now", label: "Now" },\n'
        '  { id: "messages", label: "Messages" },\n'
        "];\n"
        'export type Shade = "red" | "blue";\n'
    ),
    "phone/Phone.tsx": (
        'import { useState } from "react";\n'
        'import { TABS, type Tab } from "./state";\n'
        "export function Phone() {\n"
        '  const [tab, setTab] = useState<Tab>("now");\n'
        '  const parts = ["shell", "CLI call"];\n'
        "  return <div>{parts.length}{TABS.map((item) => item.label)}{tab}</div>;\n"
        "}\n"
    ),
}

UI_FILES = ["App.tsx", "Badge.tsx", "main.tsx", "phone/Phone.tsx", "phone/state.ts", "twin/Badge.tsx"]
HINTS = ["muted", "strong", "button", "heading", "badge", "input", "chip", "bar", "banner",
         "tabs", "table", "panel", "card", "danger", "list"]


def run(capsys, *argv):
    capsys.readouterr()
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def run_json(capsys, *argv):
    code, out, err = run(capsys, *argv, "--json")
    assert code == 0, err
    return json.loads(out)


def submit(capsys, tmp_path, task_id, value):
    path = tmp_path / "answer.json"
    path.write_text(json.dumps(value))
    return run(capsys, "submit", task_id, str(path))


def task_rows(kind):
    conn = sqlite3.connect(".cbi/model.db")
    try:
        return conn.execute("SELECT id, state FROM tasks WHERE kind = ? ORDER BY id", (kind,)).fetchall()
    finally:
        conn.close()


def confirm_structure(capsys, tmp_path):
    [task] = run_json(capsys, "tasks", "--kind", "confirm-structure")
    brief = run_json(capsys, "task", task["id"])
    code, _, err = submit(capsys, tmp_path, task["id"], {
        "input_hash": brief["input_hash"], "deployables": [], "packages": [],
    })
    assert code == 0, err


def concept_answer(brief):
    return {
        "input_hash": brief["input_hash"],
        "summary": "A demo UI.",
        "concepts": [
            {"id": "ui", "name": "UI", "summary": "The interface.", "role": "ui", "files": UI_FILES},
            {"id": "core", "name": "Core", "summary": "The board.", "role": "core", "files": ["Board.tsx"]},
        ],
        "externals": [],
        "relationships": [{"from": "ui", "to": "core", "label": "renders", "basis": "imports"}],
    }


def accept_concepts(capsys, tmp_path):
    [task] = run_json(capsys, "tasks", "--kind", "define-concepts")
    brief = run_json(capsys, "task", task["id"])
    code, out, err = submit(capsys, tmp_path, task["id"], concept_answer(brief))
    assert code == 0 and "accepted" in out, err
    return brief


def screen_answer(brief):
    app = next(comp for comp in brief["components"] if comp["ref"] == "App.tsx#App")
    return {
        "input_hash": brief["input_hash"],
        "screens": [
            {
                "id": "ui", "name": "Home", "device": "desktop",
                "root": {
                    "id": "app", "layout": "column", "component": "App.tsx#App",
                    "children": [
                        {"id": "title", "layout": "row", "text": "<b>Hi {name}</b>", "style": ["heading"]},
                        {"id": "board", "layout": "column", "component": "Board.tsx#Board"},
                        {"id": "again", "layout": "row", "component": app["id"]},
                        {"id": "grid", "layout": "grid", "cols": 3, "style": HINTS, "text": "cells"},
                    ],
                },
            },
            {
                "id": "phone", "name": "Phone", "device": "phone",
                "root": {"id": "phone", "layout": "column", "component": "phone/Phone.tsx#Phone"},
            },
        ],
        "unsketched": [
            {"component": "Badge.tsx#Badge", "reason": "a chip, not its own screen"},
            {"component": "twin/Badge.tsx#Badge", "reason": "a second chip"},
        ],
    }


def sketch_brief(capsys):
    [task] = run_json(capsys, "tasks", "--kind", "sketch-screens")
    return run_json(capsys, "task", task["id"])


def repo(make_repo, monkeypatch):
    root = make_repo(FILES, name="repo")
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    return root


def test_task_gates_and_brief_inputs(make_repo, monkeypatch, capsys, tmp_path):
    repo(make_repo, monkeypatch)
    assert task_rows("sketch-screens") == []
    confirm_structure(capsys, tmp_path)
    assert task_rows("sketch-screens") == [] and run_json(capsys, "tasks", "--kind", "define-concepts")
    accept_concepts(capsys, tmp_path)
    brief = sketch_brief(capsys)
    app = next(comp for comp in brief["components"] if comp["ref"] == "App.tsx#App")
    assert "<Board" in app["jsx"] and "App(" in app["signature"]
    assert app["renders"] == ["Badge.tsx#Badge", "Board.tsx#Board"]
    assert app["rendered_by"] == ["main.tsx"] and app["concept"] == "ui" and app["concept_name"] == "UI"
    assert all(comp["ref"] != "Board.tsx#Board" for comp in brief["components"])
    assert {"component": "App.tsx#App", "from": "main.tsx",
            "reason": "rendered from a deployable entry"} in brief["entries"]
    states = {item["name"]: item for item in brief["states"]}
    assert "Shade" not in states and "parts" not in states
    assert states["Tab"]["values"] == ["now", "messages"] and states["Tab"]["path"] == "phone/state.ts"
    assert states["Tab"]["set_in"] == ["phone/Phone.tsx#Phone"]
    assert states["TABS"]["values"] == ["now", "messages"]
    assert "phone/Phone.tsx#Phone" in states["TABS"]["set_in"]
    assert [item["id"] for item in brief["concepts"]] == ["ui"]
    code, text, _ = run(capsys, "task", brief["id"])
    assert code == 0 and "every region component is a real component node" in text and "<Board" in text


def test_task_stays_closed_without_components(make_repo, monkeypatch, capsys, tmp_path):
    root = make_repo({"a.ts": "export function a() { return 1 }\n", "README.md": "# Demo\n"}, name="repo")
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    confirm_structure(capsys, tmp_path)
    [task] = run_json(capsys, "tasks", "--kind", "define-concepts")
    brief = run_json(capsys, "task", task["id"])
    answer = {"input_hash": brief["input_hash"], "summary": "A library.",
              "concepts": [{"id": "core", "name": "Core", "summary": "The function.", "role": "core",
                            "files": ["a.ts"]}],
              "externals": [], "relationships": []}
    assert submit(capsys, tmp_path, task["id"], answer)[0] == 0
    assert task_rows("sketch-screens") == []


def test_each_check_is_reported_together(make_repo, monkeypatch, capsys, tmp_path):
    repo(make_repo, monkeypatch)
    confirm_structure(capsys, tmp_path)
    accept_concepts(capsys, tmp_path)
    brief = sketch_brief(capsys)
    good = screen_answer(brief)

    bad = json.loads(json.dumps(good))
    bad["unsketched"] = []
    bad["screens"] = [bad["screens"][0]]
    bad["screens"][0]["root"]["children"].append({"id": "nope", "layout": "row", "component": "Missing"})
    bad["screens"][0]["root"]["children"].append({"id": "which", "layout": "row", "component": "Badge"})
    code, _, err = submit(capsys, tmp_path, brief["id"], bad)
    assert code == 2
    assert "$.screens[0].root.children[4].component: 'Missing' is not a component" in err
    assert "$.screens[0].root.children[5].component: 'Badge' matches more than one component" in err
    assert "$.screens: UI components not sketched or listed in unsketched: " in err
    assert "Badge.tsx#Badge" in err and "phone/Phone.tsx#Phone" in err and "twin/Badge.tsx#Badge" in err

    unknown = json.loads(json.dumps(good))
    unknown["unsketched"].append({"component": "Nope", "reason": "gone"})
    code, _, err = submit(capsys, tmp_path, brief["id"], unknown)
    assert code == 2 and "$.unsketched[2].component: 'Nope' is not a component" in err

    dup = json.loads(json.dumps(good))
    dup["screens"][1]["id"] = "ui"
    code, _, err = submit(capsys, tmp_path, brief["id"], dup)
    assert code == 2 and "$.screens[1].id: 'ui' is duplicated" in err

    blank = json.loads(json.dumps(good))
    blank["unsketched"][0]["reason"] = "  "
    code, _, err = submit(capsys, tmp_path, brief["id"], blank)
    assert code == 2 and "$.unsketched[0].reason: empty" in err

    stack = json.loads(json.dumps(good))
    stack["screens"][0]["root"]["layout"] = "stack"
    code, _, err = submit(capsys, tmp_path, brief["id"], stack)
    assert code == 2 and "not one of row, column, grid" in err

    html = json.loads(json.dumps(good))
    html["screens"][0]["root"]["html"] = "<b>x</b>"
    code, _, err = submit(capsys, tmp_path, brief["id"], html)
    assert code == 2 and "$.screens[0].root.html: unknown key" in err

    flag = json.loads(json.dumps(good))
    flag["screens"][0]["root"]["cols"] = True
    code, _, err = submit(capsys, tmp_path, brief["id"], flag)
    assert code == 2 and "$.screens[0].root.cols: expected integer, got bool" in err

    zero = json.loads(json.dumps(good))
    zero["screens"][0]["root"]["cols"] = 0
    code, _, err = submit(capsys, tmp_path, brief["id"], zero)
    assert code == 2 and "$.screens[0].root.cols: 0 is outside 1..12" in err


def test_accept_writes_screens_shows_regions_and_lists_screens(make_repo, monkeypatch, capsys, tmp_path):
    root = repo(make_repo, monkeypatch)
    confirm_structure(capsys, tmp_path)
    accept_concepts(capsys, tmp_path)
    brief = sketch_brief(capsys)
    answer = screen_answer(brief)
    code, out, err = submit(capsys, tmp_path, brief["id"], answer)
    assert code == 0 and "accepted" in out, err
    assert json.loads((root / ".cbi" / "screens.json").read_text())["screens"][0]["name"] == "Home"
    assert task_rows("sketch-screens") == [(brief["id"], "done")]

    conn = sqlite3.connect(root / ".cbi" / "model.db")
    assert conn.execute("SELECT kind FROM nodes WHERE id = 'ui'").fetchone()[0] == "concept"
    assert conn.execute("SELECT kind FROM nodes WHERE id = 'local:repo:screen:ui'").fetchone()[0] == "screen"
    conn.close()

    shown = run_json(capsys, "show", "local:repo:screen:ui")
    assert shown["kind"] == "screen" and shown["parent_id"] == "ui"
    assert shown["attrs"]["ref"] == "ui" and shown["attrs"]["device"] == "desktop"
    assert shown["attrs"]["root"]["component"] == "App.tsx#App"
    app_edge = next(edge for edge in shown["outgoing"] if edge["kind"] == "sketches" and edge["name"] == "App")
    assert app_edge["weight"] == 2
    assert any(edge["kind"] == "sketches" and edge["name"] == "Board" for edge in shown["outgoing"])

    code, text, _ = run(capsys, "show", "Home")
    assert code == 0 and "regions:" in text and "device: desktop" in text and "ref: ui" in text
    assert '"<b>Hi {name}</b>"' in text and "3 cols" in text and "[heading]" in text
    assert "sketches" not in text and "summary:" not in text

    app = run_json(capsys, "show", "App.tsx#App")
    assert app["screens"] == [{"id": "local:repo:screen:ui", "name": "Home", "device": "desktop"}]
    phone = run_json(capsys, "show", "phone/Phone.tsx#Phone")
    assert phone["screens"] == [{"id": "local:repo:screen:phone", "name": "Phone", "device": "phone"}]
    assert "Home  (desktop)" in run(capsys, "show", "App.tsx#App")[1]
    assert run_json(capsys, "show", "ui")["kind"] == "concept"
    assert any(hit["id"] == "local:repo:screen:ui" for hit in run_json(capsys, "search", "Home"))

    code, again, err = submit(capsys, tmp_path, brief["id"], answer)
    assert code == 0 and "nothing changed" in again, err


def test_rescan_reopens_only_when_a_ui_component_is_new(make_repo, monkeypatch, capsys, tmp_path):
    root = repo(make_repo, monkeypatch)
    confirm_structure(capsys, tmp_path)
    accept_concepts(capsys, tmp_path)
    brief = sketch_brief(capsys)
    answer = screen_answer(brief)
    assert submit(capsys, tmp_path, brief["id"], answer)[0] == 0
    assert "no changes" not in run(capsys, "scan")[1]
    assert "no changes" in run(capsys, "scan")[1]

    path = root / ".cbi" / "screens.json"
    document = json.loads(path.read_text())
    document["screens"][0]["name"] = "Overview"
    path.write_text(json.dumps(document, indent=2) + "\n")
    assert "no changes" not in run(capsys, "scan")[1]
    assert "Overview (screen)" in run(capsys, "show", "local:repo:screen:ui")[1]
    assert run_json(capsys, "tasks", "--kind", "sketch-screens") == []

    app = root / "App.tsx"
    app.write_text(app.read_text() + "// note\n")
    assert main(["scan"]) == 0
    assert task_rows("sketch-screens") == []
    [task] = run_json(capsys, "tasks", "--kind", "define-concepts")
    concepts = run_json(capsys, "task", task["id"])
    assert [(item["path"], item["reason"]) for item in concepts["files"]] == [("App.tsx", "changed")]
    doc = json.loads((root / ".cbi" / "concepts.json").read_text())
    doc["input_hash"] = concepts["input_hash"]
    code, out, err = submit(capsys, tmp_path, task["id"], doc)
    assert code == 0 and "accepted" in out, err
    assert task_rows("sketch-screens")[0][1] == "done"
    assert run_json(capsys, "tasks", "--kind", "sketch-screens") == []

    app.write_text(app.read_text() + "export function Extra() { return <em>e</em>; }\n")
    assert main(["scan"]) == 0
    assert task_rows("sketch-screens") == []
    [task] = run_json(capsys, "tasks", "--kind", "define-concepts")
    concepts = run_json(capsys, "task", task["id"])
    doc = json.loads((root / ".cbi" / "concepts.json").read_text())
    doc["input_hash"] = concepts["input_hash"]
    assert submit(capsys, tmp_path, task["id"], doc)[0] == 0
    [opened] = run_json(capsys, "tasks", "--kind", "sketch-screens")
    code, _, err = submit(capsys, tmp_path, opened["id"], answer)
    assert code == 2 and "stale" in err
    fresh = run_json(capsys, "task", opened["id"])
    body = json.loads((root / ".cbi" / "screens.json").read_text())
    body["input_hash"] = fresh["input_hash"]
    code, _, err = submit(capsys, tmp_path, opened["id"], body)
    assert code == 2 and "App.tsx#Extra" in err


def test_invalid_screens_json_clears_nodes(make_repo, monkeypatch, capsys, tmp_path):
    root = repo(make_repo, monkeypatch)
    confirm_structure(capsys, tmp_path)
    accept_concepts(capsys, tmp_path)
    brief = sketch_brief(capsys)
    assert submit(capsys, tmp_path, brief["id"], screen_answer(brief))[0] == 0
    path = root / ".cbi" / "screens.json"
    path.write_text("{")
    assert main(["scan"]) == 0
    assert path.read_text() == "{"
    shown = run_json(capsys, "show", "local:repo")
    assert any(item["kind"] == "screens_invalid" for item in shown["diagnostics"])
    conn = sqlite3.connect(root / ".cbi" / "model.db")
    assert conn.execute("SELECT count(*) FROM nodes WHERE kind = 'screen'").fetchone()[0] == 0
    conn.close()
    assert task_rows("sketch-screens")[0][1] == "open"


def test_deleted_file_is_restored_from_the_cache(make_repo, monkeypatch, capsys, tmp_path):
    root = repo(make_repo, monkeypatch)
    confirm_structure(capsys, tmp_path)
    accept_concepts(capsys, tmp_path)
    brief = sketch_brief(capsys)
    assert submit(capsys, tmp_path, brief["id"], screen_answer(brief))[0] == 0
    path = root / ".cbi" / "screens.json"
    text = path.read_text()
    path.unlink()
    assert main(["scan"]) == 0
    assert path.read_text() == text
    assert task_rows("sketch-screens") == [(brief["id"], "done")]
    conn = sqlite3.connect(root / ".cbi" / "model.db")
    assert conn.execute("SELECT count(*) FROM nodes WHERE kind = 'screen'").fetchone()[0] == 2
    conn.close()


def test_when_is_accepted_and_shown(make_repo, monkeypatch, capsys, tmp_path):
    root = repo(make_repo, monkeypatch)
    confirm_structure(capsys, tmp_path)
    accept_concepts(capsys, tmp_path)
    brief = sketch_brief(capsys)
    text = run(capsys, "task", brief["id"])[1]
    assert "v-if" in brief["instructions"] and "v-show" in text
    assert "flag: arrears-view" in json.dumps(brief["answer_schema"])
    answer = screen_answer(brief)
    answer["screens"][0]["root"]["children"][0]["when"] = "role: manager"
    code, out, err = submit(capsys, tmp_path, brief["id"], answer)
    assert code == 0 and "accepted" in out, err
    code, shown, err = run(capsys, "show", "Home")
    assert code == 0 and 'when "role: manager"' in shown, err

    blank = json.loads(json.dumps(answer))
    blank["screens"][0]["root"]["children"][0]["when"] = "  "
    code, _, err = submit(capsys, tmp_path, brief["id"], blank)
    assert code == 2 and "$.screens[0].root.children[0].when: empty" in err

    long = json.loads(json.dumps(answer))
    long["screens"][0]["root"]["children"][0]["when"] = "x" * 81
    code, _, err = submit(capsys, tmp_path, brief["id"], long)
    assert code == 2 and "at most 80" in err

    conn = sqlite3.connect(root / ".cbi" / "model.db")
    try:
        viewer = build.build(conn, tmp_path / "viewer", root)
    finally:
        conn.close()
    css = (viewer.parent / "style.css").read_text()
    rule = css.split(".wf.cond", 1)[1].split("}", 1)[0]
    assert "dashed" in rule and ".cond-tag" in css
    assert "role: manager" in (viewer.parent / "data" / "concepts.js").read_text()
    proc = subprocess.run(
        ["node", str(Path(__file__).parent / "sketch_check.js")],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_read_accepts_a_commit_tree():
    class Tree:
        def __truediv__(self, other):
            return self

        def read_text(self, errors=None):
            return "export function App() { return <div />; }\n"

    assert screens._read(Tree(), "App.tsx", {}) == "export function App() { return <div />; }\n"

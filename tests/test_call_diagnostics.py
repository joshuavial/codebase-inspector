"""Ambiguous calls remain actionable without inventing an edge."""

import sqlite3

from cbi.cli import main


def test_ambiguity_lists_each_location_and_candidate(make_repo, monkeypatch, capsys):
    root = make_repo({
        "src/legacy.js": "function pick(a) { return a; }\nfunction pick(a, b) { return b; }\nfunction run() {\n  pick(1);\n  pick(2);\n}\n",
        "src/left.ts": "export function save() {}\nexport class Store { static save() {} }\n",
        "src/right.ts": "export function save() {}\nexport class Store { static save() {} }\n",
        "src/use.ts": 'import { save, Store } from "./left";\nimport * as right from "./right";\nsave();\nStore.save();\nright.save();\n',
    })
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    assert main(["scan"]) == 0
    capsys.readouterr()
    conn = sqlite3.connect(root / ".cbi/model.db")
    candidates = [row[0] for row in conn.execute(
        "SELECT id FROM nodes WHERE name = 'pick' ORDER BY id")]
    rows = conn.execute("SELECT node_id, detail FROM diagnostics WHERE kind = 'ambiguous_call' ORDER BY detail").fetchall()
    assert len(rows) == 2
    assert all(node.endswith("src/legacy.js") for node, _ in rows)
    assert [detail.split(": call", 1)[0] for _, detail in rows] == ["src/legacy.js:4:3", "src/legacy.js:5:3"]
    assert all("call pick" in detail and all(candidate in detail for candidate in candidates) for _, detail in rows)
    calls = conn.execute("SELECT src, dst FROM edges WHERE kind = 'calls'").fetchall()
    assert not any(dst in candidates for _, dst in calls)
    assert {dst.split(":", 2)[2] for src, dst in calls if src.endswith("src/use.ts")} == {
        "src/left.ts#save", "src/left.ts#Store.save", "src/right.ts#save",
    }


def test_python_and_csharp_and_vue_call_locations():
    from cbi.parse import csharp, python, vue

    _, facts, _ = python.parse(b'def run():\n    pick()\ndef pick(): pass\n', "python", False)
    assert facts["call_locations"] == [[2, 5]]
    _, facts, _ = csharp.parse(b'class A {\n void Run() { Pick(); }\n void Pick() {}\n}\n', "csharp", False)
    assert facts["call_locations"] == [[2, 15]]
    _, facts, _ = vue.parse(b'<script setup>\nimport Card from "./Card.vue";\nfunction run() { Card(); }\n</script>\n<template><Card /></template>\n', "vue", False, "View.vue")
    assert facts["call_locations"] == [[3, 18], [5, 11]]

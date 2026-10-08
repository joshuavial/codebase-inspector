"""define-concepts: every check, apply on scan, show, search and rescan."""

import json
import subprocess
from copy import deepcopy
from pathlib import Path

from cbi import build, concepts, store, tasks
from cbi.cli import main

FILES = {
    "a.ts": "export function a() { return 1 }\n",
    "b.ts": 'import { a } from "./a";\nexport function b() { return a(); }\n',
    "b.test.ts": 'import { b } from "./b";\ntest("b", () => { b(); });\n',
    "README.md": "# Demo\n",
}


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


def git(root, *args):
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def concept_brief(capsys):
    [task] = run_json(capsys, "tasks", "--kind", "define-concepts")
    return run_json(capsys, "task", task["id"])


def confirm_structure(capsys, tmp_path):
    [task] = run_json(capsys, "tasks", "--kind", "confirm-structure")
    brief = run_json(capsys, "task", task["id"])
    code, _, err = submit(capsys, tmp_path, task["id"], {
        "input_hash": brief["input_hash"], "deployables": [], "packages": [],
    })
    assert code == 0, err


def good(brief):
    """Two leaves and one integration. Covers the import and the call from b.ts to a.ts."""
    return {
        "input_hash": brief["input_hash"],
        "summary": "A small app.",
        "concepts": [
            {"id": "core", "name": "Core", "summary": "The function.", "role": "core", "files": ["a.ts"]},
            {"id": "app", "name": "App", "summary": "The caller.", "role": "app", "files": ["b.ts", "b.test.ts"]},
        ],
        "externals": [{"id": "x.os", "name": "OS", "summary": "The operating system.", "kind": "os"}],
        "relationships": [
            {"from": "app", "to": "core", "label": "calls", "basis": "imports"},
            {"from": "app", "to": "x.os", "label": "reads", "mechanism": "IPC", "at": "b.ts:b"},
        ],
    }


def repo_fixture(make_repo, monkeypatch, capsys, tmp_path):
    def make(name="repo"):
        root = make_repo(FILES, name=name)
        monkeypatch.chdir(root)
        assert main(["init"]) == 0
        assert main(["scan"]) == 0
        confirm_structure(capsys, tmp_path)
        return root
    return make


def test_brief_lists_checks_files_and_pairs(make_repo, monkeypatch, capsys, tmp_path):
    repo_fixture(make_repo, monkeypatch, capsys, tmp_path)()
    brief = concept_brief(capsys)
    assert brief["checks"] == concepts.CHECKS
    assert [f["path"] for f in brief["files"]] == ["a.ts", "b.test.ts", "b.ts"]
    assert {f["reason"] for f in brief["files"]} == {"unowned"}
    assert brief["files"][0]["outline"][0]["name"] == "a"
    assert brief["concepts"] is None and brief["rescan"] is False and brief["removed"] == [] and brief["env"] == []
    pairs = {(p["from"], p["to"], p["kind"]) for p in brief["pairs"]}
    assert ("b.ts", "a.ts", "imports") in pairs and ("b.ts", "a.ts", "calls") in pairs
    code, text, _ = run(capsys, "task", brief["id"])
    assert code == 0 and "every code and test file is owned by exactly one leaf" in text and brief["input_hash"] in text
    assert "an edge whose source file is a test does not count" in text


def test_each_check_fails_and_a_bad_answer_lists_them_all(make_repo, monkeypatch, capsys, tmp_path):
    root = repo_fixture(make_repo, monkeypatch, capsys, tmp_path)()
    brief = concept_brief(capsys)
    base = good(brief)
    conn = store.open_db(root / ".cbi" / "model.db")
    assert concepts.problems(conn, base) == ([], [])

    def errors(mutate):
        answer = deepcopy(base)
        mutate(answer)
        found, warnings = concepts.problems(conn, answer)
        assert warnings == []
        return found

    def unowned(answer):
        answer["concepts"][1]["files"] = ["b.ts"]

    def double(answer):
        answer["concepts"][1]["files"].append("a.ts")

    def nonleaf(answer):
        answer["concepts"] = [{
            "id": "parent", "name": "Parent", "summary": "Holds the leaves.", "role": "app", "files": ["a.ts"],
            "children": answer["concepts"],
        }]

    def duplicate(answer):
        answer["concepts"].append({"id": "core", "name": "Again", "summary": "Again.", "role": "core"})

    def collision(answer):
        answer["concepts"].insert(0, {"id": "local:repo", "name": "Nope", "summary": "No.", "role": "app"})

    def external_id(answer):
        answer["externals"][0]["id"] = "core"
        answer["relationships"] = [r for r in answer["relationships"] if r["to"] != "x.os"]

    def readme(answer):
        answer["concepts"][0]["files"].append("no-such.md")

    def twice(answer):
        answer["concepts"][0]["files"].append("a.ts")

    def bad_end(answer):
        answer["relationships"].append({"from": "app", "to": "missing", "label": "nope"})

    def uncovered(answer):
        answer["relationships"] = [answer["relationships"][1]]

    def no_via(answer):
        del answer["relationships"][1]["mechanism"]

    def no_at(answer):
        del answer["relationships"][1]["at"]

    def bad_at(answer):
        answer["relationships"][1]["at"] = "a.ts:a"

    def clash(answer):
        answer["relationships"][1]["via"] = "HTTP"

    def bare_at(answer):
        answer["relationships"][1]["at"] = "b.ts"

    def rollup(answer):
        answer["concepts"] = [{
            "id": "parent", "name": "Parent", "summary": "Holds the leaves.", "role": "app",
            "children": answer["concepts"],
        }]
        answer["relationships"].append({"from": "parent", "to": "x.os", "label": "uses", "basis": "reading"})

    assert errors(unowned) == ["$.concepts: unowned files: b.test.ts"]
    assert errors(double) == ["$.concepts[1].files[2]: 'a.ts' is owned by core and app"]
    assert errors(nonleaf) == ["$.concepts[0]: 'parent' owns files but is not a leaf (a.ts)"]
    assert errors(duplicate) == ["$.concepts[2].id: 'core' is duplicated ($.concepts[0].id)"]
    assert errors(collision) == ["$.concepts[0].id: 'local:repo' is already a workspace"]
    assert errors(external_id) == ["$.externals[0].id: 'core' is duplicated ($.concepts[0].id)"]
    assert errors(readme) == ["$.concepts[0].files[1]: 'no-such.md' is not a tracked file"]
    assert errors(twice) == ["$.concepts[0].files[1]: 'a.ts' listed twice"]
    assert errors(bad_end) == ["$.relationships[2].to: 'missing' is not a concept or external"]
    assert errors(uncovered) == [
        "$.relationships: no relationship covers calls app -> core: b.ts -> a.ts",
        "$.relationships: no relationship covers imports app -> core: b.ts -> a.ts",
    ]
    assert errors(no_via) == ["$.relationships[1]: integration app -> x.os has no via"]
    assert errors(no_at) == ["$.relationships[1]: integration app -> x.os has no at"]
    assert errors(bad_at) == ["$.relationships[1].at: 'a.ts:a' is not owned by app"]
    assert errors(clash) == ["$.relationships[1]: via 'HTTP' and mechanism 'IPC' differ"]
    assert errors(bare_at) == ["$.relationships[1].at: 'b.ts' is not path:function"]
    assert errors(rollup) == []

    nine = deepcopy(base)
    nine["concepts"] = [
        {"id": f"c{i}", "name": f"C{i}", "summary": "A part.", "role": "core",
         "files": ["a.ts", "b.ts", "b.test.ts"] if i == 0 else []}
        for i in range(9)
    ]
    nine["relationships"] = []
    assert concepts.problems(conn, nine) == ([], [])
    ten = deepcopy(nine)
    ten["concepts"].append({"id": "c9", "name": "C9", "summary": "A part.", "role": "core"})
    found, warnings = concepts.problems(conn, ten)
    assert found == [] and warnings == ["$.concepts: warning: the top level has 10 children; at most 9"]
    nested = deepcopy(base)
    nested["concepts"] = [{
        "id": "parent", "name": "Parent", "summary": "Holds the leaves.", "role": "app",
        "children": ten["concepts"],
    }]
    nested["relationships"] = []
    found, warnings = concepts.problems(conn, nested)
    assert found == [] and warnings == ["$.concepts[0].children: warning: 'parent' has 10 children; at most 9"]
    conn.close()

    role = deepcopy(base)
    role["concepts"][0]["role"] = "widget"
    code, _, err = submit(capsys, tmp_path, brief["id"], role)
    assert code == 2 and "$.concepts[0].role: 'widget' is not one of ui, app, service, core, data" in err
    kind = deepcopy(base)
    kind["externals"][0]["kind"] = "database"
    code, _, err = submit(capsys, tmp_path, brief["id"], kind)
    assert code == 2 and "$.externals[0].kind: 'database' is not one of platform, cli, saas, terminal, storage, os" in err

    many = deepcopy(base)
    many["concepts"][1]["files"] = ["b.ts"]
    many["relationships"] = [
        {"from": "app", "to": "missing", "label": "nope"},
        {"from": "app", "to": "x.os", "label": "reads"},
    ]
    code, _, err = submit(capsys, tmp_path, brief["id"], many)
    assert code == 2
    for line in (
        "$.concepts: unowned files: b.test.ts",
        "$.relationships[0].to: 'missing' is not a concept or external",
        "$.relationships[1]: integration app -> x.os has no via",
        "$.relationships[1]: integration app -> x.os has no at",
        "$.relationships: no relationship covers calls app -> core: b.ts -> a.ts",
        "$.relationships: no relationship covers imports app -> core: b.ts -> a.ts",
    ):
        assert line in err
    extra = deepcopy(base)
    extra["relationships"][0]["where"] = "here"
    code, _, err = submit(capsys, tmp_path, brief["id"], extra)
    assert code == 2 and "$.relationships[0].where: unknown key" in err
    assert not (root / ".cbi" / "concepts.json").exists()


def test_kind_alias_and_hand_edited_mechanism(make_repo, monkeypatch, capsys, tmp_path):
    root = repo_fixture(make_repo, monkeypatch, capsys, tmp_path)()
    brief = concept_brief(capsys)
    answer = good(brief)
    answer["externals"] = [
        {"id": "x.os", "name": "OS", "summary": "The operating system.", "kind": "os"},
        {"id": "x.term", "name": "Term", "summary": "A terminal.", "kind": "terminal"},
        {"id": "x.idb", "name": "IDB", "summary": "Browser storage.", "kind": "storage"},
    ]
    answer["concepts"] = [{
        "id": "product", "name": "Product", "summary": "The whole app.", "role": "app",
        "children": answer["concepts"],
    }]
    answer["relationships"][1]["via"] = answer["relationships"][1].pop("mechanism")
    answer["relationships"][1]["minor"] = False
    answer["relationships"].append({"from": "product", "to": "x.os", "label": "uses", "basis": "reading"})
    code, _, err = submit(capsys, tmp_path, brief["id"], answer)
    assert code == 0, err
    document = json.loads((root / ".cbi" / "concepts.json").read_text())
    assert [item["kind"] for item in document["externals"]] == ["terminal", "terminal", "storage"]
    stored = document["relationships"][1]
    assert stored == {"from": "app", "to": "x.os", "label": "reads", "via": "IPC", "at": "b.ts:b"}
    rollup = next(e for e in run_json(capsys, "show", "product")["outgoing"] if e["id"] == "x.os")
    assert rollup["attrs"] == {"basis": "reading", "integration": True, "label": "uses"}
    text = run(capsys, "show", "product")[1]
    assert "uses [integration]" in text and "via " not in text
    assert run_json(capsys, "show", "x.term")["display_kind"] == "terminal"
    assert run_json(capsys, "show", "x.idb")["attrs"]["kind"] == "storage"
    code, again, err = submit(capsys, tmp_path, brief["id"], answer)
    assert code == 0 and "nothing changed" in again, err
    stored["mechanism"] = stored.pop("via")
    document["externals"][0]["kind"] = "os"
    (root / ".cbi" / "concepts.json").write_text(json.dumps(document, indent=2) + "\n")
    assert main(["scan"]) == 0
    edge = next(e for e in run_json(capsys, "show", "app")["outgoing"] if e["id"] == "x.os")
    assert edge["attrs"]["via"] == "IPC" and "mechanism" not in edge["attrs"]
    assert run_json(capsys, "show", "x.os")["attrs"]["kind"] == "terminal"


def test_coverage_skips_edges_from_test_files(make_repo, monkeypatch, capsys, tmp_path):
    root = repo_fixture(make_repo, monkeypatch, capsys, tmp_path)()
    brief = concept_brief(capsys)
    conn = store.open_db(root / ".cbi" / "model.db")
    pairs = {(p["from"], p["to"], p["kind"]) for p in concepts._pairs(conn, concepts._code_files(conn))}
    assert ("b.test.ts", "b.ts", "imports") in pairs and ("b.test.ts", "b.ts", "calls") in pairs
    answer = good(brief)
    answer["concepts"][1]["files"] = ["b.ts"]
    answer["concepts"].append(
        {"id": "checks", "name": "Checks", "summary": "The tests.", "role": "app", "files": ["b.test.ts"]})
    assert concepts.problems(conn, answer) == ([], [])
    answer["relationships"] = [rel for rel in answer["relationships"] if rel["to"] != "core"]
    found, warnings = concepts.problems(conn, answer)
    assert warnings == []
    assert found == [
        "$.relationships: no relationship covers calls app -> core: b.ts -> a.ts",
        "$.relationships: no relationship covers imports app -> core: b.ts -> a.ts",
    ]
    conn.close()


def test_warning_is_accepted_and_reported_again(make_repo, monkeypatch, capsys, tmp_path):
    repo_fixture(make_repo, monkeypatch, capsys, tmp_path)()
    brief = concept_brief(capsys)
    answer = good(brief)
    answer["concepts"] = [
        {"id": f"c{i}", "name": f"C{i}", "summary": "A part.", "role": "core",
         "files": ["a.ts", "b.ts", "b.test.ts"] if i == 0 else []}
        for i in range(10)
    ]
    answer["relationships"] = []
    code, out, err = submit(capsys, tmp_path, brief["id"], answer)
    assert code == 0, err
    assert "warning: the top level has 10 children; at most 9" in out
    assert (Path(".cbi") / "concepts.json").exists()
    code, out, err = submit(capsys, tmp_path, brief["id"], answer)
    assert code == 0, err
    assert "nothing changed" not in out and "10 children" in out


def test_accept_shows_concepts_and_a_change_defeats_the_shortcut(make_repo, monkeypatch, capsys, tmp_path):
    root = repo_fixture(make_repo, monkeypatch, capsys, tmp_path)()
    brief = concept_brief(capsys)
    answer = {
        "input_hash": brief["input_hash"],
        "summary": "A small app.",
        "concepts": [{
            "id": "app", "name": "App", "summary": "The product.", "role": "app",
            "children": [
                {"id": "core", "name": "Core", "summary": "The function.", "role": "core", "files": ["a.ts"]},
                {"id": "ui", "name": "UI", "summary": "The caller.", "role": "ui", "files": ["b.ts", "b.test.ts"]},
            ],
        }],
        "externals": [{"id": "x.os", "name": "OS", "summary": "The operating system.", "kind": "os"}],
        "relationships": [
            {"from": "ui", "to": "core", "label": "calls", "basis": "imports"},
            {"from": "ui", "to": "core", "label": "reads"},
            {"from": "ui", "to": "x.os", "label": "reads", "mechanism": "IPC", "at": "b.ts:b", "minor": True},
        ],
    }
    code, out, err = submit(capsys, tmp_path, brief["id"], answer)
    assert code == 0 and "accepted" in out, err
    assert run_json(capsys, "tasks", "--kind", "define-concepts") == []
    code, again, _ = submit(capsys, tmp_path, brief["id"], answer)
    assert code == 0 and "nothing changed" in again

    shown = run_json(capsys, "show", "ui")
    assert shown["display_kind"] == "interface" and shown["attrs"]["role"] == "ui"
    assert shown["summary"] == "The caller." and shown["env"] == []
    assert {e["path"] for e in shown["outgoing"] if e["kind"] == "owns"} == {"b.ts", "b.test.ts"}
    rels = [e for e in shown["outgoing"] if e["kind"] == "relates" and e["id"] == "core"]
    assert {e["attrs"]["label"] for e in rels} == {"calls", "reads"}
    calls = next(e for e in rels if e["attrs"]["label"] == "calls")
    assert calls["attrs"]["basis"] == "imports" and calls["attrs"]["integration"] is False
    external = next(e for e in shown["outgoing"] if e["id"] == "x.os")
    assert external["attrs"] == {
        "at": "b.ts:b", "integration": True, "label": "reads", "minor": True, "via": "IPC"}
    assert shown["cross"] == [{
        "id": "local:repo:a.ts#a", "name": "a", "display_kind": "function",
        "concept": "core", "concept_name": "Core", "verbs": ["calls"],
    }]
    parent = run_json(capsys, "show", "app")
    assert [c["name"] for c in parent["children"]] == ["Core", "UI"] and parent["cross"] == []
    core = run_json(capsys, "show", "core")
    assert core["cross"][0]["name"] == "b" and core["cross"][0]["concept_name"] == "UI"
    assert "called" in core["cross"][0]["verbs"]

    code, text, _ = run(capsys, "show", "ui")
    assert "UI (interface)" in text and "role: ui" in text and "summary: The caller." in text
    assert "via IPC at b.ts:b [minor] [integration]" in text and "b.ts" in text and "a  (Core)" in text
    code, text, _ = run(capsys, "show", "x.os")
    assert "OS (terminal)" in text and "kind: terminal" in text and "The operating system." in text
    assert run_json(capsys, "search", "caller")[0]["id"] == "ui"
    assert any(hit["id"] == "x.os" for hit in run_json(capsys, "search", "operating"))

    conn = store.open_db(root / ".cbi" / "model.db")
    ordinals = [row[0] for row in conn.execute(
        "SELECT ordinal FROM edges WHERE kind = 'relates' AND src = 'ui' AND dst = 'core' ORDER BY ordinal")]
    assert ordinals == [0, 1]
    conn.execute(
        "INSERT INTO nodes (id, parent_id, kind, display_kind, name, workspace_id) "
        "VALUES ('local:repo:env:PORT', 'local:repo', 'env', 'env var', 'PORT', 'local:repo')"
    )
    conn.execute(
        "INSERT INTO edges (src, dst, kind, source, attrs) VALUES (?, 'local:repo:env:PORT', 'reads_env', 'agent', ?)",
        ("local:repo:a.ts#a", json.dumps({"default": "80"})),
    )
    conn.execute(
        "INSERT INTO nodes (id, parent_id, kind, display_kind, name, workspace_id, attrs) "
        "VALUES ('local:repo:service:db', 'local:repo', 'external', 'service', 'db', 'local:repo', '{}')"
    )
    concepts.apply(conn, (root / ".cbi" / "concepts.json").read_text())
    assert conn.execute("SELECT display_kind FROM nodes WHERE id = 'local:repo:service:db'").fetchone() == ("service",)
    assert conn.execute("SELECT name FROM nodes WHERE id = 'core'").fetchone() == ("Core",)
    conn.commit()
    conn.close()
    env = run_json(capsys, "show", "core")
    assert env["env"] == [{"name": "PORT", "default": "80"}]
    assert "PORT  default 80" in run(capsys, "show", "core")[1]

    code, out, _ = run(capsys, "scan")
    assert code == 0 and "scanned" in out and "no changes" not in out
    assert "no changes" in run(capsys, "scan")[1]

    path = root / ".cbi" / "concepts.json"
    document = json.loads(path.read_text())
    document["concepts"][0]["children"][0]["name"] = "Renamed"
    path.write_text(json.dumps(document, indent=2) + "\n")
    assert "no changes" not in run(capsys, "scan")[1]
    assert "Renamed (core)" in run(capsys, "show", "core")[1]
    assert run_json(capsys, "tasks", "--kind", "define-concepts") == []
    assert "no changes" in run(capsys, "scan")[1]


def test_rescan_lists_only_the_new_file(make_repo, monkeypatch, capsys, tmp_path):
    root = repo_fixture(make_repo, monkeypatch, capsys, tmp_path)()
    brief = concept_brief(capsys)
    assert submit(capsys, tmp_path, brief["id"], good(brief))[0] == 0
    (root / "dummy.ts").write_text("export const dummy = 1;\n")
    git(root, "add", "dummy.ts")
    assert main(["scan"]) == 0
    brief = concept_brief(capsys)
    assert [(f["path"], f["reason"]) for f in brief["files"]] == [("dummy.ts", "unowned")]
    assert brief["rescan"] is True and brief["concepts"]["summary"] == "A small app."
    assert brief["pairs"] == []


def test_rescan_lists_only_the_changed_file(make_repo, monkeypatch, capsys, tmp_path):
    root = repo_fixture(make_repo, monkeypatch, capsys, tmp_path)()
    brief = concept_brief(capsys)
    assert submit(capsys, tmp_path, brief["id"], good(brief))[0] == 0
    (root / "a.ts").write_text("export function a() { return 2 }\n")
    assert main(["scan"]) == 0
    brief = concept_brief(capsys)
    assert [(f["path"], f["reason"]) for f in brief["files"]] == [("a.ts", "changed")]
    assert {tuple(p[k] for k in ("from", "to", "kind")) for p in brief["pairs"]} == {
        ("b.ts", "a.ts", "calls"), ("b.ts", "a.ts", "imports"),
    }


def test_rescan_lists_a_removed_path(make_repo, monkeypatch, capsys, tmp_path):
    root = repo_fixture(make_repo, monkeypatch, capsys, tmp_path)()
    brief = concept_brief(capsys)
    assert submit(capsys, tmp_path, brief["id"], good(brief))[0] == 0
    (root / "a.ts").unlink()
    assert main(["scan"]) == 0
    brief = concept_brief(capsys)
    assert brief["files"] == [] and brief["removed"] == ["a.ts"]


def test_invalid_concepts_json_clears_the_map(make_repo, monkeypatch, capsys, tmp_path):
    root = repo_fixture(make_repo, monkeypatch, capsys, tmp_path)()
    brief = concept_brief(capsys)
    assert submit(capsys, tmp_path, brief["id"], good(brief))[0] == 0
    (root / ".cbi" / "concepts.json").write_text("{")
    assert main(["scan"]) == 0
    assert (root / ".cbi" / "concepts.json").read_text() == "{"
    shown = run_json(capsys, "show", "local:repo")
    assert any(d["kind"] == "concepts_invalid" for d in shown["diagnostics"])
    conn = store.open_db(root / ".cbi" / "model.db")
    assert conn.execute("SELECT count(*) FROM nodes WHERE kind = 'concept'").fetchone() == (0,)
    conn.close()
    brief = concept_brief(capsys)
    assert [f["path"] for f in brief["files"]] == ["a.ts", "b.test.ts", "b.ts"]



def test_brief_asks_for_delivery_and_test_suites(make_repo, monkeypatch, capsys, tmp_path):
    repo_fixture(make_repo, monkeypatch, capsys, tmp_path)()
    brief = concept_brief(capsys)
    text = run(capsys, "task", brief["id"])[1]
    for phrase in ("ci/", "pipelines", "compose files", "env/", "sql/", "seeds/", "scripts", "docs",
                   "unit, integration, e2e", "fixture builders", "may be left out"):
        assert phrase in brief["instructions"] and phrase in text
    assert any("at most one leaf" in check for check in brief["checks"])
    assert not any("seeds/" in check or "e2e" in check for check in brief["checks"])
    assert brief["checks"] == concepts.CHECKS


def test_other_tracked_files_are_optional_and_shown(make_repo, monkeypatch, capsys, tmp_path):
    root = repo_fixture(make_repo, monkeypatch, capsys, tmp_path)()
    brief = concept_brief(capsys)
    conn = store.open_db(root / ".cbi" / "model.db")
    answer = good(brief)
    assert concepts.problems(conn, answer) == ([], [])
    answer["concepts"][0]["files"].append("README.md")
    assert concepts.problems(conn, answer) == ([], [])
    both = deepcopy(answer)
    both["concepts"][1]["files"].append("README.md")
    found, warnings = concepts.problems(conn, both)
    assert warnings == []
    assert found == ["$.concepts[1].files[2]: 'README.md' is owned by core and app"]
    conn.close()

    code, _, err = submit(capsys, tmp_path, brief["id"], answer)
    assert code == 0, err
    conn = store.open_db(root / ".cbi" / "model.db")
    owned = {row[0] for row in conn.execute(
        "SELECT file.path FROM edges JOIN nodes file ON file.id = edges.dst "
        "WHERE edges.kind = 'owns' AND edges.src = 'core'")}
    assert "README.md" in owned and "a.ts" in owned
    payload = build.concept_view(conn, root)
    conn.close()

    def walk(nodes, found):
        for node in nodes:
            found.append(node)
            walk(node.get("children") or [], found)

    leaves = []
    walk(payload["concepts"], leaves)
    core = next(node for node in leaves if node["id"] == "core")
    assert "README.md" in core["files"]
    assert run_json(capsys, "tasks", "--kind", "define-concepts") == []

    (root / "README.md").write_text("# Changed\n")
    assert main(["scan"]) == 0
    brief = concept_brief(capsys)
    assert [(f["path"], f["reason"]) for f in brief["files"]] == [("README.md", "changed")]


def test_define_concepts_opens_once_structure_is_confirmed(make_repo, monkeypatch, capsys, tmp_path):
    root = make_repo(FILES, name="repo")
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    conn = store.open_db(root / ".cbi" / "model.db")
    tasks.attach_cache(conn)
    assert not concepts.structure_confirmed(conn)
    assert conn.execute("SELECT count(*) FROM tasks WHERE kind = 'define-concepts'").fetchone()[0] == 0
    conn.close()

    confirm_structure(capsys, tmp_path)
    conn = store.open_db(root / ".cbi" / "model.db")
    tasks.attach_cache(conn)
    try:
        assert concepts.structure_confirmed(conn)
        assert conn.execute("SELECT state FROM tasks WHERE kind = 'define-concepts'").fetchone() == ("open",)
        conn.execute("UPDATE tasks SET state = 'open' WHERE kind = 'confirm-structure'")
        concepts.refresh(conn)
        assert conn.execute("SELECT count(*) FROM tasks WHERE kind = 'define-concepts'").fetchone()[0] == 0
        conn.execute("UPDATE tasks SET state = 'done' WHERE kind = 'confirm-structure'")
        concepts.refresh(conn)
        assert conn.execute("SELECT state FROM tasks WHERE kind = 'define-concepts'").fetchone() == ("open",)
    finally:
        conn.close()


def test_symbol_show_groups_calls_by_owning_concept(make_repo, monkeypatch, capsys, tmp_path):
    root = make_repo({
        "a.ts": "export function a() { return 1 }\n",
        "b.ts": 'import { a } from "./a";\nexport function helper() { return 1 }\n'
                "export function b() { return helper() + a(); }\n",
        "child.tsx": "export function Child() { return null }\n",
        "view.tsx": 'import { Child } from "./child";\nexport function View() { return <Child />; }\n',
        "view.test.tsx": 'import { View } from "./view";\ntest("view", () => { View(); });\n',
    })
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0

    bare = run_json(capsys, "show", "b.ts#b")
    assert all("concept" not in edge for edge in bare["outgoing"] + bare["incoming"])
    code, text, _ = run(capsys, "show", "child.tsx#Child")
    assert code == 0 and "rendered by" not in text and "renders  " in text

    confirm_structure(capsys, tmp_path)
    brief = concept_brief(capsys)
    answer = {
        "input_hash": brief["input_hash"],
        "summary": "A small app.",
        "concepts": [
            {"id": "core", "name": "Core", "summary": "The function.", "role": "core",
             "files": ["a.ts", "child.tsx"]},
            {"id": "app", "name": "App", "summary": "The caller.", "role": "app", "files": ["b.ts"]},
            {"id": "ui", "name": "UI", "summary": "The screen.", "role": "ui",
             "files": ["view.tsx", "view.test.tsx"]},
        ],
        "externals": [],
        "relationships": [
            {"from": "app", "to": "core", "label": "calls", "basis": "imports"},
            {"from": "ui", "to": "core", "label": "renders", "basis": "imports"},
        ],
    }
    code, out, err = submit(capsys, tmp_path, brief["id"], answer)
    assert code == 0, err

    shown = run_json(capsys, "show", "b.ts#b")
    calls = {edge["name"]: edge for edge in shown["outgoing"] if edge["kind"] == "calls"}
    assert calls["a"]["concept"] == {"id": "core", "name": "Core"} and calls["a"]["module"] == "a.ts"
    assert calls["helper"]["concept"] == {"id": "app", "name": "App"} and calls["helper"]["module"] == "b.ts"
    assert all("concept" not in edge for edge in shown["outgoing"] if edge["kind"] != "calls")
    code, text, _ = run(capsys, "show", "b.ts#b")
    assert code == 0
    assert text.index("    App (here)\n") < text.index("    Core\n")
    assert "App, b.ts" in text and "Core, a.ts" in text

    shown = run_json(capsys, "show", "a.ts#a")
    caller = next(edge for edge in shown["incoming"] if edge["kind"] == "calls" and edge["name"] == "b")
    assert caller["concept"] == {"id": "app", "name": "App"} and caller["module"] == "b.ts"
    code, text, _ = run(capsys, "show", "a.ts#a")
    assert "called by" in text and "App, b.ts" in text and "(here)" not in text

    shown = run_json(capsys, "show", "view.tsx#View")
    render = next(edge for edge in shown["outgoing"] if edge["name"] == "Child")
    assert render["attrs"] == {"via": "jsx"}
    assert render["concept"] == {"id": "core", "name": "Core"} and render["module"] == "child.tsx"
    code, text, _ = run(capsys, "show", "view.tsx#View")
    assert "renders" in text and "Core, child.tsx" in text

    shown = run_json(capsys, "show", "child.tsx#Child")
    rendered = next(edge for edge in shown["incoming"] if edge["kind"] == "calls" and edge["name"] == "View")
    assert rendered["concept"] == {"id": "ui", "name": "UI"} and rendered["module"] == "view.tsx"
    code, text, _ = run(capsys, "show", "child.tsx#Child")
    assert "rendered by" in text and "UI, view.tsx" in text

    conn = store.open_db(root / ".cbi" / "model.db")
    conn.execute("DELETE FROM edges WHERE kind = 'owns' AND dst = ?", (calls["a"]["id"].split("#", 1)[0],))
    conn.commit()
    conn.close()
    shown = run_json(capsys, "show", "b.ts#b")
    orphan = next(edge for edge in shown["outgoing"] if edge["name"] == "a")
    assert orphan["concept"] is None and orphan["module"] == "a.ts"
    code, text, _ = run(capsys, "show", "b.ts#b")
    assert "(unowned)" in text and "Core\n" not in text


def _find_concept(nodes, cid):
    for node in nodes:
        if node["id"] == cid:
            return node
        found = _find_concept(node.get("children") or [], cid)
        if found:
            return found
    return None


def test_entry_and_hosts_are_validated(make_repo, monkeypatch, capsys, tmp_path):
    root = repo_fixture(make_repo, monkeypatch, capsys, tmp_path)()
    brief = concept_brief(capsys)
    code, text, _ = run(capsys, "task", brief["id"])
    assert code == 0
    assert "a concept's entry is true or false when set" in text
    assert "a relationship's kind is hosts when set" in text
    assert "Desktop app hosts Overview" in text

    bad_entry = good(brief)
    bad_entry["concepts"][0]["entry"] = "yes"
    code, _, err = submit(capsys, tmp_path, brief["id"], bad_entry)
    assert code == 2 and "$.concepts[0].entry: expected boolean, got str" in err

    bad_kind = good(brief)
    bad_kind["relationships"][0]["kind"] = "calls"
    code, _, err = submit(capsys, tmp_path, brief["id"], bad_kind)
    assert code == 2 and "$.relationships[0].kind: 'calls' is not one of hosts" in err
    assert not (root / ".cbi" / "concepts.json").exists()

    answer = good(brief)
    answer["concepts"][0]["entry"] = False
    answer["concepts"][1]["entry"] = True
    answer["relationships"][0]["kind"] = "hosts"
    conn = store.open_db(root / ".cbi" / "model.db")
    try:
        assert concepts.problems(conn, answer) == ([], [])
    finally:
        conn.close()
    code, _, err = submit(capsys, tmp_path, brief["id"], answer)
    assert code == 0, err
    document = json.loads((root / ".cbi" / "concepts.json").read_text())
    assert document["concepts"][0]["entry"] is False
    assert document["concepts"][1]["entry"] is True
    assert document["relationships"][0]["kind"] == "hosts"
    app = run_json(capsys, "show", "app")
    assert app["attrs"]["entry"] is True and "entry_file" not in app["attrs"]
    assert "starts here" in run(capsys, "show", "app")[1]
    core = run(capsys, "show", "core")[1]
    assert "hosted by App" in core and "starts here" not in core


def _mark(planned, relationships, files):
    nodes = [{"id": cid, "kind": "concept", "attrs": {}} for cid in planned]
    concepts._mark_entries(nodes, planned, {path: f"w:{path}" for path in files},
                           {f"w:{path}" for path in files}, relationships)
    return {node["id"]: node["attrs"] for node in nodes}


def test_several_entry_files_stay_on_the_ancestor():
    planned = {
        "desk": {"explicit": None, "files": [], "parent": None},
        "shell": {"explicit": None, "files": ["a.ts"], "parent": "desk"},
        "other": {"explicit": None, "files": ["b.ts"], "parent": "desk"},
    }
    by_id = _mark(planned, [], ["a.ts", "b.ts"])
    assert by_id["desk"]["entry"] is True and by_id["desk"]["entry_file"] == ["a.ts", "b.ts"]
    assert by_id["shell"] == {"entry": True, "entry_file": "a.ts"}
    assert by_id["other"] == {"entry": True, "entry_file": "b.ts"}


def test_hosted_entry_file_is_left_off_ancestors():
    """A host concept owns the UI it hosts, so the hosted entry stays off the host."""
    planned = {
        "app": {"explicit": None, "files": [], "parent": None},
        "desk": {"explicit": None, "files": [], "parent": "app"},
        "shell": {"explicit": None, "files": ["electron/main.ts"], "parent": "desk"},
        "overview": {"explicit": None, "files": ["src/main.tsx"], "parent": "desk"},
    }
    by_id = _mark(planned, [{"from": "desk", "to": "overview", "kind": "hosts"}],
                  ["electron/main.ts", "src/main.tsx"])
    assert by_id["app"]["entry"] is True and by_id["app"]["entry_file"] == "electron/main.ts"
    assert by_id["desk"]["entry"] is True and by_id["desk"]["entry_file"] == "electron/main.ts"
    assert by_id["shell"] == {"entry": True, "entry_file": "electron/main.ts"}
    assert by_id["overview"]["entry"] is False and by_id["overview"]["entry_file"] == "src/main.tsx"

    only_hosted = {
        "desk": {"explicit": None, "files": [], "parent": None},
        "overview": {"explicit": None, "files": ["src/main.tsx"], "parent": "desk"},
    }
    by_id = _mark(only_hosted, [{"from": "desk", "to": "overview", "kind": "hosts"}], ["src/main.tsx"])
    assert by_id["desk"] == {"entry": False}
    assert by_id["overview"]["entry"] is False and by_id["overview"]["entry_file"] == "src/main.tsx"


def test_hosted_renderer_is_not_an_entry(make_repo, monkeypatch, capsys, tmp_path):
    root = repo_fixture(make_repo, monkeypatch, capsys, tmp_path)()
    conn = store.open_db(root / ".cbi" / "model.db")
    wid = conn.execute("SELECT id FROM nodes WHERE kind = 'workspace'").fetchone()[0]
    conn.execute(
        "INSERT INTO nodes (id, parent_id, kind, display_kind, name, workspace_id, attrs) "
        "VALUES (?, ?, 'deployable', 'web app', 'web', ?, ?)",
        (f"{wid}:deployable:web", wid, wid, json.dumps({"entry_points": ["a.ts", "b.ts"]})),
    )
    conn.commit()
    conn.close()

    brief = concept_brief(capsys)
    answer = {
        "input_hash": brief["input_hash"],
        "summary": "A desktop app.",
        "concepts": [
            {"id": "desktop", "name": "Desktop app", "summary": "The shell.", "role": "app", "children": [
                {"id": "shell", "name": "Shell", "summary": "Opens the window.", "role": "app", "files": ["a.ts"]},
            ]},
            {"id": "ui", "name": "Overview", "summary": "The window.", "role": "ui", "children": [
                {"id": "renderer", "name": "Renderer", "summary": "Draws the window.", "role": "ui",
                 "files": ["b.ts", "b.test.ts"]},
            ]},
        ],
        "externals": [],
        "relationships": [
            {"from": "desktop", "to": "ui", "label": "opens the window for", "kind": "hosts"},
            {"from": "shell", "to": "renderer", "label": "opens the window for", "kind": "hosts"},
            {"from": "renderer", "to": "shell", "label": "calls"},
        ],
    }
    code, _, err = submit(capsys, tmp_path, brief["id"], answer)
    assert code == 0, err

    def attrs(cid):
        return run_json(capsys, "show", cid)["attrs"]

    assert attrs("desktop")["entry"] is True and attrs("desktop")["entry_file"] == "a.ts"
    assert attrs("shell")["entry"] is True and attrs("shell")["entry_file"] == "a.ts"
    assert attrs("ui")["entry"] is False and "entry_file" not in attrs("ui")
    assert attrs("renderer")["entry"] is False and attrs("renderer")["entry_file"] == "b.ts"
    assert "starts here (a.ts)" in run(capsys, "show", "desktop")[1]
    assert "starts here (a.ts)" in run(capsys, "show", "shell")[1]
    ui = run(capsys, "show", "ui")[1]
    assert "hosted by Desktop app" in ui and "starts here" not in ui
    renderer = run(capsys, "show", "renderer")[1]
    assert "hosted by Shell" in renderer and "starts here" not in renderer

    conn = store.open_db(root / ".cbi" / "model.db")
    payload = build.concept_view(conn)
    conn.close()

    def leaf(cid):
        found = []

        def walk(nodes):
            for node in nodes:
                found.append(node)
                walk(node.get("children") or [])

        walk(payload["concepts"])
        return next(node for node in found if node["id"] == cid)

    assert leaf("desktop")["entry"] is True and leaf("shell")["entryFiles"] == ["a.ts"]
    assert "entry" not in leaf("ui") and "entry" not in leaf("renderer")
    assert leaf("renderer")["entry_file"] == "b.ts"
    hosts = next(rel for rel in payload["relationships"] if rel["from"] == "desktop" and rel["to"] == "ui")
    assert hosts["kind"] == "hosts" and hosts["backing"] == "hosts"

    document = json.loads((root / ".cbi" / "concepts.json").read_text())
    _find_concept(document["concepts"], "renderer")["entry"] = True
    _find_concept(document["concepts"], "shell")["entry"] = False
    text = json.dumps(document)
    (root / ".cbi" / "concepts.json").write_text(text + "\n")
    conn = store.open_db(root / ".cbi" / "model.db")
    concepts.apply(conn, text)
    conn.commit()
    conn.close()
    assert run_json(capsys, "show", "renderer")["attrs"]["entry"] is True
    assert "starts here (b.ts)" in run(capsys, "show", "renderer")[1]
    assert "hosted by" not in run(capsys, "show", "renderer")[1]
    shell = run(capsys, "show", "shell")[1]
    assert "starts here" not in shell and "hosted by" not in shell
    assert "starts here (a.ts)" in run(capsys, "show", "desktop")[1]

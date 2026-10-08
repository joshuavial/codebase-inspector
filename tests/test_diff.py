"""Structural diff: one scanned fixture pair, plus the cases a scan does not hit."""

import json
import os
import sqlite3
import subprocess
from collections import Counter
from pathlib import Path

import pytest

from cbi import diff, store
from cbi.cli import main
from cbi.parse import symbol_nodes

GOLDEN_TEXT = Path(__file__).parent / "golden" / "diff.txt"
GOLDEN_JSON = Path(__file__).parent / "golden" / "diff.json"

# One of each change kind. Bodies differ on purpose: a move is a unique body
# hash, and two copies of `return 1` would not pair.
EXPECTED = {
    "concept-removed": 1, "concept-added": 2, "concept-split": 1, "concept-merged": 1, "concept-renamed": 2,
    "integration-removed": 1, "integration-added": 1, "integration-changed": 1,
    "relationship-removed": 1, "relationship-added": 1, "relationship-volume": 1,
    "file-moved-concept": 1, "deployable-removed": 1, "deployable-added": 1,
    "package-removed": 1, "package-added": 1, "depends-on-removed": 2, "depends-on-added": 2,
    "file-moved": 1, "env-unread": 1, "env-read": 1,
    "symbol-removed": 2, "symbol-added": 4, "symbol-moved": 2, "symbol-changed": 4, "untested": 3,
    "render-removed": 1, "render-added": 1, "test-removed": 1, "test-added": 1,
}


def fn(name, body, args=""):
    return f"export function {name}({args}) {{\n  {body}\n}}\n"


def pkg(name, **extra):
    return json.dumps({"name": name, **extra}) + "\n"


SAME = fn("same", "return 7;")
MOVE_ME = fn("moveMe", "return 41;")

BASE = {
    "left/package.json": pkg("left", main="src/index.ts"),
    "left/src/index.ts": fn("lib", "return 17;"),
    "right/package.json": pkg("right", dependencies={"left": "1.0.0"}, bin={"right": "src/main.ts"}),
    "right/src/main.ts": 'import { lib } from "../../left/src/index";\n\n' + fn("main", "return lib();"),
    "gone/package.json": pkg("gone", main="src/old.ts"),
    "gone/src/old.ts": fn("old", "return 14;"),
    "core/keep.ts": fn("keep", "return 11;"),
    "core/body.ts": fn("body", "return 1;"),
    "core/sig.ts": fn("sig", "return n;", args="n: number"),
    "core/drop.ts": fn("drop", "return 12;"),
    "core/move.ts": MOVE_ME + fn("stayPut", "return 19;"),
    "core/env.ts": fn("readEnv", "return process.env.OLD_FLAG;"),
    "core/ui.tsx": 'import { Badge } from "./badge";\n\nexport function Box() {\n  return <Badge />;\n}\n',
    "core/badge.tsx": 'export function Badge() {\n  return <span>badge</span>;\n}\n',
    "core/box.test.ts": 'import { Box } from "./ui";\n\ntest("box", () => {\n  Box();\n});\n',
    "app/use.ts": 'import { keep } from "../core/keep";\n\n' + fn("use", "return keep();"),
    "app/use.test.ts": 'import { use } from "./use";\n\ntest("use", () => {\n  use();\n});\n',
    "app/only.ts": fn("only", "return 16;"),
    "lib/stay.ts": fn("stay", "return 20;"),
    "split/a.ts": fn("partA", "return 21;"),
    "split/b.ts": fn("partB", "return 22;"),
    "merge/m1.ts": fn("m1", "return 23;"),
    "merge/m2.ts": fn("m2", "return 24;"),
    "move-file/same.ts": SAME,
}


def _head():
    files = dict(BASE)
    files["right/src/main.ts"] = fn("main", "return lib();")
    files["core/body.ts"] = fn("body", "return 2;")
    files["core/sig.ts"] = fn("sig", "return n;", args="n: number, extra: number")
    files["core/move.ts"] = fn("stayPut", "return 19;")
    files["core/env.ts"] = fn("readEnv", "return process.env.NEW_FLAG;")
    files["core/ui.tsx"] = 'import { Icon } from "./icon";\n\nexport function Box() {\n  return <Icon />;\n}\n'
    files["core/add.ts"] = fn("add", "return 13;")
    files["core/icon.tsx"] = 'export function Icon() {\n  return <span>icon</span>;\n}\n'
    files["core/sig.test.ts"] = 'import { sig } from "./sig";\n\ntest("sig", () => {\n  sig(1, 2);\n});\n'
    files["app/use.ts"] = BASE["app/use.ts"] + fn("useMore", "return keep();")
    files["app/moved.ts"] = MOVE_ME
    files["newcomer/package.json"] = pkg("newcomer", main="src/fresh.ts")
    files["newcomer/src/fresh.ts"] = 'import { lib } from "../../left/src/index";\n\n' + fn("fresh", "return 15;")
    files["relocated/same.ts"] = SAME
    for gone in ("gone/package.json", "gone/src/old.ts", "core/drop.ts", "core/box.test.ts", "move-file/same.ts"):
        del files[gone]
    return files


def _concept(cid, name, files, role="core"):
    return {"id": cid, "name": name, "summary": name, "role": role, "files": files}


def _concepts(concepts, externals, relationships):
    return json.dumps({
        "summary": "fixture", "concepts": concepts, "externals": externals, "relationships": relationships,
    })


def _base_concepts():
    return _concepts(
        [
            _concept("core", "Core", [
                "core/keep.ts", "core/body.ts", "core/sig.ts", "core/drop.ts", "core/move.ts",
                "core/env.ts", "core/ui.tsx", "core/badge.tsx", "core/box.test.ts",
            ]),
            _concept("app", "App", ["app/use.ts", "app/use.test.ts", "app/only.ts"], role="app"),
            _concept("named", "Named", ["lib/stay.ts"]),
            _concept("whole", "Whole", ["split/a.ts", "split/b.ts"]),
            _concept("part-1", "Part one", ["merge/m1.ts"]),
            _concept("part-2", "Part two", ["merge/m2.ts"]),
            _concept("going", "Going", ["gone/src/old.ts"]),
            _concept("parked", "Parked", ["move-file/same.ts"]),
        ],
        [
            {"id": "ext.os", "name": "OS", "summary": "The operating system.", "kind": "os"},
            {"id": "ext.api", "name": "API", "summary": "A service.", "kind": "saas"},
        ],
        [
            {"from": "app", "to": "core", "label": "uses", "basis": "calls"},
            {"from": "app", "to": "ext.os", "label": "reads", "mechanism": "IPC"},
            {"from": "core", "to": "ext.api", "label": "calls", "mechanism": "HTTP"},
            {"from": "named", "to": "core", "label": "old-link"},
        ],
    )


def _head_concepts():
    return _concepts(
        [
            _concept("core", "Core", [
                "core/keep.ts", "core/body.ts", "core/sig.ts", "core/move.ts", "core/env.ts",
                "core/ui.tsx", "core/badge.tsx", "core/add.ts", "core/icon.tsx", "core/sig.test.ts",
            ]),
            _concept("app", "App", ["app/use.ts", "app/use.test.ts", "app/moved.ts"], role="app"),
            _concept("other", "Other", ["app/only.ts"], role="app"),
            _concept("titled", "Titled", ["lib/stay.ts"]),
            _concept("half-a", "Half A", ["split/a.ts"]),
            _concept("half-b", "Half B", ["split/b.ts"]),
            _concept("joined", "Joined", ["merge/m1.ts", "merge/m2.ts"]),
            _concept("born", "Born", ["newcomer/src/fresh.ts"]),
            _concept("parked", "Stored", ["relocated/same.ts"]),
        ],
        [
            {"id": "ext.os", "name": "OS", "summary": "The operating system.", "kind": "os"},
            {"id": "ext.disk", "name": "Disk", "summary": "A disk.", "kind": "platform"},
        ],
        [
            {"from": "app", "to": "core", "label": "uses", "basis": "calls"},
            {"from": "app", "to": "ext.os", "label": "reads", "mechanism": "exec CLI"},
            {"from": "app", "to": "ext.disk", "label": "writes", "mechanism": "fs"},
            {"from": "born", "to": "core", "label": "starts"},
        ],
    )


def git(cwd, *args):
    subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@example.com", "-c", "commit.gpgsign=false", *args],
        cwd=cwd, check=True, capture_output=True, text=True,
    )


def commit_tree(root, files):
    keep = set(files)
    for path in root.rglob("*"):
        if not path.is_file() or ".git" in path.parts:
            continue
        rel = path.relative_to(root).as_posix()
        if rel not in keep:
            path.unlink()
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "head")


def run(capsys, *argv):
    capsys.readouterr()
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def scan_into(capsys, out, concepts):
    assert run(capsys, "init", "--out", str(out))[0] == 0
    (out / "concepts.json").write_text(concepts)
    code, stdout, err = run(capsys, "scan", "--out", str(out))
    assert code == 0, err
    assert "scanned" in stdout


def unique(result):
    """One copy of a change that is listed under more than one group."""
    found, seen = [], set()
    for group in result["groups"]:
        for change in group["changes"]:
            key = (change["kind"], change["summary"],
                   json.dumps(change["before"], sort_keys=True), json.dumps(change["after"], sort_keys=True))
            if key not in seen:
                seen.add(key)
                found.append(change)
    return found


def summaries(changes, kind):
    return [c["summary"] for c in changes if c["kind"] == kind]


def test_signature_change_keeps_the_body_hash():
    def parsed(source):
        nodes, _, err = symbol_nodes("f", "ws", "sig.ts", "typescript", source.encode(), False)
        assert not err and len(nodes) == 1
        return nodes[0]

    original = parsed(fn("sig", "return n;", args="n: number"))
    renamed = parsed("export function sig2(n: number) {\n  return n;\n}\n")
    wider = parsed(fn("sig", "return n;", args="n: number, extra: number"))
    rewritten = parsed(fn("sig", "return n + 1;", args="n: number"))
    assert original["signature"] != wider["signature"]
    assert original["content_hash"] == wider["content_hash"] == renamed["content_hash"]
    assert original["content_hash"] != rewritten["content_hash"]


def test_scanned_pair_covers_every_kind(make_repo, monkeypatch, tmp_path, capsys):
    root = make_repo(BASE)
    monkeypatch.chdir(root)
    base_out, head_out = tmp_path / "base", tmp_path / "head"
    scan_into(capsys, base_out, _base_concepts())
    commit_tree(root, _head())
    scan_into(capsys, head_out, _head_concepts())

    base, head = diff.open_model(base_out), diff.open_model(head_out)
    try:
        same = diff.open_model(base_out / "model.db")
        try:
            assert diff.render(diff.compare(base, same)) == "no architectural changes\n"
        finally:
            same.close()
        result = diff.compare(base, head)
    finally:
        base.close()
        head.close()

    changes = unique(result)
    counts = Counter(c["kind"] for c in changes)
    if counts != EXPECTED:
        detail = {k: summaries(changes, k) for k in sorted(set(counts) | set(EXPECTED)) if counts.get(k) != EXPECTED.get(k)}
        assert counts == EXPECTED, detail
    assert result["grouping"] == "concept"
    assert "(ungrouped)" not in {g["id"] for g in result["groups"]}
    for group in result["groups"]:
        ranks = [diff.RANK[c["kind"]] for c in group["changes"]]
        assert ranks == sorted(ranks)
        assert set(group) == {"id", "name", "kind", "changes"}
    group_ranks = [min(diff.RANK[c["kind"]] for c in g["changes"]) for g in result["groups"]]
    assert group_ranks == sorted(group_ranks)

    def one(kind, name):
        found = [c for c in changes if c["kind"] == kind and c["code"] and c["code"][0]["name"] == name]
        assert len(found) == 1, summaries(changes, kind)
        return found[0]

    assert one("symbol-changed", "body")["summary"].startswith("body  ")
    assert one("symbol-changed", "sig")["summary"].startswith("signature  ")
    assert one("symbol-changed", "readEnv")["summary"].startswith("body  ")
    assert one("symbol-changed", "Box")["summary"].startswith("body  ")
    assert {c["code"][0]["name"] for c in changes if c["kind"] == "untested"} == {"body", "readEnv", "Box"}
    assert set(summaries(changes, "symbol-moved")) == {
        "core/move.ts#moveMe -> app/moved.ts#moveMe",
        "move-file/same.ts#same -> relocated/same.ts#same",
    }
    assert summaries(changes, "file-moved") == ["move-file/same.ts -> relocated/same.ts"]
    assert summaries(changes, "file-moved-concept") == ["app/only.ts  App -> Other"]
    assert "calls 1 -> 2" in summaries(changes, "relationship-volume")[0]
    assert summaries(changes, "env-unread") == ["OLD_FLAG"]
    assert summaries(changes, "env-read") == ["NEW_FLAG"]
    assert any(c["kind"] == "concept-split" and isinstance(c["after"], list) for c in changes)
    assert any(c["kind"] == "concept-merged" and isinstance(c["before"], list) for c in changes)
    assert "Parked -> Stored" in summaries(changes, "concept-renamed")
    assert "Named -> Titled" in summaries(changes, "concept-renamed")
    assert not any("#main" in c["summary"] for c in changes)

    text = diff.render(result)
    rendered = diff.render(result, "json")
    assert diff.render(result, "markdown").startswith("# structural diff\n")
    code, out, err = run(capsys, "diff", "--base-model", str(base_out), "--head-model", str(head_out))
    assert code == 0 and out == text and err == ""
    code, out, err = run(capsys, "diff", "--base-model", str(base_out / "model.db"),
                         "--head-model", str(head_out), "--format", "json")
    assert code == 0 and out == rendered

    data = json.loads(rendered)
    assert set(data) == {"grouping", "groups"}
    for group in data["groups"]:
        for change in group["changes"]:
            assert set(change) == {"kind", "summary", "before", "after", "code"}
            assert change["kind"] in diff.KINDS
            for ref in change["code"]:
                assert set(ref) == {"id", "name", "path", "display_kind"}

    code, out, _ = run(capsys, "diff", "--base-model", str(base_out), "--head-model", str(head_out),
                       "--format", "json", "--concept", "named")
    assert code == 0
    named = json.loads(out)
    assert [g["id"] for g in named["groups"]] == ["titled"]
    assert named["groups"][0]["changes"][0]["kind"] == "concept-renamed"
    code, out, _ = run(capsys, "diff", "--base-model", str(base_out), "--head-model", str(head_out),
                       "--format", "json", "--concept", "going")
    going = json.loads(out)
    assert {c["kind"] for g in going["groups"] for c in g["changes"]} <= {"concept-removed", "symbol-removed"}
    assert "package-removed" not in {c["kind"] for g in going["groups"] for c in g["changes"]}

    if os.environ.get("CBI_UPDATE_GOLDEN"):
        GOLDEN_TEXT.write_text(text)
        GOLDEN_JSON.write_text(rendered)
    assert text == GOLDEN_TEXT.read_text()
    assert rendered == GOLDEN_JSON.read_text()


def test_help_documents_the_json_shape(capsys):
    with pytest.raises(SystemExit) as caught:
        main(["diff", "--help"])
    assert caught.value.code == 0
    out = capsys.readouterr().out
    assert "grouping" in out and "body is the body hash" in out
    for kind in diff.KINDS:
        assert kind in out


def test_bad_diff_arguments(tmp_path, capsys):
    code, _, err = run(capsys, "diff", "HEAD", "--base-model", "m", "--head-model", "n")
    assert code == 2 and "not both" in err
    code, _, err = run(capsys, "diff", "--base-model", "m")
    assert code == 2 and "both" in err
    code, _, err = run(capsys, "diff")
    assert code == 2

    missing = tmp_path / "missing.db"
    code, _, err = run(capsys, "diff", "--base-model", str(missing), "--head-model", str(missing))
    assert code == 1 and "no model" in err

    junk = tmp_path / "notes.txt"
    junk.write_text("not a database")
    code, _, err = run(capsys, "diff", "--base-model", str(junk), "--head-model", str(junk))
    assert code == 1 and "not a cbi model" in err

    real = tmp_path / "model.db"
    conn = store.open_db(real)
    conn.execute("PRAGMA user_version = 1")
    conn.commit()
    conn.close()
    with pytest.raises(diff.DiffError) as caught:
        diff.open_model(real)
    assert caught.value.code == 1 and "schema 1" in str(caught.value)

    base = store.open_db(tmp_path / "base.db")
    base.close()
    with pytest.raises(diff.DiffError):
        diff.open_pair(tmp_path / "base.db", tmp_path / "nope.db", None, None)
    # The base connection was closed, so the file can be opened for writing.
    sqlite3.connect(tmp_path / "base.db").close()


def test_diff_refs_scan_reuse_and_failures(make_repo, monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    code, _, err = run(capsys, "diff", "HEAD", "HEAD")
    assert code == 1 and "not inside a git repository" in err

    root = make_repo({"a.ts": fn("a", "return 1;")})
    monkeypatch.chdir(root)
    commit_tree(root, {"a.ts": fn("a", "return 2;")})
    out = tmp_path / "model"
    code, _, err = run(capsys, "diff", "--out", str(out), "HEAD~1", "HEAD")
    assert code == 1 and "not initialised" in err
    with pytest.raises(diff.DiffError) as caught:
        diff.models_for_refs("HEAD~1", "HEAD", root, out)
    assert caught.value.code == 1 and "not initialised" in str(caught.value)

    assert run(capsys, "init", "--out", str(out))[0] == 0
    code, text, err = run(capsys, "diff", "--out", str(out), "HEAD~1", "HEAD")
    assert code == 0, err
    assert err == "" and "symbol-changed" in text and "scanned" not in text
    dbs = sorted((out / "refs").glob("*/model.db"))
    assert len(dbs) == 2 and all(len(p.parent.name) == 40 for p in dbs)
    mtimes = [p.stat().st_mtime_ns for p in dbs]
    code, again, err = run(capsys, "diff", "--out", str(out), "HEAD~1", "HEAD")
    assert code == 0 and err == "" and again == text
    assert [p.stat().st_mtime_ns for p in dbs] == mtimes

    code, empty, err = run(capsys, "diff", "--out", str(out), "HEAD", "HEAD")
    assert code == 0 and err == "" and empty == "no architectural changes\n"
    assert sorted((out / "refs").glob("*/model.db")) == dbs

    code, _, err = run(capsys, "diff", "--out", str(out), "no-such-ref", "HEAD")
    assert code == 1 and "unknown ref" in err
    status = subprocess.run(["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True)
    assert status.stdout == ""
    assert not (root / ".cbi").exists()


def _node(**kwargs):
    node = {"parent_id": None, "workspace_id": "local:repo", "path": "", "content_hash": None,
            "signature": "", "attrs": None}
    node.update(kwargs)
    return node


def _write(path, nodes, edges=()):
    conn = store.open_db(path)
    conn.executemany(
        "INSERT INTO nodes (id, parent_id, kind, display_kind, name, workspace_id, path, content_hash, signature, attrs) "
        "VALUES (:id, :parent_id, :kind, :display_kind, :name, :workspace_id, :path, :content_hash, :signature, :attrs)",
        nodes,
    )
    conn.executemany(
        "INSERT INTO edges (src, dst, kind, source, weight, attrs) VALUES (?, ?, ?, 'treesitter', ?, ?)",
        edges,
    )
    conn.commit()
    conn.close()


def _compared(tmp_path, name, base_nodes, head_nodes, base_edges=(), head_edges=()):
    _write(tmp_path / f"{name}-base.db", base_nodes, base_edges)
    _write(tmp_path / f"{name}-head.db", head_nodes, head_edges)
    base, head = diff.open_model(tmp_path / f"{name}-base.db"), diff.open_model(tmp_path / f"{name}-head.db")
    try:
        return unique(diff.compare(base, head))
    finally:
        base.close()
        head.close()


def test_duplicate_body_is_not_a_move_and_a_unique_one_is(tmp_path):
    shared = "abc"
    file_node = _node(id="local:repo:a.ts", kind="file", display_kind="source file", name="a.ts", path="a.ts", content_hash="file")
    keep = _node(id="local:repo:a.ts#keep", kind="symbol", display_kind="function", name="keep", path="a.ts",
                 content_hash="keep", signature="function keep()")
    copied = _compared(
        tmp_path, "copy",
        [file_node, keep, _node(id="local:repo:a.ts#one", kind="symbol", display_kind="function", name="one",
                                path="a.ts", content_hash=shared, signature="function one()")],
        [file_node, keep,
         _node(id="local:repo:a.ts#two", kind="symbol", display_kind="function", name="two", path="a.ts",
               content_hash=shared, signature="function two()"),
         _node(id="local:repo:a.ts#three", kind="symbol", display_kind="function", name="three", path="a.ts",
               content_hash=shared, signature="function three()")],
    )
    assert {c["kind"] for c in copied} == {"symbol-removed", "symbol-added"}

    moved = _compared(
        tmp_path, "move",
        [_node(id="local:repo:a.ts#old", kind="symbol", display_kind="function", name="old", path="a.ts",
               content_hash=shared, signature="function old()")],
        [_node(id="local:repo:b.ts#new", kind="symbol", display_kind="function", name="new", path="b.ts",
               content_hash=shared, signature="function new()")],
    )
    assert [c["kind"] for c in moved] == ["symbol-moved"]


def test_without_concepts_groups_by_deployable_then_folder(tmp_path):
    def symbol(path, signature):
        return _node(id=f"local:repo:{path}#f", kind="symbol", display_kind="function", name="f", path=path,
                     content_hash="body", signature=signature)

    deployable = _node(id="local:repo:deployable:app", kind="deployable", display_kind="cli", name="app")
    folder = _node(id="local:repo:lib/", kind="group", display_kind="folder", name="lib", path="lib")
    owned = _node(id="local:repo:src/main.ts", parent_id="local:repo:src/", kind="file", display_kind="source file",
                  name="main.ts", path="src/main.ts")
    loose = _node(id="local:repo:lib/loose.ts", parent_id="local:repo:lib/", kind="file", display_kind="source file",
                  name="loose.ts", path="lib/loose.ts")
    changes = _compared(
        tmp_path, "group",
        [deployable, folder, owned, loose, symbol("src/main.ts", "function f()"), symbol("lib/loose.ts", "function f()")],
        [deployable, folder, owned, loose, symbol("src/main.ts", "function f(n)"), symbol("lib/loose.ts", "function f(n)")],
        [("local:repo:src/main.ts", "local:repo:deployable:app", "part_of", 1, None)],
        [("local:repo:src/main.ts", "local:repo:deployable:app", "part_of", 1, None)],
    )
    base, head = diff.open_model(tmp_path / "group-base.db"), diff.open_model(tmp_path / "group-head.db")
    try:
        result = diff.compare(base, head)
    finally:
        base.close()
        head.close()
    assert result["grouping"] == "deployable"
    assert {g["id"]: g["kind"] for g in result["groups"]} == {
        "local:repo:deployable:app": "deployable", "local:repo:lib/": "folder",
    }
    # No tests edge covers either symbol, so each signature change is also untested.
    assert {c["kind"] for c in changes} == {"symbol-changed", "untested"}
    assert {g["id"] for g in result["groups"] for c in g["changes"] if c["kind"] == "untested"} == {
        "local:repo:deployable:app", "local:repo:lib/",
    }


def test_moved_test_is_omitted_and_untested_walks_ancestors(tmp_path):
    moved = _compared(
        tmp_path, "tests",
        [_node(id="local:repo:a.test.ts#box", kind="test", display_kind="test case", name="box",
               path="a.test.ts", content_hash="same-test")],
        [_node(id="local:repo:b.test.ts#box", kind="test", display_kind="test case", name="box",
               path="b.test.ts", content_hash="same-test")],
    )
    assert moved == []

    file_id = "local:repo:core.ts"
    parent = "local:repo:core.ts#Box"
    child = "local:repo:core.ts#Box.render"
    nodes = [
        _node(id=file_id, kind="file", display_kind="source file", name="core.ts", path="core.ts"),
        _node(id=parent, kind="symbol", display_kind="class", name="Box", path="core.ts", signature="class Box"),
        _node(id=child, parent_id=parent, kind="symbol", display_kind="method", name="render", path="core.ts",
              signature="render()", content_hash="v1"),
    ]
    head_nodes = [
        nodes[0], nodes[1],
        _node(id=child, parent_id=parent, kind="symbol", display_kind="method", name="render", path="core.ts",
              signature="render(n)", content_hash="v1"),
    ]
    covered = _compared(tmp_path, "ancestor", nodes, head_nodes, [],
                        [("local:repo:core.test.ts#box", parent, "tests", 1, None)])
    # The tests edge points at the class, the method's parent, so the change is covered.
    assert [c["kind"] for c in covered] == ["symbol-changed"]

    on_file = _compared(tmp_path, "file", nodes, head_nodes, [],
                        [("local:repo:core.test.ts#box", file_id, "tests", 1, None)])
    assert [c["kind"] for c in on_file] == ["symbol-changed"]

    added = _compared(
        tmp_path, "added",
        [nodes[0]],
        [nodes[0], _node(id=child, kind="symbol", display_kind="method", name="render", path="core.ts",
                         signature="render()", content_hash="v1")],
    )
    assert [c["kind"] for c in added] == ["symbol-added"]


def test_integration_reads_via_or_mechanism_and_at(tmp_path):
    ends = [
        _node(id="app", kind="concept", display_kind="app", name="App"),
        _node(id="os", kind="external", display_kind="os", name="OS"),
    ]

    def edge(mechanism_key, mechanism, at=""):
        attrs = {"label": "reads", "integration": True, mechanism_key: mechanism}
        if at:
            attrs["at"] = at
        return ("app", "os", "relates", 1, json.dumps(attrs))

    changed = _compared(tmp_path, "via", ends, ends, [edge("via", "HTTP")], [edge("mechanism", "fs", "pod")])
    assert [c["kind"] for c in changed] == ["integration-changed"]
    assert changed[0]["before"]["mechanism"] == "HTTP"
    assert changed[0]["after"]["mechanism"] == "fs"
    assert "at — -> pod" in changed[0]["summary"]


def test_injection_calls_count_as_production_calls(tmp_path):
    app = _node(id="app", kind="concept", display_kind="service", name="App")
    core = _node(id="core", kind="concept", display_kind="core", name="Core")
    a = _node(id="local:repo:a.ts", kind="file", display_kind="source file", name="a.ts", path="a.ts")
    b = _node(id="local:repo:b.ts", kind="file", display_kind="source file", name="b.ts", path="b.ts")
    test = _node(id="local:repo:a.test.ts", kind="file", display_kind="test file", name="a.test.ts", path="a.test.ts")
    fn = _node(id="local:repo:a.ts#run", kind="symbol", display_kind="function", name="run", path="a.ts")
    append = _node(id="local:repo:b.ts#append", kind="symbol", display_kind="method", name="append", path="b.ts")
    tfn = _node(id="local:repo:a.test.ts#run", kind="symbol", display_kind="function", name="run", path="a.test.ts")
    nodes = [app, core, a, b, test, fn, append, tfn]
    owns = [
        ("app", "local:repo:a.ts", "owns", 1, None),
        ("app", "local:repo:a.test.ts", "owns", 1, None),
        ("core", "local:repo:b.ts", "owns", 1, None),
    ]
    relates = ("app", "core", "relates", 1, json.dumps({"label": "records to"}))
    inject = json.dumps({"via": "injection"})
    changes = _compared(
        tmp_path, "inject", nodes, nodes,
        [*owns, relates],
        [*owns, relates,
         ("local:repo:a.ts#run", "local:repo:b.ts#append", "calls", 2, inject),
         ("local:repo:a.test.ts#run", "local:repo:b.ts#append", "calls", 9, inject)],
    )
    volume = [c for c in changes if c["kind"] == "relationship-volume"]
    assert len(volume) == 1
    assert volume[0]["before"] == {"from": "app", "to": "core", "label": "records to", "calls": 0, "imports": 0}
    assert volume[0]["after"]["calls"] == 2 and volume[0]["after"]["imports"] == 0


def test_render_edges_ignore_weight_and_non_components(tmp_path):
    component = _node(id="local:repo:ui.tsx#Box", kind="symbol", display_kind="component", name="Box", path="ui.tsx")
    child = _node(id="local:repo:ui.tsx#Badge", kind="symbol", display_kind="component", name="Badge", path="ui.tsx")
    plain = _node(id="local:repo:ui.tsx#helper", kind="symbol", display_kind="function", name="helper", path="ui.tsx")
    nodes = [component, child, plain]
    jsx = json.dumps({"via": "jsx"})
    heavier = _compared(
        tmp_path, "weight", nodes, nodes,
        [("local:repo:ui.tsx#Box", "local:repo:ui.tsx#Badge", "calls", 1, jsx)],
        [("local:repo:ui.tsx#Box", "local:repo:ui.tsx#Badge", "calls", 4, jsx)],
    )
    assert heavier == []
    ignored = _compared(
        tmp_path, "plain", nodes, nodes, [],
        [("local:repo:ui.tsx#helper", "local:repo:ui.tsx#Badge", "calls", 1, jsx)],
    )
    assert ignored == []
    added = _compared(
        tmp_path, "render", nodes, nodes, [],
        [("local:repo:ui.tsx#Box", "local:repo:ui.tsx#Badge", "calls", 1, jsx)],
    )
    assert [c["kind"] for c in added] == ["render-added"]

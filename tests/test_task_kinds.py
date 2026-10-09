"""summarise-group and summarise-workspace: bottom-up blocking, submit, reopening, the shared cache and prime."""

import json
import sqlite3

import pytest

from cbi import store, tasks
from cbi.cli import main

FILES = {
    "README.md": "# Demo\n\nA demo app that adds numbers.\n",
    "root.ts": "export const r = 1;\n",
    "a/x.ts": "import { y } from './b/y';\nexport function x() { return y(); }\n",
    "a/b/y.ts": "export function y() { return 2; }\n",
    "a/b/y.test.ts": "import { y } from './y';\ntest('y is 2', () => { y(); });\n",
    "docs/guide.md": "# Guide\n",
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
    path.write_text(value if isinstance(value, str) else json.dumps(value))
    return run(capsys, "submit", task_id, str(path))


def answer(brief, text=None):
    if brief["kind"] == "summarise-files":
        return {"input_hash": brief["input_hash"],
                "files": [{"path": f["path"], "summary": text or f"About {f['path']}."} for f in brief["files"]]}
    if brief["kind"] == "confirm-structure":
        return {"input_hash": brief["input_hash"], "deployables": [], "packages": []}
    if brief["kind"] == "define-concepts":
        return {"input_hash": brief["input_hash"], "summary": "A demo app.",
                "concepts": [{"id": "app", "name": "App", "summary": "The app.", "role": "app",
                              "files": [f["path"] for f in brief["files"]]}],
                "externals": [], "relationships": []}
    if brief["kind"] == "sketch-screens":
        return {"input_hash": brief["input_hash"], "screens": [], "unsketched": [
            {"component": comp["ref"], "reason": "not a screen"} for comp in brief.get("components") or []]}
    return {"input_hash": brief["input_hash"], "summary": text or f"About {brief['node']['path'] or 'the repo'}."}


def states():
    conn = sqlite3.connect(".cbi/model.db")
    return {(k, n): s for k, n, s in conn.execute(
        "SELECT t.kind, coalesce(n.path, ''), t.state FROM tasks t JOIN nodes n ON n.id = t.node_id")}


def finish(capsys, tmp_path):
    """Answer open tasks until none are left. Returns the task IDs in the order they were answered."""
    order = []
    while found := run_json(capsys, "tasks"):
        for t in found:
            assert submit(capsys, tmp_path, t["id"], answer(run_json(capsys, "task", t["id"])))[0] == 0
            order.append(t["id"])
    return order


@pytest.fixture
def repo(make_repo, monkeypatch, capsys):
    def make(name="repo", files=FILES):
        root = make_repo(files, name=name)
        monkeypatch.chdir(root)
        assert main(["init"]) == 0
        assert main(["scan"]) == 0
        return root
    return make


def test_group_tasks_wait_for_files_and_subgroups(repo, tmp_path, capsys):
    repo()
    assert states() == {
        ("summarise-files", ""): "open", ("summarise-files", "a"): "open", ("summarise-files", "a/b"): "open",
        ("summarise-group", "a"): "blocked", ("summarise-group", "a/b"): "blocked",
        ("summarise-workspace", ""): "blocked", ("confirm-structure", ""): "open",
    }  # docs/ holds no code, so it gets no task
    by = {(t["kind"], t["node_path"]): t["id"] for t in run_json(capsys, "tasks")}
    blocked = run_json(capsys, "task", _task_id(("summarise-group", "a")))
    assert blocked["state"] == "blocked" and by[("summarise-files", "a")] in blocked["waiting_on"]
    code, _, err = submit(capsys, tmp_path, blocked["id"], answer(blocked))
    assert code == 2 and "blocked" in err

    code, out, _ = submit(capsys, tmp_path, by[("summarise-files", "a/b")],
                          answer(run_json(capsys, "task", by[("summarise-files", "a/b")])))
    assert code == 0 and f"now open: {_task_id(('summarise-group', 'a/b'))}" in out
    assert states()[("summarise-group", "a")] == "blocked"
    files_a = run_json(capsys, "task", by[("summarise-files", "a")])
    assert submit(capsys, tmp_path, files_a["id"], answer(files_a))[0] == 0
    assert states()[("summarise-group", "a")] == "blocked"  # still waits on a/b's group task

    order = finish(capsys, tmp_path)
    assert order.index(_task_id(("summarise-group", "a/b"))) < order.index(_task_id(("summarise-group", "a")))
    assert order[-1] == _task_id(("summarise-workspace", ""))
    assert set(states().values()) == {"done"}
    assert run_json(capsys, "show", "a")["summary"] == "About a."
    assert run_json(capsys, "search", "About")  # summaries are searchable


def _task_id(key):
    conn = sqlite3.connect(".cbi/model.db")
    return conn.execute(
        "SELECT t.id FROM tasks t JOIN nodes n ON n.id = t.node_id WHERE t.kind = ? AND coalesce(n.path, '') = ?", key
    ).fetchone()[0]


def test_group_and_workspace_briefs(repo, tmp_path, capsys):
    repo()
    finish_files(capsys, tmp_path)
    b = run_json(capsys, "task", _task_id(("summarise-group", "a/b")))
    assert b["node"] == {"name": "b", "display_kind": "folder", "path": "a/b"}
    assert [c["name"] for c in b["children"]] == ["y.test.ts", "y.ts"]
    assert b["children"][1]["summary"] == "About a/b/y.ts." and "enum" in b["answer_schema"]["properties"]["display_kind"]
    code, text, _ = run(capsys, "task", b["id"])
    assert code == 0 and "About a/b/y.ts." in text and b["input_hash"] in text and '"summary": "..."' in text

    for key in (("summarise-group", "a/b"), ("summarise-group", "a")):
        t = run_json(capsys, "task", _task_id(key))
        submit(capsys, tmp_path, t["id"], answer(t))
    ws = run_json(capsys, "task", _task_id(("summarise-workspace", "")))
    assert ws["state"] == "open" and ws["readme"]["path"] == "README.md"
    assert "A demo app that adds numbers." in ws["readme"]["head"]
    assert {c["name"]: c["summary"] for c in ws["children"]} == {
        "README.md": None, "a": "About a.", "docs": None, "root.ts": "About root.ts."}
    code, text, _ = run(capsys, "task", ws["id"])
    assert "## README head (README.md)" in text and "A demo app" in text


def finish_files(capsys, tmp_path):
    for t in run_json(capsys, "tasks", "--kind", "summarise-files"):
        assert submit(capsys, tmp_path, t["id"], answer(run_json(capsys, "task", t["id"])))[0] == 0


def test_group_answer_validation(repo, tmp_path, capsys):
    repo()
    finish_files(capsys, tmp_path)
    task_id = _task_id(("summarise-group", "a/b"))
    b = run_json(capsys, "task", task_id)
    bad = {"input_hash": b["input_hash"], "display_kind": "spaceship", "display_name": " ", "colour": "red"}
    code, _, err = submit(capsys, tmp_path, task_id, bad)
    assert code == 2
    assert "$.summary: required" in err and "$.colour: unknown key" in err
    assert "$.display_kind: 'spaceship' is not one of folder, module" in err and "$.display_name: empty" in err
    code, _, err = submit(capsys, tmp_path, task_id, {"input_hash": b["input_hash"], "summary": 3})
    assert code == 2 and "$.summary: expected string, got int" in err
    code, _, err = submit(capsys, tmp_path, task_id, {"input_hash": "0" * 16, "summary": "s"})
    assert code == 2 and "$.input_hash: stale" in err
    assert states()[("summarise-group", "a/b")] == "open"


def test_display_overrides_survive_rescan(repo, tmp_path, capsys):
    root = repo()
    finish_files(capsys, tmp_path)
    t = run_json(capsys, "task", _task_id(("summarise-group", "a/b")))
    good = dict(answer(t, "Adds two."), display_kind="module", display_name="Adder")
    code, out, _ = submit(capsys, tmp_path, t["id"], good)
    assert code == 0 and "accepted" in out
    shown = run_json(capsys, "show", "a/b")
    assert shown["display_kind"] == "module" and shown["attrs"]["display_name"] == "Adder"
    parent = run_json(capsys, "task", _task_id(("summarise-group", "a")))
    assert {"name": "b", "display_kind": "module", "summary": "Adds two.", "display_name": "Adder", "path": "a/b"} in parent["children"]

    (root / "docs" / "more.md").write_text("# More\n")  # rescan without touching a/
    run(capsys, "scan")
    shown = run_json(capsys, "show", "a/b")
    assert shown["display_kind"] == "module" and shown["summary"] == "Adds two."

    t = run_json(capsys, "task", _task_id(("summarise-group", "a/b")))
    submit(capsys, tmp_path, t["id"], answer(t, "Adds two."))  # same summary, no overrides
    shown = run_json(capsys, "show", "a/b")
    assert shown["display_kind"] == "folder" and shown["attrs"] is None


def test_resubmit_is_idempotent_and_parent_reopens_only_on_changed_text(repo, tmp_path, capsys):
    repo()
    finish(capsys, tmp_path)
    files_b = _task_id(("summarise-files", "a/b"))
    group_b = _task_id(("summarise-group", "a/b"))
    b = run_json(capsys, "task", group_b)
    code, out, _ = submit(capsys, tmp_path, group_b, answer(b))
    assert code == 0 and "nothing changed" in out

    # Same text for the files again: nothing reopens.
    fb = run_json(capsys, "task", files_b)
    code, out, _ = submit(capsys, tmp_path, files_b, answer(fb))
    assert code == 0 and "nothing changed" in out
    assert set(states().values()) == {"done"}

    # New text for one file: its folder reopens, the folders above wait again.
    changed = answer(fb)
    changed["files"][0]["summary"] = "A different summary."
    code, out, _ = submit(capsys, tmp_path, files_b, changed)
    assert code == 0 and f"now open: {group_b}" in out
    s = states()
    assert s[("summarise-group", "a/b")] == "open"
    assert s[("summarise-group", "a")] == "blocked" and s[("summarise-workspace", "")] == "blocked"
    assert run_json(capsys, "show", "a")["summary"] is None

    # The folder answered with its old text: the parents' inputs are unchanged, so they are done again.
    b = run_json(capsys, "task", group_b)
    code, out, _ = submit(capsys, tmp_path, group_b, answer(b))
    assert code == 0
    assert set(states().values()) == {"done"}
    assert run_json(capsys, "show", "a")["summary"] == "About a."

    # A new folder summary text reopens the parent.
    b = run_json(capsys, "task", group_b)
    code, out, _ = submit(capsys, tmp_path, group_b, answer(b, "Something else."))
    assert f"now open: {_task_id(('summarise-group', 'a'))}" in out


def test_second_repo_with_identical_files_needs_no_tasks(repo, tmp_path, capsys):
    repo("first")
    finish(capsys, tmp_path)
    repo("second")
    assert set(states().values()) == {"done"}
    assert run_json(capsys, "tasks") == []
    assert run_json(capsys, "show", "a/b")["summary"] == "About a/b."
    assert run_json(capsys, "show", "local:second")["summary"] == "About the repo."


def test_workspace_lists_a_packaged_folder_once(tmp_path):
    """A package with no summary task is the same directory as its folder. List the folder."""
    conn = store.open_db(tmp_path / "model.db")
    tasks.attach_cache(conn)
    rows = [
        ("local:r", None, "workspace", "workspace", "r", None, "", None),
        ("local:r:package:app", "local:r", "package", "package", "codebase-inspector-app", "local:r", "app",
         '{"directory": "app"}'),
        ("local:r:app/", "local:r", "group", "folder", "app", "local:r", "app", None),
        ("local:r:app/main.ts", "local:r:app/", "file", "source file", "main.ts", "local:r", "app/main.ts",
         '{"role": "code"}'),
        ("local:r:package:r", "local:r", "package", "package", "r", "local:r", "", '{"directory": ""}'),
        ("local:r:scripts/", "local:r", "group", "folder", "scripts", "local:r", "scripts", None),
        ("local:r:scripts/run.ts", "local:r:scripts/", "file", "source file", "run.ts", "local:r", "scripts/run.ts",
         '{"role": "code"}'),
    ]
    conn.executemany(
        "INSERT INTO nodes (id, parent_id, kind, display_kind, name, workspace_id, path, attrs) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
    conn.execute("UPDATE nodes SET summary = 'The app.' WHERE id = 'local:r:app/main.ts'")
    conn.execute("UPDATE nodes SET summary = 'A script.' WHERE id = 'local:r:scripts/run.ts'")
    tasks.refresh_summaries(conn)
    inputs = json.loads(conn.execute("SELECT inputs FROM tasks WHERE kind = 'summarise-workspace'").fetchone()[0])
    assert "local:r:package:app" not in inputs
    assert "local:r:app/" in inputs and "local:r:scripts/" in inputs
    assert "local:r:package:r" in inputs  # the root package is not a folder
    assert conn.execute("SELECT id FROM tasks WHERE node_id = 'local:r:package:app'").fetchone() is None
    brief = tasks.brief(conn, conn.execute("SELECT id FROM tasks WHERE kind = 'summarise-workspace'").fetchone()[0])
    assert [c["name"] for c in brief["children"]] == ["app", "r", "scripts"]


def test_package_with_its_own_summary_stays_beside_a_folder(tmp_path):
    conn = store.open_db(tmp_path / "model.db")
    tasks.attach_cache(conn)
    rows = [
        ("local:r", None, "workspace", "workspace", "r", None, "", None),
        ("local:r:package:core", "local:r", "package", "package", "core", "local:r", "core", None),
        ("local:r:core/", "local:r", "group", "folder", "core", "local:r", "core", None),
        ("local:r:core/a.ts", "local:r:package:core", "file", "source file", "a.ts", "local:r", "core/a.ts",
         '{"role": "code"}'),
    ]
    conn.executemany(
        "INSERT INTO nodes (id, parent_id, kind, display_kind, name, workspace_id, path, attrs) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
    conn.execute("UPDATE nodes SET summary = 'A.' WHERE id = 'local:r:core/a.ts'")
    tasks.refresh_summaries(conn)
    inputs = json.loads(conn.execute("SELECT inputs FROM tasks WHERE kind = 'summarise-workspace'").fetchone()[0])
    assert "local:r:package:core" in inputs and "local:r:core/" in inputs


def test_package_node_gets_a_group_task(tmp_path, monkeypatch):
    """Packages come from manifests (deliverable 5); here the rows are inserted by hand."""
    conn = store.open_db(tmp_path / "model.db")
    tasks.attach_cache(conn)
    rows = [
        ("local:r", None, "workspace", "workspace", "r", None, "", None),
        ("local:r:package:core", "local:r", "package", "package", "core", "local:r", "core", None),
        ("local:r:core/a.ts", "local:r:package:core", "file", "source file", "a.ts", "local:r", "core/a.ts", '{"role": "code"}'),
    ]
    conn.executemany("INSERT INTO nodes (id, parent_id, kind, display_kind, name, workspace_id, path, attrs) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
    tasks.refresh_summaries(conn)
    got = dict(conn.execute("SELECT node_id, state FROM tasks"))
    assert got == {"local:r:package:core": "blocked", "local:r": "blocked"}
    conn.execute("UPDATE nodes SET summary = 'A.' WHERE id = 'local:r:core/a.ts'")
    tasks.refresh_summaries(conn)
    assert dict(conn.execute("SELECT node_id, state FROM tasks"))["local:r:package:core"] == "open"


def test_prime_pending_and_complete(repo, tmp_path, capsys):
    root = repo()
    code, scan_out, err = run(capsys, "scan")
    assert code == 0, err
    code, out, _ = run(capsys, "prime")
    assert code == 0 and len(out.splitlines()) < 60
    open_n, blocked_n = sqlite3.connect(".cbi/model.db").execute(
        "SELECT coalesce(sum(state = 'open'), 0), coalesce(sum(state = 'blocked'), 0) FROM tasks"
    ).fetchone()
    headline = f"{int(open_n)} judgement tasks open, {int(blocked_n)} blocked"
    assert f"## {headline}" in out
    assert scan_out.splitlines()[-1] == headline + "; run `cbi tasks`"
    assert "summarise-files      3 open, 0 blocked" in out
    assert "summarise-group      0 open, 2 blocked" in out and "summarise-workspace  0 open, 1 blocked" in out
    assert "Accepting confirm-structure opens define-concepts beside any file summaries still open." in out
    assert "summarise-deployable stays blocked until confirm-structure is done and that deployable's member files are summarised." in out
    assert "sketch-screens opens after define-concepts is done, when the repo has UI components or screen templates." in out
    assert "Pass `--out DIR` on every command" not in out and "--out " not in out
    assert "## Ingest" in out and "No test runner detected in package.json or pyproject.toml." in out
    first = run_json(capsys, "tasks")[0]
    assert first["kind"] == "confirm-structure"
    assert f"$ cbi task {first['id']}" in out and f"$ cbi submit {first['id']} answer.json" in out
    assert '"input_hash"' in out and "subagents" in out
    assert '"packages": []' in out and '"directory"' not in out
    assert "Empty arrays accept detection as it is and do not add a package" in out
    assert "# scripts or tests, no production file outside imports them: a" in out

    finish(capsys, tmp_path)
    code, out, _ = run(capsys, "prime")
    viewer = root / ".cbi" / "viewer" / "index.html"
    assert code == 0 and len(out.splitlines()) < 60
    assert "The map is complete" in out and "repo: About the repo." in out
    assert "Pass `--out DIR` on every command" not in out and "--out " not in out
    assert "0 judgement tasks open, 0 blocked" in out
    assert f"`cbi build` writes the static viewer to {viewer}." in out
    assert "cbi show a/" in out and "cbi search y" in out
    assert "cbi show a/b/y.ts#y" in out and "cbi tests-for a/b/y.ts" in out
    assert "## Ingest" in out and "No test runner detected" in out
    for line in out.splitlines():  # every example command works
        cmd = line.split("  # ")[0].split()
        if cmd[:1] == ["cbi"] and cmd[1] in ("show", "search", "tests-for"):
            assert main(cmd[1:]) == 0, line
    assert main(["build"]) == 0 and viewer.is_file()
    code, out, _ = run(capsys, "prime")
    assert f"`cbi build` wrote the static viewer to {viewer}." in out


def test_prime_before_scan(make_repo, monkeypatch, capsys):
    monkeypatch.chdir(make_repo({"a.ts": "export {};\n"}))
    assert main(["init"]) == 0
    code, out, _ = run(capsys, "prime")
    assert code == 0 and "cbi scan" in out and "not mapped yet" in out

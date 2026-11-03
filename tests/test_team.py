"""Team mode: committed answers, clone, and a clean merge of answers.jsonl."""

import json
import sqlite3
import subprocess
from pathlib import Path

import pytest

from cbi import concepts, parts, store, tasks, team
from cbi.cli import main

MAP = {
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


def git(root, *args, check=True):
    return subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@example.com",
         "-c", "commit.gpgsign=false", *args],
        cwd=root, check=check, capture_output=True, text=True,
    )


def answer_files(capsys, tmp_path):
    for task in run_json(capsys, "tasks", "--kind", "summarise-files"):
        brief = run_json(capsys, "task", task["id"])
        body = {"input_hash": brief["input_hash"],
                "files": [{"path": f["path"], "summary": f"About {f['path']}."} for f in brief["files"]]}
        code, _, err = submit(capsys, tmp_path, task["id"], body)
        assert code == 0, err


def concepts_answer(brief):
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


def answer_all(capsys, tmp_path):
    for _ in range(12):
        open_tasks = run_json(capsys, "tasks")
        if not open_tasks:
            return
        for task in open_tasks:
            brief = run_json(capsys, "task", task["id"])
            kind = task["kind"]
            if kind == "summarise-files":
                body = {"input_hash": brief["input_hash"],
                        "files": [{"path": f["path"], "summary": f"About {f['path']}."} for f in brief["files"]]}
            elif kind == "confirm-structure":
                body = {"input_hash": brief["input_hash"], "deployables": [], "packages": []}
            elif kind in ("summarise-group", "summarise-workspace", "summarise-deployable"):
                body = {"input_hash": brief["input_hash"], "summary": f"About {kind}."}
            elif kind == "define-concepts":
                body = concepts_answer(brief)
            else:
                raise AssertionError(kind)
            code, _, err = submit(capsys, tmp_path, task["id"], body)
            assert code == 0, (kind, err)
    raise AssertionError(run_json(capsys, "tasks"))


def commit(root, message, paths):
    git(root, "add", "--", *paths)
    git(root, "commit", "-m", message)


def judgement_paths(root):
    names = [".gitattributes"]
    for name in team.JUDGEMENT:
        if (root / ".cbi" / name).is_file():
            names.append(f".cbi/{name}")
    return names


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def node_summary(root, path):
    conn = sqlite3.connect(root / ".cbi" / "model.db")
    try:
        return conn.execute("SELECT summary FROM nodes WHERE path = ?", (path,)).fetchone()[0]
    finally:
        conn.close()


def test_existing_gitattributes_stays_in_the_map(make_repo, monkeypatch, capsys):
    root = make_repo({".gitattributes": "*.png binary\n", "a.py": "x = 1\n"}, name="repo")
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    assert main(["scan"]) == 0
    assert main(["team", "init"]) == 0
    ignore = (root / ".cbi" / "ignore").read_text().splitlines()
    assert ignore.count("/.cbi/") == 1
    assert "/.gitattributes" not in ignore
    text = (root / ".gitattributes").read_text()
    assert text.startswith("*.png binary\n")
    assert text.count(".cbi/answers.jsonl") == 1 and "merge=union" in text


def test_team_is_not_a_repo_command(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    code, _, err = run(capsys, "team", "init")
    assert code == 1 and "not inside a git repository" in err


def test_non_team_stays_ignored_and_does_not_import(make_repo, monkeypatch, capsys, tmp_path):
    root = make_repo({"a.py": "x = 1\n"}, name="repo")
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    assert main(["scan"]) == 0
    answer_files(capsys, tmp_path)
    assert not (root / ".cbi" / "answers.jsonl").exists()
    assert not (root / ".cbi" / "team.toml").exists()
    assert (root / ".cbi" / ".gitignore").read_text() == "*\n"
    assert git(root, "status", "--porcelain").stdout == ""

    conn = sqlite3.connect(root / ".cbi" / "model.db")
    try:
        blob = conn.execute("SELECT content_hash FROM nodes WHERE path = 'a.py'").fetchone()[0]
    finally:
        conn.close()  # Windows will not delete a database that still has a connection
    (root / ".cbi" / "answers.jsonl").write_text(json.dumps({
        "kind": "summarise-files", "key": blob, "protocol": 1, "answer": "Should not load.",
    }) + "\n")
    for suffix in ("", "-wal", "-shm"):
        (root / ".cbi" / f"model.db{suffix}").unlink(missing_ok=True)
    monkeypatch.setenv("CBI_CACHE_DIR", str(tmp_path / "empty-cache"))
    code, out, err = run(capsys, "scan")
    assert code == 0, err
    assert "0 judgement tasks open" not in out
    assert node_summary(root, "a.py") is None


def test_team_init_exports_and_does_not_commit(make_repo, monkeypatch, capsys, tmp_path):
    root = make_repo({"a.py": "x = 1\n", "b.py": "y = 2\n"}, name="repo")
    monkeypatch.chdir(root)
    main(["init"])
    main(["scan"])
    answer_files(capsys, tmp_path)
    head = git(root, "rev-parse", "HEAD").stdout.strip()
    code, out, err = run(capsys, "team", "init")
    assert code == 0, err
    assert git(root, "rev-parse", "HEAD").stdout.strip() == head
    assert "does not commit or push" in out
    assert "git add -- " in out and ".gitattributes" in out and ".cbi/answers.jsonl" in out
    assert "cbi check" in out and "uv tool install ." in out
    assert (root / ".cbi" / ".gitignore").read_text() == team.DERIVED_GITIGNORE
    assert (root / ".gitattributes").read_text() == team.ATTR_LINE
    ignore_text = (root / ".cbi" / "ignore").read_text()
    assert "/.cbi/" in ignore_text.splitlines() and "/.gitattributes" in ignore_text.splitlines()
    assert team.settings(root / ".cbi") == {"check": "fail", "brief_budget": parts.DEFAULT_BUDGET}
    found = rows(root / ".cbi" / "answers.jsonl")
    assert [row["kind"] for row in found] == ["summarise-files", "summarise-files"]
    assert found == sorted(found, key=lambda row: (row["kind"], row["key"]))
    assert {row["answer"] for row in found} == {"About a.py.", "About b.py."}
    assert all(row["protocol"] == tasks.PROTOCOL_VERSION for row in found)
    ignored = (".cbi/model.db", ".cbi/model.db-wal", ".cbi/viewer/index.html", ".cbi/refs/abc/model.db",
               ".cbi/reviews/x.md", ".cbi/history/index.json", ".cbi/ignore.local")
    visible = (".cbi/team.toml", ".cbi/answers.jsonl", ".cbi/structure.json", ".cbi/concepts.json",
               ".cbi/screens.json", ".cbi/ignore", ".cbi/.gitignore")
    for rel in ignored:
        assert git(root, "check-ignore", "-q", rel, check=False).returncode == 0, rel
    for rel in visible:
        assert git(root, "check-ignore", "-q", rel, check=False).returncode == 1, rel

    text = (root / ".cbi" / "answers.jsonl").read_text()
    first = json.loads(text.splitlines()[0])
    first["answer"] = "not the cache"
    historical = {"answer": "stale", "key": "0" * 40, "kind": "summarise-files", "protocol": 1}
    (root / ".cbi" / "answers.jsonl").write_text(
        "not json\n" + json.dumps(historical, sort_keys=True) + "\n"
        + json.dumps(first, sort_keys=True, separators=(",", ":")) + "\n" + text
    )
    assert main(["team", "init"]) == 0
    again = rows(root / ".cbi" / "answers.jsonl")
    assert "not json" not in (root / ".cbi" / "answers.jsonl").read_text()
    assert [row["answer"] for row in again if row["key"] == "0" * 40] == ["stale"]
    assert {row["answer"] for row in again if row["kind"] == "summarise-files" and row["key"] != "0" * 40} == {
        "About a.py.", "About b.py.",
    }
    keys = [(row["kind"], row["key"]) for row in again]
    assert keys == sorted(keys) and len(keys) == len(set(keys))

    kept = 'check = "warn"\nbrief_budget = 10\n'
    (root / ".cbi" / "team.toml").write_text(kept)
    attrs = (root / ".gitattributes").read_text()
    ignore_text = (root / ".cbi" / "ignore").read_text()
    code, out, _ = run(capsys, "team", "init")
    assert code == 0
    assert (root / ".cbi" / "team.toml").read_text() == kept
    assert (root / ".gitattributes").read_text() == attrs
    assert (root / ".cbi" / "ignore").read_text() == ignore_text
    assert attrs.count("linguist-generated=true") == 1 and "merge=union" in attrs
    assert "Kept .gitattributes" in out and "Kept .cbi/team.toml" in out and "Kept .cbi/ignore" in out
    assert team.settings(root / ".cbi") == {"check": "warn", "brief_budget": 10}
    (root / ".gitattributes").write_text("# keep\n.cbi/answers.jsonl linguist-generated=true\n")
    assert main(["team", "init"]) == 0
    replaced = (root / ".gitattributes").read_text()
    assert replaced.startswith("# keep\n")
    assert replaced.count(".cbi/answers.jsonl") == 1 and "merge=union" in replaced
    assert main(["init"]) == 0
    assert (root / ".cbi" / ".gitignore").read_text() == team.DERIVED_GITIGNORE


def test_team_init_removes_only_a_plain_root_cbi_ignore(make_repo, monkeypatch, capsys):
    root = make_repo({"a.py": "x = 1\n"}, name="ignored-team")
    (root / ".gitignore").write_text("keep-this\n.cbi/\n*.log\n")
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    code, out, err = run(capsys, "team", "init")
    assert code == 0, err
    assert (root / ".gitignore").read_text() == "keep-this\n*.log\n"
    assert "Removed '.cbi/' from .gitignore line 2" in out
    assert "git add -- .gitignore " in out
    assert git(root, "check-ignore", "--no-index", ".cbi/concepts.json", check=False).returncode == 1


def test_team_init_reports_other_ignore_rules_without_changing_them(make_repo, monkeypatch, capsys):
    root = make_repo({"a.py": "x = 1\n"}, name="pattern-team")
    original = "keep-this\n/.cbi/\n*.log\n"
    (root / ".gitignore").write_text(original)
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    code, out, err = run(capsys, "team", "init")
    assert code == 0, err
    assert (root / ".gitignore").read_text() == original
    assert ".cbi/concepts.json is ignored by .gitignore line 2 ('/.cbi/')" in out
    assert "Remove that rule" in out


def test_out_does_not_edit_the_repo(make_repo, monkeypatch, capsys, tmp_path):
    root = make_repo({"a.py": "x = 1\n"}, name="repo")
    monkeypatch.chdir(root)
    main(["init"])
    side = tmp_path / "side-model"
    code, out, err = run(capsys, "team", "init", "--out", str(side))
    assert code == 0, err
    assert not (root / ".gitattributes").exists()
    assert not (root / ".cbi" / "team.toml").exists()
    assert (root / ".cbi" / ".gitignore").read_text() == "*\n"
    assert (side / "team.toml").is_file()
    assert (side / ".gitignore").read_text() == team.DERIVED_GITIGNORE
    side_ignore = (side / "ignore").read_text().splitlines()
    assert "/.cbi/" in side_ignore and "/.gitattributes" not in side_ignore
    assert "not .cbi/" in out


def test_import_skips_bad_rows(tmp_path):
    out = tmp_path / "model"
    out.mkdir()
    (out / "team.toml").write_text(team.TEMPLATE)
    (out / "answers.jsonl").write_text(
        json.dumps({"answer": "kept", "key": "aaa", "kind": "summarise-files", "protocol": 1}) + "\n"
        "not json\n"
        + json.dumps({"answer": "old", "key": "bbb", "kind": "summarise-files", "protocol": 99}) + "\n"
        + json.dumps({"answer": {"summary": "group"}, "key": "ccc", "kind": "summarise-group", "protocol": 1}) + "\n"
        + json.dumps({"answer": "", "key": "ddd", "kind": "summarise-files", "protocol": 1}) + "\n"
    )
    conn = sqlite3.connect(":memory:")
    tasks.attach_cache(conn)
    assert team.import_answers(conn, out) == 2
    assert conn.execute("SELECT content_hash, summary FROM cache.file_summaries").fetchall() == [("aaa", "kept")]
    stored = json.loads(conn.execute("SELECT answer FROM cache.summary_answers").fetchone()[0])
    assert stored == {"summary": "group"}
    assert team.import_answers(conn, tmp_path) == 0


def test_changed_answers_file_is_imported(make_repo, monkeypatch, capsys, tmp_path):
    root = make_repo({"a.py": "x = 1\n"}, name="repo")
    monkeypatch.chdir(root)
    main(["init"])
    main(["scan"])
    answer_files(capsys, tmp_path)
    assert main(["team", "init"]) == 0
    code, out, err = run(capsys, "scan")
    assert code == 0, err
    assert "no changes" not in out
    code, out, err = run(capsys, "scan")
    assert code == 0, err
    assert "no changes" in out

    path = root / ".cbi" / "answers.jsonl"
    edited = rows(path)
    edited[0]["answer"] = "Reworded summary."
    path.write_text("".join(json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n" for row in edited))
    code, out, err = run(capsys, "scan")
    assert code == 0, err
    assert "no changes" not in out
    assert node_summary(root, "a.py") == "Reworded summary."
    assert run_json(capsys, "tasks", "--kind", "summarise-files") == []
    code, out, err = run(capsys, "scan")
    assert code == 0 and "no changes" in out


def test_clone_has_no_open_tasks_and_the_same_concept_map(make_repo, monkeypatch, capsys, tmp_path):
    root = make_repo(MAP, name="repo")
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    assert main(["scan"]) == 0
    answer_all(capsys, tmp_path)
    assert run_json(capsys, "tasks") == []
    assert main(["build"]) == 0
    original = (root / ".cbi" / "viewer" / "data" / "concepts.js").read_text()
    assert "Core" in original and "App" in original
    code, _, err = run(capsys, "team", "init")
    assert code == 0, err
    commit(root, "commit the map", judgement_paths(root))
    assert git(root, "status", "--porcelain").stdout == ""
    assert not git(root, "ls-files", ".cbi/model.db").stdout.strip()

    clone = tmp_path / "nested" / "repo"
    git(root, "clone", "--quiet", str(root), str(clone))
    assert not (clone / ".cbi" / "model.db").exists()
    assert (clone / ".cbi" / "answers.jsonl").is_file()
    monkeypatch.setenv("CBI_CACHE_DIR", str(tmp_path / "clone-cache"))
    monkeypatch.chdir(clone)
    code, out, err = run(capsys, "scan")
    assert code == 0, err
    assert "0 judgement tasks open, 0 blocked" in out
    assert node_summary(clone, "a.ts") == "About a.ts."
    assert main(["build"]) == 0
    assert (clone / ".cbi" / "viewer" / "data" / "concepts.js").read_text() == original


def test_scan_prefers_a_newer_committed_concept_answer(make_repo, monkeypatch, capsys, tmp_path):
    seed = make_repo(MAP, name="concept-seed")
    monkeypatch.chdir(seed)
    assert main(["init"]) == 0
    assert main(["scan"]) == 0
    answer_all(capsys, tmp_path)
    assert main(["team", "init"]) == 0
    commit(seed, "base map", judgement_paths(seed))

    origin = tmp_path / "concept-origin.git"
    local = tmp_path / "concept-local"
    refresh = tmp_path / "concept-refresh"
    git(tmp_path, "clone", "--quiet", "--bare", str(seed), str(origin))
    git(tmp_path, "clone", "--quiet", str(origin), str(local))
    git(tmp_path, "clone", "--quiet", str(origin), str(refresh))

    monkeypatch.chdir(local)
    assert main(["scan"]) == 0
    assert run_json(capsys, "tasks", "--kind", "define-concepts") == []
    conn = sqlite3.connect(local / ".cbi" / "model.db")
    local_task = conn.execute("SELECT id FROM tasks WHERE kind = 'define-concepts'").fetchone()[0]
    conn.close()
    local_brief = run_json(capsys, "task", local_task)
    local_answer = concepts_answer(local_brief)
    local_answer["summary"] = "The locally accepted application map."
    code, _, err = submit(capsys, tmp_path, local_task, local_answer)
    assert code == 0, err
    git(local, "checkout", "--", ".cbi/answers.jsonl", ".cbi/concepts.json")
    assert git(local, "status", "--porcelain").stdout == ""

    monkeypatch.chdir(refresh)
    (refresh / "b.ts").write_text((refresh / "b.ts").read_text() + "// revised\n")
    assert main(["scan"]) == 0
    answer_files(capsys, tmp_path)
    conn = sqlite3.connect(refresh / ".cbi" / "model.db")
    task_id = conn.execute("SELECT id FROM tasks WHERE kind = 'define-concepts'").fetchone()[0]
    conn.close()
    brief = run_json(capsys, "task", task_id)
    newer = concepts_answer(brief)
    newer["summary"] = "The revised application map."
    newer["concepts"][0]["name"] = "Foundation"
    code, _, err = submit(capsys, tmp_path, task_id, newer)
    assert code == 0, err
    commit(refresh, "revise map", ["b.ts", ".cbi/answers.jsonl", ".cbi/concepts.json"])
    git(refresh, "push", "--quiet", "origin", "main")

    monkeypatch.chdir(local)
    git(local, "pull", "--quiet", "--ff-only")
    code, out, err = run(capsys, "scan")
    assert code == 0, err
    assert "0 judgement tasks open, 0 blocked" in out
    assert run_json(capsys, "tasks", "--kind", "define-concepts") == []
    assert json.loads((local / ".cbi" / "concepts.json").read_text())["summary"] == "The revised application map."


def test_an_unrelated_committed_answer_does_not_refresh_the_concept_snapshot(
        make_repo, monkeypatch, capsys, tmp_path):
    root = make_repo(MAP, name="unrelated-answer")
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    assert main(["scan"]) == 0
    answer_all(capsys, tmp_path)
    assert main(["team", "init"]) == 0
    commit(root, "base map", judgement_paths(root))
    (root / "b.ts").write_text((root / "b.ts").read_text() + "// revised\n")
    assert main(["scan"]) == 0
    assert len(run_json(capsys, "tasks", "--kind", "define-concepts")) == 1
    answer_files(capsys, tmp_path)
    commit(root, "update file summary", ["b.ts", ".cbi/answers.jsonl"])

    assert main(["scan"]) == 0
    assert len(run_json(capsys, "tasks", "--kind", "define-concepts")) == 1


def test_two_branches_merge_answers_without_a_conflict(make_repo, monkeypatch, capsys, tmp_path):
    root = make_repo({"a.py": "def a():\n    return 1\n", "b.py": "def b():\n    return 2\n"}, name="repo")
    monkeypatch.chdir(root)
    main(["init"])
    main(["scan"])
    answer_files(capsys, tmp_path)
    assert main(["team", "init"]) == 0
    commit(root, "base map", ["a.py", "b.py", *judgement_paths(root)])
    base_lines = (root / ".cbi" / "answers.jsonl").read_text().splitlines()

    def add_file(branch, name):
        git(root, "checkout", "-B", branch, "main")
        (root / name).write_text(f"def {Path(name).stem}():\n    return 1\n")
        git(root, "add", "--", name)
        assert main(["scan"]) == 0
        answer_files(capsys, tmp_path)
        git(root, "add", "--", name, ".cbi/answers.jsonl")
        git(root, "commit", "-m", f"add {name}")

    add_file("add-c", "c.py")
    add_file("add-d", "d.py")
    git(root, "checkout", "main")
    assert git(root, "merge", "--no-edit", "add-c").returncode == 0
    merged = git(root, "merge", "--no-edit", "add-d", check=False)
    assert merged.returncode == 0, merged.stdout + merged.stderr
    text = (root / ".cbi" / "answers.jsonl").read_text()
    assert "<<<<<<<" not in text
    found = rows(root / ".cbi" / "answers.jsonl")
    assert {row["answer"] for row in found} >= {"About a.py.", "About b.py.", "About c.py.", "About d.py."}
    assert all(line in text.splitlines() for line in base_lines)
    # union keeps both added lines and does not sort them. The next export does.
    assert main(["team", "init"]) == 0
    again = rows(root / ".cbi" / "answers.jsonl")
    keys = [(row["kind"], row["key"]) for row in again]
    assert keys == sorted(keys) and len(keys) == len(set(keys))
    assert {row["answer"] for row in again} >= {"About a.py.", "About b.py.", "About c.py.", "About d.py."}


def test_submit_seeds_fresh_cache_before_refreshing_parents(make_repo, monkeypatch, capsys, tmp_path):
    root = make_repo({"stable/core.py": "def core():\n    return 1\n",
                      "changed/app.py": "def app():\n    return 2\n",
                      "package.json": '{"name":"demo","bin":"stable/core.py"}'})
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    assert main(["scan"]) == 0

    def complete():
        for _ in range(20):
            pending = run_json(capsys, "tasks")
            if not pending:
                return
            for task in pending:
                b = run_json(capsys, "task", task["id"])
                body = {"input_hash": b["input_hash"]}
                if b["kind"] == "summarise-files":
                    body["files"] = [{"path": f["path"], "summary": "Summary of " + f["path"]} for f in b["files"]]
                elif b["kind"] == "confirm-structure":
                    body.update(deployables=[], packages=[])
                elif b["kind"] == "define-concepts":
                    body.update(summary="Demo.", concepts=[{"id": "core", "name": "Core",
                        "role": "core", "summary": "Demo logic.",
                        "files": [f["path"] for f in b["files"]]}], externals=[], relationships=[])
                else:
                    body["summary"] = "Summary of " + b["node"]["name"]
                code, _, err = submit(capsys, tmp_path, task["id"], body)
                assert code == 0, err
        raise AssertionError("tasks did not finish")

    complete()
    assert main(["team", "init"]) == 0
    (root / "changed/app.py").write_text("def app():\n    return 3\n")
    assert main(["scan"]) == 0
    path = root / ".cbi/model.db"
    with sqlite3.connect(path) as conn:
        accepted = conn.execute("SELECT id FROM tasks WHERE state = 'done' AND kind IN "
                                "('summarise-group', 'summarise-deployable')").fetchall()
    assert accepted
    task = run_json(capsys, "tasks", "--kind", "summarise-files")[0]
    b = run_json(capsys, "task", task["id"])
    body = {"input_hash": b["input_hash"], "files": [
        {"path": f["path"], "summary": "Updated " + f["path"]} for f in b["files"]]}
    monkeypatch.setenv("CBI_CACHE_DIR", str(tmp_path / "fresh-cache"))
    code, _, err = submit(capsys, tmp_path, task["id"], body)
    assert code == 0, err
    with sqlite3.connect(path) as conn:
        for (task_id,) in accepted:
            assert conn.execute("SELECT state FROM tasks WHERE id = ?", (task_id,)).fetchone() == ("done",)


def test_interleaved_branch_submits_keep_their_own_shared_answers(make_repo, monkeypatch, capsys, tmp_path):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    first = make_repo(MAP)
    monkeypatch.chdir(first)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    answer_all(capsys, tmp_path)
    assert main(["team", "init"]) == 0
    commit(first, "team fixture", judgement_paths(first))
    git(first, "checkout", "-q", "-b", "branch-a")
    second = tmp_path / "other"
    git(first, "clone", "--quiet", str(first), str(second))
    git(second, "checkout", "-q", "-b", "branch-b")
    shared_key = next(row["key"] for row in rows(first / ".cbi/answers.jsonl")
                      if row["kind"] == "summarise-files" and row["answer"] == "About a.ts.")
    submissions = {}
    for root, label in ((first, "A"), (second, "B")):
        answers = rows(root / ".cbi/answers.jsonl")
        for row in answers:
            if row["kind"] == "summarise-files" and row["key"] == shared_key:
                row["answer"] = f"Branch {label} core summary."
        (root / ".cbi/answers.jsonl").write_text("".join(json.dumps(row) + "\n" for row in answers))
        (root / "b.ts").write_text(MAP["b.ts"] + f"// branch {label}\n")
        monkeypatch.chdir(root)
        assert main(["init"]) == 0 and main(["scan"]) == 0
        task = run_json(capsys, "tasks", "--kind", "summarise-files")[0]
        brief = run_json(capsys, "task", task["id"])
        body = {"input_hash": brief["input_hash"], "files": [
            {"path": f["path"], "summary": f"Branch {label} caller summary."} for f in brief["files"]]}
        submissions[label] = (root, task["id"], json.dumps(body))

    b_ready = threading.Event()
    a_validating = threading.Event()
    b_finished_or_contended = threading.Event()
    local = threading.local()
    validate = tasks._validated
    is_busy = store.is_busy

    def interleaved_validation(conn, task_id, text):
        if local.branch == "A":
            a_validating.set()
            assert b_finished_or_contended.wait(30)
        return validate(conn, task_id, text)

    def observe_contention(err):
        busy = is_busy(err)
        if busy and local.branch == "B":
            b_finished_or_contended.set()
        return busy

    monkeypatch.setattr(tasks, "_validated", interleaved_validation)
    monkeypatch.setattr(store, "is_busy", observe_contention)

    def worker(label):
        local.branch = label
        root, task_id, text = submissions[label]
        conn = store.open_db(root / ".cbi/model.db")
        try:
            tasks.attach_cache(conn)
            if label == "B":
                conn.execute("PRAGMA busy_timeout = 1000")
                b_ready.set()
                assert a_validating.wait(30)
            else:
                assert b_ready.wait(30)
            return tasks.submit(conn, task_id, text, root, root / ".cbi")
        finally:
            conn.close()
            if label == "B":
                b_finished_or_contended.set()

    # A pauses after importing. B either completes (the old unprotected gap)
    # or encounters A's cache lock, allowing A to finish before B retries.
    with ThreadPoolExecutor(max_workers=2) as pool:
        b = pool.submit(worker, "B")
        a = pool.submit(worker, "A")
        assert "accepted" in a.result(timeout=45)
        assert "accepted" in b.result(timeout=45)
    for root, label in ((first, "A"), (second, "B")):
        exported = next(row["answer"] for row in rows(root / ".cbi/answers.jsonl")
                        if row["kind"] == "summarise-files" and row["key"] == shared_key)
        assert exported == f"Branch {label} core summary."


def test_rejected_submit_rolls_back_its_team_import(make_repo, monkeypatch):
    import pytest
    from cbi.files import blob_id

    source = "def core():\n    return 1\n"
    root = make_repo({"core.py": source})
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    assert main(["team", "init"]) == 0
    key = blob_id(source.encode())
    row = {"kind": "summarise-files", "key": key, "protocol": tasks.PROTOCOL_VERSION,
           "answer": "Branch-specific answer."}
    out = root / ".cbi"
    (out / "answers.jsonl").write_text(json.dumps(row) + "\n")
    conn = store.open_db(out / "model.db")
    try:
        tasks.attach_cache(conn)
        conn.execute("INSERT INTO cache.file_summaries VALUES (?, ?, ?)",
                     (key, tasks.PROTOCOL_VERSION, "Existing cache answer."))
        conn.commit()
        task_id = conn.execute("SELECT id FROM tasks WHERE kind = 'summarise-files'").fetchone()[0]
        with pytest.raises(tasks.AnswerError):
            tasks.submit(conn, task_id, "{}", root, out)
        assert conn.execute("SELECT summary FROM cache.file_summaries WHERE content_hash = ?",
                            (key,)).fetchone() == ("Existing cache answer.",)
        assert rows(out / "answers.jsonl") == [row]
    finally:
        conn.close()


def test_superseded_concept_answer_cannot_return_after_source_reverts(make_repo, monkeypatch, capsys, tmp_path):
    root = make_repo(MAP, name="superseded-map")
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    assert main(["scan"]) == 0
    answer_all(capsys, tmp_path)
    assert main(["team", "init"]) == 0
    conn = sqlite3.connect(root / ".cbi" / "model.db")
    task_id = conn.execute("SELECT id FROM tasks WHERE kind = 'define-concepts'").fetchone()[0]
    conn.close()
    baseline = run_json(capsys, "task", task_id)
    assert submit(capsys, tmp_path, task_id, concepts_answer(baseline))[0] == 0
    original = (root / "b.ts").read_text()
    (root / "b.ts").write_text(original + "// changed\n")
    assert main(["scan"]) == 0
    answer_files(capsys, tmp_path)
    conn = sqlite3.connect(root / ".cbi" / "model.db")
    task_id = conn.execute("SELECT id FROM tasks WHERE kind = 'define-concepts'").fetchone()[0]
    conn.close()
    brief = run_json(capsys, "task", task_id)
    answer = concepts_answer(brief)
    answer["concepts"][0]["name"] = "Revised foundation"
    assert submit(capsys, tmp_path, task_id, answer)[0] == 0
    (root / "b.ts").write_text(original)
    (root / ".cbi" / "concepts.json").unlink()
    # A fresh cache must respect retirement persisted in the team answer file.
    monkeypatch.setenv("CBI_CACHE_DIR", str(tmp_path / "fresh-retirement-cache"))
    assert main(["scan"]) == 0
    assert not (root / ".cbi" / "concepts.json").exists()
    assert len(run_json(capsys, "tasks", "--kind", "define-concepts")) == 1
    assert main(["prime"]) == 0
    assert not (root / ".cbi" / "concepts.json").exists()


def test_supersession_survives_union_merge_order():
    for generation in (None, 5):
        live = team._canon("define-concepts", "old", tasks.PROTOCOL_VERSION, {"summary": "Old map."})
        if generation is not None:
            live["generation"] = generation
        retired = {**live, "superseded_by": "new"}
        for records in ([live, retired], [retired, live]):
            parsed = team._parse("\n".join(json.dumps(row) for row in records))
            assert parsed[("define-concepts", "old")]["superseded_by"] == "new"


def test_retired_concept_hash_is_not_restored_from_repopulated_cache(make_repo, monkeypatch, capsys, tmp_path):
    from cbi import concepts

    root = make_repo(MAP, name="retired-cache")
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    assert main(["scan"]) == 0
    answer_all(capsys, tmp_path)
    assert main(["team", "init"]) == 0
    out = root / ".cbi"
    conn = store.open_db(out / "model.db")
    tasks.attach_cache(conn)
    task_id = conn.execute("SELECT id FROM tasks WHERE kind = 'define-concepts'").fetchone()[0]
    conn.close()
    baseline = run_json(capsys, "task", task_id)
    old = concepts_answer(baseline)
    assert submit(capsys, tmp_path, task_id, old)[0] == 0
    original = (root / "b.ts").read_text()
    (root / "b.ts").write_text(original + "// revised\n")
    assert main(["scan"]) == 0
    answer_files(capsys, tmp_path)
    brief = run_json(capsys, "task", task_id)
    replacement = concepts_answer(brief)
    replacement["summary"] = "The replacement map."
    assert submit(capsys, tmp_path, task_id, replacement)[0] == 0
    (root / "b.ts").write_text(original)
    (out / "concepts.json").unlink()
    assert main(["scan"]) == 0
    assert not (out / "concepts.json").exists()

    # A historical cache user can publish this old input again after the import.
    key = ("define-concepts", baseline["input_hash"])
    retired = team._parse((out / "answers.jsonl").read_text())[key]
    conn = store.open_db(out / "model.db")
    tasks.attach_cache(conn)
    with conn:
        stale = {**concepts._body(old), "summary": "A stale cached application."}
        conn.execute("INSERT OR REPLACE INTO cache.summary_answers (input_hash, answer) VALUES (?, ?)",
                     (baseline["input_hash"], json.dumps(stale)))
        concepts.refresh(conn, out, root)
        assert key not in team._collect(conn)
        team.sync(conn, out)
    conn.close()
    assert team._parse((out / "answers.jsonl").read_text())[key] == retired
    assert not (out / "concepts.json").exists()
    reviewed = concepts_answer(run_json(capsys, "task", task_id))
    reviewed["summary"] = "The explicitly reviewed map."
    assert submit(capsys, tmp_path, task_id, reviewed)[0] == 0
    assert json.loads((out / "concepts.json").read_text())["summary"] == reviewed["summary"]


@pytest.mark.parametrize("matching_projection", [False, True])
def test_reaccepted_concept_answer_survives_older_merged_tombstone(make_repo, monkeypatch, capsys, tmp_path, matching_projection):
    root = make_repo(MAP, name="reaccepted-map")
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    assert main(["scan"]) == 0
    answer_all(capsys, tmp_path)
    assert main(["team", "init"]) == 0
    out = root / ".cbi"
    conn = sqlite3.connect(out / "model.db")
    task_id = conn.execute("SELECT id FROM tasks WHERE kind = 'define-concepts'").fetchone()[0]
    conn.close()
    baseline = run_json(capsys, "task", task_id)
    assert submit(capsys, tmp_path, task_id, concepts_answer(baseline))[0] == 0
    original = (root / "b.ts").read_text()
    (root / "b.ts").write_text(original + "// revised\n")
    assert main(["scan"]) == 0
    answer_files(capsys, tmp_path)
    replacement = concepts_answer(run_json(capsys, "task", task_id))
    replacement["summary"] = "The replacement application."
    assert submit(capsys, tmp_path, task_id, replacement)[0] == 0
    path = out / "answers.jsonl"
    old_key = ("define-concepts", baseline["input_hash"])
    retired = team._parse(path.read_text())[old_key]

    (root / "b.ts").write_text(original)
    assert main(["scan"]) == 0
    reviewed = concepts_answer(run_json(capsys, "task", task_id))
    reviewed["summary"] = "The explicitly reviewed application."
    assert reviewed["input_hash"] == baseline["input_hash"]
    if matching_projection:
        body = concepts._body(reviewed)
        (out / "concepts.json").write_text(json.dumps(body, indent=2) + "\n")
        conn = store.open_db(out / "model.db")
        tasks.attach_cache(conn)
        with conn:
            conn.execute("INSERT OR REPLACE INTO cache.summary_answers (input_hash, answer) VALUES (?, ?)",
                         (baseline["input_hash"], json.dumps(body)))
        conn.close()
    assert submit(capsys, tmp_path, task_id, reviewed)[0] == 0
    accepted = team._parse(path.read_text())[old_key]
    other_rows = {key: row for key, row in team._parse(path.read_text()).items() if key != old_key}

    for duplicate_rows in ([retired, accepted], [accepted, retired]):
        path.write_text(team._dump(other_rows) + "".join(json.dumps(row) + "\n" for row in duplicate_rows))
        assert team.committed_answer(out, *old_key, tasks.PROTOCOL_VERSION) == accepted["answer"]
        assert not team.answer_superseded(out, *old_key)
        conn = store.open_db(out / "model.db")
        tasks.attach_cache(conn)
        with conn:
            team.import_answers(conn, out)
            restored = json.loads(conn.execute(
                "SELECT answer FROM cache.summary_answers WHERE input_hash = ?", (old_key[1],)
            ).fetchone()[0])
            assert restored == accepted["answer"]
            assert team._collect(conn)[old_key]["generation"] == accepted["generation"]
            team.sync(conn, out)
        conn.close()
        assert team._parse(path.read_text())[old_key] == accepted
    assert accepted["generation"] > retired["generation"]
    conn = store.open_db(out / "model.db")
    tasks.attach_cache(conn)
    with conn:
        conn.execute("UPDATE cache.summary_answers SET answer = ? WHERE input_hash = ?",
                     (json.dumps(concepts._body(concepts_answer(baseline))), old_key[1]))
        assert old_key not in team._collect(conn)
        team.sync(conn, out)
    conn.close()
    assert team._parse(path.read_text())[old_key] == accepted
    (out / "concepts.json").unlink()
    conn = store.open_db(out / "model.db")
    tasks.attach_cache(conn)
    with conn:
        concepts.apply(conn, None)
        concepts.refresh(conn, out, root)
    conn.close()
    assert json.loads((out / "concepts.json").read_text()) == accepted["answer"]


def _accept_document_key(conn, out, key, summary):
    with conn:
        conn.execute("INSERT OR REPLACE INTO cache.summary_answers (input_hash, answer) VALUES (?, ?)",
                     (key, json.dumps({"summary": summary})))
        team.supersede(conn, out, "define-concepts", key)


def _branched_document_answers(make_repo, tmp_path, branch_keys, higher_generation=False):
    root = make_repo({"core.py": "def run():\n    return 1\n"}, name="concurrent-maps")
    out = root / ".cbi"
    out.mkdir()
    (out / "team.toml").write_text(team.TEMPLATE)
    conn = store.open_db(out / "model.db")
    tasks.attach_cache(conn)
    _accept_document_key(conn, out, "input-a", "The first map.")
    _accept_document_key(conn, out, "input-b", "The second map.")
    baseline = (out / "answers.jsonl").read_text()
    branches = []
    for index, key in enumerate(branch_keys):
        branch = tmp_path / f"branch-{index}"
        branch.mkdir()
        (branch / "team.toml").write_text(team.TEMPLATE)
        (branch / "answers.jsonl").write_text(baseline)
        side = store.open_db(branch / "model.db")
        tasks.attach_cache(side)
        if higher_generation and index == 1:
            _accept_document_key(side, branch, key, "An intermediate reviewed map.")
        _accept_document_key(side, branch, key, f"The reviewed map from branch {index}.")
        branches.append((branch / "answers.jsonl").read_text())
        side.close()
    return root, out, conn, branches


@pytest.mark.parametrize("higher_generation", [False, True])
@pytest.mark.parametrize("reverse", [False, True])
def test_concurrent_acceptances_are_not_retired_by_unseen_branch_events(make_repo, tmp_path, higher_generation, reverse):
    _root, out, conn, branches = _branched_document_answers(
        make_repo, tmp_path, ["input-a", "input-b"], higher_generation)
    try:
        for left, right in [branches[::-1] if reverse else branches]:
            (out / "answers.jsonl").write_text(left + right)
            assert team.committed_answer(out, "define-concepts", "input-a", tasks.PROTOCOL_VERSION) == {
                "summary": "The reviewed map from branch 0.",
            }
            assert team.committed_answer(out, "define-concepts", "input-b", tasks.PROTOCOL_VERSION) == {
                "summary": "The reviewed map from branch 1.",
            }
            with conn:
                team.import_answers(conn, out)
                team.sync(conn, out)
            assert all(not row.get("superseded_by") for row in team._parse((out / "answers.jsonl").read_text()).values())
    finally:
        conn.close()


def test_same_key_concurrent_acceptances_are_preserved_and_reported(make_repo, tmp_path):
    from cbi import check

    root, out, conn, branches = _branched_document_answers(make_repo, tmp_path, ["input-b", "input-b"])
    key = ("define-concepts", "input-b")
    try:
        for left, right in (branches, branches[::-1]):
            (out / "answers.jsonl").write_text(left + right)
            row = team._parse((out / "answers.jsonl").read_text())[key]
            assert {candidate["answer"]["summary"] for candidate in row["conflicts"]} == {
                "The reviewed map from branch 0.", "The reviewed map from branch 1.",
            }
            assert team.committed_answer(out, *key, tasks.PROTOCOL_VERSION) is None
            assert team.answer_superseded(out, *key)
            with conn:
                team.import_answers(conn, out)
                assert conn.execute("SELECT 1 FROM cache.summary_answers WHERE input_hash = ?", (key[1],)).fetchone() is None
                findings = check._stale_findings(conn, root, out)
                assert any(item["file"] == ".cbi/answers.jsonl" and "conflicting" in item["message"]
                           and "define-concepts" in item["message"] and "input-b" in item["message"] for item in findings)
                team.sync(conn, out)
            assert team._parse((out / "answers.jsonl").read_text())[key]["conflicts"] == row["conflicts"]
            _accept_document_key(conn, out, key[1], "The explicitly resolved map.")
            assert team.committed_answer(out, *key, tasks.PROTOCOL_VERSION) == {"summary": "The explicitly resolved map."}
            # Previously merged alternatives cannot undo their explicit resolution.
            resolved = (out / "answers.jsonl").read_text()
            (out / "answers.jsonl").write_text(resolved + left + right)
            assert team.committed_answer(out, *key, tasks.PROTOCOL_VERSION) == {"summary": "The explicitly resolved map."}
            team._store(out, {key: team._canon(*key, tasks.PROTOCOL_VERSION, {"summary": "A stale cache copy."})})
            assert team.committed_answer(out, *key, tasks.PROTOCOL_VERSION) == {"summary": "The explicitly resolved map."}
    finally:
        conn.close()

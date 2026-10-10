"""Team mode: committed answers, clone, and a clean merge of answers.jsonl."""

import json
import sqlite3
import subprocess
from pathlib import Path

from cbi import parts, store, tasks, team
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

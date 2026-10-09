"""Architecture history points, projection, output and incremental reuse."""

import json
import sqlite3
import subprocess

from cbi import history, store
from cbi.cli import main


def git(root, *args):
    return subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@example.com",
         "-c", "commit.gpgsign=false", *args], cwd=root, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def commit(root, message, **files):
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", message)
    return git(root, "rev-parse", "HEAD")


def concept_map(paths):
    return {
        "summary": "Fixture.",
        "concepts": [{"id": "app", "name": "App", "summary": "The app.",
                      "role": "app", "files": paths}],
        "externals": [], "relationships": [],
    }


def test_points_prefer_merges_and_fall_back_to_first_parent(make_repo):
    plain = make_repo({"a.py": "x = 1\n"}, name="plain")
    second = commit(plain, "feature (#12)", **{"b.py": "y = 2\n"})
    points = history.history_points(plain, since="2000-01-01")
    assert [point["sha"] for point in points][-1] == second
    assert points[-1]["pr"] == 12

    merged = make_repo({"a.py": "x = 1\n"}, name="merged")
    git(merged, "checkout", "-q", "-b", "feature")
    commit(merged, "inside branch", **{"b.py": "y = 2\n"})
    git(merged, "checkout", "-q", "main")
    git(merged, "merge", "--no-ff", "-m", "Merge pull request #7 from feature", "feature")
    points = history.history_points(merged, since="2000-01-01")
    assert len(points) == 1 and points[0]["pr"] == 7


def test_project_concepts_keeps_move_and_marks_folder_guess(tmp_path):
    current = sqlite3.connect(tmp_path / "current.db")
    point = sqlite3.connect(tmp_path / "point.db")
    for conn in (current, point):
        conn.executescript(
            "CREATE TABLE nodes (id TEXT, path TEXT, content_hash TEXT, kind TEXT);"
            "CREATE TABLE edges (src TEXT, dst TEXT, kind TEXT);"
        )
    current.executemany("INSERT INTO nodes VALUES (?, ?, ?, 'file')", [
        ("w:new/core.py", "new/core.py", "same",),
        ("w:old/near.py", "old/near.py", "near",),
    ])
    current.executemany("INSERT INTO edges VALUES (?, ?, 'owns')", [
        ("core", "w:new/core.py"), ("app", "w:old/near.py"),
    ])
    point.executemany("INSERT INTO nodes VALUES (?, ?, ?, 'file')", [
        ("w:old/core.py", "old/core.py", "same",),
        ("w:old/near.py", "old/near.py", "near",),
        ("w:old/gone.py", "old/gone.py", "gone",),
    ])
    document = {
        "summary": "Fixture.",
        "concepts": [
            {"id": "core", "name": "Core", "summary": "Core.", "role": "core", "files": ["new/core.py"]},
            {"id": "app", "name": "App", "summary": "App.", "role": "app", "files": ["old/near.py"]},
            {"id": "vanished", "name": "Gone", "summary": "Gone.", "role": "core", "files": ["gone/now.py"]},
        ], "externals": [], "relationships": [],
    }
    projected, provisional = history.project_concepts(document, point, current)
    leaves = {item["id"]: item["files"] for item in projected["concepts"]}
    assert leaves["core"] == ["old/core.py"]
    assert "vanished" not in leaves
    assert "old/gone.py" in leaves["app"]
    assert provisional == [{"file_id": "w:old/gone.py", "path": "old/gone.py",
                            "concept_id": "app", "by": "folder"}]


def test_history_cli_writes_markdown_and_reuses_point_models(make_repo, monkeypatch, capsys):
    root = make_repo({"a.py": "def a():\n    return 1\n"}, name="history-repo")
    commit(root, "add b (#2)", **{"b.py": "def b():\n    return 2\n"})
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    (root / ".cbi" / "concepts.json").write_text(json.dumps(concept_map(["a.py", "b.py"])))
    assert main(["scan"]) == 0
    capsys.readouterr()

    assert main(["history", "--since", "2000-01-01", "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["entries"]
    mtimes = {path: path.stat().st_mtime_ns for path in (root / ".cbi" / "refs").glob("*/model.db")}

    assert main(["history", "--since", "2000-01-01", "--write"]) == 0
    written = root / ".cbi" / "CHANGELOG-ARCHITECTURE.md"
    assert written.is_file()
    entries = history.select(history.build_history(root, root / ".cbi", "2000-01-01"))
    assert written.read_text() == history.render(entries, "markdown")
    assert mtimes == {path: path.stat().st_mtime_ns for path in mtimes}
    assert main(["build", "--history"]) == 0
    script = (root / ".cbi" / "viewer" / "data" / "history.js").read_text()
    prefix = 'cbiLoad("history", '
    timeline = json.loads(script[len(prefix):-3])
    assert len(timeline["entries"]) == len(entries)
    latest = timeline["entries"][-1]
    assert latest["model"]["concepts"]
    assert latest["diff"]["changes"]["groups"]
    assert "cbi diff" not in latest["text"]
    assert (root / ".cbi" / "viewer" / "index.html").read_text().find("data/history.js") > 0
    conn = store.read_only(next(iter(mtimes)))
    try:
        assert store.get_meta(conn, "commit")
    finally:
        conn.close()


def test_narrative_uses_summarise_change_and_appears_in_outputs(make_repo, monkeypatch, capsys, tmp_path):
    root = make_repo({"a.py": "def a():\n    return 1\n"}, name="narrative-repo")
    commit(root, "add b (#3)", **{"b.py": "def b():\n    return 2\n"})
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    (root / ".cbi" / "concepts.json").write_text(json.dumps(concept_map(["a.py", "b.py"])))
    assert main(["scan"]) == 0
    capsys.readouterr()
    assert main(["history", "--since", "2000-01-01", "--format", "json"]) == 0
    entry = json.loads(capsys.readouterr().out)["entries"][0]

    assert main(["history", "--narrate", entry["sha"][:8]]) == 0
    line = capsys.readouterr().out.strip()
    task_id = line.split()[1]
    assert line == f"summarise-change {task_id} open"
    assert main(["task", task_id, "--ref", entry["sha"], "--json"]) == 0
    brief = json.loads(capsys.readouterr().out)
    answer = tmp_path / "narrative.json"
    answer.write_text(json.dumps({"input_hash": brief["input_hash"],
                                  "narrative": "This introduces the second architectural function."}))
    assert main(["submit", task_id, str(answer), "--ref", entry["sha"]]) == 0
    capsys.readouterr()

    assert main(["history", "--since", "2000-01-01", "--format", "markdown"]) == 0
    assert "This introduces the second architectural function." in capsys.readouterr().out
    assert main(["build", "--history"]) == 0
    capsys.readouterr()
    assert "This introduces the second architectural function." in (
        root / ".cbi" / "viewer" / "data" / "history.js").read_text()

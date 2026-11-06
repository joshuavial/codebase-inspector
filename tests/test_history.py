"""Architecture history points, projection, output and incremental reuse."""

import datetime as dt
import json
import sqlite3
import subprocess

from cbi import change_summaries, history, store, tasks
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
    assert history.history_points(plain, since=dt.date.today().isoformat())

    merged = make_repo({"a.py": "x = 1\n"}, name="merged")
    initial = git(merged, "rev-parse", "HEAD")
    direct = commit(merged, "direct on main", **{"early.py": "early = True\n"})
    git(merged, "checkout", "-q", "-b", "feature")
    commit(merged, "inside branch", **{"b.py": "y = 2\n"})
    git(merged, "checkout", "-q", "main")
    git(merged, "merge", "--no-ff", "-m", "Merge pull request #7 from feature", "feature")
    points = history.history_points(merged, since="2000-01-01")
    assert [point["sha"] for point in points[:2]] == [initial, direct]
    assert len(points) == 3 and points[-1]["pr"] == 7

    later = commit(merged, "direct after merges", **{"late.py": "late = True\n"})
    assert later not in {point["sha"] for point in history.history_points(merged, since="2000-01-01")}


def test_project_concepts_keeps_move_and_marks_folder_guess(tmp_path):
    current = sqlite3.connect(tmp_path / "current.db")
    point = sqlite3.connect(tmp_path / "point.db")
    for conn in (current, point):
        conn.executescript(
            "CREATE TABLE nodes (id TEXT, path TEXT, content_hash TEXT, kind TEXT, workspace_id TEXT, attrs TEXT);"
            "CREATE TABLE edges (src TEXT, dst TEXT, kind TEXT);"
        )
    current.executemany("INSERT INTO nodes VALUES (?, ?, ?, 'file', NULL, NULL)", [
        ("w:new/core.py", "new/core.py", "same",),
        ("w:old/near.py", "old/near.py", "near",),
    ])
    current.executemany("INSERT INTO edges VALUES (?, ?, 'owns')", [
        ("core", "w:new/core.py"), ("app", "w:old/near.py"),
    ])
    point.executemany("INSERT INTO nodes VALUES (?, ?, ?, 'file', NULL, NULL)", [
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


def test_project_concepts_uses_paths_from_the_top_repo(tmp_path):
    current = sqlite3.connect(tmp_path / "current.db")
    point = sqlite3.connect(tmp_path / "point.db")
    for conn in (current, point):
        conn.executescript(
            "CREATE TABLE nodes (id TEXT, path TEXT, content_hash TEXT, kind TEXT, workspace_id TEXT, attrs TEXT);"
            "CREATE TABLE edges (src TEXT, dst TEXT, kind TEXT);"
            "INSERT INTO nodes VALUES ('top', '', NULL, 'workspace', NULL, '{}');"
            "INSERT INTO nodes VALUES ('sub', 'lib', NULL, 'workspace', 'top', '{\"root\": \"lib\"}');"
            "INSERT INTO nodes VALUES ('top:README.md', 'README.md', 'a', 'doc', 'top', '{}');"
            "INSERT INTO nodes VALUES ('sub:README.md', 'README.md', 'b', 'doc', 'sub', '{}');"
        )
    current.executemany("INSERT INTO edges VALUES (?, ?, 'owns')", [("app", "top:README.md"), ("lib", "sub:README.md")])
    document = {
        "summary": "Fixture.",
        "concepts": [
            {"id": "app", "name": "App", "summary": "App.", "role": "app", "files": ["README.md"]},
            {"id": "lib", "name": "Lib", "summary": "Lib.", "role": "core", "files": ["lib/README.md"]},
        ], "externals": [], "relationships": [],
    }
    projected, provisional = history.project_concepts(document, point, current)
    leaves = {item["id"]: item["files"] for item in projected["concepts"]}
    assert leaves == {"app": ["README.md"], "lib": ["lib/README.md"]}
    assert provisional == []


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
    assert (root / ".cbi" / "viewer" / "index.html").read_text(encoding="utf-8").find("data/history.js") > 0
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


def test_project_model_preserves_projected_concepts_when_ref_has_committed_map(make_repo, monkeypatch):
    root = make_repo({"a.py": "x = 1\n"}, name="history-ref-committed-map")
    old_map = {
        "summary": "Old map.",
        "concepts": [{"id": "old_c", "name": "Old", "summary": "Old.", "role": "core", "files": ["a.py"]}],
        "externals": [], "relationships": [],
    }
    commit(root, "commit with map (#1)", **{".cbi/concepts.json": json.dumps(old_map)})
    commit(root, "add b (#2)", **{"b.py": "y = 2\n"})
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    today_map = {
        "summary": "Today map.",
        "concepts": [{"id": "new_c", "name": "New", "summary": "New.", "role": "core", "files": ["a.py", "b.py"]}],
        "externals": [], "relationships": [],
    }
    (root / ".cbi" / "concepts.json").write_text(json.dumps(today_map))
    assert main(["scan"]) == 0

    out = root / ".cbi"
    from cbi import diff, files
    conn = diff.open_model(out / "model.db")
    try:
        sha = files.resolve_commit(root, "HEAD~1")
        _db, _prov = history.point_model(root, out, sha, json.dumps(today_map), conn)
        ref_concepts_file = out / "refs" / sha / "concepts.json"
        assert ref_concepts_file.is_file()
        ref_data = json.loads(ref_concepts_file.read_text())
        concept_ids = [c["id"] for c in ref_data.get("concepts", [])]
        assert "new_c" in concept_ids
        assert "old_c" not in concept_ids
    finally:
        conn.close()



def test_cached_history_refreshes_architecture_answers_without_old_models(make_repo, monkeypatch, capsys, tmp_path):
    root = make_repo({"a.py": "def a():\n    return 1\n"}, name="summary-history")
    older = commit(root, "add another function", **{"b.py": "def b():\n    return 2\n"})
    newest = commit(root, "update another function", **{"b.py": "def b():\n    return 3\n"})
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    out = root / ".cbi"
    (out / "concepts.json").write_text(json.dumps(concept_map(["a.py", "b.py"])))
    assert main(["scan"]) == 0
    entries = history.build_history(root, out, "2000-01-01")
    entry = next(item for item in entries if item["sha"] == older)
    assert entry["changes"]["summaries"]["overall"]["state"] == "pending"
    assert main(["build", "--history"]) == 0
    assert "Summary pending: run cbi tasks" in (out / "viewer/data/history.js").read_text()
    capsys.readouterr()

    task_id = entry["changes"]["summaries"]["overall"]["task_id"]
    assert main(["task", task_id, "--json"]) == 0
    brief = json.loads(capsys.readouterr().out)
    narrative = "The app gains a second function; its caller impact and motivation are unknown from these facts."
    answer = tmp_path / "history-answer.json"
    answer.write_text(json.dumps({"input_hash": brief["input_hash"], "narrative": narrative,
                                  "citations": ["b.py"]}))
    assert main(["submit", task_id, str(answer)]) == 0
    capsys.readouterr()

    # Rescans can discard task rows. The history snapshot itself must retain
    # enough key/evidence metadata to reload and validate this answer.
    conn = store.open_db(out / "model.db")
    try:
        conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        conn.commit()
    finally:
        conn.close()

    old_model = out / "refs" / older / "model.db"
    assert not old_model.exists(), "history should have discarded this old point model"
    real_point = history.point_model

    def newest_point_only(repo, home, sha, *args):
        assert sha == newest, "answer refresh must not rebuild an old point"
        return real_point(repo, home, sha, *args)

    def no_structural_diff(*_args, **_kwargs):
        raise AssertionError("answer refresh must reuse the structural diff")

    with monkeypatch.context() as stable:
        stable.setattr(history, "point_model", newest_point_only)
        stable.setattr(history.diff, "compare_refs", no_structural_diff)
        refreshed = history.build_history(root, out, "2000-01-01")
    assert not old_model.exists()
    assert narrative in history.render(refreshed, "markdown")
    saved = json.loads((out / "history" / f"{older}.json").read_text())
    assert saved["changes"]["summaries"]["overall"]["state"] == "answered"
    assert saved["changes"]["summaries"]["overall"]["citations"] == ["b.py"]

    # Submit another answer after refreshing the history index. A standalone
    # viewer build must reload it too, without requiring another history command.
    concept_task = saved["changes"]["summaries"]["concepts"]["app"]["task_id"]
    assert main(["task", concept_task, "--json"]) == 0
    brief = json.loads(capsys.readouterr().out)
    concept_narrative = "A second application function is added; risk and user impact need further review."
    answer.write_text(json.dumps({"input_hash": brief["input_hash"], "narrative": concept_narrative,
                                  "citations": ["b.py"]}))
    assert main(["submit", concept_task, str(answer)]) == 0
    capsys.readouterr()

    # Viewer generation still rebuilds the point pictures by design, but its text
    # and comparison payload must use the refreshed answer from the cached entry.
    assert main(["build", "--history"]) == 0
    script = (out / "viewer/data/history.js").read_text()
    payload = json.loads(script[len('cbiLoad("history", '):-3])
    shown = next(item for item in payload["entries"] if item["sha"] == older)
    assert narrative in shown["text"]
    assert shown["diff"]["changes"]["summaries"]["overall"]["narrative"] == narrative
    assert concept_narrative in shown["text"]
    assert shown["diff"]["changes"]["summaries"]["concepts"]["app"]["narrative"] == concept_narrative


def test_history_snapshot_refresh_rejects_ungrounded_cached_answers(tmp_path):
    conn = store.open_db(tmp_path / "model.db")
    tasks.attach_cache(conn)
    digest = "history-snapshot-answer"
    entry = {"task_id": "missing-task", "input_hash": digest, "evidence_citations": ["a.py"],
             "state": "pending", "narrative": None, "citations": []}
    result = {"summaries": {"overall": entry, "concepts": {}}}
    try:
        conn.execute("INSERT INTO cache.summary_answers VALUES (?, ?)",
                     (digest, json.dumps({"narrative": "The app changes.", "citations": ["a.py"]})))
        conn.commit()
        assert change_summaries.refresh(conn, result)
        assert entry["state"] == "answered"
        assert not change_summaries.refresh(conn, result), "unchanged cache state should not rewrite history"
        conn.execute("UPDATE cache.summary_answers SET answer = ? WHERE input_hash = ?",
                     (json.dumps({"narrative": "An unsupported claim.", "citations": ["outside.py"]}), digest))
        conn.commit()
        assert change_summaries.refresh(conn, result)
        assert entry["state"] == "pending"
        assert entry["narrative"] is None
        assert entry["citations"] == []
    finally:
        conn.close()


def test_legacy_summary_without_scoped_evidence_stays_pending(tmp_path):
    conn = store.open_db(tmp_path / "model.db")
    tasks.attach_cache(conn)
    digest = "0123456789abcdef" + "a" * 48
    entry = {"task_id": "sac-" + digest[:16], "state": "answered",
             "narrative": "A stale summary.", "citations": ["first.py"]}
    result = {
        "groups": [
            {"id": "first", "changes": [{"code": [{"path": "first.py"}]}]},
            {"id": "second", "changes": [{"code": [{"path": "second.py"}]}]},
        ],
        "summaries": {"overall": None, "concepts": {"first": entry}},
    }
    try:
        # A unique cache prefix identifies an answer, but cannot recover the leaf's
        # original evidence boundary after both its task row and metadata are gone.
        conn.execute("INSERT INTO cache.summary_answers VALUES (?, ?)",
                     (digest, json.dumps({"narrative": "The sibling changed.", "citations": ["second.py"]})))
        conn.commit()
        assert change_summaries.refresh(conn, result)
        assert entry["state"] == "pending"
        assert entry["narrative"] is None
        assert entry["citations"] == []
        assert "input_hash" not in entry
        assert "evidence_citations" not in entry
        assert not change_summaries.refresh(conn, result)
    finally:
        conn.close()


def test_select_timezone_instants_and_date_bounds():
    # Commit at 2026-11-06T23:00:00+00:00, which is 2026-11-07 12:00 NZDT (+13:00)
    entries = [{"date": "2026-11-06T23:00:00+00:00", "changes": {"groups": []}}]

    # Instant comparison across timezones: 11:00 to 13:00 in NZ includes 23:00 UTC
    assert len(history.select(entries, since="2026-11-07T11:00:00+13:00", until="2026-11-07T13:00:00+13:00")) == 1
    # Instant comparison before window
    assert len(history.select(entries, since="2026-11-07T13:00:00+13:00")) == 0
    # Instant comparison after window
    assert len(history.select(entries, until="2026-11-07T11:00:00+13:00")) == 0


import sqlite3

from cbi import store, tasks


def test_connections_wait_and_use_wal(tmp_path):
    path = tmp_path / "model.db"
    conn = store.open_db(path)
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == store.BUSY_MS
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    tasks.attach_cache(conn)
    assert conn.execute("PRAGMA cache.journal_mode").fetchone()[0] == "wal"
    conn.close()
    before = set(path.parent.iterdir())
    reader = store.read_only(path)
    try:
        assert reader.execute("PRAGMA busy_timeout").fetchone()[0] == store.BUSY_MS
        assert reader.execute("SELECT count(*) FROM nodes").fetchone()[0] == 0
    finally:
        reader.close()
    # immutable=1 reports delete for the connection. The file header stays WAL (byte 18 == 2)
    # and the read creates no -wal or -shm.
    assert path.read_bytes()[18] == 2
    assert set(path.parent.iterdir()) == before


def test_schema_has_every_table_and_rebuilds_on_version_change(tmp_path):
    path = tmp_path / "model.db"
    conn = store.open_db(path)
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"nodes", "edges", "diagnostics", "file_state", "coverage_lines", "results", "tasks", "search", "meta"} <= tables
    with conn:
        store.set_meta(conn, "fingerprint", "x")
        conn.execute("PRAGMA user_version = 999")
    conn.close()
    conn = store.open_db(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == store.SCHEMA_VERSION
    assert store.get_meta(conn, "fingerprint") is None


def test_check_reports_busy_model_without_a_traceback(make_repo, monkeypatch, capsys):
    from cbi.cli import main

    root = make_repo({"core.py": "def run():\n    return 1\n"})
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    assert main(["scan"]) == 0
    capsys.readouterr()
    monkeypatch.setattr(store, "BUSY_MS", 20)
    holder = sqlite3.connect(root / ".cbi/model.db")
    holder.execute("BEGIN IMMEDIATE")
    try:
        assert main(["check"]) == 1
        err = capsys.readouterr().err
        assert "busy" in err.lower()
        assert "retry" in err.lower()
        assert "Traceback" not in err
    finally:
        holder.rollback()
        holder.close()


def test_concurrent_scans_wait_for_the_writer(make_repo, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from cbi.cli import main, scan

    root = make_repo({"core.py": "def run():\n    return 1\n"})
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    assert main(["scan"]) == 0
    entered = threading.Event()
    release = threading.Event()
    replace = store.replace_file_states

    def hold_first(conn, states):
        if not entered.is_set():
            entered.set()
            assert release.wait(10)
        return replace(conn, states)

    monkeypatch.setattr(store, "replace_file_states", hold_first)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(scan, root, root / ".cbi")
        assert entered.wait(10)
        second = pool.submit(scan, root, root / ".cbi")
        release.set()
        assert first.result(timeout=30)[0]
        assert second.result(timeout=30)[0]


def test_task_queries_do_not_need_a_writable_cache(make_repo, monkeypatch, capsys, tmp_path):
    import json
    from cbi.cli import main

    root = make_repo({"core.py": "def run():\n    return 1\n"})
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    assert main(["scan"]) == 0
    path = root / ".cbi/model.db"
    with sqlite3.connect(path) as conn:
        task_id = conn.execute("SELECT id FROM tasks WHERE kind = 'summarise-files'").fetchone()[0]
    blocked = tmp_path / "blocked"
    blocked.write_text("This path cannot hold a cache directory.")
    monkeypatch.setenv("CBI_CACHE_DIR", str(blocked / "cache"))
    before = path.read_bytes()
    capsys.readouterr()
    assert main(["task", task_id, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["id"] == task_id
    assert main(["tasks", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)
    assert path.read_bytes() == before


def test_task_query_reports_schema_mismatch_without_migrating(make_repo, monkeypatch, capsys):
    from cbi.cli import main

    root = make_repo({"core.py": "def run():\n    return 1\n"})
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    assert main(["scan"]) == 0
    path = root / ".cbi/model.db"
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA user_version = 999")
    conn.close()
    before = path.read_bytes()
    capsys.readouterr()
    assert main(["task", "any", "--json"]) == 1
    assert "rescan" in capsys.readouterr().err.lower()
    assert path.read_bytes() == before


def test_task_queries_report_unreadable_cache_and_keep_working(make_repo, monkeypatch, capsys, tmp_path):
    import json
    from cbi.cli import main

    root = make_repo({"core.py": "def run():\n    return 1\n"})
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    assert main(["scan"]) == 0
    with sqlite3.connect(root / ".cbi/model.db") as conn:
        task_id = conn.execute("SELECT id FROM tasks LIMIT 1").fetchone()[0]
    cache = tmp_path / "invalid-cache"
    cache.mkdir()
    (cache / "answers.db").write_text("not a SQLite database")
    monkeypatch.setenv("CBI_CACHE_DIR", str(cache))
    capsys.readouterr()
    assert main(["task", task_id, "--json"]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["id"] == task_id
    assert "CBI_CACHE_DIR" in captured.err
    assert "Continuing with the local model" in captured.err
    assert "Traceback" not in captured.err


def test_readonly_task_query_sees_committed_wal_changes(make_repo, monkeypatch, capsys):
    import json
    from cbi.cli import main

    root = make_repo({"core.py": "def run():\n    return 1\n"})
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    assert main(["scan"]) == 0
    writer = sqlite3.connect(root / ".cbi/model.db")
    task_id = writer.execute("SELECT id FROM tasks WHERE kind = 'summarise-files'").fetchone()[0]
    writer.execute("UPDATE tasks SET state = 'done' WHERE id = ?", (task_id,))
    writer.commit()
    capsys.readouterr()
    try:
        assert main(["task", task_id, "--json"]) == 0
        assert json.loads(capsys.readouterr().out)["state"] == "done"
    finally:
        writer.close()


def test_readonly_cache_sees_committed_wal_changes(tmp_path):
    conn = store.open_db(tmp_path / "model.db")
    tasks.attach_cache(conn)
    conn.execute("INSERT INTO cache.file_summaries VALUES (?, ?, ?)",
                 ("blob", tasks.PROTOCOL_VERSION, "Current summary."))
    conn.commit()
    reader = store.read_only(tmp_path / "model.db")
    try:
        tasks.attach_cache(reader, readonly=True)
        assert reader.execute("SELECT summary FROM cache.file_summaries").fetchone() == ("Current summary.",)
    finally:
        reader.close()
        conn.close()

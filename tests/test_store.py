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

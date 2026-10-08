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

import sqlite3

from cbi import store


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

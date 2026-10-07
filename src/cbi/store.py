"""SQLite model store: schema, version check and the queries scan needs."""

import json
import sqlite3

# Bump when the schema changes. The model is derived from the repo, so an old
# database is dropped and rebuilt rather than migrated.
SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE nodes (
    id TEXT PRIMARY KEY,
    parent_id TEXT,
    kind TEXT NOT NULL,
    display_kind TEXT NOT NULL,
    name TEXT NOT NULL,
    workspace_id TEXT,
    path TEXT,
    start_line INTEGER,
    end_line INTEGER,
    lang TEXT,
    loc INTEGER,
    content_hash TEXT,
    signature TEXT,
    doc TEXT,
    summary TEXT,
    summary_source TEXT,
    attrs TEXT
);
CREATE INDEX nodes_parent ON nodes(parent_id);
CREATE INDEX nodes_kind ON nodes(kind);

CREATE TABLE edges (
    src TEXT NOT NULL,
    dst TEXT NOT NULL,
    kind TEXT NOT NULL,
    source TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 1.0,
    weight INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (src, dst, kind, source)
);
CREATE INDEX edges_dst ON edges(dst);

CREATE TABLE diagnostics (
    node_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    detail TEXT
);
CREATE INDEX diagnostics_node ON diagnostics(node_id);

CREATE TABLE file_state (
    path TEXT PRIMARY KEY,
    mtime_ns INTEGER NOT NULL,
    size INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    parser_version INTEGER NOT NULL
);

CREATE TABLE coverage_lines (
    file_id TEXT NOT NULL,
    line INTEGER NOT NULL,
    hits INTEGER NOT NULL,
    artifact TEXT NOT NULL
);
CREATE INDEX coverage_file ON coverage_lines(file_id);

CREATE TABLE results (
    test_node_id TEXT NOT NULL,
    status TEXT NOT NULL,
    duration_ms REAL,
    artifact TEXT NOT NULL
);

CREATE TABLE tasks (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    node_id TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    state TEXT NOT NULL,
    depends_on TEXT NOT NULL DEFAULT '[]'
);

CREATE VIRTUAL TABLE search USING fts5(
    id UNINDEXED, name, display_kind, path, signature, doc, summary
);

-- Scan bookkeeping, such as the no-change fingerprint.
CREATE TABLE meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""

ENUMERATED_KINDS = ("workspace", "group", "file", "doc")


def open_db(path):
    """Open the model, creating it or rebuilding it if the schema version differs."""
    conn = sqlite3.connect(path)
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version != SCHEMA_VERSION:
        if version:
            conn.close()
            path.unlink()
            conn = sqlite3.connect(path)
        with conn:
            conn.executescript(SCHEMA)
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    return conn


def get_meta(conn, key):
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def set_meta(conn, key, value):
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))


def file_states(conn):
    return {
        row[0]: row[1:]
        for row in conn.execute("SELECT path, mtime_ns, size, content_hash, parser_version FROM file_state")
    }


def replace_file_states(conn, states):
    """states: {path: (mtime_ns, size, content_hash, parser_version)}"""
    conn.execute("DELETE FROM file_state")
    conn.executemany(
        "INSERT INTO file_state (path, mtime_ns, size, content_hash, parser_version) VALUES (?, ?, ?, ?, ?)",
        [(path, *state) for path, state in states.items()],
    )


NODE_COLUMNS = ("id", "parent_id", "kind", "display_kind", "name", "workspace_id", "path", "lang", "content_hash", "attrs")


def replace_enumerated_nodes(conn, nodes):
    """Upsert workspace, group and file nodes and drop the ones no longer present.

    Columns filled by later steps (summary, doc, ...) are left alone on update.
    """
    rows = [
        tuple(json.dumps(n["attrs"], sort_keys=True) if c == "attrs" and n.get(c) is not None else n.get(c) for c in NODE_COLUMNS)
        for n in nodes
    ]
    updates = ", ".join(f"{c} = excluded.{c}" for c in NODE_COLUMNS[1:])
    conn.executemany(
        f"INSERT INTO nodes ({', '.join(NODE_COLUMNS)}) VALUES ({', '.join('?' * len(NODE_COLUMNS))}) "
        f"ON CONFLICT(id) DO UPDATE SET {updates}",
        rows,
    )
    conn.execute("CREATE TEMP TABLE IF NOT EXISTS keep (id TEXT PRIMARY KEY)")
    conn.execute("DELETE FROM keep")
    conn.executemany("INSERT OR IGNORE INTO keep VALUES (?)", [(n["id"],) for n in nodes])
    conn.execute(
        f"DELETE FROM nodes WHERE kind IN ({', '.join('?' * len(ENUMERATED_KINDS))}) AND id NOT IN (SELECT id FROM keep)",
        ENUMERATED_KINDS,
    )


def counts_by_display_kind(conn):
    return dict(conn.execute("SELECT display_kind, COUNT(*) FROM nodes GROUP BY display_kind ORDER BY display_kind"))

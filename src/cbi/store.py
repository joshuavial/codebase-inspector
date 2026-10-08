"""SQLite model store: schema, version check and the queries scan needs."""

import json
import sqlite3
import time
from pathlib import Path

# Bump when the schema changes. The model is derived from the repo, so an old
# database is dropped and rebuilt rather than migrated.
SCHEMA_VERSION = 6

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
    attrs TEXT, -- JSON. Calls from JSX or createElement: {"via": "jsx"}.
                -- part_of: {"via": "direct"} or {"via": "transitive"}.
                -- Injected calls: {"via": "injection"}. Type-only imports: {"type_only": true}.
                -- A reads_env edge may hold {"default": "..."}.
                -- http_calls: {"method", "path", "confidence"}. The handler's node attrs hold http_routes.
                -- Relates: {"label", "via"?, "at"?, "minor"?, "basis"?, "kind"?: "hosts", "integration": bool}.
                -- Concept attrs: {"role", "entry": bool, "entry_file"?: path or [paths]}.
                -- sketches: a screen region names this component; weight is how many.
    ordinal INTEGER NOT NULL DEFAULT 0, -- a second relates edge between the same ends
    PRIMARY KEY (src, dst, kind, source, ordinal)
);
CREATE INDEX edges_dst ON edges(dst);

CREATE TABLE diagnostics (
    node_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    detail TEXT
);
CREATE INDEX diagnostics_node ON diagnostics(node_id);

-- Per code file, the parser's imports, exports, call sites, reads and env reads as JSON, so
-- resolution can rerun over every file without reparsing unchanged ones.
CREATE TABLE facts (
    file_id TEXT PRIMARY KEY,
    data TEXT NOT NULL
);

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
    depends_on TEXT NOT NULL DEFAULT '[]',
    inputs TEXT NOT NULL DEFAULT '[]' -- JSON list of the node IDs the brief covers
);

CREATE VIRTUAL TABLE search USING fts5(
    id UNINDEXED, name, display_kind, path, signature, doc, summary
);

-- Scan bookkeeping, such as the no-change fingerprint.
CREATE TABLE meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

-- Symbols are replaced and dropped by file (deliverable 13: a large monorepo spent 50 s scanning nodes without it).
CREATE INDEX nodes_file ON nodes(workspace_id, path);
"""

ENUMERATED_KINDS = ("workspace", "group", "file", "doc")

# Wait this long for another writer before raising SQLITE_BUSY. Concurrent submits
# from parallel agents otherwise fail at once, because the default wait is 5 seconds
# and a transaction that already started does not restart itself.
BUSY_MS = 30_000
BUSY_SECONDS = BUSY_MS / 1000


def prepare(conn, *, wal):
    """Busy timeout on this connection. WAL on a writable one, so readers do not block a submit."""
    conn.execute(f"PRAGMA busy_timeout = {BUSY_MS}")
    if wal:
        conn.execute("PRAGMA journal_mode = WAL")
    return conn


def _connect(path):
    conn = sqlite3.connect(path, timeout=BUSY_SECONDS)
    return prepare(conn, wal=True)


def _remove_db(path):
    path.unlink(missing_ok=True)
    for suffix in ("-wal", "-shm"):
        Path(str(path) + suffix).unlink(missing_ok=True)


def open_db(path):
    """Open the model, creating it or rebuilding it if the schema version differs."""
    conn = _connect(path)
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version != SCHEMA_VERSION:
        if version:
            conn.close()
            _remove_db(path)
            conn = _connect(path)
        with conn:
            conn.executescript(SCHEMA)
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    return conn


def read_only(path):
    """Open a model without creating, migrating, or changing its journal.

    ``mode=ro`` refuses writes. ``immutable=1`` stops SQLite creating ``-wal`` and
    ``-shm`` beside the file: a plain ``mode=ro`` open of a WAL database still
    creates them, and that creation fails when the directory cannot be written.
    No journal-mode pragma is issued.
    """
    uri = Path(path).resolve().as_uri() + "?mode=ro&immutable=1"
    conn = sqlite3.connect(uri, uri=True, timeout=BUSY_SECONDS)
    return prepare(conn, wal=False)


def _busy_codes():
    codes = {sqlite3.SQLITE_BUSY}
    for name in ("SQLITE_BUSY_SNAPSHOT", "SQLITE_BUSY_RECOVERY", "SQLITE_BUSY_TIMEOUT"):
        code = getattr(sqlite3, name, None)
        if code is not None:
            codes.add(code)
    return codes


def is_busy(err):
    """True when SQLite could not get a lock. The statement must be rolled back and tried again."""
    if not isinstance(err, sqlite3.OperationalError):
        return False
    if getattr(err, "sqlite_errorcode", None) in _busy_codes():
        return True
    text = str(err).lower()
    return "locked" in text or "busy" in text


def retry_write(conn, fn, attempts=8):
    """Run fn inside one write transaction. On SQLITE_BUSY, roll back and run it again.

    The connection's busy timeout already waits, and still raises when a deferred
    transaction has to be restarted after another writer committed. fn must only write.
    """
    delay = 0.02
    for attempt in range(attempts):
        try:
            with conn:
                return fn()
        except sqlite3.OperationalError as err:
            if not is_busy(err) or attempt + 1 == attempts:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 0.4)


def ref_reusable(path, ignore_hash, parser_version):
    """True when a commit model is already stored and still matches this parser and ignore file."""
    if not Path(path).exists():
        return False
    try:
        conn = read_only(path)
    except sqlite3.Error:
        return False
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version != SCHEMA_VERSION:
            return False
        meta = dict(conn.execute("SELECT key, value FROM meta"))
    except sqlite3.Error:
        return False
    finally:
        conn.close()
    return meta.get("parser_version") == str(parser_version) and meta.get("ignore") == ignore_hash


def model_flags(path):
    """(has a model file, no open or blocked tasks). A missing or unreadable file is (False, False)
    unless the file exists but cannot be queried, which is (True, False)."""
    if not Path(path).exists():
        return False, False
    try:
        conn = read_only(path)
        try:
            waiting = conn.execute("SELECT COUNT(*) FROM tasks WHERE state != 'done'").fetchone()[0]
        finally:
            conn.close()
        return True, waiting == 0
    except sqlite3.Error:
        return True, False


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


# content_hash on a symbol or test is the sha1 of its body, the source after the
# signature, so a rename keeps the hash and the diff can see a move.
SYMBOL_COLUMNS = ("id", "parent_id", "kind", "display_kind", "name", "workspace_id", "path",
                  "start_line", "end_line", "lang", "loc", "signature", "doc", "content_hash", "attrs")


def replace_file_symbols(conn, workspace_id, path, loc, nodes, file_node_id, facts):
    """Replace the symbol and test nodes and the facts parsed from one file and set the file's LOC."""
    conn.execute("INSERT OR REPLACE INTO facts (file_id, data) VALUES (?, ?)", (file_node_id, json.dumps(facts)))
    conn.execute(
        "DELETE FROM nodes WHERE kind IN ('symbol', 'test') AND workspace_id = ? AND path = ?",
        (workspace_id, path),
    )
    conn.executemany(
        f"INSERT INTO nodes ({', '.join(SYMBOL_COLUMNS)}) VALUES ({', '.join('?' * len(SYMBOL_COLUMNS))})",
        [tuple(json.dumps(n["attrs"], sort_keys=True) if c == "attrs" and n.get("attrs") is not None else n.get(c)
               for c in SYMBOL_COLUMNS) for n in nodes],
    )
    conn.execute("UPDATE nodes SET loc = ? WHERE kind = 'file' AND workspace_id = ? AND path = ?", (loc, workspace_id, path))


def drop_orphan_symbols(conn):
    """Delete symbol and test nodes whose file is gone from the model, and facts and diagnostics of missing nodes."""
    conn.execute(
        "DELETE FROM nodes WHERE kind IN ('symbol', 'test') AND NOT EXISTS ("
        "SELECT 1 FROM nodes f WHERE f.kind = 'file' AND f.workspace_id = nodes.workspace_id AND f.path = nodes.path)"
    )
    conn.execute("DELETE FROM facts WHERE file_id NOT IN (SELECT id FROM nodes)")
    conn.execute("DELETE FROM diagnostics WHERE node_id NOT IN (SELECT id FROM nodes)")


def set_diagnostic(conn, node_id, kind, detail):
    """Replace the node's diagnostics of this kind with one row, or none when detail is None."""
    conn.execute("DELETE FROM diagnostics WHERE node_id = ? AND kind = ?", (node_id, kind))
    if detail is not None:
        conn.execute("INSERT INTO diagnostics (node_id, kind, detail) VALUES (?, ?, ?)", (node_id, kind, detail))


# Route method and path are appended to the indexed signature so a path word is searchable.
# The nodes table keeps the real signature. Missing http_routes leaves the signature unchanged.
_ROUTE_SIGNATURE = (
    "trim(coalesce(signature, '') || ' ' || coalesce(("
    "SELECT group_concat(json_extract(value, '$.method') || ' ' || json_extract(value, '$.path'), ' ') "
    "FROM json_each(json_extract(attrs, '$.http_routes'))), ''))"
)


def reindex(conn, ids=None):
    """Rebuild the search rows for the given node IDs, or for every node."""
    columns = "id, name, display_kind, path, signature, doc, summary"
    selected = f"id, name, display_kind, path, {_ROUTE_SIGNATURE}, doc, summary"
    if ids is None:
        conn.execute("DELETE FROM search")
        conn.execute(f"INSERT INTO search ({columns}) SELECT {selected} FROM nodes")
        return
    ids = json.dumps(list(ids))
    conn.execute("DELETE FROM search WHERE id IN (SELECT value FROM json_each(?))", (ids,))
    conn.execute(
        f"INSERT INTO search ({columns}) SELECT {selected} FROM nodes "
        "WHERE id IN (SELECT value FROM json_each(?))",
        (ids,),
    )

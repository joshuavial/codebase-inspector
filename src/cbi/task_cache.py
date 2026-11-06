"""Shared answer cache database attachment and lookups across mapped repositories."""

import json
import os
import sqlite3
import sys
from pathlib import Path

from cbi import store
from cbi.files import blob_id

PROTOCOL_VERSION = 1
EMPTY_BLOB_ID = blob_id(b"")


class AnswerError(Exception):
    pass


def cache_path():
    return Path(os.environ.get("CBI_CACHE_DIR") or Path.home() / ".cache" / "codebase-inspector") / "answers.db"


def attach_cache(conn, *, readonly=False):
    """Attach the shared answer cache as `cache`.

    A writable attach creates the file and its tables, so one transaction covers both
    databases. A read-only attach opens an existing file with ``mode=ro`` and does not
    create the cache or its directory. A protected cache without WAL sidecars is
    read as a frozen snapshot; a mutable cache uses normal SQLite locking. When
    the file is missing or cannot be opened, it is skipped and the model stays usable.
    """
    path = cache_path()
    if readonly:
        _attach_cache_readonly(conn, path)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    conn.execute("ATTACH DATABASE ? AS cache", (str(path),))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS cache.file_summaries ("
        "content_hash TEXT NOT NULL, protocol INTEGER NOT NULL, summary TEXT NOT NULL, "
        "PRIMARY KEY (content_hash, protocol))"
    )
    # Group and workspace answers, keyed by an input hash that already includes the protocol version.
    conn.execute("CREATE TABLE IF NOT EXISTS cache.summary_answers (input_hash TEXT PRIMARY KEY, answer TEXT NOT NULL)")
    conn.execute("PRAGMA cache.journal_mode = WAL")
    conn.commit()


def _attach_cache_readonly(conn, path):
    try:
        if not path.is_file():
            return
        uri = store.read_uri(path, frozen_fallback=True)
        uri = store.validate_read_uri(path, uri, frozen_fallback=True)
        conn.execute("ATTACH DATABASE ? AS cache", (uri,))
        conn.execute("SELECT 1 FROM cache.sqlite_master LIMIT 1").fetchone()
        store.note_frozen_read(path, uri)
    except (OSError, sqlite3.Error) as err:
        print(f"Cannot read answer cache at {path}: {err}. Continuing with the local model. "
              "Check cache read permissions or set CBI_CACHE_DIR to an accessible cache directory.", file=sys.stderr)
        try:
            conn.execute("DETACH DATABASE cache")
        except sqlite3.Error:
            pass


def _cached_answer(conn, input_hash):
    row = conn.execute("SELECT answer FROM cache.summary_answers WHERE input_hash = ?", (input_hash,)).fetchone()
    return json.loads(row[0]) if row else None

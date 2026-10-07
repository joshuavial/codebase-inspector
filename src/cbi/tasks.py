"""Judgement tasks: generation, briefs, answer validation and the shared answer cache.

Only `summarise-files` exists so far. Answers are cached per file content hash in
a cache shared by every mapped repo, so identical files are summarised once.
"""

import hashlib
import json
import os
import posixpath
from pathlib import Path

from cbi import store
from cbi.files import PARSER_VERSION

# Bump when briefs or answers change meaning; cached answers from older versions are ignored.
PROTOCOL_VERSION = 1
FILES_PER_TASK = 15

SCHEMAS = {
    "summarise-files": {
        "type": "object",
        "required": ["input_hash", "files"],
        "additionalProperties": False,
        "properties": {
            "input_hash": {"type": "string", "description": "copied from the brief"},
            "files": {
                "type": "array",
                "minItems": 1,
                "description": "one entry for every file in the brief",
                "items": {
                    "type": "object",
                    "required": ["path", "summary"],
                    "additionalProperties": False,
                    "properties": {
                        "path": {"type": "string", "description": "the file's path as given in the brief"},
                        "summary": {"type": "string", "minLength": 1, "maxLength": 600,
                                    "description": "1 to 3 sentences on what the file is for"},
                    },
                },
            },
        },
    },
}


class AnswerError(Exception):
    """A rejected answer. The message lists each problem with its JSON path."""


class UnknownTask(Exception):
    pass


def cache_path():
    return Path(os.environ.get("CBI_CACHE_DIR") or Path.home() / ".cache" / "codebase-inspector") / "answers.db"


def attach_cache(conn):
    """Attach the shared answer cache as `cache`, so one transaction covers both databases."""
    path = cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn.execute("ATTACH DATABASE ? AS cache", (str(path),))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS cache.file_summaries ("
        "content_hash TEXT NOT NULL, protocol INTEGER NOT NULL, summary TEXT NOT NULL, "
        "PRIMARY KEY (content_hash, protocol))"
    )
    conn.commit()


def _cached(conn, content_hash):
    row = conn.execute(
        "SELECT summary FROM cache.file_summaries WHERE content_hash = ? AND protocol = ?",
        (content_hash, PROTOCOL_VERSION),
    ).fetchone()
    return row[0] if row else None


def _input_hash(files):
    text = json.dumps([PROTOCOL_VERSION, PARSER_VERSION, [[f[0], f[1]] for f in files]])
    return hashlib.sha1(text.encode()).hexdigest()[:16]


def refresh(conn):
    """Fill file summaries from the cache and open a task for each batch with uncached files.

    Files are batched by folder (the workspace for files at its root) in path order,
    FILES_PER_TASK per batch, and a batch's task lists only its uncached files. A task
    whose files are all answered is marked done.
    """
    rows = conn.execute(
        "SELECT id, content_hash, parent_id FROM nodes "
        "WHERE kind = 'file' AND json_extract(attrs, '$.role') IN ('code', 'test') ORDER BY parent_id, path"
    ).fetchall()
    by_group = {}
    for node_id, content_hash, parent in rows:
        by_group.setdefault(parent, []).append((node_id, content_hash))
    wanted = set()
    for group, group_files in by_group.items():
        prefix = "sf-" + hashlib.sha1(group.encode()).hexdigest()[:8]
        for start in range(0, len(group_files), FILES_PER_TASK):
            pending = []
            for node_id, content_hash in group_files[start:start + FILES_PER_TASK]:
                summary = _cached(conn, content_hash)
                if summary is None:
                    pending.append((node_id, content_hash))
                    conn.execute(
                        "UPDATE nodes SET summary = NULL, summary_source = NULL WHERE id = ? AND summary_source = 'agent'",
                        (node_id,),
                    )
                else:
                    conn.execute("UPDATE nodes SET summary = ?, summary_source = 'agent' WHERE id = ?", (summary, node_id))
            if not pending:
                continue
            task_id = f"{prefix}-{start // FILES_PER_TASK + 1}"
            wanted.add(task_id)
            conn.execute(
                "INSERT INTO tasks (id, kind, node_id, input_hash, state, inputs) VALUES (?, 'summarise-files', ?, ?, 'open', ?) "
                "ON CONFLICT(id) DO UPDATE SET node_id = excluded.node_id, input_hash = excluded.input_hash, "
                "state = 'open', inputs = excluded.inputs",
                (task_id, group, _input_hash(pending), json.dumps([n for n, _ in pending])),
            )
    conn.execute(
        "UPDATE tasks SET state = 'done' WHERE kind = 'summarise-files' AND state = 'open' "
        "AND id NOT IN (SELECT value FROM json_each(?))",
        (json.dumps(sorted(wanted)),),
    )


def open_tasks(conn, kind=None, limit=None):
    sql = (
        "SELECT t.id, t.kind, t.node_id, n.display_kind, n.path, json_array_length(t.inputs) FROM tasks t "
        "LEFT JOIN nodes n ON n.id = t.node_id WHERE t.state = 'open'"
    )
    params = []
    if kind:
        sql += " AND t.kind = ?"
        params.append(kind)
    sql += " ORDER BY n.path, t.id"
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    return [
        {"id": r[0], "kind": r[1], "node_id": r[2], "node_display_kind": r[3], "node_path": r[4], "files": r[5]}
        for r in conn.execute(sql, params)
    ]


def _task(conn, task_id):
    row = conn.execute("SELECT kind, node_id, input_hash, state, inputs FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if not row:
        raise UnknownTask(f"no task {task_id}; run `cbi tasks` to list open tasks")
    return {"id": task_id, "kind": row[0], "node_id": row[1], "input_hash": row[2], "state": row[3],
            "inputs": json.loads(row[4])}


def _read_path(conn, workspace_id, path):
    """A workspace-relative path made relative to the top repo, so the agent can open it."""
    row = conn.execute("SELECT json_extract(attrs, '$.root') FROM nodes WHERE id = ?", (workspace_id,)).fetchone()
    root = row[0] if row else ""
    return posixpath.join(root, path) if root else path


def _task_files(conn, task):
    out = []
    for node_id in task["inputs"]:
        row = conn.execute("SELECT workspace_id, path, content_hash FROM nodes WHERE id = ?", (node_id,)).fetchone()
        if row:
            out.append({"id": node_id, "path": _read_path(conn, row[0], row[1]), "content_hash": row[2]})
    return out


def brief(conn, task_id):
    """Everything an agent needs to answer a task, as a dict."""
    task = _task(conn, task_id)
    files = _task_files(conn, task)
    for f in files:
        f["outline"] = [
            {"display_kind": r[0], "name": r[1], "lines": f"{r[2]}-{r[3]}", "signature": r[4], "doc": r[5]}
            for r in conn.execute(
                "SELECT display_kind, name, start_line, end_line, signature, doc FROM nodes "
                "WHERE kind IN ('symbol', 'test') AND parent_id = ? ORDER BY start_line",
                (f["id"],),
            )
        ]
    return {
        "id": task_id,
        "kind": task["kind"],
        "state": task["state"],
        "node_id": task["node_id"],
        "input_hash": task["input_hash"],
        "instructions": (
            "Read each file listed (paths are relative to the repo root) and write a summary of 1 to 3 "
            "sentences saying what the file is for and what it provides, for someone who has not read it. "
            "Answer with JSON matching `answer_schema`: copy `input_hash` and give one entry per file."
        ),
        "files": files,
        "answer_schema": SCHEMAS[task["kind"]],
    }


def _check(value, schema, path, errors):
    """Collect `<json path>: <problem>` strings for value against a small JSON Schema subset."""
    kind = schema["type"]
    if not isinstance(value, {"object": dict, "array": list, "string": str}[kind]):
        errors.append(f"{path}: expected {kind}, got {type(value).__name__}")
        return
    if kind == "object":
        props = schema["properties"]
        errors.extend(f"{path}.{key}: required" for key in schema["required"] if key not in value)
        if not schema.get("additionalProperties", True):
            errors.extend(f"{path}.{key}: unknown key" for key in value if key not in props)
        for key, sub in props.items():
            if key in value:
                _check(value[key], sub, f"{path}.{key}", errors)
    elif kind == "array":
        if len(value) < schema.get("minItems", 0):
            errors.append(f"{path}: needs at least {schema['minItems']} item(s)")
        for i, item in enumerate(value):
            _check(item, schema["items"], f"{path}[{i}]", errors)
    else:
        length = len(value.strip())
        if length < schema.get("minLength", 0):
            errors.append(f"{path}: empty")
        if length > schema.get("maxLength", length):
            errors.append(f"{path}: {length} characters, at most {schema['maxLength']}")


def submit(conn, task_id, text):
    """Validate and store an answer in one transaction. Returns a one-line report.

    Raises AnswerError when the answer is malformed, misses or adds files, or was
    written for inputs that have since changed.
    """
    task = _task(conn, task_id)
    try:
        answer = json.loads(text)
    except json.JSONDecodeError as err:
        raise AnswerError(f"$: not valid JSON ({err})") from None
    errors = []
    _check(answer, SCHEMAS[task["kind"]], "$", errors)
    if errors:
        raise AnswerError("\n".join(errors))
    if answer["input_hash"] != task["input_hash"]:
        raise AnswerError(
            f"$.input_hash: stale. The task's inputs changed since this brief was issued; "
            f"run `cbi task {task_id}` again and answer the new brief."
        )
    files = {f["path"]: f for f in _task_files(conn, task)}
    seen = set()
    for i, entry in enumerate(answer["files"]):
        if entry["path"] not in files:
            errors.append(f"$.files[{i}].path: {entry['path']!r} is not in this task")
        elif entry["path"] in seen:
            errors.append(f"$.files[{i}].path: {entry['path']!r} given twice")
        seen.add(entry["path"])
    errors.extend(f"$.files: missing {path!r}" for path in files if path not in seen)
    if errors:
        raise AnswerError("\n".join(errors))

    changed = 0
    with conn:
        for entry in answer["files"]:
            summary = entry["summary"].strip()
            content_hash = files[entry["path"]]["content_hash"]
            changed += _cached(conn, content_hash) != summary
            conn.execute(
                "INSERT OR REPLACE INTO cache.file_summaries (content_hash, protocol, summary) VALUES (?, ?, ?)",
                (content_hash, PROTOCOL_VERSION, summary),
            )
            # Every file in this model with the same content gets the summary too.
            conn.execute(
                "UPDATE nodes SET summary = ?, summary_source = 'agent' WHERE kind = 'file' AND content_hash = ?",
                (summary, content_hash),
            )
        ids = [r[0] for r in conn.execute(
            "SELECT id FROM nodes WHERE kind = 'file' AND content_hash IN (SELECT value FROM json_each(?))",
            (json.dumps([f["content_hash"] for f in files.values()]),),
        )]
        store.reindex(conn, ids)
        conn.execute("UPDATE tasks SET state = 'done' WHERE id = ?", (task_id,))
    if not changed:
        return f"{task_id}: already accepted, nothing changed"
    return f"{task_id}: accepted {len(answer['files'])} file summaries"

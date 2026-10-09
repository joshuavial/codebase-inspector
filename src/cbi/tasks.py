"""Judgement tasks: generation, briefs, answer validation and the shared answer cache.

`summarise-files` answers are cached per file content hash, and other answers per input
hash, in a cache shared by every mapped repo, so identical inputs are answered once.
Summary tasks run bottom-up. `confirm-structure` is one per workspace; accepting it
writes structure.json and reruns manifests and resolution. `summarise-deployable` waits
for that, then for its member files' summaries.
"""

import hashlib
import json
import os
import posixpath
import re
from collections import defaultdict
from pathlib import Path

from cbi import concepts, manifests, resolve, screens, store
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


GROUP_DISPLAY_KINDS = ["folder", "module", "component", "library", "skill", "repertoire", "tests", "scripts",
                       "config", "examples", "docs"]

SCHEMAS["summarise-group"] = {
    "type": "object",
    "required": ["input_hash", "summary"],
    "additionalProperties": False,
    "properties": {
        "input_hash": {"type": "string", "description": "copied from the brief"},
        "summary": {"type": "string", "minLength": 1, "maxLength": 600,
                    "description": "1 to 3 sentences on what this folder or package is for"},
        "display_name": {"type": "string", "minLength": 1, "maxLength": 60,
                         "description": "optional: a clearer name to show than the directory name"},
        "display_kind": {"type": "string", "enum": GROUP_DISPLAY_KINDS,
                         "description": "optional: what this group is, when the current kind undersells it"},
    },
}
SCHEMAS["summarise-workspace"] = {
    "type": "object",
    "required": ["input_hash", "summary"],
    "additionalProperties": False,
    "properties": {
        "input_hash": {"type": "string", "description": "copied from the brief"},
        "summary": {"type": "string", "minLength": 1, "maxLength": 1000,
                    "description": "2 to 4 sentences: what this repository is and its main parts"},
    },
}
SCHEMAS["summarise-deployable"] = {
    "type": "object",
    "required": ["input_hash", "summary"],
    "additionalProperties": False,
    "properties": {
        "input_hash": {"type": "string", "description": "copied from the brief"},
        "summary": {"type": "string", "minLength": 1, "maxLength": 600,
                    "description": "1 to 3 sentences on what this deployable is and what it ships"},
    },
}
_STRUCTURE_ITEM = {
    "deployables": {
        "type": "object", "additionalProperties": False,
        "properties": {
            "id": {"type": "string", "minLength": 1, "description": "detected id; required to rename or remove, and the id is kept"},
            "name": {"type": "string", "minLength": 1, "maxLength": 120, "description": "deployable name"},
            "display_kind": {"type": "string", "minLength": 1, "maxLength": 40, "description": "such as node app, web app, cli"},
            "entry_points": {"type": "array", "items": {"type": "string", "minLength": 1, "maxLength": 300},
                             "description": "source paths from the repo root"},
            "remove": {"type": "boolean", "description": "true to drop this detected deployable"},
        },
    },
    "packages": {
        "type": "object", "additionalProperties": False,
        "properties": {
            "id": {"type": "string", "minLength": 1, "description": "detected id; required to rename or remove"},
            "name": {"type": "string", "minLength": 1, "maxLength": 120, "description": "package name"},
            "display_kind": {"type": "string", "minLength": 1, "maxLength": 40},
            "directory": {"type": "string", "minLength": 1, "maxLength": 300, "description": "path from the repo root"},
            "remove": {"type": "boolean", "description": "true to drop this detected package"},
        },
    },
}
SCHEMAS["confirm-structure"] = {
    "type": "object",
    "required": ["input_hash", "deployables", "packages"],
    "additionalProperties": False,
    "properties": {
        "input_hash": {"type": "string", "description": "copied from the brief"},
        "deployables": {"type": "array", "items": _STRUCTURE_ITEM["deployables"],
                        "description": "corrections; empty accepts detection as it is"},
        "packages": {"type": "array", "items": _STRUCTURE_ITEM["packages"],
                     "description": "packages to add or correct; empty accepts detection as it is and does not add bare directories"},
    },
}

# Summary tasks above file level, by the kind of node they cover: (task kind, task ID prefix).
# `confirm-structure` is one per workspace (prefix `cs`), not keyed by node kind: the workspace
# node already carries `summarise-workspace`. `summarise-deployable` waits for it.
SUMMARY_KINDS = {
    "group": ("summarise-group", "sg"),
    "package": ("summarise-group", "sg"),
    "workspace": ("summarise-workspace", "sw"),
    "deployable": ("summarise-deployable", "sd"),
}

STRUCTURE_EMPTY = (
    "Empty arrays accept detection as it is and do not add a package: "
    "a manifest-less library is created only when you add it."
)

INSTRUCTIONS = {
    "summarise-files": (
        "Read each file listed (paths are relative to the repo root) and write a summary of 1 to 3 "
        "sentences saying what the file is for and what it provides, for someone who has not read it. "
        "Answer with JSON matching `answer_schema`: copy `input_hash` and give one entry per file."
    ),
    "summarise-group": (
        "Write a summary of 1 to 3 sentences saying what this folder or package is for and what it holds, "
        "built from its children's summaries below; open a file only if they leave it unclear. Optionally "
        "give `display_name`, when a clearer name than the directory's helps, and `display_kind` from the "
        "allowed list, such as `module` for a code package or `tests` for a test folder. Answer with JSON "
        "matching `answer_schema` and copy `input_hash`."
    ),
    "summarise-workspace": (
        "Write a summary of 2 to 4 sentences saying what this repository is and what its main parts are, "
        "from the top-level summaries and the README head below. Answer with JSON matching `answer_schema` "
        "and copy `input_hash`."
    ),
    "confirm-structure": " ".join((
        "The manifests detected the deployables, packages and bare directories below, before any "
        "structure.json overrides. Answer with the corrections for this workspace: copy `input_hash` and "
        "give `deployables` and `packages`. List only what should change.",
        STRUCTURE_EMPTY,
        "To remove one, give its id and \"remove\": true. To rename one, give its id and the "
        "new name (the id stays). To add a manifest-less library, give its name and directory, a path "
        "from the repo root. The comment under the bare directories says which look like libraries "
        "(production code outside the directory imports a source file there) and which look like "
        "scripts or tests. That comment is not part of the answer. The answer template accepts "
        "detection as it is.",
        "`overrides`, when present, is the current structure.json for this workspace; your answer "
        "replaces it. Accepting writes structure.json and reruns manifest detection and resolution.",
    )),
    "summarise-deployable": (
        "Write a summary of 1 to 3 sentences saying what this deployable is and what it ships, from its "
        "entry points and the member summaries below. Open a file only if those leave it unclear. Answer "
        "with JSON matching `answer_schema` and copy `input_hash`."
    ),
    "define-concepts": concepts.INSTRUCTIONS,
    "sketch-screens": screens.INSTRUCTIONS,
    "summarise-change": (
        "Read the structural diff below and write a short narrative of what the change does to the "
        "architecture and what a reviewer should look at. A few sentences, not a restatement of every "
        "row. Answer with JSON matching `answer_schema` and copy `input_hash`. The narrative is shown "
        "in the review or history entry once you submit it. It is never required for either to be written."
    ),
}
SCHEMAS["define-concepts"] = concepts.ANSWER_SCHEMA
SCHEMAS["sketch-screens"] = screens.ANSWER_SCHEMA
SCHEMAS["summarise-change"] = {
    "type": "object",
    "required": ["input_hash", "narrative"],
    "additionalProperties": False,
    "properties": {
        "input_hash": {"type": "string", "description": "copied from the brief"},
        "narrative": {
            "type": "string", "minLength": 1, "maxLength": 2000,
            "description": "a few sentences on what the change does to the architecture and what to look at",
        },
    },
}

# A manifest file anywhere under a top-level directory means that directory is not "bare".
_MANIFEST = re.compile(
    r"(^|/)(?:package\.json|pyproject\.toml|wrangler\.toml|compose\.ya?ml|"
    r"Dockerfile(?:\.[^/]+)?|Containerfile|vite\.config\.[^/]+)$"
)
_DEP_KEYS = ("id", "name", "display_kind", "entry_points", "remove")
_PKG_KEYS = ("id", "name", "display_kind", "directory", "remove")


class AnswerError(Exception):
    """A rejected answer. The message lists each problem with its JSON path."""


class UnknownTask(Exception):
    pass


def cache_path():
    return Path(os.environ.get("CBI_CACHE_DIR") or Path.home() / ".cache" / "codebase-inspector") / "answers.db"


def attach_cache(conn, *, readonly=False):
    """Attach the shared answer cache as `cache`.

    A writable attach creates the file and its tables, so one transaction covers both
    databases. A read-only attach opens an existing file with ``mode=ro`` and does not
    create it, its directory, or a journal. When that file is missing or cannot be
    opened, the cache is skipped and the model connection stays usable.
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
    if not path.is_file():
        return
    uri = path.resolve().as_uri() + "?mode=ro&immutable=1"
    try:
        conn.execute("ATTACH DATABASE ? AS cache", (uri,))
        conn.execute("SELECT 1 FROM cache.sqlite_master LIMIT 1").fetchone()
    except sqlite3.Error:
        try:
            conn.execute("DETACH DATABASE cache")
        except sqlite3.Error:
            pass


def _cached(conn, content_hash):
    row = conn.execute(
        "SELECT summary FROM cache.file_summaries WHERE content_hash = ? AND protocol = ?",
        (content_hash, PROTOCOL_VERSION),
    ).fetchone()
    return row[0] if row else None


def _input_hash(files):
    text = json.dumps([PROTOCOL_VERSION, PARSER_VERSION, [[f[0], f[1]] for f in files]])
    return hashlib.sha1(text.encode()).hexdigest()[:16]


def refresh(conn, root, out=None):
    """Fill file summaries from the cache and open a task for each batch with uncached files.

    Files are batched by folder (the workspace for files at its root) in path order,
    FILES_PER_TASK per batch, and a batch's task lists only its uncached files. A task
    whose files are all answered is marked done.
    """
    from cbi import team
    team.import_answers(conn, out)
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
    refresh_structure(conn, root, out)
    refresh_summaries(conn)
    # Last, so a confirm-structure task created above is visible to the gate.
    concepts.refresh(conn, out, root)


NODE_FIELDS = ("id", "parent_id", "kind", "display_kind", "name", "workspace_id", "path", "summary",
               "summary_source", "content_hash", "attrs")


def _nodes(conn, where, params=()):
    rows = conn.execute(f"SELECT {', '.join(NODE_FIELDS)} FROM nodes WHERE {where}", params)
    return [dict(zip(NODE_FIELDS, r), role=json.loads(r[-1] or "{}").get("role")) for r in rows]


def _summarisable_file(node):
    return node["kind"] == "file" and node["role"] in ("code", "test")


def _summary_child(node):
    """Concept and screen nodes are a second tree and must not change summary inputs."""
    if node["kind"] in ("concept", "screen"):
        return False
    if node["kind"] == "external" and json.loads(node["attrs"] or "{}").get("source") == "concepts":
        return False
    return True


def _record(node):
    """What a parent's brief and input hash see of one child."""
    rec = {"name": node["name"], "display_kind": node["display_kind"], "summary": node["summary"]}
    display_name = json.loads(node["attrs"] or "{}").get("display_name")
    if display_name:
        rec["display_name"] = display_name
    return rec


def _readme(kids):
    return next((k for k in kids if k["kind"] in ("doc", "file") and k["name"].lower().startswith("readme")), None)


def _summary_hash(node, kids):
    """Hash of what a summary task's answer depends on: never node IDs or paths, so it is shared across repos."""
    task_kind = SUMMARY_KINDS[node["kind"]][0]
    name = None if node["kind"] == "workspace" else node["name"]
    readme = _readme(kids)
    text = json.dumps([PROTOCOL_VERSION, task_kind, name, [_record(k) for k in kids], readme and readme["content_hash"]])
    return hashlib.sha1(text.encode()).hexdigest()[:16]


def _set_answer(conn, node, answer):
    """Show answer on the node, or remove the last agent answer when answer is None. True if the node changed."""
    attrs = json.loads(node["attrs"] or "{}")
    base = attrs.pop("enumerated_display_kind", node["display_kind"])
    attrs.pop("display_name", None)
    summary, display_kind = None, base
    if answer:
        summary = answer["summary"]
        display_kind = answer.get("display_kind") or base
        if display_kind != base:
            attrs["enumerated_display_kind"] = base
        if answer.get("display_name"):
            attrs["display_name"] = answer["display_name"]
    elif node["summary_source"] != "agent":
        summary = node["summary"]
    new = {"summary": summary, "summary_source": "agent" if answer else node["summary_source"] if summary else None,
           "display_kind": display_kind, "attrs": json.dumps(attrs, sort_keys=True) if attrs else None}
    if all(node[k] == v for k, v in new.items()):
        return False
    conn.execute("UPDATE nodes SET summary = ?, summary_source = ?, display_kind = ?, attrs = ? WHERE id = ?",
                 (*new.values(), node["id"]))
    node.update(new)
    return True


def refresh_summaries(conn):
    """Bring every group, package and workspace task up to date, bottom-up.

    A node gets a task when it has a code or test file, or a child with a task. The task
    is blocked until each such child has a summary, done when the shared cache holds an
    answer for its current input hash (which is then shown on the node), and open
    otherwise. Because the hash covers child summary text, a parent reopens only when a
    child's summary text changes.
    """
    nodes = {n["id"]: n for n in _nodes(conn, "kind NOT IN ('symbol', 'test')")}
    children = defaultdict(list)
    for n in nodes.values():
        if n["parent_id"] in nodes and _summary_child(n):
            children[n["parent_id"]].append(n)
    files_tasks = defaultdict(list)
    for task_id, node_id in conn.execute("SELECT id, node_id FROM tasks WHERE kind = 'summarise-files' ORDER BY id"):
        files_tasks[node_id].append(task_id)
    structure_tasks = {
        node_id: (task_id, state)
        for task_id, node_id, state in conn.execute(
            "SELECT id, node_id, state FROM tasks WHERE kind = 'confirm-structure'")
    }
    file_to_task = {}
    for task_id, raw in conn.execute("SELECT id, inputs FROM tasks WHERE kind = 'summarise-files'"):
        for fid in json.loads(raw):
            file_to_task[fid] = task_id
    done, changed = {}, []

    def visit_deployable(node):
        """One summarise-deployable task. It stays blocked until confirm-structure is done and every
        member code or test file has a summary. The hash covers that text, so a changed summary reopens it."""
        view = _deployable_inputs(conn, node)
        cs = structure_tasks.get(node["workspace_id"])
        files_ready = all(f["summary"] for f in view["files"])
        ready = bool(cs) and cs[1] == "done" and files_ready
        deps = ([cs[0]] if cs else []) + sorted(
            {file_to_task[f["id"]] for f in view["files"] if not f["summary"] and f["id"] in file_to_task})
        task_kind, prefix = SUMMARY_KINDS["deployable"]
        task_id = f"{prefix}-{hashlib.sha1(node['id'].encode()).hexdigest()[:8]}"
        input_hash = _deployable_hash(node["name"], view)
        answer = _cached_answer(conn, input_hash) if ready else None
        state = "done" if answer else "open" if ready else "blocked"
        if _set_answer(conn, node, answer):
            changed.append(node["id"])
        stored = {
            "entry_points": view["entry_points"],
            "files": [{"path": f["path"], "summary": f["summary"]} for f in view["files"]],
            "packages": [{"name": p["name"], "directory": p["directory"], "summary": p["summary"]} for p in view["packages"]],
        }
        conn.execute(
            "INSERT INTO tasks (id, kind, node_id, input_hash, state, depends_on, inputs) VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET kind = excluded.kind, node_id = excluded.node_id, "
            "input_hash = excluded.input_hash, state = excluded.state, depends_on = excluded.depends_on, "
            "inputs = excluded.inputs",
            (task_id, task_kind, node["id"], input_hash, state, json.dumps(deps), json.dumps(stored)),
        )
        done[node["id"]] = (task_id, state)

    def visit(node):
        kids = sorted(children[node["id"]], key=lambda k: (k["name"], k["id"]))
        for k in kids:
            if k["kind"] in SUMMARY_KINDS:
                visit(k)
        if node["kind"] == "deployable":
            visit_deployable(node)
            return
        if node["kind"] not in SUMMARY_KINDS:
            return
        kids = _without_duplicate_packages(kids, done)
        deps, ready, needed = list(files_tasks[node["id"]]), True, False
        for k in kids:
            if _summarisable_file(k):
                needed, ready = True, ready and k["summary"] is not None
            elif k["id"] in done:
                needed, ready = True, ready and done[k["id"]][1] == "done"
                deps.append(done[k["id"]][0])
        if not needed:
            if _set_answer(conn, node, None):
                changed.append(node["id"])
            return
        task_kind, prefix = SUMMARY_KINDS[node["kind"]]
        task_id = f"{prefix}-{hashlib.sha1(node['id'].encode()).hexdigest()[:8]}"
        input_hash = _summary_hash(node, kids)
        answer = _cached_answer(conn, input_hash) if ready else None
        state = "done" if answer else "open" if ready else "blocked"
        if _set_answer(conn, node, answer):
            changed.append(node["id"])
        conn.execute(
            "INSERT INTO tasks (id, kind, node_id, input_hash, state, depends_on, inputs) VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET kind = excluded.kind, node_id = excluded.node_id, "
            "input_hash = excluded.input_hash, state = excluded.state, depends_on = excluded.depends_on, "
            "inputs = excluded.inputs",
            (task_id, task_kind, node["id"], input_hash, state, json.dumps(deps), json.dumps([k["id"] for k in kids])),
        )
        done[node["id"]] = (task_id, state)

    # ponytail: recomputes every summary task on each scan and submit; limit to changed ancestors if it gets slow.
    for node in nodes.values():
        if node["parent_id"] not in nodes:
            visit(node)
    kinds = sorted({k for k, _ in SUMMARY_KINDS.values()})
    conn.execute(
        f"DELETE FROM tasks WHERE kind IN ({', '.join('?' * len(kinds))}) AND id NOT IN (SELECT value FROM json_each(?))",
        (*kinds, json.dumps([t for t, _ in done.values()])),
    )
    store.reindex(conn, changed)


def _cached_answer(conn, input_hash):
    row = conn.execute("SELECT answer FROM cache.summary_answers WHERE input_hash = ?", (input_hash,)).fetchone()
    return json.loads(row[0]) if row else None


def _input_count(raw):
    try:
        data = json.loads(raw or "[]")
    except ValueError:
        return 0
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        if "files" in data:
            return len(data["files"])
        changes = data.get("changes")
        if isinstance(changes, dict):
            return len(changes.get("groups") or [])
        return sum(len(data.get(key) or []) for key in ("deployables", "packages", "directories"))
    return 0


def task_counts(conn):
    """(open, blocked) across every judgement task. Done tasks are neither."""
    row = conn.execute(
        "SELECT coalesce(sum(state = 'open'), 0), coalesce(sum(state = 'blocked'), 0) FROM tasks"
    ).fetchone()
    return int(row[0]), int(row[1])


def task_headline(open_n, blocked_n):
    """The count line shared by `cbi scan` and `cbi prime`."""
    return f"{open_n} judgement tasks open, {blocked_n} blocked"


def _summary_dir(node):
    """Directory a package or folder covers, with no trailing slash. Empty is the workspace root."""
    path = node.get("path") or ""
    if not path:
        path = json.loads(node["attrs"] or "{}").get("directory") or ""
    return path.strip("/")


def _without_duplicate_packages(kids, done):
    """Drop a package that has no summary task when a sibling folder is the same directory.

    Manifest detection adds a package node beside the folder that already holds the files.
    The folder is the one with a summary. The root package has an empty directory and stays.
    A package that has its own summary task stays too.
    """
    folders = {_summary_dir(kid) for kid in kids if kid["kind"] == "group"}
    folders.discard("")
    return [
        kid for kid in kids
        if not (kid["kind"] == "package" and kid["id"] not in done and _summary_dir(kid) in folders)
    ]


def open_tasks(conn, kind=None, limit=None, offset=None):
    sql = (
        "SELECT t.id, t.kind, t.node_id, n.display_kind, n.path, t.inputs FROM tasks t "
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
    if offset:
        if not limit:
            sql += " LIMIT -1"
        sql += " OFFSET ?"
        params.append(offset)
    return [
        {"id": r[0], "kind": r[1], "node_id": r[2], "node_display_kind": r[3], "node_path": r[4],
         "files": _input_count(r[5])}
        for r in conn.execute(sql, params)
    ]


# --- confirm-structure ----------------------------------------------------------


def _bare_directories(conn, ws_id, packages):
    """Top-level directories that contain code or tests, with no manifest under them and no package."""
    row = conn.execute("SELECT attrs FROM nodes WHERE id = ?", (ws_id,)).fetchone()
    root = json.loads(row[0] or "{}").get("root") or "" if row else ""
    covered = {p["directory"].split("/")[0] for p in packages.values()
               if p["ws"].id == ws_id and p.get("directory")}
    code_tops, manifest_tops = set(), set()
    for path, role in conn.execute(
        "SELECT path, json_extract(attrs, '$.role') FROM nodes WHERE workspace_id = ? AND kind = 'file'", (ws_id,)):
        if not path or "/" not in path:
            continue
        top = path.split("/")[0]
        if role in ("code", "test"):
            code_tops.add(top)
        if _MANIFEST.search(path):
            manifest_tops.add(top)
    return [posixpath.join(root, d) if root else d for d in sorted(code_tops - manifest_tops - covered)]


def _content_root(root):
    """A filesystem path, or a commit tree left as it is so reads come from git objects."""
    return Path(root) if isinstance(root, (str, bytes)) else root


def _snapshots(conn, root):
    """Manifest detection per workspace, before structure.json. Paths are from the top repo."""
    deployables, packages, _externals = manifests._detect(conn, _content_root(root), None)
    found = defaultdict(lambda: {"deployables": [], "packages": [], "directories": []})
    for wid, in conn.execute("SELECT id FROM nodes WHERE kind = 'workspace'"):
        found[wid]
    for did, d in deployables.items():
        ws = d["ws"]
        resolved, unresolved = [], []
        for raw, src in d["entries"]:
            (resolved if src else unresolved).append(ws.top(src) if src else raw)
        found[ws.id]["deployables"].append({
            "id": did, "name": d["name"], "display_kind": d["display_kind"], "evidence": d["evidence"],
            "entry_points": sorted(resolved), "unresolved": sorted(set(unresolved)),
        })
    for pid, p in packages.items():
        found[p["ws"].id]["packages"].append({
            "id": pid, "name": p["name"], "display_kind": p["display_kind"],
            "directory": p["ws"].top(p.get("directory") or ""),
        })
    for wid, snap in found.items():
        snap["deployables"].sort(key=lambda d: (d["name"], d["id"]))
        snap["packages"].sort(key=lambda p: (p["name"], p["id"]))
        snap["directories"] = _bare_directories(conn, wid, packages)
    return dict(found)


def _structure_hash(snap):
    """Hash of the detection an answer corrects. Ids are left out so another repo with the same
    names and paths shares the cached answer; applying the answer does not change this hash."""
    portable = {
        "deployables": [{k: d[k] for k in ("display_kind", "entry_points", "evidence", "name", "unresolved")}
                        for d in snap["deployables"]],
        "packages": [{k: p[k] for k in ("directory", "display_kind", "name")} for p in snap["packages"]],
        "directories": snap["directories"],
    }
    return hashlib.sha1(json.dumps([PROTOCOL_VERSION, "confirm-structure", portable], sort_keys=True).encode()).hexdigest()[:16]


def _canon_item(item, keys):
    out = {}
    for key in keys:
        if key not in item or item[key] in (None, "", [], False):
            continue
        value = item[key]
        if isinstance(value, str):
            value = value.strip()
            if not value:
                continue
        elif isinstance(value, list):
            value = [v.strip() if isinstance(v, str) else v for v in value]
            if not value:
                continue
        out[key] = value
    return out


def _canon_doc(doc):
    def sort_key(item):
        return (item.get("id") or "", item.get("name") or "", item.get("directory") or "")
    return {
        "deployables": sorted((_canon_item(i, _DEP_KEYS) for i in doc.get("deployables") or []), key=sort_key),
        "packages": sorted((_canon_item(i, _PKG_KEYS) for i in doc.get("packages") or []), key=sort_key),
    }


def _dumps(doc):
    return json.dumps(_canon_doc(doc), indent=2, sort_keys=True) + "\n"


def _load_doc(text):
    try:
        data = json.loads(text) if text else {}
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    return {key: [i for i in data.get(key) or [] if isinstance(i, dict)] for key in ("deployables", "packages")}


def _owner_id(iid, ws_ids):
    if not isinstance(iid, str):
        return None
    for ws_id in sorted(ws_ids, key=len, reverse=True):
        if iid.startswith(ws_id + ":"):
            return ws_id
    return None


def _slice(doc, ws_id):
    def keep(items):
        return [i for i in items if _owner_id(i.get("id"), [ws_id]) == ws_id]
    return _canon_doc({"deployables": keep(doc.get("deployables") or []), "packages": keep(doc.get("packages") or [])})


def _merge_doc(existing, updates, drop_unscoped):
    """Replace items owned by workspaces in updates. Unscoped items (no id) are dropped on submit."""
    doc = {"deployables": [], "packages": []}
    for kind in doc:
        for item in existing.get(kind) or []:
            owner = _owner_id(item.get("id"), updates)
            if owner in updates or (owner is None and drop_unscoped):
                continue
            doc[kind].append(item)
        for ans in updates.values():
            doc[kind].extend(ans.get(kind) or [])
    return doc


def _map_ids(doc, fn):
    out = {"deployables": [], "packages": []}
    for kind in out:
        for item in doc[kind]:
            item = dict(item)
            if isinstance(item.get("id"), str):
                item["id"] = fn(item["id"])
            out[kind].append(item)
    return out


def _port(doc, ws_id):
    """Store ids as `@:deployable:<name>` so the cache applies to another workspace of the same shape."""
    prefix = ws_id + ":"
    return _map_ids(doc, lambda iid: "@:" + iid[len(prefix):] if iid.startswith(prefix) else iid)


def _unport(doc, ws_id):
    return _map_ids(doc, lambda iid: ws_id + iid[1:] if iid.startswith("@:") else iid)


def _with_ids(doc, ws_id):
    out = {"deployables": [], "packages": []}
    for kind, marker, keys in (("deployables", ":deployable:", _DEP_KEYS), ("packages", ":package:", _PKG_KEYS)):
        for item in doc[kind]:
            item = _canon_item(item, keys)
            if item.get("name") and not item.get("id") and not item.get("remove"):
                item["id"] = f"{ws_id}{marker}{item['name']}"
            out[kind].append(item)
    return out


def _atomic_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def refresh_structure(conn, root, out=None, force_ws=None):
    """Open or close one confirm-structure task per workspace. Returns True if detection was rerun.

    A cached answer is written to structure.json when the file is missing (another repo with the
    same detection) or when force_ws is that workspace (its answer was just submitted). A file that
    already differs from the cache is left as it is and the task stays open.
    """
    snapshots = _snapshots(conn, root)
    path = Path(out) / "structure.json" if out else None
    existing_text = path.read_text() if path and path.exists() else None
    existing = _load_doc(existing_text)
    updates = {}
    for ws_id, snap in snapshots.items():
        cached = _cached_answer(conn, _structure_hash(snap))
        if cached and (existing_text is None or ws_id == force_ws):
            updates[ws_id] = _unport(cached, ws_id)
    current = _canon_doc(existing)
    rebuilt = False
    if path and updates:
        merged = _merge_doc(existing, updates, drop_unscoped=force_ws is not None)
        text = _dumps(merged)
        if _canon_doc(merged) != current:
            _atomic_write(path, text)
            resolve.resolve(conn, root)
            manifests.apply(conn, root, text)
            rebuilt = True
        elif existing_text != text:
            _atomic_write(path, text)
        current = _canon_doc(merged)
    wanted = []
    for ws_id, snap in snapshots.items():
        digest = _structure_hash(snap)
        cached = _cached_answer(conn, digest)
        answered = _canon_doc(_unport(cached, ws_id)) if cached else None
        state = "done" if answered is not None and _slice(current, ws_id) == answered else "open"
        task_id = f"cs-{hashlib.sha1(ws_id.encode()).hexdigest()[:8]}"
        wanted.append(task_id)
        stored = {key: snap[key] for key in ("deployables", "packages", "directories")}
        overrides = _slice(current, ws_id)
        if overrides["deployables"] or overrides["packages"]:
            stored["overrides"] = overrides
        conn.execute(
            "INSERT INTO tasks (id, kind, node_id, input_hash, state, depends_on, inputs) "
            "VALUES (?, 'confirm-structure', ?, ?, ?, '[]', ?) "
            "ON CONFLICT(id) DO UPDATE SET node_id = excluded.node_id, input_hash = excluded.input_hash, "
            "state = excluded.state, depends_on = '[]', inputs = excluded.inputs",
            (task_id, ws_id, digest, state, json.dumps(stored, sort_keys=True)),
        )
    conn.execute(
        "DELETE FROM tasks WHERE kind = 'confirm-structure' AND id NOT IN (SELECT value FROM json_each(?))",
        (json.dumps(wanted),),
    )
    return rebuilt


def _member_ids(conn, deployable_id):
    files = [r[0] for r in conn.execute(
        "SELECT n.id FROM edges e JOIN nodes n ON n.id = e.src "
        "WHERE e.kind = 'part_of' AND e.dst = ? AND n.kind = 'file' ORDER BY n.path", (deployable_id,))]
    packages = {r[0]: r[1] for r in conn.execute("SELECT id, name FROM nodes WHERE kind = 'package'")}
    found = set()
    for dst, in conn.execute("SELECT dst FROM edges WHERE kind = 'depends_on' AND src = ?", (deployable_id,)):
        if dst in packages:
            found.add(dst)
    if files:
        for dst, in conn.execute(
            "SELECT dst FROM edges WHERE kind = 'part_of' AND src IN (SELECT value FROM json_each(?))",
            (json.dumps(files),)):
            if dst in packages:
                found.add(dst)
    return files, sorted(found, key=lambda i: (packages[i], i))


def _by_ids(conn, ids):
    if not ids:
        return {}
    return {n["id"]: n for n in _nodes(conn, "id IN (SELECT value FROM json_each(?))", (json.dumps(ids),))}


def _deployable_inputs(conn, node):
    attrs = json.loads(node["attrs"] or "{}")
    entries = [_read_path(conn, node["workspace_id"], p) for p in attrs.get("entry_points") or []]
    file_ids, package_ids = _member_ids(conn, node["id"])
    nodes = _by_ids(conn, file_ids + package_ids)
    files = []
    for fid in file_ids:
        n = nodes.get(fid)
        if not n or not _summarisable_file(n):
            continue
        files.append({"id": fid, "path": _read_path(conn, n["workspace_id"], n["path"]), "summary": n["summary"]})
    files.sort(key=lambda f: f["path"])
    packages = []
    for pid in package_ids:
        n = nodes.get(pid)
        if not n:
            continue
        directory = json.loads(n["attrs"] or "{}").get("directory") or ""
        packages.append({
            "name": n["name"],
            "directory": _read_path(conn, n["workspace_id"], directory) if directory else "",
            "summary": n["summary"],
        })
    packages.sort(key=lambda p: (p["name"], p["directory"]))
    return {"entry_points": entries, "files": files, "packages": packages}


def _deployable_hash(name, view):
    body = [PROTOCOL_VERSION, "summarise-deployable", name, view["entry_points"],
            [{"path": f["path"], "summary": f["summary"]} for f in view["files"]],
            [{"name": p["name"], "directory": p["directory"], "summary": p["summary"]} for p in view["packages"]]]
    return hashlib.sha1(json.dumps(body, sort_keys=True).encode()).hexdigest()[:16]


def _task(conn, task_id):
    row = conn.execute("SELECT kind, node_id, input_hash, state, inputs, depends_on FROM tasks WHERE id = ?",
                       (task_id,)).fetchone()
    if not row:
        raise UnknownTask(f"no task {task_id}; run `cbi tasks` to list open tasks")
    return {"id": task_id, "kind": row[0], "node_id": row[1], "input_hash": row[2], "state": row[3],
            "inputs": json.loads(row[4]), "depends_on": json.loads(row[5])}


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


README_LINES = 40


def brief(conn, task_id, root=None):
    """Everything an agent needs to answer a task, as a dict. root is the repo root, for README heads."""
    task = _task(conn, task_id)
    out = {
        "id": task_id,
        "kind": task["kind"],
        "state": task["state"],
        "node_id": task["node_id"],
        "input_hash": task["input_hash"],
        "instructions": INSTRUCTIONS[task["kind"]],
    }
    if task["kind"] == "define-concepts":
        out.update(concepts.brief_body(conn, task))
        out["answer_schema"] = SCHEMAS[task["kind"]]
        return out
    if task["kind"] == "sketch-screens":
        out.update(screens.brief_body(conn, task, root))
        out["answer_schema"] = SCHEMAS[task["kind"]]
        return out
    if task["kind"] == "summarise-change":
        data = task["inputs"] if isinstance(task["inputs"], dict) else {}
        out["base"] = data.get("base")
        out["head"] = data.get("head")
        out["changes"] = data.get("changes")
        out["answer_schema"] = SCHEMAS[task["kind"]]
        return out
    if task["kind"] == "confirm-structure":
        out.update(_structure_brief(conn, task))
    elif task["kind"] == "summarise-deployable":
        out.update(_deployable_brief(conn, task))
    elif task["kind"] != "summarise-files":
        out.update(_summary_brief(conn, task, root))
    else:
        out["files"] = _file_outline(conn, task)
    out["answer_schema"] = SCHEMAS[task["kind"]]
    return out


def _file_outline(conn, task):
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
    return files


def _waiting(conn, task):
    return [t for t, in conn.execute(
        "SELECT id FROM tasks WHERE id IN (SELECT value FROM json_each(?)) AND state != 'done' ORDER BY id",
        (json.dumps(task["depends_on"]),),
    )]


def _classify_directories(conn, directories):
    """Split bare directories into libraries and the rest.

    A library has a source file imported by production code outside the directory.
    A test import does not count: tested app trees are not libraries. Anything else
    looks like scripts or tests.
    """
    if not directories:
        return [], []
    roots = {wid: root or "" for wid, root in conn.execute(
        "SELECT id, json_extract(attrs, '$.root') FROM nodes WHERE kind = 'workspace'")}
    files = {}
    for fid, wid, path, role in conn.execute(
        "SELECT id, workspace_id, path, json_extract(attrs, '$.role') "
        "FROM nodes WHERE kind = 'file' AND path IS NOT NULL"
    ):
        root = roots.get(wid) or ""
        files[fid] = (posixpath.join(root, path) if root else path, role)
    incoming = []
    for src, dst in conn.execute("SELECT src, dst FROM edges WHERE kind = 'imports'"):
        src_info, dst_info = files.get(src), files.get(dst)
        if src_info and dst_info and src_info[1] == "code" and dst_info[1] == "code":
            incoming.append((src_info[0], dst_info[0]))
    libraries, scripts = [], []
    for directory in directories:
        prefix = directory.rstrip("/") + "/"
        hit = any(dst.startswith(prefix) and not src.startswith(prefix) for src, dst in incoming)
        (libraries if hit else scripts).append(directory)
    return libraries, scripts


def directory_note(libraries, scripts):
    """Comment lines for the brief. They are not part of the answer JSON."""
    lines = []
    if libraries:
        lines.append("# library, source files imported from elsewhere: " + ", ".join(libraries))
    if scripts:
        lines.append("# scripts or tests, no production file outside imports them: " + ", ".join(scripts))
    return lines


def structure_add_line(libraries):
    """One sentence showing how to add a real manifest-less library, or None."""
    if not libraries:
        return None
    directory = libraries[0].rstrip("/")
    name = posixpath.basename(directory)
    if not name:
        return None
    return "To add that library, put this in packages: " + json.dumps(
        {"name": name, "directory": directory}, separators=(", ", ": "))


def _structure_brief(conn, task):
    [node] = _nodes(conn, "id = ?", (task["node_id"],))
    data = task["inputs"] if isinstance(task["inputs"], dict) else {}
    directories = data.get("directories") or []
    libraries, scripts = _classify_directories(conn, directories)
    out = {"node": {"name": node["name"], "display_kind": node["display_kind"], "path": _top_path(conn, node)},
           "deployables": data.get("deployables") or [], "packages": data.get("packages") or [],
           "directories": directories, "libraries": libraries,
           "directory_note": directory_note(libraries, scripts)}
    if data.get("overrides"):
        out["overrides"] = data["overrides"]
    return out


def _deployable_brief(conn, task):
    [node] = _nodes(conn, "id = ?", (task["node_id"],))
    data = task["inputs"] if isinstance(task["inputs"], dict) else {}
    out = {"node": {"name": node["name"], "display_kind": node["display_kind"], "path": _top_path(conn, node)},
           "entry_points": data.get("entry_points") or [], "files": data.get("files") or [],
           "packages": data.get("packages") or []}
    if task["state"] == "blocked":
        out["waiting_on"] = _waiting(conn, task)
    return out


def _top_path(conn, node):
    if node["kind"] == "workspace":
        return json.loads(node["attrs"] or "{}").get("root", "")
    return _read_path(conn, node["workspace_id"], node["path"])


def _summary_brief(conn, task, root):
    [node] = _nodes(conn, "id = ?", (task["node_id"],))
    kids = {k["id"]: k for k in _nodes(conn, "id IN (SELECT value FROM json_each(?))", (json.dumps(task["inputs"]),))}
    kids = [kids[i] for i in task["inputs"] if i in kids]
    out = {"node": {"name": node["name"], "display_kind": node["display_kind"], "path": _top_path(conn, node)},
           "children": [dict(_record(k), path=_top_path(conn, k)) for k in kids]}
    readme = _readme(kids)
    if readme:
        path = _top_path(conn, readme)
        head = None
        if root:
            try:
                src = _content_root(root) / path
                if isinstance(src, Path):
                    with open(src, errors="replace") as f:
                        head = "".join(line for _, line in zip(range(README_LINES), f))
                else:
                    lines = src.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
                    head = "".join(lines[:README_LINES])
            except OSError:
                pass
        out["readme"] = {"path": path, "head": head}
    if task["state"] == "blocked":
        out["waiting_on"] = _waiting(conn, task)
    return out


def answer_template(b):
    """A skeleton answer for a brief, with "..." where the agent writes."""
    if b["kind"] == "summarise-change":
        return {"input_hash": b["input_hash"], "narrative": "..."}
    if b["kind"] == "define-concepts":
        return concepts.template(b)
    if b["kind"] == "sketch-screens":
        return screens.template(b)
    if b["kind"] == "summarise-files":
        return {"input_hash": b["input_hash"], "files": [{"path": f["path"], "summary": "..."} for f in b["files"]]}
    if b["kind"] == "confirm-structure":
        return {"input_hash": b["input_hash"], "deployables": [], "packages": []}
    return {"input_hash": b["input_hash"], "summary": "..."}


def _format_tail(b, lines):
    if b["kind"] == "confirm-structure" and b.get("directories"):
        lines += ["", STRUCTURE_EMPTY, *(b.get("directory_note") or [])]
        add = structure_add_line(b.get("libraries") or [])
        if add:
            lines.append(add)
    lines += ["", "## Answer schema", json.dumps(b["answer_schema"], indent=2), "", "## Answer template",
              json.dumps(answer_template(b), indent=2), "",
              f"Submit with: cbi submit {b['id']} answer.json   (or pipe the JSON to `cbi submit {b['id']} -`)"]
    return "\n".join(lines)


def _format_structure(b):
    node = b["node"]
    lines = [f"# Task {b['id']}: {b['kind']} ({b['state']})", f"node: {node['display_kind']} {node['path'] or node['name']}",
             f"input_hash: {b['input_hash']}", "", b["instructions"], "", "## Deployables"]
    if not b["deployables"]:
        lines.append("  (none)")
    for d in b["deployables"]:
        lines.append(f"  {d['display_kind']:<16} {d['name']}  {d['id']}")
        lines.append(f"  {'':<16} {d['evidence']}")
        lines.extend(f"  {'':<16} entry: {entry}" for entry in d["entry_points"])
        lines.extend(f"  {'':<16} unresolved: {raw}" for raw in d["unresolved"])
    lines += ["", "## Packages"]
    if b["packages"]:
        lines.extend(f"  {p['display_kind']:<16} {p['name']}  {p['directory']}" for p in b["packages"])
    else:
        lines.append("  (none)")
    lines += ["", "## Top-level directories with code and no manifest"]
    lines.extend(f"  {d}" for d in b["directories"])
    if not b["directories"]:
        lines.append("  (none)")
    if b.get("overrides"):
        lines += ["", "## Current structure.json", json.dumps(b["overrides"], indent=2)]
    return _format_tail(b, lines)


def _format_deployable(b):
    node = b["node"]
    lines = [f"# Task {b['id']}: {b['kind']} ({b['state']})", f"node: {node['display_kind']} {node['path'] or node['name']}",
             f"input_hash: {b['input_hash']}", "", b["instructions"], ""]
    if b.get("waiting_on"):
        lines += [f"Blocked: waiting on {', '.join(b['waiting_on'])}. Do those first.", ""]
    lines.append("## Entry points")
    lines.extend(f"  {entry}" for entry in b["entry_points"])
    if not b["entry_points"]:
        lines.append("  (none)")
    lines += ["", "## Member files"]
    if b["files"]:
        lines.extend(f"  {f['path']}" + (f": {f['summary']}" if f["summary"] else "") for f in b["files"])
    else:
        lines.append("  (none)")
    lines += ["", "## Member packages"]
    if b["packages"]:
        lines.extend(f"  {p['name']}  {p['directory']}" + (f": {p['summary']}" if p["summary"] else "") for p in b["packages"])
    else:
        lines.append("  (none)")
    return _format_tail(b, lines)


def _format_change(b):
    lines = [f"# Task {b['id']}: summarise-change ({b['state']})",
             f"base: {b.get('base')}", f"head: {b.get('head')}",
             f"input_hash: {b['input_hash']}", "", b["instructions"], "",
             "## Change list", json.dumps(b.get("changes"), indent=2, sort_keys=True)]
    return _format_tail(b, lines)


def format_brief(b):
    """Text form of a group, workspace, structure, deployable or change brief."""
    if b["kind"] == "summarise-change":
        return _format_change(b)
    if b["kind"] == "confirm-structure":
        return _format_structure(b)
    if b["kind"] == "summarise-deployable":
        return _format_deployable(b)
    node = b["node"]
    lines = [f"# Task {b['id']}: {b['kind']} ({b['state']})", f"node: {node['display_kind']} {node['path'] or node['name']}",
             f"input_hash: {b['input_hash']}", "", b["instructions"], ""]
    if b.get("waiting_on"):
        lines += [f"Blocked: waiting on {', '.join(b['waiting_on'])}. Do those first.", ""]
    lines.append("## Children")
    for c in b["children"]:
        name = f"{c['name']} ({c['display_name']})" if c.get("display_name") else c["name"]
        lines.append(f"  {c['display_kind']:<12} {name}" + (f": {c['summary']}" if c["summary"] else ""))
    if "readme" in b:
        lines += ["", f"## README head ({b['readme']['path']})", (b["readme"]["head"] or "(not read; open the file)").rstrip()]
    return _format_tail(b, lines)


def _check(value, schema, path, errors, root=None):
    """Collect `<json path>: <problem>` strings for value against a small JSON Schema subset."""
    root = schema if root is None else root
    if "$ref" in schema:
        target = root
        for part in schema["$ref"].removeprefix("#/").split("/"):
            target = target[part]
        return _check(value, target, path, errors, root)
    kind = schema["type"]
    if kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            errors.append(f"{path}: expected integer, got {type(value).__name__}")
            return
        low, high = schema.get("minimum"), schema.get("maximum")
        if (low is not None and value < low) or (high is not None and value > high):
            errors.append(f"{path}: {value} is outside {low}..{high}")
        return
    if not isinstance(value, {"object": dict, "array": list, "string": str, "boolean": bool}[kind]):
        errors.append(f"{path}: expected {kind}, got {type(value).__name__}")
        return
    if kind == "boolean":
        return
    if kind == "object":
        props = schema["properties"]
        errors.extend(f"{path}.{key}: required" for key in schema.get("required", ()) if key not in value)
        if not schema.get("additionalProperties", True):
            errors.extend(f"{path}.{key}: unknown key" for key in value if key not in props)
        for key, sub in props.items():
            if key in value:
                _check(value[key], sub, f"{path}.{key}", errors, root)
    elif kind == "array":
        if len(value) < schema.get("minItems", 0):
            errors.append(f"{path}: needs at least {schema['minItems']} item(s)")
        for i, item in enumerate(value):
            _check(item, schema["items"], f"{path}[{i}]", errors, root)
    else:
        if "enum" in schema and value not in schema["enum"]:
            errors.append(f"{path}: {value!r} is not one of {', '.join(schema['enum'])}")
        length = len(value.strip())
        if length < schema.get("minLength", 0):
            errors.append(f"{path}: empty")
        if length > schema.get("maxLength", length):
            errors.append(f"{path}: {length} characters, at most {schema['maxLength']}")


def _tracked_paths(conn):
    roots = {r[0]: json.loads(r[1] or "{}").get("root") or ""
             for r in conn.execute("SELECT id, attrs FROM nodes WHERE kind = 'workspace'")}
    return [posixpath.join(roots.get(ws) or "", path) if roots.get(ws) else path
            for ws, path in conn.execute(
                "SELECT workspace_id, path FROM nodes WHERE kind IN ('file', 'doc') AND path IS NOT NULL")]


def _repo_path(value, path, errors):
    norm = posixpath.normpath(value.strip())
    if value.strip().startswith("/") or norm == ".." or norm.startswith("../"):
        errors.append(f"{path}: expected a path relative to the repo root")


def _under(tracked, directory):
    directory = posixpath.normpath(directory.strip())
    return any(p == directory or p.startswith(directory + "/") for p in tracked)


def _structure_errors(answer, task, conn):
    """Schema and semantic problems for a confirm-structure answer, all at once."""
    errors = []
    _check(answer, SCHEMAS["confirm-structure"], "$", errors)
    if not isinstance(answer, dict):
        return errors
    snap = task["inputs"] if isinstance(task["inputs"], dict) else {}
    known = {}
    for kind, label in (("deployables", "deployable"), ("packages", "package")):
        ids = {item["id"] for item in snap.get(kind) or [] if isinstance(item, dict) and item.get("id")}
        for item in (snap.get("overrides") or {}).get(kind) or []:
            if isinstance(item, dict) and item.get("id"):
                ids.add(item["id"])
        known[kind] = (ids, label)
    tracked = _tracked_paths(conn)
    for kind in ("deployables", "packages"):
        items = answer.get(kind)
        if not isinstance(items, list):
            continue
        ids, label = known[kind]
        seen = set()
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            path = f"$.{kind}[{i}]"
            iid, name, remove = item.get("id"), item.get("name"), item.get("remove")
            if isinstance(iid, str):
                if iid not in ids:
                    errors.append(f"{path}.id: {iid!r} is not a detected {label}")
                if iid in seen:
                    errors.append(f"{path}.id: {iid!r} given twice")
                seen.add(iid)
            elif isinstance(name, str) and name.strip():
                if name.strip() in seen:
                    errors.append(f"{path}.name: {name.strip()!r} given twice")
                seen.add(name.strip())
            if remove is True:
                if not isinstance(iid, str):
                    errors.append(f"{path}.id: required to remove")
                continue
            if remove not in (None, False):
                continue
            if "name" not in item:
                errors.append(f"{path}.name: required")
            if kind == "packages" and "directory" not in item:
                errors.append(f"{path}.directory: required")
            directory = item.get("directory")
            if kind == "packages" and isinstance(directory, str) and directory.strip():
                _repo_path(directory, f"{path}.directory", errors)
                if not _under(tracked, directory):
                    errors.append(f"{path}.directory: no tracked file under {directory.strip()!r}")
            entries = item.get("entry_points")
            if isinstance(entries, list):
                for j, entry in enumerate(entries):
                    if isinstance(entry, str) and entry.strip():
                        _repo_path(entry, f"{path}.entry_points[{j}]", errors)
    return errors


def _submit_structure(conn, task, answer, root, out):
    if root is None or out is None:
        raise AnswerError("$: confirm-structure needs the repo and the model directory")
    doc = _with_ids({"deployables": answer["deployables"], "packages": answer["packages"]}, task["node_id"])
    portable = _port(_canon_doc(doc), task["node_id"])

    def write():
        previous = _cached_answer(conn, task["input_hash"])
        conn.execute("INSERT OR REPLACE INTO cache.summary_answers (input_hash, answer) VALUES (?, ?)",
                     (task["input_hash"], json.dumps(portable, sort_keys=True)))
        before = _open_ids(conn)
        rebuilt = refresh_structure(conn, root, out, force_ws=task["node_id"])
        refresh_summaries(conn)
        concepts.refresh(conn, out, root)
        if rebuilt:
            store.reindex(conn)
        _sync_team(conn, out)
        return previous, rebuilt, _opened(before, conn)

    previous, rebuilt, opened = store.retry_write(conn, write)
    if previous == portable and not rebuilt:
        return f"{task['id']}: already accepted, nothing changed"
    return f"{task['id']}: accepted{opened}"


def _file_errors(conn, task, answer):
    """(errors, files by path) for a summarise-files answer. files is None when the shape is wrong."""
    files = {f["path"]: f for f in _task_files(conn, task)}
    listed = answer.get("files")
    if not isinstance(listed, list):
        return ["$.files: expected an array"], None
    seen, errors = set(), []
    for i, entry in enumerate(listed):
        if not isinstance(entry, dict):
            continue
        path = entry.get("path")
        if path not in files:
            errors.append(f"$.files[{i}].path: {path!r} is not in this task")
        elif path in seen:
            errors.append(f"$.files[{i}].path: {path!r} given twice")
        seen.add(path)
    errors.extend(f"$.files: missing {path!r}" for path in files if path not in seen)
    return errors, files


def _validated(conn, task_id, text):
    """The parsed answer, after the checks that do not write. Raises AnswerError."""
    task = _task(conn, task_id)
    try:
        answer = json.loads(text)
    except json.JSONDecodeError as err:
        raise AnswerError(f"$: not valid JSON ({err})") from None
    errors = _structure_errors(answer, task, conn) if task["kind"] == "confirm-structure" else []
    if task["kind"] != "confirm-structure":
        _check(answer, SCHEMAS[task["kind"]], "$", errors)
    if errors:
        raise AnswerError("\n".join(errors))
    if task["state"] == "blocked":
        raise AnswerError(f"$: task {task_id} is blocked; run `cbi task {task_id}` to see what it waits on")
    if answer["input_hash"] != task["input_hash"]:
        raise AnswerError(
            f"$.input_hash: stale. The task's inputs changed since this brief was issued; "
            f"run `cbi task {task_id}` again and answer the new brief."
        )
    if task["kind"] == "summarise-files":
        extra, _files = _file_errors(conn, task, answer)
        if extra:
            raise AnswerError("\n".join(extra))
    return task, answer


def check(conn, task_id, text, root=None):
    """Run submit's checks and write nothing. Returns warnings. Raises AnswerError.

    root is accepted so callers can pass the same arguments as submit. The checks read the model.
    """
    task, answer = _validated(conn, task_id, text)
    if task["kind"] == "define-concepts":
        errors, warnings = concepts.problems(conn, answer)
        if errors:
            raise AnswerError("\n".join(errors + warnings))
        return warnings
    if task["kind"] == "sketch-screens":
        errors = screens.problems(conn, answer, root)
        if errors:
            raise AnswerError("\n".join(errors))
    return []


def submit(conn, task_id, text, root=None, out=None):
    """Validate and store an answer in one transaction. Returns a one-line report.

    Raises AnswerError when the answer is malformed, misses or adds files, or was
    written for inputs that have since changed. root and out are the repo and the model
    directory; accepting confirm-structure writes structure.json there and reruns detection.
    A busy database rolls the transaction back and retries it.
    """
    task, answer = _validated(conn, task_id, text)
    if task["kind"] == "confirm-structure":
        return _submit_structure(conn, task, answer, root, out)
    if task["kind"] == "define-concepts":
        return concepts.accept(conn, task, answer, out, root)
    if task["kind"] == "sketch-screens":
        return screens.accept(conn, task, answer, out, root)
    if task["kind"] == "summarise-change":
        return _submit_change(conn, task, answer, out)
    if task["kind"] != "summarise-files":
        return _submit_summary(conn, task, answer, out)
    _errors, files = _file_errors(conn, task, answer)

    def write():
        changed = 0
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
        before = _open_ids(conn)
        refresh_summaries(conn)
        _sync_team(conn, out)
        return changed, _opened(before, conn)

    changed, opened = store.retry_write(conn, write)
    if not changed:
        return f"{task_id}: already accepted, nothing changed"
    return f"{task_id}: accepted {len(answer['files'])} file summaries{opened}"


def _submit_change(conn, task, answer, out=None):
    """Cache the narrative by the task's input hash, which is the commit pair, and close the task."""
    stored = {"narrative": answer["narrative"].strip()}

    def write():
        previous = _cached_answer(conn, task["input_hash"])
        conn.execute("INSERT OR REPLACE INTO cache.summary_answers (input_hash, answer) VALUES (?, ?)",
                     (task["input_hash"], json.dumps(stored, sort_keys=True)))
        conn.execute("UPDATE tasks SET state = 'done' WHERE id = ?", (task["id"],))
        _sync_team(conn, out)
        return previous

    previous = store.retry_write(conn, write)
    if previous == stored:
        return f"{task['id']}: already accepted, nothing changed"
    return f"{task['id']}: accepted"


def _submit_summary(conn, task, answer, out=None):
    stored = {k: v.strip() for k, v in answer.items() if k != "input_hash"}

    def write():
        changed = _cached_answer(conn, task["input_hash"]) != stored
        conn.execute("INSERT OR REPLACE INTO cache.summary_answers (input_hash, answer) VALUES (?, ?)",
                     (task["input_hash"], json.dumps(stored, sort_keys=True)))
        before = _open_ids(conn)
        refresh_summaries(conn)
        _sync_team(conn, out)
        return changed, _opened(before, conn)

    changed, opened = store.retry_write(conn, write)
    if not changed:
        return f"{task['id']}: already accepted, nothing changed"
    return f"{task['id']}: accepted{opened}"


def _sync_team(conn, out):
    from cbi import team
    team.sync(conn, out)


def sized(text):
    """Text with a `size: N bytes` line under the title. N is the UTF-8 length of the result."""
    if not text.endswith("\n"):
        text += "\n"
    head, sep, tail = text.partition("\n")

    def build(n):
        return f"{head}\nsize: {n} bytes{sep}{tail}"

    n = len(build(0).encode())
    while True:
        out = build(n)
        actual = len(out.encode())
        if actual == n:
            return out
        n = actual


def _open_ids(conn):
    return {r[0] for r in conn.execute("SELECT id FROM tasks WHERE state = 'open'")}


def _opened(before, conn):
    opened = sorted(_open_ids(conn) - before)
    return f"; now open: {', '.join(opened)}" if opened else ""

"""Concept map: `.cbi/concepts.json` projected into the model, and the define-concepts task.

Concepts are a second hierarchy beside the file tree. A leaf owns tracked files
through `owns` edges; `relates` edges carry the label, via, at, minor, basis and kind the
agent wrote. A concept's attrs hold `role`, `entry` and `entry_file`. `entry` is true when
the concept or a descendant owns a deployable entry point, unless a hosts relationship
points at it or the answer set `entry`. A hosted concept still records the entry file it
owns; that file does not count for the host or the host's ancestors. The file is applied
on every scan. Coverage checks run on submit, not on a hand edit.
"""

import hashlib
import json
import posixpath
from collections import defaultdict

from cbi import store

ROLES = ("ui", "app", "service", "core", "data")
ROLE_DISPLAY = {"ui": "interface", "app": "app", "service": "service", "core": "core", "data": "data"}
KINDS = ("platform", "cli", "saas", "terminal", "storage")
KIND_ALIAS = {"os": "terminal"}
KIND_DISPLAY = {kind: kind for kind in KINDS}
MAX_CHILDREN = 9

# Other tracked files are optional. Code and test files stay exactly-once.
PLACEMENT = (
    "Place delivery and infrastructure files in a concept when the repo has them: "
    "ci/, pipelines, compose files, env/, sql/, seeds/, scripts and docs. "
    "Give each test suite (unit, integration, e2e) its own concept, with relationships "
    "to the concepts it tests. Describe testing endpoints and fixture builders accurately from the code."
)

CHECKS = [
    "every code and test file is owned by exactly one leaf",
    "any other tracked file is owned by at most one leaf and may be left unowned",
    "only leaves own files",
    "ids are unique across concepts and externals",
    "roles are ui, app, service, core or data",
    "external kinds are platform, cli, saas, terminal or storage (os is accepted as terminal)",
    "every relationship end is a concept or an external",
    "a concept's entry is true or false when set, and overrides the derived entry",
    "a relationship's kind is hosts when set (one concept runs the other, such as opening its window)",
    "every cross-concept import or call from a production file is covered by a relationship from the source leaf (or an ancestor) to the destination leaf (or an ancestor); an edge whose source file is a test does not count; an injection call counts only at confidence 0.6 or higher",
    "a leaf integration has via (mechanism is an alias) and at (path:function owned by that leaf)",
    "at most 9 children per concept (warning; a warning alone does not reject)",
]

INSTRUCTIONS = (
    "Define the concept map. Concepts nest; only a leaf owns files, and every code and test file "
    "belongs to exactly one leaf. Any other tracked file may be owned by one leaf and may be left out. "
    "A relationship is a labelled arrow. One whose end is an external "
    "is an integration point. On a leaf it needs via, the mechanism (HTTP, exec CLI, IPC, security CLI; "
    "mechanism is an alias), and at, the path:function where it happens. A parent may omit them. "
    "minor: true draws the arrow lighter. Set kind to \"hosts\" when one concept runs the other, "
    "for example Desktop app hosts Overview, \"opens the window for\". Set entry true or "
    "false on a concept to override the derived entry; leave it out and the concept is an entry "
    "when it owns a deployable's entry point, unless a hosts relationship points at it. Copy "
    "input_hash. When `concepts` is present this is a rescan: edit that map and assign the listed "
    "files, which are the unowned, changed or removed ones. " + PLACEMENT + " "
    "Every check runs; a rejected answer lists each failure with the files, pairs or ids."
)

_CONCEPT = {
    "type": "object",
    "required": ["id", "name", "summary", "role"],
    "additionalProperties": False,
    "properties": {
        "id": {"type": "string", "minLength": 1, "maxLength": 120},
        "name": {"type": "string", "minLength": 1, "maxLength": 80},
        "summary": {"type": "string", "minLength": 1, "maxLength": 600},
        "role": {"type": "string", "enum": list(ROLES)},
        "entry": {"type": "boolean",
                  "description": "true or false overrides the derived entry; omit to derive it"},
        "children": {"type": "array", "items": {"$ref": "#/$defs/concept"}},
        "files": {"type": "array", "items": {"type": "string", "minLength": 1}},
    },
}

ANSWER_SCHEMA = {
    "$defs": {"concept": _CONCEPT},
    "type": "object",
    "required": ["input_hash", "summary", "concepts", "externals", "relationships"],
    "additionalProperties": False,
    "properties": {
        "input_hash": {"type": "string", "description": "copied from the brief"},
        "summary": {"type": "string", "minLength": 1, "maxLength": 1000,
                    "description": "what this system is, in one or two sentences"},
        "concepts": {"type": "array", "items": {"$ref": "#/$defs/concept"},
                     "description": "the concept tree; only leaves have files, repo-relative paths"},
        "externals": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "name", "summary", "kind"],
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string", "minLength": 1, "maxLength": 120},
                    "name": {"type": "string", "minLength": 1, "maxLength": 80},
                    "summary": {"type": "string", "minLength": 1, "maxLength": 600},
                    "kind": {"type": "string", "enum": [*KINDS, *KIND_ALIAS]},
                },
            },
        },
        "relationships": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["from", "to", "label"],
                "additionalProperties": False,
                "properties": {
                    "from": {"type": "string", "minLength": 1},
                    "to": {"type": "string", "minLength": 1},
                    "label": {"type": "string", "minLength": 1, "maxLength": 160},
                    "via": {"type": "string", "maxLength": 80,
                            "description": "mechanism; required on a leaf integration"},
                    "mechanism": {"type": "string", "maxLength": 80,
                                  "description": "alias of via"},
                    "at": {"type": "string", "maxLength": 240,
                           "description": "where a leaf integration happens, path:function"},
                    "minor": {"type": "boolean",
                              "description": "true draws the relationship lighter"},
                    "basis": {"type": "string", "maxLength": 40,
                              "description": "optional: imports, reading, or similar"},
                    "kind": {"type": "string", "enum": ["hosts"],
                             "description": "hosts: this concept runs the other (a window, a process)"},
                },
            },
        },
    },
}


def structure_confirmed(conn):
    """True once every confirm-structure task is done.

    define-concepts stays closed while any confirm-structure task is open or missing.
    If that kind is not registered and no rows exist, nothing is waiting.
    """
    from cbi import tasks
    states = [row[0] for row in conn.execute("SELECT state FROM tasks WHERE kind = 'confirm-structure'")]
    if "confirm-structure" not in tasks.SCHEMAS and not states:
        return True
    return bool(states) and all(state == "done" for state in states)


# --- projection -----------------------------------------------------------------


def _workspace(conn):
    row = conn.execute(
        "SELECT id, name, summary FROM nodes WHERE kind = 'workspace' AND parent_id IS NULL ORDER BY id LIMIT 1"
    ).fetchone()
    return {"id": row[0], "name": row[1], "summary": row[2]} if row else None


def _tracked_files(conn):
    """Tracked files the model kept, including docs. Paths are relative to the top repo."""
    rows = conn.execute(
        "SELECT n.id, n.path, n.content_hash, n.summary, coalesce(json_extract(w.attrs, '$.root'), ''), "
        "json_extract(n.attrs, '$.role') "
        "FROM nodes n LEFT JOIN nodes w ON w.id = n.workspace_id "
        "WHERE n.kind IN ('file', 'doc') ORDER BY n.path, n.id"
    )
    return [{"id": nid, "path": posixpath.join(root, path) if root else path, "content_hash": digest,
             "summary": summary, "role": role}
            for nid, path, digest, summary, root, role in rows]


def _code_files(conn):
    """Code and test files, with paths relative to the top repo."""
    return [f for f in _tracked_files(conn) if f["role"] in ("code", "test")]


def _pairs(conn, files):
    """Cross-file import and call pairs between code and test files, with counts."""
    ids = {f["id"]: f["path"] for f in files}
    if not ids:
        return []
    rows = conn.execute(
        "SELECT CASE WHEN s.kind = 'file' THEN s.id ELSE "
        "  (SELECT f.id FROM nodes f WHERE f.kind = 'file' AND f.workspace_id = s.workspace_id AND f.path = s.path) END, "
        "CASE WHEN d.kind = 'file' THEN d.id ELSE "
        "  (SELECT f.id FROM nodes f WHERE f.kind = 'file' AND f.workspace_id = d.workspace_id AND f.path = d.path) END, "
        "e.kind, sum(e.weight) FROM edges e JOIN nodes s ON s.id = e.src JOIN nodes d ON d.id = e.dst "
        "WHERE e.kind IN ('imports', 'calls') AND ("
        "coalesce(json_extract(e.attrs, '$.via'), '') != 'injection' OR e.confidence >= 0.6) "
        "GROUP BY 1, 2, 3"
    )
    pairs = []
    for src, dst, kind, count in rows:
        if src and dst and src != dst and src in ids and dst in ids:
            pairs.append({"from": ids[src], "to": ids[dst], "from_id": src, "to_id": dst, "kind": kind, "count": count})
    pairs.sort(key=lambda p: (p["kind"], p["from"], p["to"]))
    return pairs


def _input_hash(files, pairs):
    from cbi import tasks
    payload = ["define-concepts", tasks.PROTOCOL_VERSION,
               [[f["path"], f["content_hash"]] for f in files],
               [[p["from"], p["to"], p["kind"], p["count"]] for p in pairs]]
    return hashlib.sha1(json.dumps(payload).encode()).hexdigest()[:16]


def _document(text):
    """The concepts document, or None when there is nothing to apply."""
    if not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _leaves(concepts):
    """(concept, files) for every leaf. A concept with children is not a leaf."""
    for concept in concepts or []:
        if not isinstance(concept, dict):
            continue
        children = concept.get("children") or []
        if children:
            yield from _leaves(children)
        else:
            yield concept, [p for p in concept.get("files") or [] if isinstance(p, str)]


def _owned_paths(data):
    if not data:
        return []
    return [path for _, files in _leaves(data.get("concepts")) for path in files]


def _classify(conn, files, data):
    """Files the task should list, and paths the map still names that are gone.

    Code and test files must be owned. Any other tracked file is listed only when the
    map owns it and its content hash changed. A file is changed only when this
    accept-time snapshot has a different content hash. A path the map owns but the
    snapshot never saw (a hand edit) is not a change.
    """
    snapshot = json.loads(store.get_meta(conn, "concept_files") or "{}")
    owned = set(_owned_paths(data))
    review = []
    for f in files:
        if f["path"] not in owned:
            if f["role"] in ("code", "test"):
                review.append({**f, "reason": "unowned"})
        elif f["path"] in snapshot and snapshot[f["path"]] != f["content_hash"]:
            review.append({**f, "reason": "changed"})
    return review, sorted(owned - {f["path"] for f in files})


def _save_snapshot(conn, files, data):
    by_path = {f["path"]: f["content_hash"] for f in files}
    snapshot = {path: by_path[path] for path in _owned_paths(data) if path in by_path}
    store.set_meta(conn, "concept_files", json.dumps(snapshot, sort_keys=True))


def _clear(conn):
    old = [row[0] for row in conn.execute(
        "SELECT id FROM nodes WHERE kind = 'concept' "
        "OR (kind = 'external' AND json_extract(attrs, '$.source') = 'concepts')")]
    if old:
        conn.execute("DELETE FROM nodes WHERE id IN (SELECT value FROM json_each(?))", (json.dumps(old),))
    conn.execute("DELETE FROM edges WHERE source = 'agent' AND kind IN ('owns', 'relates')")
    return old


def apply(conn, text):
    """Replace concept nodes, authored externals and their edges with the document.

    Unparseable text clears the concept map and records a diagnostic. A hand edit is
    projected as written; submit is what enforces the checks. Returns (old ids, new ids).
    """
    workspace = _workspace(conn)
    data = _document(text)
    if text and data is None:
        old = _clear(conn)
        if workspace:
            store.set_diagnostic(conn, workspace["id"], "concepts_invalid", "concepts.json is not a JSON object")
        store.set_meta(conn, "concepts_json", "")
        return old, []
    if workspace:
        store.set_diagnostic(conn, workspace["id"], "concepts_invalid", None)
    store.set_meta(conn, "concepts_json", text or "")
    old = _clear(conn)
    if not data or not workspace:
        return old, []

    existing = {row[0] for row in conn.execute("SELECT id FROM nodes")}
    nodes, owns, seen = [], [], set()
    planned = {}

    def walk(concepts, parent):
        for concept in concepts or []:
            if not isinstance(concept, dict) or not isinstance(concept.get("id"), str):
                continue
            if concept["id"] in seen or concept["id"] in existing:
                continue
            seen.add(concept["id"])
            children = concept.get("children") or []
            files = [path for path in (concept.get("files") or []) if isinstance(path, str)]
            explicit = concept["entry"] if isinstance(concept.get("entry"), bool) else None
            planned[concept["id"]] = {"explicit": explicit, "files": files, "parent": parent}
            nodes.append({
                "id": concept["id"], "parent_id": parent, "kind": "concept",
                "display_kind": ROLE_DISPLAY.get(concept.get("role"), "concept"),
                "name": concept.get("name") or concept["id"], "summary": concept.get("summary"),
                "attrs": {"role": concept.get("role")},
            })
            if children:
                walk(children, concept["id"])
            else:
                owns.append((concept["id"], files))

    walk(data.get("concepts"), workspace["id"])
    ext_ids = set()
    for external in data.get("externals") or []:
        if not isinstance(external, dict) or not isinstance(external.get("id"), str):
            continue
        if external["id"] in seen or external["id"] in existing:
            continue
        seen.add(external["id"])
        ext_ids.add(external["id"])
        kind = _canonical_kind(external.get("kind"))
        nodes.append({
            "id": external["id"], "parent_id": workspace["id"], "kind": "external",
            "display_kind": KIND_DISPLAY.get(kind, "external"),
            "name": external.get("name") or external["id"], "summary": external.get("summary"),
            "attrs": {"kind": kind, "source": "concepts"},
        })

    by_path = {f["path"]: f["id"] for f in _tracked_files(conn)}
    _mark_entries(nodes, planned, by_path, _entry_file_ids(conn), data.get("relationships"))
    conn.executemany(
        "INSERT INTO nodes (id, parent_id, kind, display_kind, name, workspace_id, summary, summary_source, attrs) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 'agent', ?)",
        [(n["id"], n["parent_id"], n["kind"], n["display_kind"], n["name"], workspace["id"], n["summary"],
          json.dumps(n["attrs"], sort_keys=True)) for n in nodes],
    )
    edges = []
    for leaf, paths in owns:
        for path in paths:
            if isinstance(path, str) and path in by_path:
                edges.append((leaf, by_path[path], "owns", "agent", 1.0, 1, None, 0))
    ordinal = defaultdict(int)
    for rel in data.get("relationships") or []:
        if not isinstance(rel, dict) or rel.get("from") not in seen or rel.get("to") not in seen:
            continue
        key = (rel["from"], rel["to"])
        attrs = {"label": rel.get("label") or "", "integration": rel["from"] in ext_ids or rel["to"] in ext_ids}
        if _field(rel, "basis"):
            attrs["basis"] = _field(rel, "basis")
        if _via(rel):
            attrs["via"] = _via(rel)
        if _field(rel, "at"):
            attrs["at"] = _field(rel, "at")
        if rel.get("minor") is True:
            attrs["minor"] = True
        if _field(rel, "kind") == "hosts":
            attrs["kind"] = "hosts"
        edges.append((rel["from"], rel["to"], "relates", "agent", 1.0, 1,
                      json.dumps(attrs, sort_keys=True), ordinal[key]))
        ordinal[key] += 1
    conn.executemany(
        "INSERT INTO edges (src, dst, kind, source, confidence, weight, attrs, ordinal) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        edges,
    )
    return old, [n["id"] for n in nodes]


# --- checks ---------------------------------------------------------------------


def _entry_file_ids(conn):
    """File ids a deployable names as an entry point. Paths are workspace-relative."""
    found = set()
    for wid, attrs in conn.execute("SELECT workspace_id, attrs FROM nodes WHERE kind = 'deployable'"):
        data = json.loads(attrs or "{}")
        points = data.get("entry_points") if isinstance(data, dict) else None
        if not wid or not isinstance(points, list):
            continue
        found.update(f"{wid}:{path}" for path in points if isinstance(path, str) and path)
    return found


def _mark_entries(nodes, planned, by_path, entry_ids, relationships):
    """Set entry and entry_file from deployable entry points, hosts and an explicit entry.

    A concept is an entry when it or a descendant owns an entry-point file, unless a hosts
    relationship points at it. An explicit true or false on the concept wins. entry_file is
    the path (or paths) that made it so. A hosted concept still records the file it owns.
    That file does not count towards the host, or any ancestor of the host.
    """
    children = defaultdict(list)
    for cid, info in planned.items():
        if info["parent"] in planned:
            children[info["parent"]].append(cid)
    hosted = {
        rel["to"] for rel in relationships or []
        if isinstance(rel, dict) and _field(rel, "kind") == "hosts" and rel.get("to") in planned
    }
    cache = {}

    def under(cid):
        if cid not in cache:
            found = [path for path in planned[cid]["files"] if by_path.get(path) in entry_ids]
            for kid in children[cid]:
                if kid not in hosted:
                    found.extend(under(kid))
            cache[cid] = sorted(set(found))
        return cache[cid]

    for node in nodes:
        if node["kind"] != "concept" or node["id"] not in planned:
            continue
        info = planned[node["id"]]
        tree = under(node["id"])
        direct = [path for path in info["files"] if path in tree]
        is_entry = info["explicit"] if info["explicit"] is not None else (bool(tree) and node["id"] not in hosted)
        node["attrs"]["entry"] = bool(is_entry)
        named = direct or (tree if is_entry else [])
        if named:
            node["attrs"]["entry_file"] = named[0] if len(named) == 1 else named


def _field(rel, key):
    value = rel.get(key)
    return value.strip() if isinstance(value, str) else ""


def _via(rel):
    """The mechanism. `via` is the stored name; `mechanism` is the alias."""
    return _field(rel, "via") or _field(rel, "mechanism")


def _canonical_kind(kind):
    return KIND_ALIAS.get(kind, kind)


def _under(node_id, concept_id, parent):
    while node_id:
        if node_id == concept_id:
            return True
        node_id = parent.get(node_id)
    return False


def _ancestors(parent, concept_id):
    chain = []
    while concept_id:
        chain.append(concept_id)
        concept_id = parent.get(concept_id)
    return chain


def _integration(errors, index, rel, ends, required, owner, parent):
    """A leaf integration needs via and at. A parent arrow may omit them; at is checked when present."""
    if required and not _via(rel):
        errors.append(f"$.relationships[{index}]: integration {rel['from']} -> {rel['to']} has no via")
    at = _field(rel, "at")
    if not at:
        if required:
            errors.append(f"$.relationships[{index}]: integration {rel['from']} -> {rel['to']} has no at")
        return
    file, _, fn = at.partition(":")
    if not file or not fn:
        errors.append(f"$.relationships[{index}].at: {at!r} is not path:function")
        return
    for end in ends:
        if not _under(owner.get(file), end, parent):
            errors.append(f"$.relationships[{index}].at: {at!r} is not owned by {end}")


def problems(conn, answer):
    """(errors, warnings) for one define-concepts answer. Schema-valid answers only.

    Every check runs. Errors name the files, pairs or ids; warnings do not reject on their own.
    """
    errors, warnings = [], []
    tracked = _tracked_files(conn)
    by_path = {f["path"]: f for f in tracked}
    taken = dict(conn.execute(
        "SELECT id, kind FROM nodes WHERE NOT (kind = 'concept' "
        "OR (kind = 'external' AND json_extract(attrs, '$.source') = 'concepts'))"
    ))
    parent, leaves, owner = {}, [], {}
    non_leaves = set()
    seen = {}

    def claim(path, node_id):
        if node_id in seen:
            errors.append(f"{path}: {node_id!r} is duplicated ({seen[node_id]})")
            return False
        if node_id in taken:
            errors.append(f"{path}: {node_id!r} is already a {taken[node_id]}")
            return False
        seen[node_id] = path
        return True

    def walk(concepts, path, parent_id):
        concepts = concepts or []
        if len(concepts) > MAX_CHILDREN:
            whose = f"{parent_id!r}" if parent_id else "the top level"
            warnings.append(f"{path}: warning: {whose} has {len(concepts)} children; at most {MAX_CHILDREN}")
        for i, concept in enumerate(concepts):
            here = f"{path}[{i}]"
            node_id = concept["id"]
            if not claim(f"{here}.id", node_id):
                continue
            parent[node_id] = parent_id
            children = concept.get("children") or []
            listed = concept.get("files") or []
            if children and listed:
                errors.append(f"{here}: {node_id!r} owns files but is not a leaf ({', '.join(listed)})")
            if children:
                non_leaves.add(node_id)
                walk(children, f"{here}.children", node_id)
                continue
            leaves.append(node_id)
            seen_files = set()
            for j, file_path in enumerate(listed):
                where = f"{here}.files[{j}]"
                if file_path in seen_files:
                    errors.append(f"{where}: {file_path!r} listed twice")
                    continue
                seen_files.add(file_path)
                if file_path not in by_path:
                    errors.append(f"{where}: {file_path!r} is not a tracked file")
                    continue
                if file_path in owner:
                    errors.append(f"{where}: {file_path!r} is owned by {owner[file_path]} and {node_id}")
                    continue
                owner[file_path] = node_id

    walk(answer.get("concepts"), "$.concepts", None)
    externals = set()
    for i, external in enumerate(answer.get("externals") or []):
        if claim(f"$.externals[{i}].id", external["id"]):
            externals.add(external["id"])
    required = {f["path"] for f in tracked if f["role"] in ("code", "test")}
    missing = sorted(required - set(owner))
    if missing:
        errors.append("$.concepts: unowned files: " + ", ".join(missing))

    known = set(seen)
    for i, rel in enumerate(answer.get("relationships") or []):
        for side in ("from", "to"):
            if rel[side] not in known:
                errors.append(f"$.relationships[{i}].{side}: {rel[side]!r} is not a concept or external")
        via, mechanism = _field(rel, "via"), _field(rel, "mechanism")
        if via and mechanism and via != mechanism:
            errors.append(f"$.relationships[{i}]: via {via!r} and mechanism {mechanism!r} differ")
        if rel["from"] in externals or rel["to"] in externals:
            ends = [rel[side] for side in ("from", "to") if rel[side] in known and rel[side] not in externals]
            _integration(errors, i, rel, ends, required=bool(ends) and all(end not in non_leaves for end in ends),
                         owner=owner, parent=parent)

    covered = {(rel["from"], rel["to"]) for rel in answer.get("relationships") or []}
    chains = {leaf: _ancestors(parent, leaf) for leaf in leaves}
    code = [f for f in tracked if f["role"] in ("code", "test")]
    production = {f["path"] for f in code if f["role"] == "code"}
    gaps = defaultdict(list)
    for pair in _pairs(conn, code):
        # A test file's imports and calls are test links, not architecture.
        if pair["from"] not in production:
            continue
        src, dst = owner.get(pair["from"]), owner.get(pair["to"])
        if not src or not dst or src == dst:
            continue
        if any((a, b) in covered for a in chains[src] for b in chains[dst]):
            continue
        gaps[(pair["kind"], src, dst)].append(f"{pair['from']} -> {pair['to']}")
    for (kind, src, dst), ends in sorted(gaps.items()):
        errors.append(
            f"$.relationships: no relationship covers {kind} {src} -> {dst}: " + ", ".join(ends))
    return errors, warnings


# --- task -----------------------------------------------------------------------


def _canonical_external(external):
    return {**external, "kind": _canonical_kind(external.get("kind"))}


def _canonical_rel(rel):
    """Stored document shape. `via` is written; `mechanism` is not."""
    out = {"from": rel["from"], "to": rel["to"], "label": rel["label"]}
    if _field(rel, "kind") == "hosts":
        out["kind"] = "hosts"
    if _via(rel):
        out["via"] = _via(rel)
    if _field(rel, "at"):
        out["at"] = _field(rel, "at")
    if rel.get("minor") is True:
        out["minor"] = True
    if _field(rel, "basis"):
        out["basis"] = _field(rel, "basis")
    return out


def _body(answer):
    return {
        "summary": answer["summary"],
        "concepts": answer["concepts"],
        "externals": [_canonical_external(external) for external in answer["externals"]],
        "relationships": [_canonical_rel(rel) for rel in answer["relationships"]],
    }


def _cached(conn, digest):
    row = conn.execute("SELECT answer FROM cache.summary_answers WHERE input_hash = ?", (digest,)).fetchone()
    return json.loads(row[0]) if row else None


def _task_id(workspace_id):
    return "dc-" + hashlib.sha1(workspace_id.encode()).hexdigest()[:8]


def refresh(conn, out=None, root=None):
    """Open, close or fill define-concepts from the current files and concepts.json."""
    from cbi import screens
    if not structure_confirmed(conn):
        conn.execute("DELETE FROM tasks WHERE kind = 'define-concepts'")
        screens.refresh(conn, out, root)
        return
    workspace = _workspace(conn)
    if not workspace:
        screens.refresh(conn, out, root)
        return
    text = store.get_meta(conn, "concepts_json")
    if text is None and out is not None:
        path = out / "concepts.json"
        text = path.read_text() if path.exists() else ""
        store.set_meta(conn, "concepts_json", text)
    data = _document(text)
    tracked = _tracked_files(conn)
    files = [f for f in tracked if f["role"] in ("code", "test")]
    pairs = _pairs(conn, files)
    digest = _input_hash(files, pairs)
    cached = _cached(conn, digest)
    # A deleted concepts.json is restored from the cache. An existing file, even a broken one, is kept.
    absent = out is not None and not (out / "concepts.json").exists()
    if cached and data is None and absent and not problems(conn, {**cached, "input_hash": digest})[0]:
        written = json.dumps(cached, indent=2) + "\n"
        (out / "concepts.json").write_text(written)
        apply(conn, written)
        _save_snapshot(conn, tracked, cached)
        data = cached
    review, removed = _classify(conn, tracked, data)
    state = "done" if data is not None and not review and not removed else "open"
    conn.execute(
        "INSERT INTO tasks (id, kind, node_id, input_hash, state, depends_on, inputs) "
        "VALUES (?, 'define-concepts', ?, ?, ?, '[]', ?) "
        "ON CONFLICT(id) DO UPDATE SET node_id = excluded.node_id, input_hash = excluded.input_hash, "
        "state = excluded.state, depends_on = '[]', inputs = excluded.inputs",
        (_task_id(workspace["id"]), workspace["id"], digest, state, json.dumps([f["id"] for f in review])),
    )
    conn.execute("DELETE FROM tasks WHERE kind = 'define-concepts' AND id != ?", (_task_id(workspace["id"]),))
    screens.refresh(conn, out, root)


def accept(conn, task, answer, out, root=None):
    """Write concepts.json, project it, and close the task. Raises AnswerError listing every failure."""
    from cbi import tasks, team
    if out is None:
        raise tasks.AnswerError("$: no model directory; submit through `cbi submit`")
    errors, warnings = problems(conn, answer)
    if errors:
        raise tasks.AnswerError("\n".join(errors + warnings))
    body = _body(answer)
    text = json.dumps(body, indent=2) + "\n"
    current = (out / "concepts.json").read_text() if (out / "concepts.json").exists() else None
    if _cached(conn, task["input_hash"]) == body and current == text and not warnings:
        team.sync(conn, out)
        return f"{task['id']}: already accepted, nothing changed"
    def write():
        (out / "concepts.json").write_text(text)
        old, new = apply(conn, text)
        _save_snapshot(conn, _tracked_files(conn), body)
        conn.execute("INSERT OR REPLACE INTO cache.summary_answers (input_hash, answer) VALUES (?, ?)",
                     (task["input_hash"], json.dumps(body)))
        before = {row[0] for row in conn.execute("SELECT id FROM tasks WHERE state = 'open'")}
        refresh(conn, out, root)
        store.reindex(conn, old + new)
        team.sync(conn, out)
        return sorted({row[0] for row in conn.execute("SELECT id FROM tasks WHERE state = 'open'")} - before)

    opened = store.retry_write(conn, write)
    note = f"; warning: {'; '.join(item.split('warning: ', 1)[-1] for item in warnings)}" if warnings else ""
    suffix = f"; now open: {', '.join(opened)}" if opened else ""
    return f"{task['id']}: accepted{note}{suffix}"


def brief_body(conn, task):
    """The define-concepts inputs: structure, the files to assign, pairs, and the current map."""
    workspace = _workspace(conn) or {"id": task["node_id"], "name": "", "summary": None}
    tracked = _tracked_files(conn)
    files = [f for f in tracked if f["role"] in ("code", "test")]
    by_id = {f["id"]: f for f in tracked}
    data = _document(store.get_meta(conn, "concepts_json"))
    review, removed = _classify(conn, tracked, data)
    reason = {f["id"]: f["reason"] for f in review}
    listed = []
    for node_id in task["inputs"]:
        if node_id not in by_id:
            continue
        entry = dict(by_id[node_id])
        entry["reason"] = reason.get(node_id, "unowned")
        entry["outline"] = [
            {"display_kind": row[0], "name": row[1], "lines": f"{row[2]}-{row[3]}", "signature": row[4], "doc": row[5]}
            for row in conn.execute(
                "SELECT display_kind, name, start_line, end_line, signature, doc FROM nodes "
                "WHERE kind IN ('symbol', 'test') AND parent_id = ? ORDER BY start_line", (node_id,))
        ]
        listed.append(entry)
    pairs = _pairs(conn, files)
    if listed and len(listed) < len(files):
        want = {f["path"] for f in listed}
        pairs = [p for p in pairs if p["from"] in want or p["to"] in want]
    groups = {"deployables": [], "packages": []}
    for kind, name, display, summary, path in conn.execute(
            "SELECT kind, name, display_kind, summary, path FROM nodes WHERE kind IN ('deployable', 'package') "
            "ORDER BY kind, path, name"):
        groups[kind + "s"].append({"name": name, "display_kind": display, "summary": summary, "path": path})
    env = []
    for name, attrs in conn.execute("SELECT name, attrs FROM nodes WHERE kind = 'env' ORDER BY name"):
        attrs = json.loads(attrs or "{}")
        env.append({"name": name, "default": attrs.get("default"), "declared_in": attrs.get("declared_in")})
    return {
        "checks": CHECKS,
        "workspace": workspace,
        "deployables": groups["deployables"],
        "packages": groups["packages"],
        "files": listed,
        "pairs": [{"from": p["from"], "to": p["to"], "kind": p["kind"], "count": p["count"]} for p in pairs],
        "env": env,
        "concepts": data,
        "removed": removed,
        "rescan": data is not None,
    }


def template(brief):
    """A short skeleton. The current map, when there is one, is the `concepts` field of the brief."""
    files = [f["path"] for f in brief.get("files") or []][:2]
    return {"input_hash": brief["input_hash"], "summary": "...",
            "concepts": [{"id": "app", "name": "App", "summary": "...", "role": "app", "files": files}],
            "externals": [], "relationships": []}


def _part_line(b):
    part = b.get("part")
    if not part:
        return []
    return [f"part: {part['index']} of {part['count']}  {part['name']}"]


def format_brief(b):
    node = b.get("workspace") or {}
    lines = [f"# Task {b['id']}: define-concepts ({b['state']})",
             f"node: workspace {node.get('name') or b['node_id']}", f"input_hash: {b['input_hash']}"]
    lines += _part_line(b)
    lines += ["", b["instructions"], "", "## Checks"]
    lines += [f"- {check}" for check in b["checks"]]
    summary = node.get("summary")
    lines += ["", "## Workspace", f"{node.get('name')}: {summary}" if summary else f"{node.get('name')}: (no summary yet)"]
    for heading, key in (("Deployables", "deployables"), ("Packages", "packages")):
        lines += ["", f"## {heading}"]
        rows = b.get(key) or []
        lines += [f"  {row['display_kind']:<12} {row['name']}" + (f": {row['summary']}" if row["summary"] else "")
                  for row in rows] or ["  (none)"]
    if b.get("areas"):
        lines += ["", "## Areas"]
        for area in b["areas"]:
            line = f"  {area['name']}: {area['files']} files"
            if area.get("summary"):
                line += f". {area['summary']}"
            lines.append(line)
    files = b.get("files") or []
    why = "to assign" if not b.get("rescan") else "unowned, changed or removed"
    lines += ["", f"## Files {why} ({len(files)})"]
    for f in files:
        lines.append(f"### {f['path']}  ({f.get('reason', 'unowned')})")
        if f.get("summary"):
            lines.append(f"  {f['summary']}")
        for item in f.get("outline") or []:
            lines.append(f"  {item['display_kind']:<12} L{item['lines']:<9} {item['signature']}")
    lines += ["", "## Import and call pairs"]
    lines += [f"  {p['from']} -> {p['to']}  {p['kind']} {p['count']}" for p in b.get("pairs") or []] or ["  (none)"]
    if b.get("env"):
        lines += ["", "## Env vars"]
        lines += [f"  {e['name']}" + (f"  default {e['default']}" if e.get("default") else "") for e in b["env"]]
    if b.get("removed"):
        lines += ["", "## Removed from the tree", *[f"- {path}" for path in b["removed"]]]
    if b.get("concepts"):
        lines += ["", "## Current concepts", json.dumps(b["concepts"], indent=2)]
    lines += ["", "## Answer schema", json.dumps(b["answer_schema"], indent=2), "", "## Answer template",
              json.dumps(template(b), indent=2), "",
              f"Submit with: cbi submit {b['id']} answer.json   (or pipe the JSON to `cbi submit {b['id']} -`)"]
    return "\n".join(lines)


# --- show -----------------------------------------------------------------------


def _jsx(attrs):
    if not attrs:
        return False
    data = json.loads(attrs) if isinstance(attrs, str) else attrs
    return (data or {}).get("via") == "jsx"


def leaf_detail(conn, concept_id):
    """Env vars this concept's files read, and symbols in other concepts it calls or that call it."""
    env = []
    if conn.execute("SELECT 1 FROM nodes WHERE kind = 'env'").fetchone():
        for name, default in conn.execute(
                "SELECT DISTINCT env.name, json_extract(re.attrs, '$.default') FROM edges owns "
                "JOIN nodes file ON file.id = owns.dst "
                "JOIN nodes reader ON reader.workspace_id = file.workspace_id AND reader.path = file.path "
                "JOIN edges re ON re.kind = 'reads_env' AND re.src = reader.id "
                "JOIN nodes env ON env.id = re.dst AND env.kind = 'env' "
                "WHERE owns.kind = 'owns' AND owns.src = ? ORDER BY env.name", (concept_id,)):
            env.append({"name": name, "default": default})
    cross = []
    if not conn.execute("SELECT 1 FROM nodes WHERE kind = 'concept' AND parent_id = ?", (concept_id,)).fetchone():
        owner = dict(conn.execute("SELECT dst, src FROM edges WHERE kind = 'owns'"))
        symbols = {}
        for sid, fid, display, name in conn.execute(
                "SELECT s.id, f.id, s.display_kind, s.name FROM nodes s "
                "JOIN nodes f ON f.kind = 'file' AND f.workspace_id = s.workspace_id AND f.path = s.path "
                "WHERE s.kind = 'symbol'"):
            symbols[sid] = (fid, display, name)
        names = dict(conn.execute("SELECT id, name FROM nodes WHERE kind = 'concept'"))
        found = {}
        for src, dst, attrs in conn.execute("SELECT src, dst, attrs FROM edges WHERE kind = 'calls'"):
            if src not in symbols or dst not in symbols:
                continue
            sf, sdisp, sname = symbols[src]
            df, ddisp, dname = symbols[dst]
            so, do = owner.get(sf), owner.get(df)
            if so == concept_id and do not in (None, concept_id):
                verb = "renders" if _jsx(attrs) else "calls"
                slot = found.setdefault(dst, {"id": dst, "name": dname, "display_kind": ddisp, "concept": do,
                                               "concept_name": names.get(do, do), "verbs": set()})
                slot["verbs"].add(verb)
            elif do == concept_id and so not in (None, concept_id):
                verb = "rendered" if _jsx(attrs) else "called"
                slot = found.setdefault(src, {"id": src, "name": sname, "display_kind": sdisp, "concept": so,
                                               "concept_name": names.get(so, so), "verbs": set()})
                slot["verbs"].add(verb)
        cross = sorted(found.values(), key=lambda item: (item["concept"], item["name"], item["id"]))
        for item in cross:
            item["verbs"] = sorted(item["verbs"])
    return {"env": env, "cross": cross}

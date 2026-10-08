"""Screen sketches: `.cbi/screens.json` projected into the model, and the sketch-screens task.

A screen is one JSON region tree on a node (`kind = 'screen'`), parented to the UI concept
that owns its root component. Each region that names a component gets a `sketches` edge.
The file is applied on every scan. Coverage checks run on submit, not on a hand edit.
"""

import hashlib
import json
import posixpath
import re
from collections import defaultdict
from pathlib import Path

from cbi import store

CHECKS = [
    "every region component is a real component node",
    "every component owned by a UI concept appears in at least one screen, or is listed in unsketched with a reason",
]

INSTRUCTIONS = (
    "Sketch each screen as a tree of regions. A region has an id and a layout (row, column or grid) "
    "and may name a component (a path#Name from this brief, or its node id), a label, static text, "
    "style hints and children. Text is data, never HTML; write a dynamic value as {expr}. Style hints "
    "are short words such as card, list, button, badge, input, heading or muted; other short hints are "
    "kept. A grid may set cols from 1 to 12. device is a short word such as desktop or phone. "
    "Copy input_hash. Every component owned by a UI concept must appear in a region or in unsketched "
    "with a reason. A region the template shows only sometimes has when, a short condition such as "
    "\"role: manager\", \"flag: arrears-view\" or \"state: connected\", taken from a v-if, v-show or &&. "
    "When jsx_truncated is set, open the file; the slice is the first 400 lines. "
    "When screens is present, edit that document. Every check runs; a rejected answer lists each failure."
)

JSX_LINES = 400
FILE_LIMIT = 200_000
STATE_LIMIT = 40
_LOOKAHEAD = 500

_REGION = {
    "type": "object",
    "required": ["id", "layout"],
    "additionalProperties": False,
    "properties": {
        "id": {"type": "string", "minLength": 1, "maxLength": 80},
        "label": {"type": "string", "minLength": 1, "maxLength": 80},
        "component": {"type": "string", "minLength": 1, "maxLength": 500,
                      "description": "path#Name from the brief, or a component node id"},
        "layout": {"type": "string", "enum": ["row", "column", "grid"]},
        "text": {"type": "string", "maxLength": 500,
                 "description": "static text; a dynamic value is written as {expr}"},
        "style": {"type": "array", "items": {"type": "string", "minLength": 1, "maxLength": 20},
                  "description": "short hints such as card, list, button, badge, input, heading, muted"},
        "cols": {"type": "integer", "minimum": 1, "maximum": 12,
                 "description": "grid columns, when layout is grid"},
        "when": {"type": "string", "minLength": 1, "maxLength": 80,
                 "description": "short condition from a v-if, v-show or && in the template, "
                                "such as \"role: manager\", \"flag: arrears-view\" or \"state: connected\""},
        "children": {"type": "array", "items": {"$ref": "#/$defs/region"}},
    },
}

ANSWER_SCHEMA = {
    "$defs": {"region": _REGION},
    "type": "object",
    "required": ["input_hash", "screens"],
    "additionalProperties": False,
    "properties": {
        "input_hash": {"type": "string", "description": "copied from the brief"},
        "screens": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "name", "device", "root"],
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string", "minLength": 1, "maxLength": 80},
                    "name": {"type": "string", "minLength": 1, "maxLength": 80},
                    "device": {"type": "string", "minLength": 1, "maxLength": 20,
                               "description": "a short word such as desktop or phone"},
                    "root": {"$ref": "#/$defs/region"},
                },
            },
        },
        "unsketched": {
            "type": "array",
            "description": "UI components deliberately left out of every screen, each with a reason",
            "items": {
                "type": "object",
                "required": ["component", "reason"],
                "additionalProperties": False,
                "properties": {
                    "component": {"type": "string", "minLength": 1, "maxLength": 500},
                    "reason": {"type": "string", "minLength": 1, "maxLength": 200},
                },
            },
        },
    },
}

AMBIGUOUS = object()
_UNION = re.compile(
    r'(?:export\s+)?type\s+([A-Za-z_$][\w$]*)\s*=\s*((?:"[^"\n]*"\s*\|\s*)+"[^"\n]*")'
)
_CONST = re.compile(r'(?:export\s+)?const\s+([A-Za-z_$][\w$]*)\b')
_QUOTED = re.compile(r'"([^"]*)"')
_ID_VALUE = re.compile(r'\bid\s*:\s*"([^"]*)"')


def _workspace(conn):
    row = conn.execute(
        "SELECT id, name FROM nodes WHERE kind = 'workspace' AND parent_id IS NULL ORDER BY id LIMIT 1"
    ).fetchone()
    return {"id": row[0], "name": row[1]} if row else None


def _screen_id(workspace_id, agent_id):
    return f"{workspace_id}:screen:{agent_id}"


def _task_id(workspace_id):
    return "ss-" + hashlib.sha1(workspace_id.encode()).hexdigest()[:8]


def _document(text):
    """The screens document, or None when there is nothing to apply."""
    if not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    if "screens" not in data:
        data = {**data, "screens": []}
    return data


def _concepts_done(conn):
    states = [row[0] for row in conn.execute("SELECT state FROM tasks WHERE kind = 'define-concepts'")]
    return bool(states) and all(state == "done" for state in states)


def _files(conn):
    rows = conn.execute(
        "SELECT n.id, n.path, n.workspace_id, n.content_hash, coalesce(json_extract(w.attrs, '$.root'), '') "
        "FROM nodes n LEFT JOIN nodes w ON w.id = n.workspace_id WHERE n.kind = 'file'"
    )
    files = {}
    for fid, path, wid, digest, root in rows:
        files[fid] = {
            "id": fid, "wid": wid, "ws_path": path, "hash": digest or "",
            "path": posixpath.join(root, path) if root else path,
        }
    return files


def _owners(conn):
    return {
        dst: (cid, name, role)
        for dst, cid, name, role in conn.execute(
            "SELECT e.dst, c.id, c.name, json_extract(c.attrs, '$.role') FROM edges e "
            "JOIN nodes c ON c.id = e.src WHERE e.kind = 'owns' AND c.kind = 'concept'")
    }


def _components(conn):
    """Every React component symbol, with the concept that owns its file."""
    files, owners = _files(conn), _owners(conn)
    components = []
    for sid, name, signature, start, end in conn.execute(
            "SELECT id, name, signature, start_line, end_line FROM nodes "
            "WHERE kind = 'symbol' AND display_kind = 'component' ORDER BY id"):
        info = files.get(sid.split("#", 1)[0])
        if not info:
            continue
        owner = owners.get(info["id"])
        components.append({
            "id": sid, "name": name, "path": info["path"], "ws_path": info["ws_path"],
            "ref": f"{info['path']}#{name}", "file_id": info["id"], "signature": signature or "",
            "start": start, "end": end, "content_hash": info["hash"],
            "concept": owner[0] if owner else None, "concept_name": owner[1] if owner else None,
            "ui": bool(owner and owner[2] == "ui"),
        })
    components.sort(key=lambda c: (c["ref"], c["id"]))
    return components, _index(components), files


def _index(components):
    by_id, by_ref, by_name = {}, {}, {}
    for comp in components:
        by_id[comp["id"]] = comp
        by_ref[comp["ref"]] = comp
        ws_ref = f"{comp['ws_path']}#{comp['name']}"
        if comp["ws_path"] and ws_ref != comp["ref"]:
            by_ref[ws_ref] = comp
        by_name.setdefault(comp["name"], []).append(comp)
    return {"by_id": by_id, "by_ref": by_ref, "by_name": by_name}


def _resolve(index, ref):
    """The component ref names, AMBIGUOUS when a bare name matches several, else None."""
    if not isinstance(ref, str) or not ref:
        return None
    if ref in index["by_id"]:
        return index["by_id"][ref]
    if ref in index["by_ref"]:
        return index["by_ref"][ref]
    if "#" in ref or "/" in ref:
        return None
    hits = index["by_name"].get(ref) or []
    if len(hits) == 1:
        return hits[0]
    return AMBIGUOUS if len(hits) > 1 else None


def _node_ref(conn, node_id, index, cache):
    if node_id in cache:
        return cache[node_id]
    comp = index["by_id"].get(node_id)
    if comp:
        cache[node_id] = comp["ref"]
        return comp["ref"]
    row = conn.execute(
        "SELECT n.kind, n.name, n.path, coalesce(json_extract(w.attrs, '$.root'), '') "
        "FROM nodes n LEFT JOIN nodes w ON w.id = n.workspace_id WHERE n.id = ?", (node_id,)).fetchone()
    if not row:
        cache[node_id] = None
        return None
    kind, name, path, root = row
    top = posixpath.join(root, path) if root and path else (path or "")
    cache[node_id] = top if kind in ("file", "doc") else (f"{top}#{name}" if top else name)
    return cache[node_id]


def _jsx_edges(conn):
    return conn.execute(
        "SELECT src, dst, weight FROM edges WHERE kind = 'calls' AND json_extract(attrs, '$.via') = 'jsx'"
    ).fetchall()


def _render_maps(conn, index):
    """JSX render refs keyed by source node, incoming refs keyed by component, and sorted pairs."""
    renders, rendered_by, pairs, cache = defaultdict(set), defaultdict(set), [], {}
    for src, dst, weight in _jsx_edges(conn):
        if dst not in index["by_id"]:
            continue
        src_ref = _node_ref(conn, src, index, cache)
        if not src_ref:
            continue
        dst_ref = index["by_id"][dst]["ref"]
        renders[src].add(dst_ref)
        rendered_by[dst].add(src_ref)
        pairs.append((src_ref, dst_ref, weight))
    return ({k: sorted(v) for k, v in renders.items()},
            {k: sorted(v) for k, v in rendered_by.items()}, sorted(pairs))


def _entry_files(conn, files):
    by_path = {(info["wid"], info["ws_path"]): info for info in files.values()}
    found = []
    for wid, attrs in conn.execute("SELECT workspace_id, attrs FROM nodes WHERE kind = 'deployable'"):
        for entry in json.loads(attrs or "{}").get("entry_points") or []:
            info = by_path.get((wid, entry))
            if info and info not in found:
                found.append(info)
    return found


def _entries(conn, components, files, index):
    """Components defined in a deployable entry, or rendered from one."""
    infos = _entry_files(conn, files)
    if not infos:
        return []
    entry_ids = {info["id"] for info in infos}
    by_file = {info["id"]: info["path"] for info in infos}
    src_from = dict(by_file)
    for sid, path, wid in conn.execute("SELECT id, path, workspace_id FROM nodes WHERE kind = 'symbol'"):
        info = next((item for item in infos if item["wid"] == wid and item["ws_path"] == path), None)
        if info:
            src_from[sid] = info["path"]
    entries = {}
    for comp in components:
        if comp["file_id"] in entry_ids:
            entries[(comp["ref"], comp["path"])] = {
                "component": comp["ref"], "from": comp["path"], "reason": "defined in a deployable entry",
            }
    for src, dst, _weight in _jsx_edges(conn):
        if src not in src_from or dst not in index["by_id"]:
            continue
        comp = index["by_id"][dst]
        key = (comp["ref"], src_from[src])
        entries.setdefault(key, {
            "component": comp["ref"], "from": src_from[src], "reason": "rendered from a deployable entry",
        })
    return sorted(entries.values(), key=lambda item: (item["from"], item["component"], item["reason"]))


def _read(root, path, cache, limit=True):
    if path in cache:
        return cache[path]
    if not root:
        cache[path] = None
        return None
    try:
        # A ref scan passes a commit tree, which supports `/` but is not a filesystem path.
        base = Path(root) if isinstance(root, (str, bytes)) else root
        text = (base / path).read_text(errors="replace")
    except OSError:
        cache[path] = None
        return None
    cache[path] = None if limit and len(text) > FILE_LIMIT else text
    return cache[path]


def _slice(text, start, end):
    if not text or not start or not end:
        return ""
    return "\n".join(text.splitlines()[start - 1:end])


def _bracket(text):
    """The `[...]` text starts with, respecting strings and nested brackets."""
    if not text.startswith("["):
        return None
    depth, quote = 0, False
    i = 0
    while i < len(text):
        char = text[i]
        if quote:
            if char == "\\":
                i += 2
                continue
            if char == '"':
                quote = False
        elif char == '"':
            quote = True
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return text[:i + 1]
        i += 1
    return None


def _string_sets(text):
    """(name, values) for string-literal unions and id-lists of 2 to 12 members."""
    found = []
    for match in _UNION.finditer(text):
        values = _QUOTED.findall(match.group(2))
        if 2 <= len(values) <= 12:
            found.append((match.group(1), values))
    for match in _CONST.finditer(text):
        window = text[match.end():match.end() + _LOOKAHEAD]
        eq = window.find("=")
        if eq < 0:
            continue
        rest = window[eq + 1:].lstrip()
        body = _bracket(rest) if rest.startswith("[") else None
        if not body:
            continue
        # Only id lists. A bare array of labels ("CLI call", "subagent") is copy, not a tab switch.
        ids = _ID_VALUE.findall(body)
        if 2 <= len(ids) <= 12:
            found.append((match.group(1), ids))
    return found


def _states(conn, components, files, root):
    """Tab and state enums named in a component, from that file or one it imports."""
    file_ids = [comp["file_id"] for comp in components]
    paths = {comp["path"] for comp in components}
    if file_ids:
        for src, dst in conn.execute(
                "SELECT src, dst FROM edges WHERE kind = 'imports' AND src IN (SELECT value FROM json_each(?))",
                (json.dumps(file_ids),)):
            info = files.get(dst) or files.get(dst.split("#", 1)[0])
            if info and info["path"].endswith((".ts", ".tsx", ".js", ".jsx")):
                paths.add(info["path"])
    cache = {}
    mentions = {}
    for comp in components:
        mentions[comp["ref"]] = _slice(_read(root, comp["path"], cache), comp["start"], comp["end"])
    states = []
    for path in sorted(paths):
        text = _read(root, path, cache)
        if not text:
            continue
        for name, values in _string_sets(text):
            word = re.compile(r"\b" + re.escape(name) + r"\b")
            set_in = sorted(ref for ref, source in mentions.items() if word.search(source))
            if set_in:
                states.append({"name": name, "path": path, "values": values, "set_in": set_in})
    states.sort(key=lambda item: (item["path"], item["name"], item["values"]))
    return states[:STATE_LIMIT]


def _listed(components, entries):
    refs = {item["component"] for item in entries}
    return [comp for comp in components if comp["ui"] or comp["ref"] in refs]


def _input_hash(listed, pairs, entries, states):
    from cbi import tasks
    payload = [
        "sketch-screens", tasks.PROTOCOL_VERSION,
        [[c["ref"], c["content_hash"], c["concept"] or "", c["signature"]] for c in listed],
        pairs,
        [[e["component"], e["from"], e["reason"]] for e in entries],
        [[s["name"], s["path"], s["values"]] for s in states],
    ]
    return hashlib.sha1(json.dumps(payload).encode()).hexdigest()[:16]


def _ui_ancestor(conn, leaf_id, workspace_id):
    """The leaf when its role is ui, else the nearest ui ancestor, else the leaf."""
    current, seen = leaf_id, set()
    while current and current not in seen and current != workspace_id:
        seen.add(current)
        row = conn.execute(
            "SELECT json_extract(attrs, '$.role'), parent_id, kind FROM nodes WHERE id = ?", (current,)
        ).fetchone()
        if not row or row[2] != "concept":
            break
        if row[0] == "ui":
            return current
        current = row[1]
    return leaf_id


def _parent(conn, root, index, workspace_id):
    ref = root.get("component") if isinstance(root, dict) else None
    hit = _resolve(index, ref) if isinstance(ref, str) else None
    if not isinstance(hit, dict):
        return workspace_id
    row = conn.execute(
        "SELECT e.src FROM edges e JOIN nodes c ON c.id = e.src "
        "WHERE e.kind = 'owns' AND e.dst = ? AND c.kind = 'concept'", (hit["file_id"],)).fetchone()
    return _ui_ancestor(conn, row[0], workspace_id) if row else workspace_id


def _count(region, index, counts):
    if not isinstance(region, dict):
        return
    hit = _resolve(index, region.get("component")) if isinstance(region.get("component"), str) else None
    if isinstance(hit, dict):
        counts[hit["id"]] += 1
    children = region.get("children")
    if isinstance(children, list):
        for child in children:
            _count(child, index, counts)


def _clear(conn):
    old = [row[0] for row in conn.execute("SELECT id FROM nodes WHERE kind = 'screen'")]
    if old:
        conn.execute("DELETE FROM edges WHERE src IN (SELECT value FROM json_each(?))", (json.dumps(old),))
        conn.execute("DELETE FROM nodes WHERE id IN (SELECT value FROM json_each(?))", (json.dumps(old),))
    conn.execute("DELETE FROM edges WHERE source = 'agent' AND kind = 'sketches'")
    return old


def apply(conn, text):
    """Replace screen nodes and their sketches edges with the document.

    Unparseable text clears the screens and records a diagnostic. A hand edit is projected
    as written; submit is what enforces the checks. Returns (old ids, new ids).
    """
    workspace = _workspace(conn)
    if text:
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = None
        if not isinstance(data, dict):
            data = None
    else:
        data = None
    if text and data is None:
        old = _clear(conn)
        if workspace:
            store.set_diagnostic(conn, workspace["id"], "screens_invalid", "screens.json is not a JSON object")
        store.set_meta(conn, "screens_json", "")
        return old, []
    if workspace:
        store.set_diagnostic(conn, workspace["id"], "screens_invalid", None)
    store.set_meta(conn, "screens_json", text or "")
    old = _clear(conn)
    if not data or not workspace:
        return old, []

    screens = data.get("screens") if isinstance(data.get("screens"), list) else []
    _components_now, index, _files_now = _components(conn)
    existing = {row[0] for row in conn.execute("SELECT id FROM nodes")}
    nodes, edges, seen = [], [], set()
    for screen in screens:
        if not isinstance(screen, dict) or not isinstance(screen.get("id"), str) or not screen["id"].strip():
            continue
        agent_id = screen["id"]
        if agent_id in seen:
            continue
        seen.add(agent_id)
        node_id = _screen_id(workspace["id"], agent_id)
        if node_id in existing:
            continue
        root = screen.get("root") if isinstance(screen.get("root"), dict) else {}
        device = screen.get("device") if isinstance(screen.get("device"), str) and screen["device"].strip() else "desktop"
        name = screen.get("name") if isinstance(screen.get("name"), str) and screen["name"].strip() else agent_id
        counts = defaultdict(int)
        _count(root, index, counts)
        nodes.append({
            "id": node_id, "parent_id": _parent(conn, root, index, workspace["id"]),
            "name": name, "attrs": {"device": device, "ref": agent_id, "root": root},
        })
        for comp_id, weight in counts.items():
            edges.append((node_id, comp_id, "sketches", "agent", 1.0, weight, None, 0))
    conn.executemany(
        "INSERT INTO nodes (id, parent_id, kind, display_kind, name, workspace_id, attrs) "
        "VALUES (?, ?, 'screen', 'screen', ?, ?, ?)",
        [(n["id"], n["parent_id"], n["name"], workspace["id"], json.dumps(n["attrs"], sort_keys=True)) for n in nodes],
    )
    conn.executemany(
        "INSERT INTO edges (src, dst, kind, source, confidence, weight, attrs, ordinal) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        edges,
    )
    return old, [n["id"] for n in nodes]


def _walk(region, path, index, covered, errors):
    if not isinstance(region, dict):
        errors.append(f"{path}: expected a region")
        return
    ref = region.get("component")
    if isinstance(ref, str) and ref.strip():
        hit = _resolve(index, ref)
        if hit is None:
            errors.append(f"{path}.component: {ref!r} is not a component")
        elif hit is AMBIGUOUS:
            errors.append(f"{path}.component: {ref!r} matches more than one component")
        else:
            covered.add(hit["id"])
    children = region.get("children")
    if children is None:
        return
    if not isinstance(children, list):
        errors.append(f"{path}.children: expected an array")
        return
    for i, child in enumerate(children):
        _walk(child, f"{path}.children[{i}]", index, covered, errors)


def problems(conn, answer):
    """Every failing check for one sketch-screens answer, schema-valid or hand-edited."""
    if not isinstance(answer, dict):
        return ["$: expected an object"]
    errors, covered = [], set()
    components, index, _files_now = _components(conn)
    screens = answer.get("screens")
    if not isinstance(screens, list):
        errors.append("$.screens: expected an array")
        screens = []
    workspace = _workspace(conn)
    taken = dict(conn.execute("SELECT id, kind FROM nodes WHERE kind != 'screen'")) if workspace else {}
    seen = {}
    for i, screen in enumerate(screens):
        if not isinstance(screen, dict):
            errors.append(f"$.screens[{i}]: expected a screen")
            continue
        agent_id = screen.get("id")
        if isinstance(agent_id, str):
            if agent_id in seen:
                errors.append(f"$.screens[{i}].id: {agent_id!r} is duplicated")
            else:
                seen[agent_id] = i
            if workspace:
                node_id = _screen_id(workspace["id"], agent_id)
                if node_id in taken:
                    errors.append(f"$.screens[{i}].id: {agent_id!r} is already a {taken[node_id]}")
        root = screen.get("root")
        if not isinstance(root, dict):
            errors.append(f"$.screens[{i}].root: expected a region")
        else:
            _walk(root, f"$.screens[{i}].root", index, covered, errors)
    unsketched = answer.get("unsketched") or []
    if not isinstance(unsketched, list):
        errors.append("$.unsketched: expected an array")
        unsketched = []
    for i, item in enumerate(unsketched):
        if not isinstance(item, dict):
            errors.append(f"$.unsketched[{i}]: expected an object")
            continue
        reason = item.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            errors.append(f"$.unsketched[{i}].reason: empty")
        ref = item.get("component")
        hit = _resolve(index, ref) if isinstance(ref, str) else None
        if hit is None:
            errors.append(f"$.unsketched[{i}].component: {ref!r} is not a component")
        elif hit is AMBIGUOUS:
            errors.append(f"$.unsketched[{i}].component: {ref!r} matches more than one component")
        else:
            covered.add(hit["id"])
    missing = sorted(comp["ref"] for comp in components if comp["ui"] and comp["id"] not in covered)
    if missing:
        errors.append("$.screens: UI components not sketched or listed in unsketched: " + ", ".join(missing))
    return errors


def _body(answer):
    body = {"screens": answer["screens"]}
    if answer.get("unsketched"):
        body["unsketched"] = answer["unsketched"]
    return body


def _cached(conn, digest):
    row = conn.execute("SELECT answer FROM cache.summary_answers WHERE input_hash = ?", (digest,)).fetchone()
    return json.loads(row[0]) if row else None


def _context(conn, root):
    components, index, files = _components(conn)
    entries = _entries(conn, components, files, index)
    _renders, _by, pairs = _render_maps(conn, index)
    states = _states(conn, components, files, root)
    listed = _listed(components, entries)
    return components, index, files, entries, pairs, states, listed


def refresh(conn, out=None, root=None):
    """Open, close or drop sketch-screens. It stays absent until concepts are done and a component exists."""
    if not _concepts_done(conn):
        conn.execute("DELETE FROM tasks WHERE kind = 'sketch-screens'")
        return
    workspace = _workspace(conn)
    components, _index_now, _files_now, entries, pairs, states, listed = _context(conn, root)
    if not workspace or not components:
        conn.execute("DELETE FROM tasks WHERE kind = 'sketch-screens'")
        return
    text = store.get_meta(conn, "screens_json")
    if text is None and out is not None:
        path = out / "screens.json"
        text = path.read_text() if path.exists() else ""
        store.set_meta(conn, "screens_json", text)
    data = _document(text)
    digest = _input_hash(listed, pairs, entries, states)
    cached = _cached(conn, digest)
    absent = out is not None and not (out / "screens.json").exists()
    if cached and data is None and absent and not problems(conn, cached):
        written = json.dumps(cached, indent=2) + "\n"
        (out / "screens.json").write_text(written)
        apply(conn, written)
        data = cached
    state = "done" if data is not None and not problems(conn, data) else "open"
    conn.execute(
        "INSERT INTO tasks (id, kind, node_id, input_hash, state, depends_on, inputs) "
        "VALUES (?, 'sketch-screens', ?, ?, ?, '[]', ?) "
        "ON CONFLICT(id) DO UPDATE SET node_id = excluded.node_id, input_hash = excluded.input_hash, "
        "state = excluded.state, depends_on = '[]', inputs = excluded.inputs",
        (_task_id(workspace["id"]), workspace["id"], digest, state,
         json.dumps([comp["id"] for comp in components if comp["ui"]])),
    )
    conn.execute("DELETE FROM tasks WHERE kind = 'sketch-screens' AND id != ?", (_task_id(workspace["id"]),))


def accept(conn, task, answer, out, root=None):
    """Write screens.json, project it, and close the task. Raises AnswerError listing every failure."""
    from cbi import tasks, team
    if out is None:
        raise tasks.AnswerError("$: no model directory; submit through `cbi submit`")
    errors = problems(conn, answer)
    if errors:
        raise tasks.AnswerError("\n".join(errors))
    body = _body(answer)
    text = json.dumps(body, indent=2) + "\n"
    current = (out / "screens.json").read_text() if (out / "screens.json").exists() else None
    if _cached(conn, task["input_hash"]) == body and current == text:
        team.sync(conn, out)
        return f"{task['id']}: already accepted, nothing changed"
    def write():
        (out / "screens.json").write_text(text)
        old, new = apply(conn, text)
        conn.execute("INSERT OR REPLACE INTO cache.summary_answers (input_hash, answer) VALUES (?, ?)",
                     (task["input_hash"], json.dumps(body)))
        before = {row[0] for row in conn.execute("SELECT id FROM tasks WHERE state = 'open'")}
        refresh(conn, out, root)
        store.reindex(conn, old + new)
        team.sync(conn, out)
        return sorted({row[0] for row in conn.execute("SELECT id FROM tasks WHERE state = 'open'")} - before)

    opened = store.retry_write(conn, write)
    suffix = f"; now open: {', '.join(opened)}" if opened else ""
    return f"{task['id']}: accepted{suffix}"


def _jsx(text, start, end, full=False):
    body = _slice(text, start, end).splitlines()
    if full:
        return "\n".join(body), False
    truncated = len(body) > JSX_LINES
    return "\n".join(body[:JSX_LINES]), truncated


def brief_body(conn, task, root=None, full_jsx=False):
    """UI components with their JSX, render edges, entry points and tab or state enums.

    full_jsx keeps every line of a component. A part of a large brief uses that, so nothing
    inside the part is cut off. The whole brief still stops at JSX_LINES.
    """
    components, index, files, entries, _pairs, states, listed = _context(conn, root)
    renders, rendered_by, _pairs = _render_maps(conn, index)
    cache = {}
    shown = []
    for comp in listed:
        jsx, truncated = _jsx(_read(root, comp["path"], cache, limit=not full_jsx), comp["start"], comp["end"], full_jsx)
        entry = {
            "id": comp["id"], "ref": comp["ref"], "name": comp["name"], "path": comp["path"],
            "concept": comp["concept"], "concept_name": comp["concept_name"],
            "signature": comp["signature"],
            "lines": f"{comp['start']}-{comp['end']}" if comp["start"] else "",
            "jsx": jsx, "renders": renders.get(comp["id"], []), "rendered_by": rendered_by.get(comp["id"], []),
        }
        if truncated:
            entry["jsx_truncated"] = True
        shown.append(entry)
    groups = defaultdict(list)
    names = {}
    for comp in components:
        if comp["ui"] and comp["concept"]:
            groups[comp["concept"]].append(comp["ref"])
            names[comp["concept"]] = comp["concept_name"]
    concepts = [{"id": cid, "name": names[cid], "components": groups[cid]} for cid in sorted(groups)]
    return {
        "checks": CHECKS,
        "entries": entries,
        "states": states,
        "concepts": concepts,
        "components": shown,
        "screens": _document(store.get_meta(conn, "screens_json")),
    }


def template(brief):
    comp = next((c["ref"] for c in brief.get("components") or []), "src/App.tsx#App")
    return {"input_hash": brief["input_hash"], "screens": [{
        "id": "main", "name": "Main", "device": "desktop",
        "root": {"id": "root", "layout": "column", "component": comp, "children": []},
    }]}


def format_brief(b):
    lines = [f"# Task {b['id']}: sketch-screens ({b['state']})",
             f"node: workspace {b['node_id']}", f"input_hash: {b['input_hash']}"]
    part = b.get("part")
    if part:
        lines.append(f"part: {part['index']} of {part['count']}  {part['name']}")
    lines += ["", b["instructions"], "", "## Checks"]
    lines += [f"- {check}" for check in b["checks"]]
    lines += ["", "## Screen entries"]
    lines += [f"  {e['component']}  from {e['from']}  {e['reason']}" for e in b.get("entries") or []] or ["  (none)"]
    lines += ["", "## Tabs and states"]
    states = b.get("states") or []
    if not states:
        lines.append("  (none)")
    for state in states:
        lines.append(f"  {state['name']}  {state['path']}  {', '.join(state['values'])}")
        lines.append(f"    set in {', '.join(state['set_in'])}")
    lines += ["", "## UI concepts"]
    concepts = b.get("concepts") or []
    if not concepts:
        lines.append("  (none)")
    for concept in concepts:
        lines.append(f"  {concept['id']}  {concept['name']}")
        lines += [f"    {ref}" for ref in concept["components"]]
    lines += ["", f"## Components ({len(b.get('components') or [])})"]
    for comp in b.get("components") or []:
        lines.append(f"### {comp['ref']}")
        bits = [comp["signature"]]
        if comp.get("lines"):
            bits.append(f"L{comp['lines']}")
        if comp.get("concept_name"):
            bits.append(comp["concept_name"])
        lines.append("  " + "  ".join(bit for bit in bits if bit))
        if comp["renders"]:
            lines.append("  renders " + ", ".join(comp["renders"]))
        if comp["rendered_by"]:
            lines.append("  rendered by " + ", ".join(comp["rendered_by"]))
        if comp.get("jsx_truncated"):
            lines.append("  jsx truncated; open the file")
        if comp.get("jsx"):
            lines.append("  jsx:")
            lines += [f"    {line}" for line in comp["jsx"].splitlines()]
    if b.get("screens"):
        lines += ["", "## Current screens", json.dumps(b["screens"], indent=2)]
    lines += ["", "## Answer schema", json.dumps(b["answer_schema"], indent=2), "", "## Answer template",
              json.dumps(template(b), indent=2), "",
              f"Submit with: cbi submit {b['id']} answer.json   (or pipe the JSON to `cbi submit {b['id']} -`)"]
    return "\n".join(lines)


def region_lines(region, indent=0):
    """Compact lines for one region tree. Text is quoted data, never markup."""
    if not isinstance(region, dict):
        return []
    bits = []
    if isinstance(region.get("layout"), str):
        bits.append(region["layout"])
    comp = region.get("component")
    if isinstance(comp, str) and comp:
        bits.append(comp.split("#")[-1])
    if isinstance(region.get("label"), str) and region["label"]:
        bits.append(region["label"])
    if isinstance(region.get("text"), str) and region["text"]:
        collapsed = " ".join(region["text"].split())
        dumped = json.dumps(collapsed, ensure_ascii=False)
        if len(dumped) > 60:
            dumped = json.dumps(collapsed[:40] + "...", ensure_ascii=False)
        bits.append(dumped)
    style = region.get("style")
    if isinstance(style, list) and style:
        bits.append("[" + " ".join(str(hint) for hint in style) + "]")
    cols = region.get("cols")
    if isinstance(cols, int) and not isinstance(cols, bool):
        bits.append(f"{cols} cols")
    when = region.get("when")
    if isinstance(when, str) and when.strip():
        bits.append("when " + json.dumps(when.strip(), ensure_ascii=False))
    pad = " " * indent
    lines = [pad + " ".join(bits)] if bits else []
    children = region.get("children")
    if isinstance(children, list):
        for child in children:
            lines.extend(region_lines(child, indent + 2))
    return lines


def appearances(conn, node_id):
    """Screens that sketch this node, by name."""
    rows = conn.execute(
        "SELECT s.id, s.name, coalesce(json_extract(s.attrs, '$.device'), 'desktop') "
        "FROM edges e JOIN nodes s ON s.id = e.src "
        "WHERE e.kind = 'sketches' AND e.dst = ? ORDER BY s.name, s.id", (node_id,))
    return [{"id": nid, "name": name, "device": device or "desktop"} for nid, name, device in rows]

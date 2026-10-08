"""A short Markdown description of one node, for pasting into an agent.

`cbi context` prints it. `cbi build` embeds the same text per viewable node so the
static viewer can copy it without running the CLI. Env var values, defaults and
examples are never included.
"""

import json
import shlex
import sqlite3
import subprocess
import sys
from pathlib import Path

from cbi import files, query, store

# Relationship bullets per direction, then the block is trimmed to this many lines.
REL_CAP = 10
INT_CAP = 6
CHILD_CAP = 12
ENV_CAP = 15
LINE_CAP = 60
_SKIP = {"tests", "reads_env", "sketches", "owns", "part_of", "pins"}
_BOX = {"concept", "workspace", "group", "deployable", "package"}
_NODE = ("id", "parent_id", "kind", "display_kind", "name", "workspace_id", "path", "start_line", "summary", "attrs")


class Place:
    """Where the commands in the block should look.

    model_root is the `.cbi` directory or the `--out` directory. model_db is the
    file those commands would open (a ref model lives under `refs/<sha>/`).
    compare is `(base, head)` as the user typed them.
    """

    def __init__(self, repo, model_root, model_db=None, branch=None, ref=None, sha=None, compare=None):
        self.repo = Path(repo).resolve()
        self.model_root = Path(model_root).resolve()
        self.model_db = Path(model_db).resolve() if model_db else self.model_root / "model.db"
        self.branch = branch or None
        self.ref = ref or None
        self.sha = sha or None
        self.compare = tuple(compare) if compare else None

    def version_line(self):
        if self.compare:
            return f"comparison {self.compare[0]}..{self.compare[1]}"
        if self.ref or self.sha:
            ref = self.ref or self.sha
            if self.sha and ref != self.sha:
                return f"ref {ref} ({self.sha})"
            return f"ref {self.sha or ref}"
        if self.branch:
            return f"worktree {self.repo} on {self.branch}"
        return f"worktree {self.repo}"


def current_branch(repo):
    """The checked-out branch name, or None when HEAD is detached or repo is not a worktree."""
    try:
        result = subprocess.run(
            ["git", "symbolic-ref", "--short", "HEAD"],
            cwd=repo, capture_output=True, text=True, check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def infer_place(viewer_out, root=None, compare=None):
    """A place for a viewer directory when the caller did not pass one.

    A comparison's head model is `refs/<sha>/model.db` when that file is already
    there. Otherwise the block points at the model next to the viewer.
    """
    viewer_out = Path(viewer_out)
    model_root = viewer_out.parent
    repo = model_root
    sha = None
    if isinstance(root, files.CommitTree):
        repo = Path(root.root)
        sha = root.sha
    elif root is not None:
        repo = Path(root)
    comp = None
    model_db = model_root / "model.db"
    if compare:
        base = compare.get("base_label") or ""
        head = compare.get("head_label") or ""
        comp = (base, head)
        candidate = model_root / "refs" / head / "model.db"
        if head and candidate.is_file():
            model_db = candidate
            sha = head
    branch = None if comp or sha else current_branch(repo)
    ref = sha if sha and not comp else None
    return Place(repo=repo, model_root=model_root, model_db=model_db, branch=branch, ref=ref, sha=sha, compare=comp)


def open_model(path):
    """Open a model read-only. Raises FileNotFoundError or sqlite3.Error."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    conn = store.read_only(path)
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    except sqlite3.Error:
        conn.close()
        raise
    if version != store.SCHEMA_VERSION:
        conn.close()
        raise sqlite3.DatabaseError(
            f"{path} is schema {version}; this cbi expects {store.SCHEMA_VERSION}. Rescan it.")
    return conn


def emit(conn, ref, place):
    """Print the block for ref. Returns 0, or 1 when ref does not name one node."""
    found = query._one(conn, ref, False)
    if not found:
        return 1
    sys.stdout.write(render(conn, found, place))
    return 0


def embed(conn, payload, place):
    """`{workspace, blocks}` for data/context.js. One block per box and symbol the viewer can select."""
    ids = []

    def walk(nodes):
        for node in nodes or []:
            ids.append(node["id"])
            for sym in node.get("symbols") or []:
                ids.append(sym["id"])
            walk(node.get("children"))

    walk(payload.get("concepts"))
    for ext in payload.get("externals") or []:
        ids.append(ext["id"])
    row = conn.execute(
        "SELECT id FROM nodes WHERE kind = 'workspace' AND parent_id IS NULL ORDER BY id LIMIT 1").fetchone()
    workspace = row[0] if row else ""
    if workspace:
        ids.append(workspace)
    facts = _facts(conn)
    blocks = {}
    for node_id in dict.fromkeys(ids):
        if _exists(conn, node_id):
            blocks[node_id] = render(conn, node_id, place, facts)
            continue
        # A fallback folder id is `<box>#<group>`. The group is the real node.
        group = node_id.split("#", 1)[1] if "#" in node_id else ""
        if group and _exists(conn, group):
            blocks[node_id] = blocks.get(group) or render(conn, group, place, facts)
            blocks.setdefault(group, blocks[node_id])
    return {"workspace": workspace, "blocks": blocks}


def render(conn, node_id, place, facts=None):
    """The Markdown block for one existing node. Always ends with a newline."""
    facts = facts or _facts(conn)
    row = conn.execute(f"SELECT {', '.join(_NODE)} FROM nodes WHERE id = ?", (node_id,)).fetchone()
    if not row:
        return ""
    node = dict(zip(_NODE, row))
    node["attrs"] = json.loads(node["attrs"]) if node["attrs"] else {}
    lines = _header(node, place, facts)
    lines += _identity(conn, node, facts)
    lines += _relations(conn, node, facts)
    lines += _tests_line(node, facts)
    lines += _env_line(node, facts)
    lines += _integrations(node, facts)
    lines += ["", "To see more", "", "```"]
    lines += _commands(node, place)
    lines += ["```"]
    lines = _fit(lines)
    return "\n".join(lines) + "\n"


def _exists(conn, node_id):
    return conn.execute("SELECT 1 FROM nodes WHERE id = ?", (node_id,)).fetchone() is not None


def _facts(conn):
    """Edges and names the block reads, loaded once so a build can render every node."""
    owners = {}
    for file_id, cid, name in conn.execute(
            "SELECT e.dst, c.id, c.name FROM edges e "
            "JOIN nodes c ON c.id = e.src AND c.kind = 'concept' WHERE e.kind = 'owns'"):
        owners[file_id] = (cid, name)
    concepts = {
        cid: (name, parent) for cid, name, parent in conn.execute(
            "SELECT id, name, parent_id FROM nodes WHERE kind = 'concept'")}
    names = dict(conn.execute("SELECT id, name FROM nodes"))
    kinds = dict(conn.execute("SELECT id, kind FROM nodes"))
    relates = []
    for src, dst, attrs in conn.execute("SELECT src, dst, attrs FROM edges WHERE kind = 'relates'"):
        relates.append((src, dst, json.loads(attrs) if attrs else {}))
    owns = [(src, dst) for src, dst in conn.execute("SELECT src, dst FROM edges WHERE kind = 'owns'")]
    reads = [(src, name) for src, name in conn.execute(
        "SELECT e.src, n.name FROM edges e JOIN nodes n ON n.id = e.dst WHERE e.kind = 'reads_env'")]
    tests = [(src, dst, confidence if confidence is not None else 1) for src, dst, confidence in conn.execute(
        "SELECT src, dst, confidence FROM edges WHERE kind = 'tests'")]
    parts = {}
    for dst, count in conn.execute("SELECT dst, count(*) FROM edges WHERE kind = 'part_of' GROUP BY dst"):
        parts[dst] = count
    top = conn.execute(
        "SELECT name FROM nodes WHERE kind = 'workspace' AND parent_id IS NULL ORDER BY id LIMIT 1").fetchone()
    return {
        "owners": owners, "concepts": concepts, "names": names, "kinds": kinds, "relates": relates,
        "owns": owns, "reads": reads, "tests": tests, "parts": parts,
        "project": top[0] if top and top[0] else "",
    }


def _header(node, place, facts):
    if node["kind"] == "workspace":
        project = node["name"]
    else:
        project = facts["project"] or place.repo.name
    return [
        f"# {node['name']}",
        "",
        f"Project: {project}",
        f"Path: {place.repo}",
        f"Model: {place.model_root}",
        f"Version: {place.version_line()}",
        "",
    ]


def _identity(conn, node, facts):
    lines = [
        f"kind: {node['display_kind']}",
        f"id: `{node['id']}`",
    ]
    if node["kind"] not in _BOX and node["path"]:
        line = f":{node['start_line']}" if node["start_line"] else ""
        lines.append(f"file: `{node['path']}{line}`")
    summary = " ".join((node["summary"] or "").split())
    if summary:
        lines.append(f"summary: {summary}")
    elif node["kind"] in ("concept", "workspace", "external"):
        lines.append("summary: (none yet)")
    chain = _chain(node, facts)
    if node["kind"] == "concept":
        if len(chain) > 1:
            lines.append("parents: " + " / ".join(chain[:-1]))
    elif chain:
        lines.append("concept: " + " / ".join(chain))
    if node["kind"] in _BOX:
        children = _children(conn, node)
        if children:
            shown = children[:CHILD_CAP]
            extra = len(children) - len(shown)
            text = ", ".join(shown)
            if extra:
                text += f" (+{extra})"
            lines.append(f"children: {text}")
        count = _file_count(node, facts)
        if node["kind"] == "concept":
            lines.append(f"owned files: {count}")
        elif count is not None:
            lines.append(f"files: {count}")
    if node["kind"] == "env":
        declared = node["attrs"].get("declared_in") or []
        if isinstance(declared, str):
            declared = [declared]
        declared = [str(item) for item in declared if isinstance(item, str) and item]
        if declared:
            lines.append("declared in: " + ", ".join(declared))
    return lines


def _chain(node, facts):
    """Concept names from the root down to this node's concept, or this concept."""
    if node["kind"] == "concept":
        cid = node["id"]
    else:
        owner = facts["owners"].get(_file_of(node))
        cid = owner[0] if owner else None
    names = []
    seen = set()
    while cid in facts["concepts"] and cid not in seen:
        seen.add(cid)
        name, parent = facts["concepts"][cid]
        names.append(name)
        cid = parent
    names.reverse()
    return names


def _file_of(node):
    if node["kind"] in ("file", "doc"):
        return node["id"]
    if "#" in node["id"]:
        return node["id"].split("#", 1)[0]
    return node["id"]


def _children(conn, node):
    if node["kind"] == "workspace":
        rows = conn.execute(
            "SELECT id, name, attrs FROM nodes WHERE parent_id = ? AND kind = 'concept'", (node["id"],)).fetchall()
        if not rows:
            rows = conn.execute(
                "SELECT id, name, attrs FROM nodes WHERE parent_id = ? AND kind IN ('deployable', 'package') "
                "ORDER BY kind, name, id", (node["id"],)).fetchall()
        return [name for _cid, name, _attrs in _by_order(rows)]
    if node["kind"] == "concept":
        rows = conn.execute(
            "SELECT id, name, attrs FROM nodes WHERE parent_id = ? AND kind = 'concept'", (node["id"],)).fetchall()
        return [name for _cid, name, _attrs in _by_order(rows)]
    rows = conn.execute(
        "SELECT name FROM nodes WHERE parent_id = ? ORDER BY name, id", (node["id"],)).fetchall()
    return [row[0] for row in rows]


def _by_order(rows):
    def key(row):
        attrs = json.loads(row[2]) if row[2] else {}
        order = attrs.get("order")
        return (order if isinstance(order, int) else 1000, row[1], row[0])
    return sorted(rows, key=key)


def _concept_tree(facts, cid):
    kids = {}
    for node_id, (_name, parent) in facts["concepts"].items():
        kids.setdefault(parent, []).append(node_id)
    out, stack, seen = [], [cid], set()
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        out.append(cur)
        stack.extend(kids.get(cur, ()))
    return out


def _file_count(node, facts):
    if node["kind"] == "concept":
        owned = set(_concept_tree(facts, node["id"]))
        return len({dst for src, dst in facts["owns"] if src in owned})
    if node["kind"] == "workspace":
        if facts["owns"]:
            return len({dst for _src, dst in facts["owns"]})
        return None
    if node["kind"] in ("deployable", "package"):
        return facts["parts"].get(node["id"], 0)
    return None


def _relations(conn, node, facts):
    home = facts["owners"].get(_file_of(node))
    home_id = home[0] if home else None
    outgoing = query._edges(conn, node["id"], "src", "dst")
    incoming = query._edges(conn, node["id"], "dst", "src")
    lines = []
    for title, edges, direction in (("Out", outgoing, "outgoing"), ("In", incoming, "incoming")):
        body = _relation_lines(edges, direction, facts, home_id)
        if body:
            lines += ["", title, *body]
    return lines


def _relation_lines(edges, direction, facts, home_id):
    kept = []
    for edge in edges:
        if edge["kind"] in _SKIP or not query._keep_under_floor(edge, query.SHOW_CONFIDENCE):
            continue
        kept.append(edge)
    kept.sort(key=lambda edge: (_label(edge, direction), edge["name"] or "", edge["id"]))
    shown, extra = kept[:REL_CAP], len(kept) - REL_CAP
    lines, current = [], None
    for edge in shown:
        label = _label(edge, direction)
        if label != current:
            current = label
            lines.append(label)
        concept = _other_concept(edge, facts, home_id)
        item = f"- `{edge['name']}`"
        if concept:
            item += f" ({concept})"
        if edge["kind"] == "relates" and (edge.get("attrs") or {}).get("minor"):
            item += " [minor]"
        lines.append(item)
    if extra > 0:
        lines.append(f"- ... {extra} more")
    return lines


def _label(edge, direction):
    attrs = edge.get("attrs") or {}
    out = direction == "outgoing"
    if edge["kind"] == "imports" and attrs.get("type_only"):
        return "imports types from" if out else "type-imported by"
    if edge["kind"] == "calls" and attrs.get("via") == "jsx":
        return "renders" if out else "rendered by"
    if edge["kind"] == "calls" and attrs.get("via") == "injection":
        return "calls" if out else "called by"
    if edge["kind"] == "calls":
        return "calls" if out else "called by"
    if edge["kind"] == "imports":
        return "imports" if out else "imported by"
    if edge["kind"] == "relates":
        if attrs.get("kind") == "hosts":
            return "hosts" if out else "hosted by"
        return attrs.get("label") or "relates"
    if edge["kind"] == "references":
        return "references" if out else "referenced by"
    if edge["kind"] == "mentions":
        return "mentions" if out else "mentioned by"
    return edge["kind"] if out else f"{edge['kind']} by"


def _other_concept(edge, facts, home_id):
    """The other node's concept, when it has one and it is not this node's own."""
    if facts["kinds"].get(edge["id"]) in ("concept", "external", "workspace"):
        return ""
    owner = facts["owners"].get(edge["id"].split("#", 1)[0])
    if not owner or owner[0] == home_id:
        return ""
    return owner[1]


def _tests_line(node, facts):
    count = _test_count(node, facts)
    if node["kind"] in ("symbol", "file", "concept", "group") or count:
        return ["", f"Tests: {count} linked"]
    return []


def _test_count(node, facts):
    if node["kind"] == "concept":
        files = {dst for src, dst in facts["owns"] if src in set(_concept_tree(facts, node["id"]))}
        dsts = set()
        for src, dst, confidence in facts["tests"]:
            if confidence < query.SHOW_CONFIDENCE:
                continue
            file_id = dst.split("#", 1)[0]
            if dst in files or file_id in files:
                dsts.add(src)
        return len(dsts)
    prefix = node["id"] + "."
    seen = set()
    for src, dst, confidence in facts["tests"]:
        if confidence < query.SHOW_CONFIDENCE:
            continue
        if dst == node["id"] or dst.startswith(prefix):
            seen.add(src)
    return len(seen)


def _env_line(node, facts):
    """Names only. Defaults and example values stay in the model and out of this block."""
    names = _env_names(node, facts)
    if not names:
        return []
    shown = names[:ENV_CAP]
    extra = len(names) - len(shown)
    text = ", ".join(shown)
    if extra:
        text += f" (+{extra})"
    return ["", f"Environment: {text}"]


def _env_names(node, facts):
    if node["kind"] == "env":
        return []
    readers = _reader_ids(node, facts)
    if readers is None:
        names = sorted({name for _src, name in facts["reads"]})
    else:
        names = sorted({name for src, name in facts["reads"] if src in readers or _file_of_id(src) in readers})
    return names


def _reader_ids(node, facts):
    """Node ids whose reads_env edges count, or None for the whole model (a workspace)."""
    if node["kind"] == "workspace":
        return None
    if node["kind"] == "concept":
        files = {dst for src, dst in facts["owns"] if src in set(_concept_tree(facts, node["id"]))}
        return files
    if node["kind"] in ("file", "doc", "symbol"):
        return {node["id"]}
    return set()


def _file_of_id(node_id):
    return node_id.split("#", 1)[0]


def _integrations(node, facts):
    lines = []
    for src, dst, attrs in facts["relates"]:
        if not _integration_for(node, src, dst, attrs, facts):
            continue
        label = attrs.get("label") or ("hosts" if attrs.get("kind") == "hosts" else "relates")
        via = attrs.get("via") or attrs.get("mechanism")
        text = f"- {facts['names'].get(src, src)} {label} {facts['names'].get(dst, dst)}"
        if via:
            text += f" via {via}"
        if attrs.get("at"):
            text += f" at {attrs['at']}"
        lines.append(text)
        if len(lines) >= INT_CAP:
            break
    if not lines:
        return []
    return ["", "Integration points", *lines]


def _integration_for(node, src, dst, attrs, facts):
    external = facts["kinds"].get(src) == "external" or facts["kinds"].get(dst) == "external"
    if not (attrs.get("integration") or external):
        return False
    if node["kind"] == "workspace":
        return bool(attrs.get("integration") or external)
    if node["kind"] == "external":
        return node["id"] in (src, dst)
    if node["kind"] == "concept":
        tree = set(_concept_tree(facts, node["id"]))
        return src in tree or dst in tree
    return _at_matches(attrs.get("at"), node)


def _at_matches(at, node):
    if not at or not node.get("path"):
        return False
    file, sep, fn = str(at).partition(":")
    if not sep or file != node["path"]:
        return False
    qual = node["id"].split("#", 1)[-1] if "#" in node["id"] else node["name"]
    return fn in (node["name"], qual, qual.rsplit(".", 1)[-1])


def _commands(node, place):
    name = node["name"] if node["name"] and node["name"] != "*" else node["id"]
    lines = [
        _join(["cd", str(place.repo)]),
        _cbi(place, "show", node["id"]),
        _cbi(place, "tests-for", node["id"]),
        _cbi(place, "search", name),
    ]
    diff = _diff_command(place)
    if diff:
        lines.append(diff)
    sql = (
        "select src, dst, kind, source, confidence from edges "
        f"where src={_sql_quote(node['id'])} or dst={_sql_quote(node['id'])}"
    )
    lines.append(_join(["sqlite3", str(place.model_db), sql]))
    return lines


def _cbi(place, sub, arg):
    return _join(["cbi", sub, arg, *_tail(place)])


def _diff_command(place):
    if not place.compare:
        return ""
    tail = _out_flag(place)
    return _join(["cbi", "diff", place.compare[0], place.compare[1], *tail])


def _tail(place):
    tail = _out_flag(place)
    if place.compare:
        tail += ["--ref", place.compare[1]]
    elif place.ref:
        tail += ["--ref", place.ref]
    elif place.sha and not place.branch:
        tail += ["--ref", place.sha]
    return tail


def _out_flag(place):
    if place.model_root.resolve() == (place.repo / ".cbi").resolve():
        return []
    return ["--out", str(place.model_root)]


def _join(args):
    return " ".join(shlex.quote(str(arg)) for arg in args if arg is not None and str(arg) != "")


def _sql_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def _fit(lines):
    """Drop relationship bullets until the block is about 60 lines. The commands stay."""
    if len(lines) <= LINE_CAP:
        return lines
    try:
        end = lines.index("To see more")
    except ValueError:
        return lines
    body, tail = lines[:end], lines[end:]
    while len(body) + len(tail) > LINE_CAP and any(line.startswith("- ") for line in body):
        for index in range(len(body) - 1, -1, -1):
            if body[index].startswith("- "):
                del body[index]
                break
    return body + tail

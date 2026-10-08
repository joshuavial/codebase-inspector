"""Read commands over the model: search, show, tests-for and status.

Every function takes an open model connection and the parsed arguments, prints text or
JSON and returns the exit code. Nothing here knows the full list of node, edge or
diagnostic kinds; it prints whatever the model holds.
"""

import json
import posixpath
import sys

from cbi import store

HELP = {
    "search": """\
Full-text search over node names, display kinds, paths, signatures, docs and
summaries. Each word of TEXT also matches as a prefix, and every word must
match. Hits come best first: a name match outranks a path, doc or summary
match. A query that contains / also matches HTTP routes by path.

Text output: one hit per two lines, display kind, name and path:line, then
the node ID to pass to `cbi show`.
--json: a list of {id, kind, display_kind, name, path, start_line}.

--kind K keeps hits whose display kind (class, function, test case, folder,
env var, ...) or internal kind (symbol, test, file, group, env, ...) is K.

Exit codes: 0 done (even with no hits), 1 no model (run `cbi scan`).

Example: cbi search registry --kind class --limit 5""",
    "show": """\
Show one node: display kind, path and lines, summary, signature, doc,
children, relationships, linked tests and diagnostics.

NODE can be a node ID, a path from the repo root (service/registry.ts, or
service/ for a folder), a path with a qualified name
(service/registry.ts#DeviceRegistry.load), a qualified name
(DeviceRegistry.load) or a bare name (DeviceRegistry, registry.ts). When
several nodes match, none is shown: the candidates are listed with their
IDs so you can pick one.

Relationships are this node's own edges: outgoing (what it imports, calls
or tests) and incoming (what imports, calls or tests it). Text lists them
imports, calls, renders, tests, then mentions, then any other kind. Each
has a source (treesitter from the syntax tree, naming from file names, ...)
and a confidence from 0 to 1. Text hides edges below 0.6 unless
--min-confidence F sets another floor from 0 to 1; --json keeps every edge
unless that flag is passed. An injection call stays visible below that floor:
it is a production call. --all lifts the cap of 10 per kind and
direction. A calls edge whose attrs are {"via": "jsx"} is printed as
renders. An imports edge whose attrs are {"type_only": true} is printed as
imports types from. A calls edge whose attrs are {"via": "injection"} is a
constructor-injected call. A part_of edge is marked direct or transitive
when its attrs say so. An env var node lists its readers and where it is
declared (`declared_in`, and `example` from an example file). A reads_env
edge is an environment variable this node reads; its attrs hold `default`
for a string default. A relates edge prints its label, then via and at when
the relationship has them, and tags [minor] and [integration]. A concept
with entry true prints `starts here` and its entry file. A concept a hosts
relationship points at prints `hosted by` that concept's name. A file that
spreads `...process.env` says it passes the whole environment. Once
concepts exist, each calls edge also names the other function's owning
concept and module (the file's base name). Text lists those as calls,
called by, renders and rendered by, grouped by concept, with the shown
symbol's own concept first. An http_calls edge is printed as calls
endpoints or called by clients, with its method and path. A relates edge
lists the HTTP endpoints between the two concepts. A screen prints its
device and region tree (text is quoted data, not HTML). A region with
`when` prints that condition. A component lists the screens it appears
on. Incoming tests edges print once, under tests,
which also covers the node's descendants as in `cbi tests-for NODE`.

--json: the node's columns (kind and display_kind, attrs as an object)
plus `children` [{id, display_kind, name, start_line, end_line}],
`outgoing` and `incoming` [{kind, source, confidence, weight, attrs, id,
display_kind, name, path, start_line}] sorted by kind, `tests` (as in
`cbi tests-for --json`) and `diagnostics` [{kind, detail}]. Once concepts
exist, a calls edge also has `concept` ({id, name}, or null when that file
has no owner) and `module`. A node that appears on a screen also has
`screens` [{id, name, device}].
When NODE is ambiguous or unknown, --json prints {error, candidates} where
candidates is [{id, display_kind, name, path, start_line}].

Exit codes: 0 found, 1 not found, ambiguous or no model.

Example: cbi show DeviceRegistry.revoke""",
    "tests-for": """\
List the tests linked to a node or to anything inside it (a file's
symbols, a class's methods, a folder's files). NODE is resolved as in
`cbi show`. One test case, test suite or test file per line, best
confidence first, with how it was linked (treesitter: it calls the code,
imports it or reads the file; naming: x.test.ts beside x.ts; coverage:
per-test coverage) and the last recorded results. When coverage has been
ingested, a line per file gives the covered and measured lines within the
node.

--json: {node, tests, coverage}. tests is [{id, display_kind, name, path,
start_line, confidence, sources, targets, results}], where targets counts
the linked nodes inside NODE and results is [{status, duration_ms,
artifact}]. coverage is [{file_id, path, covered, lines, percent,
artifacts}], empty when none was ingested.

Exit codes: 0 done (even with no tests), 1 not found, ambiguous or no
model.

Example: cbi tests-for service/registry.ts --json""",
    "status": """\
Summarise the model: when the last scan ran, node counts by display kind,
open judgement tasks by kind (work through them with `cbi tasks`) and
diagnostics by kind with a few example nodes (see one node's with
`cbi show`).

--json: {scanned_at, nodes: {display kind: count}, open_tasks: {kind:
count}, diagnostics: {kind: {count, examples: [{node_id, path,
detail}]}}}. scanned_at is local ISO time, null before the first scan.

Exit codes: 0 done, 1 no model (run `cbi init` and `cbi scan`).

Example: cbi status --json""",
}

DIAGNOSTIC_EXAMPLES = 3
SHOW_EDGE_LIMIT = 10
SHOW_TEST_LIMIT = 10
SHOW_CONFIDENCE = 0.6
REL_ORDER = ("imports", "calls", "calls endpoints", "called by clients", "renders", "tests", "mentions")


def _print_json(value):
    print(json.dumps(value, indent=2))


def _where(path, line):
    return f"{path}:{line}" if line else (path or "")


# --- search ---------------------------------------------------------------------


def _search_query(text):
    """Each word as a quoted FTS5 prefix term, so user text cannot inject query syntax."""
    return " ".join('"' + w.replace('"', '""') + '"*' for w in text.split())


def search(conn, args):
    text = " ".join(args.text)
    query = _search_query(text)
    kind_filter = " AND (n.display_kind = :kind OR n.kind = :kind)" if args.kind else ""
    rows = conn.execute(
        "SELECT n.id, n.kind, n.display_kind, n.name, n.path, n.start_line FROM search s JOIN nodes n ON n.id = s.id "
        # Weights per column: id, name, display_kind, path, signature, doc, summary.
        f"WHERE search MATCH :q{kind_filter} ORDER BY bm25(search, 0, 10, 2, 3, 2, 1, 1) LIMIT :limit",
        {"q": query, "kind": args.kind, "limit": args.limit},
    ).fetchall() if query else []
    hits = [dict(zip(("id", "kind", "display_kind", "name", "path", "start_line"), r)) for r in rows]
    if "/" in text:
        seen = {hit["id"] for hit in hits}
        for row in _route_hits(conn, text, args.kind, args.limit):
            hit = dict(zip(("id", "kind", "display_kind", "name", "path", "start_line"), row))
            if hit["id"] not in seen:
                seen.add(hit["id"])
                hits.append(hit)
        hits = hits[:args.limit]
    if args.json:
        _print_json(hits)
        return 0
    for h in hits:
        print(f"{h['display_kind']:<12} {h['name']}  {_where(h['path'], h['start_line'])}\n  {h['id']}")
    if not hits:
        print(f"no matches for {text!r}" + (f" with kind {args.kind!r}" if args.kind else ""))
    return 0


# --- resolving a node reference -------------------------------------------------


def _route_hits(conn, text, kind, limit):
    """Nodes whose stored route path contains text. `/` is not an FTS token."""
    needle = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    kind_sql = " AND (display_kind = ? OR kind = ?)" if kind else ""
    params = [f"%{needle}%"]
    if kind:
        params.extend((kind, kind))
    params.append(limit)
    return conn.execute(
        "SELECT id, kind, display_kind, name, path, start_line FROM nodes "
        f"WHERE attrs LIKE ? ESCAPE '\\'{kind_sql} ORDER BY path, start_line, id LIMIT ?",
        params,
    ).fetchall()


def resolve(conn, ref):
    """Node IDs matching ref, tried as an ID, a path, path#qualified.name, then a name or qualified name."""
    if conn.execute("SELECT 1 FROM nodes WHERE id = ?", (ref,)).fetchone():
        return [ref]
    path, sep, qualname = ref.partition("#")
    path = path.strip("/")
    found = [r[0] for r in conn.execute(
        "SELECT n.id FROM nodes n LEFT JOIN nodes w ON w.id = n.workspace_id "
        "WHERE n.kind IN ('file', 'doc', 'group') AND (n.path = ? OR "
        "coalesce(json_extract(w.attrs, '$.root'), '') || '/' || n.path = ?) ORDER BY n.id",
        (path, path),
    )]
    if sep:
        found = [f"{f}#{qualname}" for f in found]
        found = [i for i in found if conn.execute("SELECT 1 FROM nodes WHERE id = ?", (i,)).fetchone()]
    if found:
        return found
    return [r[0] for r in conn.execute(
        "SELECT id FROM nodes WHERE name = ?1 OR substr(id, -length(?1) - 1) = '#' || ?1 ORDER BY id", (ref,))]


def _brief(conn, ids):
    return [dict(zip(("id", "display_kind", "name", "path", "start_line"), conn.execute(
        "SELECT id, display_kind, name, path, start_line FROM nodes WHERE id = ?", (i,)).fetchone())) for i in ids]


def _one(conn, ref, as_json):
    """The single node ID ref names, or None after printing why not (candidates when ambiguous)."""
    ids = resolve(conn, ref)
    if len(ids) == 1:
        return ids[0]
    error = f"no node matches {ref!r}" if not ids else f"{ref!r} matches {len(ids)} nodes; pick one by ID"
    candidates = _brief(conn, ids)
    if as_json:
        _print_json({"error": error, "candidates": candidates})
        return None
    print(error, file=sys.stderr)
    for c in candidates:
        print(f"  {c['display_kind']:<12} {c['name']}  {_where(c['path'], c['start_line'])}\n    {c['id']}",
              file=sys.stderr)
    return None


# --- tests-for ------------------------------------------------------------------


def _scope(conn, node_id):
    """(kind, ID prefix of the node's descendants or None). Descendants share an ID prefix:
    file#name, class#name.member, folder/..., workspace:..."""
    kind = conn.execute("SELECT kind FROM nodes WHERE id = ?", (node_id,)).fetchone()[0]
    sep = {"file": "#", "doc": "#", "symbol": ".", "workspace": ":", "group": ""}.get(kind)
    return kind, None if sep is None else node_id + sep


def linked_tests(conn, node_id):
    _, prefix = _scope(conn, node_id)
    rows = conn.execute(
        "SELECT n.id, n.display_kind, n.name, n.path, n.start_line, max(e.confidence), "
        "group_concat(DISTINCT e.source), count(DISTINCT e.dst) "
        "FROM edges e JOIN nodes n ON n.id = e.src WHERE e.kind = 'tests' AND "
        "(e.dst = :id OR (:prefix IS NOT NULL AND substr(e.dst, 1, length(:prefix)) = :prefix)) "
        "GROUP BY n.id ORDER BY max(e.confidence) DESC, n.path, n.start_line, n.id",
        {"id": node_id, "prefix": prefix},
    ).fetchall()
    tests = [dict(zip(("id", "display_kind", "name", "path", "start_line", "confidence", "sources", "targets"), r))
             for r in rows]
    for t in tests:
        t["sources"] = sorted(t["sources"].split(","))
        t["results"] = [dict(zip(("status", "duration_ms", "artifact"), r)) for r in conn.execute(
            "SELECT status, duration_ms, artifact FROM results WHERE test_node_id = ? ORDER BY artifact", (t["id"],))]
    return tests


def coverage(conn, node_id):
    """Covered and measured lines per file inside the node. A line is covered if any artifact hit it."""
    kind, prefix = _scope(conn, node_id)
    path, ws, start, end = conn.execute(
        "SELECT path, workspace_id, start_line, end_line FROM nodes WHERE id = ?", (node_id,)).fetchone()
    if start and kind not in ("file", "doc"):  # a symbol or test: lines of its file within its range
        where = ("c.file_id = (SELECT id FROM nodes WHERE kind IN ('file', 'doc') AND workspace_id = :ws AND path = :path) "
                 "AND c.line BETWEEN :start AND :end")
    else:
        where = "(c.file_id = :id OR (:prefix IS NOT NULL AND substr(c.file_id, 1, length(:prefix)) = :prefix))"
    rows = conn.execute(
        "SELECT file_id, f.path, sum(hits > 0), count(*), group_concat(DISTINCT artifacts) FROM ("
        "  SELECT c.file_id, c.line, max(c.hits) AS hits, group_concat(DISTINCT c.artifact) AS artifacts "
        f"  FROM coverage_lines c WHERE {where} GROUP BY c.file_id, c.line"
        ") LEFT JOIN nodes f ON f.id = file_id GROUP BY file_id ORDER BY f.path, file_id",
        {"id": node_id, "prefix": prefix, "ws": ws, "path": path, "start": start, "end": end},
    ).fetchall()
    return [{"file_id": r[0], "path": r[1], "covered": r[2], "lines": r[3], "percent": round(100 * r[2] / r[3], 1),
             "artifacts": sorted(set(r[4].split(",")))} for r in rows]


def _test_line(t):
    results = ", ".join(r["status"] for r in t["results"])
    return (f"{t['display_kind']:<12} {t['name']}  {_where(t['path'], t['start_line'])}  "
            f"({', '.join(t['sources'])} {t['confidence']:g})" + (f"  last: {results}" if results else ""))


def tests_for(conn, args):
    found = _one(conn, args.node, args.json)
    if not found:
        return 1
    tests, cov = linked_tests(conn, found), coverage(conn, found)
    if args.json:
        _print_json({"node": found, "tests": tests, "coverage": cov})
        return 0
    for t in tests:
        print(_test_line(t))
    if not tests:
        print(f"no tests linked to {found}")
    for c in cov:
        print(f"coverage     {c['path'] or c['file_id']}  {c['covered']}/{c['lines']} lines ({c['percent']:g}%)")
    return 0


# --- show -----------------------------------------------------------------------

SHOW_COLUMNS = ("id", "parent_id", "kind", "display_kind", "name", "workspace_id", "path", "start_line",
                "end_line", "lang", "loc", "content_hash", "signature", "doc", "summary", "summary_source", "attrs")
EDGE_FIELDS = ("kind", "source", "confidence", "weight", "attrs", "id", "display_kind", "name", "path", "start_line")


def _edges(conn, node_id, here, there):
    """Edges with node_id at the `here` end, joined to the node at the `there` end."""
    edges = []
    for r in conn.execute(
            f"SELECT e.kind, e.source, e.confidence, e.weight, e.attrs, n.id, n.display_kind, n.name, n.path, n.start_line "
            f"FROM edges e JOIN nodes n ON n.id = e.{there} WHERE e.{here} = ? "
            "ORDER BY e.kind, n.path, n.start_line, n.id", (node_id,)):
        edge = dict(zip(EDGE_FIELDS, r))
        edge["attrs"] = json.loads(edge["attrs"]) if edge["attrs"] else None
        edges.append(edge)
    return edges


def _concept_place(node):
    """`starts here` for an entry concept, otherwise `hosted by` when a hosts edge points here."""
    attrs = node.get("attrs") or {}
    if attrs.get("entry"):
        file = attrs.get("entry_file")
        if isinstance(file, list):
            file = ", ".join(str(item) for item in file if item)
        if isinstance(file, str) and file:
            return f"  starts here ({file})"
        return "  starts here"
    hosts = sorted({
        edge["name"] for edge in node.get("incoming") or []
        if edge["kind"] == "relates" and (edge.get("attrs") or {}).get("kind") == "hosts" and edge.get("name")
    })
    if hosts:
        return "  hosted by " + ", ".join(hosts)
    return ""


def _relates_suffix(edge):
    if edge["kind"] != "relates":
        return ""
    attrs = edge["attrs"] or {}
    bits = [attrs.get("label") or ""]
    via = attrs.get("via") or attrs.get("mechanism")
    if via:
        bits.append(f"via {via}")
    if attrs.get("at"):
        bits.append(f"at {attrs['at']}")
    text = " ".join(bit for bit in bits if bit)
    tags = []
    if attrs.get("minor"):
        tags.append("[minor]")
    if attrs.get("integration"):
        tags.append("[integration]")
    if tags:
        text = f"{text} {' '.join(tags)}".strip()
    return f"  {text}" if text else ""


CALL_LABELS = frozenset({"calls", "called by", "renders", "rendered by"})


def _annotate_calls(conn, node):
    """Once concepts exist, name the owning concept and module on each calls edge.

    Returns the concept id that owns this node's file, when it has one.
    """
    if not conn.execute("SELECT 1 FROM nodes WHERE kind = 'concept' LIMIT 1").fetchone():
        return None
    owners = {
        file_id: {"id": cid, "name": name}
        for file_id, cid, name in conn.execute(
            "SELECT e.dst, c.id, c.name FROM edges e "
            "JOIN nodes c ON c.id = e.src AND c.kind = 'concept' WHERE e.kind = 'owns'")
    }
    for edge in (*node["outgoing"], *node["incoming"]):
        if edge["kind"] != "calls":
            continue
        edge["concept"] = owners.get(edge["id"].split("#", 1)[0])
        edge["module"] = posixpath.basename(edge["path"]) if edge["path"] else None
    owner = owners.get(node["id"].split("#", 1)[0])
    return owner["id"] if owner else None


def _call_label(edge, direction):
    if edge["kind"] == "http_calls":
        return "called by clients" if direction == "incoming" else "calls endpoints"
    if edge["kind"] == "imports" and (edge["attrs"] or {}).get("type_only"):
        return "imports types from"
    jsx = edge["kind"] == "calls" and (edge["attrs"] or {}).get("via") == "jsx"
    if "concept" in edge:
        if direction == "incoming":
            return "rendered by" if jsx else "called by"
        return "renders" if jsx else "calls"
    return "renders" if jsx else edge["kind"]


def _concept_suffix(edge):
    if "concept" not in edge:
        return ""
    name = (edge["concept"] or {}).get("name")
    module = edge.get("module")
    bits = [bit for bit in (name, module) if bit]
    return "  " + ", ".join(bits) if bits else ""


def _part_suffix(edge):
    if edge["kind"] != "part_of":
        return ""
    via = (edge["attrs"] or {}).get("via")
    return f"  {via}" if via in ("direct", "transitive") else ""


def _edge_line(node, kind, edge, indent="    "):
    if edge["kind"] == "http_calls":
        attrs = edge["attrs"] or {}
        method = attrs.get("method") or ""
        path = attrs.get("path") or ""
        return (f"{indent}{kind:<8} {method} {path}  {edge['display_kind']} {edge['name']}"
                f"  ({edge['source']} {edge['confidence']:g})")
    same_file = edge["path"] == node["path"] and edge["display_kind"] not in ("source file", "test file")
    where = "" if not edge["path"] or same_file else f"  {edge['path']}"
    line = f":{edge['start_line']}" if edge["start_line"] and where else ""
    default = edge["attrs"].get("default") if edge["kind"] == "reads_env" and edge["attrs"] else None
    suffix = f"  default={default!r}" if default is not None else ""
    return (f"{indent}{kind:<8} {edge['display_kind']:<12} {edge['name']}{where}{line}{suffix}"
            f"{_part_suffix(edge)}  ({edge['source']} {edge['confidence']:g})"
            f"{_relates_suffix(edge)}{_concept_suffix(edge)}")


def _rel_key(kind):
    try:
        return (0, REL_ORDER.index(kind), "")
    except ValueError:
        return (1, 0, kind)


def _confidence_floor(args):
    """Text defaults to 0.6. JSON keeps every edge unless --min-confidence is set. None when F is invalid."""
    raw = getattr(args, "min_confidence", None)
    if raw is None:
        return 0.0 if args.json else SHOW_CONFIDENCE
    if not 0 <= raw <= 1:
        print("error: --min-confidence must be between 0 and 1", file=sys.stderr)
        return None
    return raw


def _print_call_groups(node, kind, edges, home):
    groups = {}
    for edge in edges:
        key = edge["concept"]["id"] if edge["concept"] else None
        groups.setdefault(key, []).append(edge)

    def order(key):
        if key is None:
            return (2, "", "")
        if key == home:
            return (0, "", key)
        return (1, groups[key][0]["concept"]["name"], key)

    ordered = sorted(groups, key=order)
    multi = len(ordered) > 1
    for key in ordered:
        if multi:
            if key is None:
                title = "(unowned)"
            else:
                title = groups[key][0]["concept"]["name"]
                if key == home:
                    title = f"{title} (here)"
            print(f"    {title}")
        indent = "      " if multi else "    "
        for edge in groups[key]:
            print(_edge_line(node, kind, edge, indent))


def _print_direction(node, direction, home, limit):
    shown = [edge for edge in node[direction] if edge["kind"] != "sketches"]
    by_kind = {}
    for edge in shown:
        by_kind.setdefault(_call_label(edge, direction), []).append(edge)
    kinds = sorted(by_kind, key=_rel_key)
    if kinds:
        print(f"  {direction} ({len(shown)}): " + ", ".join(
            f"{kind} {len(by_kind[kind])}" for kind in kinds))
    for kind in kinds:
        edges = by_kind[kind]
        if direction == "incoming" and edges[0]["kind"] == "tests":
            continue  # listed under tests below
        shown = edges if limit is None else edges[:limit]
        if kind in CALL_LABELS and "concept" in edges[0]:
            _print_call_groups(node, kind, shown, home)
        else:
            for edge in shown:
                print(_edge_line(node, kind, edge))
                for ep in edge.get("endpoints") or []:
                    print(f"      {ep['method']} {ep['path']}  {ep.get('dst_name') or ''}".rstrip())
        if limit is not None and len(edges) > limit:
            print(f"    ... {len(edges) - limit} more {kind}; use --all or --json")


def _keep_under_floor(edge, floor):
    if edge["confidence"] >= floor:
        return True
    # Injection is a production call even at the resolver's 0.4-0.7 confidence.
    return edge["kind"] == "calls" and (edge.get("attrs") or {}).get("via") == "injection"


def _apply_floor(node, floor):
    for direction in ("outgoing", "incoming"):
        node[direction] = [e for e in node[direction] if _keep_under_floor(e, floor)]
    node["tests"] = [t for t in node["tests"] if t["confidence"] >= floor]


def _concept_files(conn):
    """Concept id -> file ids owned by that concept or a descendant."""
    children = {}
    for cid, parent in conn.execute("SELECT id, parent_id FROM nodes WHERE kind = 'concept'"):
        children.setdefault(parent, []).append(cid)
    owns = {}
    for src, dst in conn.execute("SELECT src, dst FROM edges WHERE kind = 'owns'"):
        owns.setdefault(src, set()).add(dst)
    cache = {}

    def files(cid, seen):
        if cid in cache:
            return cache[cid]
        if cid in seen:
            return set()
        seen = seen | {cid}
        found = set(owns.get(cid, ()))
        for kid in children.get(cid, ()):
            found |= files(kid, seen)
        cache[cid] = found
        return found

    return {cid: files(cid, set()) for (cid,) in conn.execute("SELECT id FROM nodes WHERE kind = 'concept'")}


def _attach_http_endpoints(conn, node):
    """List the HTTP calls between this concept and each concept it relates to."""
    trees = _concept_files(conn)
    mine = trees.get(node["id"], set())
    file_of = {}
    http = []
    for src, dst, attrs, src_name, dst_name, src_ws, src_path, dst_ws, dst_path in conn.execute(
            "SELECT e.src, e.dst, e.attrs, s.name, d.name, s.workspace_id, s.path, d.workspace_id, d.path "
            "FROM edges e JOIN nodes s ON s.id = e.src JOIN nodes d ON d.id = e.dst WHERE e.kind = 'http_calls'"):
        http.append((src, dst, json.loads(attrs) if attrs else {}, src_name, dst_name, src_ws, src_path, dst_ws, dst_path))

    def file_id(workspace, path, node_id):
        key = (workspace, path, node_id)
        if key in file_of:
            return file_of[key]
        if conn.execute("SELECT 1 FROM nodes WHERE id = ? AND kind = 'file'", (node_id,)).fetchone():
            found = node_id
        else:
            row = conn.execute(
                "SELECT id FROM nodes WHERE kind = 'file' AND workspace_id IS ? AND path IS ?",
                (workspace, path),
            ).fetchone()
            found = row[0] if row else None
        file_of[key] = found
        return found

    def between(src_files, dst_files):
        found = []
        seen = set()
        for src, dst, attrs, src_name, dst_name, src_ws, src_path, dst_ws, dst_path in http:
            src_file = file_id(src_ws, src_path, src)
            dst_file = file_id(dst_ws, dst_path, dst)
            if src_file not in src_files or dst_file not in dst_files:
                continue
            key = (attrs.get("method"), attrs.get("path"), src, dst)
            if key in seen:
                continue
            seen.add(key)
            found.append({
                "method": attrs.get("method") or "", "path": attrs.get("path") or "",
                "src": src, "dst": dst, "src_name": src_name, "dst_name": dst_name,
                "id": dst, "name": dst_name,
            })
        found.sort(key=lambda item: (item["method"], item["path"], item["src_name"] or "", item["dst_name"] or ""))
        return found

    for edge in node["outgoing"]:
        if edge["kind"] == "relates":
            eps = between(mine, trees.get(edge["id"], set()))
            if eps:
                edge["endpoints"] = eps
    for edge in node["incoming"]:
        if edge["kind"] == "relates":
            eps = between(trees.get(edge["id"], set()), mine)
            if eps:
                edge["endpoints"] = eps


def show(conn, args):
    floor = _confidence_floor(args)
    if floor is None:
        return 2
    found = _one(conn, args.node, args.json)
    if not found:
        return 1
    node = dict(zip(SHOW_COLUMNS, conn.execute(f"SELECT {', '.join(SHOW_COLUMNS)} FROM nodes WHERE id = ?", (found,)).fetchone()))
    node["attrs"] = json.loads(node["attrs"]) if node["attrs"] else None
    node["children"] = [
        {"id": r[0], "display_kind": r[1], "name": r[2], "start_line": r[3], "end_line": r[4]}
        for r in conn.execute(
            "SELECT id, display_kind, name, start_line, end_line FROM nodes WHERE parent_id = ? "
            "ORDER BY start_line, name", (found,))
    ]
    node["outgoing"] = _edges(conn, found, "src", "dst")
    node["incoming"] = _edges(conn, found, "dst", "src")
    node["tests"] = linked_tests(conn, found)
    node["diagnostics"] = [{"kind": r[0], "detail": r[1]} for r in conn.execute(
        "SELECT kind, detail FROM diagnostics WHERE node_id = ? ORDER BY kind, detail", (found,))]
    if node["kind"] == "concept":
        from cbi import concepts
        node.update(concepts.leaf_detail(conn, found))
    home = _annotate_calls(conn, node)
    from cbi import screens as screen_mod
    appeared = screen_mod.appearances(conn, found)
    if appeared:
        node["screens"] = appeared
    if args.min_confidence is not None or not args.json:
        _apply_floor(node, floor)
    if node["kind"] == "concept":
        _attach_http_endpoints(conn, node)
    if args.json:
        _print_json(node)
        return 0
    limit = None if args.all else SHOW_EDGE_LIMIT
    print(f"{node['name']} ({node['display_kind']})")
    print(f"  id: {node['id']}")
    if node["path"]:
        lines = f":{node['start_line']}-{node['end_line']}" if node["start_line"] else ""
        print(f"  path: {node['path']}{lines}")
    if node["loc"]:
        print(f"  lines of code: {node['loc']}")
    passes_env = any(d["kind"] == "env_passthrough" for d in node["diagnostics"])
    if passes_env:
        print("  passes whole environment")
    if node["kind"] == "env":
        attrs = node["attrs"] or {}
        if attrs.get("passthrough"):
            print("  whole environment")
        if attrs.get("declared_in"):
            print("  declared in: " + ", ".join(attrs["declared_in"]))
        if "example" in attrs:
            print(f"  example: {attrs['example']}")
    if node["summary"] or node["kind"] not in ("symbol", "test", "env", "screen"):  # symbols get no summaries in PRD-01
        print(f"  summary: {node['summary'] or '(none yet)'}")
    attrs = node["attrs"] or {}
    if node["kind"] == "concept" and attrs.get("role"):
        print(f"  role: {attrs['role']}")
    if node["kind"] == "concept" and (place := _concept_place(node)):
        print(place)
    if node["kind"] == "external" and attrs.get("source") == "concepts" and attrs.get("kind"):
        print(f"  kind: {attrs['kind']}")
    if node["kind"] == "screen":
        print(f"  device: {attrs.get('device') or 'desktop'}")
        if attrs.get("ref"):
            print(f"  ref: {attrs['ref']}")
        root = attrs.get("root")
        if isinstance(root, dict):
            print("  regions:")
            for line in screen_mod.region_lines(root):
                print(f"    {line}")
    if node["signature"]:
        print(f"  signature: {node['signature']}")
    if node["display_kind"] == "route" and attrs.get("redirect"):
        print(f"  redirect: {attrs['redirect']}")
    if node["display_kind"] == "route" and attrs.get("guard"):
        print("  guard: " + ", ".join(attrs["guard"]))
    if node["doc"]:
        print("  doc: " + node["doc"].replace("\n", "\n       "))
    if node["children"]:
        print(f"  children ({len(node['children'])}):")
        for c in node["children"]:
            lines = f"  L{c['start_line']}-{c['end_line']}" if c["start_line"] else ""
            print(f"    {c['display_kind']:<12} {c['name']}{lines}")
    for direction in ("outgoing", "incoming"):
        _print_direction(node, direction, home, limit)
    if node.get("env"):
        print("  env:")
        for item in node["env"]:
            default = f"  default {item['default']}" if item.get("default") else ""
            print(f"    {item['name']}{default}")
    if node.get("cross"):
        print("  symbols in other concepts:")
        for item in node["cross"]:
            print(f"    {', '.join(item['verbs']):<16} {item['display_kind']:<12} {item['name']}  ({item['concept_name']})")
    if node.get("screens"):
        print(f"  screens ({len(node['screens'])}):")
        for item in node["screens"]:
            print(f"    {item['name']}  ({item['device']})")
    if node["tests"]:
        print(f"  tests ({len(node['tests'])}):")
        shown = node["tests"] if args.all else node["tests"][:SHOW_TEST_LIMIT]
        for t in shown:
            print("    " + _test_line(t))
        if not args.all and len(node["tests"]) > SHOW_TEST_LIMIT:
            print(f"    ... {len(node['tests']) - SHOW_TEST_LIMIT} more; use --all or see `cbi tests-for`")
    diagnostics = [d for d in node["diagnostics"] if not (passes_env and d["kind"] == "env_passthrough")]
    if diagnostics:
        print(f"  diagnostics ({len(diagnostics)}):")
        for d in diagnostics:
            print(f"    {d['kind']}: {d['detail']}" if d["detail"] else f"    {d['kind']}")
    return 0


# --- status ---------------------------------------------------------------------


def status(conn, args):
    diagnostics = {}
    for kind, count in conn.execute("SELECT kind, count(*) FROM diagnostics GROUP BY kind ORDER BY kind"):
        examples = [{"node_id": r[0], "path": r[1], "detail": r[2]} for r in conn.execute(
            "SELECT d.node_id, n.path, d.detail FROM diagnostics d LEFT JOIN nodes n ON n.id = d.node_id "
            "WHERE d.kind = ? ORDER BY n.path, d.node_id LIMIT ?", (kind, DIAGNOSTIC_EXAMPLES))]
        diagnostics[kind] = {"count": count, "examples": examples}
    result = {
        "scanned_at": store.get_meta(conn, "scanned_at"),
        "nodes": store.counts_by_display_kind(conn),
        "open_tasks": dict(conn.execute(
            "SELECT kind, count(*) FROM tasks WHERE state = 'open' GROUP BY kind ORDER BY kind")),
        "diagnostics": diagnostics,
    }
    if args.json:
        _print_json(result)
        return 0
    print(f"last scan: {result['scanned_at'] or 'never'}")
    print("nodes:")
    for kind, count in result["nodes"].items():
        print(f"  {kind}: {count}")
    print("open tasks:" + ("" if result["open_tasks"] else " none"))
    for kind, count in result["open_tasks"].items():
        print(f"  {kind}: {count}")
    print("diagnostics:" + ("" if diagnostics else " none"))
    for kind, d in diagnostics.items():
        print(f"  {kind}: {d['count']}")
        for e in d["examples"]:
            print(f"    {e['path'] or e['node_id']}" + (f": {e['detail'].splitlines()[0]}" if e["detail"] else ""))
    return 0

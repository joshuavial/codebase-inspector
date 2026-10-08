"""Hotspots, orphans, import cycles and the dependency matrix.

`record_cycles` runs at the end of manifest detection, once package nodes
exist, and replaces `cycle` diagnostics. Cycle and matrix edges are production
imports (both files have role code). Hotspots count every file-to-file import,
including imports from tests, so a file's fan-in matches `cbi show`.
"""

import json
import posixpath
import re
import sys
from collections import defaultdict, deque

HELP = {
    "hotspots": """\
Rank source files, folders, packages and concepts by a graph metric.
Folders, packages and concepts appear when they contain source files.
Concepts are omitted until the model has some. Test files are not ranked
unless --kind asks for them.

--by is fan-in (default), fan-out, loc or symbols. Fan-in and fan-out count
file-to-file imports, including imports from tests. For a folder, package
or concept, fan-in counts imports whose destination is inside and whose
source is outside. loc sums lines of code of the source and test files
inside. symbols counts symbol nodes inside. --kind K keeps one list, matched
on display kind (source file, folder, package, concept) or internal kind.
--limit N is 20 by default.

--json: {by, kind, files, folders, packages, concepts?}, each a list of
{id, kind, display_kind, name, path, fan_in, fan_out, loc, symbols} plus
test_files on folders, packages and concepts. With --kind, {by, kind, nodes}.

Exit codes: 0 done (even with no matches), 1 no model (run `cbi scan`).

Example: cbi hotspots --by fan-in --kind "source file" --limit 20""",
    "orphans": """\
List production code the rest of production does not use, and code no
deployable reaches.

Four lists. Production files with no import, call or literal path reference
from another production file, and not the target of a script tag in an HTML
file (tests do not count as callers); deployable entry points are roots and
are left off this list. A path reference is path.join or path.resolve of
strings, optionally from __dirname, and a compiled name such as preload.js
maps back to preload.ts through the tsconfig outDir. Tool configs (vite,
vitest, jest, eslint, tailwind, postcss, electron-builder) and .d.ts files
are left out. Exported symbols with at least one caller, all of them in
test files. Production files not reachable by imports, path references or
HTML script entries from a resolved deployable entry point; when the model
has none, that list is empty rather than every file. Packages, and
top-level folders that are not themselves a package, that contain source
and no test file. A package or folder with test cases outside it names
that count.

--json: {entries, unreferenced, test_only_symbols, unreachable, untested}.
entries is false when nothing has a resolved entry point. untested items
are {id, kind, name, path, outside_tests}.

Exit codes: 0 done, 1 no model (run `cbi scan`).

Example: cbi orphans --json""",
    "cycles": """\
List import cycles between production files, between their folders and
between their packages. The same cycles are `cycle` diagnostics, one per
node in the cycle, shown by `cbi status` and `cbi show`. A folder cycle is
an import that leaves a folder and comes back. A package cycle follows
part_of. Imports that stay inside one folder or package are not a cycle.

--json: {files, folders, packages}, each a list of {detail, members:
[{id, name, path}]}.

Exit codes: 0 done, 1 no model (run `cbi scan`).

Example: cbi cycles""",
    "deps": """\
Direction-aware dependency matrix. --level is package (default), folder,
concept or deployable. Folder cells are the immediate parent folder of each
file. Package, concept and deployable cells are the node a file belongs to;
a file in none is left out. An edge from a file to another in the same cell
counts as internal coupling. Production imports only, unless --include-tests.

--from and --to keep cells. For a folder they match that folder and
everything under it, so --from src keeps src/mobile. --forbid FROM:TO is the
assertion form: it prints each production import from FROM to TO and exits
1 when any exist. A missing or ambiguous name also exits 1. FROM:TO is
split on the first colon.

--json: {level, tests, nodes, edges: [{from, to, count, files: [{from, to}]}]}.

Exit codes: 0 done, or no forbidden edge, 1 a forbidden edge, an unknown
name, or no model, 2 --forbid is not FROM:TO.

Example: cbi deps --level folder --forbid src:core""",
}

_METRIC = {"fan-in": "fan_in", "fan-out": "fan_out", "loc": "loc", "symbols": "symbols"}
_FILE_CAP = 10
_DETAIL_CAP = 500
_LEFT_OUT = re.compile(
    r"(?:^|/)(?:vite|vitest|jest|eslint|tailwind|postcss)\.config\.[^/]+$"
    r"|(?:^|/)\.eslintrc(?:\.[^/]+)?$"
    r"|(?:^|/)electron-builder(?:\.config)?\.[^/]+$"
)


def _left_out(path):
    """Tool configs and TypeScript declaration files are not production code."""
    return path.endswith(".d.ts") or bool(_LEFT_OUT.search(path))


def _print_json(value):
    print(json.dumps(value, indent=2))


def _files(conn):
    return [
        {"id": r[0], "wid": r[1], "path": r[2] or "", "role": r[3], "loc": r[4] or 0, "name": r[5]}
        for r in conn.execute(
            "SELECT id, workspace_id, path, json_extract(attrs, '$.role'), loc, name FROM nodes WHERE kind = 'file'")
    ]


def _imports(conn, file_ids):
    return [(s, d) for s, d in conn.execute("SELECT src, dst FROM edges WHERE kind = 'imports'")
            if s in file_ids and d in file_ids]


def _under(path, root):
    return bool(root) and (path == root or path.startswith(root + "/"))


def _ws_names(conn):
    names = dict(conn.execute("SELECT id, name FROM nodes WHERE kind = 'workspace'"))
    return names, len(names) > 1


def _label(text, wid, names, multi):
    if multi and wid in names:
        return f"{names[wid]}:{text}"
    return text


def _symbol_counts(conn):
    counts = defaultdict(int)
    for (sid,) in conn.execute("SELECT id FROM nodes WHERE kind = 'symbol'"):
        counts[sid.split("#", 1)[0]] += 1
    return counts


def _file_of(nid, file_ids):
    if nid in file_ids:
        return nid
    base = nid.split("#", 1)[0]
    return base if base in file_ids else None


# --- hotspots -------------------------------------------------------------------


def _metrics(member_ids, imports, by_id, symbols):
    inside = set(member_ids)
    fan_in = fan_out = loc = symbol_n = test_files = code = 0
    for src, dst in imports:
        if dst in inside and src not in inside:
            fan_in += 1
        if src in inside and dst not in inside:
            fan_out += 1
    for fid in inside:
        found = by_id.get(fid)
        if not found:
            continue
        if found["role"] in ("code", "test"):
            loc += found["loc"]
        symbol_n += symbols[fid]
        test_files += found["role"] == "test"
        code += found["role"] == "code"
    return {"fan_in": fan_in, "fan_out": fan_out, "loc": loc, "symbols": symbol_n,
            "test_files": test_files, "code": code}


def _row(node, metrics, label, container):
    row = {"id": node["id"], "kind": node["kind"], "display_kind": node["display_kind"],
           "name": node["name"], "path": node["path"], "label": label, **metrics}
    if not container:
        row.pop("test_files", None)
        row.pop("code", None)
    return row


def _containers(conn, files, imports, symbols, names, multi):
    by_id = {f["id"]: f for f in files}
    groups, packages, concepts = [], [], []
    for nid, wid, path, name, display in conn.execute(
            "SELECT id, workspace_id, path, name, display_kind FROM nodes WHERE kind = 'group'"):
        member = [f["id"] for f in files if f["wid"] == wid and _under(f["path"], path or "")]
        metrics = _metrics(member, imports, by_id, symbols)
        if not metrics["code"]:
            continue
        groups.append(_row({"id": nid, "kind": "group", "display_kind": display, "name": name, "path": path or ""},
                           metrics, _label(path or name, wid, names, multi), True))
    owns = defaultdict(set)
    for src, dst in conn.execute("SELECT src, dst FROM edges WHERE kind = 'owns'"):
        if dst in by_id:
            owns[src].add(dst)
    for nid, wid, path, name in conn.execute(
            "SELECT id, workspace_id, path, name FROM nodes WHERE kind = 'concept'"):
        metrics = _metrics(owns.get(nid, ()), imports, by_id, symbols)
        if not metrics["code"]:
            continue
        concepts.append(_row({"id": nid, "kind": "concept", "display_kind": "concept", "name": name, "path": path},
                             metrics, _label(name, wid, names, multi), True))
    part_of = defaultdict(set)
    for src, dst in conn.execute(
            "SELECT e.src, e.dst FROM edges e JOIN nodes n ON n.id = e.dst "
            "WHERE e.kind = 'part_of' AND n.kind = 'package'"):
        if src in by_id:
            part_of[dst].add(src)
    for nid, wid, path, name in conn.execute(
            "SELECT id, workspace_id, path, name FROM nodes WHERE kind = 'package'"):
        metrics = _metrics(part_of.get(nid, ()), imports, by_id, symbols)
        if not metrics["code"]:
            continue
        packages.append(_row({"id": nid, "kind": "package", "display_kind": "package", "name": name, "path": path},
                             metrics, _label(name, wid, names, multi), True))
    source = []
    for found in files:
        if found["role"] != "code":
            continue
        fan_in = sum(1 for src, dst in imports if dst == found["id"])
        fan_out = sum(1 for src, dst in imports if src == found["id"])
        source.append(_row(
            {"id": found["id"], "kind": "file", "display_kind": "source file", "name": found["name"], "path": found["path"]},
            {"fan_in": fan_in, "fan_out": fan_out, "loc": found["loc"], "symbols": symbols[found["id"]]},
            _label(found["path"], found["wid"], names, multi), False))
    return source, groups, packages, concepts


def _ordered(rows, by, limit):
    key = _METRIC[by]
    rows = sorted(rows, key=lambda r: (-r[key], r["path"] or "", r["id"]))
    return rows[:limit] if limit >= 0 else []


def _public(row):
    kept = ("id", "kind", "display_kind", "name", "path", "fan_in", "fan_out", "loc", "symbols")
    out = {k: row[k] for k in kept}
    if "test_files" in row:
        out["test_files"] = row["test_files"]
    return out


def _print_rows(title, rows):
    print(f"{title}:")
    if not rows:
        print("  none")
        return
    for row in rows:
        bits = [f"fan-in {row['fan_in']}", f"fan-out {row['fan_out']}", f"loc {row['loc']}", f"symbols {row['symbols']}"]
        if "test_files" in row:
            bits.append(f"test files {row['test_files']}")
        print(f"  {row['label']}  " + "  ".join(bits))


def hotspots(conn, args):
    limit = args.limit if args.limit is not None else 20
    files = _files(conn)
    names, multi = _ws_names(conn)
    source, groups, packages, concepts = _containers(
        conn, files, _imports(conn, {f["id"] for f in files}), _symbol_counts(conn), names, multi)
    if args.kind:
        pool = [r for r in (*source, *groups, *packages, *concepts)
                if r["display_kind"] == args.kind or r["kind"] == args.kind]
        pool = _ordered(pool, args.by, limit)
        if args.json:
            _print_json({"by": args.by, "kind": args.kind, "nodes": [_public(r) for r in pool]})
            return 0
        if not pool:
            print(f"no nodes of kind {args.kind!r}")
            return 0
        _print_rows(f"by {args.by}", pool)
        return 0
    sections = (("files", source), ("folders", groups), ("packages", packages))
    if concepts:
        sections = (*sections, ("concepts", concepts))
    shown = [(title, _ordered(rows, args.by, limit)) for title, rows in sections]
    if args.json:
        body = {"by": args.by, "kind": None}
        for title, rows in shown:
            body[title] = [_public(r) for r in rows]
        _print_json(body)
        return 0
    for title, rows in shown:
        _print_rows(f"{title} by {args.by}", rows)
    return 0


# --- orphans --------------------------------------------------------------------


def _entries(conn, file_ids):
    found = []
    for wid, attrs in conn.execute("SELECT workspace_id, attrs FROM nodes WHERE kind = 'deployable'"):
        for path in json.loads(attrs or "{}").get("entry_points") or []:
            fid = f"{wid}:{path}"
            if fid in file_ids:
                found.append(fid)
    return found


def orphans(conn, args):
    files = _files(conn)
    by_id = {f["id"]: f for f in files}
    code = [f for f in files if f["role"] == "code"]
    code_ids = {f["id"] for f in code}
    imports = _imports(conn, set(by_id))
    referenced = set()
    for src, dst in imports:
        if src in code_ids and dst in code_ids and src != dst:
            referenced.add(dst)
    for src, dst in conn.execute("SELECT src, dst FROM edges WHERE kind = 'calls'"):
        src_file, dst_file = _file_of(src, by_id), _file_of(dst, by_id)
        if src_file and dst_file and src_file != dst_file and src_file in code_ids and dst_file in code_ids:
            referenced.add(dst_file)
    ref_edges = list(conn.execute("SELECT src, dst FROM edges WHERE kind = 'references'"))
    for src, dst in ref_edges:
        if dst in code_ids and src != dst:
            referenced.add(dst)
    entries = _entries(conn, by_id)
    entry_ids = set(entries)
    unreferenced = [f for f in code if f["id"] not in referenced and f["id"] not in entry_ids
                    and not _left_out(f["path"])]

    callers = defaultdict(set)
    for src, dst in conn.execute("SELECT src, dst FROM edges WHERE kind = 'calls'"):
        src_file = _file_of(src, by_id)
        if src_file:
            callers[dst].add(src_file)
    exported = defaultdict(set)
    for fid, data in conn.execute("SELECT file_id, data FROM facts"):
        for name in (json.loads(data).get("exports") or {}).values():
            if isinstance(name, str):
                exported[fid].add(name)
    test_only = []
    for nid, name, path, wid in conn.execute(
            "SELECT id, name, path, workspace_id FROM nodes WHERE kind = 'symbol'"):
        fid = f"{wid}:{path}" if path else None
        if not path or _left_out(path) or fid not in code_ids or name not in exported[fid]:
            continue
        found = callers.get(nid)
        if found and all(c in by_id and by_id[c]["role"] == "test" for c in found):
            test_only.append({"id": nid, "name": name, "path": path})

    reached = set()
    imports_from = defaultdict(set)
    for src, dst in imports:
        imports_from[src].add(dst)
    html_roots = []
    for src, dst in ref_edges:
        if src in by_id and dst in by_id:
            imports_from[src].add(dst)
        if src not in code_ids and dst in code_ids:
            html_roots.append(dst)
    stack = list(entry_ids) + (html_roots if entry_ids else [])
    while stack:
        fid = stack.pop()
        if fid in reached:
            continue
        reached.add(fid)
        stack.extend(imports_from[fid] - reached)
    unreachable = [] if not entry_ids else [f for f in code if f["id"] not in reached and not _left_out(f["path"])]

    package_dirs = {}
    packages = []
    for nid, wid, path, name in conn.execute(
            "SELECT id, workspace_id, path, name FROM nodes WHERE kind = 'package'"):
        directory = path or ""
        if directory:
            package_dirs[(wid, directory)] = nid
        member = [f for f in files if f["wid"] == wid and _under(f["path"], directory)]
        if _has_production(member):
            packages.append({"id": nid, "kind": "package", "name": name, "path": directory, "wid": wid,
                             "members": {f["id"] for f in member}})
    folders = []
    for nid, wid, path, name in conn.execute(
            "SELECT id, workspace_id, path, name FROM nodes WHERE kind = 'group' AND instr(path, '/') = 0"):
        if not path or (wid, path) in package_dirs:
            continue
        member = [f for f in files if f["wid"] == wid and _under(f["path"], path)]
        if _has_production(member):
            folders.append({"id": nid, "kind": "group", "name": name, "path": path, "wid": wid,
                            "members": {f["id"] for f in member}})
    untested = sorted(packages + folders, key=lambda n: (n["path"], n["id"]))
    cases = {}
    for nid, path, wid in conn.execute(
            "SELECT id, path, workspace_id FROM nodes WHERE kind = 'test' AND display_kind = 'test case'"):
        if path:
            cases[nid] = f"{wid}:{path}"
    outside = defaultdict(set)
    for src, dst in conn.execute("SELECT src, dst FROM edges WHERE kind = 'tests'"):
        case_file = cases.get(src)
        dst_file = _file_of(dst, by_id)
        if not case_file or not dst_file:
            continue
        for node in untested:
            if dst_file in node["members"] and case_file not in node["members"]:
                outside[node["id"]].add(src)

    def listed(rows):
        return [{"id": r["id"], "path": r["path"]} for r in sorted(rows, key=lambda r: (r["path"], r["id"]))]

    body = {
        "entries": bool(entry_ids),
        "unreferenced": listed(unreferenced),
        "test_only_symbols": sorted(test_only, key=lambda r: (r["path"] or "", r["name"], r["id"])),
        "unreachable": listed(unreachable),
        "untested": [{"id": n["id"], "kind": n["kind"], "name": n["name"], "path": n["path"],
                      "outside_tests": len(outside[n["id"]])} for n in untested],
    }
    if args.json:
        _print_json(body)
        return 0
    _print_orphan("production code with no production importer or caller", [r["path"] for r in body["unreferenced"]])
    _print_orphan("exported symbols with only test callers",
                  [f"{r['path']}#{r['name']}" for r in body["test_only_symbols"]])
    if body["entries"]:
        _print_orphan("files reachable from no deployable entry point", [r["path"] for r in body["unreachable"]])
    else:
        print("files reachable from no deployable entry point:")
        print("  no deployable entry points")
    print("no test files of their own:")
    if not body["untested"]:
        print("  none")
    for node in body["untested"]:
        extra = f", {node['outside_tests']} test cases outside" if node["outside_tests"] else ""
        print(f"  {node['path'] or node['name']}  0 test files{extra}")
    return 0


def _has_production(member):
    """Source files other than tool configs and declaration files, and no test file."""
    return (any(f["role"] == "code" and not _left_out(f["path"]) for f in member)
            and not any(f["role"] == "test" for f in member))


def _print_orphan(title, rows):
    print(f"{title}:")
    if not rows:
        print("  none")
        return
    for row in rows:
        print(f"  {row}")


# --- cycles ---------------------------------------------------------------------


def _sccs(nodes, graph):
    """Strongly connected components of graph, iterative Kosaraju. graph maps a node to its successors."""
    node_set = set(nodes)
    succ = {n: [d for d in graph.get(n, ()) if d in node_set] for n in node_set}
    seen, order = set(), []
    for start in nodes:
        if start in seen:
            continue
        stack = [(start, False)]
        while stack:
            node, done = stack.pop()
            if done:
                order.append(node)
                continue
            if node in seen:
                continue
            seen.add(node)
            stack.append((node, True))
            for nxt in succ[node]:
                if nxt not in seen:
                    stack.append((nxt, False))
    pred = defaultdict(list)
    for src, dsts in succ.items():
        for dst in dsts:
            pred[dst].append(src)
    seen, comps = set(), []
    for start in reversed(order):
        if start in seen:
            continue
        stack = [start]
        seen.add(start)
        comp = []
        while stack:
            node = stack.pop()
            comp.append(node)
            for nxt in pred.get(node, ()):
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        comps.append(comp)
    return comps, succ


def _is_cycle(comp, succ):
    if len(comp) > 1:
        return True
    node = comp[0]
    return node in succ.get(node, ())


def _cycle_detail(comp, succ, label):
    start = min(comp, key=lambda n: (label(n), str(n)))
    if len(comp) == 1:
        text = f"{label(start)} → {label(start)}"
        return text[:_DETAIL_CAP]
    member = set(comp)
    prev = {start: None}
    queue = deque([start])
    found = None
    while queue and found is None:
        node = queue.popleft()
        for nxt in sorted(succ.get(node, ()), key=lambda n: (label(n), str(n))):
            if nxt not in member:
                continue
            if nxt == start and node != start:
                found = node
                break
            if nxt not in prev:
                prev[nxt] = node
                queue.append(nxt)
    if found is None:
        text = " → ".join(label(n) for n in sorted(comp, key=lambda n: (label(n), str(n))))
        return text[:_DETAIL_CAP]
    chain = []
    node = found
    while node is not None:
        chain.append(node)
        node = prev[node]
    chain.reverse()
    text = " → ".join(label(n) for n in chain) + f" → {label(start)}"
    return text[:_DETAIL_CAP]


def _components(nodes, graph, label, describe):
    comps, succ = _sccs(nodes, graph)
    found = []
    for comp in comps:
        if not _is_cycle(comp, succ):
            continue
        detail = _cycle_detail(comp, succ, label)
        found.append({"detail": detail, "members": [describe(n) for n in sorted(comp, key=lambda n: (label(n), str(n)))]})
    found.sort(key=lambda c: c["detail"])
    return found


def collect_cycles(conn):
    """Import cycles among production files, their immediate folders and their packages."""
    files = _files(conn)
    by_id = {f["id"]: f for f in files}
    names, multi = _ws_names(conn)
    code = {f["id"]: f for f in files if f["role"] == "code"}
    graph = defaultdict(set)
    for src, dst in _imports(conn, set(by_id)):
        if src in code and dst in code:
            graph[src].add(dst)
    file_cycles = _components(
        list(code), graph,
        lambda n: _label(code[n]["path"], code[n]["wid"], names, multi),
        lambda n: {"id": n, "name": code[n]["name"], "path": code[n]["path"]},
    )

    groups = {(wid, path): {"id": nid, "name": name, "path": path or "", "wid": wid}
              for nid, wid, path, name in conn.execute(
                  "SELECT id, workspace_id, path, name FROM nodes WHERE kind = 'group'")}
    parent = {}
    for fid, found in code.items():
        directory = posixpath.dirname(found["path"])
        group = groups.get((found["wid"], directory))
        if group:
            parent[fid] = group["id"]
    by_group = {g["id"]: g for g in groups.values()}
    folder_graph = defaultdict(set)
    for src, dsts in graph.items():
        src_group = parent.get(src)
        for dst in dsts:
            dst_group = parent.get(dst)
            if src_group and dst_group and src_group != dst_group:
                folder_graph[src_group].add(dst_group)
    folder_cycles = _components(
        list(by_group), folder_graph,
        lambda n: _label(by_group[n]["path"], by_group[n]["wid"], names, multi),
        lambda n: {"id": n, "name": by_group[n]["name"], "path": by_group[n]["path"]},
    )

    packages = {nid: {"id": nid, "name": name, "path": path, "wid": wid}
                for nid, wid, path, name in conn.execute(
                    "SELECT id, workspace_id, path, name FROM nodes WHERE kind = 'package'")}
    file_pkg = {}
    for src, dst in conn.execute(
            "SELECT src, dst FROM edges WHERE kind = 'part_of' AND dst IN (SELECT id FROM nodes WHERE kind = 'package')"):
        if src in code:
            file_pkg[src] = dst
    package_graph = defaultdict(set)
    for src, dsts in graph.items():
        src_pkg = file_pkg.get(src)
        for dst in dsts:
            dst_pkg = file_pkg.get(dst)
            if src_pkg and dst_pkg and src_pkg != dst_pkg:
                package_graph[src_pkg].add(dst_pkg)
    package_cycles = _components(
        list(packages), package_graph,
        lambda n: _label(packages[n]["name"], packages[n]["wid"], names, multi),
        lambda n: {"id": n, "name": packages[n]["name"], "path": packages[n]["path"]},
    )
    return {"files": file_cycles, "folders": folder_cycles, "packages": package_cycles}


def record_cycles(conn):
    """Replace cycle diagnostics with one row per node in a file, folder or package cycle."""
    found = collect_cycles(conn)
    conn.execute("DELETE FROM diagnostics WHERE kind = 'cycle'")
    rows = [(member["id"], comp["detail"]) for comps in found.values() for comp in comps for member in comp["members"]]
    conn.executemany("INSERT INTO diagnostics (node_id, kind, detail) VALUES (?, 'cycle', ?)", rows)


def cycles(conn, args):
    found = collect_cycles(conn)
    if args.json:
        _print_json(found)
        return 0
    for key in ("files", "folders", "packages"):
        comps = found[key]
        if not comps:
            print(f"{key}: none")
            continue
        print(f"{key}:")
        for comp in comps:
            print(f"  {comp['detail']}")
    return 0


# --- deps -----------------------------------------------------------------------


def _level_nodes(conn, level):
    if level == "folder":
        kind = "group"
    else:
        kind = level
    nodes = []
    for nid, wid, path, name, display in conn.execute(
            "SELECT id, workspace_id, path, name, display_kind FROM nodes WHERE kind = ?", (kind,)):
        nodes.append({"id": nid, "wid": wid, "path": path or "", "name": name, "kind": kind, "display_kind": display})
    return nodes


def _find_endpoint(nodes, level, text):
    text = text.strip("/")
    if level == "folder":
        hits = [n for n in nodes if n["path"] == text]
    else:
        hits = [n for n in nodes if n["name"] == text or (n["path"] and n["path"] == text)]
    if not hits:
        return None, f"no {level} {text!r}"
    if len(hits) > 1:
        return None, f"{level} {text!r} matches {len(hits)} nodes: " + ", ".join(n["id"] for n in hits)
    return hits[0], None


def _members(files, level, node, file_pkg, file_deps, owns):
    if level == "folder":
        return {f["id"] for f in files if f["wid"] == node["wid"] and _under(f["path"], node["path"])}
    if level == "package":
        return {fid for fid, pid in file_pkg.items() if pid == node["id"]}
    if level == "deployable":
        return {fid for fid, dids in file_deps.items() if node["id"] in dids}
    return {fid for fid, cid in owns.items() if cid == node["id"]}


def _containers_of(found, level, file_pkg, file_deps, owns, packages, concepts, deployables):
    if level == "folder":
        directory = posixpath.dirname(found["path"])
        if not directory:
            return []
        return [{"key": (found["wid"], directory), "label": directory, "path": directory}]
    if level == "package":
        pid = file_pkg.get(found["id"])
        if not pid or pid not in packages:
            return []
        node = packages[pid]
        return [{"key": pid, "label": node["name"], "path": node["path"]}]
    if level == "concept":
        cid = owns.get(found["id"])
        if not cid or cid not in concepts:
            return []
        node = concepts[cid]
        return [{"key": cid, "label": node["name"], "path": node["path"]}]
    return [{"key": did, "label": deployables[did]["name"], "path": deployables[did]["path"]}
            for did in file_deps.get(found["id"], ()) if did in deployables]


def _cell_matches(cell, end, which, level):
    if end is None:
        return True
    if level == "folder":
        return _under(cell[which + "_path"], end["path"])
    return cell[which] == end["name"] or (end["path"] and cell[which + "_path"] == end["path"])


def deps(conn, args):
    level = args.level
    nodes = _level_nodes(conn, level)
    if not nodes:
        print(f"no {level}s in the model")
        return 1 if args.forbid else 0
    files = _files(conn)
    by_id = {f["id"]: f for f in files}
    imports = _imports(conn, set(by_id))
    if not args.include_tests:
        imports = [(s, d) for s, d in imports if by_id[s]["role"] == "code" and by_id[d]["role"] == "code"]
    packages, deployables, concepts = {}, {}, {}
    file_pkg, file_deps = {}, defaultdict(set)
    owns = {}
    for nid, wid, path, name in conn.execute("SELECT id, workspace_id, path, name FROM nodes WHERE kind = 'package'"):
        packages[nid] = {"id": nid, "name": name, "path": path or "", "wid": wid}
    for nid, wid, path, name in conn.execute("SELECT id, workspace_id, path, name FROM nodes WHERE kind = 'deployable'"):
        deployables[nid] = {"id": nid, "name": name, "path": path or "", "wid": wid}
    for nid, wid, path, name in conn.execute("SELECT id, workspace_id, path, name FROM nodes WHERE kind = 'concept'"):
        concepts[nid] = {"id": nid, "name": name, "path": path or "", "wid": wid}
    for src, dst, kind in conn.execute(
            "SELECT e.src, e.dst, n.kind FROM edges e JOIN nodes n ON n.id = e.dst WHERE e.kind = 'part_of'"):
        if src not in by_id:
            continue
        if kind == "package":
            file_pkg[src] = dst
        elif kind == "deployable":
            file_deps[src].add(dst)
    for src, dst in conn.execute(
            "SELECT e.src, e.dst FROM edges e JOIN nodes n ON n.id = e.src "
            "WHERE e.kind = 'owns' AND n.kind = 'concept'"):
        if dst in by_id:
            owns[dst] = src

    if not args.forbid:
        cells = {}
        for src, dst in imports:
            sources = _containers_of(by_id[src], level, file_pkg, file_deps, owns, packages, concepts, deployables)
            dests = _containers_of(by_id[dst], level, file_pkg, file_deps, owns, packages, concepts, deployables)
            for source in sources:
                for dest in dests:
                    cell = cells.setdefault((source["key"], dest["key"]), {
                        "from": source["label"], "to": dest["label"],
                        "from_path": source["path"], "to_path": dest["path"], "files": []})
                    cell["files"].append({"from": by_id[src]["path"], "to": by_id[dst]["path"]})
        start = end = None
        for text, slot in ((args.start, "start"), (args.end, "end")):
            if not text:
                continue
            found, err = _find_endpoint(nodes, level, text)
            if err:
                print(err, file=sys.stderr)
                return 1
            if slot == "start":
                start = found
            else:
                end = found
        kept = [c for c in cells.values() if _cell_matches(c, start, "from", level) and _cell_matches(c, end, "to", level)]
        for cell in kept:
            cell["files"].sort(key=lambda f: (f["from"], f["to"]))
        kept.sort(key=lambda c: (c["from"], c["to"]))
        labels = sorted({c["label"] for fid, found in by_id.items()
                         for c in _containers_of(found, level, file_pkg, file_deps, owns, packages, concepts, deployables)})
        edges = [{"from": c["from"], "to": c["to"], "count": len(c["files"]), "files": c["files"]} for c in kept]
        if args.json:
            _print_json({"level": level, "tests": bool(args.include_tests), "nodes": labels, "edges": edges})
            return 0
        if not edges:
            print(f"no {level} dependencies")
            return 0
        for cell in kept:
            print(f"{cell['from']} → {cell['to']}  {len(cell['files'])}")
            for item in cell["files"][:_FILE_CAP]:
                print(f"  {item['from']} → {item['to']}")
            extra = len(cell["files"]) - _FILE_CAP
            if extra > 0:
                print(f"  ... {extra} more; use --json")
        return 0

    failed = False
    word = "imports" if args.include_tests else "production imports"
    for spec in args.forbid:
        if ":" not in spec:
            print("error: --forbid expects FROM:TO", file=sys.stderr)
            return 2
        src_text, dst_text = spec.split(":", 1)
        if not src_text or not dst_text:
            print("error: --forbid expects FROM:TO", file=sys.stderr)
            return 2
        src_node, src_err = _find_endpoint(nodes, level, src_text)
        dst_node, dst_err = _find_endpoint(nodes, level, dst_text)
        if src_err or dst_err:
            if src_err:
                print(src_err, file=sys.stderr)
            if dst_err:
                print(dst_err, file=sys.stderr)
            failed = True
            continue
        src_ids = _members(files, level, src_node, file_pkg, file_deps, owns)
        dst_ids = _members(files, level, dst_node, file_pkg, file_deps, owns)
        offending = sorted(((by_id[s]["path"], by_id[d]["path"]) for s, d in imports if s in src_ids and d in dst_ids),
                           key=lambda pair: pair)
        if not offending:
            print(f"no {word} from {src_text.strip('/')} to {dst_text.strip('/')}")
            continue
        failed = True
        for src_path, dst_path in offending:
            print(f"{src_path} → {dst_path}")
    return 1 if failed else 0

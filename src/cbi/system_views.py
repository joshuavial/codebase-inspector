"""Layout-free database and endpoint projections for the static viewer."""

import hashlib
import json
from collections import defaultdict, deque


def _attrs(text):
    try:
        value = json.loads(text or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _nodes(conn):
    fields = ("id", "parent_id", "kind", "display_kind", "name", "workspace_id", "path",
              "start_line", "end_line", "doc", "summary", "attrs")
    return {
        row[0]: {key: value for key, value in zip(fields, row)} | {"attrs": _attrs(row[-1])}
        for row in conn.execute(f"SELECT {', '.join(fields)} FROM nodes")
    }


def _file_id(nodes, node):
    if not node:
        return None
    if node["kind"] in ("file", "doc"):
        return node["id"]
    for candidate in nodes.values():
        if candidate["kind"] == "file" and candidate["workspace_id"] == node["workspace_id"] \
                and candidate["path"] == node["path"]:
            return candidate["id"]
    return None


def _owners(conn):
    return {dst: src for src, dst in conn.execute("SELECT src, dst FROM edges WHERE kind = 'owns'")}


def _code_ref(nodes, owners, node_id):
    node = nodes.get(node_id)
    if not node:
        return None
    file_id = _file_id(nodes, node)
    return {
        "id": node["id"], "name": node["name"], "kind": node["display_kind"],
        "file": node["path"] or "", "line": node["start_line"] or 1,
        "concept": owners.get(file_id),
    }


def database_view(conn):
    """Tables, columns, foreign keys and code uses, with no layout fields."""
    nodes = _nodes(conn)
    owners = _owners(conn)
    tables = {}
    for node in nodes.values():
        if node["kind"] != "table":
            continue
        tables[node["id"]] = {
            "id": node["id"], "name": node["name"], "sources": node["attrs"].get("sources", []),
            "models": node["attrs"].get("models", []), "columns": [], "reads": [], "writes": [],
            "foreignKeys": [], "referencedBy": [],
        }
    for node in nodes.values():
        if node["kind"] != "column" or node["parent_id"] not in tables:
            continue
        attrs = node["attrs"]
        tables[node["parent_id"]]["columns"].append({
            "id": node["id"], "name": node["name"], "type": attrs.get("type") or "",
            "nullable": bool(attrs.get("nullable", True)), "default": attrs.get("default"),
            "primaryKey": bool(attrs.get("primary_key")), "unique": bool(attrs.get("unique")),
            "sources": attrs.get("sources", []),
        })
    relationships = []
    for src, dst, attrs in conn.execute(
            "SELECT src, dst, attrs FROM edges WHERE kind = 'foreign_key' ORDER BY src, dst, ordinal"):
        local, target = nodes.get(src), nodes.get(dst)
        if not local or not target or local["parent_id"] not in tables or target["parent_id"] not in tables:
            continue
        item = {"from": local["parent_id"], "column": src, "to": target["parent_id"],
                "targetColumn": dst, "source": _attrs(attrs).get("source")}
        relationships.append(item)
        tables[local["parent_id"]]["foreignKeys"].append(item)
        tables[target["parent_id"]]["referencedBy"].append(item)
    for src, dst, kind, weight, attrs in conn.execute(
            "SELECT src, dst, kind, weight, attrs FROM edges "
            "WHERE kind IN ('reads_table', 'writes_table') ORDER BY dst, kind, src"):
        if dst not in tables:
            continue
        ref = _code_ref(nodes, owners, src)
        if not ref:
            continue
        ref["weight"] = weight
        ref["locations"] = _attrs(attrs).get("locations", [])
        tables[dst]["reads" if kind == "reads_table" else "writes"].append(ref)
    for table in tables.values():
        table["columns"].sort(key=lambda row: (not row["primaryKey"], row["name"].lower()))
        for key in ("reads", "writes"):
            table[key].sort(key=lambda row: (row["file"], row["line"], row["name"], row["id"]))
        table["foreignKeys"].sort(key=lambda row: (row["column"], row["targetColumn"]))
        table["referencedBy"].sort(key=lambda row: (row["from"], row["column"]))
    return {"tables": sorted(tables.values(), key=lambda row: (row["name"].lower(), row["id"])),
            "relationships": relationships}


def _sentence(text, limit=180):
    text = " ".join((text or "").split())
    if not text:
        return ""
    for mark in (". ", "! ", "? "):
        if mark in text:
            text = text.split(mark, 1)[0] + mark[0]
            break
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def _endpoint_id(handler, method, path):
    digest = hashlib.sha1(f"{handler}\0{method}\0{path}".encode()).hexdigest()[:12]
    return "endpoint:" + digest


def _reachable(handler, calls, limit=4):
    depth = {handler: 0}
    queue = deque([handler])
    while queue:
        src = queue.popleft()
        if depth[src] >= limit:
            continue
        for dst in calls.get(src, ()):
            if dst not in depth:
                depth[dst] = depth[src] + 1
                queue.append(dst)
    return depth


def endpoint_view(conn):
    """Every detected HTTP route with callers, downstream code and tables."""
    nodes = _nodes(conn)
    owners = _owners(conn)
    calls = defaultdict(set)
    imports = defaultdict(set)
    uses = defaultdict(list)
    http_edges = []
    for src, dst, kind, attrs in conn.execute(
            "SELECT src, dst, kind, attrs FROM edges "
            "WHERE kind IN ('calls', 'imports', 'http_calls', 'reads_table', 'writes_table')"):
        if kind == "calls":
            calls[src].add(dst)
        elif kind == "imports":
            imports[src].add(dst)
        elif kind == "http_calls":
            http_edges.append((src, dst, _attrs(attrs)))
        else:
            uses[src].append((dst, "read" if kind == "reads_table" else "write"))

    endpoints = []
    for handler in nodes.values():
        routes = handler["attrs"].get("http_routes")
        if not isinstance(routes, list):
            continue
        handler_ref = _code_ref(nodes, owners, handler["id"])
        file_id = _file_id(nodes, handler)
        file_node = nodes.get(file_id)
        for route in routes:
            method, path = str(route.get("method") or "").upper(), str(route.get("path") or "")
            if not method or not path:
                continue
            caller_refs = []
            for src, dst, attrs in http_edges:
                if dst != handler["id"] or attrs.get("method") != method or attrs.get("path") != path:
                    continue
                ref = _code_ref(nodes, owners, src)
                if ref and ref not in caller_refs:
                    caller_refs.append(ref)
            reach = _reachable(handler["id"], calls)
            code = []
            for node_id, depth in sorted(reach.items(), key=lambda row: (row[1], row[0])):
                if node_id == handler["id"]:
                    continue
                ref = _code_ref(nodes, owners, node_id)
                if ref:
                    ref["via"], ref["depth"] = "call", depth
                    code.append(ref)
            if file_id:
                for target in sorted(imports.get(file_id, ())):
                    if target in reach:
                        continue
                    ref = _code_ref(nodes, owners, target)
                    if ref:
                        ref["via"], ref["depth"] = "import", 1
                        code.append(ref)
            table_rows = {}
            for node_id, depth in reach.items():
                for table_id, mode in uses.get(node_id, ()):
                    table = nodes.get(table_id)
                    if not table:
                        continue
                    key = (table_id, mode)
                    prev = table_rows.get(key)
                    item = {"id": table_id, "name": table["name"], "mode": mode,
                            "direct": depth == 0, "via": node_id, "depth": depth}
                    if prev is None or depth < prev["depth"]:
                        table_rows[key] = item
            summary = _sentence(handler.get("summary")) or _sentence(handler.get("doc"))
            summary = summary or _sentence(file_node.get("summary") if file_node else "")
            summary = summary or f"Handled by {handler['name']}."
            endpoints.append({
                "id": _endpoint_id(handler["id"], method, path), "method": method, "path": path,
                "note": summary, "handler": handler_ref, "callers": sorted(
                    caller_refs, key=lambda row: (row["file"], row["line"], row["name"])),
                "code": sorted(code, key=lambda row: (row["depth"], row["file"], row["line"], row["id"])),
                "tables": sorted(table_rows.values(), key=lambda row: (row["name"].lower(), row["mode"])),
            })
    endpoints.sort(key=lambda row: (row["path"], row["method"], row["id"]))
    return {"endpoints": endpoints}

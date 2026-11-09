"""Layout-free database and endpoint projections for the static viewer."""

import hashlib
import json
import re
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


HELP = {
    "endpoints": """\
List HTTP route endpoints detected in the codebase model with their handlers,
caller references, downstream code calls, and database tables.

Filter by path substring (--path), HTTP method (--method), handler name or
file (--handler), or table read/written (--table).
Use --format (text, json, markdown) or --json for structured output.

Exit codes: 0 done, 1 no model (run `cbi init` and `cbi scan`).

Example:
  cbi endpoints --method GET
  cbi endpoints --format markdown
  cbi endpoints --path /api/accounts --json
  cbi endpoints --table accounts""",
    "tables": """\
List database tables, columns, primary and foreign keys, and code references
(reads and writes) detected in the codebase model.

Filter by table name or id substring (--table).
Use --format (text, json, markdown, mermaid) or --json for structured output.

Exit codes: 0 done, 1 no model (run `cbi init` and `cbi scan`).

Example:
  cbi tables
  cbi tables --format markdown
  cbi tables --format mermaid
  cbi tables --table accounts
  cbi tables --json""",
}


def filter_endpoints(endpoints, path=None, method=None, handler=None, table=None):
    """Filter a list of endpoint dicts by path, method, handler, or table."""
    result = []
    path_term = path.lower() if path else None
    method_term = method.upper() if method else None
    handler_term = handler.lower() if handler else None
    table_term = table.lower() if table else None

    for ep in endpoints:
        if path_term and path_term not in ep.get("path", "").lower():
            continue
        if method_term and method_term != ep.get("method", "").upper():
            continue
        if handler_term:
            h = ep.get("handler") or {}
            h_name = (h.get("name") or "").lower()
            h_file = (h.get("file") or "").lower()
            h_id = (h.get("id") or "").lower()
            if handler_term not in h_name and handler_term not in h_file and handler_term not in h_id:
                continue
        if table_term:
            tables = ep.get("tables") or []
            if not any(
                table_term in (t.get("name") or "").lower() or table_term in (t.get("id") or "").lower()
                for t in tables
            ):
                continue
        result.append(ep)
    return result


def filter_tables(tables, relationships=None, table=None):
    """Filter tables and relationships by table name or id substring."""
    if not table:
        return list(tables), list(relationships or [])
    table_term = table.lower()
    matched_tables = []
    matched_ids = set()
    for t in tables:
        t_name = (t.get("name") or "").lower()
        t_id = (t.get("id") or "").lower()
        if table_term in t_name or table_term in t_id:
            matched_tables.append(t)
            matched_ids.add(t["id"])
    matched_rels = [
        r for r in (relationships or [])
        if r.get("from") in matched_ids or r.get("to") in matched_ids
    ]
    return matched_tables, matched_rels


def format_endpoints_text(endpoints):
    """Format endpoint view dictionaries into human-readable text."""
    if not endpoints:
        return "no endpoints found"
    blocks = []
    for ep in endpoints:
        lines = [f"{ep['method']:<6} {ep['path']}"]
        handler = ep.get("handler")
        if handler:
            where = f" ({handler['file']}:{handler['line']})" if handler.get("file") else ""
            lines.append(f"  handler: {handler['name']}{where}")
        if ep.get("note"):
            lines.append(f"  note:    {ep['note']}")
        if ep.get("callers"):
            caller_strs = [
                f"{c['name']} ({c['file']}:{c['line']})" if c.get("file") else c["name"]
                for c in ep["callers"]
            ]
            lines.append(f"  callers: {', '.join(caller_strs)}")
        if ep.get("code"):
            code_strs = [
                f"{c['name']} ({c['via']}, depth {c['depth']})"
                for c in ep["code"]
            ]
            lines.append(f"  code:    {', '.join(code_strs)}")
        if ep.get("tables"):
            table_strs = [f"{t['name']} ({t['mode']})" for t in ep["tables"]]
            lines.append(f"  tables:  {', '.join(table_strs)}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def format_endpoints_markdown(endpoints):
    """Format endpoint view dictionaries into a clean GFM markdown table."""
    if not endpoints:
        return "no endpoints found"

    def _esc(val):
        return str(val).replace("|", "\\|").replace("\n", " ").strip()

    lines = [
        "| Method | Route | Handler | Callers | Tables |",
        "| --- | --- | --- | --- | --- |",
    ]
    for ep in endpoints:
        method = ep.get("method") or ""
        route = ep.get("path") or ""
        handler = ep.get("handler")
        if handler:
            where = f" ({handler['file']}:{handler['line']})" if handler.get("file") else ""
            handler_str = f"{handler['name']}{where}"
        else:
            handler_str = "-"

        if ep.get("callers"):
            caller_strs = [
                f"{c['name']} ({c['file']}:{c['line']})" if c.get("file") else c["name"]
                for c in ep["callers"]
            ]
            callers_str = ", ".join(caller_strs)
        else:
            callers_str = "-"

        if ep.get("tables"):
            table_strs = [f"{t['name']} ({t['mode']})" for t in ep["tables"]]
            tables_str = ", ".join(table_strs)
        else:
            tables_str = "-"

        lines.append(
            f"| {_esc(method)} | {_esc(route)} | {_esc(handler_str)} | {_esc(callers_str)} | {_esc(tables_str)} |"
        )
    return "\n".join(lines)


def format_tables_text(tables, relationships=None, all_tables=None):
    """Format table dictionaries into human-readable text."""
    if not tables:
        return "no tables found"

    source_tables = all_tables if all_tables is not None else tables
    table_names = {t["id"]: t["name"] for t in source_tables if "id" in t}
    col_names = {c["id"]: c["name"] for t in source_tables for c in t.get("columns", []) if "id" in c}

    blocks = []
    for table in tables:
        col_count = len(table.get("columns", []))
        lines = [f"table {table['name']} ({col_count} column{'s' if col_count != 1 else ''})"]
        if table.get("models"):
            lines.append(f"  models:  {', '.join(table['models'])}")
        if table.get("columns"):
            lines.append("  columns:")
            max_name = max(len(c["name"]) for c in table["columns"])
            for col in table["columns"]:
                attrs = []
                if col.get("type"):
                    attrs.append(col["type"])
                if col.get("primaryKey"):
                    attrs.append("PRIMARY KEY")
                elif not col.get("nullable", True):
                    attrs.append("NOT NULL")
                if col.get("unique"):
                    attrs.append("UNIQUE")
                if col.get("default") is not None:
                    attrs.append(f"DEFAULT {col['default']}")
                attr_str = ("  " + " ".join(attrs)) if attrs else ""
                lines.append(f"    {col['name']:<{max_name}}{attr_str}")
        if table.get("foreignKeys"):
            lines.append("  foreign keys:")
            for fk in table["foreignKeys"]:
                from_col = col_names.get(fk["column"]) or fk["column"].rsplit("#", 1)[-1]
                to_tbl = table_names.get(fk["to"]) or fk["to"].rsplit(":", 1)[-1]
                to_col = col_names.get(fk["targetColumn"]) or fk["targetColumn"].rsplit("#", 1)[-1]
                lines.append(f"    {from_col} -> {to_tbl}({to_col})")
        if table.get("referencedBy"):
            lines.append("  referenced by:")
            for ref in table["referencedBy"]:
                from_tbl = table_names.get(ref["from"]) or ref["from"].rsplit(":", 1)[-1]
                from_col = col_names.get(ref["column"]) or ref["column"].rsplit("#", 1)[-1]
                to_col = col_names.get(ref["targetColumn"]) or ref["targetColumn"].rsplit("#", 1)[-1]
                lines.append(f"    {from_tbl}({from_col}) -> {to_col}")
        if table.get("reads"):
            readers = [
                f"{r['name']} ({r['file']}:{r['line']})" if r.get("file") else r["name"]
                for r in table["reads"]
            ]
            lines.append(f"  reads:   {', '.join(readers)}")
        if table.get("writes"):
            writers = [
                f"{w['name']} ({w['file']}:{w['line']})" if w.get("file") else w["name"]
                for w in table["writes"]
            ]
            lines.append(f"  writes:  {', '.join(writers)}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def format_tables_markdown(tables, relationships=None, all_tables=None):
    """Format table dictionaries into GFM markdown tables of tables, columns, and relationships."""
    if not tables:
        return "no tables found"

    source_tables = all_tables if all_tables is not None else tables
    table_names = {t["id"]: t["name"] for t in source_tables if "id" in t}
    col_names = {c["id"]: c["name"] for t in source_tables for c in t.get("columns", []) if "id" in c}

    def _esc(val):
        return str(val).replace("|", "\\|").replace("\n", " ").strip()

    blocks = []

    # Overview table of tables
    overview_lines = [
        "## Tables",
        "",
        "| Table | Columns | Primary Key |",
        "| --- | --- | --- |",
    ]
    for table in tables:
        name = table.get("name") or ""
        cols = table.get("columns") or []
        pk_cols = [c["name"] for c in cols if c.get("primaryKey")]
        pk_str = ", ".join(pk_cols) if pk_cols else "-"
        overview_lines.append(f"| {_esc(name)} | {len(cols)} | {_esc(pk_str)} |")
    blocks.append("\n".join(overview_lines))

    # Per-table column tables
    for table in tables:
        tbl_lines = [f"### `{table['name']}`", ""]
        if table.get("models"):
            tbl_lines.append(f"- **Models:** {', '.join(table['models'])}")

        columns = table.get("columns") or []
        if columns:
            tbl_lines.append("| Column | Type | Primary Key | Nullable | Default |")
            tbl_lines.append("| --- | --- | --- | --- | --- |")
            for col in columns:
                c_name = col.get("name") or ""
                c_type = col.get("type") or "-"
                c_pk = "Yes" if col.get("primaryKey") else "No"
                c_null = "Yes" if col.get("nullable", True) else "No"
                c_default = str(col["default"]) if col.get("default") is not None else "-"
                tbl_lines.append(
                    f"| {_esc(c_name)} | {_esc(c_type)} | {c_pk} | {c_null} | {_esc(c_default)} |"
                )
            tbl_lines.append("")

        meta_lines = []
        if table.get("foreignKeys"):
            fk_strs = []
            for fk in table["foreignKeys"]:
                from_col = col_names.get(fk["column"]) or fk["column"].rsplit("#", 1)[-1]
                to_tbl = table_names.get(fk["to"]) or fk["to"].rsplit(":", 1)[-1]
                to_col = col_names.get(fk["targetColumn"]) or fk["targetColumn"].rsplit("#", 1)[-1]
                fk_strs.append(f"`{from_col}` -> `{to_tbl}({to_col})`")
            meta_lines.append(f"- **Foreign Keys:** {', '.join(fk_strs)}")

        if table.get("referencedBy"):
            ref_strs = []
            for ref in table["referencedBy"]:
                from_tbl = table_names.get(ref["from"]) or ref["from"].rsplit(":", 1)[-1]
                from_col = col_names.get(ref["column"]) or ref["column"].rsplit("#", 1)[-1]
                to_col = col_names.get(ref["targetColumn"]) or ref["targetColumn"].rsplit("#", 1)[-1]
                ref_strs.append(f"`{from_tbl}({from_col})` -> `{to_col}`")
            meta_lines.append(f"- **Referenced By:** {', '.join(ref_strs)}")

        if table.get("reads"):
            readers = [
                f"`{r['name']}` ({r['file']}:{r['line']})" if r.get("file") else f"`{r['name']}`"
                for r in table["reads"]
            ]
            meta_lines.append(f"- **Reads:** {', '.join(readers)}")

        if table.get("writes"):
            writers = [
                f"`{w['name']}` ({w['file']}:{w['line']})" if w.get("file") else f"`{w['name']}`"
                for w in table["writes"]
            ]
            meta_lines.append(f"- **Writes:** {', '.join(writers)}")

        if meta_lines:
            tbl_lines.extend(meta_lines)

        blocks.append("\n".join(tbl_lines).rstrip())

    # Relationships table
    rels_to_format = []
    if relationships:
        for rel in relationships:
            from_tbl = table_names.get(rel.get("from")) or (rel.get("from") or "").rsplit(":", 1)[-1]
            from_col = col_names.get(rel.get("column")) or (rel.get("column") or "").rsplit("#", 1)[-1]
            to_tbl = table_names.get(rel.get("to")) or (rel.get("to") or "").rsplit(":", 1)[-1]
            to_col = col_names.get(rel.get("targetColumn")) or (rel.get("targetColumn") or "").rsplit("#", 1)[-1]
            if from_tbl and to_tbl:
                rels_to_format.append((from_tbl, from_col, to_tbl, to_col))

    if rels_to_format:
        rels_to_format = sorted(set(rels_to_format))
        rel_lines = [
            "## Relationships",
            "",
            "| From Table | Column | To Table | Target Column |",
            "| --- | --- | --- | --- |",
        ]
        for f_tbl, f_col, t_tbl, t_col in rels_to_format:
            rel_lines.append(f"| {_esc(f_tbl)} | {_esc(f_col)} | {_esc(t_tbl)} | {_esc(t_col)} |")
        blocks.append("\n".join(rel_lines))

    return "\n\n".join(blocks)


def format_tables_mermaid(tables, relationships=None, all_tables=None):
    """Format table dictionaries into valid Mermaid erDiagram syntax."""
    if not tables:
        return "erDiagram\n"

    source_tables = all_tables if all_tables is not None else tables
    table_names = {t["id"]: t["name"] for t in source_tables if "id" in t}
    col_names = {c["id"]: c["name"] for t in source_tables for c in t.get("columns", []) if "id" in c}

    def _mermaid_entity(name):
        name = str(name).strip()
        if re.match(r"^[A-Za-z0-9_]+$", name):
            return name
        return f'"{name}"'

    lines = ["erDiagram"]

    # Relationships first
    rels_to_format = []
    if relationships:
        for rel in relationships:
            from_tbl = table_names.get(rel.get("from")) or (rel.get("from") or "").rsplit(":", 1)[-1]
            from_col = col_names.get(rel.get("column")) or (rel.get("column") or "").rsplit("#", 1)[-1]
            to_tbl = table_names.get(rel.get("to")) or (rel.get("to") or "").rsplit(":", 1)[-1]
            if from_tbl and to_tbl:
                rels_to_format.append((to_tbl, from_tbl, from_col))

    if rels_to_format:
        for to_tbl, from_tbl, from_col in sorted(
            set(rels_to_format),
            key=lambda r: (r[0].lower(), r[1].lower(), r[2].lower()),
        ):
            to_ent = _mermaid_entity(to_tbl)
            from_ent = _mermaid_entity(from_tbl)
            label = re.sub(r'["\[\]|]+', "_", from_col or "references").strip() or "references"
            lines.append(f'    {to_ent} ||--o{{ {from_ent} : "{label}"')

    # Tables and attributes
    for table in sorted(tables, key=lambda t: (t["name"].lower(), t.get("id", ""))):
        ent = _mermaid_entity(table["name"])
        columns = table.get("columns") or []
        fk_col_ids = {fk["column"] for fk in table.get("foreignKeys", [])}
        if not columns:
            lines.append(f"    {ent}")
            continue

        lines.append(f"    {ent} {{")
        for col in columns:
            c_type = re.sub(r"\s+", "_", (col.get("type") or "").strip())
            if not c_type:
                c_type = "unknown"
            c_name = re.sub(r"[^A-Za-z0-9_]", "_", (col.get("name") or "").strip()) or "col"

            is_pk = bool(col.get("primaryKey"))
            is_fk = col.get("id") in fk_col_ids
            is_uk = bool(col.get("unique"))

            if is_pk and is_fk:
                key = " PK,FK"
            elif is_pk:
                key = " PK"
            elif is_fk and is_uk:
                key = " UK,FK"
            elif is_fk:
                key = " FK"
            elif is_uk:
                key = " UK"
            else:
                key = ""

            lines.append(f"        {c_type} {c_name}{key}")
        lines.append("    }")

    return "\n".join(lines) + "\n"


_ER_RELATIONSHIP = re.compile(
    r'^\s*("[^"]+"|[A-Za-z0-9_]+)\s+(\|\|--o\{|\}o--\|\||\|\|--\|\||\}o--o\{)\s+("[^"]+"|[A-Za-z0-9_]+)\s*:\s*("[^"]+"|[A-Za-z0-9_]+)\s*$'
)
_ER_ENTITY_START = re.compile(r'^\s*("[^"]+"|[A-Za-z0-9_]+)\s*\{\s*$')
_ER_ENTITY_SINGLE = re.compile(r'^\s*("[^"]+"|[A-Za-z0-9_]+)\s*$')
_ER_ATTR = re.compile(r'^\s*([A-Za-z0-9_()]+)\s+([A-Za-z0-9_]+)(\s+(PK|FK|UK|PK,FK|UK,FK))?\s*$')


def valid_mermaid_er(text):
    """True when text is valid Mermaid erDiagram syntax produced by this module."""
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines or lines[0].strip() != "erDiagram":
        return False
    in_block = False
    for line in lines[1:]:
        if in_block:
            if line.strip() == "}":
                in_block = False
                continue
            if not _ER_ATTR.match(line):
                return False
        else:
            if _ER_ENTITY_START.match(line):
                in_block = True
                continue
            if _ER_RELATIONSHIP.match(line) or _ER_ENTITY_SINGLE.match(line):
                continue
            return False
    return not in_block


def cmd_endpoints(conn, args):
    """CLI handler for `cbi endpoints`."""
    view = endpoint_view(conn)
    endpoints = filter_endpoints(
        view["endpoints"],
        path=getattr(args, "path", None),
        method=getattr(args, "method", None),
        handler=getattr(args, "handler", None),
        table=getattr(args, "table", None),
    )
    fmt = "json" if getattr(args, "json", False) else getattr(args, "format", "text")
    if fmt == "json":
        print(json.dumps({"endpoints": endpoints}, indent=2))
        return 0
    if fmt == "markdown":
        print(format_endpoints_markdown(endpoints))
        return 0
    print(format_endpoints_text(endpoints))
    return 0


def cmd_tables(conn, args):
    """CLI handler for `cbi tables`."""
    view = database_view(conn)
    tables, rels = filter_tables(
        view["tables"],
        view["relationships"],
        table=getattr(args, "table", None),
    )
    fmt = "json" if getattr(args, "json", False) else getattr(args, "format", "text")
    if fmt == "json":
        print(json.dumps({"tables": tables, "relationships": rels}, indent=2))
        return 0
    if fmt == "markdown":
        print(format_tables_markdown(tables, rels, all_tables=view["tables"]))
        return 0
    if fmt == "mermaid":
        print(format_tables_mermaid(tables, rels, all_tables=view["tables"]).rstrip())
        return 0
    print(format_tables_text(tables, rels, all_tables=view["tables"]))
    return 0

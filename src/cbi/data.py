"""Database schema and table-use facts derived without executing target code.

Tables and columns are ordinary model nodes. Foreign keys and code uses are
edges with source ``data``. This module stores semantic facts and source
evidence only; diagram layout belongs to the viewer.
"""

import json
import re
from collections import defaultdict


LAYOUT_KEYS = {"x", "y", "width", "height", "position", "route", "points"}

_IDENT = r'(?:"(?:[^"]|"")+"|`[^`]+`|\[[^]]+\]|[A-Za-z_][\w$]*)'
_QUALIFIED = rf"{_IDENT}(?:\s*\.\s*{_IDENT})?"
_CREATE = re.compile(rf"\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?P<name>{_QUALIFIED})\s*\(", re.I)
_ALTER_FK = re.compile(
    rf"\bALTER\s+TABLE\s+(?:ONLY\s+)?(?P<table>{_QUALIFIED}).*?"
    rf"FOREIGN\s+KEY\s*\((?P<cols>[^)]+)\)\s*REFERENCES\s+"
    rf"(?P<target>{_QUALIFIED})\s*\((?P<targets>[^)]+)\)", re.I | re.S)
_CONSTRAINT = re.compile(r"^(?:CONSTRAINT\s+\S+\s+)?(PRIMARY\s+KEY|FOREIGN\s+KEY|UNIQUE|CHECK)\b", re.I)
_STOP_TYPE = re.compile(
    r"\s+(?:CONSTRAINT|PRIMARY\s+KEY|NOT\s+NULL|NULL|UNIQUE|DEFAULT|REFERENCES|CHECK|COLLATE|GENERATED)\b",
    re.I)


def _unquote(value):
    value = value.strip()
    if len(value) >= 2 and (value[0], value[-1]) in (("\"", "\""), ("`", "`"), ("[", "]")):
        value = value[1:-1]
    return value.replace('""', '"')


def _name(value):
    return ".".join(_unquote(part) for part in re.split(r"\s*\.\s*", value.strip()))


def _id_name(value):
    return re.sub(r"[^a-z0-9_.-]+", "_", value.lower()).strip("_")


def table_id(workspace_id, name):
    return f"{workspace_id}:table:{_id_name(name)}"


def column_id(workspace_id, table, column):
    return f"{table_id(workspace_id, table)}#{_id_name(column)}"


def _comments(text):
    text = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
    return re.sub(r"--[^\n]*", "", text)


def _balanced(text, opening):
    depth = 1
    quote = None
    index = opening + 1
    while index < len(text):
        char = text[index]
        if quote:
            if char == quote:
                if index + 1 < len(text) and text[index + 1] == quote:
                    index += 2
                    continue
                quote = None
        elif char in ("'", '"', "`"):
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return text[opening + 1:index], index
        index += 1
    return text[opening + 1:], len(text)


def _split(value):
    out = []
    start = depth = 0
    quote = None
    for index, char in enumerate(value):
        if quote:
            if char == quote:
                quote = None
        elif char in ("'", '"', "`"):
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        elif char == "," and depth == 0:
            out.append(value[start:index].strip())
            start = index + 1
    tail = value[start:].strip()
    if tail:
        out.append(tail)
    return out


def _names(value):
    return [_name(part) for part in _split(value) if part.strip()]


def _constraint(item):
    head = re.sub(r"^CONSTRAINT\s+\S+\s+", "", item.strip(), flags=re.I)
    primary = re.match(r"PRIMARY\s+KEY\s*\(([^)]+)\)", head, re.I | re.S)
    if primary:
        return {"kind": "primary", "columns": _names(primary.group(1))}
    unique = re.match(r"UNIQUE\s*\(([^)]+)\)", head, re.I | re.S)
    if unique:
        return {"kind": "unique", "columns": _names(unique.group(1))}
    foreign = re.match(
        rf"FOREIGN\s+KEY\s*\(([^)]+)\)\s*REFERENCES\s+({_QUALIFIED})\s*\(([^)]+)\)",
        head, re.I | re.S)
    if foreign:
        return {"kind": "foreign", "columns": _names(foreign.group(1)),
                "table": _name(foreign.group(2)), "targets": _names(foreign.group(3))}
    return None


def _column(item):
    match = re.match(rf"\s*(?P<name>{_IDENT})\s+(?P<rest>.+)$", item, re.S)
    if not match:
        return None
    rest = match.group("rest").strip()
    stop = _STOP_TYPE.search(" " + rest)
    type_name = rest[:max(0, stop.start() - 1)].strip() if stop else rest
    if not type_name:
        return None
    default = re.search(
        r"\bDEFAULT\s+(.+?)(?=\s+(?:CONSTRAINT|PRIMARY|NOT\s+NULL|NULL|UNIQUE|REFERENCES|CHECK)\b|$)",
        rest, re.I | re.S)
    ref = re.search(rf"\bREFERENCES\s+({_QUALIFIED})\s*\(([^)]+)\)", rest, re.I | re.S)
    return {
        "name": _unquote(match.group("name")), "type": re.sub(r"\s+", " ", type_name),
        "nullable": not bool(re.search(r"\bNOT\s+NULL\b|\bPRIMARY\s+KEY\b", rest, re.I)),
        "default": default.group(1).strip() if default else None,
        "primary_key": bool(re.search(r"\bPRIMARY\s+KEY\b", rest, re.I)),
        "unique": bool(re.search(r"\bUNIQUE\b", rest, re.I)),
        "reference": (_name(ref.group(1)), _names(ref.group(2))[0]) if ref else None,
    }


def parse_sql(text, path):
    """Return table declarations from one SQL file."""
    clean = _comments(text)
    tables = []
    for match in _CREATE.finditer(clean):
        body, _end = _balanced(clean, match.end() - 1)
        table = {"name": _name(match.group("name")), "path": path,
                 "line": clean.count("\n", 0, match.start()) + 1, "columns": [], "constraints": []}
        for item in _split(body):
            if _CONSTRAINT.match(item):
                constraint = _constraint(item)
                if constraint:
                    table["constraints"].append(constraint)
            else:
                column = _column(item)
                if column:
                    table["columns"].append(column)
        tables.append(table)
    for match in _ALTER_FK.finditer(clean):
        tables.append({
            "name": _name(match.group("table")), "path": path,
            "line": clean.count("\n", 0, match.start()) + 1, "columns": [],
            "constraints": [{"kind": "foreign", "columns": _names(match.group("cols")),
                             "table": _name(match.group("target")),
                             "targets": _names(match.group("targets"))}],
        })
    return tables


def _source(root, workspace_root, path):
    try:
        rel = "/".join(part for part in (workspace_root, path) if part)
        return (root / rel).read_text(errors="replace")
    except OSError:
        return None


def _merge(declarations):
    tables = {}
    for item in declarations:
        table = tables.setdefault(item["name"].lower(), {
            "name": item["name"], "sources": [], "columns": {}, "foreign": []})
        source = {"path": item["path"], "line": item["line"], "kind": "sql"}
        if source not in table["sources"]:
            table["sources"].append(source)
        for raw in item["columns"]:
            column = table["columns"].setdefault(raw["name"].lower(), dict(raw, sources=[]))
            for key in ("type", "default", "reference"):
                if not column.get(key) and raw.get(key):
                    column[key] = raw[key]
            column["nullable"] = column.get("nullable", True) and raw.get("nullable", True)
            column["primary_key"] = column.get("primary_key", False) or raw.get("primary_key", False)
            column["unique"] = column.get("unique", False) or raw.get("unique", False)
            if source not in column["sources"]:
                column["sources"].append(source)
            if raw.get("reference"):
                table["foreign"].append((raw["name"], *raw["reference"], source))
        for constraint in item["constraints"]:
            for name in constraint.get("columns", []):
                column = table["columns"].setdefault(name.lower(), {
                    "name": name, "type": "", "nullable": True, "default": None,
                    "primary_key": False, "unique": False, "reference": None, "sources": [source]})
                if constraint["kind"] == "primary":
                    column["primary_key"], column["nullable"] = True, False
                elif constraint["kind"] == "unique":
                    column["unique"] = True
            if constraint["kind"] == "foreign":
                for local, target in zip(constraint["columns"], constraint["targets"]):
                    table["foreign"].append((local, constraint["table"], target, source))
    return tables


def _clean_attrs(attrs):
    assert not (LAYOUT_KEYS & set(attrs)), "database model contains viewer layout"
    return json.dumps(attrs, sort_keys=True)


def apply(conn, root):
    """Replace derived SQL schema nodes and edges in ``conn``."""
    workspace_roots = {
        wid: (json.loads(attrs or "{}").get("root") or "")
        for wid, attrs in conn.execute("SELECT id, attrs FROM nodes WHERE kind = 'workspace'")}
    by_workspace = defaultdict(list)
    for _fid, wid, path in conn.execute(
            "SELECT id, workspace_id, path FROM nodes WHERE kind = 'file' AND lower(path) LIKE '%.sql' ORDER BY id"):
        text = _source(root, workspace_roots.get(wid, ""), path)
        if text is not None:
            by_workspace[wid].extend(parse_sql(text, path))

    conn.execute("DELETE FROM edges WHERE source = 'data'")
    conn.execute("DELETE FROM nodes WHERE kind IN ('table', 'column')")
    for wid, raw in sorted(by_workspace.items()):
        tables = _merge(raw)
        for table in list(tables.values()):
            for _local, target_name, target_col, source in table["foreign"]:
                target = tables.setdefault(target_name.lower(), {
                    "name": target_name, "sources": [], "columns": {}, "foreign": []})
                target["columns"].setdefault(target_col.lower(), {
                    "name": target_col, "type": "", "nullable": True, "default": None,
                    "primary_key": False, "unique": False, "reference": None, "sources": [source]})
        for table in sorted(tables.values(), key=lambda row: row["name"].lower()):
            tid = table_id(wid, table["name"])
            first = min(table["sources"], key=lambda row: (row["path"], row["line"])) if table["sources"] else {}
            attrs = {"sources": sorted(table["sources"], key=lambda row: (row["path"], row["line"]))}
            conn.execute(
                "INSERT INTO nodes (id, parent_id, kind, display_kind, name, workspace_id, path, start_line, attrs) "
                "VALUES (?, ?, 'table', 'table', ?, ?, ?, ?, ?)",
                (tid, wid, table["name"], wid, first.get("path"), first.get("line"), _clean_attrs(attrs)))
            for column in sorted(table["columns"].values(), key=lambda row: row["name"].lower()):
                cid = column_id(wid, table["name"], column["name"])
                sources = sorted(column["sources"], key=lambda row: (row["path"], row["line"]))
                cattrs = {key: value for key, value in column.items()
                          if key not in ("name", "sources") and value is not None}
                cattrs["sources"] = sources
                conn.execute(
                    "INSERT INTO nodes (id, parent_id, kind, display_kind, name, workspace_id, path, start_line, attrs) "
                    "VALUES (?, ?, 'column', 'column', ?, ?, ?, ?, ?)",
                    (cid, tid, column["name"], wid, first.get("path"), first.get("line"), _clean_attrs(cattrs)))
        ordinal = defaultdict(int)
        for table in sorted(tables.values(), key=lambda row: row["name"].lower()):
            for local, target_table, target_column, source in table["foreign"]:
                src = column_id(wid, table["name"], local)
                dst = column_id(wid, tables[target_table.lower()]["name"], target_column)
                slot = ordinal[(src, dst)]
                ordinal[(src, dst)] += 1
                conn.execute(
                    "INSERT INTO edges (src, dst, kind, source, confidence, weight, attrs, ordinal) "
                    "VALUES (?, ?, 'foreign_key', 'data', 1, 1, ?, ?)",
                    (src, dst, _clean_attrs({"source": source}), slot))

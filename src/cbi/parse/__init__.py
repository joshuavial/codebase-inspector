"""Parsers per language. Each turns one file's bytes into symbol and test nodes and resolution facts."""

import hashlib
import re

from cbi.ids import symbol_ids
from cbi.parse import csharp, python, typescript, vue

LANGS = set(typescript.GRAMMARS) | set(python.GRAMMARS) | set(csharp.GRAMMARS) | set(vue.GRAMMARS)
HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
NEXT_ROUTE_FILES = {"route.ts", "route.tsx", "route.js", "route.jsx", "route.mts", "route.cts"}


def _next_route(path):
    """Return the URL for a Next.js app-router route file, or None."""
    parts = path.replace("\\", "/").split("/")
    if len(parts) < 3 or parts[-1] not in NEXT_ROUTE_FILES or "app" not in parts[:-1]:
        return None
    start = max(index for index, part in enumerate(parts[:-1]) if part == "app")
    route = []
    for part in parts[start + 1:-1]:
        if (part.startswith("(") and part.endswith(")")) or part.startswith("@"):
            continue
        if part.startswith("[[...") and part.endswith("]]"):
            route.append("{" + part[5:-2] + "}")
        elif part.startswith("[...") and part.endswith("]"):
            route.append("{" + part[4:-1] + "}")
        elif part.startswith("[") and part.endswith("]"):
            route.append("{" + part[1:-1] + "}")
        else:
            route.append(part)
    return "/" + "/".join(route)


def span_hashes(source, start_line, end_line, signature):
    """(full span sha1, body sha1) for a symbol's source lines.

    The body is the span with the signature stripped, so a rename keeps the
    body hash. That hash is the symbol's content hash: a move is an unchanged
    body with a new path or qualified name. The signature may start after a
    short prefix on the same lines (`export function` is stored from
    `function`), so the match is the first one that still sits before any `{`.
    """
    text = source.decode("utf-8", "replace") if isinstance(source, (bytes, bytearray)) else source
    lines = text.splitlines()
    start = max(int(start_line or 1), 1)
    end = max(int(end_line or start), start)
    span = "\n".join(lines[start - 1:end])
    body = span
    parts = (signature or "").split()
    if parts:
        match = re.search(r"\s*".join(re.escape(part) for part in parts), span)
        if match and "{" not in span[:match.start()]:
            body = span[match.end():]
    digest = lambda value: hashlib.sha1(value.encode()).hexdigest()
    return digest(span), digest(body)


def symbol_nodes(file_node_id, workspace_id, path, lang, source, is_test):
    """Return (nodes, facts, has_parse_error) for one file.

    Nodes carry stable IDs and parent IDs. In facts, calls, reads and env reads
    name the innermost enclosing definition by node ID, or None for the file
    itself. A `...process.env` spread is an env read of `*` with no definition,
    so resolution keeps it on the file.
    """
    if lang in vue.GRAMMARS:
        defs, facts, has_error = vue.parse(source, lang, is_test, path)
    elif lang in csharp.GRAMMARS:
        defs, facts, has_error = csharp.parse(source, lang, is_test)
    elif lang in python.GRAMMARS:
        defs, facts, has_error = python.parse(source, lang, is_test)
    else:
        defs, facts, has_error = typescript.parse(source, lang, is_test)
    ids = symbol_ids(file_node_id, [(d["qualname"], d["signature"]) for d in defs])
    nodes = []
    for i, d in enumerate(defs):
        _full, body = span_hashes(source, d["start_line"], d["end_line"], d["signature"])
        nodes.append({
            "id": ids[i],
            "parent_id": file_node_id if d["parent"] is None else ids[d["parent"]],
            "kind": d["kind"],
            "display_kind": d["display_kind"],
            "name": d["name"],
            "workspace_id": workspace_id,
            "path": path,
            "start_line": d["start_line"],
            "end_line": d["end_line"],
            "lang": lang,
            "loc": d["end_line"] - d["start_line"] + 1,
            "signature": d["signature"],
            "doc": d["doc"],
            "content_hash": body,
        })
        if d.get("attrs"):
            nodes[-1]["attrs"] = d["attrs"]
    at = lambda i: None if i is None else ids[i]
    facts["calls"] = [[at(d), at(c), *rest] for d, c, *rest in facts["calls"]]
    facts["reads"] = [[at(d), *rest] for d, *rest in facts["reads"]]
    if "patches" in facts:
        facts["patches"] = [[at(d), spec] for d, spec in facts["patches"]]
    facts["envs"] = [[at(d), name, default] for d, name, default in facts.get("envs", [])]
    facts["uses"] = [[at(d), at(c), *rest] for d, c, *rest in facts.get("uses", [])]
    facts["fields"] = [[at(c), *rest] for c, *rest in facts.get("fields", [])]
    facts["protocols"] = [at(i) for i in facts.get("protocols", [])]
    if facts.get("visits"):
        facts["visits"] = [[at(src), pattern] for src, pattern in facts["visits"]]
    if facts.get("routes"):
        rewritten = []
        for item in facts["routes"]:
            item = dict(item)
            item["def"] = at(item.get("def"))
            rewritten.append(item)
        facts["routes"] = rewritten
    facts["http_routes"] = [[at(row[0]), *row[1:]] for row in facts.get("http_routes") or []]
    next_path = _next_route(path) if not is_test and lang in typescript.GRAMMARS else None
    if next_path is not None:
        exported = facts.get("exports") or {}
        by_name = {node["name"]: node["id"] for node in nodes}
        existing = {(row[0], row[1], row[2]) for row in facts["http_routes"]}
        for method in sorted(HTTP_METHODS):
            local = exported.get(method)
            handler = by_name.get(local) if local else None
            route = (handler, method, next_path)
            if handler and route not in existing:
                facts["http_routes"].append([handler, method, next_path, None, local])
    facts["http_calls"] = [[at(row[0]), *row[1:]] for row in facts.get("http_calls") or []]
    facts.setdefault("http_routers", [])
    facts.setdefault("http_mounts", [])
    return nodes, facts, has_error

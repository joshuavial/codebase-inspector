"""Normalise HTTP paths and match client calls to server routes.

A route path is the join of every prefix that mounts its router. A client may
omit a server prefix; the match is the longest suffix that ends on a segment
boundary. `{id}`, `:id` and `{id:int}` are the same kind of parameter segment.
`link` reads parse facts and returns edges, diagnostics and handler attrs.
It does not import `resolve` (that module imports this one).
"""

import json
from collections import defaultdict

from cbi.parse.http_paths import from_pieces, has_literal, is_api_href, is_external_url, is_param, join_path, normalise, segments

VERBS = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS")
TEST_DIRS = {"test", "tests", "__tests__"}


def _test_helper(file_row):
    _workspace, path, role = file_row
    parts = path.replace("\\", "/").split("/")
    stem = parts[-1].rsplit(".", 1)[0].lower()
    helper_dirs = {"fixtures", "mocks", "test_helpers"}
    helper_name = stem.startswith(("fake_", "mock_", "stub_")) or stem.endswith(("_fake", "_mock", "_stub"))
    return role == "test" or bool(TEST_DIRS & set(parts)) or bool(helper_dirs & set(parts)) or helper_name


def score(client, server):
    """(matched segments, literal matches, extra segments) or None when a literal differs.

    A parameter segment matches only another parameter. The client may be a
    suffix of the server (it omitted a prefix) or the server a suffix of the
    client (it kept a base). Fewer extra segments is the closer match.
    """
    left, right = segments(client), segments(server)
    if not left or not right:
        return None

    def align(one, two):
        literals = 0
        for client_seg, server_seg in zip(one, two):
            client_param, server_param = is_param(client_seg), is_param(server_seg)
            if client_param and server_param:
                continue
            if client_param or server_param or client_seg != server_seg:
                return None
            literals += 1
        return literals

    best = None
    if len(left) <= len(right):
        extra = len(right) - len(left)
        literals = align(left, right[extra:])
        if literals is not None:
            best = (len(left), literals, extra)
    if len(right) <= len(left):
        extra = len(left) - len(right)
        literals = align(left[extra:], right)
        if literals is not None:
            cand = (len(right), literals, extra)
            if best is None or (cand[0], cand[1], -cand[2]) > (best[0], best[1], -best[2]):
                best = cand
    return best


def _confidence(client, server, extra):
    if extra:
        return 0.8
    if client == server:
        return 1.0
    return 0.9


def _pad(row, size):
    row = list(row)
    if len(row) < size:
        row.extend([None] * (size - len(row)))
    return row


def _lookup(model, fid, name):
    """The first symbol named `name` in this file, top-level preferred."""
    if not name:
        return None
    direct = model.members.get((fid, name))
    if direct:
        return sorted(direct)[0]
    found = []
    for (parent, member), ids in model.members.items():
        if member != name:
            continue
        for nid in ids:
            if model.nodes.get(nid, (None, None, None, None))[3] == fid:
                found.append(nid)
    return sorted(found)[0] if found else None


def _resolve_child(model, fid, expr, routers):
    """The (file, router name) a mount's child expression names, or None."""
    parts = [part for part in (expr or "").split(".") if part]
    if not parts:
        return None
    head, *rest = parts
    if not rest and (fid, head) in routers:
        return (fid, head)
    binding = model.bindings.get(fid, {}).get(head)
    if not binding:
        return (fid, head) if (fid, head) in routers and not rest else None
    spec, imported = binding
    path = model.files[fid][1]
    if path.endswith(".py"):
        return _py_child(model, fid, spec, imported, rest, routers)
    return _ts_child(model, fid, spec, imported, rest, routers)


def _py_child(model, fid, spec, imported, rest, routers):
    if imported == "*":
        target = model.spec(fid, spec)
        attr = rest[0] if rest else None
        if target and attr and (target, attr) in routers:
            return (target, attr)
        return None
    found = model.py_name(fid, spec, imported, set())
    if not found:
        return None
    file, name = found
    if name is None:
        attr = rest[0] if rest else None
        if file and attr and (file, attr) in routers:
            return (file, attr)
        return None
    if not rest and (file, name) in routers:
        return (file, name)
    if rest and (file, rest[0]) in routers:
        return (file, rest[0])
    return None


def _ts_child(model, fid, spec, imported, rest, routers):
    target = model.spec(fid, spec)
    if not target:
        return None
    if rest and (target, rest[0]) in routers:
        return (target, rest[0])
    if rest:
        return None
    if (target, imported) in routers:
        return (target, imported)
    if imported in ("default", "*"):
        names = [name for (file, name) in routers if file == target]
        if len(names) == 1:
            return (target, names[0])
        for cand in ("default", "router", "app"):
            if (target, cand) in routers:
                return (target, cand)
    return None


def _aboves(key, mount_of, routers, stack):
    """Prefixes from ancestor mounts, not including this router's own prefix."""
    if key in stack:
        return []
    found = mount_of.get(key)
    if not found:
        return [""]
    out = []
    for parent, extra in found:
        parent_prefix = routers.get(parent, {}).get("prefix") or ""
        for base in _aboves(parent, mount_of, routers, stack | {key}):
            out.append(join_path(base, parent_prefix, extra))
    return list(dict.fromkeys(out))


def _dynamic_consumer(client, server):
    """A possible consumer only: unknown resource segments never create edges."""
    left, right = segments(client), segments(server)
    if not any(is_param(part) for part in left):
        return False
    width = min(len(left), len(right))
    return bool(width) and all(
        is_param(a) or is_param(b) or a == b
        for a, b in zip(left[-width:], right[-width:])
    )


def _route_boundary(route, calls):
    if any(method == route["method"] and not is_external_url(path) and _dynamic_consumer(path, route["path"])
           for _caller, method, path in calls):
        return "dynamic_client", "a dynamic/generic client may consume this route; binding unresolved"
    words = {part.lower().replace("-", "_") for part in segments(route["path"])}
    if words & {"webhook", "webhooks", "callback", "callbacks"}:
        return "external_callback_candidate", "callback-shaped path; external consumer cannot be established statically"
    return "static_unresolved", "no statically resolved consumer; usage is unknown"


def link(model):
    """(edge rows, diagnostics, handler attrs) from the model's HTTP facts.

    An edge row is (src, dst, method, path, confidence, weight). The path is
    the server's full path. Diagnostics are (node id, kind, detail). Handler
    attrs map a node id to [{method, path}, ...].
    """
    routers = {}
    mounts = []
    raw_routes = []
    raw_calls = []
    unresolved_calls = set()
    for fid, facts in model.facts.items():
        if fid not in model.files or _test_helper(model.files[fid]):
            continue
        for row in facts.get("http_routers") or []:
            name, prefix, kind = _pad(row, 3)[:3]
            if name:
                routers[(fid, name)] = {"prefix": prefix or "", "kind": kind or "router"}
        for row in facts.get("http_mounts") or []:
            parent, child, extra = _pad(row, 3)[:3]
            if parent and child:
                mounts.append((fid, parent, child, extra or ""))
        for row in facts.get("http_routes") or []:
            handler, method, path, router_name, handler_name = _pad(row, 5)[:5]
            if not method or not path:
                continue
            hid = handler if handler in model.nodes else None
            if hid is None and handler_name:
                hid = _lookup(model, fid, handler_name)
            raw_routes.append((fid, hid or fid, str(method).upper(), path, router_name))
        for caller, method, line in facts.get("http_unresolved_calls") or []:
            cid = caller if caller in model.nodes else fid
            detail = f"{method} <dynamic URL> at {model.files[fid][1]}:{line}: no static path [resolution=dynamic_client]"
            unresolved_calls.add((cid, "unmatched_http_call", detail))
        for row in facts.get("http_calls") or []:
            caller, method, path = _pad(row, 3)[:3]
            if not method or not path:
                continue
            cid = caller if caller in model.nodes else fid
            raw_calls.append((cid, str(method).upper(), path))

    mount_of = defaultdict(list)
    for fid, parent, child, extra in mounts:
        parent_key = (fid, parent)
        if parent_key not in routers:
            continue
        child_key = _resolve_child(model, fid, child, routers)
        if not child_key or child_key == parent_key or child_key not in routers:
            continue
        mount_of[child_key].append((parent_key, extra))

    routes = []
    seen_route = set()
    for fid, handler, method, path, router_name in raw_routes:
        key = (fid, router_name) if router_name else None
        if key and key in routers:
            prefixes = _aboves(key, mount_of, routers, frozenset())
            own = routers[key]["prefix"]
            fulls = [join_path(prefix, own, path) for prefix in prefixes]
        else:
            fulls = [normalise(path)]
        for full in fulls:
            if not full:
                continue
            rec = (method, full, handler)
            if rec in seen_route:
                continue
            seen_route.add(rec)
            routes.append({"method": method, "path": full, "handler": handler})

    by_method = defaultdict(list)
    for route in routes:
        by_method[route["method"]].append(route)

    grouped = {}
    for caller, method, path in raw_calls:
        path = normalise(path)
        if not path or not has_literal(path):
            continue
        slot = (caller, method, path)
        grouped[slot] = grouped.get(slot, 0) + 1

    matched = set()
    edges = []
    diagnostics = sorted(unresolved_calls)
    for (caller, method, path), weight in sorted(grouped.items()):
        if is_external_url(path):
            continue
        best = None
        best_rank = None
        for route in by_method.get(method, ()):
            found = score(path, route["path"])
            if found is None:
                continue
            hit, literals, extra = found
            rank = (hit, literals, -extra, -len(route["path"]))
            if best is None or rank > best_rank or (rank == best_rank and route["handler"] < best["handler"]):
                best = route
                best_rank = rank
        if best is None:
            diagnostics.append((caller, "unmatched_http_call", f"{method} {path}: no route [resolution={'dynamic_client' if any(is_param(p) for p in segments(path)) else 'static_unresolved'}]"))
            continue
        matched.add((best["method"], best["path"], best["handler"]))
        extra = -best_rank[2]
        edges.append((caller, best["handler"], method, best["path"], _confidence(path, best["path"], extra), weight))

    for route in routes:
        key = (route["method"], route["path"], route["handler"])
        if key not in matched:
            boundary, explanation = _route_boundary(route, raw_calls)
            diagnostics.append((route["handler"], "unmatched_http_call",
                                f"{route['method']} {route['path']}: {explanation} [resolution={boundary}]"))

    by_handler = defaultdict(list)
    seen_attr = set()
    for route in routes:
        item = (route["handler"], route["method"], route["path"])
        if item in seen_attr:
            continue
        seen_attr.add(item)
        by_handler[route["handler"]].append({"method": route["method"], "path": route["path"]})
    for items in by_handler.values():
        items.sort(key=lambda row: (row["method"], row["path"]))
    diagnostics.sort(key=lambda row: (row[0] or "", row[2]))
    return edges, diagnostics, dict(by_handler)


def dump_attrs(rows):
    """JSON for a handler's route list. Stable key order."""
    return json.dumps(rows, sort_keys=True)

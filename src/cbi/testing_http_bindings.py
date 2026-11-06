"""Static in-process TestClient bindings, scoped to the selected application."""

import ast
from collections import defaultdict
from urllib.parse import urlsplit

from cbi import http
from cbi.testing_static import owner, python_modules

CLIENT_MODULES = {"fastapi.testclient", "starlette.testclient"}
FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)


def _dotted(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return base + "." + node.attr if base else ""
    return ""


def _client_imports(tree):
    aliases = {}
    for stmt in tree.body:
        if isinstance(stmt, ast.ImportFrom) and stmt.module in CLIENT_MODULES:
            aliases.update({item.asname or item.name: stmt.module + "." + item.name
                            for item in stmt.names if item.name == "TestClient"})
        elif isinstance(stmt, ast.Import):
            for item in stmt.names:
                if item.name in CLIENT_MODULES:
                    aliases[item.asname or item.name.split(".")[0]] = item.name if item.asname else item.name.split(".")[0]
    return aliases


def _application_routes(m):
    routers = {}
    for fid, facts in m.facts.items():
        if fid not in m.files or http._test_helper(m.files[fid]):
            continue
        for name, prefix, kind in facts.get("http_routers", []):
            routers[fid, name] = {"prefix": prefix or "", "kind": kind}
    children = defaultdict(list)
    direct = defaultdict(list)
    for fid, facts in m.facts.items():
        for parent, child, extra in facts.get("http_mounts", []):
            target = http._resolve_child(m, fid, child, routers)
            if target and (fid, parent) in routers:
                children[fid, parent].append((target, extra or ""))
        for row in facts.get("http_routes", []):
            handler, method, path, router, *_ = row
            if handler in m.nodes and (fid, router) in routers:
                direct[fid, router].append((handler, method, path))

    route_cache = {}
    def routes(app):
        if app in route_cache:
            return route_cache[app]
        found = []
        def visit(key, prefix, seen):
            if key in seen:
                return
            prefix = http.join_path(prefix, routers[key]["prefix"])
            for handler, method, path in direct[key]:
                found.append((handler, method, http.join_path(prefix, path)))
            for child, extra in children[key]:
                visit(child, http.join_path(prefix, extra), {*seen, key})
        visit(app, "", set())
        route_cache[app] = found
        return found
    return routers, routes


def _local_names(function):
    """Python binds locals for the entire function, including before assignment."""
    names = {arg.arg for arg in [*function.args.posonlyargs, *function.args.args,
                                *function.args.kwonlyargs]}
    for arg in (function.args.vararg, function.args.kwarg):
        if arg:
            names.add(arg.arg)
    globals_ = set()
    def visit(node):
        if isinstance(node, (ast.ClassDef, *FUNCTIONS)):
            names.add(node.name)
            return
        if isinstance(node, ast.Global):
            globals_.update(node.names)
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            names.add(node.id)
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names.update(item.asname or item.name.split(".")[0] for item in node.names)
        if isinstance(node, ast.ExceptHandler) and node.name:
            names.add(node.name)
        for child in ast.iter_child_nodes(node):
            visit(child)
    for stmt in function.body:
        visit(stmt)
    return names - globals_


def _matches(path, route):
    if not isinstance(path, str):
        return False
    parsed = urlsplit(path)
    if parsed.scheme or parsed.netloc:
        return False
    left, right = http.segments(parsed.path), http.segments(route)
    return len(left) == len(right) and all(http.is_param(expected) or actual == expected
                                           for actual, expected in zip(left, right))


def link(m, edges, add):
    """Add test edges for literal calls on statically identified TestClient apps."""
    modules = python_modules(m)
    routers, routes = _application_routes(m)
    aliases = {fid: _client_imports(tree) for fid, tree in modules.items()}
    functions = {}
    for fid, tree in modules.items():
        for node in ast.walk(tree):
            if isinstance(node, FUNCTIONS):
                nid = owner(m, fid, node)
                start = min([node.lineno, *(decorator.lineno for decorator in node.decorator_list)])
                span = m.node_spans.get(nid)
                # A nested, unmodeled definition belongs to its enclosing
                # symbol's span; it must not replace that symbol's body.
                if span and span[0] == start:
                    functions[nid] = (fid, node)
    fixture_contexts = getattr(m, "test_fixture_bindings", {})
    diagnostics = set()

    def analyze(fid, body, clients, apps, shadows, on_call=None, report=None):
        returned = set()

        def app_target(expr):
            name = _dotted(expr)
            if name in apps:
                return apps[name]
            if name.split(".")[0] in shadows:
                return None
            return http._resolve_child(m, fid, name, routers)

        def client_value(expr):
            if isinstance(expr, ast.Name):
                return clients.get(expr.id, set())
            if not isinstance(expr, ast.Call):
                return set()
            dotted = _dotted(expr.func)
            head, dot, rest = dotted.partition(".")
            imported = aliases.get(fid, {}).get(head, "")
            name = imported + (dot + rest if rest else "")
            if head in shadows or name not in {module + ".TestClient" for module in CLIENT_MODULES}:
                return set()
            application = expr.args[0] if expr.args else next((kw.value for kw in expr.keywords if kw.arg == "app"), None)
            target = app_target(application)
            if not target and report:
                report(fid, expr, "in-process HTTP application is not statically tracked", "dynamic_app")
            return {target} if target else set()

        def visit(node):
            if isinstance(node, (ast.ClassDef, *FUNCTIONS)):
                return
            if isinstance(node, ast.If):
                visit(node.test)
                alternatives = []
                for body in (node.body, node.orelse):
                    branch_clients, branch_apps, branch_shadows = dict(clients), dict(apps), set(shadows)
                    returned.update(analyze(fid, body, branch_clients, branch_apps, branch_shadows, on_call, report))
                    alternatives.append((branch_clients, branch_apps, branch_shadows))
                left, right = alternatives
                for name in left[0].keys() | right[0].keys():
                    a, b = left[0].get(name, set()), right[0].get(name, set())
                    clients[name] = a if a == b else set()
                for name in left[1].keys() | right[1].keys():
                    a, b = left[1].get(name), right[1].get(name)
                    apps[name] = a if a == b else None
                shadows.update(left[2] | right[2])
                return
            if isinstance(node, (ast.AugAssign, ast.Delete)):
                targets = node.targets if isinstance(node, ast.Delete) else [node.target]
                for target in targets:
                    for name in ast.walk(target):
                        if isinstance(name, ast.Name):
                            clients.pop(name.id, None)
                            apps[name.id] = None
                            shadows.add(name.id)
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                value = node.value
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                bound_clients = client_value(value)
                app = app_target(value)
                for target in targets:
                    if isinstance(target, ast.Name):
                        clients[target.id] = bound_clients
                        apps[target.id] = app
                        shadows.add(target.id)
            if isinstance(node, (ast.With, ast.AsyncWith)):
                for item in node.items:
                    if isinstance(item.optional_vars, ast.Name):
                        clients[item.optional_vars.id] = client_value(item.context_expr)
                        apps[item.optional_vars.id] = None
                        shadows.add(item.optional_vars.id)
            if isinstance(node, (ast.Return, ast.Yield, ast.YieldFrom)) and node.value is not None:
                returned.update(client_value(node.value))
            if on_call and isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                selected = client_value(node.func.value)
                method = node.func.attr.upper()
                arg = node.args[0] if node.args else next((kw.value for kw in node.keywords if kw.arg == "url"), None)
                if method == "REQUEST" and len(node.args) >= 2 and isinstance(node.args[0], ast.Constant):
                    method, arg = str(node.args[0].value).upper(), node.args[1]
                if selected and method in http.VERBS:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        on_call(fid, node, selected, method, arg.value)
                    elif report:
                        report(fid, node, "in-process HTTP URL is dynamic", "dynamic_url")
            for child in ast.iter_child_nodes(node):
                visit(child)
        for stmt in body:
            visit(stmt)
        return returned

    globals_cache = {}
    def globals_for(fid):
        if fid not in globals_cache:
            clients, apps, shadows = {}, {}, set()
            analyze(fid, modules[fid].body, clients, apps, shadows)
            globals_cache[fid] = (clients, apps, shadows)
        clients, apps, shadows = globals_cache[fid]
        return dict(clients), dict(apps), set(shadows)

    def scope_for(fid, node):
        clients, apps, shadows = globals_for(fid)
        for name in _local_names(node):
            clients.pop(name, None)
            apps[name] = None
            shadows.add(name)
        return clients, apps, shadows

    def fixture_client(nid, registry, seen, on_call, report):
        if nid in seen or nid not in functions:
            return set()
        fid, node = functions[nid]
        clients, apps, shadows = scope_for(fid, node)
        for arg in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]:
            if arg.arg in registry:
                clients[arg.arg] = fixture_client(registry[arg.arg], registry, {*seen, nid}, on_call, report)
            shadows.add(arg.arg)
        return analyze(fid, node.body, clients, apps, shadows, on_call, report)

    for nid, (fid, node) in functions.items():
        if m.nodes.get(nid, (None, None, None))[1:3] != ("test", "test case"):
            continue
        def on_call(file_id, call, applications, method, path):
            for application in applications:
                matches = [(handler, route) for handler, verb, route in routes(application)
                           if verb == method and _matches(path, route)]
                if not matches:
                    continue
                matches = set(matches)
                if len(matches) > 1:
                    report(file_id, call, "in-process HTTP handler selection is ambiguous", "ambiguous_route")
                if len(matches) == 1:
                    handler, route = next(iter(matches))
                    add(nid, handler, "tests", "treesitter", 0.9,
                        {"via": "in_process_http", "method": method, "path": route})
        def report(file_id, call, message, boundary):
            detail = f"{m.files[file_id][1]}:{call.lineno}: {message} [resolution={boundary}]"
            diagnostics.add((nid, "unsupported_test_mechanism", detail))

        clients, apps, shadows = scope_for(fid, node)
        registry = fixture_contexts.get(nid, {})
        for arg in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]:
            if arg.arg in registry:
                clients[arg.arg] = fixture_client(registry[arg.arg], registry, set(), on_call, report)
            shadows.add(arg.arg)

        analyze(fid, node.body, clients, apps, shadows, on_call, report)
    return sorted(diagnostics)

"""Static pytest fixture registration and production targets, without importing tests."""

import ast
import posixpath
from collections import defaultdict
from dataclasses import dataclass

from cbi.testing_static import owner, python_modules


@dataclass(frozen=True)
class _Fixture:
    fid: str
    nid: str
    name: str
    dependencies: tuple
    autouse: bool
    explicit_name: bool


def _dotted(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return _dotted(node.value) + "." + node.attr
    return ""


def _strings(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, (ast.List, ast.Tuple)):
        return [value for child in node.elts for value in _strings(child)]
    return []


def _marks(nodes, aliases):
    found = []
    for node in nodes:
        if isinstance(node, (ast.List, ast.Tuple)):
            found.extend(_marks(node.elts, aliases))
        elif isinstance(node, ast.Call):
            name = _dotted(node.func).split(".")
            if name and name[0] in aliases:
                name[0] = aliases[name[0]]
            if ".".join(name) == "pytest.mark.usefixtures":
                found.extend(value for arg in node.args for value in _strings(arg))
    return found


def _module_marks(body, aliases):
    return _marks(_module_mark_values(body), aliases)


def _module_mark_values(body):
    return [stmt.value for stmt in body if isinstance(stmt, (ast.Assign, ast.AnnAssign))
            and any(isinstance(target, ast.Name) and target.id == "pytestmark"
                    for target in (stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]))]


def _direct_parameters(nodes, aliases):
    """Direct pytest parameters supply values instead of requesting fixtures."""
    found = set()
    for node in nodes:
        if isinstance(node, (ast.List, ast.Tuple)):
            found.update(_direct_parameters(node.elts, aliases))
        elif isinstance(node, ast.Call):
            parts = _dotted(node.func).split(".")
            if parts and parts[0] in aliases:
                parts[0] = aliases[parts[0]]
            if ".".join(parts) != "pytest.mark.parametrize" or not node.args:
                continue
            names = {part.strip() for value in _strings(node.args[0]) for part in value.split(",") if part.strip()}
            indirect = next((kw.value for kw in node.keywords if kw.arg == "indirect"), None)
            if isinstance(indirect, ast.Constant) and indirect.value is True:
                continue
            found.update(names - set(_strings(indirect)))
    return found


def _parameters(node):
    return tuple(arg.arg for arg in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
                 if arg.arg not in ("self", "cls"))


def _requested(node):
    """A pytest request parameter may ask for a literal fixture explicitly."""
    if "request" not in _parameters(node):
        return ()
    return tuple(value for call in ast.walk(node) if isinstance(call, ast.Call)
                 and _dotted(call.func) == "request.getfixturevalue"
                 for value in _strings(call.args[0] if call.args else
                                       next((kw.value for kw in call.keywords if kw.arg == "argname"), None)))


def link(m, edges, add):
    """Link collected tests through visible registered fixtures to tracked production."""
    modules = python_modules(m)
    metadata = {}
    fixture_files = set()
    for fid, tree in modules.items():
        aliases = {"pytest": "pytest"}
        for stmt in tree.body:
            if isinstance(stmt, ast.Import):
                aliases.update({item.asname or item.name: item.name for item in stmt.names})
            elif isinstance(stmt, ast.ImportFrom) and stmt.module == "pytest":
                aliases.update({item.asname or item.name: "pytest." + item.name for item in stmt.names})
        info = {"fixtures": defaultdict(dict), "tests": [], "plugins": [], "marks": {(): _module_marks(tree.body, aliases)}}
        for stmt in tree.body:
            if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
                targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
                if any(isinstance(target, ast.Name) and target.id == "pytest_plugins" for target in targets):
                    info["plugins"].extend(_strings(stmt.value))

        def visit(body, scope=(), inherited=(), excluded=frozenset()):
            marks = (*inherited, *_module_marks(body, aliases)) if scope else inherited
            excluded = excluded | _direct_parameters(_module_mark_values(body), aliases)
            for node in body:
                if isinstance(node, ast.ClassDef):
                    visit(node.body, (*scope, node.name), (*marks, *_marks(node.decorator_list, aliases)),
                          excluded | _direct_parameters(node.decorator_list, aliases))
                    continue
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                nid = owner(m, fid, node)
                if nid not in m.nodes:
                    continue
                fixture = None
                for decorator in node.decorator_list:
                    func = decorator.func if isinstance(decorator, ast.Call) else decorator
                    parts = _dotted(func).split(".")
                    if parts and parts[0] in aliases:
                        parts[0] = aliases[parts[0]]
                    if ".".join(parts) != "pytest.fixture":
                        continue
                    keywords = {kw.arg: kw.value for kw in decorator.keywords} if isinstance(decorator, ast.Call) else {}
                    names = _strings(keywords.get("name"))
                    if "name" in keywords and not names:
                        continue
                    auto = keywords.get("autouse")
                    fixture = _Fixture(fid, nid, names[0] if names else node.name, (*_parameters(node), *_requested(node)),
                                       isinstance(auto, ast.Constant) and auto.value is True, bool(names))
                if fixture:
                    info["fixtures"][scope][fixture.name] = fixture
                    fixture_files.add(fid)
                elif m.nodes[nid][1:3] == ("test", "test case"):
                    direct = excluded | _direct_parameters(node.decorator_list, aliases)
                    requests = (*_parameters(node), *_requested(node), *marks, *_marks(node.decorator_list, aliases),
                                *info["marks"][()])
                    info["tests"].append((nid, scope, tuple(name for name in requests if name not in direct), direct))
        visit(tree.body)
        metadata[fid] = info

    registration_cache = {}

    def registered(fid, seen):
        if fid in seen or fid not in metadata:
            return []
        if fid in registration_cache:
            return registration_cache[fid]
        seen = {*seen, fid}
        info = metadata[fid]
        layers = []
        for spec in info["plugins"]:
            target = m.spec(fid, spec)
            if target:
                layers.extend(registered(target, seen))
        imported = {}
        for imp in m.facts.get(fid, {}).get("imports", []):
            target = m.spec(fid, imp["spec"])
            if not target or target not in metadata:
                continue
            exported = {}
            for layer in registered(target, seen):
                exported.update(layer)
            # Imported fixtures are registered under the local binding, unless
            # their decorator supplies an explicit public fixture name.
            for local, original in (imp.get("names") or {}).items():
                fixture = exported.get(original) or next((item for item in exported.values()
                                                          if item.nid == f"{target}#{original}"), None)
                if fixture:
                    imported[fixture.name if fixture.explicit_name else local] = fixture
        layers.append(imported)
        layers.append(info["fixtures"][()])
        registration_cache[fid] = layers
        return layers

    calls = defaultdict(list)
    imports = defaultdict(list)
    for (src, dst, kind, _), (confidence, _weight, _attrs) in list(edges.items()):
        if kind == "calls":
            calls[src].append((dst, confidence))
        elif kind == "imports":
            imports[src].append(dst)
    reads = defaultdict(list)
    for fid, facts in m.facts.items():
        for src, path in facts.get("reads", []):
            target = m.read_target(fid, path)
            if target:
                reads[src or fid].append(target)

    # Supplemental paths keep their exact syntax owner here. Their ordinary
    # test edges may belong to a support file, which cannot identify which
    # registered fixture (or helper) performed the read.
    from cbi.testing_paths import GlobValue, contexts, resolve_target
    from cbi.testing_sql import _targets as sql_targets
    supplemental = defaultdict(dict)
    for context in contexts(m, file_ids=fixture_files):
        dst, _mechanism, value = resolve_target(context)
        src = owner(m, context.fid, context.call)
        if dst and dst != context.fid:
            supplemental[src][dst] = 1.0
        if isinstance(context.call.func, ast.Attribute) and context.call.func.attr in {"glob", "rglob"}:
            value = context.value(context.call)
        if isinstance(value, GlobValue):
            for dst in sql_targets(context, value):
                supplemental[src][dst] = max(supplemental[src].get(dst, 0), 0.8)

    def support(fid):
        return fid in fixture_files or m.files[fid][2] == "test"

    def targets(fixture):
        found = {}
        pending = [(fixture.nid, 1.0)]
        seen = set()
        while pending:
            src, confidence = pending.pop()
            if src in seen:
                continue
            seen.add(src)
            fid = m.nodes[src][3] if src in m.nodes else src
            for evidence in (src, fid):
                for dst, conf in supplemental.get(evidence, {}).items():
                    if not support(dst):
                        found[dst] = max(found.get(dst, 0), min(confidence, conf))
            for dst in reads.get(src, ()):
                if not support(dst):
                    found[dst] = max(found.get(dst, 0), confidence)
            for dst, call_confidence in calls.get(src, ()):
                dst_fid = m.nodes[dst][3] if dst in m.nodes else dst
                conf = min(confidence, call_confidence)
                if support(dst_fid):
                    pending.append((dst, conf))
                else:
                    found[dst] = max(found.get(dst, 0), conf)
            for dst in imports.get(fid, ()):
                if not support(dst) and m.files[dst][2] == "code":
                    found[dst] = max(found.get(dst, 0), min(confidence, 0.5))
        return found

    target_cache = {}
    m.test_fixture_bindings = {}
    for fid, info in metadata.items():
        if not info["tests"]:
            continue
        wid, path, _ = m.files[fid]
        directories = []
        directory = posixpath.dirname(path)
        while True:
            directories.append(directory)
            if not directory:
                break
            directory = posixpath.dirname(directory)
        base = []
        for directory in reversed(directories):
            config = m.by_path[wid].get(posixpath.join(directory, "conftest.py"))
            if config:
                base.extend(registered(config, set()))
        base.extend(registered(fid, set()))
        for test, scope, requests, direct in info["tests"]:
            bindings = m.test_fixture_bindings.setdefault(test, {})
            layers = [*base, *(info["fixtures"][scope[:depth]] for depth in range(1, len(scope) + 1))]
            registry = defaultdict(list)
            auto = set()
            for layer in layers:
                for name, fixture in layer.items():
                    registry[name].append(fixture)
                    if fixture.autouse:
                        auto.add(name)
            pending = [(name, ()) for name in (*requests, *sorted(auto)) if name not in direct]
            visited = set()
            while pending:
                name, chain = pending.pop()
                fixture = next((item for item in reversed(registry.get(name, ())) if item.nid not in chain), None)
                if not fixture:
                    continue
                bindings.setdefault(name, fixture.nid)
                if fixture.nid in visited:
                    continue
                visited.add(fixture.nid)
                pending.extend((dependency, (*chain, fixture.nid)) for dependency in fixture.dependencies)
                if fixture.nid not in target_cache:
                    target_cache[fixture.nid] = targets(fixture)
                for dst, confidence in target_cache[fixture.nid].items():
                    add(test, dst, "tests", "treesitter", confidence, {"via": "fixture", "fixture": fixture.nid})

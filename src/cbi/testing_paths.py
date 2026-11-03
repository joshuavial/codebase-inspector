"""Bounded Python test paths and dynamic imports, interpreted as syntax only."""

import ast
import posixpath
from dataclasses import dataclass

from cbi.testing_static import owner, python_modules


@dataclass(frozen=True)
class PathValue:
    path: str
    anchored: bool = False


@dataclass(frozen=True)
class GlobValue:
    base: PathValue
    pattern: str
    recursive: bool = False


def dotted(node, aliases):
    if isinstance(node, ast.Name):
        return aliases.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        base = dotted(node.value, aliases)
        return f"{base}.{node.attr}" if base else None
    return None


def evaluate(node, values, aliases, own):
    """A literal value/path or None. Unknown code is never evaluated."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (str, int)):
        return node.value
    if isinstance(node, ast.Name):
        return PathValue(own, True) if node.id == "__file__" else values.get(node.id)
    if isinstance(node, (ast.Tuple, ast.List)):
        return tuple(evaluate(item, values, aliases, own) for item in node.elts)
    if isinstance(node, ast.JoinedStr):
        parts = [evaluate(item.value if isinstance(item, ast.FormattedValue) else item,
                          values, aliases, own) for item in node.values]
        return "".join(parts) if all(isinstance(part, str) for part in parts) else None
    if isinstance(node, ast.BinOp):
        left = evaluate(node.left, values, aliases, own)
        right = evaluate(node.right, values, aliases, own)
        if isinstance(node.op, ast.Add) and isinstance(left, str) and isinstance(right, str):
            return left + right
        if isinstance(node.op, ast.Div) and isinstance(left, PathValue) and isinstance(right, str):
            return PathValue(posixpath.normpath(posixpath.join(left.path, right)), left.anchored)
    if isinstance(node, ast.Attribute) and node.attr == "parent":
        base = evaluate(node.value, values, aliases, own)
        if isinstance(base, PathValue):
            return PathValue(posixpath.dirname(base.path), base.anchored)
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute) and node.value.attr == "parents":
        base = evaluate(node.value.value, values, aliases, own)
        index = evaluate(node.slice, values, aliases, own)
        if isinstance(base, PathValue) and isinstance(index, int) and 0 <= index <= 100:
            for _ in range(index + 1):
                base = PathValue(posixpath.dirname(base.path), base.anchored)
            return base
    if not isinstance(node, ast.Call):
        return None
    name = dotted(node.func, aliases)
    args = [evaluate(arg, values, aliases, own) for arg in node.args]
    if name in {"pathlib.Path", "pathlib.PurePath", "pathlib.PurePosixPath"} and args:
        base = args[0] if isinstance(args[0], PathValue) else PathValue(args[0]) if isinstance(args[0], str) else None
        if base and all(isinstance(arg, str) for arg in args[1:]):
            return PathValue(posixpath.normpath(posixpath.join(base.path, *args[1:])), base.anchored)
    if name in {"str", "os.fspath"} and len(args) == 1:
        return args[0]
    if name in {"os.path.join", "posixpath.join"} and args:
        if all(isinstance(arg, (str, PathValue)) for arg in args):
            return PathValue(posixpath.normpath(posixpath.join(*[arg.path if isinstance(arg, PathValue) else arg for arg in args])),
                             isinstance(args[0], PathValue) and args[0].anchored)
    if name in {"os.path.dirname", "posixpath.dirname"} and len(args) == 1:
        arg = args[0]
        if isinstance(arg, (str, PathValue)):
            return PathValue(posixpath.dirname(arg.path if isinstance(arg, PathValue) else arg),
                             isinstance(arg, PathValue) and arg.anchored)
    if isinstance(node.func, ast.Attribute):
        base = evaluate(node.func.value, values, aliases, own)
        if isinstance(base, PathValue):
            if node.func.attr in {"resolve", "absolute"} and not args:
                return base
            if node.func.attr == "joinpath" and args and all(isinstance(arg, str) for arg in args):
                return PathValue(posixpath.normpath(posixpath.join(base.path, *args)), base.anchored)
            if node.func.attr in {"glob", "rglob"} and len(args) == 1 and isinstance(args[0], str):
                return GlobValue(base, args[0], node.func.attr == "rglob")
    return None


@dataclass
class Context:
    model: object
    fid: str
    call: ast.Call
    values: dict
    aliases: dict

    def value(self, node):
        return evaluate(node, self.values, self.aliases, self.model.files[self.fid][1])

    def name(self, node=None):
        return dotted(self.call.func if node is None else node, self.aliases)

    def target(self, value):
        if isinstance(value, PathValue):
            if value.anchored:
                return self.model.by_path[self.model.files[self.fid][0]].get(value.path)
            value = value.path
        return self.model.read_target(self.fid, value) if isinstance(value, str) and value else None

    def owner(self):
        return self.model.test_owner(owner(self.model, self.fid, self.call))


def _assigned(node):
    """Names local to a function; do not walk into a nested scope."""
    found = set()
    stack = list(ast.iter_child_nodes(node))
    while stack:
        child = stack.pop()
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            found.add(child.name)
            continue
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
            found.add(child.id)
        elif isinstance(child, ast.Import):
            found.update(alias.asname or alias.name.split(".")[0] for alias in child.names)
        elif isinstance(child, ast.ImportFrom):
            found.update(alias.asname or alias.name for alias in child.names)
        elif isinstance(child, ast.ExceptHandler) and child.name:
            found.add(child.name)
        elif isinstance(child, (ast.MatchAs, ast.MatchStar)) and child.name:
            found.add(child.name)
        elif isinstance(child, ast.MatchMapping) and child.rest:
            found.add(child.rest)
        if not isinstance(child, ast.Lambda):
            stack.extend(ast.iter_child_nodes(child))
    return found


def contexts(model, file_ids=None):
    """Call contexts in Python tests and optional registered helpers, with lexical bindings."""
    additional = set(file_ids or ())
    for fid, module in python_modules(model).items():
        if model.files[fid][2] != "test" and fid not in additional:
            continue
        own = model.files[fid][1]

        def walk(node, values, aliases):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                values, aliases = dict(values), dict(aliases)
                arguments = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
                arguments += [arg for arg in (node.args.vararg, node.args.kwarg) if arg]
                for name in _assigned(node) | {arg.arg for arg in arguments}:
                    values.pop(name, None)
                    aliases[name] = None
                body = [node.body] if isinstance(node, ast.Lambda) else node.body
                for child in body:
                    yield from walk(child, values, aliases)
                return
            if isinstance(node, ast.ClassDef):
                for child in node.body:
                    yield from walk(child, dict(values), dict(aliases))
                return
            if isinstance(node, ast.Import):
                for item in node.names:
                    aliases[item.asname or item.name.split(".")[0]] = item.name if item.asname else item.name.split(".")[0]
                return
            if isinstance(node, ast.ImportFrom):
                for item in node.names:
                    aliases[item.asname or item.name] = f"{node.module}.{item.name}"
                return
            if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                value_node = node.value
                if value_node:
                    yield from walk(value_node, values, aliases)
                value = evaluate(value_node, values, aliases, own)
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    for part in ast.walk(target):
                        if isinstance(part, ast.Name):
                            values[part.id] = value if not isinstance(node, ast.AugAssign) else None
                            aliases[part.id] = None
                return
            if isinstance(node, (ast.For, ast.AsyncFor)):
                yield from walk(node.iter, values, aliases)
                value = evaluate(node.iter, values, aliases, own)
                choices = value if isinstance(value, tuple) else (value,)
                for choice in choices[:100]:
                    inner, names = dict(values), dict(aliases)
                    for part in ast.walk(node.target):
                        if isinstance(part, ast.Name):
                            inner[part.id], names[part.id] = choice, None
                    for child in node.body:
                        yield from walk(child, inner, names)
                for child in node.orelse:
                    yield from walk(child, dict(values), dict(aliases))
                for name in _assigned(node):
                    values.pop(name, None)
                    aliases[name] = None
                return
            if isinstance(node, (ast.With, ast.AsyncWith)):
                inner, names = dict(values), dict(aliases)
                for item in node.items:
                    yield from walk(item.context_expr, inner, names)
                    if item.optional_vars:
                        for target in ast.walk(item.optional_vars):
                            if isinstance(target, ast.Name) and isinstance(target.ctx, ast.Store):
                                inner.pop(target.id, None)
                                names[target.id] = None
                for child in node.body:
                    yield from walk(child, inner, names)
                for name in _assigned(node):
                    values.pop(name, None)
                    aliases[name] = None
                return
            if isinstance(node, (ast.Try, ast.TryStar)):
                # Handler, else and finally regions may observe any preceding
                # write, including one that happened before an exception.
                inner, names = dict(values), dict(aliases)
                for child in node.body:
                    yield from walk(child, inner, names)
                written = _assigned(node)
                regions = [(handler.type, handler.body) for handler in node.handlers]
                regions += [(None, node.orelse), (None, node.finalbody)]
                for exception_type, body in regions:
                    inner, names = dict(values), dict(aliases)
                    for name in written:
                        inner.pop(name, None)
                        names[name] = None
                    if exception_type:
                        yield from walk(exception_type, inner, names)
                    for child in body:
                        yield from walk(child, inner, names)
                for name in written:
                    values.pop(name, None)
                    aliases[name] = None
                return
            if isinstance(node, ast.Match):
                yield from walk(node.subject, values, aliases)
                for case in node.cases:
                    inner, names = dict(values), dict(aliases)
                    captures = set()
                    for pattern in ast.walk(case.pattern):
                        if isinstance(pattern, (ast.MatchAs, ast.MatchStar)) and pattern.name:
                            captures.add(pattern.name)
                        elif isinstance(pattern, ast.MatchMapping) and pattern.rest:
                            captures.add(pattern.rest)
                    for name in captures:
                        inner.pop(name, None)
                        names[name] = None
                    if case.guard:
                        yield from walk(case.guard, inner, names)
                    for child in case.body:
                        yield from walk(child, inner, names)
                for name in _assigned(node):
                    values.pop(name, None)
                    aliases[name] = None
                return
            if isinstance(node, (ast.If, ast.While)):
                # Conditional writes cannot become unconditional literal facts.
                for _field, children in ast.iter_fields(node):
                    inner, names = dict(values), dict(aliases)
                    if isinstance(children, list):
                        for child in children:
                            if isinstance(child, ast.AST):
                                yield from walk(child, inner, names)
                    elif isinstance(children, ast.AST):
                        yield from walk(children, inner, names)
                for name in _assigned(node):
                    values.pop(name, None)
                    aliases[name] = None
                return
            if isinstance(node, ast.Call):
                yield Context(model, fid, node, dict(values), dict(aliases))
            for child in ast.iter_child_nodes(node):
                yield from walk(child, values, aliases)

        yield from walk(module, {}, {})


def read_value(context):
    call, name = context.call, context.name()
    if name in {"open", "io.open"} and call.args:
        return context.value(call.args[0]), "file_read"
    if name == "importlib.util.spec_from_file_location" and len(call.args) >= 2:
        return context.value(call.args[1]), "dynamic_import_path"
    if name == "runpy.run_path" and call.args:
        return context.value(call.args[0]), "dynamic_import_path"
    if isinstance(call.func, ast.Attribute) and call.func.attr in {"read_text", "read_bytes", "open"}:
        base = context.value(call.func.value)
        if isinstance(base, (PathValue, GlobValue)) or call.func.attr in {"read_text", "read_bytes"}:
            return base, "file_read"
    return None, None


def resolve_target(context):
    """Return (tracked target, mechanism, abstract value) without emitting edges."""
    call, name = context.call, context.name()
    value, mechanism = read_value(context)
    dst = None
    if name in {"importlib.import_module", "runpy.run_module"} and call.args:
        value = context.value(call.args[0])
        mechanism = "dynamic_import"
        if isinstance(value, str) and value and not value.startswith("."):
            dst = context.model.spec(context.fid, value)
        elif isinstance(value, str) and value.startswith("."):
            package = context.value(call.args[1]) if len(call.args) > 1 else next(
                (context.value(kw.value) for kw in call.keywords if kw.arg == "package"), None)
            if isinstance(package, str):
                parts = package.split(".")
                dots = len(value) - len(value.lstrip("."))
                if dots <= len(parts):
                    dst = context.model.spec(context.fid, ".".join(parts[:len(parts) - dots + 1]) + value[dots - 1:])
    elif mechanism and not isinstance(value, GlobValue):
        dst = context.target(value)
    return dst, mechanism, value


def link(model, edges, add):
    diagnostics = set()
    for context in contexts(model):
        call = context.call
        dst, mechanism, value = resolve_target(context)
        if dst and dst != context.fid:
            src = context.owner()
            existing = edges.get((src, dst, "tests", "treesitter"))
            if not existing or existing[0] < 1.0:
                add(src, dst, "tests", "treesitter", 1.0, {"via": mechanism})
        elif mechanism and not isinstance(value, GlobValue):
            path = model.files[context.fid][1]
            detail = f"{path}:{call.lineno}:{call.col_offset + 1}: {mechanism}: target is dynamic, external or absent from tracked files"
            diagnostics.add((context.fid, "unsupported_test_mechanism", detail))
    return sorted(diagnostics)

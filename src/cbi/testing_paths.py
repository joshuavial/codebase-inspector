"""Bounded Python test paths and dynamic imports, interpreted as syntax only."""

import ast
import posixpath
from dataclasses import dataclass

from cbi.testing_static import owner, python_modules

MAX_CONTEXT_EXPANSIONS = 64


@dataclass(frozen=True)
class PathValue:
    path: str
    anchored: bool = False
    scratch: bool = False
    fixture: bool = False


FIXTURE_DIRS = {"fixtures", "test-data", "test_data", "golden"}


def _is_fixture_path(val):
    path = val.path if isinstance(val, PathValue) else val if isinstance(val, str) else None
    if path is None:
        return False
    parts = [p for p in path.replace("\\", "/").split("/") if p]
    if not parts:
        return False
    has_fixture_dir = any(p in FIXTURE_DIRS for p in parts)
    if not has_fixture_dir:
        return False
    if isinstance(val, PathValue) and val.anchored:
        return True
    return parts[0] in {"tests", "test"}


TEMPORARY_FIXTURES = {
    "tmp_path",
    "tmpdir",
    "make_repo",
    "repo",
    "tmp_path_factory",
}

TEMPORARY_CALLS = {
    "mkdtemp",
    "tempfile.mkdtemp",
    "TemporaryDirectory",
    "tempfile.TemporaryDirectory",
    "NamedTemporaryFile",
    "tempfile.NamedTemporaryFile",
    "mkstemp",
    "tempfile.mkstemp",
}


@dataclass(frozen=True)
class GlobValue:

    base: PathValue
    pattern: str
    recursive: bool = False


def dotted(node, aliases):
    if isinstance(node, ast.Name):
        return aliases.get(node.id) or node.id
    if isinstance(node, ast.Attribute):
        base = dotted(node.value, aliases)
        return f"{base}.{node.attr}" if base else None
    return None


def evaluate(node, values, aliases, own):
    """A literal value/path or None. Unknown code is never evaluated."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (str, bytes, int)):
        return node.value
    if isinstance(node, ast.Name):
        if node.id == "__file__":
            return PathValue(own, True, fixture=_is_fixture_path(own))
        if node.id in values:
            return values[node.id]
        if node.id in TEMPORARY_FIXTURES:
            return PathValue(f"<{node.id}>", False, scratch=True)
        if dotted(node, aliases) == "sys.executable":
            return "sys.executable"
        return None
    if isinstance(node, (ast.Tuple, ast.List)):
        return tuple(evaluate(item, values, aliases, own) for item in node.elts)
    if isinstance(node, ast.Dict) and not node.keys:
        return ()
    if isinstance(node, ast.JoinedStr):
        parts = [evaluate(item.value if isinstance(item, ast.FormattedValue) else item,
                          values, aliases, own) for item in node.values]
        return "".join(parts) if all(isinstance(part, str) for part in parts) else None
    if isinstance(node, ast.BinOp):
        left = evaluate(node.left, values, aliases, own)
        right = evaluate(node.right, values, aliases, own)
        if isinstance(node.op, ast.Add) and isinstance(left, str) and isinstance(right, str):
            return left + right
        if isinstance(node.op, ast.Div) and isinstance(left, PathValue):
            if isinstance(right, str):
                new_path = posixpath.normpath(posixpath.join(left.path, right))
                fixture = left.fixture or _is_fixture_path(new_path)
                return PathValue(new_path, left.anchored, left.scratch, fixture=fixture)
            elif left.scratch:
                return PathValue(posixpath.normpath(posixpath.join(left.path, "<dynamic>")), False, True, False)
            elif left.fixture:
                return PathValue(posixpath.normpath(posixpath.join(left.path, "<dynamic>")), False, False, True)
    if isinstance(node, ast.Attribute):
        if dotted(node, aliases) == "sys.executable":
            return "sys.executable"
        if node.attr == "parent":
            base = evaluate(node.value, values, aliases, own)
            if isinstance(base, PathValue):
                new_path = posixpath.dirname(base.path)
                return PathValue(new_path, base.anchored, base.scratch, fixture=base.fixture or _is_fixture_path(new_path))
    if isinstance(node, ast.Subscript):
        if isinstance(node.value, ast.Attribute) and node.value.attr == "parents":
            base = evaluate(node.value.value, values, aliases, own)
            index = evaluate(node.slice, values, aliases, own)
            if isinstance(base, PathValue) and isinstance(index, int) and 0 <= index <= 100:
                for _ in range(index + 1):
                    new_path = posixpath.dirname(base.path)
                    base = PathValue(new_path, base.anchored, base.scratch, fixture=base.fixture or _is_fixture_path(new_path))
                return base
        base = evaluate(node.value, values, aliases, own)
        index = evaluate(node.slice, values, aliases, own)
        if isinstance(base, (tuple, list)) and isinstance(index, int) and 0 <= index < len(base):
            return base[index]
    if not isinstance(node, ast.Call):
        return None
    name = dotted(node.func, aliases)
    args = [evaluate(arg, values, aliases, own) for arg in node.args]
    if name in TEMPORARY_CALLS or (name in values and getattr(values[name], "scratch", False)):
        return PathValue(f"<{name}>", False, scratch=True)
    if name in values and isinstance(values[name], tuple) and any(getattr(x, "scratch", False) for x in values[name]):
        return values[name]
    if isinstance(node.func, ast.Attribute) and node.func.attr in {"mkdtemp", "mkstemp", "TemporaryDirectory", "NamedTemporaryFile"}:
        return PathValue(f"<{node.func.attr}>", False, scratch=True)
    if name in {"Path", "pathlib.Path", "PurePath", "pathlib.PurePath", "PurePosixPath", "pathlib.PurePosixPath"} and args:
        base = args[0] if isinstance(args[0], PathValue) else PathValue(args[0], fixture=_is_fixture_path(args[0])) if isinstance(args[0], str) else None
        if base and all(isinstance(arg, str) for arg in args[1:]):
            new_path = posixpath.normpath(posixpath.join(base.path, *args[1:]))
            fixture = base.fixture or _is_fixture_path(new_path)
            return PathValue(new_path, base.anchored, base.scratch, fixture=fixture)
        elif base and base.scratch:
            return PathValue(posixpath.normpath(posixpath.join(base.path, "<dynamic>")), False, True, False)
        elif base and base.fixture:
            return PathValue(posixpath.normpath(posixpath.join(base.path, "<dynamic>")), False, False, True)
    if name in {"str", "os.fspath"} and len(args) == 1:
        return args[0]
    if name in {"os.path.join", "posixpath.join"} and args:
        if all(isinstance(arg, (str, PathValue)) for arg in args):
            scratch = any(getattr(arg, "scratch", False) for arg in args)
            fixture = any(getattr(arg, "fixture", False) or _is_fixture_path(arg.path if isinstance(arg, PathValue) else arg) for arg in args)
            return PathValue(posixpath.normpath(posixpath.join(*[arg.path if isinstance(arg, PathValue) else arg for arg in args])),
                             isinstance(args[0], PathValue) and args[0].anchored,
                             scratch=scratch,
                             fixture=fixture)
    if name in {"os.path.dirname", "posixpath.dirname"} and len(args) == 1:
        arg = args[0]
        if isinstance(arg, (str, PathValue)):
            scratch = getattr(arg, "scratch", False) if isinstance(arg, PathValue) else False
            fixture = getattr(arg, "fixture", False) if isinstance(arg, PathValue) else False
            new_path = posixpath.dirname(arg.path if isinstance(arg, PathValue) else arg)
            return PathValue(new_path,
                             isinstance(arg, PathValue) and arg.anchored,
                             scratch=scratch,
                             fixture=fixture or _is_fixture_path(new_path))
    if isinstance(node.func, ast.Attribute):
        base = evaluate(node.func.value, values, aliases, own)
        if isinstance(base, PathValue):
            if node.func.attr in {"resolve", "absolute"} and not args:
                return base
            if node.func.attr == "with_name" and len(args) == 1 and isinstance(args[0], str):
                new_path = posixpath.normpath(posixpath.join(posixpath.dirname(base.path), args[0]))
                return PathValue(new_path, base.anchored, base.scratch, fixture=base.fixture or _is_fixture_path(new_path))
            if node.func.attr == "with_suffix" and len(args) == 1 and isinstance(args[0], str):
                new_path = posixpath.splitext(base.path)[0] + args[0]
                return PathValue(new_path, base.anchored, base.scratch, fixture=base.fixture or _is_fixture_path(new_path))
            if node.func.attr == "joinpath" and args and all(isinstance(arg, str) for arg in args):
                new_path = posixpath.normpath(posixpath.join(base.path, *args))
                return PathValue(new_path, base.anchored, base.scratch, fixture=base.fixture or _is_fixture_path(new_path))
            if node.func.attr in {"glob", "rglob"} and len(args) == 1 and isinstance(args[0], str):
                return GlobValue(base, args[0], node.func.attr == "rglob")
            if node.func.attr == "iterdir" and not args:
                return GlobValue(base, "*", False)
    if name in {"team._store", "_store", "cbi.team._store"} and args and getattr(args[0], "scratch", False):
        return (PathValue(posixpath.normpath(posixpath.join(args[0].path, "answers.jsonl")), False, scratch=True), 1, True)
    if name in {"build.build", "cbi.build.build"}:
        out_val = None
        if len(args) >= 2:
            out_val = args[1]
        for kw in node.keywords:
            if kw.arg == "out":
                out_val = evaluate(kw.value, values, aliases, own)
        if isinstance(out_val, PathValue) and out_val.scratch:
            return PathValue(posixpath.normpath(posixpath.join(out_val.path, "index.html")), False, scratch=True)
    if name in {"render.viewer_png", "cbi.render.viewer_png"}:
        png_val = None
        if len(args) >= 3:
            png_val = args[2]
        for kw in node.keywords:
            if kw.arg == "png":
                png_val = evaluate(kw.value, values, aliases, own)
        if isinstance(png_val, PathValue) and png_val.scratch:
            return png_val
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


def _find_returns(block):
    stack = list(block)
    returns = []
    while stack:
        curr = stack.pop()
        if isinstance(curr, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        if isinstance(curr, (ast.Return, ast.Yield, ast.YieldFrom)) and curr.value:
            returns.append(curr.value)
        stack.extend(ast.iter_child_nodes(curr))
    return returns


SCRATCH_CONSTRUCTORS = {
    "make_repo",
    "create_repo",
    "make_test_repo",
    "setup_repo",
    "mkdtemp",
    "mkstemp",
    "TemporaryDirectory",
    "NamedTemporaryFile",
}


def _is_scratch_expr(expr, local_scratch, fn_returns, scratch_callables):
    if isinstance(expr, ast.Name):
        return expr.id in local_scratch
    if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Div):
        return _is_scratch_expr(expr.left, local_scratch, fn_returns, scratch_callables)
    if isinstance(expr, ast.Call):
        cname = dotted(expr.func, {})
        base_name = cname.split(".")[-1] if cname else ""
        if cname in scratch_callables or base_name in scratch_callables:
            return True
        if cname in fn_returns or base_name in fn_returns:
            ret = fn_returns.get(cname) or fn_returns.get(base_name)
            if getattr(ret, "scratch", False):
                return True
            if isinstance(ret, tuple) and any(getattr(x, "scratch", False) for x in ret):
                return True
        if isinstance(expr.func, ast.Attribute):
            if expr.func.attr in {"resolve", "absolute", "parent"} and _is_scratch_expr(expr.func.value, local_scratch, fn_returns, scratch_callables):
                return True
            if expr.func.attr == "mktemp" and _is_scratch_expr(expr.func.value, local_scratch, fn_returns, scratch_callables):
                return True
        if cname in {"Path", "pathlib.Path", "PurePath", "pathlib.PurePath", "PurePosixPath", "pathlib.PurePosixPath"} and expr.args:
            return _is_scratch_expr(expr.args[0], local_scratch, fn_returns, scratch_callables)
        if cname in {"team._store", "_store", "cbi.team._store"} and expr.args:
            return _is_scratch_expr(expr.args[0], local_scratch, fn_returns, scratch_callables)
        if cname in {"build.build", "cbi.build.build"}:
            out_arg = expr.args[1] if len(expr.args) >= 2 else None
            for kw in expr.keywords:
                if kw.arg == "out":
                    out_arg = kw.value
            if out_arg and _is_scratch_expr(out_arg, local_scratch, fn_returns, scratch_callables):
                return True
        if cname in {"render.viewer_png", "cbi.render.viewer_png"}:
            png_arg = expr.args[2] if len(expr.args) >= 3 else None
            for kw in expr.keywords:
                if kw.arg == "png":
                    png_arg = kw.value
            if png_arg and _is_scratch_expr(png_arg, local_scratch, fn_returns, scratch_callables):
                return True
    return False


def _analyze_module_fixtures_and_helpers(module):
    """Detect module-level fixtures and helpers that construct scratch repositories."""
    scratch_callables = set(TEMPORARY_FIXTURES) | set(TEMPORARY_CALLS) | SCRATCH_CONSTRUCTORS
    fn_returns = {}

    for _pass in range(3):
        for stmt in module.body:
            if not isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            fn_name = stmt.name
            args = [a.arg for a in stmt.args.args + stmt.args.posonlyargs + stmt.args.kwonlyargs]
            local_scratch = {arg for arg in args if arg in scratch_callables}

            for _sub in range(2):
                for node in ast.walk(stmt):
                    if isinstance(node, (ast.Assign, ast.AnnAssign)):
                        val = node.value
                        if val is None:
                            continue
                        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                        cname = dotted(val.func, {}) if isinstance(val, ast.Call) else None
                        ret_val = (fn_returns.get(cname) or fn_returns.get(cname.split(".")[-1])) if cname else None
                        if cname in {"team._store", "_store", "cbi.team._store"} and val.args and _is_scratch_expr(val.args[0], local_scratch, fn_returns, scratch_callables):
                            ret_val = (PathValue("<answers.jsonl>", False, scratch=True), None, None)
                        if isinstance(ret_val, tuple):
                            for target in targets:
                                if isinstance(target, (ast.Tuple, ast.List)):
                                    for sub_t, sub_v in zip(target.elts, ret_val):
                                        if getattr(sub_v, "scratch", False):
                                            for part in ast.walk(sub_t):
                                                if isinstance(part, ast.Name):
                                                    local_scratch.add(part.id)
                        elif _is_scratch_expr(val, local_scratch, fn_returns, scratch_callables):
                            for target in targets:
                                for part in ast.walk(target):
                                    if isinstance(part, ast.Name):
                                        local_scratch.add(part.id)
                    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node is not stmt:
                        for sub_val in _find_returns(node.body):
                            if _is_scratch_expr(sub_val, local_scratch, fn_returns, scratch_callables):
                                local_scratch.add(node.name)

            for val in _find_returns(stmt.body):
                if isinstance(val, (ast.Tuple, ast.List)):
                    elts = []
                    has_scratch = False
                    for i, elt in enumerate(val.elts):
                        if _is_scratch_expr(elt, local_scratch, fn_returns, scratch_callables):
                            has_scratch = True
                            elts.append(PathValue(f"<{fn_name}[{i}]>", False, scratch=True))
                        else:
                            elts.append(None)
                    if has_scratch:
                        fn_returns[fn_name] = tuple(elts)
                        scratch_callables.add(fn_name)
                elif _is_scratch_expr(val, local_scratch, fn_returns, scratch_callables):
                    fn_returns[fn_name] = PathValue(f"<{fn_name}>", False, scratch=True)
                    scratch_callables.add(fn_name)

    return fn_returns


def contexts(model, file_ids=None):
    """Call contexts in Python tests and optional registered helpers, with lexical bindings."""
    additional = set(file_ids or ())
    if not hasattr(model, "_test_path_contexts"):
        model._test_path_contexts = {}
        model._test_path_budget = MAX_CONTEXT_EXPANSIONS
        model._test_path_limits = set()
    if not hasattr(model, "_test_written_paths"):
        model._test_written_paths = {}
    cache = model._test_path_contexts
    for fid, module in sorted(python_modules(model).items()):
        if model.files[fid][2] != "test" and fid not in additional:
            continue
        if fid in cache:
            yield from cache[fid]
            continue
        own = model.files[fid][1]
        file_written = model._test_written_paths.setdefault(fid, set())
        module_scratch = _analyze_module_fixtures_and_helpers(module)

        def boundary(node, mechanism):
            model._test_path_limits.add((fid, node, mechanism))

        def walk(node, values, aliases):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                values, aliases = dict(values), dict(aliases)
                arguments = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
                arguments += [arg for arg in (node.args.vararg, node.args.kwarg) if arg]
                for name in _assigned(node) | {arg.arg for arg in arguments}:
                    values.pop(name, None)
                    aliases[name] = None
                for arg in arguments:
                    if arg.arg in TEMPORARY_FIXTURES:
                        values[arg.arg] = PathValue(f"<{arg.arg}>", anchored=False, scratch=True)
                    elif arg.arg in module_scratch:
                        values[arg.arg] = module_scratch[arg.arg]
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

                def _bind_target(tgt, val):
                    if isinstance(tgt, (ast.Tuple, ast.List)):
                        if isinstance(val, (tuple, list)) and len(tgt.elts) == len(val):
                            for sub_tgt, sub_val in zip(tgt.elts, val):
                                _bind_target(sub_tgt, sub_val)
                            return
                        if getattr(val, "scratch", False):
                            for i, sub_tgt in enumerate(tgt.elts):
                                sub_val = PathValue(f"<{val.path}[{i}]>", False, scratch=True) if (i == 0 or (isinstance(sub_tgt, ast.Name) and any(k in sub_tgt.id for k in ("path", "root", "file", "dir")))) else None
                                _bind_target(sub_tgt, sub_val)
                            return
                    elif isinstance(tgt, ast.Name):
                        values[tgt.id] = val if not isinstance(node, ast.AugAssign) else None
                        aliases[tgt.id] = None
                    else:
                        for part in ast.walk(tgt):
                            if isinstance(part, ast.Name):
                                values.pop(part.id, None)
                                aliases[part.id] = None

                for target in targets:
                    _bind_target(target, value)
                return
            if isinstance(node, ast.NamedExpr):
                # Guard assignments execute before the selected body, but a
                # conditional value is not an unconditional path literal.
                yield from walk(node.value, values, aliases)
                for target in ast.walk(node.target):
                    if isinstance(target, ast.Name):
                        values.pop(target.id, None)
                        aliases[target.id] = None
                return
            if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
                inner, names = dict(values), dict(aliases)
                for gen in node.generators:
                    yield from walk(gen.iter, inner, names)
                    iter_val = evaluate(gen.iter, inner, names, own)
                    item_val = None
                    if isinstance(iter_val, GlobValue):
                        base = iter_val.base
                        item_val = PathValue(posixpath.normpath(posixpath.join(base.path, "<item>")),
                                             anchored=base.anchored, scratch=base.scratch, fixture=base.fixture)
                    for part in ast.walk(gen.target):
                        if isinstance(part, ast.Name):
                            inner[part.id] = item_val
                            names[part.id] = None
                    for if_clause in gen.ifs:
                        yield from walk(if_clause, inner, names)
                if isinstance(node, ast.DictComp):
                    yield from walk(node.key, inner, names)
                    yield from walk(node.value, inner, names)
                else:
                    yield from walk(node.elt, inner, names)
                return
            if isinstance(node, (ast.For, ast.AsyncFor)):
                yield from walk(node.iter, values, aliases)
                value = evaluate(node.iter, values, aliases, own)
                if isinstance(value, (tuple, str, bytes)) and not value:
                    # An empty literal cannot enter its body or overwrite its target.
                    for child in node.orelse:
                        yield from walk(child, values, aliases)
                    return
                choices = value if isinstance(value, tuple) else (None,)
                guarded = any(isinstance(child, (ast.If, ast.IfExp, ast.While, ast.Match,
                    ast.Try, ast.TryStar, ast.Assert, ast.BoolOp, ast.Break, ast.Continue,
                    ast.Return, ast.Raise)) or isinstance(child, ast.comprehension) and child.ifs
                    for statement in node.body for child in ast.walk(statement))
                if guarded:
                    choices = (None,)
                    boundary(node, "guarded_loop")
                elif not isinstance(value, tuple):
                    boundary(node, "dynamic_loop")
                elif len(choices) > model._test_path_budget:
                    choices = (None,)
                    boundary(node, "expansion_limit")
                else:
                    model._test_path_budget -= len(choices)
                for choice in choices:
                    inner, names = dict(values), dict(aliases)
                    for part in ast.walk(node.target):
                        if isinstance(part, ast.Name):
                            inner[part.id], names[part.id] = choice, None
                    for child in node.body:
                        yield from walk(child, inner, names)
                after, after_names = dict(values), dict(aliases)
                for name in _assigned(node):
                    after.pop(name, None)
                    after_names[name] = None
                for child in node.orelse:
                    yield from walk(child, after, after_names)
                for name in _assigned(node):
                    values.pop(name, None)
                    aliases[name] = None
                return
            if isinstance(node, (ast.With, ast.AsyncWith)):
                inner, names = dict(values), dict(aliases)
                for item in node.items:
                    yield from walk(item.context_expr, inner, names)
                    if item.optional_vars:
                        ctx_val = evaluate(item.context_expr, inner, names, own)
                        for target in ast.walk(item.optional_vars):
                            if isinstance(target, ast.Name) and isinstance(target.ctx, ast.Store):
                                inner[target.id] = ctx_val
                                names[target.id] = None
                for child in node.body:
                    yield from walk(child, inner, names)
                for name in _assigned(node):
                    values.pop(name, None)
                    aliases[name] = None
                return
            if isinstance(node, (ast.Try, ast.TryStar)):
                if not node.handlers:
                    for child in node.body:
                        yield from walk(child, values, aliases)
                    if node.finalbody:
                        for child in node.finalbody:
                            yield from walk(child, values, aliases)
                    return
                # Handler, else and finally regions may observe any preceding
                # write, including one that happened before an exception.
                inner, names = dict(values), dict(aliases)
                for child in node.body:
                    yield from walk(child, inner, names)
                try_written = _assigned(node)
                regions = [(handler.type, handler.body) for handler in node.handlers]
                regions += [(None, node.orelse), (None, node.finalbody)]
                for exception_type, body in regions:
                    inner, names = dict(values), dict(aliases)
                    for name in try_written:
                        inner.pop(name, None)
                        names[name] = None
                    if exception_type:
                        yield from walk(exception_type, inner, names)
                    for child in body:
                        yield from walk(child, inner, names)
                for name in try_written:
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
            if isinstance(node, ast.While):
                guard_writes = _assigned(node.test)
                for field, children in ast.iter_fields(node):
                    inner, names = dict(values), dict(aliases)
                    if field != "test":
                        for name in guard_writes:
                            inner.pop(name, None)
                            names[name] = None
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
            if isinstance(node, ast.If):
                guard_writes = _assigned(node.test)
                test_values, test_aliases = dict(values), dict(aliases)
                yield from walk(node.test, test_values, test_aliases)

                body_values, body_aliases = dict(values), dict(aliases)
                for name in guard_writes:
                    body_values.pop(name, None)
                    body_aliases[name] = None
                for child in node.body:
                    yield from walk(child, body_values, body_aliases)

                if node.orelse:
                    orelse_values, orelse_aliases = dict(values), dict(aliases)
                    for name in guard_writes:
                        orelse_values.pop(name, None)
                        orelse_aliases[name] = None
                    for child in node.orelse:
                        yield from walk(child, orelse_values, orelse_aliases)

                    for name in _assigned(node):
                        b_val = body_values.get(name)
                        o_val = orelse_values.get(name)
                        if getattr(b_val, "scratch", False) and getattr(o_val, "scratch", False):
                            values[name] = PathValue(f"<{name}>", False, scratch=True)
                            aliases[name] = None
                        elif getattr(b_val, "fixture", False) and getattr(o_val, "fixture", False):
                            values[name] = PathValue(f"<{name}>", False, fixture=True)
                            aliases[name] = None
                        else:
                            values.pop(name, None)
                            aliases[name] = None
                else:
                    for name in _assigned(node):
                        values.pop(name, None)
                        aliases[name] = None
                return
            if isinstance(node, ast.Call):
                _track_write(node, values, aliases, own, file_written)
                yield Context(model, fid, node, dict(values), dict(aliases))
            for child in ast.iter_child_nodes(node):
                yield from walk(child, values, aliases)

        cache[fid] = tuple(walk(module, dict(module_scratch), {}))
        yield from cache[fid]


def _is_write_mode(mode):
    if isinstance(mode, (str, bytes)):
        text = mode.decode() if isinstance(mode, bytes) else mode
        return any(c in text for c in ("w", "a", "x"))
    return False


def _extract_mode_from_call(call, values, aliases, own, is_method=False):
    for kw in call.keywords:
        if kw.arg == "mode":
            return evaluate(kw.value, values, aliases, own)
    args = call.args if is_method else call.args[1:]
    if args:
        return evaluate(args[0], values, aliases, own)
    return "r"


def _track_write(call, values, aliases, own, written):
    target = None
    if isinstance(call.func, ast.Attribute) and call.func.attr in {"write_text", "write_bytes"}:
        target = call.func.value
    elif isinstance(call.func, ast.Attribute) and call.func.attr == "open":
        mode = _extract_mode_from_call(call, values, aliases, own, is_method=True)
        if _is_write_mode(mode):
            target = call.func.value
    else:
        name = dotted(call.func, aliases)
        if name in {"open", "io.open"} and call.args:
            mode = _extract_mode_from_call(call, values, aliases, own, is_method=False)
            if _is_write_mode(mode):
                target = call.args[0]
        elif name in {"render.viewer_png", "cbi.render.viewer_png"}:
            if len(call.args) >= 3:
                target = call.args[2]
            for kw in call.keywords:
                if kw.arg == "png":
                    target = kw.value
    if target is not None:
        try:
            written.add(ast.unparse(target))
        except Exception:
            pass
        val = evaluate(target, values, aliases, own)
        if isinstance(val, PathValue):
            written.add(val.path)
        elif isinstance(val, str):
            written.add(val)
        if isinstance(target, ast.Name):
            written.add(target.id)
            values[target.id] = PathValue(target.id, anchored=False, scratch=True)


def _open_mode(call, context, is_method=False):
    for kw in call.keywords:
        if kw.arg == "mode":
            return context.value(kw.value)
    args = call.args if is_method else call.args[1:]
    if args:
        return context.value(args[0])
    return "r"


def _is_scratch_read(context, target_node):
    written = getattr(context.model, "_test_written_paths", {}).get(context.fid, set())
    try:
        if ast.unparse(target_node) in written:
            return True
    except Exception:
        pass
    if isinstance(target_node, ast.Name):
        if target_node.id in written:
            return True
        val = context.values.get(target_node.id)
        if val is not None:
            return getattr(val, "scratch", False) or getattr(val, "fixture", False) or _is_fixture_path(val)
        if target_node.id in TEMPORARY_FIXTURES:
            return True
    curr = target_node
    while isinstance(curr, ast.BinOp) and isinstance(curr.op, ast.Div):
        curr = curr.left
    if isinstance(curr, ast.Name):
        if curr.id in written:
            return True
        val = context.values.get(curr.id)
        if val is not None:
            return getattr(val, "scratch", False) or getattr(val, "fixture", False) or _is_fixture_path(val)
        if curr.id in TEMPORARY_FIXTURES:
            return True
    if isinstance(curr, ast.Call):
        name = dotted(curr.func, context.aliases)
        if name in TEMPORARY_CALLS or (name in context.values and getattr(context.values[name], "scratch", False)):
            return True
        if name in {"Path", "pathlib.Path", "PurePath", "pathlib.PurePath", "PurePosixPath", "pathlib.PurePosixPath"} and curr.args:
            return _is_scratch_read(context, curr.args[0])
        if isinstance(curr.func, ast.Attribute) and curr.func.attr in {"mkdtemp", "mkstemp", "TemporaryDirectory", "NamedTemporaryFile"}:
            return True
    val = context.value(target_node)
    if isinstance(val, PathValue):
        if val.scratch or val.fixture or _is_fixture_path(val) or val.path in written:
            return True
    elif isinstance(val, str) and (val in written or _is_fixture_path(val)):
        return True
    return False


def read_value(context):
    call, name = context.call, context.name()
    if name in {"open", "io.open"} and call.args:
        mode = _open_mode(call, context, is_method=False)
        if _is_write_mode(mode):
            return None, None
        target_node = call.args[0]
        if _is_scratch_read(context, target_node):
            return None, None
        val = context.value(target_node)
        if getattr(val, "scratch", False) or getattr(val, "fixture", False) or _is_fixture_path(val):
            return None, None
        return val, "file_read"

    if name == "importlib.util.spec_from_file_location" and len(call.args) >= 2:
        return context.value(call.args[1]), "dynamic_import_path"
    if name == "runpy.run_path" and call.args:
        return context.value(call.args[0]), "dynamic_import_path"

    if isinstance(call.func, ast.Attribute) and call.func.attr == "open":
        mode = _open_mode(call, context, is_method=True)
        if _is_write_mode(mode):
            return None, None
        target_node = call.func.value
        if _is_scratch_read(context, target_node):
            return None, None
        base = context.value(target_node)
        if getattr(base, "scratch", False) or getattr(base, "fixture", False) or _is_fixture_path(base):
            return None, None
        return base, "file_read"

    if isinstance(call.func, ast.Attribute) and call.func.attr in {"read_text", "read_bytes"}:
        target_node = call.func.value
        if _is_scratch_read(context, target_node):
            return None, None
        base = context.value(target_node)
        if getattr(base, "scratch", False) or getattr(base, "fixture", False) or _is_fixture_path(base):
            return None, None
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
            if mechanism == "file_read" and (getattr(value, "scratch", False) or getattr(value, "fixture", False) or _is_fixture_path(value)):
                continue
            path = model.files[context.fid][1]
            detail = f"{path}:{call.lineno}:{call.col_offset + 1}: {mechanism}: target is dynamic, external or absent from tracked files"
            diagnostics.add((context.fid, "unsupported_test_mechanism", detail))
    return sorted(diagnostics)


def expansion_diagnostics(model):
    """Report capped/guarded scopes only when they contain an actual path mechanism."""
    targets = {}
    for fid, items in getattr(model, "_test_path_contexts", {}).items():
        calls = set()
        for context in items:
            _dst, mechanism, _value = resolve_target(context)
            if mechanism or (isinstance(context.call.func, ast.Attribute)
                             and context.call.func.attr in {"glob", "rglob"}):
                calls.add(context.call)
        targets[fid] = calls
    diagnostics = set()
    for fid, loop, mechanism in getattr(model, "_test_path_limits", ()):
        if not any(call in targets.get(fid, ()) for statement in loop.body
                   for call in ast.walk(statement) if isinstance(call, ast.Call)):
            continue
        path = model.files[fid][1]
        diagnostics.add((fid, "unsupported_test_mechanism",
            f"{path}:{loop.lineno}:{loop.col_offset + 1}: {mechanism}: "
            "loop-dependent targets remain unresolved"))
    return sorted(diagnostics)

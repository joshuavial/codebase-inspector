"""Symbols, pytest cases and resolution facts from Python syntax trees.

Definitions are read at the top level of a module (including inside `if`,
`try` and `with` blocks) and in class bodies, which covers methods and nested
classes; functions defined inside functions are not symbols. Facts have the
shape `typescript.py` gives them, with Python module specifiers (`pkg.mod`,
`.sibling`, `..`) that `resolve.py` binds across files.
"""

import ast
import inspect
import posixpath
import re

from tree_sitter_language_pack import get_parser

from cbi.parse import endpoints

GRAMMARS = {"python": "python"}
TEST_SEP = " > "
# Compound statements whose bodies still run at module or class level.
COMPOUND = {"if_statement", "elif_clause", "else_clause", "try_statement", "except_clause", "except_group_clause",
            "finally_clause", "with_statement", "block"}
DEFINITIONS = {"function_definition", "class_definition"}
COMPREHENSIONS = {"list_comprehension", "set_comprehension", "dictionary_comprehension", "generator_expression"}
IMPORTS = {"import_statement", "import_from_statement"}
PATH_CTORS = {"Path", "pathlib.Path", "PurePath", "pathlib.PurePath"}
DIRNAMES = {"os.path.dirname", "dirname", "path.dirname"}
JOINS = {"os.path.join", "join", "path.join"}
READ_METHODS = {"read_text", "read_bytes", "open"}
WRAPPERS = {"str", "os.path.abspath", "os.path.realpath", "abspath", "realpath"}
ENV_NAME = re.compile(r"[A-Z_][A-Z0-9_]*")
# A typing wrapper is not the injected class. `T | None` is unwrapped separately.
PY_WRAPPERS = {"Optional", "Union", "list", "dict", "set", "tuple", "Sequence", "Mapping", "Iterable", "Callable",
               "ClassVar", "Final", "Literal", "Annotated", "Collection", "AbstractSet", "MutableMapping",
               "MutableSequence"}


def _text(node):
    return node.text.decode(errors="replace")


def _string(node):
    """The value of a plain string literal node, or None (f-strings, concatenations, other nodes)."""
    if node.type != "string" or any(c.type == "interpolation" for c in node.named_children):
        return None
    return "".join(_text(c) for c in node.named_children if c.type == "string_content")


def _statements(node):
    """Statements of a module or class body, looking inside compound statements."""
    for child in node.named_children:
        if child.type in COMPOUND:
            yield from _statements(child)
        elif child.type == "expression_statement" and child.named_children:
            yield child.named_children[0]
        else:
            yield child


def _doc(defn):
    """The docstring of a function or class definition, cleaned like `inspect.getdoc`."""
    body = defn.child_by_field_name("body")
    first = next((c for c in body.named_children if c.type != "comment"), None) if body else None
    if first is not None and first.type == "expression_statement" and first.named_children:
        first = first.named_children[0]
    if first is None or first.type != "string":
        return None
    try:
        value = ast.literal_eval(_text(first))
    except (ValueError, SyntaxError):
        return None
    return inspect.cleandoc(value) or None if isinstance(value, str) else None


def _signature(source, anchor, defn):
    """Decorators and the `def`/`class` line up to the colon, whitespace collapsed."""
    colon = [c for c in defn.children if c.type == ":"]
    end = colon[-1].start_byte if colon else defn.end_byte
    return " ".join(source[anchor.start_byte:end].decode(errors="replace").split())


def _targets(node):
    """Names an assignment, `for`, `with ... as` or `except ... as` target binds."""
    out, stack = set(), [node]
    while stack:
        n = stack.pop()
        if n.type == "identifier":
            out.add(_text(n))
        elif n.type in ("pattern_list", "tuple_pattern", "list_pattern", "list_splat_pattern",
                        "parenthesized_expression", "as_pattern_target", "tuple", "list"):
            stack.extend(n.named_children)
    return out


def _params(params):
    out = set()
    for p in params.named_children if params else ():
        if p.type == "identifier":
            out.add(_text(p))
            continue
        name = p.child_by_field_name("name") or next((c for c in p.named_children if c.type == "identifier"), None)
        if name is not None and name.type == "identifier":
            out.add(_text(name))
    return out


def _assigned(body):
    """Local names a function body binds, not looking into nested functions, classes or lambdas.

    Imports inside a function are left out on purpose: they bind a module's name,
    so a call through them should still resolve.
    """
    out, stack = set(), list(body.named_children) if body else []
    while stack:
        n = stack.pop()
        if n.type in DEFINITIONS:
            name = n.child_by_field_name("name")
            if name is not None:
                out.add(_text(name))
            continue
        if n.type in ("lambda", *COMPREHENSIONS):
            continue
        if n.type in ("assignment", "augmented_assignment", "for_statement"):
            target = n.child_by_field_name("left")
            if target is not None:
                out |= _targets(target)
        elif n.type in ("as_pattern_target", "named_expression"):
            out |= _targets(n.child_by_field_name("name") or n)
        stack.extend(n.named_children)
    return out


def _scope_names(n):
    """Names a node brings into scope for its children: parameters, locals, comprehension variables."""
    if n.type == "function_definition":
        return _params(n.child_by_field_name("parameters")) | _assigned(n.child_by_field_name("body"))
    if n.type == "lambda":
        return _params(n.child_by_field_name("parameters"))
    if n.type in COMPREHENSIONS:
        return {name for c in n.named_children if c.type == "for_in_clause" for name in _targets(c.child_by_field_name("left"))}
    return None


def _shadowed(scope, name):
    while scope:
        names, scope = scope
        if name in names:
            return True
    return False


def _callee(call):
    fn = call.child_by_field_name("function")
    return _text(fn) if fn is not None and fn.type in ("identifier", "attribute") else None


def _args(call):
    args = call.child_by_field_name("arguments")
    return [a for a in args.named_children if a.type != "comment"] if args is not None and args.type == "argument_list" else []


FILE = "\0file"  # stands for `__file__` while a path expression is evaluated


def _up(path, levels):
    """The directory `levels` above path, where FILE's first level is its own directory."""
    if path == FILE:
        path, levels = ".", levels - 1
    return posixpath.join(path, *[".."] * levels) if levels >= 0 else None


def _path(node, consts):
    """Evaluate a literal path expression to a path (from the file's directory when it starts
    from `__file__`), FILE for `__file__` itself, or None.

    Covers strings, `__file__`, module constants holding such a path, `.parent`,
    `.parents[n]`, `.resolve()`, `Path(...)`, `str(...)`, `os.path.dirname`,
    `abspath`, `join` and the `/` operator.
    """
    t = node.type
    if t == "string":
        return _string(node)
    if t == "identifier":
        return FILE if _text(node) == "__file__" else consts.get(_text(node))
    if t == "parenthesized_expression" and node.named_children:
        return _path(node.named_children[0], consts)
    if t == "attribute" and _text(node.child_by_field_name("attribute")) == "parent":
        base = _path(node.child_by_field_name("object"), consts)
        return None if base is None else _up(base, 1)
    if t == "subscript":
        value, index = node.child_by_field_name("value"), node.child_by_field_name("subscript")
        if value.type == "attribute" and _text(value.child_by_field_name("attribute")) == "parents" \
                and index is not None and index.type == "integer":
            base = _path(value.child_by_field_name("object"), consts)
            return None if base is None else _up(base, int(_text(index)) + 1)
        return None
    if t == "binary_operator" and _text(node.child_by_field_name("operator")) == "/":
        left = _path(node.child_by_field_name("left"), consts)
        right = _path(node.child_by_field_name("right"), consts)
        return None if left in (None, FILE) or right in (None, FILE) else posixpath.join(left, right)
    if t != "call":
        return None
    fn, args, name = node.child_by_field_name("function"), _args(node), _callee(node)
    if fn.type == "attribute" and _text(fn.child_by_field_name("attribute")) in ("resolve", "absolute") and not args:
        return _path(fn.child_by_field_name("object"), consts)
    if name in DIRNAMES and len(args) == 1:
        base = _path(args[0], consts)
        return None if base is None else _up(base, 1)
    if name in PATH_CTORS | WRAPPERS and len(args) == 1:
        return _path(args[0], consts)
    if name in JOINS and args:
        parts = [_path(a, consts) for a in args]
        return None if None in parts or FILE in parts else posixpath.join(*parts)
    return None


def _os_env_bindings(imports):
    """Local names bound to the `os` module, to `os.environ`, and to `os.getenv`."""
    modules, environs, getenvs = set(), set(), set()
    for imp in imports:
        if imp["spec"] != "os" or not imp["names"]:
            continue
        for local, imported in imp["names"].items():
            if imported == "*":
                modules.add(local)
            elif imported == "environ":
                environs.add(local)
            elif imported == "getenv":
                getenvs.add(local)
    return modules, environs, getenvs


def _py_written(node):
    """True when `node` is the target of an assignment or `del`, not a read."""
    cur = node
    while cur.parent is not None and cur.parent.type in ("expression_list", "parenthesized_expression"):
        cur = cur.parent
    parent = cur.parent
    if parent is None:
        return False
    if parent.type == "delete_statement":
        return True
    # `==` not `is`: child_by_field_name returns a new wrapper each call.
    return parent.type == "assignment" and parent.child_by_field_name("left") == cur


def _py_default(arg):
    """A string default: the positional argument, or the `default=` keyword."""
    if arg is None:
        return None
    if arg.type == "keyword_argument":
        name = arg.child_by_field_name("name")
        if name is None or _text(name) != "default":
            return None
        arg = arg.child_by_field_name("value")
    return _string(arg) if arg is not None else None


def _is_environ(node, modules, environs, scope):
    """True for `environ` imported from `os`, or `<os>.environ`, when the name is not shadowed."""
    if node is None:
        return False
    if node.type == "identifier":
        name = _text(node)
        return name in environs and not _shadowed(scope, name)
    if node.type == "attribute" and _text(node.child_by_field_name("attribute")) == "environ":
        obj = node.child_by_field_name("object")
        return (obj is not None and obj.type == "identifier" and _text(obj) in modules
                and not _shadowed(scope, _text(obj)))
    return False


def _py_env_read(node, modules, environs, getenvs, scope):
    """`(NAME, default or None)` for an env read, else None. A non-string default is dropped."""
    if _py_written(node):
        return None
    if node.type == "subscript":
        value, index = node.child_by_field_name("value"), node.child_by_field_name("subscript")
        name = _string(index) if index is not None else None
        if name and ENV_NAME.fullmatch(name) and _is_environ(value, modules, environs, scope):
            return name, None
        return None
    if node.type != "call":
        return None
    fn = node.child_by_field_name("function")
    if fn is None:
        return None
    if fn.type == "attribute" and _text(fn.child_by_field_name("attribute")) == "get":
        if not _is_environ(fn.child_by_field_name("object"), modules, environs, scope):
            return None
    elif fn.type == "attribute" and _text(fn.child_by_field_name("attribute")) == "getenv":
        obj = fn.child_by_field_name("object")
        if obj is None or obj.type != "identifier" or _text(obj) not in modules or _shadowed(scope, _text(obj)):
            return None
    elif not (fn.type == "identifier" and _text(fn) in getenvs and not _shadowed(scope, _text(fn))):
        return None
    args = _args(node)
    if not args:
        return None
    name = _string(args[0])
    if not name or not ENV_NAME.fullmatch(name):
        return None
    return name, _py_default(args[1]) if len(args) > 1 else None


_PATCH_ATTRS = {"patch", "setattr"}
_MODULE_TARGET = re.compile(r"[A-Za-z_][\w.]*")


def _patch_target(call):
    """The module string in `patch("pkg.mod.attr")` or `mocker.patch` / `monkeypatch.setattr` of the same shape.

    `patch.object` and `patch.dict` are not this form. A string with no dot is not a module path.
    """
    fn = call.child_by_field_name("function")
    if fn is None:
        return None
    if fn.type == "identifier":
        name = _text(fn)
    elif fn.type == "attribute":
        name = _text(fn.child_by_field_name("attribute"))
    else:
        return None
    if name not in _PATCH_ATTRS:
        return None
    args = _args(call)
    if not args:
        return None
    target = _string(args[0])
    if target and "." in target and _MODULE_TARGET.fullmatch(target):
        return target
    return None


def _read_path(call, consts):
    """The literal path read by `open(p)`, `p.read_text()`, `spec_from_file_location(name, p)` or `run_path(p)`."""
    fn, args = call.child_by_field_name("function"), _args(call)
    if fn is None:
        return None
    name, target = _text(fn), None
    if name in ("open", "io.open", "runpy.run_path", "run_path") and args:
        target = args[0]
    elif name.endswith("spec_from_file_location") and len(args) >= 2:
        target = args[1]
    elif fn.type == "attribute" and _text(fn.child_by_field_name("attribute")) in READ_METHODS:
        target = fn.child_by_field_name("object")
    path = _path(target, consts) if target is not None else None
    return None if path in (None, FILE) else path


class _Collector:
    def __init__(self, source, is_test):
        self.source = source
        self.is_test = is_test
        self.defs = []
        self.anchors = {}  # (start byte, end byte, type) of a definition's node -> its index
        self.locals = set()  # names bound at the top level
        self.imports = []  # {"spec", "names": {local: imported name, or "*" for a whole module}, "type_only"?}
        self.exports = {}  # a module exports every top-level name, imported ones included
        self.reexports = []  # `from m import *`: {"spec", "names": None}
        self.consts = {}  # top-level name -> the literal path it holds, such as HERE = Path(__file__).parent
        self.fields = {}  # class def index -> {field: {"type", "param", "index"}}
        self.uses = []  # [def index, class index, field, declared type, method]
        self.protocols = []  # class def indexes whose bases include Protocol

    def add(self, node, name, display_kind, parent, signature, doc, kind="symbol"):
        qualname = name if parent is None else f"{self.defs[parent]['qualname']}{TEST_SEP if kind == 'test' else '.'}{name}"
        self.defs.append({
            "qualname": qualname,
            "name": name,
            "kind": kind,
            "display_kind": display_kind,
            "parent": parent,
            "start_line": node.start_point.row + 1,
            "end_line": node.end_point.row + 1,
            "signature": signature,
            "doc": doc,
        })
        self.anchors[(node.start_byte, node.end_byte, node.type)] = len(self.defs) - 1
        return len(self.defs) - 1

    def body(self, node, parent):
        for stmt in _statements(node):
            self.statement(stmt, parent)

    def statement(self, stmt, parent):
        top = parent is None
        if top and stmt.type in ("assignment", "augmented_assignment"):
            left, right = stmt.child_by_field_name("left"), stmt.child_by_field_name("right")
            self.locals |= _targets(left)
            path = _path(right, self.consts) if left.type == "identifier" and right is not None else None
            if path is not None:
                self.consts[_text(left)] = path
            return
        defn = stmt.child_by_field_name("definition") if stmt.type == "decorated_definition" else stmt
        if defn is None or defn.type not in DEFINITIONS:
            return
        name = _text(defn.child_by_field_name("name"))
        if top:
            self.locals.add(name)
        is_class = defn.type == "class_definition"
        kind, display = "symbol", "class" if is_class else "function" if top else "method"
        # pytest collects test* functions, Test* classes, and test* methods and Test* classes inside those.
        if self.is_test and (top or self.defs[parent]["kind"] == "test"):
            if is_class and name.startswith("Test"):
                kind, display = "test", "test suite"
            elif not is_class and name.startswith("test"):
                kind, display = "test", "test case"
        index = self.add(stmt, name, display, parent, _signature(self.source, stmt, defn), _doc(defn), kind)
        if is_class:
            if _is_protocol(defn):
                self.protocols.append(index)
            self.body(defn.child_by_field_name("body"), index)
        elif name == "__init__" and parent is not None:
            self.fields[parent] = _init_fields(defn)

    def import_statement(self, stmt, top):
        names = {}
        for n in stmt.children_by_field_name("name"):
            original = n.child_by_field_name("name") if n.type == "aliased_import" else n
            alias = n.child_by_field_name("alias") if n.type == "aliased_import" else None
            names[_text(alias or original)] = _text(original)
        if stmt.type == "import_statement":
            # `import a.b` binds the dotted name to the whole module a.b; calls name it as `a.b.f()`.
            for local, module in names.items():
                rec = {"spec": module, "names": {local: "*"}}
                if _in_type_checking(stmt):
                    rec["type_only"] = True
                self.imports.append(rec)
        else:
            spec = "".join(_text(stmt.child_by_field_name("module_name")).split())
            if any(c.type == "wildcard_import" for c in stmt.named_children):
                self.reexports.append({"spec": spec, "names": None})
                return
            rec = {"spec": spec, "names": names}
            if _in_type_checking(stmt):
                rec["type_only"] = True
            self.imports.append(rec)
        if top:
            self.exports.update({local: local for local in names})

    def sites(self, root):
        """Imports anywhere in the file, then call sites and literal file reads with the innermost definition.

        A call is kept only when its callee could bind: a top-level or imported
        name that no parameter or local variable shadows, or `self.x` / `cls.x`
        inside a class. Calls are [def index or None, class index or None, shape,
        name, member] with shape `name` (f(), Cls()), `this` (self.f()) or
        `member` (mod.f(), Cls.f(), a.b.f()). Reads are [def index or None, path].
        Env reads are [def index or None, name, default or None], from
        `os.environ["X"]`, `os.environ.get`, `os.getenv` and `environ` or
        `getenv` imported from `os`. Patches are [def index or None, module string]
        from `patch("pkg.mod.attr")` and `setattr` of the same shape.
        """
        stack = [(root, False)]
        while stack:
            n, nested = stack.pop()
            if n.type in IMPORTS:
                self.import_statement(n, not nested)
                continue
            nested = nested or n.type in DEFINITIONS
            stack.extend((c, nested) for c in n.named_children)
        bindings = self.locals | {local for imp in self.imports for local in imp["names"]}
        modules, environs, getenvs = _os_env_bindings(self.imports)

        calls, reads, envs, patches = [], [], [], []
        stack = [(root, None, None, None)]
        while stack:
            n, d, c, scope = stack.pop()
            index = self.anchors.get((n.start_byte, n.end_byte, n.type))
            if index is not None:
                d = index
                if self.defs[index]["display_kind"] in ("class", "test suite"):
                    c = index
            names = _scope_names(n)
            if names:
                scope = (names, scope)
            if n.type == "call":
                read = _read_path(n, self.consts)
                if read:
                    reads.append([d, read])
                patched = _patch_target(n)
                if patched:
                    patches.append([d, patched])
                fn = n.child_by_field_name("function")
                if fn.type == "identifier":
                    name = _text(fn)
                    if name in bindings and not _shadowed(scope, name):
                        calls.append([d, c, "name", name, None])
                elif fn.type == "attribute":
                    obj, attr = fn.child_by_field_name("object"), _text(fn.child_by_field_name("attribute"))
                    if obj.type == "identifier" and _text(obj) in ("self", "cls"):
                        if c is not None:
                            calls.append([d, c, "this", attr, None])
                    elif obj.type == "attribute" and c is not None and _self_field(obj):
                        field = _self_field(obj)
                        info = self.fields.get(c, {}).get(field)
                        if info:
                            self.uses.append([d, c, field, info["type"], attr])
                    elif obj.type in ("identifier", "attribute"):
                        name = _text(obj)
                        if name in bindings and not _shadowed(scope, name.split(".")[0]):
                            calls.append([d, c, "member", name, attr])
            found = _py_env_read(n, modules, environs, getenvs, scope)
            if found:
                envs.append([d, found[0], found[1]])
            for child in reversed(n.named_children):
                stack.append((child, d, c, scope))
        return calls, reads, envs, patches


def _annotation(node):
    return next((c for c in node.named_children if c.type == "type"), None)


def _py_type_name(node):
    """A single type name from an annotation, unwrapping `T | None`. Anything else is None."""
    if node is None:
        return None
    if node.type == "type":
        node = node.named_children[0] if node.named_children else None
    return _py_type_expr(node)


def _py_type_expr(node):
    if node is None:
        return None
    if node.type == "identifier":
        return _text(node)
    if node.type == "none":
        return None
    if node.type == "subscript":
        value = node.child_by_field_name("value")
        if value is not None and value.type == "identifier" and _text(value) not in PY_WRAPPERS:
            return _text(value)
        return None
    if node.type == "binary_operator" and node.child_by_field_name("operator") is not None \
            and _text(node.child_by_field_name("operator")) == "|":
        names = []
        for side in (node.child_by_field_name("left"), node.child_by_field_name("right")):
            if side is None or side.type == "none":
                continue
            name = _py_type_expr(side)
            if not name:
                return None
            names.append(name)
        return names[0] if len(names) == 1 else None
    if node.type == "parenthesized_expression" and node.named_children:
        return _py_type_expr(node.named_children[0])
    return None


def _init_params(defn):
    """(index, name, type or None) for a function's parameters, skipping the leading self or cls."""
    params = defn.child_by_field_name("parameters")
    out, index = [], 0
    for p in params.named_children if params else ():
        if p.type in ("list_splat_pattern", "dictionary_splat_pattern"):
            continue
        if p.type == "identifier":
            text, typ = _text(p), None
        else:
            name = p.child_by_field_name("name")
            if name is None or name.type != "identifier":
                name = next((c for c in p.named_children if c.type == "identifier"), None)
            if name is None or name.type != "identifier":
                continue
            text, typ = _text(name), _py_type_name(_annotation(p))
        if not out and text in ("self", "cls"):
            continue
        out.append((index, text, typ))
        index += 1
    return out


def _self_field(node):
    """The field name of `self.field`, else None."""
    if node is None or node.type != "attribute":
        return None
    obj, attr = node.child_by_field_name("object"), node.child_by_field_name("attribute")
    if obj is not None and obj.type == "identifier" and _text(obj) == "self" and attr is not None:
        return _text(attr)
    return None


def _init_fields(defn):
    """`self.field = param` in `__init__`, with the annotation on the assignment or the parameter."""
    by_name = {name: (index, typ) for index, name, typ in _init_params(defn)}
    body = defn.child_by_field_name("body")
    fields, stack = {}, list(body.named_children) if body else []
    while stack:
        n = stack.pop()
        if n.type in DEFINITIONS or n.type == "lambda":
            continue
        if n.type == "assignment":
            left, right = n.child_by_field_name("left"), n.child_by_field_name("right")
            field = _self_field(left)
            if field and right is not None and right.type == "identifier" and _text(right) in by_name:
                index, param_typ = by_name[_text(right)]
                typ = _py_type_name(_annotation(n)) or param_typ
                if typ:
                    fields[field] = {"type": typ, "param": _text(right), "index": index}
            continue
        stack.extend(n.named_children)
    return fields


def _is_protocol(defn):
    supers = defn.child_by_field_name("superclasses")
    for arg in supers.named_children if supers else ():
        if arg.type == "identifier" and _text(arg) == "Protocol":
            return True
        if arg.type == "attribute":
            attr = arg.child_by_field_name("attribute")
            if attr is not None and _text(attr) == "Protocol":
                return True
    return False


def _if_condition(node):
    cond = node.child_by_field_name("condition")
    if cond is not None:
        return cond
    named = node.named_children
    return named[0] if named else None


def _is_type_checking(node):
    if node is None:
        return False
    if node.type == "identifier":
        return _text(node) == "TYPE_CHECKING"
    if node.type == "attribute":
        attr = node.child_by_field_name("attribute")
        return attr is not None and _text(attr) == "TYPE_CHECKING"
    if node.type == "parenthesized_expression" and node.named_children:
        return _is_type_checking(node.named_children[0])
    return False


def _in_type_checking(node):
    cur = node.parent
    while cur is not None:
        if cur.type == "if_statement" and _is_type_checking(_if_condition(cur)):
            return True
        cur = cur.parent
    return False


def _py_inner_names(node):
    """Names a lambda or comprehension binds. An empty scope would let them see an outer type."""
    if node.type == "lambda":
        return _params(node.child_by_field_name("parameters"))
    names = set()
    for clause in node.named_children:
        if clause.type == "for_in_clause":
            left = clause.child_by_field_name("left")
            if left is not None:
                names |= _targets(left)
    return names


def _lookup(scopes, name):
    for scope in reversed(scopes):
        if name in scope:
            return scope[name] or None
    return None


def _py_expr_type(node, scopes, bound=True):
    if node is None:
        return None
    if node.type == "identifier":
        return _lookup(scopes, _text(node)) if bound else None
    if node.type == "parenthesized_expression" and node.named_children:
        return _py_expr_type(node.named_children[0], scopes, bound)
    if node.type == "call":
        fn = node.child_by_field_name("function")
        return _text(fn) if fn is not None and fn.type == "identifier" else None
    return None


def _constructs(root):
    """`Foo(...)` whose arguments name a type. Each is [class, [[keyword or None, type or None]]]."""
    found = []

    def walk(node, scopes):
        entered = scopes
        if node.type == "function_definition":
            entered = [*scopes, {name: typ or "" for _, name, typ in _init_params(node)}]
        elif node.type in ("lambda", *COMPREHENSIONS):
            entered = [*scopes, {name: "" for name in _py_inner_names(node)}]
        if node.type == "for_statement":
            # The name is rebound for the rest of the function, so it drops a type assigned above the loop.
            left = node.child_by_field_name("left")
            if left is not None:
                for name in _targets(left):
                    entered[-1][name] = ""
        if node.type == "call":
            fn = node.child_by_field_name("function")
            if fn is not None and fn.type == "identifier":
                args = []
                for arg in _args(node):
                    if arg.type == "keyword_argument":
                        name, value = arg.child_by_field_name("name"), arg.child_by_field_name("value")
                        args.append([_text(name) if name is not None else None, _py_expr_type(value, entered)])
                    else:
                        args.append([None, _py_expr_type(arg, entered)])
                if any(typ for _, typ in args):
                    found.append([_text(fn), args])
        for child in node.named_children:
            walk(child, entered)
        if node.type == "assignment":
            left = node.child_by_field_name("left")
            if left is not None and left.type == "identifier":
                typ = _py_type_name(_annotation(node)) or _py_expr_type(node.child_by_field_name("right"), entered, False)
                entered[-1][_text(left)] = typ or ""

    walk(root, [{}])
    return found


def parse(source, lang, is_test):
    """Return (definitions in source order, facts, has_parse_error), as `typescript.parse` does."""
    tree = get_parser(GRAMMARS[lang]).parse(source)
    collector = _Collector(source, is_test)
    collector.body(tree.root_node, None)
    calls, reads, envs, patches = collector.sites(tree.root_node)
    exports = {name: name for name in collector.locals}
    exports.update(collector.exports)
    facts = {
        "imports": collector.imports,
        "exports": exports,
        "reexports": collector.reexports,
        "locals": sorted(collector.locals),
        "calls": calls,
        "reads": reads,
        "patches": patches,
        "envs": envs,
        "uses": collector.uses,
        "fields": [[index, name, info["type"], info["param"], info["index"]]
                   for index, fields in collector.fields.items() for name, info in fields.items()],
        "constructs": _constructs(tree.root_node),
        "protocols": collector.protocols,
    }
    facts.update(endpoints.python_facts(tree.root_node, is_test, collector.defs))
    return collector.defs, facts, tree.root_node.has_error

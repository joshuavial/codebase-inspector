"""Symbols, node:test cases and resolution facts from TypeScript, TSX and JS syntax trees.

Definitions are read at the top level of a file (unwrapping `export`) and as
members of classes. Facts (imports, exports, call sites, literal file reads)
are what `resolve.py` binds across files; nothing is resolved here.
"""

from tree_sitter_language_pack import get_parser

GRAMMARS = {"typescript": "typescript", "tsx": "tsx", "javascript": "javascript"}
CLASSES = {"class_declaration", "abstract_class_declaration"}
FUNCTIONS = {"function_declaration", "generator_function_declaration"}
FUNCTION_VALUES = {"arrow_function", "function_expression"}
METHODS = {"method_definition", "abstract_method_signature"}
JSX = {"jsx_element", "jsx_self_closing_element", "jsx_fragment"}
TEST_CALLS = {"test", "it", "describe"}
TEST_SEP = " > "
FUNCTION_LIKE = {"function_declaration", "generator_function_declaration", "function_expression", "function",
                 "generator_function", "arrow_function", "method_definition"}
DECLARATIONS = {"lexical_declaration", "variable_declaration"}
READ_CALLS = {"readFileSync", "readFile", "createReadStream"}
PATH_JOINS = {"join", "resolve"}


def _text(node):
    return node.text.decode(errors="replace")


def _between(source, start, end):
    """Source text from byte start to end with whitespace collapsed."""
    return " ".join(source[start:end].decode(errors="replace").split())


def _doc(node):
    """The JSDoc comment directly above node, cleaned of comment markers."""
    prev = node.prev_named_sibling
    if not prev or prev.type != "comment" or prev.end_point.row < node.start_point.row - 1:
        return None
    text = _text(prev)
    if not text.startswith("/**"):
        return None
    lines = [line.strip().removeprefix("*").strip() for line in text[3:-2].splitlines()]
    return "\n".join(lines).strip() or None


def _has_jsx(node):
    stack = [node]
    while stack:
        n = stack.pop()
        if n.type in JSX:
            return True
        stack.extend(n.named_children)
    return False


def _signature(source, node, body):
    return _between(source, node.start_byte, body.start_byte if body else node.end_byte)


class _Collector:
    def __init__(self, source):
        self.source = source
        self.defs = []
        self.anchors = {}  # (start byte, end byte, type) of a definition's node -> its index
        self.locals = set()  # names declared at the top level
        self.imports = []  # {"spec", "names": {local: imported name, "default" or "*"}}
        self.exports = {}  # exported name -> local name
        self.reexports = []  # {"spec", "names": {exported: imported, or "*"}, or None for `export *`}

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

    def statement(self, stmt):
        if stmt.type == "import_statement":
            self.import_statement(stmt)
            return
        decl = stmt.child_by_field_name("declaration") if stmt.type == "export_statement" else stmt
        if stmt.type == "export_statement":
            self.export_statement(stmt, decl)
        if not decl:
            return
        doc_anchor = stmt
        name_node = decl.child_by_field_name("name")
        if name_node and name_node.type in ("identifier", "type_identifier"):
            self.locals.add(_text(name_node))
        for declarator in decl.named_children if decl.type in DECLARATIONS else ():
            if declarator.type == "variable_declarator":
                self.locals.update(_bound_names(declarator))
                self.require(declarator)
        body = decl.child_by_field_name("body")
        if decl.type in CLASSES and name_node:
            index = self.add(decl, _text(name_node), "class", None, _signature(self.source, decl, body), _doc(doc_anchor))
            for member in body.named_children if body else ():
                self.member(member, index)
        elif decl.type in FUNCTIONS and name_node:
            name = _text(name_node)
            kind = "component" if name[:1].isupper() and body and _has_jsx(body) else "function"
            self.add(decl, name, kind, None, _signature(self.source, decl, body), _doc(doc_anchor))
        elif decl.type == "interface_declaration" and name_node:
            self.add(decl, _text(name_node), "interface", None, _signature(self.source, decl, body), _doc(doc_anchor))
        elif decl.type in DECLARATIONS:
            keyword = _text(decl.child(0))
            for declarator in decl.named_children:
                value = declarator.child_by_field_name("value")
                name_node = declarator.child_by_field_name("name")
                if declarator.type != "variable_declarator" or not value or value.type not in FUNCTION_VALUES:
                    continue
                if name_node.type != "identifier":
                    continue
                name = _text(name_node)
                fbody = value.child_by_field_name("body")
                kind = "component" if name[:1].isupper() and fbody and _has_jsx(fbody) else "function"
                signature = f"{keyword} {_signature(self.source, declarator, fbody)}"
                self.add(declarator, name, kind, None, signature, _doc(doc_anchor))

    def import_statement(self, stmt):
        source = stmt.child_by_field_name("source")
        if not source:
            return
        names = {}
        clause = next((c for c in stmt.named_children if c.type == "import_clause"), None)
        for c in clause.named_children if clause else ():
            if c.type == "identifier":
                names[_text(c)] = "default"
            elif c.type == "namespace_import":
                names[_text(c.named_children[0])] = "*"
            elif c.type == "named_imports":
                for spec in c.named_children:
                    if spec.type == "import_specifier":
                        name, alias = spec.child_by_field_name("name"), spec.child_by_field_name("alias")
                        names[_text(alias or name)] = _text(name)
        self.imports.append({"spec": _string(source), "names": names})

    def require(self, declarator):
        """`const x = require("./y")` and `const { a } = require("./y")`."""
        value = declarator.child_by_field_name("value")
        spec = _require_spec(value) if value else None
        if spec is None:
            return
        target = declarator.child_by_field_name("name")
        if target.type == "identifier":
            names = {_text(target): "*"}
        else:
            names = {}
            for prop in target.named_children if target.type == "object_pattern" else ():
                if prop.type == "shorthand_property_identifier_pattern":
                    names[_text(prop)] = _text(prop)
                elif prop.type == "pair_pattern" and prop.child_by_field_name("value").type == "identifier":
                    names[_text(prop.child_by_field_name("value"))] = _text(prop.child_by_field_name("key"))
        self.imports.append({"spec": spec, "names": names})

    def export_statement(self, stmt, decl):
        source = stmt.child_by_field_name("source")
        default = any(c.type == "default" for c in stmt.children)
        clause = next((c for c in stmt.named_children if c.type == "export_clause"), None)
        if source:
            if clause:
                names = {}
                for spec in clause.named_children:
                    name, alias = spec.child_by_field_name("name"), spec.child_by_field_name("alias")
                    names[_text(alias or name)] = _text(name)
            else:
                ns = next((c for c in stmt.named_children if c.type == "namespace_export"), None)
                names = {_text(ns.named_children[0]): "*"} if ns else None
            self.reexports.append({"spec": _string(source), "names": names})
        elif clause:
            for spec in clause.named_children:
                name, alias = spec.child_by_field_name("name"), spec.child_by_field_name("alias")
                self.exports[_text(alias or name)] = _text(name)
        elif decl:
            name_node = decl.child_by_field_name("name")
            if decl.type in DECLARATIONS:
                for declarator in decl.named_children:
                    for name in _bound_names(declarator):
                        self.exports[name] = name
            elif name_node:
                self.exports["default" if default else _text(name_node)] = _text(name_node)
        elif default:
            value = stmt.child_by_field_name("value")
            if value and value.type == "identifier":
                self.exports["default"] = _text(value)

    def member(self, member, parent):
        name_node = member.child_by_field_name("name") or member.child_by_field_name("property")
        if not name_node:
            return
        if member.type in METHODS:
            body = member.child_by_field_name("body")
        elif member.type in ("public_field_definition", "field_definition"):
            value = member.child_by_field_name("value")
            if not value or value.type not in FUNCTION_VALUES:
                return
            body = value.child_by_field_name("body")
        else:
            return
        self.add(member, _text(name_node), "method", parent, _signature(self.source, member, body), _doc(member))

    def tests(self, node, parent):
        """node:test style cases: test(...), it(...), describe(...), test.skip(...), t.test(...)."""
        stack = [(node, parent)]
        while stack:
            n, parent = stack.pop()
            index = self._test_case(n, parent) if n.type == "call_expression" else None
            for child in reversed(n.named_children):
                stack.append((child, parent if index is None else index))

    def _test_case(self, call, parent):
        fn = call.child_by_field_name("function")
        args = call.child_by_field_name("arguments")
        if not fn or not args or not args.named_children:
            return None
        first = args.named_children[0]
        callback = next((a for a in args.named_children[1:] if a.type in FUNCTION_VALUES), None)
        if fn.type == "identifier":
            word = _text(fn)
            if word not in TEST_CALLS:
                return None
        elif fn.type == "member_expression":
            obj, prop = fn.child_by_field_name("object"), fn.child_by_field_name("property")
            if obj.type == "identifier" and _text(obj) in TEST_CALLS:
                word = _text(obj)  # test.skip(...), describe.only(...)
            elif _text(prop) in TEST_CALLS and callback:
                word = _text(prop)  # t.test(...) subtests; the callback rules out regex.test("x")
            else:
                return None
        else:
            return None
        if first.type not in ("string", "template_string"):
            return None
        end = callback.child_by_field_name("body") if callback else None
        signature = _between(self.source, call.start_byte, end.start_byte if end else call.end_byte)
        display_kind = "test suite" if word == "describe" else "test case"
        return self.add(call, _text(first)[1:-1], display_kind, parent, signature, None, kind="test")


    def sites(self, root):
        """Call sites and literal file reads, with the innermost definition around each.

        A call is kept only when its callee could bind: a top-level name or import
        that no parameter or local variable shadows, or `this.x` inside a class.
        Calls are [def index or None, class index or None, shape, name, member]
        with shape `name` (f(), new F(), <F />), `this` (this.f()) or `member`
        (ns.f(), Class.f()). Reads are [def index or None, path].
        """
        bindings = self.locals | {local for imp in self.imports for local in imp["names"]}
        calls, reads = [], []
        stack = [(root, None, None, None)]
        while stack:
            n, d, c, scope = stack.pop()
            index = self.anchors.get((n.start_byte, n.end_byte, n.type))
            if index is not None:
                d = index
                if self.defs[index]["display_kind"] == "class":
                    c = index
            names = _scope_names(n)
            if names:
                scope = (names, scope)
            callee = None
            if n.type == "call_expression":
                callee = n.child_by_field_name("function")
                read = _read_path(n)
                if read:
                    reads.append([d, read])
                spec = _require_spec(n)
                if spec is not None and not _top_level_declarator(n.parent):
                    self.imports.append({"spec": spec, "names": {}})  # import("./x"), nested require
            elif n.type == "new_expression":
                callee = n.child_by_field_name("constructor")
            elif n.type in ("jsx_opening_element", "jsx_self_closing_element"):
                callee = n.child_by_field_name("name")
            if callee is not None:
                if callee.type == "identifier":
                    name = _text(callee)
                    if name in bindings and not _shadowed(scope, name):
                        calls.append([d, c, "name", name, None])
                elif callee.type == "member_expression":
                    obj, prop = callee.child_by_field_name("object"), callee.child_by_field_name("property")
                    if obj.type == "this" and c is not None:
                        calls.append([d, c, "this", _text(prop), None])
                    elif obj.type == "identifier" and _text(obj) in bindings and not _shadowed(scope, _text(obj)):
                        calls.append([d, c, "member", _text(obj), _text(prop)])
            for child in reversed(n.named_children):
                stack.append((child, d, c, scope))
        return calls, reads


def _string(node):
    """The value of a string literal node, or None if it is not a plain one."""
    if node.type not in ("string", "template_string") or any(c.type == "template_substitution" for c in node.named_children):
        return None
    return _text(node)[1:-1]


def _require_spec(node):
    """The module named by require("x") or import("x"), else None."""
    if node.type != "call_expression":
        return None
    fn, args = node.child_by_field_name("function"), node.child_by_field_name("arguments")
    if not fn or fn.type not in ("identifier", "import") or _text(fn) not in ("require", "import"):
        return None
    if not args or len(args.named_children) != 1:
        return None
    return _string(args.named_children[0])


def _top_level_declarator(node):
    """True for a declarator whose require() the statement pass already recorded with its names."""
    if node.type != "variable_declarator":
        return False
    holder = node.parent.parent
    return holder.type == "program" or (holder.type == "export_statement" and holder.parent.type == "program")


def _callee_name(call):
    fn = call.child_by_field_name("function")
    if fn is None:
        return None
    if fn.type == "member_expression":
        fn = fn.child_by_field_name("property")
    return _text(fn) if fn.type in ("identifier", "property_identifier") else None


def _literal_path(node):
    """The path text of a literal path expression, or None.

    Accepts a string, `new URL("./x", import.meta.url)`, `fileURLToPath(...)` of
    one, and `path.join` / `path.resolve` of strings, optionally starting with
    `__dirname`, `import.meta.dirname` or `process.cwd()`.
    """
    text = _string(node)
    if text is not None:
        return text
    ctor = node.child_by_field_name("constructor") if node.type == "new_expression" else None
    if ctor is not None and _text(ctor) == "URL":
        args = node.child_by_field_name("arguments")
        parts = args.named_children if args else []
        if len(parts) == 2 and _text(parts[1]) == "import.meta.url" and _string(parts[0]) is not None:
            return _string(parts[0])
        return None
    if node.type != "call_expression":
        return None
    args = node.child_by_field_name("arguments")
    parts = list(args.named_children) if args else []
    name = _callee_name(node)
    if name == "fileURLToPath" and len(parts) == 1:
        return _literal_path(parts[0])
    if name not in PATH_JOINS or not parts:
        return None
    if _text(parts[0]) in ("__dirname", "import.meta.dirname", "process.cwd()"):
        parts = parts[1:]
    texts = [_string(p) for p in parts]
    if not texts or None in texts:
        return None
    return "/".join(texts)


def _read_path(call):
    if _callee_name(call) not in READ_CALLS:
        return None
    args = call.child_by_field_name("arguments")
    return _literal_path(args.named_children[0]) if args and args.named_children else None


def _bound_names(node):
    """Names a declarator, parameter or pattern binds."""
    out, stack = set(), [node]
    while stack:
        n = stack.pop()
        if n.type in ("identifier", "shorthand_property_identifier_pattern"):
            out.add(_text(n))
        elif n.type == "variable_declarator":
            stack.append(n.child_by_field_name("name"))
        elif n.type in ("required_parameter", "optional_parameter"):
            stack.append(n.child_by_field_name("pattern"))
        elif n.type in ("assignment_pattern", "object_assignment_pattern"):
            stack.append(n.child_by_field_name("left"))
        elif n.type == "pair_pattern":
            stack.append(n.child_by_field_name("value"))
        elif n.type in ("object_pattern", "array_pattern", "rest_pattern", "formal_parameters"):
            stack.extend(n.named_children)
    out.discard(None)
    return out


def _scope_names(n):
    """Names a node brings into scope for its children: parameters, block declarations, loop and catch variables."""
    if n.type in FUNCTION_LIKE:
        params = n.child_by_field_name("parameters") or n.child_by_field_name("parameter")
        return _bound_names(params) if params else None
    if n.type == "statement_block":
        names = set()
        for stmt in n.named_children:
            if stmt.type in DECLARATIONS:
                for declarator in stmt.named_children:
                    names |= _bound_names(declarator)
            elif stmt.type in FUNCTIONS or stmt.type in CLASSES:
                name = stmt.child_by_field_name("name")
                if name:
                    names.add(_text(name))
        return names
    if n.type == "for_in_statement":
        left = n.child_by_field_name("left")
        return _bound_names(left) if left else None
    if n.type == "for_statement":
        init = n.child_by_field_name("initializer")
        return {name for d in init.named_children for name in _bound_names(d)} if init and init.type in DECLARATIONS else None
    if n.type == "catch_clause":
        param = n.child_by_field_name("parameter")
        return _bound_names(param) if param else None
    return None


def _shadowed(scope, name):
    while scope:
        names, scope = scope
        if name in names:
            return True
    return False


def parse(source, lang, is_test):
    """Return (definitions in source order, facts, has_parse_error).

    Each definition is a dict with qualname, name, kind (symbol or test),
    display_kind, parent (index into the list or None), start_line, end_line,
    signature and doc. Facts hold imports, exports, reexports, locals, calls and
    reads; calls and reads refer to definitions by index (see `sites`).
    """
    tree = get_parser(GRAMMARS[lang]).parse(source)
    collector = _Collector(source)
    for stmt in tree.root_node.named_children:
        collector.statement(stmt)
    if is_test:
        collector.tests(tree.root_node, None)
    calls, reads = collector.sites(tree.root_node)
    facts = {
        "imports": [i for i in collector.imports if i["spec"] is not None],
        "exports": collector.exports,
        "reexports": [r for r in collector.reexports if r["spec"] is not None],
        "locals": sorted(collector.locals),
        "calls": calls,
        "reads": reads,
    }
    return collector.defs, facts, tree.root_node.has_error

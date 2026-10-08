"""Symbols, tests, route records and resolution facts from TypeScript, TSX and JS syntax trees.

Definitions are read at the top level of a file (unwrapping `export`) and as
members of classes. Methods of an exported object literal are methods too
(`export const api = { raiseInvoice() {} }` is `api.raiseInvoice`). Facts
(imports, exports, call sites, literal file reads, literal path builds,
env var reads, Cypress visits and route records) are what `resolve.py` binds
across files; nothing is resolved here.
"""

import re

from tree_sitter_language_pack import get_parser

from cbi.parse import endpoints

GRAMMARS = {"typescript": "typescript", "tsx": "tsx", "javascript": "javascript"}
CLASSES = {"class_declaration", "abstract_class_declaration"}
FUNCTIONS = {"function_declaration", "generator_function_declaration"}
FUNCTION_VALUES = {"arrow_function", "function_expression"}
METHODS = {"method_definition", "abstract_method_signature"}
JSX = {"jsx_element", "jsx_self_closing_element", "jsx_fragment"}
TEST_CALLS = {"test", "it", "describe", "context", "specify"}
TEST_SUITES = {"describe", "context"}
TEST_SEP = " > "
NAVIGATE = {"Navigate", "Redirect"}
ROUTE_KEYS = {"path", "component", "Component", "element", "children", "redirect", "beforeEnter", "index"}
ROUTER_FACTORIES = {"createBrowserRouter", "createMemoryRouter", "createHashRouter", "createStaticRouter"}
_GUARD_CALLS = {"beforeEach", "beforeEnter"}
# `importOriginal<typeof import('../api')>()` is a type argument the TypeScript
# grammar rejects (it reads `<` as a comparison and the error swallows the rest
# of the file). `Import` is the same length, so later byte offsets still match.
_TYPEOF_IMPORT = re.compile(br"(<typeof\s+)import(\s*\()")
FUNCTION_LIKE = {"function_declaration", "generator_function_declaration", "function_expression", "function",
                 "generator_function", "arrow_function", "method_definition"}
DECLARATIONS = {"lexical_declaration", "variable_declaration"}
READ_CALLS = {"readFileSync", "readFile", "createReadStream"}
PATH_JOINS = {"join", "resolve"}
ENV_NAME = re.compile(r"[A-Z_][A-Z0-9_]*")
PROP_NAME = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")
# `as const` and parentheses wrap the object. The value underneath is what is exported.
OBJECT_WRAPS = {"as_expression", "satisfies_expression", "parenthesized_expression",
                "non_null_expression", "type_assertion"}
# A default may wrap the read: `(process.env.X as string) ?? "y"`, `process.env.X! || "y"`.
ENV_WRAPPERS = {"parenthesized_expression", "as_expression", "non_null_expression", "satisfies_expression",
                "type_assertion"}
# A wrapper around a type is not the injected class. `T | null` is unwrapped separately.
TS_WRAPPERS = {"Promise", "Array", "ReadonlyArray", "Readonly", "Record", "Map", "Set", "Partial", "Required",
               "Pick", "Omit", "Exclude", "Extract", "NonNullable", "ReturnType", "InstanceType"}


def _text(node):
    return node.text.decode(errors="replace")


def _each_keyword(fn):
    """The test keyword of `it.each` or `test.only.each`, or None."""
    props = []
    node = fn
    while node is not None and node.type == "member_expression":
        prop = node.child_by_field_name("property")
        if prop is not None:
            props.append(_text(prop))
        node = node.child_by_field_name("object")
    if node is not None and node.type == "identifier" and _text(node) in TEST_CALLS and "each" in props:
        return _text(node)
    return None


def _test_word(fn, callback):
    """The test keyword of a callee, or None.

    `it.each(rows)("name", fn)` is a call whose callee is itself a call.
    `regex.test("x")` needs a callback so it is not a test.
    """
    if fn.type == "call_expression":
        inner = fn.child_by_field_name("function")
        return _each_keyword(inner) if inner is not None else None
    if fn.type == "identifier":
        word = _text(fn)
        return word if word in TEST_CALLS else None
    if fn.type == "member_expression":
        obj, prop = fn.child_by_field_name("object"), fn.child_by_field_name("property")
        if obj is not None and obj.type == "identifier" and _text(obj) in TEST_CALLS:
            return _text(obj)  # test.skip(...), describe.only(...)
        if prop is not None and _text(prop) in TEST_CALLS and callback:
            return _text(prop)  # t.test(...) subtests
    return None


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
        self.imports = []  # {"spec", "names": {local: imported name, "default" or "*"}, "type_only"?, "type_names"?}
        self.exports = {}  # exported name -> local name
        self.reexports = []  # {"spec", "names": {exported: imported, or "*"}, or None for `export *`}
        self.fields = {}  # class def index -> {field: {"type", "param", "index"}}
        self.uses = []  # [def index, class index, field, declared type, method]
        self.route_calls = []  # identifier components, recorded as jsx calls from the route
        self.route_facts = []  # {"def", "path"?, "redirect"?, "names", "import"?}
        self.objects = []  # (name, object node, declarator, doc anchor, keyword) for a top-level object literal

    def add(self, node, name, display_kind, parent, signature, doc, kind="symbol", attrs=None):
        qualname = name if parent is None else f"{self.defs[parent]['qualname']}{TEST_SEP if kind == 'test' else '.'}{name}"
        defin = {
            "qualname": qualname,
            "name": name,
            "kind": kind,
            "display_kind": display_kind,
            "parent": parent,
            "start_line": node.start_point.row + 1,
            "end_line": node.end_point.row + 1,
            "signature": signature,
            "doc": doc,
        }
        if attrs:
            defin["attrs"] = attrs
        self.defs.append(defin)
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
            self.fields[index] = _injected_fields(body)
            for member in body.named_children if body else ():
                self.member(member, index)
        elif decl.type in FUNCTIONS and name_node:
            name = _text(name_node)
            kind = "component" if name[:1].isupper() and body and _has_jsx(body) else "function"
            self.add(decl, name, kind, None, _signature(self.source, decl, body), _doc(doc_anchor))
        elif decl.type == "interface_declaration" and name_node:
            index = self.add(decl, _text(name_node), "interface", None, _signature(self.source, decl, body), _doc(doc_anchor))
            for member in body.named_children if body else ():
                self.interface_member(member, index)
        elif decl.type in DECLARATIONS:
            keyword = _text(decl.child(0))
            for declarator in decl.named_children:
                value = declarator.child_by_field_name("value")
                name_node = declarator.child_by_field_name("name")
                if declarator.type != "variable_declarator" or not value or not name_node or name_node.type != "identifier":
                    continue
                name = _text(name_node)
                obj = _as_object(value)
                if obj is not None:
                    self.objects.append((name, obj, declarator, doc_anchor, keyword))
                    continue
                if value.type not in FUNCTION_VALUES:
                    continue
                fbody = value.child_by_field_name("body")
                kind = "component" if name[:1].isupper() and fbody and _has_jsx(fbody) else "function"
                signature = f"{keyword} {_signature(self.source, declarator, fbody)}"
                self.add(declarator, name, kind, None, signature, _doc(doc_anchor))

    def exported_objects(self):
        """Methods of an exported object literal. A config object with no function is left alone.

        The const is a symbol so `api.raiseInvoice()` resolves through the same member
        lookup a class method uses. Nested objects are not walked.
        """
        exported = set(self.exports.values())
        for name, obj, declarator, doc_anchor, keyword in self.objects:
            if name not in exported:
                continue
            methods = _object_methods(obj)
            if not methods:
                continue
            parent = self.add(declarator, name, "object", None, f"{keyword} {name}", _doc(doc_anchor))
            for node, method, body in methods:
                self.add(node, method, "method", parent, _signature(self.source, node, body), _doc(node))

    def import_statement(self, stmt):
        source = stmt.child_by_field_name("source")
        if not source:
            return
        names, type_names = {}, []
        whole = any(c.type == "type" for c in stmt.children)
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
                        local = _text(alias or name)
                        names[local] = _text(name)
                        if any(ch.type == "type" for ch in spec.children):
                            type_names.append(local)
        rec = {"spec": _string(source), "names": names}
        if whole:
            rec["type_only"] = True
        elif type_names:
            rec["type_names"] = type_names
        self.imports.append(rec)

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
            whole = any(c.type == "type" for c in stmt.children)
            type_names = []
            if clause:
                names = {}
                for spec in clause.named_children:
                    if spec.type != "export_specifier":
                        continue
                    name, alias = spec.child_by_field_name("name"), spec.child_by_field_name("alias")
                    exported = _text(alias or name)
                    names[exported] = _text(name)
                    if any(c.type == "type" for c in spec.children):
                        type_names.append(exported)
            else:
                ns = next((c for c in stmt.named_children if c.type == "namespace_export"), None)
                names = {_text(ns.named_children[0]): "*"} if ns else None
            rec = {"spec": _string(source), "names": names}
            if whole:
                rec["type_only"] = True
            elif type_names:
                rec["type_names"] = type_names
            self.reexports.append(rec)
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

    def interface_member(self, member, parent):
        """A method signature, or a property whose type is a function, is a method of the interface."""
        name = member.child_by_field_name("name")
        if not name:
            return
        if member.type == "method_signature" or (member.type == "property_signature" and _function_property(member)):
            self.add(member, _text(name), "method", parent, _signature(self.source, member, None), _doc(member))

    def tests(self, node, parent):
        """Test cases: test(...), it(...), describe(...), context(...), specify(...),
        test.skip(...), t.test(...), and vitest or jest `it.each(rows)("name", fn)`.
        `describe` and `context` are suites; the others are cases."""
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
        word = _test_word(fn, callback)
        if not word or first.type not in ("string", "template_string"):
            return None
        end = callback.child_by_field_name("body") if callback else None
        signature = _between(self.source, call.start_byte, end.start_byte if end else call.end_byte)
        display_kind = "test suite" if word in TEST_SUITES else "test case"
        return self.add(call, _text(first)[1:-1], display_kind, parent, signature, None, kind="test")

    def commands(self, root):
        """`Cypress.Commands.add('name', fn)` is a function named `name`."""
        stack = [root]
        while stack:
            node = stack.pop()
            if node.type == "call_expression" and _commands_add(node):
                args = node.child_by_field_name("arguments")
                parts = args.named_children if args else []
                name = _string(parts[0]) if parts else None
                if name:
                    callback = next((part for part in parts[1:] if part.type in FUNCTION_VALUES), None)
                    body = callback.child_by_field_name("body") if callback else None
                    signature = _between(self.source, node.start_byte, body.start_byte if body else node.end_byte)
                    self.add(node, name, "function", None, signature, None)
            stack.extend(node.named_children)

    def routes(self, root):
        """Vue Router objects and React `<Route>` / `createBrowserRouter` records.

        Each record is a symbol with display kind `route`. Its attrs hold the full
        path, a redirect, and guard targets. Identifier components become jsx calls
        from the route; JSX tags are calls once `sites` walks the anchored record.
        """
        file_guards = _file_guards(root)

        def take_object(obj, parent_path):
            pairs = _pairs(obj)
            if not pairs.keys() & ROUTE_KEYS:
                return
            self._route(obj, parent_path, pairs, file_guards)
            children = pairs.get("children")
            if children is not None and children.type == "array":
                full = self.route_facts[-1].get("path")
                walk_array(children, full if full else parent_path)

        def walk_array(array, parent_path):
            for element in array.named_children:
                if element.type == "object":
                    take_object(element, parent_path)

        def walk(node):
            if node.type == "pair":
                key, value = node.child_by_field_name("key"), node.child_by_field_name("value")
                if _key_name(key) == "routes" and value is not None and value.type == "array":
                    walk_array(value, None)
                    return
            if node.type == "variable_declarator":
                name, value = node.child_by_field_name("name"), node.child_by_field_name("value")
                if (name is not None and name.type == "identifier" and _text(name) == "routes"
                        and value is not None and value.type == "array"):
                    walk_array(value, None)
                    return
            if node.type == "call_expression":
                fn = node.child_by_field_name("function")
                args = node.child_by_field_name("arguments")
                if (fn is not None and fn.type == "identifier" and _text(fn) in ROUTER_FACTORIES
                        and args and args.named_children and args.named_children[0].type == "array"):
                    walk_array(args.named_children[0], None)
                    return
            if node.type in ("jsx_element", "jsx_self_closing_element") and _jsx_tag(node) == "Route":
                self._jsx_route(node, None, file_guards)
                return
            for child in node.named_children:
                walk(child)

        walk(root)

    def _route(self, node, parent_path, pairs, file_guards):
        path = _path_text(pairs.get("path"))
        index = pairs.get("index") is not None and pairs["index"].type == "true"
        full = _full_path(parent_path, path, index)
        names, direct, spec, redirect = [], [], None, _path_text(pairs.get("redirect"))
        for key in ("component", "Component", "element"):
            if key not in pairs:
                continue
            got, lazy, nav, is_direct = _components_of(pairs[key])
            names.extend(got)
            if is_direct:
                direct.extend(got)
            spec = spec or lazy
            redirect = redirect or nav
        meta = _pairs(pairs["meta"]) if pairs.get("meta") is not None and pairs["meta"].type == "object" else {}
        public = meta.get("public") is not None and meta["public"].type == "true"
        self._finish_route(
            node, full, names, direct, redirect, index, spec, file_guards, public, "flag" in meta,
            _guard_returns(pairs.get("beforeEnter")),
        )

    def _jsx_route(self, node, parent_path, file_guards):
        attrs = _jsx_attrs(node)
        element = _attr_expr(attrs.get("element"))
        got, lazy, nav, is_direct = _components_of(element) if element is not None else ([], None, None, False)
        full = _full_path(parent_path, _path_text(_attr_expr(attrs.get("path"))), "index" in attrs)
        meta = _attr_expr(attrs.get("meta"))
        meta_pairs = _pairs(meta) if meta is not None and meta.type == "object" else {}
        public = meta_pairs.get("public") is not None and meta_pairs["public"].type == "true"
        self._finish_route(
            node, full, got, got if is_direct else [], nav or _path_text(_attr_expr(attrs.get("redirect"))),
            "index" in attrs, lazy, file_guards, public, "flag" in meta_pairs,
            _guard_returns(_attr_expr(attrs.get("beforeEnter"))),
        )
        child_path = full if full else parent_path
        for child in node.named_children:
            if child.type in ("jsx_element", "jsx_self_closing_element") and _jsx_tag(child) == "Route":
                self._jsx_route(child, child_path, file_guards)

    def _finish_route(self, node, full, names, direct, redirect, index, spec, file_guards, public, flag, guards):
        names = [name for name in names if name not in NAVIGATE and name != "Route"]
        direct = [name for name in direct if name not in NAVIGATE and name != "Route"]
        guard = [item for scope, item in guards if scope != "public"]
        if full is not None:
            for scope, item in file_guards:
                if (scope == "flag" and flag) or (scope == "auth" and not public) or scope == "always":
                    guard.append(item)
        guard = list(dict.fromkeys(guard))
        label = full if full else ("layout:" + names[0] if names else "layout")
        signature = "route " + label
        if names:
            signature += " " + names[0]
        if redirect:
            signature += " -> " + redirect
        if index:
            signature += " index"
        attrs = {}
        if full is not None:
            attrs["path"] = full
        if redirect:
            attrs["redirect"] = redirect
        if guard:
            attrs["guard"] = guard
        index_def = self.add(node, label, "route", None, signature, None, attrs=attrs or None)
        for name in direct:
            self.route_calls.append([index_def, None, "name", name, None, "jsx"])
        self.route_facts.append({
            "def": index_def, "path": full, "redirect": redirect or None, "names": names, "import": spec,
        })

    def sites(self, root):
        """Call sites and literal file reads, with the innermost definition around each.

        A call is kept only when its callee could bind: a top-level name or import
        that no parameter or local variable shadows, or `this.x` inside a class.
        Calls are [def index or None, class index or None, shape, name, member]
        and, when the site is a JSX tag or a createElement type, a trailing "jsx".
        Shape is `name` (f(), new F(), <F />), `this` (this.f()) or `member`
        (ns.f(), Class.f(), <ns.Foo />). Reads are [def index or None, path].
        Paths are [anchor, path] for a literal path build (`dirname`, `cwd`
        or `file`). Env reads are [def index or None, name, default or None]. A
        `...process.env` spread is `*` with no definition, so it stays on the file.
        """
        bindings = self.locals | {local for imp in self.imports for local in imp["names"]}
        calls, reads, envs, paths, visits = [], [], [], [], []
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
            anchored = _anchored_path(n) if n.type in ("call_expression", "new_expression") else None
            if anchored:
                paths.append(list(anchored))
            callee, via = None, None
            if n.type == "call_expression":
                callee = n.child_by_field_name("function")
                read = _read_path(n)
                if read:
                    reads.append([d, read])
                spec = _require_spec(n)
                if spec is not None and not _top_level_declarator(n.parent):
                    self.imports.append({"spec": spec, "names": {}})  # import("./x"), nested require
                element = _element_name(n)
                if element and element in bindings and not _shadowed(scope, element):
                    calls.append([d, c, "name", element, None, "jsx"])
            elif n.type == "new_expression":
                callee = n.child_by_field_name("constructor")
            elif n.type in ("jsx_opening_element", "jsx_self_closing_element"):
                callee = n.child_by_field_name("name")
                via = "jsx"
            if callee is not None:
                if callee.type == "identifier":
                    name = _text(callee)
                    if name in bindings and not _shadowed(scope, name):
                        calls.append([d, c, "name", name, None, *([via] if via else [])])
                elif callee.type == "member_expression":
                    obj, prop = callee.child_by_field_name("object"), callee.child_by_field_name("property")
                    if (obj is not None and obj.type == "identifier" and _text(obj) == "cy"
                            and prop is not None and not _shadowed(scope, "cy")):
                        member = _text(prop)
                        if member == "visit":
                            pattern = _visit_pattern(n)
                            if pattern:
                                visits.append([d, pattern])
                        else:
                            calls.append([d, None, "cy", member, None])
                    else:
                        field = _receiver_field(obj)
                        if obj is not None and obj.type == "this" and c is not None and prop is not None:
                            calls.append([d, c, "this", _text(prop), None])
                        elif field and c is not None and prop is not None:
                            info = self.fields.get(c, {}).get(field)
                            if info:
                                self.uses.append([d, c, field, info["type"], _text(prop)])
                        elif obj is not None and obj.type == "identifier" and _text(obj) in bindings and not _shadowed(scope, _text(obj)):
                            calls.append([d, c, "member", _text(obj), _text(prop), *([via] if via else [])])
            if n.type == "spread_element" and n.named_children and _is_process_env(n.named_children[0]):
                if not _process_hidden(self, scope):
                    envs.append([None, "*", None])
            else:
                found = _env_read(n)
                if found and not _env_written(n):
                    source, name = found
                    if source == "meta" or not _process_hidden(self, scope):
                        envs.append([d, name, _string_default(n)])
            for child in reversed(n.named_children):
                stack.append((child, d, c, scope))
        return calls, reads, envs, paths, visits


def _as_object(node):
    """The object literal under `as` / `satisfies` / parentheses, or None."""
    for _ in range(5):
        if node is None or node.type not in OBJECT_WRAPS:
            break
        node = next(iter(node.named_children), None)
    return node if node is not None and node.type == "object" else None


def _prop_name(node):
    """An identifier property name, or None for a computed or non-identifier key."""
    if node is None:
        return None
    if node.type in ("property_identifier", "identifier"):
        text = _text(node)
        return text if PROP_NAME.match(text) else None
    if node.type == "string":
        raw = _text(node)
        if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
            raw = raw[1:-1]
        return raw if PROP_NAME.match(raw) else None
    return None


def _object_methods(obj):
    """Direct method and arrow-function properties of one object literal."""
    found = []
    for child in obj.named_children:
        if child.type == "method_definition":
            name = _prop_name(child.child_by_field_name("name"))
            if name:
                found.append((child, name, child.child_by_field_name("body")))
        elif child.type == "pair":
            value = child.child_by_field_name("value")
            if value is not None and value.type in FUNCTION_VALUES:
                name = _prop_name(child.child_by_field_name("key"))
                if name:
                    found.append((child, name, value.child_by_field_name("body")))
    return found


def _process_hidden(collector, scope):
    """True when a local or parameter named `process` hides the global."""
    return "process" in collector.locals or _shadowed(scope, "process")


def _is_process_env(node):
    """True for the member expression `process.env` itself."""
    if node is None or node.type != "member_expression":
        return False
    obj, prop = node.child_by_field_name("object"), node.child_by_field_name("property")
    return obj is not None and obj.type == "identifier" and _text(obj) == "process" and prop is not None and _text(prop) == "env"


def _is_import_meta_env(node):
    """True for the member expression `import.meta.env` itself."""
    if node is None or node.type != "member_expression":
        return False
    obj, prop = node.child_by_field_name("object"), node.child_by_field_name("property")
    return (obj is not None and obj.type == "meta_property" and _text(obj) == "import.meta"
            and prop is not None and _text(prop) == "env")


def _env_read(node):
    """`("process"|"meta", NAME)` for `process.env.NAME`, `process.env["NAME"]` or `import.meta.env`, else None.

    NAME must match `[A-Z_][A-Z0-9_]*`. The object `process.env` itself is not a named read.
    """
    if node.type == "member_expression":
        obj, prop = node.child_by_field_name("object"), node.child_by_field_name("property")
        name = _text(prop) if prop is not None else None
    elif node.type == "subscript_expression":
        obj, index = node.child_by_field_name("object"), node.child_by_field_name("index")
        name = _string(index) if index is not None else None
    else:
        return None
    if not name or not ENV_NAME.fullmatch(name) or obj is None:
        return None
    if _is_process_env(obj):
        return ("process", name)
    if _is_import_meta_env(obj):
        return ("meta", name)
    return None


def _env_written(node):
    """True when the expression is the target of an assignment or `delete`, not a read."""
    parent = node.parent
    if parent is None:
        return False
    # `==` not `is`: child_by_field_name returns a new wrapper each call.
    if parent.type == "assignment_expression" and parent.child_by_field_name("left") == node:
        return True
    if parent.type == "unary_expression" and parent.child_count and _text(parent.child(0)) == "delete":
        return True
    return False


def _string_default(node):
    """The string literal on the right of `??` or `||` when `node` is the left, looking through wrappers."""
    cur = node
    while cur.parent is not None and cur.parent.type in ENV_WRAPPERS:
        cur = cur.parent
    parent = cur.parent
    # `==` not `is`: child_by_field_name returns a new wrapper each call.
    if parent is None or parent.type != "binary_expression" or parent.child_by_field_name("left") != cur:
        return None
    op = parent.child_by_field_name("operator")
    if op is None or _text(op) not in ("??", "||"):
        return None
    return _string(parent.child_by_field_name("right"))


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


def _anchored_path(node):
    """(anchor, path) when node builds a literal path, else None.

    anchor is `dirname` (`__dirname`, `import.meta.dirname`), `cwd`
    (`process.cwd()`) or `file` (`new URL(..., import.meta.url)`, or
    `path.join` / `path.resolve` of strings). A bare string is not a path.
    """
    ctor = node.child_by_field_name("constructor") if node.type == "new_expression" else None
    if ctor is not None and _text(ctor) == "URL":
        args = node.child_by_field_name("arguments")
        parts = args.named_children if args else []
        if len(parts) == 2 and _text(parts[1]) == "import.meta.url":
            text = _string(parts[0])
            return ("file", text) if text else None
        return None
    if node.type != "call_expression":
        return None
    args = node.child_by_field_name("arguments")
    parts = list(args.named_children) if args else []
    name = _callee_name(node)
    if name == "fileURLToPath" and len(parts) == 1:
        return _anchored_path(parts[0])
    fn = node.child_by_field_name("function")
    if fn is None or fn.type != "member_expression" or name not in PATH_JOINS or not parts:
        return None
    obj = fn.child_by_field_name("object")
    if obj is None or obj.type != "identifier" or _text(obj) != "path":
        return None
    anchor = "file"
    if _text(parts[0]) in ("__dirname", "import.meta.dirname"):
        anchor, parts = "dirname", parts[1:]
    elif _text(parts[0]) == "process.cwd()":
        anchor, parts = "cwd", parts[1:]
    texts = [_string(p) for p in parts]
    if not texts or None in texts:
        return None
    return anchor, "/".join(texts)


def _read_path(call):
    if _callee_name(call) not in READ_CALLS:
        return None
    args = call.child_by_field_name("arguments")
    return _literal_path(args.named_children[0]) if args and args.named_children else None


def _element_name(call):
    """The component identifier in createElement(X) or React.createElement(X), else None."""
    fn = call.child_by_field_name("function")
    args = call.child_by_field_name("arguments")
    if not fn or not args or not args.named_children:
        return None
    if fn.type == "identifier":
        matched = _text(fn) == "createElement"
    elif fn.type == "member_expression":
        obj, prop = fn.child_by_field_name("object"), fn.child_by_field_name("property")
        matched = (obj is not None and prop is not None and obj.type == "identifier"
                   and _text(obj) == "React" and _text(prop) == "createElement")
    else:
        return None
    first = args.named_children[0]
    return _text(first) if matched and first.type == "identifier" else None


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


def _ts_type_name(node):
    """A single type name, unwrapping `T | null` and `T | undefined`. Anything else is None."""
    if node is None:
        return None
    if node.type == "type_annotation":
        node = next(iter(node.named_children), None)
        if node is None:
            return None
    if node.type == "predefined_type" or (node.type == "literal_type" and _text(node) in ("null", "undefined")):
        return None
    if node.type in ("type_identifier", "identifier"):
        return _text(node)
    if node.type == "generic_type":
        name = node.child_by_field_name("name") or (node.named_children[0] if node.named_children else None)
        if name is not None and name.type in ("type_identifier", "identifier") and _text(name) not in TS_WRAPPERS:
            return _text(name)
        return None
    if node.type == "parenthesized_type" and node.named_children:
        return _ts_type_name(node.named_children[0])
    if node.type == "union_type":
        names = []
        for part in node.named_children:
            if part.type == "literal_type" and _text(part) in ("null", "undefined"):
                continue
            if part.type == "predefined_type" and _text(part) == "undefined":
                continue
            name = _ts_type_name(part)
            if not name:
                return None
            names.append(name)
        return names[0] if len(names) == 1 else None
    return None


def _function_property(member):
    """True when a property signature's type is a function."""
    ann = member.child_by_field_name("type")
    stack = list(ann.named_children) if ann else []
    while stack:
        n = stack.pop()
        if n.type in ("function_type", "arrow_function"):
            return True
        if n.type in ("parenthesized_type", "type_annotation"):
            stack.extend(n.named_children)
    return False


def _param_name(param):
    pattern = param.child_by_field_name("pattern")
    if pattern is None or pattern.type != "identifier":
        pattern = next((c for c in param.named_children if c.type == "identifier"), None)
    return _text(pattern) if pattern is not None and pattern.type == "identifier" else None


def _param_prop(param):
    return any(c.type in ("accessibility_modifier", "readonly") for c in param.children)


def _injected_fields(body):
    """Constructor parameter properties and `this.field = param` assignments, with the field's type.

    The type is the field's annotation when it has one, else the parameter's. A union other than
    `T | null` or `T | undefined` records nothing.
    """
    declared = {}
    constructor = None
    for member in body.named_children if body else ():
        if member.type in ("public_field_definition", "field_definition"):
            name = member.child_by_field_name("name") or member.child_by_field_name("property")
            typ = _ts_type_name(member.child_by_field_name("type") or _type_annotation(member))
            if name is not None and typ:
                declared[_text(name)] = typ
        elif member.type in METHODS:
            name = member.child_by_field_name("name")
            if name is not None and _text(name) == "constructor":
                constructor = member
    if constructor is None:
        return {}
    params = []
    formal = constructor.child_by_field_name("parameters")
    for param in formal.named_children if formal else ():
        if param.type not in ("required_parameter", "optional_parameter"):
            continue
        name = _param_name(param)
        if not name:
            continue
        params.append((name, _ts_type_name(param.child_by_field_name("type") or _type_annotation(param)), _param_prop(param)))
    fields = {}
    for index, (name, typ, prop) in enumerate(params):
        chosen = declared.get(name) or typ
        if prop and chosen:
            fields[name] = {"type": chosen, "param": name, "index": index}
    by_name = {name: (index, typ) for index, (name, typ, _) in enumerate(params)}
    ctor_body = constructor.child_by_field_name("body")
    stack = list(ctor_body.named_children) if ctor_body else []
    while stack:
        n = stack.pop()
        if n.type in FUNCTION_LIKE or n.type in CLASSES:
            continue
        if n.type == "assignment_expression":
            left, right = n.child_by_field_name("left"), n.child_by_field_name("right")
            field = _receiver_field(left)
            if field and right is not None and right.type == "identifier" and _text(right) in by_name:
                index, typ = by_name[_text(right)]
                chosen = declared.get(field) or typ
                if chosen:
                    fields[field] = {"type": chosen, "param": _text(right), "index": index}
            continue
        stack.extend(n.named_children)
    return fields


def _type_annotation(node):
    return next((c for c in node.named_children if c.type == "type_annotation"), None)


def _receiver_field(node):
    """The field name of `this.field`, else None."""
    if node is None or node.type != "member_expression":
        return None
    obj, prop = node.child_by_field_name("object"), node.child_by_field_name("property")
    if obj is not None and obj.type == "this" and prop is not None:
        return _text(prop)
    return None


def _expr_type(node, lookup):
    """The class name an argument expression names, from a binding, `new Foo` or `Foo()`."""
    if node is None:
        return None
    if node.type == "identifier":
        return lookup(_text(node))
    if node.type == "parenthesized_expression" and node.named_children:
        return _expr_type(node.named_children[0], lookup)
    if node.type == "new_expression":
        ctor = node.child_by_field_name("constructor")
        return _text(ctor) if ctor is not None and ctor.type == "identifier" else None
    if node.type == "call_expression":
        fn = node.child_by_field_name("function")
        return _text(fn) if fn is not None and fn.type == "identifier" else None
    if node.type == "as_expression":
        return _expr_type(node.child_by_field_name("expression") or (node.named_children[0] if node.named_children else None), lookup)
    return None


def _lookup(scopes, name):
    for scope in reversed(scopes):
        if name in scope:
            return scope[name] or None
    return None


def _param_scope(node):
    params = node.child_by_field_name("parameters") or node.child_by_field_name("parameter")
    scope = {}
    for param in params.named_children if params else ():
        if param.type not in ("required_parameter", "optional_parameter"):
            continue
        name = _param_name(param)
        if name:
            scope[name] = _ts_type_name(param.child_by_field_name("type") or _type_annotation(param)) or ""
    return scope


def _constructs(root):
    """`new Foo(...)` and `Foo(...)` whose arguments name a type. Each is [class, [[keyword or None, type or None]]]."""
    found = []

    def walk(node, scopes):
        entered = scopes
        if node.type in FUNCTION_LIKE:
            entered = [*scopes, _param_scope(node)]
        elif node.type == "statement_block":
            entered = [*scopes, {}]
        elif node.type == "for_in_statement":
            # `for (const port of xs)` is a bare name, not a declarator, and it hides an outer port.
            left = node.child_by_field_name("left")
            entered = [*scopes, {name: "" for name in (_bound_names(left) if left else ())}]
        elif node.type == "for_statement":
            entered = [*scopes, {}]
        elif node.type == "catch_clause":
            param = node.child_by_field_name("parameter")
            entered = [*scopes, {name: "" for name in (_bound_names(param) if param else ())}]
        callee = None
        if node.type == "new_expression":
            ctor = node.child_by_field_name("constructor")
            callee = _text(ctor) if ctor is not None and ctor.type == "identifier" else None
        elif node.type == "call_expression":
            fn = node.child_by_field_name("function")
            callee = _text(fn) if fn is not None and fn.type == "identifier" else None
        if callee:
            args_node = node.child_by_field_name("arguments")
            args = [[None, _expr_type(arg, lambda name: _lookup(entered, name))]
                    for arg in (args_node.named_children if args_node else [])]
            if any(typ for _, typ in args):
                found.append([callee, args])
        for child in node.named_children:
            walk(child, entered)
        _bind_ts(node, entered)

    walk(root, [{}])
    return found


def _bind_ts(node, scopes):
    if node.type == "variable_declarator":
        name = node.child_by_field_name("name")
        if name is not None and name.type == "identifier":
            typ = _ts_type_name(node.child_by_field_name("type")) or _expr_type(node.child_by_field_name("value"), lambda n: None)
            scopes[-1][_text(name)] = typ or ""
    elif node.type == "assignment_expression":
        left = node.child_by_field_name("left")
        if left is not None and left.type == "identifier":
            typ = _expr_type(node.child_by_field_name("right"), lambda n: None)
            scopes[-1][_text(left)] = typ or ""


def _tree(source, lang):
    """Parse source. A `<typeof import(...)>` type argument is rewritten when that is what fails.

    `Import` is the same length as `import`, so node byte offsets still address `source`.
    """
    tree = get_parser(GRAMMARS[lang]).parse(source)
    if not tree.root_node.has_error:
        return tree, False
    relaxed = _TYPEOF_IMPORT.sub(br"\1Import\2", source)
    if relaxed == source:
        return tree, True
    other = get_parser(GRAMMARS[lang]).parse(relaxed)
    if other.root_node.has_error:
        return tree, True
    return other, False


def _commands_add(node):
    """True for `Cypress.Commands.add(...)`."""
    fn = node.child_by_field_name("function")
    if fn is None or fn.type != "member_expression":
        return False
    prop = fn.child_by_field_name("property")
    obj = fn.child_by_field_name("object")
    if prop is None or _text(prop) != "add" or obj is None or obj.type != "member_expression":
        return False
    mid = obj.child_by_field_name("property")
    base = obj.child_by_field_name("object")
    return (mid is not None and _text(mid) == "Commands" and base is not None
            and base.type == "identifier" and _text(base) == "Cypress")


def _key_name(key):
    if key is None:
        return None
    if key.type in ("property_identifier", "identifier", "string"):
        return _string(key) if key.type == "string" else _text(key)
    return None


def _pairs(obj):
    """Property name to value for an object, including method shorthand."""
    out = {}
    if obj is None or obj.type != "object":
        return out
    for child in obj.named_children:
        if child.type == "pair":
            name = _key_name(child.child_by_field_name("key"))
            value = child.child_by_field_name("value")
            if name and value is not None:
                out[name] = value
        elif child.type in METHODS:
            name = child.child_by_field_name("name")
            if name is not None:
                out[_text(name)] = child
    return out


def _clean_path(text):
    if not text:
        return None
    text = text.split("?", 1)[0].split("#", 1)[0]
    return text or None


def _template_pattern(node):
    parts = []
    for child in node.children:
        if child.type == "string_fragment":
            parts.append(_text(child))
        elif child.type == "template_substitution":
            parts.append("*")
    return _clean_path("".join(parts))


def _path_text(node):
    """A path or redirect: a string, a template with holes as `*`, `{ path }`, or a function that returns one."""
    if node is None:
        return None
    if node.type == "string":
        return _clean_path(_string(node))
    if node.type == "template_string":
        return _template_pattern(node)
    if node.type == "object":
        return _path_text(_pairs(node).get("path"))
    if node.type in FUNCTION_VALUES or node.type in METHODS:
        body = node.child_by_field_name("body")
        if body is None:
            return None
        if body.type != "statement_block":
            return _path_text(body)
        for child in body.named_children:
            if child.type == "return_statement":
                found = _return_path(child)
                if found:
                    return found
        return None
    if node.type == "parenthesized_expression" and node.named_children:
        return _path_text(node.named_children[0])
    return None


def _return_path(node):
    child = next((c for c in node.named_children), None)
    return _path_text(child) if child is not None else None


def _full_path(parent, path, index):
    """Join a route path onto its parent. None is a layout with no path of its own."""
    if path is None and not index:
        return None
    path = "" if path is None else path
    if path.startswith("/"):
        return path
    if path == "*" and parent is None:
        return "*"
    if parent is None:
        return "/" if path == "" else "/" + path
    base = (parent or "/").rstrip("/")
    if path == "":
        return parent or "/"
    return (base or "") + "/" + path


def _jsx_container(node):
    if node.type == "jsx_self_closing_element":
        return node
    return next((c for c in node.named_children if c.type == "jsx_opening_element"), None)


def _jsx_tag(node):
    container = _jsx_container(node)
    if container is None:
        return None
    name = next((c for c in container.children if c.type == "identifier"), None)
    return _text(name) if name is not None else None


def _jsx_attrs(node):
    container = _jsx_container(node)
    out = {}
    if container is None:
        return out
    for child in container.children:
        if child.type != "jsx_attribute":
            continue
        name = next((c for c in child.children if c.type == "property_identifier"), None)
        if name is not None:
            out[_text(name)] = child
    return out


def _attr_expr(attr):
    """The string or expression an attribute holds. A valueless attribute has none."""
    if attr is None:
        return None
    for child in attr.children:
        if child.type == "string":
            return child
        if child.type == "jsx_expression":
            return next((c for c in child.named_children), None)
    return None


def _navigate_target(node):
    found = []

    def walk(current):
        if current.type in ("jsx_element", "jsx_self_closing_element"):
            if _jsx_tag(current) in NAVIGATE:
                path = _path_text(_attr_expr(_jsx_attrs(current).get("to")))
                if path:
                    found.append(path)
                return
        for child in current.named_children:
            walk(child)

    walk(node)
    return found[0] if found else None


def _lazy_spec(fn):
    """The module named by `import("./x")` inside a route component function."""
    stack = [fn]
    while stack:
        node = stack.pop()
        if node is not fn and node.type in FUNCTION_LIKE:
            continue
        if node.type == "call_expression":
            callee = node.child_by_field_name("function")
            if callee is not None and callee.type == "import":
                spec = _require_spec(node)
                if spec:
                    return spec
        stack.extend(node.named_children)
    return None


def _components_of(value):
    """(names, lazy import spec, navigate target, value is a bare identifier)."""
    if value is None:
        return [], None, None, False
    if value.type == "identifier":
        return [_text(value)], None, None, True
    if value.type in ("jsx_element", "jsx_self_closing_element"):
        tag = _jsx_tag(value)
        return ([tag] if tag else []), None, _navigate_target(value), False
    if value.type == "jsx_expression" and value.named_children:
        return _components_of(value.named_children[0])
    if value.type in FUNCTION_VALUES or value.type in METHODS:
        return [], _lazy_spec(value), None, False
    if value.type == "parenthesized_expression" and value.named_children:
        return _components_of(value.named_children[0])
    return [], None, None, False


def _is_meta(obj):
    if obj is None:
        return False
    if obj.type == "identifier" and _text(obj) == "meta":
        return True
    if obj.type == "member_expression":
        prop = obj.child_by_field_name("property")
        return prop is not None and _text(prop) == "meta"
    return False


def _condition_scope(node):
    """`flag` when the condition reads `to.meta.flag`, `public` for `to.meta.public`, else `auth`."""
    flag = public = False
    stack = [node] if node is not None else []
    while stack:
        current = stack.pop()
        if current.type == "member_expression":
            prop = current.child_by_field_name("property")
            obj = current.child_by_field_name("object")
            if prop is not None and _is_meta(obj):
                if _text(prop) == "flag":
                    flag = True
                elif _text(prop) == "public":
                    public = True
        stack.extend(current.named_children)
    if flag:
        return "flag"
    if public:
        return "public"
    return "auth"


def _next_path(node):
    if node.type != "call_expression":
        return None
    fn = node.child_by_field_name("function")
    if fn is None or fn.type != "identifier" or _text(fn) != "next":
        return None
    args = node.child_by_field_name("arguments")
    if not args or not args.named_children:
        return None
    return _path_text(args.named_children[0])


def _guard_returns(fn):
    """(scope, path) for string returns and `next(path)` inside a guard. `public` returns are kept for the caller to drop."""
    if fn is None or fn.type not in FUNCTION_VALUES | METHODS:
        return []
    body = fn.child_by_field_name("body")
    if body is None:
        return []
    if body.type != "statement_block":
        path = _path_text(body)
        return [("always", path)] if path else []
    found = []

    def walk(current, scope):
        if current.type in FUNCTION_LIKE or current.type in CLASSES:
            return
        if current.type == "if_statement":
            kind = _condition_scope(current.child_by_field_name("condition"))
            cons = current.child_by_field_name("consequence")
            alt = current.child_by_field_name("alternative")
            if kind == "public":
                if cons:
                    walk(cons, "public")
                if alt:
                    walk(alt, "auth")
            else:
                if cons:
                    walk(cons, kind)
                if alt:
                    walk(alt, scope)
            return
        path = _return_path(current) if current.type == "return_statement" else _next_path(current)
        if path and scope != "public":
            found.append((scope, path))
            return
        for child in current.named_children:
            walk(child, scope)

    walk(body, "always")
    return found


def _guard_call(node):
    fn = node.child_by_field_name("function")
    if fn is None or fn.type != "member_expression":
        return False
    prop = fn.child_by_field_name("property")
    return prop is not None and _text(prop) in _GUARD_CALLS


def _file_guards(root):
    """Redirects from `router.beforeEach` / `router.beforeEnter`. Mocha `beforeEach(fn)` is not a member call."""
    found = []
    stack = [root]
    while stack:
        node = stack.pop()
        if node.type == "call_expression" and _guard_call(node):
            args = node.child_by_field_name("arguments")
            fn = next((a for a in (args.named_children if args else ())
                       if a.type in FUNCTION_VALUES or a.type in METHODS), None)
            found.extend(_guard_returns(fn))
            continue
        stack.extend(node.named_children)
    return found


def _visit_pattern(call):
    """The path `cy.visit` names. A template hole is `*`. A fully dynamic path is skipped."""
    args = call.child_by_field_name("arguments")
    if not args or not args.named_children:
        return None
    arg = args.named_children[0]
    if arg.type == "string":
        text = _clean_path(_string(arg))
    elif arg.type == "template_string":
        text = _template_pattern(arg)
    else:
        return None
    if not text or not text.startswith("/"):
        return None
    holes = [part for part in text.split("/") if part]
    if holes and all(part == "*" for part in holes):
        return None
    return text


def parse(source, lang, is_test):
    """Return (definitions in source order, facts, has_parse_error).

    Each definition is a dict with qualname, name, kind (symbol or test),
    display_kind, parent (index into the list or None), start_line, end_line,
    signature and doc. Facts hold imports, exports, reexports, locals, calls,
    reads and env reads; calls, reads and env reads refer to definitions by
    index (see `sites`). Visits and route records are present only when the
    file has them.
    """
    tree, has_error = _tree(source, lang)
    collector = _Collector(source)
    for stmt in tree.root_node.named_children:
        collector.statement(stmt)
    collector.exported_objects()
    if is_test:
        collector.tests(tree.root_node, None)
    collector.commands(tree.root_node)
    collector.routes(tree.root_node)
    calls, reads, envs, paths, visits = collector.sites(tree.root_node)
    calls.extend(collector.route_calls)
    facts = {
        "imports": [i for i in collector.imports if i["spec"] is not None],
        "exports": collector.exports,
        "reexports": [r for r in collector.reexports if r["spec"] is not None],
        "locals": sorted(collector.locals),
        "calls": calls,
        "reads": reads,
        "envs": envs,
        "paths": paths,
        "uses": collector.uses,
        "fields": [[index, name, info["type"], info["param"], info["index"]]
                   for index, fields in collector.fields.items() for name, info in fields.items()],
        "constructs": _constructs(tree.root_node),
    }
    if visits:
        facts["visits"] = visits
    if collector.route_facts:
        facts["routes"] = collector.route_facts
    facts.update(endpoints.typescript_facts(tree.root_node, is_test, collector.defs))
    return collector.defs, facts, has_error

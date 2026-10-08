"""Symbols, xUnit/NUnit/MSTest cases and resolution facts from C# syntax trees.

Namespaces are qualname prefixes, not group nodes. `using` directives, aliases
and type mentions are facts; `resolve.py` binds a using to the files whose types
this file actually names. Nothing is resolved here.
"""

import re

from tree_sitter_language_pack import get_parser

from cbi.parse import endpoints

GRAMMARS = {"csharp": "csharp"}
ENV_NAME = re.compile(r"[A-Z_][A-Z0-9_]*")
TYPE_NODES = {"class_declaration", "record_declaration", "struct_declaration", "interface_declaration", "enum_declaration"}
TYPE_DISPLAY = {
    "class_declaration": "class",
    "record_declaration": "record",
    "struct_declaration": "struct",
    "interface_declaration": "interface",
    "enum_declaration": "enum",
}
TYPEISH = {"identifier", "qualified_name", "generic_name", "predefined_type", "nullable_type", "array_type",
           "tuple_type", "pointer_type", "implicit_type"}
BODY_STOP = {"declaration_list", "block", "accessor_list", "enum_member_declaration_list", "arrow_expression_clause"}
SKIP_TYPE = {"var", "dynamic"}
TEST_ATTRS = {"Fact", "Theory", "Test", "TestMethod"}
NESTED = TYPE_NODES | {"local_function_statement", "lambda_expression", "anonymous_method_expression"}


def _text(node):
    return node.text.decode(errors="replace")


def _unique(items):
    seen = set()
    out = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _string(node):
    """The text of a plain string literal, or None for interpolations and other nodes."""
    if node is None or node.type != "string_literal":
        return None
    if any(c.type == "interpolation" for c in node.named_children):
        return None
    parts = [c for c in node.named_children if c.type in ("string_literal_content", "verbatim_string_literal_content")]
    if not parts:
        return None
    return "".join(_text(c) for c in parts)


def _signature(source, node):
    end = node.end_byte
    for child in node.children:
        if child.type in BODY_STOP:
            end = child.start_byte
            break
    return " ".join(source[node.start_byte:end].decode(errors="replace").split())


def _doc_text(comments):
    lines = []
    for comment in comments:
        raw = _text(comment).strip()
        if raw.startswith("///"):
            lines.append(raw[3:].strip())
    body = "\n".join(lines).strip()
    if not body:
        return None
    match = re.search(r"<summary>(.*?)</summary>", body, re.DOTALL | re.IGNORECASE)
    text = match.group(1) if match else body
    return " ".join(text.split()) or None


def _decl_name(node):
    for child in node.children:
        if child.type == "identifier":
            return _text(child)
    return None


def _member_name(node):
    """The identifier before the parameter list, type parameters or accessors.

    The return type is also an identifier (`IWidget Run`), so the first identifier
    in the declaration is the wrong one.
    """
    children = list(node.children)
    stop = None
    for i, child in enumerate(children):
        if child.type in ("parameter_list", "accessor_list", "arrow_expression_clause"):
            stop = i
            break
    if stop is None:
        return _decl_name(node)
    for child in reversed(children[:stop]):
        if child.type == "identifier":
            return _text(child)
    return None


def _modifiers(node):
    return [_text(child) for child in node.children if child.type == "modifier"]


def _type_param_names(node):
    names = set()
    for child in node.children:
        if child.type != "type_parameter_list":
            continue
        for param in child.named_children:
            if param.type == "type_parameter":
                ident = next((c for c in param.children if c.type == "identifier"), None)
                if ident is not None:
                    names.add(_text(ident))
    return names


def _mentioned(node, skip):
    """Type names a type node mentions. A qualified name is one string. Type parameters are dropped."""
    if node is None:
        return []
    if node.type in ("predefined_type", "implicit_type"):
        return []
    if node.type == "identifier":
        name = _text(node)
        return [] if name in skip or name in SKIP_TYPE else [name]
    if node.type == "qualified_name":
        return [_text(node)]
    if node.type == "generic_name":
        out = []
        name = next((c for c in node.named_children if c.type in ("identifier", "qualified_name")), None)
        if name is not None and name.type == "identifier" and _text(name) not in skip:
            out.append(_text(name))
        elif name is not None and name.type == "qualified_name":
            out.append(_text(name))
        args = next((c for c in node.named_children if c.type == "type_argument_list"), None)
        for arg in args.named_children if args else ():
            out.extend(_mentioned(arg, skip))
        return out
    if node.type in ("nullable_type", "array_type", "pointer_type") and node.named_children:
        return _mentioned(node.named_children[0], skip)
    if node.type == "tuple_type":
        out = []
        for child in node.named_children:
            out.extend(_mentioned(child, skip))
        return out
    return []


def _simple_type(node, skip=()):
    """The simple name of a type node, unwrapping `T?` and `T[]`. None for predefined types and type parameters."""
    if node is None:
        return None
    if node.type in ("nullable_type", "array_type", "pointer_type"):
        return _simple_type(node.named_children[0], skip) if node.named_children else None
    if node.type == "identifier":
        name = _text(node)
        return None if name in skip or name in SKIP_TYPE else name
    if node.type == "qualified_name":
        return _text(node).split(".")[-1]
    if node.type == "generic_name":
        name = next((c for c in node.named_children if c.type in ("identifier", "qualified_name")), None)
        return _simple_type(name, skip)
    return None


def _member_parts(node):
    """(object, name) of a member access. `this` and `base` are anonymous nodes."""
    obj = None
    name = None
    for child in node.children:
        if child.type in (".", "argument_list"):
            continue
        if obj is None:
            obj = child
        elif child.type == "identifier":
            name = _text(child)
    return obj, name


def _creation_name(node):
    for child in node.named_children:
        if child.type == "argument_list":
            break
        if child.type in TYPEISH:
            return _simple_type(child)
    return None


def _foreach_var(node):
    children = list(node.children)
    for i, child in enumerate(children):
        if child.type == "in" or child.text == b"in":
            for prev in reversed(children[:i]):
                if prev.type == "identifier":
                    return _text(prev)
            return None
    return None


def _catch_var(node):
    decl = next((c for c in node.named_children if c.type == "catch_declaration"), None)
    if decl is None:
        return None
    idents = [c for c in decl.named_children if c.type == "identifier"]
    return _text(idents[-1]) if len(idents) >= 2 else None


def _collect_locals(body):
    """Names a body binds, not looking inside nested functions, lambdas or types."""
    names = set()
    stack = list(body.named_children) if body else []
    while stack:
        node = stack.pop()
        if node.type in NESTED:
            if node.type == "local_function_statement":
                name = _member_name(node)
                if name:
                    names.add(name)
            elif node.type in TYPE_NODES:
                name = _decl_name(node)
                if name:
                    names.add(name)
            continue
        if node.type == "local_declaration_statement":
            for decl in node.named_children:
                if decl.type != "variable_declaration":
                    continue
                for var in decl.named_children:
                    if var.type == "variable_declarator":
                        ident = next((c for c in var.children if c.type == "identifier"), None)
                        if ident is not None:
                            names.add(_text(ident))
            continue
        if node.type == "foreach_statement":
            var = _foreach_var(node)
            if var:
                names.add(var)
            block = next((c for c in node.named_children if c.type == "block"), None)
            stack.extend(block.named_children if block else [])
            continue
        if node.type == "catch_clause":
            var = _catch_var(node)
            if var:
                names.add(var)
        stack.extend(node.named_children)
    return names


def _lambda_names(node):
    names = set()
    for child in node.named_children:
        if child.type == "parameter_list":
            for param in child.named_children:
                idents = [c for c in param.children if c.type == "identifier"]
                if idents:
                    names.add(_text(idents[-1]))
        elif child.type == "identifier":
            names.add(_text(child))
    return names


def _shadowed(scope, name):
    while scope:
        names, scope = scope
        if name in names:
            return True
    return False


def _lookup(scopes, name):
    for scope in reversed(scopes):
        if name in scope:
            return scope[name] or None
    return None


def _expr_type(node, scopes):
    if node is None:
        return None
    if node.type == "identifier":
        return _lookup(scopes, _text(node))
    if node.type == "object_creation_expression":
        return _creation_name(node)
    if node.type in ("parenthesized_expression", "cast_expression") and node.named_children:
        return _expr_type(node.named_children[-1], scopes)
    return None


def _arg_types(node, scopes):
    args = next((c for c in node.named_children if c.type == "argument_list"), None)
    out = []
    for arg in args.named_children if args else ():
        if arg.type != "argument":
            continue
        named = [c for c in arg.named_children]
        keyword = None
        expr = named[-1] if named else None
        if len(named) >= 2 and named[0].type == "identifier" and any(c.type == ":" for c in arg.children):
            keyword = _text(named[0])
        out.append([keyword, _expr_type(expr, scopes)])
    return out


def _first_string_arg(node):
    args = next((c for c in node.named_children if c.type in ("argument_list", "bracketed_argument_list")), None)
    for arg in args.named_children if args else ():
        if arg.type == "string_literal":
            return _string(arg)
        for child in arg.children:
            if child.type == "string_literal":
                return _string(child)
    return None


def _null_default(node):
    parent = node.parent
    if parent is not None and parent.type == "postfix_unary_expression":
        parent = parent.parent
    if parent is None or parent.type != "binary_expression":
        return None
    children = list(parent.children)
    for i, child in enumerate(children):
        if child.type == "??" or child.text == b"??":
            for right in children[i + 1:]:
                if right.is_named:
                    return _string(right)
            return None
    return None


def _is_environment(node):
    if node is None:
        return False
    if node.type == "identifier":
        return _text(node) == "Environment"
    if node.type == "member_access_expression":
        _obj, name = _member_parts(node)
        return name == "Environment"
    if node.type == "qualified_name":
        return _text(node).endswith(".Environment") or _text(node) == "Environment"
    return False


def _is_configuration(node):
    if node is None:
        return False
    if node.type == "identifier":
        return _text(node).casefold() == "configuration"
    if node.type == "member_access_expression":
        _obj, name = _member_parts(node)
        return name is not None and name.casefold() == "configuration"
    return False


_CONFIG_METHODS = {"GetValue", "GetSection", "GetConnectionString"}
_DICT_METHODS = {"TryGetValue", "GetValueOrDefault"}
_MINIMAL = {"Map", "MapGet", "MapPost", "MapPut", "MapDelete", "MapPatch", "MapMethods", "MapFallback"}
_CONN_KEY = re.compile(r"[A-Za-z0-9_]+")


def _attr_simple(attr):
    for child in attr.children:
        if child.type == "identifier":
            return _text(child)
        if child.type == "qualified_name":
            return _text(child).split(".")[-1]
    return None


def _from_services(param):
    for group in param.children:
        if group.type != "attribute_list":
            continue
        for attr in group.named_children:
            simple = _attr_simple(attr)
            if attr.type == "attribute" and simple and simple.removesuffix("Attribute") == "FromServices":
                return True
    return False


def _param_type_node(param):
    """The type node of a parameter. A single identifier is the name, not a type."""
    idents = [c for c in param.children if c.type == "identifier"]
    type_node = None
    for child in param.named_children:
        if child.type == "identifier" and idents and child == idents[-1] and type_node is not None:
            break
        if child.type in TYPEISH:
            type_node = child
    if type_node is not None and type_node.type == "identifier" and idents and type_node == idents[-1] and len(idents) == 1:
        return None
    return type_node


def _return_type_node(node):
    children = list(node.children)
    stop = len(children)
    for i, child in enumerate(children):
        if child.type in ("parameter_list", "accessor_list", "arrow_expression_clause"):
            stop = i
            break
    name_at = None
    for i in range(stop - 1, -1, -1):
        if children[i].type == "identifier":
            name_at = i
            break
    if name_at is None:
        return None
    for i in range(name_at - 1, -1, -1):
        if children[i].type in TYPEISH:
            return children[i]
    return None


def _return_type(node, skip):
    return _simple_type(_return_type_node(node), skip)


def _unwrap_paren(node):
    while node is not None and node.type == "parenthesized_expression" and node.named_children:
        node = node.named_children[-1]
    return node


def _callee_ident(fn):
    fn = _unwrap_paren(fn)
    if fn is None:
        return None
    if fn.type == "identifier":
        return _text(fn)
    if fn.type == "generic_name":
        ident = next((c for c in fn.named_children if c.type == "identifier"), None)
        return _text(ident) if ident else None
    return None


def _invoked(fn):
    """(receiver, method name) of a call, including `obj.Method<T>`."""
    if fn is None or fn.type != "member_access_expression":
        return None, None
    obj = None
    member = None
    for child in fn.children:
        if child.type == ".":
            continue
        if obj is None:
            obj = child
        else:
            member = child
            break
    if member is None:
        return obj, None
    if member.type == "identifier":
        return obj, _text(member)
    if member.type == "generic_name":
        return obj, _callee_ident(member)
    return obj, None


def _type_arg_is(fn, wanted):
    if fn is None:
        return False
    generic = fn if fn.type == "generic_name" else None
    if fn.type == "member_access_expression":
        generic = next((c for c in fn.children if c.type == "generic_name"), None)
    if generic is None:
        return False
    args = next((c for c in generic.named_children if c.type == "type_argument_list"), None)
    return any(_simple_type(arg) == wanted for arg in (args.named_children if args else ()))


def _receiver_is_config(obj, types):
    """True when this expression is an IConfiguration: the name, the type, or GetRequiredService of it."""
    if obj is None:
        return False
    if _is_configuration(obj):
        return True
    if obj.type == "identifier":
        return _lookup(types, _text(obj)) == "IConfiguration"
    if obj.type == "invocation_expression":
        fn = next((c for c in obj.named_children if c.type != "argument_list"), None)
        return _type_arg_is(fn, "IConfiguration")
    if obj.type == "member_access_expression":
        return _type_arg_is(obj, "IConfiguration")
    return False


def _string_args(node):
    args = next((c for c in node.named_children if c.type in ("argument_list", "bracketed_argument_list")), None)
    found = []
    for arg in args.named_children if args else ():
        if arg.type == "string_literal":
            found.append(_string(arg))
            continue
        literal = next((c for c in arg.children if c.type == "string_literal"), None)
        found.append(_string(literal) if literal else None)
    return found


def _is_dotenv_path(text):
    return bool(text) and (text == ".env" or text.endswith("/.env") or text.endswith("\\.env"))


def _file_loads_dotenv(root):
    stack = [root]
    while stack:
        node = stack.pop()
        if node.type == "string_literal":
            if _is_dotenv_path(_string(node)):
                return True
            continue
        stack.extend(node.children)
    return False


def _is_minimal_lambda(node):
    parent = node.parent
    if parent is None or parent.type != "argument":
        return False
    args = parent.parent
    if args is None or args.type != "argument_list":
        return False
    call = args.parent
    if call is None or call.type != "invocation_expression":
        return False
    fn = next((c for c in call.named_children if c.type != "argument_list"), None)
    _obj, name = _invoked(fn)
    return name in _MINIMAL


def _lambda_injected(node):
    """Typed parameters of a minimal-API lambda. Untyped and predefined parameters are not services."""
    if not _is_minimal_lambda(node):
        return {}
    found = {}
    plist = next((c for c in node.named_children if c.type == "parameter_list"), None)
    for param in plist.named_children if plist else ():
        if param.type != "parameter":
            continue
        idents = [c for c in param.children if c.type == "identifier"]
        if not idents:
            continue
        typ = _simple_type(_param_type_node(param))
        if typ:
            found[_text(idents[-1])] = typ
    return found


def _type_refs_in(root):
    """Simple and qualified type names written in type position, skipping type parameters."""
    refs = []

    def add(node, skip):
        refs.extend(_mentioned(node, skip))

    def visit(node, skip):
        kind = node.type
        if kind in TYPE_NODES or kind in ("method_declaration", "local_function_statement"):
            skip = set(skip) | _type_param_names(node)
        if kind == "typeof_expression":
            for child in node.named_children:
                add(child, skip)
            return
        if kind == "attribute":
            name = next((c for c in node.named_children if c.type in TYPEISH), None)
            if name is not None:
                add(name, skip)
            for child in node.named_children:
                if child.type == "attribute_argument_list":
                    visit(child, skip)
            return
        if kind == "parameter":
            type_node = _param_type_node(node)
            if type_node is not None:
                add(type_node, skip)
            for child in node.named_children:
                if child is not type_node and child.type != "attribute_list":
                    visit(child, skip)
            return
        if kind == "variable_declaration":
            type_node = next((c for c in node.named_children if c.type in TYPEISH), None)
            if type_node is not None and type_node.type != "implicit_type":
                add(type_node, skip)
            for child in node.named_children:
                if child is not type_node:
                    visit(child, skip)
            return
        if kind == "object_creation_expression":
            for child in node.named_children:
                if child.type == "argument_list":
                    visit(child, skip)
                elif child.type in TYPEISH:
                    add(child, skip)
            return
        if kind in ("cast_expression", "as_expression", "is_expression"):
            type_node = next((c for c in node.named_children if c.type in TYPEISH), None)
            if type_node is not None:
                add(type_node, skip)
            for child in node.named_children:
                if child is not type_node:
                    visit(child, skip)
            return
        if kind == "base_list":
            for child in node.named_children:
                add(child, skip)
            return
        if kind in ("method_declaration", "local_function_statement", "constructor_declaration",
                    "property_declaration", "indexer_declaration"):
            returned = _return_type_node(node)
            if returned is not None:
                add(returned, skip)
            for child in node.named_children:
                if child is not returned:
                    visit(child, skip)
            return
        if kind == "generic_name":
            args = next((c for c in node.named_children if c.type == "type_argument_list"), None)
            for arg in args.named_children if args else ():
                add(arg, skip)
            return
        for child in node.named_children:
            visit(child, skip)

    visit(root, set())
    return refs


def _test_attr(node):
    for group in node.children:
        if group.type != "attribute_list":
            continue
        for attr in group.named_children:
            if attr.type != "attribute":
                continue
            name = None
            for child in attr.children:
                if child.type == "identifier":
                    name = _text(child)
                    break
                if child.type == "qualified_name":
                    name = _text(child).split(".")[-1]
                    break
            if name and (name in TEST_ATTRS or name.removesuffix("Attribute") in TEST_ATTRS):
                return True
    return False


def _assign_parts(node):
    named = [c for c in node.named_children]
    if len(named) < 2:
        return None, None
    left, right = named[0], named[-1]
    field = None
    if left.type == "identifier":
        field = _text(left)
    elif left.type == "member_access_expression":
        obj, name = _member_parts(left)
        if obj is not None and obj.type == "this":
            field = name
    rhs = _text(right) if right.type == "identifier" else None
    return field, rhs


def _assignments(body):
    stack = list(body.named_children) if body else []
    while stack:
        node = stack.pop()
        if node.type in NESTED:
            continue
        if node.type == "assignment_expression":
            yield node
            continue
        stack.extend(node.named_children)


class _Collector:
    def __init__(self, source):
        self.source = source
        self.ns = [""]
        self.defs = []
        self.anchors = {}
        self.namespaces = []
        self.types = []
        self.usings = []
        self.aliases = []
        self.type_refs = []
        self.exports = {}
        self.locals = set()
        self.methods = {}  # class index -> set of method names
        self.bases = {}  # class index -> simple name of the first base type
        self.fields = {}  # class index -> {field: {type, param, index}}
        self.declared = {}  # class index -> {field: declared simple type}
        self.ctor_params = {}  # ctor index -> {name: {type, param, index}}
        self.param_names = {}  # def index -> [param names]
        self.param_types = {}  # def index -> {name: simple type}
        self.param_injected = {}  # def index -> {name: {type, param, index}} for [FromServices]
        self.returns = {}  # class index or None -> {method name: simple return type, or None when overloads disagree}
        self.lambda_injected = {}  # lambda start byte -> {param name: type}
        self.loads_dotenv = False
        self.calls = []
        self.uses = []
        self.envs = []
        self.constructs = []

    def add(self, node, name, display_kind, parent, signature, doc, kind="symbol"):
        if parent is None:
            qualname = f"{self.ns[0]}.{name}" if self.ns[0] else name
        else:
            qualname = f"{self.defs[parent]['qualname']}.{name}"
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

    def note_namespace(self, name):
        if name and name not in self.namespaces:
            self.namespaces.append(name)

    def walk(self, nodes, parent, tparams):
        pending = []
        for node in nodes:
            if node.type == "comment":
                text = _text(node).lstrip()
                if text.startswith("///"):
                    if pending and node.start_point.row > pending[-1].end_point.row + 1:
                        pending = []
                    pending.append(node)
                else:
                    pending = []
                continue
            docs = _doc_text(pending) if pending and node.start_point.row <= pending[-1].end_point.row + 1 else None
            pending = []
            self.one(node, parent, tparams, docs)

    def one(self, node, parent, tparams, docs):
        kind = node.type
        if kind == "using_directive":
            self.using(node)
        elif kind == "file_scoped_namespace_declaration":
            name = _namespace_name(node)
            self.ns[0] = name
            self.note_namespace(name)
        elif kind == "namespace_declaration":
            name = _namespace_name(node)
            full = f"{self.ns[0]}.{name}" if self.ns[0] and name else name
            self.note_namespace(full)
            saved = self.ns[0]
            self.ns[0] = full
            body = next((c for c in node.named_children if c.type == "declaration_list"), None)
            if body is not None:
                self.walk(body.named_children, parent, tparams)
            self.ns[0] = saved
        elif kind.startswith("preproc"):
            self.walk(node.named_children, parent, tparams)
        elif kind == "global_statement":
            self.walk(node.named_children, parent, tparams)
        elif kind in TYPE_NODES:
            self.type_decl(node, parent, tparams, docs)
        elif kind == "local_function_statement" and parent is None:
            self.function(node, docs)
        elif kind == "method_declaration" and parent is not None:
            self.method(node, parent, tparams, docs)
        elif kind == "constructor_declaration" and parent is not None:
            self.constructor(node, parent, tparams, docs)
        elif kind == "property_declaration" and parent is not None:
            self.property(node, parent, docs)
        elif kind == "field_declaration" and parent is not None:
            self.field(node, parent, tparams)

    def using(self, node):
        equals = next((i for i, child in enumerate(node.children) if child.type == "="), None)
        if equals is not None:
            alias = next((c for c in node.children[:equals] if c.type == "identifier"), None)
            target = next((c for c in node.children[equals + 1:] if c.type in ("identifier", "qualified_name", "generic_name")), None)
            if alias is not None and target is not None:
                self.aliases.append([_text(alias), _text(target)])
                self.type_refs.append(_text(target))
            return
        name = next((c for c in node.named_children if c.type in ("identifier", "qualified_name")), None)
        if name is None:
            return
        text = _text(name)
        if any(c.type == "static" for c in node.children):
            self.type_refs.append(text)
        else:
            self.usings.append(text)

    def type_decl(self, node, parent, outer_params, docs):
        name = _decl_name(node)
        if not name:
            return
        display = TYPE_DISPLAY[node.type]
        index = self.add(node, name, display, parent, _signature(self.source, node), docs)
        file_local = "file" in _modifiers(node)
        if parent is None and not file_local:
            self.types.append([self.ns[0], name])
            self.exports[name] = name
            self.locals.add(name)
        tparams = set(outer_params) | _type_param_names(node)
        self.methods[index] = set()
        self.fields[index] = {}
        base_list = next((c for c in node.named_children if c.type == "base_list"), None)
        if base_list is not None:
            first = None
            for child in base_list.named_children:
                self.type_refs.extend(_mentioned(child, tparams))
                if first is None:
                    first = _simple_type(child, tparams)
            if first:
                self.bases[index] = first
        primary_list = next((c for c in node.named_children if c.type == "parameter_list"), None)
        primary = self.parameters(primary_list, tparams) if primary_list is not None else []
        for i, (pname, typ, _pnode) in enumerate(primary):
            if typ:
                self.fields[index][pname] = {"type": typ, "param": pname, "index": i}
        body = next((c for c in node.named_children if c.type == "declaration_list"), None)
        if display == "record":
            existing = set()
            for member in body.named_children if body else ():
                if member.type == "property_declaration":
                    prop = _member_name(member)
                    if prop:
                        existing.add(prop)
            for pname, typ, pnode in primary:
                if pname in existing:
                    continue
                signature = " ".join(_text(pnode).split())
                self.add(pnode, pname, "property", index, signature, None)
        if body is not None and node.type != "enum_declaration":
            self.walk(body.named_children, index, tparams)

    def parameters(self, plist, skip):
        out = []
        for param in plist.named_children if plist is not None else ():
            if param.type != "parameter":
                continue
            idents = [c for c in param.children if c.type == "identifier"]
            if not idents:
                continue
            name = _text(idents[-1])
            type_node = None
            for child in param.named_children:
                if child.type == "identifier" and child == idents[-1] and type_node is not None:
                    break
                if child.type in TYPEISH:
                    type_node = child
            if type_node is not None and type_node.type == "identifier" and type_node == idents[-1] and len(idents) == 1:
                type_node = None
            self.type_refs.extend(_mentioned(type_node, skip))
            out.append((name, _simple_type(type_node, skip), param))
        return out

    def remember_params(self, index, params):
        self.param_names[index] = [name for name, _typ, _node in params]
        self.param_types[index] = {name: typ or "" for name, typ, _node in params}

    def _note_injected(self, index, params):
        found = {}
        for i, (pname, typ, pnode) in enumerate(params):
            if typ and _from_services(pnode):
                found[pname] = {"type": typ, "param": pname, "index": i}
        if found:
            self.param_injected[index] = found

    def _note_return(self, parent, name, node, skip):
        if not name:
            return
        typ = _return_type(node, skip)
        if not typ:
            return
        got = self.returns.setdefault(parent, {})
        got[name] = typ if got.get(name, typ) == typ else None

    def method(self, node, parent, tparams, docs):
        name = _member_name(node)
        if not name:
            return
        skip = set(tparams) | _type_param_names(node)
        params = self.parameters(next((c for c in node.named_children if c.type == "parameter_list"), None), skip)
        kind = "test" if _test_attr(node) else "symbol"
        display = "test case" if kind == "test" else "method"
        index = self.add(node, name, display, parent, _signature(self.source, node), docs, kind=kind)
        self.methods[parent].add(name)
        self.remember_params(index, params)
        self._note_injected(index, params)
        self._note_return(parent, name, node, skip)

    def function(self, node, docs):
        name = _member_name(node)
        if not name:
            return
        params = self.parameters(next((c for c in node.named_children if c.type == "parameter_list"), None), _type_param_names(node))
        kind = "test" if _test_attr(node) else "symbol"
        display = "test case" if kind == "test" else "function"
        index = self.add(node, name, display, None, _signature(self.source, node), docs, kind=kind)
        self.exports[name] = name
        self.locals.add(name)
        self.remember_params(index, params)
        self._note_injected(index, params)
        self._note_return(None, name, node, _type_param_names(node))

    def constructor(self, node, parent, tparams, docs):
        name = _member_name(node) or self.defs[parent]["name"]
        params = self.parameters(
            next((c for c in node.named_children if c.type == "parameter_list"), None),
            set(tparams) | _type_param_names(node),
        )
        index = self.add(node, name, "constructor", parent, _signature(self.source, node), docs)
        self.remember_params(index, params)
        self.ctor_params[index] = {}
        for i, (pname, typ, _pnode) in enumerate(params):
            if typ:
                self.ctor_params[index][pname] = {"type": typ, "param": pname, "index": i}
        block = next((c for c in node.named_children if c.type == "block"), None)
        declared = dict(self.declared.get(parent, {}))
        for assignment in _assignments(block):
            field, rhs = _assign_parts(assignment)
            info = self.ctor_params[index].get(rhs) if field and rhs else None
            if not info:
                continue
            chosen = declared.get(field) or info["type"]
            if chosen:
                self.fields[parent][field] = {"type": chosen, "param": info["param"], "index": info["index"]}

    def property(self, node, parent, docs):
        name = _member_name(node)
        if not name:
            return
        self.add(node, name, "property", parent, _signature(self.source, node), docs)

    def field(self, node, parent, tparams):
        declaration = next((c for c in node.named_children if c.type == "variable_declaration"), None)
        if declaration is None:
            return
        type_node = next((c for c in declaration.named_children if c.type in TYPEISH), None)
        self.type_refs.extend(_mentioned(type_node, tparams))
        simple = _simple_type(type_node, tparams)
        known = self.fields.get(parent, {})
        declared = self.declared.setdefault(parent, {})
        for var in declaration.named_children:
            if var.type != "variable_declarator":
                continue
            ident = next((c for c in var.children if c.type == "identifier"), None)
            if ident is None:
                continue
            fname = _text(ident)
            if simple:
                declared[fname] = simple
                if fname in known:
                    known[fname]["type"] = simple
            init = next((c for c in var.named_children if c.type == "identifier" and c != ident), None)
            if init is None:
                continue
            info = known.get(_text(init))
            if info and fname not in known:
                chosen = simple or info["type"]
                if chosen:
                    known[fname] = {"type": chosen, "param": info["param"], "index": info["index"]}

    def sites(self, root):
        self._walk(root, None, None, None, [{}])

    def _enter(self, node, index, class_index, shadow, types):
        if index is not None and self.defs[index]["display_kind"] in TYPE_DISPLAY.values():
            fields = {name: info["type"] for name, info in self.fields.get(index, {}).items()}
            types = [*types, fields]
        if node.type in ("method_declaration", "constructor_declaration", "local_function_statement"):
            if node.type == "local_function_statement":
                self._note_return(class_index, _member_name(node), node, set())
            block = next((c for c in node.named_children if c.type == "block"), None)
            locals_ = _collect_locals(block)
            params = set(self.param_names.get(index, ())) if index is not None else set()
            if index is None and node.type == "local_function_statement":
                params = {name for name, _typ, _n in self._unstored_params(node)}
            injected = set(self.fields.get(class_index, {})) if class_index is not None else set()
            if node.type == "constructor_declaration" and index is not None:
                injected |= set(self.ctor_params.get(index, {}))
            if index is not None:
                injected |= set(self.param_injected.get(index, {}))
            shadow = (params - injected | locals_, shadow)
            param_types = dict(self.param_types.get(index, {})) if index is not None else {}
            types = [*types, param_types]
        elif node.type == "lambda_expression":
            injected = _lambda_injected(node)
            if injected:
                self.lambda_injected[node.start_byte] = injected
            names = _lambda_names(node)
            if names or injected:
                shadow = (names - set(injected), shadow)
                types = [*types, {name: "" for name in names}]
        elif node.type == "block":
            types = [*types, {}]
        elif node.type == "foreach_statement":
            var = _foreach_var(node)
            if var:
                shadow = ({var}, shadow)
                types = [*types, {var: ""}]
        elif node.type == "catch_clause":
            var = _catch_var(node)
            if var:
                shadow = ({var}, shadow)
                types = [*types, {var: ""}]
        return shadow, types

    def _unstored_params(self, node):
        """Parameter names of a local function that is not a symbol. Types are not indexed."""
        plist = next((c for c in node.named_children if c.type == "parameter_list"), None)
        out = []
        for param in plist.named_children if plist else ():
            idents = [c for c in param.children if c.type == "identifier"]
            if idents:
                out.append((_text(idents[-1]), None, param))
        return out

    def _walk(self, node, d, c, shadow, types):
        index = self.anchors.get((node.start_byte, node.end_byte, node.type))
        if index is not None:
            d = index
            if self.defs[index]["display_kind"] in TYPE_DISPLAY.values():
                c = index
        shadow, types = self._enter(node, index, c, shadow, types)
        self._emit(node, d, c, shadow, types)
        for child in node.named_children:
            self._walk(child, d, c, shadow, types)
        if node.type == "variable_declarator" and types:
            ident = next((child for child in node.children if child.type == "identifier"), None)
            if ident is not None:
                type_node = None
                parent = node.parent
                if parent is not None and parent.type == "variable_declaration":
                    type_node = next((child for child in parent.named_children if child.type in TYPEISH), None)
                types[-1][_text(ident)] = _simple_type(type_node) or ""

    def _emit(self, node, d, c, shadow, types):
        if node.type == "invocation_expression":
            fn = next((child for child in node.named_children if child.type != "argument_list"), None)
            if not self._env_from_call(node, fn, d, types):
                self._call(fn, d, c, shadow)
            self._getenv(node, d)
        elif node.type == "object_creation_expression":
            name = _creation_name(node)
            if name and not _shadowed(shadow, name):
                self.calls.append([d, c, "name", name, None])
            args = _arg_types(node, types)
            if name and any(typ for _key, typ in args):
                self.constructs.append([name, args])
        elif node.type == "element_access_expression":
            self._config(node, d)

    def _call(self, fn, d, c, shadow):
        if fn is None:
            return
        if fn.type == "generic_name":
            ident = next((child for child in fn.named_children if child.type == "identifier"), None)
            if ident is None:
                return
            self._bare(ident, d, c, shadow)
            return
        if fn.type == "identifier":
            self._bare(fn, d, c, shadow)
            return
        if fn.type != "member_access_expression":
            return
        obj, member = _member_parts(fn)
        if not member or obj is None:
            return
        if obj.type == "this" and c is not None:
            self.calls.append([d, c, "this", member, None])
            return
        if obj.type == "base" and c is not None:
            base = self.bases.get(c)
            if base:
                self.calls.append([d, c, "member", base, member])
            return
        obj = _unwrap_paren(obj)
        if obj is None:
            return
        if obj.type == "identifier":
            name = _text(obj)
            if _shadowed(shadow, name):
                return
            if self._use(d, c, name, member, fn):
                return
            if name[:1].isupper():
                self.calls.append([d, c, "member", name, member])
                self.type_refs.append(name)
            return
        if obj.type == "member_access_expression" and c is not None:
            inner, field = _member_parts(obj)
            if inner is not None and inner.type == "this" and field:
                info = self.fields.get(c, {}).get(field)
                if info:
                    self.uses.append([d, c, field, info["type"], member])
            return
        factory = self._factory_type(obj, c, shadow)
        if factory:
            self.calls.append([d, c, "member", factory, member])
            return
        if obj.type == "object_creation_expression":
            created = _creation_name(obj)
            if created:
                self.calls.append([d, c, "member", created, member])

    def _bare(self, ident, d, c, shadow):
        name = _text(ident)
        if _shadowed(shadow, name):
            return
        if c is not None and name in self.methods.get(c, ()):
            self.calls.append([d, c, "this", name, None])
        elif name[:1].isupper():
            self.calls.append([d, c, "name", name, None])

    def _factory_type(self, obj, c, shadow):
        """Return type of a same-file call used as a receiver. None when overloads disagree."""
        node = _unwrap_paren(obj)
        if node is None or node.type != "invocation_expression":
            return None
        fn = next((child for child in node.named_children if child.type != "argument_list"), None)
        name = _callee_ident(fn)
        if not name or _shadowed(shadow, name):
            return None
        return (self.returns.get(c) or {}).get(name)

    def _lambda_type(self, name, node):
        current = node
        while current is not None:
            if current.type == "lambda_expression":
                found = self.lambda_injected.get(current.start_byte, {}).get(name)
                if found:
                    return found
            current = current.parent
        return None

    def _use(self, d, c, name, member, node):
        info = self.fields.get(c, {}).get(name) if c is not None else None
        if info is None and d is not None and self.defs[d]["display_kind"] == "constructor":
            info = self.ctor_params.get(d, {}).get(name)
        if info is None and d is not None:
            info = self.param_injected.get(d, {}).get(name)
        if info is None:
            typ = self._lambda_type(name, node)
            if typ:
                info = {"type": typ}
        if not info or not info.get("type"):
            return False
        self.uses.append([d, c, name, info["type"], member])
        return True

    def _env_from_call(self, node, fn, d, types):
        _obj, member = _invoked(fn)
        if member in _CONFIG_METHODS and _receiver_is_config(_obj, types):
            return self._record_config_method(node, d, member)
        if member in _DICT_METHODS and self.loads_dotenv:
            return self._record_dict(node, d, member)
        return False

    def _record_config_method(self, node, d, member):
        args = _string_args(node)
        key = args[0] if args else None
        if not key:
            return False
        if member == "GetConnectionString":
            if not _CONN_KEY.fullmatch(key):
                return False
            name = f"ConnectionStrings__{key}"
        elif not ENV_NAME.fullmatch(key):
            return False
        else:
            name = key
        default = _null_default(node)
        if default is None and len(args) > 1 and args[1]:
            default = args[1]
        self.envs.append([d, name, default])
        return True

    def _record_dict(self, node, d, member):
        args = _string_args(node)
        key = args[0] if args else None
        if not key or not ENV_NAME.fullmatch(key):
            return False
        default = args[1] if member == "GetValueOrDefault" and len(args) > 1 and args[1] else _null_default(node)
        self.envs.append([d, key, default])
        return True

    def _getenv(self, node, d):
        fn = next((child for child in node.named_children if child.type == "member_access_expression"), None)
        if fn is None:
            return
        obj, name = _member_parts(fn)
        if name != "GetEnvironmentVariable" or not _is_environment(obj):
            return
        key = _first_string_arg(node)
        if key and ENV_NAME.fullmatch(key):
            self.envs.append([d, key, _null_default(node)])

    def _config(self, node, d):
        obj = next((child for child in node.named_children if child.type != "bracketed_argument_list"), None)
        if not _is_configuration(obj):
            return
        key = _first_string_arg(node)
        if key and ENV_NAME.fullmatch(key):
            self.envs.append([d, key, _null_default(node)])


def _namespace_name(node):
    name = next((c for c in node.named_children if c.type in ("identifier", "qualified_name")), None)
    return _text(name) if name is not None else ""


def parse(source, lang, is_test):
    """Return (definitions in source order, facts, has_parse_error).

    `is_test` skips HTTP extraction. A `[Fact]`, `[Theory]`, `[Test]` or
    `[TestMethod]` method is a test case whether or not the file was classified
    as a test.
    Facts use the same call, field, use and construct indexes as `typescript.py`,
    plus `namespaces`, `types`, `usings`, `aliases` and `type_refs`. Usings are
    not imports: a namespace is not a module specifier.
    """
    tree = get_parser(GRAMMARS[lang]).parse(source)
    collector = _Collector(source)
    collector.loads_dotenv = _file_loads_dotenv(tree.root_node)
    collector.walk(tree.root_node.named_children, None, set())
    collector.sites(tree.root_node)
    facts = {
        "imports": [],
        "exports": collector.exports,
        "reexports": [],
        "locals": sorted(collector.locals),
        "calls": collector.calls,
        "reads": [],
        "envs": collector.envs,
        "uses": collector.uses,
        "fields": [[index, name, info["type"], info["param"], info["index"]]
                   for index, fields in collector.fields.items() for name, info in fields.items()],
        "constructs": collector.constructs,
        "namespaces": collector.namespaces,
        "types": collector.types,
        "usings": _unique(collector.usings),
        "aliases": collector.aliases,
        "type_refs": _unique([*collector.type_refs, *_type_refs_in(tree.root_node)]),
    }
    facts.update(endpoints.csharp_facts(tree.root_node, is_test, collector.defs))
    return collector.defs, facts, tree.root_node.has_error

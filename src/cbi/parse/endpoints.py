"""HTTP route and client-call facts from a Python, TypeScript or C# syntax tree.

Facts use definition indexes (the same order `parse` records symbols). A caller
or handler that is not a symbol is None, and resolution then uses the file.
Test files yield empty lists: mock fetches are not client calls.
"""

from cbi.http import from_pieces, has_literal, is_api_href, join_path, normalise

VERBS = {"get", "post", "put", "patch", "delete", "head", "options"}
CLIENTS = {"fetch", "axios", "ky", "httpx", "requests"}
PY_FUNCS = {"function_definition", "lambda"}
TS_FUNCS = {"function_declaration", "generator_function_declaration", "function_expression", "function",
            "arrow_function", "method_definition"}
TS_CTOR = {"call_expression", "new_expression"}
HTTP_ATTRS = {"HttpGet": "GET", "HttpPost": "POST", "HttpPut": "PUT", "HttpPatch": "PATCH",
              "HttpDelete": "DELETE", "HttpHead": "HEAD", "HttpOptions": "OPTIONS"}
MAP_VERBS = {"MapGet": "GET", "MapPost": "POST", "MapPut": "PUT", "MapPatch": "PATCH",
             "MapDelete": "DELETE", "MapHead": "HEAD", "MapOptions": "OPTIONS"}

EMPTY = {"http_routes": [], "http_routers": [], "http_mounts": [], "http_calls": []}


def _text(node):
    return node.text.decode(errors="replace") if node is not None else ""


def _at(defs, line):
    best, span = None, None
    if not line:
        return None
    for index, defin in enumerate(defs or []):
        if defin["start_line"] <= line <= defin["end_line"]:
            width = defin["end_line"] - defin["start_line"]
            if span is None or width < span:
                best, span = index, width
    return best


def _by_name(defs, name):
    if not name:
        return None
    for index, defin in enumerate(defs or []):
        if defin["name"] == name:
            return index
    return None


def _line(node):
    return node.start_point.row + 1


def _empty():
    return {key: list(value) for key, value in EMPTY.items()}


def _norm_prefix(text):
    if not text or text == "/":
        return ""
    return normalise(text) or ""


def python_facts(root, is_test, defs):
    if is_test:
        return _empty()
    found = _collect(root, "python")
    return _bind(found, defs)


def typescript_facts(root, is_test, defs):
    if is_test:
        return _empty()
    found = _collect(root, "typescript")
    return _bind(found, defs)


def csharp_facts(root, is_test, defs):
    if is_test:
        return _empty()
    found = _csharp(root)
    return _bind(found, defs)


def _bind(found, defs):
    facts = _empty()
    facts["http_routers"] = found["routers"]
    facts["http_mounts"] = found["mounts"]
    for handler, method, path, router_name, handler_name in found["routes"]:
        if isinstance(handler, tuple) and handler and handler[0] == "name":
            index = _by_name(defs, handler[1])
            handler_name = handler_name or handler[1]
        elif isinstance(handler, tuple) and handler and handler[0] == "line":
            index = _at(defs, handler[1])
        else:
            index = None
        facts["http_routes"].append([index, method, path, router_name, handler_name])
    seen = set()
    for line, method, path in found["calls"]:
        item = (_at(defs, line), method, path)
        if item in seen:
            continue
        seen.add(item)
        facts["http_calls"].append(list(item))
    return facts


def _collect(root, lang):
    """Routers, mounts, routes and client calls. Wrappers are known before calls."""
    state = {"routers": [], "mounts": [], "routes": [], "calls": [], "known": set(), "wrappers": {}}
    _walk(root, lang, state, None, True)
    _walk(root, lang, state, None, False)
    return state


def _walk(node, lang, state, func, routes_only):
    if node is None:
        return
    if lang == "python" and node.type in PY_FUNCS:
        _function(node, lang, state, _py_name(node), _py_params(node), None, routes_only)
        return
    if lang == "typescript" and node.type in TS_FUNCS and node.type != "arrow_function":
        _function(node, lang, state, _ts_name(node), _ts_params(node), None, routes_only)
        return
    if lang == "typescript" and node.type == "variable_declarator":
        name = node.child_by_field_name("name")
        value = node.child_by_field_name("value")
        if value is not None and value.type in ("arrow_function", "function_expression") and name is not None and name.type == "identifier":
            _function(value, lang, state, _text(name), _ts_params(value), node, routes_only)
            return
        if func is None and not routes_only:
            _assign(node, lang, state, "value")
        elif func is None and routes_only:
            _assign(node, lang, state, "value")
    if func is None and node.type == "assignment" and lang == "python":
        _assign(node, lang, state, "right")
    if not routes_only and lang == "typescript" and node.type == "jsx_attribute":
        _jsx_href(state, node)
    if _is_call(node, lang):
        if routes_only:
            _route_call(node, lang, state, func)
        else:
            _client_call(node, lang, state, func)
    for child in node.named_children:
        _walk(child, lang, state, func, routes_only)


def _function(node, lang, state, name, params, declarator, routes_only):
    """Walk a function. The first pass records a wrapper; both passes see its body."""
    library = []
    inner = {"locals": {}, "params": params, "library": library}
    for child in node.named_children:
        _walk_body(child, lang, state, inner, node, routes_only)
    if routes_only and name and _wrapper_spec(library, params):
        state["wrappers"][name] = _wrapper_spec(library, params)


def _walk_body(node, lang, state, frame, func, routes_only):
    if node is None:
        return
    if lang == "python" and node.type in PY_FUNCS:
        _function(node, lang, state, _py_name(node), _py_params(node), None, routes_only)
        return
    if lang == "typescript" and node.type in TS_FUNCS and node.type != "arrow_function":
        _function(node, lang, state, _ts_name(node), _ts_params(node), None, routes_only)
        return
    if lang == "typescript" and node.type == "variable_declarator":
        name = node.child_by_field_name("name")
        value = node.child_by_field_name("value")
        if value is not None and value.type in ("arrow_function", "function_expression") and name is not None and name.type == "identifier":
            _note_local(frame, _text(name), value, lang)
            _function(value, lang, state, _text(name), _ts_params(value), node, routes_only)
            return
        _note_local(frame, _text(name) if name is not None and name.type == "identifier" else None, value, lang)
    if lang == "python" and node.type == "assignment":
        left = node.child_by_field_name("left")
        if left is not None and left.type == "identifier":
            _note_local(frame, _text(left), node.child_by_field_name("right"), lang)
    if not routes_only and lang == "typescript" and node.type == "jsx_attribute":
        _jsx_href(state, node)
    if _is_call(node, lang):
        if routes_only:
            _route_call(node, lang, state, func)
            _note_library(node, lang, frame)
        else:
            _client_call(node, lang, state, func, frame)
    for child in node.named_children:
        _walk_body(child, lang, state, frame, func, routes_only)


def _is_call(node, lang):
    if lang == "python":
        return node.type == "call"
    return node.type in TS_CTOR


def _py_name(node):
    if node.type != "function_definition":
        return None
    name = node.child_by_field_name("name")
    return _text(name) if name is not None else None


def _ts_name(node):
    name = node.child_by_field_name("name")
    if name is None:
        return None
    return _text(name)


def _py_params(node):
    params = node.child_by_field_name("parameters") if node.type == "function_definition" else None
    names = []
    for child in params.named_children if params is not None else ():
        ident = None
        if child.type == "identifier":
            ident = child
        elif child.type in ("typed_parameter", "default_parameter", "typed_default_parameter", "list_splat_pattern"):
            ident = child.child_by_field_name("name")
            if ident is None:
                ident = next((c for c in child.named_children if c.type == "identifier"), None)
        if ident is not None and ident.type == "identifier":
            text = _text(ident)
            if text not in ("self", "cls"):
                names.append(text)
    return names


def _ts_params(node):
    if node.type == "arrow_function":
        ident = next((c for c in node.named_children if c.type == "identifier"), None)
        formal = node.child_by_field_name("parameters")
        if formal is None and ident is not None:
            return [_text(ident)]
    params = node.child_by_field_name("parameters")
    names = []
    for child in params.named_children if params is not None else ():
        if child.type == "identifier":
            names.append(_text(child))
            continue
        pattern = child.child_by_field_name("pattern") if child.type.endswith("parameter") or child.type == "rest_parameter" else None
        if pattern is None:
            pattern = next((c for c in child.named_children if c.type in ("identifier", "rest_pattern")), None)
        if pattern is not None and pattern.type == "rest_pattern":
            pattern = next((c for c in pattern.named_children if c.type == "identifier"), None)
        if pattern is not None and pattern.type == "identifier":
            names.append(_text(pattern))
    return names


def _assign(node, lang, state, field):
    if lang == "python":
        left = node.child_by_field_name("left")
        value = node.child_by_field_name(field)
        if left is None or left.type != "identifier" or value is None or value.type != "call":
            return
        name = _text(left)
    else:
        name_node = node.child_by_field_name("name")
        value = node.child_by_field_name(field)
        if name_node is None or name_node.type != "identifier" or value is None:
            return
        name = _text(name_node)
    kind, prefix = _ctor(value, lang)
    if not kind:
        return
    state["known"].add(name)
    # Last assignment wins: drop the earlier one with this name.
    state["routers"] = [row for row in state["routers"] if row[0] != name]
    state["routers"].append([name, prefix, kind])


def _ctor(node, lang):
    is_new = node.type == "new_expression"
    call = node
    obj, name = _callee(call, lang)
    kind = None
    if name == "Router" and (obj in (None, "express") or is_new):
        kind = "router"
    elif name == "express" and obj is None and not is_new:
        kind = "app"
    elif name == "FastAPI":
        kind = "app"
    elif name == "APIRouter":
        kind = "router"
    elif name == "Koa":
        kind = "app"
    if kind is None:
        return None, ""
    return kind, _ctor_prefix(call, lang, name)


def _ctor_prefix(call, lang, name):
    args = _args(call, lang)
    for kind, key, value in args:
        if kind == "kw" and key == "prefix":
            text = _plain(value, lang)
            return _norm_prefix(text) if text is not None else ""
        if kind == "pos" and _is_object(value):
            prop = _object_prop(value, "prefix", lang)
            text = _plain(prop, lang) if prop is not None else None
            if text is not None:
                return _norm_prefix(text)
    if name == "APIRouter":
        return ""
    return ""


def _callee(node, lang):
    """(object name or None, callee name or None) of a call or new-expression."""
    if lang == "python":
        fn = node.child_by_field_name("function")
    elif node.type == "new_expression":
        fn = node.child_by_field_name("constructor")
        if fn is None:
            fn = next((c for c in node.named_children if c.type != "arguments"), None)
    else:
        fn = node.child_by_field_name("function")
    if fn is None:
        return None, None
    if fn.type == "identifier":
        return None, _text(fn)
    if lang == "python" and fn.type == "attribute":
        obj = fn.child_by_field_name("object")
        attr = fn.child_by_field_name("attribute")
        obj_name = _text(obj) if obj is not None and obj.type == "identifier" else None
        return obj_name, _text(attr) if attr is not None else None
    if fn.type == "member_expression":
        obj = fn.child_by_field_name("object")
        prop = fn.child_by_field_name("property")
        obj_name = _text(obj) if obj is not None and obj.type == "identifier" else None
        return obj_name, _text(prop) if prop is not None else None
    return None, None


def _args(call, lang):
    node = call.child_by_field_name("arguments")
    out = []
    for child in node.named_children if node is not None else ():
        if lang == "python" and child.type == "keyword_argument":
            name = child.child_by_field_name("name")
            value = child.child_by_field_name("value")
            out.append(("kw", _text(name) if name is not None else None, value))
        elif child.type != "comment":
            out.append(("pos", None, child))
    return out


def _is_object(node):
    return node is not None and node.type in ("dictionary", "object", "object_expression")


def _object_prop(node, name, lang):
    for child in node.named_children:
        if child.type in ("shorthand_property_identifier", "shorthand_property_identifier_pattern") and _text(child) == name:
            return child
        if lang == "python" and child.type == "pair":
            key, value = child.child_by_field_name("key"), child.child_by_field_name("value")
            if key is not None and _text(key).strip("\"'") == name:
                return value
        if child.type in ("pair", "property_assignment", "public_field_definition"):
            key = child.child_by_field_name("key") or child.child_by_field_name("name")
            value = child.child_by_field_name("value")
            if key is not None and _text(key).strip("\"'") == name:
                return value
    return None


def _plain(node, lang):
    pieces = _pieces(node, lang)
    if not pieces or any(part is None for part in pieces) or len(pieces) != 1:
        return None
    return pieces[0]


def _pieces(node, lang):
    node = _unwrap(node)
    if node is None:
        return None
    if lang == "python" and node.type == "string":
        pieces = []
        for child in node.named_children:
            if child.type == "string_content":
                pieces.append(_text(child))
            elif child.type == "interpolation":
                pieces.append(None)
        return pieces or [""]
    if node.type == "template_string":
        pieces = []
        for child in node.named_children:
            if child.type == "string_fragment":
                pieces.append(_text(child))
            elif child.type == "template_substitution":
                pieces.append(None)
        return pieces
    if node.type == "string":
        frags = [c for c in node.named_children if c.type == "string_fragment"]
        if frags:
            return ["".join(_text(c) for c in frags)]
        raw = _text(node)
        if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'`":
            return [raw[1:-1]]
        return [raw]
    return None


def _unwrap(node):
    while node is not None and node.type == "parenthesized_expression":
        nxt = next(iter(node.named_children), None)
        if nxt is None:
            break
        node = nxt
    return node


def _expr_text(node, lang):
    node = _unwrap(node)
    if node is None:
        return None
    if node.type == "identifier":
        return _text(node)
    if lang == "python" and node.type == "attribute":
        obj = _expr_text(node.child_by_field_name("object"), lang)
        attr = node.child_by_field_name("attribute")
        if obj and attr is not None:
            return f"{obj}.{_text(attr)}"
    if node.type == "member_expression":
        obj = _expr_text(node.child_by_field_name("object"), lang)
        prop = node.child_by_field_name("property")
        if obj and prop is not None:
            return f"{obj}.{_text(prop)}"
    return None


def _route_call(node, lang, state, func):
    if lang == "python" and node.parent is not None and node.parent.type == "decorator":
        _decorator_route(node, state)
        return
    if node.type == "new_expression":
        return
    obj, name = _callee(node, lang)
    if name == "include_router" and obj:
        _mount(node, lang, state, obj)
        return
    if name == "use" and obj:
        _mount_use(node, lang, state, obj)
        return
    if not name or name.lower() not in VERBS:
        return
    if obj in CLIENTS:
        return
    args = _args(node, lang)
    path, later = _path_and_rest(args, lang)
    if not path:
        return
    fn = _later_function(later)
    ident = _later_identifier(later)
    known = obj in state["known"] or (obj in {"app", "router"} and (fn or ident))
    if not known and not fn:
        return
    handler = ("name", ident) if ident and not fn else ("line", _line(node))
    state["routes"].append([handler, name.upper(), path, obj, ident if ident and not fn else None])


def _decorator_route(node, state):
    obj, name = _callee(node, "python")
    if not obj or not name:
        return
    args = _args(node, "python")
    if name.lower() in VERBS:
        methods = [name.upper()]
    elif name in ("api_route", "route"):
        methods = _methods_kw(args)
        if not methods:
            return
    elif name == "include_router":
        _mount(node, "python", state, obj)
        return
    else:
        return
    path = _first_path(args, "python")
    if path is None:
        return
    for method in methods:
        state["routes"].append([("line", _line(node)), method, path, obj, None])


def _methods_kw(args):
    for kind, key, value in args:
        if kind == "kw" and key == "methods" and value is not None and value.type == "list":
            found = []
            for child in value.named_children:
                verb = _verb_text(_plain(child, "python"))
                if verb:
                    found.append(verb)
            return found
    return []


def _mount(node, lang, state, parent):
    args = _args(node, lang)
    child = None
    extra = ""
    for kind, key, value in args:
        if kind == "kw" and key == "prefix":
            text = _plain(value, lang)
            extra = _norm_prefix(text) if text else ""
        elif kind == "pos" and child is None:
            child = _expr_text(value, lang)
    if parent and child:
        state["mounts"].append([parent, child, extra])


def _mount_use(node, lang, state, parent):
    args = _args(node, lang)
    extra = ""
    child = None
    seen_string = False
    for kind, _key, value in args:
        if kind != "pos":
            continue
        text = _plain(value, lang)
        if text is not None and not seen_string and child is None:
            extra = _norm_prefix(text)
            seen_string = True
            continue
        name = _expr_text(value, lang)
        if name and child is None:
            child = name
    if parent and child:
        state["mounts"].append([parent, child, extra])


def _path_and_rest(args, lang):
    path = None
    later = []
    seen = False
    for kind, key, value in args:
        if kind == "kw":
            continue
        if not seen:
            found = _path_value(value, lang)
            if found:
                path = found
                seen = True
                continue
            return None, []
        later.append(value)
    return path, later


def _path_value(node, lang):
    pieces = _pieces(node, lang)
    if pieces is None:
        return None
    path = from_pieces(pieces)
    if not path or path == "/":
        # A bare "/" is a real route path (the router's root).
        if pieces and pieces != [None] and any(part == "/" or part == "" for part in pieces if part is not None) or pieces == ["/"]:
            return "/"
        if path == "/":
            return "/"
        return None
    return path


def _first_path(args, lang):
    for kind, key, value in args:
        if kind == "kw" and key in ("path", "url"):
            return _path_value(value, lang)
        if kind == "pos":
            return _path_value(value, lang)
    return None


def _later_function(nodes):
    return any(node is not None and node.type in (
        "arrow_function", "function_expression", "function", "lambda", "function_definition") for node in nodes)


def _later_identifier(nodes):
    found = None
    for node in nodes:
        node = _unwrap(node)
        if node is not None and node.type == "identifier":
            found = _text(node)
    return found


def _client_call(node, lang, state, func, frame=None):
    if lang == "python" and node.parent is not None and node.parent.type == "decorator":
        return
    if node.type == "new_expression":
        return
    obj, name = _callee(node, lang)
    if name in ("include_router", "use"):
        return
    frame = frame or {"locals": {}, "params": []}
    args = _args(node, lang)
    if _is_route_call(obj, name, args, lang, state):
        return
    found = _library(obj, name, args, lang, frame)
    if found:
        _emit_calls(state, node, found[0], found[1])
        return
    if name and name.lower() in VERBS and obj not in state["known"]:
        paths = _eval_paths(_first_pos(args), lang, frame)
        if paths and all(item.startswith("/") for item in paths):
            _emit_calls(state, node, [name.upper()], paths)
            return
    if _is_method_path(args, lang, frame):
        methods, paths = _is_method_path(args, lang, frame)
        _emit_calls(state, node, methods, paths)
        return
    spec = state["wrappers"].get(name) if name and obj not in CLIENTS else None
    if spec:
        _wrapper_call(state, node, spec, args, lang, frame)


def _is_route_call(obj, name, args, lang, state):
    if not name or name.lower() not in VERBS or obj in CLIENTS:
        return False
    _path, later = _path_and_rest(args, lang)
    if not _path:
        return False
    if obj in state["known"]:
        return True
    if _later_function(later):
        return True
    if obj in {"app", "router"} and _later_identifier(later):
        return True
    return False


def _jsx_href(state, node):
    """`<a href="/api/...">` is a GET. Other tags and other paths are not calls."""
    parent = node.parent
    if parent is None or parent.type not in ("jsx_opening_element", "jsx_self_closing_element"):
        return
    tag = parent.child_by_field_name("name")
    if tag is None or tag.type != "identifier" or _text(tag) != "a":
        return
    # This grammar gives a jsx_attribute no fields. The name is the property identifier.
    key = next((child for child in node.named_children if child.type == "property_identifier"), None)
    if key is None or _text(key) != "href":
        return
    value = None
    for child in node.named_children:
        if child.type == "string":
            value = child
        elif child.type == "jsx_expression":
            value = next(iter(child.named_children), None)
    if value is None:
        return
    for path in _eval_paths(value, "typescript", {"locals": {}, "params": []}):
        if is_api_href(path):
            state["calls"].append([_line(node), "GET", path])


def _emit_calls(state, node, methods, paths):
    for method in methods:
        for path in paths:
            if method and path and has_literal(path):
                state["calls"].append([_line(node), method, path])


def _library(obj, name, args, lang, frame):
    """(methods, paths) when this call is fetch, axios, ky, httpx or requests."""
    if name == "fetch" and obj in (None, "window", "globalThis", "self"):
        paths = _eval_paths(_first_pos(args), lang, frame)
        methods = _option_method(args, lang, frame) or ["GET"]
        return methods, paths
    if obj in ("axios", "ky") and name and name.lower() in VERBS:
        return [name.upper()], _eval_paths(_first_pos(args), lang, frame)
    if obj in ("axios", "ky") and name is None:
        return _axios_call(args, lang, frame)
    if name in ("axios", "ky") and obj is None:
        return _axios_call(args, lang, frame)
    if obj in ("requests", "httpx") and name and name.lower() in VERBS:
        return [name.upper()], _eval_paths(_first_pos(args), lang, frame)
    if obj in ("requests", "httpx") and name == "request":
        return _method_and_path(args, lang, frame)
    if name in ("requests", "httpx") and obj is None:
        return None
    return None


def _axios_call(args, lang, frame):
    first = _first_pos(args)
    if first is not None and _is_object(first):
        url = _object_prop(first, "url", lang)
        method = _verb_text(_plain(_object_prop(first, "method", lang), lang)) or "GET"
        return [method], _eval_paths(url, lang, frame)
    paths = _eval_paths(first, lang, frame)
    methods = _option_method(args[1:], lang, frame) or ["GET"]
    return methods, paths


def _method_and_path(args, lang, frame):
    positional = [value for kind, _key, value in args if kind == "pos"]
    if len(positional) < 2:
        return None
    method = _eval_verbs(positional[0], lang, frame)
    paths = _eval_paths(positional[1], lang, frame)
    if not method:
        return None
    return method, paths


def _is_method_path(args, lang, frame):
    positional = [value for kind, _key, value in args if kind == "pos"]
    if len(positional) < 2:
        return None
    methods = _eval_verbs(positional[0], lang, frame)
    paths = _eval_paths(positional[1], lang, frame)
    if not methods or not paths:
        return None
    return methods, paths


def _wrapper_call(state, node, spec, args, lang, frame):
    positional = [value for kind, _key, value in args if kind == "pos"]
    if spec["method"]:
        methods = [spec["method"]]
    elif spec["method_index"] is not None and spec["method_index"] < len(positional):
        methods = _eval_verbs(positional[spec["method_index"]], lang, frame)
    else:
        methods = ["GET"]
    index = spec["path_index"]
    if index is None or index >= len(positional):
        return
    paths = _eval_paths(positional[index], lang, frame)
    _emit_calls(state, node, methods or ["GET"], paths)


def _first_pos(args):
    for kind, _key, value in args:
        if kind == "pos":
            return value
    return None


def _option_method(args, lang, frame):
    """Verbs from a fetch/axios options object, or None when the call has none."""
    nodes = args
    if nodes and isinstance(nodes[0], tuple):
        nodes = [value for kind, _key, value in nodes if kind == "pos"]
        if not nodes:
            return None
        nodes = nodes[1:] if len(nodes) > 1 else []
        # called with the arg list; the options object is the second positional, already sliced by caller
    for node in nodes if not (args and isinstance(args[0], tuple)) else []:
        if _is_object(node):
            verb = _verb_text(_plain(_object_prop(node, "method", lang), lang))
            if verb:
                return [verb]
            prop = _object_prop(node, "method", lang)
            if prop is not None:
                return _eval_verbs(prop, lang, frame) or None
    if args and isinstance(args[0], tuple):
        positional = [value for kind, _key, value in args if kind == "pos"]
        if len(positional) >= 2 and _is_object(positional[1]):
            prop = _object_prop(positional[1], "method", lang)
            verb = _verb_text(_plain(prop, lang))
            if verb:
                return [verb]
            if prop is not None:
                found = _eval_verbs(prop, lang, frame)
                if found:
                    return found
    return None


def _note_library(node, lang, frame):
    obj, name = _callee(node, lang)
    args = _args(node, lang)
    found = _library(obj, name, args, lang, frame)
    if not found:
        return
    path_node = _library_path_node(obj, name, args)
    method_node, fixed = _library_method(obj, name, args, lang)
    frame["library"].append((path_node, method_node, fixed))


def _library_path_node(obj, name, args):
    if obj in ("requests", "httpx") and name == "request":
        positional = [value for kind, _key, value in args if kind == "pos"]
        return positional[1] if len(positional) > 1 else None
    if name in ("axios", "ky") or obj in ("axios", "ky"):
        first = _first_pos(args)
        if first is not None and _is_object(first):
            return None  # object url is handled only when it is a plain param; skip for wrappers
        return first
    return _first_pos(args)


def _library_method(obj, name, args, lang):
    if name and name.lower() in VERBS and obj in CLIENTS:
        return None, name.upper()
    if name == "fetch":
        positional = [value for kind, _key, value in args if kind == "pos"]
        if len(positional) >= 2 and _is_object(positional[1]):
            prop = _object_prop(positional[1], "method", lang)
            verb = _verb_text(_plain(prop, lang))
            if verb:
                return None, verb
            return prop, None
        return None, "GET"
    if obj in ("requests", "httpx") and name == "request":
        positional = [value for kind, _key, value in args if kind == "pos"]
        return (positional[0] if positional else None), None
    return None, "GET"


def _wrapper_spec(library, params):
    """A function that passes one parameter through to fetch/axios/ky/httpx/requests."""
    if not library or not params:
        return None
    path_name = None
    method_name = None
    fixed = None
    for path_node, method_node, method_fixed in library:
        name = _param_ref(path_node, params)
        if not name:
            return None
        if path_name and path_name != name:
            return None
        path_name = name
        if method_fixed:
            if fixed and fixed != method_fixed:
                return None
            fixed = method_fixed
        else:
            ref = _param_ref(method_node, params)
            if ref:
                method_name = ref
            elif method_node is not None:
                return None
            else:
                fixed = fixed or "GET"
    if not path_name:
        return None
    return {
        "path_index": params.index(path_name),
        "method": fixed,
        "method_index": params.index(method_name) if method_name in params else None,
    }


def _param_ref(node, params):
    """The one parameter this URL expression references, when it has no literal segment."""
    node = _unwrap(node)
    if node is None:
        return None
    if node.type in ("identifier", "shorthand_property_identifier") and _text(node) in params:
        return _text(node)
    pieces = None
    names = []
    if node.type == "template_string" or (node.type == "string" and any(c.type == "interpolation" for c in node.named_children)):
        if node.type == "template_string":
            for child in node.named_children:
                if child.type == "template_substitution":
                    ident = next((c for c in child.named_children if c.type == "identifier"), None)
                    if ident is None or len(child.named_children) != 1:
                        return None
                    names.append(_text(ident))
                elif child.type == "string_fragment" and _text(child).strip("/?#"):
                    return None
        else:
            for child in node.named_children:
                if child.type == "interpolation":
                    ident = next((c for c in child.named_children if c.type == "identifier"), None)
                    if ident is None:
                        return None
                    names.append(_text(ident))
                elif child.type == "string_content" and _text(child).strip("/?#"):
                    return None
        if len(set(names)) == 1 and names[0] in params:
            return names[0]
    return None


def _note_local(frame, name, value, lang):
    if not name or value is None:
        return
    paths = _eval_paths(value, lang, frame)
    if paths:
        frame["locals"][name] = paths
        return
    verbs = _eval_verbs(value, lang, frame)
    if verbs:
        frame["locals"][name] = verbs


def _eval_paths(node, lang, frame):
    node = _unwrap(node)
    if node is None:
        return []
    pieces = _pieces(node, lang)
    if pieces is not None:
        raw = "".join(part for part in pieces if isinstance(part, str))
        path = from_pieces(pieces)
        # A bare word (`dict.get("key")`) is not a URL. The source has to contain a slash.
        return [path] if path and has_literal(path) and "/" in raw else []
    if node.type == "identifier":
        found = frame["locals"].get(_text(node), [])
        return [item for item in found if isinstance(item, str) and item.startswith("/")]
    arms = _arms(node)
    if arms:
        return _eval_paths(arms[0], lang, frame) + _eval_paths(arms[1], lang, frame)
    return []


def _eval_verbs(node, lang, frame):
    node = _unwrap(node)
    if node is None:
        return []
    verb = _verb_text(_plain(node, lang))
    if verb:
        return [verb]
    if node.type == "identifier":
        found = frame["locals"].get(_text(node), [])
        return [item for item in found if item in {v.upper() for v in VERBS} or item in ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS")]
    arms = _arms(node)
    if arms:
        return _eval_verbs(arms[0], lang, frame) + _eval_verbs(arms[1], lang, frame)
    return []


def _verb_text(text):
    if not text:
        return None
    verb = text.strip().strip("\"'").upper()
    if verb in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}:
        return verb
    return None


def _arms(node):
    if node is None or node.type not in ("conditional_expression", "ternary_expression"):
        return None
    cons = node.child_by_field_name("consequence")
    alt = node.child_by_field_name("alternative")
    if cons is not None and alt is not None:
        return cons, alt
    named = list(node.named_children)
    if len(named) >= 3:
        return named[0], named[2]
    return None


# --- C# ------------------------------------------------------------------------


def _csharp(root):
    state = {"routers": [], "mounts": [], "routes": [], "calls": []}
    groups = {}
    pending = []
    _cs_groups(root, pending)
    _resolve_groups(pending, groups)
    _cs_walk(root, state, None, groups)
    return state


def _cs_groups(node, pending):
    if node is None:
        return
    if node.type == "variable_declarator":
        name = node.child_by_field_name("name")
        value = node.child_by_field_name("value") or next((c for c in node.named_children if c.type == "invocation_expression"), None)
        if name is not None and name.type == "identifier" and value is not None and value.type == "invocation_expression":
            obj, method = _cs_member(value)
            if method == "MapGroup":
                path = _cs_string_arg(value)
                if path is not None:
                    pending.append((_text(name), obj, path))
    for child in node.named_children:
        _cs_groups(child, pending)


def _resolve_groups(pending, groups):
    left = list(pending)
    changed = True
    while changed and left:
        changed = False
        stay = []
        names = {name for name, _obj, _path in left}
        for name, obj, path in left:
            if obj in names and obj not in groups:
                stay.append((name, obj, path))
                continue
            groups[name] = join_path(groups.get(obj, ""), path)
            changed = True
        left = stay


def _cs_walk(node, state, class_info, groups):
    if node is None:
        return
    if node.type == "class_declaration":
        info = _class_route(node)
        body = next((c for c in node.named_children if c.type == "declaration_list"), None)
        for child in body.named_children if body is not None else ():
            _cs_walk(child, state, info, groups)
        return
    if node.type == "method_declaration" and class_info:
        _method_routes(node, state, class_info)
    if node.type == "invocation_expression":
        _map_call(node, state, groups)
    for child in node.named_children:
        if node.type == "class_declaration":
            continue
        _cs_walk(child, state, class_info, groups)


def _class_route(node):
    name = None
    for child in node.children:
        if child.type == "identifier":
            name = _text(child)
            break
    route = ""
    for group in node.children:
        if group.type != "attribute_list":
            continue
        for attr in _attributes(group):
            if _attr_name(attr) == "Route":
                text = _attr_string(attr)
                if text is not None:
                    route = text
    token = name[:-10] if name and name.endswith("Controller") and len(name) > 10 else (name or "")
    return {"name": name or "", "route": route, "token": token}


def _method_routes(node, state, class_info):
    http = []
    method_route = None
    action = None
    for child in node.children:
        if child.type == "identifier":
            action = _text(child)
    # The name is the identifier before the parameter list, which the loop above may set too early.
    action = _cs_method_name(node) or action or ""
    for group in node.children:
        if group.type != "attribute_list":
            continue
        for attr in _attributes(group):
            aname = _attr_name(attr)
            if aname in HTTP_ATTRS:
                http.append((HTTP_ATTRS[aname], _attr_string(attr)))
            elif aname == "Route":
                method_route = _attr_string(attr)
    if not http and method_route is None:
        return
    base = _tokens(class_info["route"], class_info["token"], action)
    if not http:
        # A method [Route] with no [HttpGet] is GET. The template is the [Route] path.
        http = [("GET", method_route)]
    for method, template in http:
        if template is None:
            template = method_route if method_route is not None else ""
        template = _tokens(template, class_info["token"], action)
        if template.startswith("/"):
            path = normalise(template)
        else:
            path = join_path(base, template)
        if not method:
            continue
        state["routes"].append([("line", _line(node)), method, path, None, None])


def _cs_method_name(node):
    children = list(node.children)
    stop = None
    for index, child in enumerate(children):
        if child.type in ("parameter_list", "arrow_expression_clause"):
            stop = index
            break
    if stop is None:
        return None
    for child in reversed(children[:stop]):
        if child.type == "identifier":
            return _text(child)
    return None


def _map_call(node, state, groups):
    obj, name = _cs_member(node)
    method = MAP_VERBS.get(name or "")
    if not method:
        return
    path = _cs_string_arg(node)
    if path is None:
        return
    prefix = groups.get(obj or "", "")
    if path.startswith("/"):
        full = join_path(prefix, path) if prefix else normalise(path)
    else:
        full = join_path(prefix, path)
    handler = _cs_handler(node)
    state["routes"].append([handler, method, full, None, None])


def _cs_handler(node):
    args = _cs_args(node)
    if len(args) < 2:
        return ("line", _line(node))
    arg = args[1]
    if arg.type == "identifier":
        return ("name", _text(arg))
    ident = next((c for c in arg.named_children if c.type == "identifier"), None)
    if arg.type == "argument":
        inner = next((c for c in arg.named_children if c.type != "attribute_list"), None)
        if inner is not None and inner.type == "identifier":
            return ("name", _text(inner))
        if inner is not None and inner.type in ("lambda_expression", "anonymous_method_expression"):
            return ("line", _line(node))
    if ident is not None and arg.type == "identifier":
        return ("name", _text(ident))
    return ("line", _line(node))


def _cs_member(node):
    member = next((c for c in node.named_children if c.type == "member_access_expression"), None)
    if member is None:
        return None, None
    obj = None
    name = None
    for child in member.children:
        if child.type in (".", "argument_list"):
            continue
        if obj is None:
            obj = child
        elif child.type == "identifier":
            name = _text(child)
    obj_name = _text(obj) if obj is not None and obj.type == "identifier" else None
    return obj_name, name


def _cs_args(node):
    arglist = next((c for c in node.named_children if c.type == "argument_list"), None)
    if arglist is None:
        return []
    return [c for c in arglist.named_children if c.type == "argument"]


def _cs_string_arg(node):
    for arg in _cs_args(node):
        for child in arg.named_children:
            if child.type == "string_literal":
                return _cs_string(child)
            if child.type == "interpolated_string_expression":
                return None
        # A string can be the argument's direct named content.
        text = _cs_string(arg)
        if text is not None:
            return text
    return None


def _cs_string(node):
    if node is None:
        return None
    if node.type == "string_literal":
        if any(c.type == "interpolation" for c in node.named_children):
            return None
        parts = [c for c in node.named_children if c.type in ("string_literal_content", "verbatim_string_literal_content")]
        if parts:
            return "".join(_text(c) for c in parts)
        raw = _text(node)
        if len(raw) >= 2 and raw[0] == raw[-1]:
            return raw[1:-1]
    return None


def _attributes(group):
    return [child for child in group.named_children if child.type == "attribute"]


def _attr_name(attr):
    for child in attr.children:
        if child.type == "identifier":
            return _text(child).removesuffix("Attribute")
        if child.type == "qualified_name":
            return _text(child).split(".")[-1].removesuffix("Attribute")
    return None


def _attr_string(attr):
    for child in attr.children:
        if child.type != "attribute_argument_list":
            continue
        for arg in child.named_children:
            if arg.type == "string_literal":
                return _cs_string(arg)
            for inner in arg.named_children:
                if inner.type == "string_literal":
                    return _cs_string(inner)
                text = _cs_string(inner)
                if text is not None:
                    return text
    return None


def _tokens(text, controller, action):
    if not text:
        return ""
    out = []
    index = 0
    lower = text.lower()
    while index < len(text):
        if lower.startswith("[controller]", index):
            out.append(controller)
            index += len("[controller]")
            continue
        if lower.startswith("[action]", index):
            out.append(action)
            index += len("[action]")
            continue
        out.append(text[index])
        index += 1
    return "".join(out)

"""Symbols and node:test cases from TypeScript and TSX syntax trees.

Definitions are read at the top level of a file (unwrapping `export`) and as
members of classes. No import or call resolution happens here.
"""

from tree_sitter_language_pack import get_parser

GRAMMARS = {"typescript": "typescript", "tsx": "tsx"}
CLASSES = {"class_declaration", "abstract_class_declaration"}
FUNCTIONS = {"function_declaration", "generator_function_declaration"}
FUNCTION_VALUES = {"arrow_function", "function_expression"}
METHODS = {"method_definition", "abstract_method_signature"}
JSX = {"jsx_element", "jsx_self_closing_element", "jsx_fragment"}
TEST_CALLS = {"test", "it", "describe"}
TEST_SEP = " > "


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
        return len(self.defs) - 1

    def statement(self, stmt):
        decl = stmt.child_by_field_name("declaration") if stmt.type == "export_statement" else stmt
        if not decl:
            return
        doc_anchor = stmt
        name_node = decl.child_by_field_name("name")
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
        elif decl.type == "lexical_declaration":
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

    def member(self, member, parent):
        name_node = member.child_by_field_name("name")
        if not name_node:
            return
        if member.type in METHODS:
            body = member.child_by_field_name("body")
        elif member.type == "public_field_definition":
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


def parse(source, lang, is_test):
    """Return (definitions in source order, has_parse_error).

    Each definition is a dict with qualname, name, kind (symbol or test),
    display_kind, parent (index into the list or None), start_line, end_line,
    signature and doc.
    """
    tree = get_parser(GRAMMARS[lang]).parse(source)
    collector = _Collector(source)
    for stmt in tree.root_node.named_children:
        collector.statement(stmt)
    if is_test:
        collector.tests(tree.root_node, None)
    return collector.defs, tree.root_node.has_error

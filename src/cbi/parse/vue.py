"""A Vue single-file component: its script blocks are TypeScript or JavaScript, and its template tags are renders.

The component symbol is the file's default export, named after the file. Line
numbers are shifted onto the `.vue` file. Template tags that name an imported
component are calls with a trailing `jsx`, the same shape JSX uses. An
`<a href="/api/...">` in the template is a GET call on the component.
"""

import posixpath
import re

from tree_sitter_language_pack import get_parser

from cbi.http import is_api_href, normalise
from cbi.parse import typescript

GRAMMARS = {"vue": "vue"}
SCRIPT_LANG = {
    "ts": "typescript", "typescript": "typescript", "tsx": "tsx",
    "js": "javascript", "javascript": "javascript", "jsx": "javascript",
}


def _text(node):
    return node.text.decode(errors="replace")


def _attr(tag, name):
    for attr in tag.named_children:
        if attr.type != "attribute":
            continue
        aname = next((c for c in attr.children if c.type == "attribute_name"), None)
        if aname is None or _text(aname) != name:
            continue
        for child in attr.named_children:
            if child.type in ("quoted_attribute_value", "attribute_value"):
                return _text(child).strip().strip("\"'").strip()
        return ""
    return None


def _kebab(name):
    text = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1-\2", name)
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", text)
    return text.replace("_", "-").lower()


def _shift(index, base):
    return None if index is None else index + base


def _empty():
    return {
        "imports": [], "exports": {}, "reexports": [], "locals": [],
        "calls": [], "reads": [], "envs": [], "paths": [], "uses": [],
        "fields": [], "constructs": [],
        "http_routes": [], "http_calls": [], "http_routers": [], "http_mounts": [],
    }


def _merge(facts, defs, sub_facts, sub_defs, offset):
    base = len(defs)
    for defin in sub_defs:
        defin["start_line"] += offset
        defin["end_line"] += offset
        if defin["parent"] is not None:
            defin["parent"] += base
        defs.append(defin)
    facts["imports"].extend(sub_facts.get("imports") or [])
    facts["exports"].update(sub_facts.get("exports") or {})
    facts["reexports"].extend(sub_facts.get("reexports") or [])
    facts["locals"] = sorted(set(facts["locals"]) | set(sub_facts.get("locals") or []))
    for call in sub_facts.get("calls") or []:
        src, cls, *rest = call
        facts["calls"].append([_shift(src, base), _shift(cls, base), *rest])
    for read in sub_facts.get("reads") or []:
        src, *rest = read
        facts["reads"].append([_shift(src, base), *rest])
    for env in sub_facts.get("envs") or []:
        src, *rest = env
        facts["envs"].append([_shift(src, base), *rest])
    for path in sub_facts.get("paths") or []:
        facts["paths"].append(path)
    for use in sub_facts.get("uses") or []:
        src, cls, *rest = use
        facts["uses"].append([_shift(src, base), _shift(cls, base), *rest])
    for field in sub_facts.get("fields") or []:
        cls, *rest = field
        facts["fields"].append([_shift(cls, base), *rest])
    facts["constructs"].extend(sub_facts.get("constructs") or [])
    for src, pattern in sub_facts.get("visits") or []:
        facts.setdefault("visits", []).append([_shift(src, base), pattern])
    for route in sub_facts.get("routes") or []:
        item = dict(route)
        item["def"] = _shift(item.get("def"), base)
        facts.setdefault("routes", []).append(item)
    for route in sub_facts.get("http_routes") or []:
        handler, *rest = route
        facts["http_routes"].append([_shift(handler, base), *rest])
    for call in sub_facts.get("http_calls") or []:
        caller, *rest = call
        facts["http_calls"].append([_shift(caller, base), *rest])
    facts["http_routers"].extend(sub_facts.get("http_routers") or [])
    facts["http_mounts"].extend(sub_facts.get("http_mounts") or [])


def _script(element):
    start = next((c for c in element.named_children if c.type == "start_tag"), None)
    raw = next((c for c in element.named_children if c.type == "raw_text"), None)
    if start is None or raw is None or not raw.text.strip():
        return None
    lang = _attr(start, "lang") or "js"
    return raw, SCRIPT_LANG.get(lang.lower(), "javascript")


def _tag(node):
    for child in node.named_children:
        if child.type == "tag_name":
            return _text(child)
    return None


def _component(defs, facts, source, stem):
    """One component named after the file. An existing top-level symbol of that name, or the default export, is promoted."""
    top = [i for i, defin in enumerate(defs) if defin["parent"] is None and defin["kind"] == "symbol"]
    chosen = next((i for i in top if defs[i]["name"] == stem), None)
    if chosen is None:
        exported = facts["exports"].get("default")
        chosen = next((i for i in top if defs[i]["name"] == exported), None) if exported else None
    if chosen is not None:
        defs[chosen]["name"] = stem
        defs[chosen]["qualname"] = stem
        defs[chosen]["display_kind"] = "component"
        return chosen
    text = source.decode("utf-8", "replace") if isinstance(source, (bytes, bytearray)) else source
    end = max(len(text.splitlines()), 1)
    defs.append({
        "qualname": stem, "name": stem, "kind": "symbol", "display_kind": "component",
        "parent": None, "start_line": 1, "end_line": end,
        "signature": f"component {stem}", "doc": None,
    })
    return len(defs) - 1


def _renders(tree, facts, component):
    bindings = {}
    for imp in facts["imports"]:
        for local in imp.get("names") or {}:
            if not local or local == "*":
                continue
            bindings[local] = local
            bindings[_kebab(local)] = local
    if not bindings:
        return

    def walk(node):
        if node.type in ("start_tag", "self_closing_tag"):
            tag = _tag(node)
            local = bindings.get(tag) if tag else None
            if local:
                facts["calls"].append([component, None, "name", local, None, "jsx"])
        for child in node.named_children:
            walk(child)

    for node in tree.root_node.named_children:
        if node.type == "template_element":
            walk(node)


def _hrefs(tree, facts, component):
    """`<a href="/api/...">` is a GET on the component. Other hrefs are page links."""
    def walk(node):
        if node.type in ("start_tag", "self_closing_tag") and _tag(node) == "a":
            href = _attr(node, "href")
            path = normalise(href) if href and "/" in href else None
            if is_api_href(path):
                item = [component, "GET", path]
                if item not in facts["http_calls"]:
                    facts["http_calls"].append(item)
        for child in node.named_children:
            walk(child)

    for node in tree.root_node.named_children:
        if node.type == "template_element":
            walk(node)


def parse(source, lang, is_test, path):
    """Return (definitions, facts, has_parse_error) for one `.vue` file."""
    del lang
    tree = get_parser("vue").parse(source)
    defs, facts, has_error = [], _empty(), tree.root_node.has_error
    for element in tree.root_node.named_children:
        if element.type != "script_element":
            continue
        found = _script(element)
        if found is None:
            continue
        raw, script_lang = found
        sub_defs, sub_facts, sub_error = typescript.parse(bytes(raw.text), script_lang, is_test)
        _merge(facts, defs, sub_facts, sub_defs, raw.start_point.row)
        has_error = has_error or sub_error
    stem = posixpath.splitext(posixpath.basename(path))[0] or "component"
    component = _component(defs, facts, source, stem)
    facts["exports"]["default"] = stem
    if stem not in facts["locals"]:
        facts["locals"] = sorted(set(facts["locals"]) | {stem})
    _renders(tree, facts, component)
    if not is_test:
        _hrefs(tree, facts, component)
    return defs, facts, has_error

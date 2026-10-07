"""Parsers per language. Each turns one file's bytes into symbol and test nodes and resolution facts."""

from cbi.ids import symbol_ids
from cbi.parse import typescript

LANGS = set(typescript.GRAMMARS)


def symbol_nodes(file_node_id, workspace_id, path, lang, source, is_test):
    """Return (nodes, facts, has_parse_error) for one file.

    Nodes carry stable IDs and parent IDs. In facts, calls and reads name the
    innermost enclosing definition by node ID, or None for the file itself.
    """
    defs, facts, has_error = typescript.parse(source, lang, is_test)
    ids = symbol_ids(file_node_id, [(d["qualname"], d["signature"]) for d in defs])
    nodes = [{
        "id": ids[i],
        "parent_id": file_node_id if d["parent"] is None else ids[d["parent"]],
        "kind": d["kind"],
        "display_kind": d["display_kind"],
        "name": d["name"],
        "workspace_id": workspace_id,
        "path": path,
        "start_line": d["start_line"],
        "end_line": d["end_line"],
        "lang": lang,
        "loc": d["end_line"] - d["start_line"] + 1,
        "signature": d["signature"],
        "doc": d["doc"],
    } for i, d in enumerate(defs)]
    at = lambda i: None if i is None else ids[i]
    facts["calls"] = [[at(d), at(c), *rest] for d, c, *rest in facts["calls"]]
    facts["reads"] = [[at(d), *rest] for d, *rest in facts["reads"]]
    return nodes, facts, has_error

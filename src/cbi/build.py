"""Static viewer export: copies the viewer assets and writes the model as script files.

`data/concepts.js` is the concept map the viewer draws. `data/tree.js` stays the
node list search falls back to. With no concept nodes, the map is deployables,
packages and externals, with depends_on edges and an includes arrow where a
deployable and a package share files. A box drills into its folders.
"""

import json
import os
import re
import shutil
from pathlib import Path

from cbi import context

ASSETS = Path(__file__).parent / "viewer"
TREE_FIELDS = ("id", "parent_id", "kind", "display_kind", "name", "path", "start_line", "end_line", "loc",
               "signature", "doc", "summary")
SHOWN = {"class", "function", "component"}
# The mockup's derive.py badges a symbol from tests edges at this confidence and above.
TEST_CONFIDENCE = 0.6
ROLE_BY_LABEL = {
    "ui": "ui", "interface": "ui",
    "app": "app", "app or process": "app",
    "service": "service",
    "core": "core", "core logic": "core",
    "data": "data", "data and model": "data",
}
# Architecture says external kind `os`. The mockup's colour class is `terminal`.
KIND_BY_LABEL = {
    "platform": "platform", "platform service": "platform",
    "cli": "cli", "cli tool": "cli",
    "saas": "saas", "saas or api": "saas",
    "os": "terminal", "terminal": "terminal", "terminal or os": "terminal",
    "storage": "storage",
}
FALLBACK_ROLE = {
    "web app": "ui", "cli": "app", "node app": "app", "electron app": "app", "worker": "app",
    "container image": "app", "service": "service", "package": "core",
    "library": "core", "skill": "core", "repertoire": "core",
}
RESULT = {
    "pass": "pass", "passed": "pass", "ok": "pass",
    "fail": "fail", "failed": "fail", "failure": "fail", "error": "fail",
    "skipped": "skipped", "skip": "skipped",
}
RESULT_RANK = {"fail": 0, "skipped": 1, "pass": 2}
# Same shape as the mockup's derive.py: `export { A as B } from "./mod"` and `export * from`.
REEXPORT = re.compile(r"""export\s+(?!type\b)(\*|\{([^}]*)\})\s+from\s+["']([^"']+)["']""")


def build(conn, out, root=None, compare=None, place=None, *, editor="vscode", project=None, ref_sha=None):
    """Write the viewer into out/. Returns the path of index.html.

    compare, when set, is the head's counterpart: {"base", "base_root", "changes",
    "base_label", "head_label"}. The viewer is still the head model. data/diff.js
    is null without a comparison, which leaves comparison mode off.
    place is the repo and model the Copy for agent block names. Without one,
    it is inferred from out and root.
    editor is the static viewer's URL scheme: vscode, cursor, or none.
    project is the absolute checkout the scheme opens. It defaults to root.
    ref_sha, when set, marks a ref view: the static viewer copies a git show
    command instead of opening a vscode:// link to a file that may not be on disk.
    """
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    for name in ("index.html", "app.js", "style.css", "open-editor.js"):
        shutil.copyfile(ASSETS / name, out / name)
    vendor = out / "vendor"
    vendor.mkdir(exist_ok=True)
    for name in ("elk.bundled.js", "elkjs-LICENSE.md"):
        shutil.copyfile(ASSETS / "vendor" / name, vendor / name)
    data = out / "data"
    data.mkdir(exist_ok=True)
    (data / "tree.js").write_text(_script("tree", {"nodes": _tree(conn)}))
    concepts = concept_view(conn, root)
    (data / "concepts.js").write_text(_script("concepts", concepts))
    if place is None:
        place = context.infer_place(out, root, compare)
    (data / "context.js").write_text(_script("context", context.embed(conn, concepts, place)))
    payload = None
    if compare:
        payload = compare_payload(
            conn, compare["base"], compare["changes"], root, compare.get("base_root"),
            compare.get("base_label") or "", compare.get("head_label") or "",
        )
    (data / "diff.js").write_text(_script("diff", payload))
    editor_payload = {
        "editor": editor if editor in ("vscode", "cursor", "none") else "vscode",
        "root": _project_root(root, project),
    }
    if ref_sha:
        editor_payload["sha"] = ref_sha
    (data / "editor.js").write_text(_script("editor", editor_payload))
    return out / "index.html"


def _project_root(root, project):
    """Absolute path embedded for the editor URL. A commit tree exposes .root."""
    chosen = project if project is not None else root
    if isinstance(chosen, Path):
        return str(chosen.resolve())
    found = getattr(chosen, "root", None)
    if isinstance(found, Path):
        return str(found.resolve())
    return ""


def concept_view(conn, root=None):
    """The concept-map payload, or the deployable fallback when the model has no concepts."""
    nodes, edges = _load(conn)
    concepts = [n for n in nodes.values() if n["kind"] == "concept"]
    if not concepts:
        return _fallback(nodes, edges)
    return _concepts(conn, nodes, edges, concepts, root)


def _script(name, data):
    body = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    return f'cbiLoad("{name}", {body});\n'


def _tree(conn):
    columns = ", ".join(TREE_FIELDS)
    return [
        {k: v for k, v in zip(TREE_FIELDS, row) if v is not None}
        for row in conn.execute(f"SELECT {columns} FROM nodes ORDER BY id")
    ]


def _load(conn):
    fields = ("id", "parent_id", "kind", "display_kind", "name", "workspace_id", "path",
              "start_line", "end_line", "signature", "summary", "attrs")
    nodes = {}
    for row in conn.execute(f"SELECT {', '.join(fields)} FROM nodes"):
        node = dict(zip(fields, row))
        node["attrs"] = _obj(node["attrs"])
        nodes[node["id"]] = node
    edges = []
    for src, dst, kind, confidence, weight, attrs in conn.execute(
            "SELECT src, dst, kind, confidence, weight, attrs FROM edges"):
        edges.append({"src": src, "dst": dst, "kind": kind, "confidence": confidence if confidence is not None else 1,
                      "weight": weight or 1, "attrs": _obj(attrs)})
    return nodes, edges


def _obj(text):
    if not text:
        return {}
    if isinstance(text, dict):
        return text
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _role(node):
    raw = node["attrs"].get("role") or node["display_kind"] or ""
    return ROLE_BY_LABEL.get(str(raw).lower(), "core")


def _ext_kind(node):
    for raw in (node["attrs"].get("kind"), node["display_kind"]):
        if isinstance(raw, str) and raw.lower() in KIND_BY_LABEL:
            return KIND_BY_LABEL[raw.lower()]
    return None


def _order(node):
    order = node["attrs"].get("order")
    return (order if isinstance(order, int) else 10**9, (node["name"] or "").lower(), node["id"])


def _workspace(nodes, concepts):
    roots = [n for n in nodes.values() if n["kind"] == "workspace" and not n["parent_id"]]
    if not roots:
        roots = [n for n in nodes.values() if n["kind"] == "workspace"]
    roots.sort(key=lambda n: n["id"])
    if not roots:
        return None
    concept_ids = {c["id"] for c in concepts}
    parents = {c["parent_id"] for c in concepts if c["parent_id"] not in concept_ids}
    return next((n for n in roots if n["id"] in parents), roots[0])


def _props(signature):
    match = re.search(r"\(\{([^}]*)\}", signature or "")
    if not match:
        return []
    props = [part.strip().split("=")[0].strip() for part in match.group(1).split(",")]
    return [prop for prop in props if prop and prop != "children"]


def _concepts(conn, nodes, edges, concepts, root=None):
    concept_ids = {c["id"] for c in concepts}
    parent = {c["id"]: c["parent_id"] if c["parent_id"] in concept_ids else None for c in concepts}
    children = {c["id"]: [] for c in concepts}
    for c in concepts:
        if parent[c["id"]]:
            children[parent[c["id"]]].append(c)
    for kids in children.values():
        kids.sort(key=_order)
    leaves = {cid for cid, kids in children.items() if not kids}
    by_path = {(n.get("workspace_id"), n.get("path")): n for n in nodes.values() if n["kind"] == "file"}
    symbols = {n["id"]: n for n in nodes.values() if n["kind"] == "symbol"}

    def file_of(node):
        if node["kind"] == "file":
            return node
        if node["kind"] == "symbol":
            return by_path.get((node.get("workspace_id"), node.get("path")))
        return None

    def test_file(node):
        file = file_of(node) if node else None
        return bool(file and file["display_kind"] == "test file")

    owner = {}
    for edge in edges:
        if edge["kind"] != "owns" or edge["dst"] not in nodes:
            continue
        if edge["dst"] not in owner or edge["src"] in leaves:
            owner[edge["dst"]] = edge["src"]

    def top_of(sid):
        seen = set()
        while sid in symbols and symbols[sid]["parent_id"] in symbols and sid not in seen:
            seen.add(sid)
            sid = symbols[sid]["parent_id"]
        return sid

    shown = {}
    for node in symbols.values():
        if node["display_kind"] not in SHOWN or node["parent_id"] in symbols:
            continue
        file = file_of(node)
        if not file or file["display_kind"] == "test file":
            continue
        leaf = owner.get(file["id"])
        if leaf not in concept_ids:
            continue
        shown[node["id"]] = _symbol(node, leaf)

    _attach_tests(conn, nodes, edges, shown, top_of)
    _attach_coverage(conn, nodes, shown, by_path)
    module_env = _attach_env(nodes, edges, shown, owner, file_of, top_of)
    calls = _leaf_calls(edges, symbols, shown, top_of)
    records = _code_records(nodes, edges, symbols, shown, owner, file_of, top_of, test_file)
    imports = _import_sides(edges, nodes, owner, test_file)
    screens = _screens(nodes, symbols)
    _attach_http(nodes, edges, symbols, shown, top_of)

    def build(node):
        out = {"id": node["id"], "name": node["name"], "summary": node["summary"] or "", "role": _role(node)}
        kids = children[node["id"]]
        if kids:
            out["children"] = [build(kid) for kid in kids]
            _copy_entry(node, out)
            return out
        ids = {sid for sid, sym in shown.items() if sym["concept"] == node["id"]}
        mine = [(a, b, verb) for (a, b), verb in calls.items() if a in ids or b in ids]
        ghosts = {}
        for a, b, _verb in mine:
            for end in (a, b):
                if end not in ids:
                    ghosts[end] = {"name": shown[end]["name"], "kind": shown[end]["kind"], "concept": shown[end]["concept"]}
        owned = [nodes[fid] for fid, leaf in owner.items() if leaf == node["id"] and fid in nodes]
        out["files"] = sorted(n["path"] for n in owned if n["display_kind"] != "test file" and n["path"])
        out["tests"] = [
            {"file": n["path"], "cases": _case_count(nodes, n["path"])}
            for n in sorted((n for n in owned if n["display_kind"] == "test file" and n["path"]), key=lambda n: n["path"])
        ]
        out["symbols"] = sorted((shown[sid] for sid in ids), key=lambda s: (s["file"], s.get("line") or 0, s["name"], s["id"]))
        out["calls"] = [list(item) for item in sorted(mine)]
        out["importsIn"] = imports["in"].get(node["id"], [])
        out["importsOut"] = imports["out"].get(node["id"], [])
        out["reexports"] = _reexports(root, out["files"], owner, nodes, shown, ids, ghosts)
        out["ghosts"] = {sid: ghosts[sid] for sid in sorted(ghosts)}
        out["env"] = _leaf_env(shown, ids, module_env.get(node["id"], {}))
        _copy_entry(node, out)
        return out

    roots = sorted((c for c in concepts if parent[c["id"]] is None), key=_order)
    ws = _workspace(nodes, concepts)
    related = {end for edge in edges if edge["kind"] == "relates" for end in (edge["src"], edge["dst"])}
    externals = []
    for node in sorted((n for n in nodes.values() if n["kind"] == "external"), key=_order):
        kind = _ext_kind(node)
        if kind is None and node["id"] not in related:
            continue  # compose image services stay out of the concept map unless a relationship names them
        externals.append({"id": node["id"], "name": node["name"], "summary": node["summary"] or "",
                          "kind": kind or (node["display_kind"] or "external").lower()})
    relationships = []
    for edge in edges:
        if edge["kind"] != "relates":
            continue
        if edge["attrs"].get("kind") == "hosts":
            # One concept runs the other. There is no call to resolve.
            relationships.append(_relationship(edge, [], "hosts"))
            continue
        both = edge["src"] in concept_ids and edge["dst"] in concept_ids
        code = _code_between(records, edge["src"], edge["dst"], parent) if both else []
        backing = _backing(code) if both else None
        evidence = _stated_evidence(
            edges, nodes, shown, owner, file_of, top_of, test_file, edge["src"], edge["dst"], parent,
        ) if backing == "stated" else None
        endpoints = _http_between(
            edges, nodes, owner, file_of, edge["src"], edge["dst"], parent,
        ) if both else None
        relationships.append(_relationship(edge, code, backing, evidence, endpoints))
    relationships.sort(key=lambda r: (r["from"], r["to"], r["label"]))
    return {
        "workspace": ws["name"] if ws else "",
        "summary": (ws["summary"] if ws else "") or "",
        "concepts": [build(c) for c in roots],
        "externals": externals,
        "relationships": relationships,
        "screens": screens,
    }


def _attach_http(nodes, edges, symbols, shown, top_of):
    """Roll HTTP calls up to the shown function or class. Keys stay absent when empty."""
    outgoing, incoming = {}, {}
    for edge in edges:
        if edge["kind"] != "http_calls":
            continue
        method = edge["attrs"].get("method") or ""
        path = edge["attrs"].get("path") or ""
        src, dst = edge["src"], edge["dst"]
        src_top = top_of(src) if src in symbols else None
        dst_top = top_of(dst) if dst in symbols else None
        dst_name = (nodes.get(dst) or {}).get("name") or ""
        src_name = (nodes.get(src) or {}).get("name") or ""
        if src_top in shown:
            outgoing.setdefault(src_top, []).append({
                "method": method, "path": path, "id": dst, "name": dst_name,
                "fn": dst_top if dst_top in shown else None,
            })
        if dst_top in shown:
            incoming.setdefault(dst_top, []).append({
                "method": method, "path": path, "id": src, "name": src_name,
                "fn": src_top if src_top in shown else None,
            })

    def put(sid, key, rows):
        seen = set()
        kept = []
        for row in sorted(rows, key=lambda item: (item["method"], item["path"], item["name"], item["id"] or "")):
            ident = (row["method"], row["path"], row["id"])
            if ident in seen:
                continue
            seen.add(ident)
            kept.append(row)
        if kept:
            shown[sid][key] = kept

    for sid, rows in outgoing.items():
        put(sid, "httpOut", rows)
    for sid, rows in incoming.items():
        put(sid, "httpIn", rows)


def _http_between(edges, nodes, owner, file_of, src_concept, dst_concept, parent):
    """HTTP calls from src_concept's tree to dst_concept's tree, for one relates edge."""
    found = []
    seen = set()
    for edge in edges:
        if edge["kind"] != "http_calls":
            continue
        src_node, dst_node = nodes.get(edge["src"]), nodes.get(edge["dst"])
        if not src_node or not dst_node:
            continue
        src_file, dst_file = file_of(src_node), file_of(dst_node)
        src_leaf = owner.get(src_file["id"]) if src_file else None
        dst_leaf = owner.get(dst_file["id"]) if dst_file else None
        if not _under(src_leaf, src_concept, parent) or not _under(dst_leaf, dst_concept, parent):
            continue
        method = edge["attrs"].get("method") or ""
        path = edge["attrs"].get("path") or ""
        key = (method, path, edge["src"], edge["dst"])
        if key in seen:
            continue
        seen.add(key)
        found.append({
            "method": method, "path": path, "src": edge["src"], "dst": edge["dst"],
            "src_name": src_node.get("name") or "", "dst_name": dst_node.get("name") or "",
            "id": edge["dst"], "name": dst_node.get("name") or "",
            "fn": _shown_fn(nodes, edge["dst"]),
        })
    found.sort(key=lambda item: (item["method"], item["path"], item["src_name"], item["dst_name"]))
    return found


def _shown_fn(nodes, nid):
    """The shown function or class a handler rolls up to, when it has one."""
    seen = set()
    while nid and nid not in seen:
        seen.add(nid)
        node = nodes.get(nid)
        if not node or node.get("kind") != "symbol":
            return None
        if node.get("display_kind") in SHOWN:
            return nid
        nid = node.get("parent_id")
    return None


def _symbol(node, leaf):
    sym = {
        "id": node["id"], "name": node["name"], "kind": node["display_kind"],
        "file": node["path"] or "", "line": node["start_line"] or 0, "concept": leaf, "tests": [],
    }
    if node["signature"]:
        sym["sig"] = node["signature"]
    if node["display_kind"] == "component":
        sym["props"] = _props(node["signature"])
        reads = node["attrs"].get("reads")
        if isinstance(reads, list):
            sym["reads"] = [str(item) for item in reads]
    return sym


def _attach_tests(conn, nodes, edges, shown, top_of):
    results = {}
    for test_id, status in conn.execute("SELECT test_node_id, status FROM results"):
        norm = RESULT.get(str(status).lower())
        if norm and (test_id not in results or RESULT_RANK[norm] < RESULT_RANK[results[test_id]]):
            results[test_id] = norm
    for edge in edges:
        if edge["kind"] != "tests" or edge["confidence"] < TEST_CONFIDENCE:
            continue
        sym = shown.get(top_of(edge["dst"]))
        if not sym:
            continue
        name = nodes.get(edge["src"], {}).get("name")
        if name and name not in sym["tests"]:
            sym["tests"].append(name)
        result = results.get(edge["src"])
        if result and (not sym.get("result") or RESULT_RANK[result] < RESULT_RANK[sym["result"]]):
            sym["result"] = result
    for sym in shown.values():
        sym["tests"].sort()


def _attach_coverage(conn, nodes, shown, by_path):
    lines = {}
    for file_id, line, hits in conn.execute(
            "SELECT file_id, line, max(hits) FROM coverage_lines GROUP BY file_id, line"):
        lines.setdefault(file_id, {})[line] = hits
    if not lines:
        return
    for sym in shown.values():
        node = nodes[sym["id"]]
        file = by_path.get((node.get("workspace_id"), node.get("path")))
        start, end = node.get("start_line"), node.get("end_line")
        if not file or file["id"] not in lines or not start or not end:
            continue
        measured = [hits for line, hits in lines[file["id"]].items() if start <= line <= end]
        if measured:
            sym["cov"] = round(100 * sum(1 for hits in measured if hits) / len(measured), 1)


def _attach_env(nodes, edges, shown, owner, file_of, top_of):
    """Symbol reads land on the symbol. Module-level reads (the src is a file) return per leaf."""
    envs = {n["id"]: n for n in nodes.values() if n["kind"] == "env"}
    module = {}
    for edge in edges:
        if edge["kind"] != "reads_env" or edge["dst"] not in envs:
            continue
        src = nodes.get(edge["src"])
        if not src:
            continue
        file = file_of(src)
        leaf = owner.get(file["id"]) if file else None
        if not leaf:
            continue
        env = envs[edge["dst"]]
        default = edge["attrs"].get("default")
        declared = _declared(env)
        top = top_of(edge["src"]) if src["kind"] == "symbol" else None
        sym = shown.get(top) if top and shown.get(top, {}).get("concept") == leaf else None
        if sym:
            entry = sym.setdefault("_env", {}).setdefault(env["name"], {"default": None, "declared": declared})
            if entry["default"] is None and default is not None:
                entry["default"] = default
            if declared and not entry["declared"]:
                entry["declared"] = declared
            names = sym.setdefault("env", [])
            if env["name"] not in names:
                names.append(env["name"])
        else:
            entry = module.setdefault(leaf, {}).setdefault(env["name"], {"default": None, "declared": declared, "symbols": []})
            if entry["default"] is None and default is not None:
                entry["default"] = default
            if declared and not entry["declared"]:
                entry["declared"] = declared
    return module


def _declared(env):
    raw = env["attrs"].get("declared_in")
    if isinstance(raw, list):
        return ", ".join(str(item) for item in raw)
    return str(raw) if raw else None


def _import_sides(edges, nodes, owner, test_file):
    """Import edges between leaves, grouped the way the mockup draws them.

    importsIn on a leaf lists who imports it, with the files of this leaf they import.
    importsOut lists who it imports, with those files.
    """
    incoming, outgoing = {}, {}
    for edge in edges:
        if edge["kind"] != "imports" or edge["attrs"].get("type_only"):
            continue  # type-only imports are evidence for a stated relationship, not a resolved one
        src, dst = nodes.get(edge["src"]), nodes.get(edge["dst"])
        if not src or not dst or src["kind"] != "file" or dst["kind"] != "file":
            continue
        if test_file(src) or test_file(dst):
            continue
        src_leaf, dst_leaf = owner.get(src["id"]), owner.get(dst["id"])
        if not src_leaf or not dst_leaf or src_leaf == dst_leaf or not dst.get("path"):
            continue
        incoming.setdefault(dst_leaf, {}).setdefault(src_leaf, set()).add(dst["path"])
        outgoing.setdefault(src_leaf, {}).setdefault(dst_leaf, set()).add(dst["path"])

    def pack(bucket):
        return {
            leaf: [{"concept": other, "files": sorted(files)} for other, files in sorted(groups.items())]
            for leaf, groups in bucket.items()
        }

    return {"in": pack(incoming), "out": pack(outgoing)}


def _reexports(root, files, owner, nodes, shown, ids, ghosts):
    """Re-exports in this leaf's files, and the symbol that defines each one.

    The model does not store re-exports, so this reads the source the way the mockup does.
    Without a repo root (unit tests, a model copied off its tree) the list stays empty.
    """
    if root is None:
        return []
    if isinstance(root, (str, Path)):
        root = Path(root)
    by_path = {}
    for node in nodes.values():
        if node["kind"] == "file" and node.get("path"):
            by_path[node["path"]] = node["id"]
    named = {}
    for sym in shown.values():
        named.setdefault(sym["file"], {})[sym["name"]] = sym
    found = []
    for rel in files:
        try:
            text = (root / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for match in REEXPORT.finditer(text):
            base = os.path.normpath(str(Path(rel).parent / match.group(3)))
            target = next((t for t in (base, base + ".ts", base + ".tsx", base + "/index.ts") if t in by_path), None)
            if not target or owner.get(by_path[target]) is None:
                continue
            concept = owner[by_path[target]]
            raw = ["*"] if match.group(1) == "*" else [
                part.strip() for part in (match.group(2) or "").split(",")
                if part.strip() and not part.strip().startswith("type ")
            ]
            for name in raw:
                src_name, _, as_name = name.partition(" as ")
                src_name, as_name = src_name.strip(), as_name.strip()
                defined = named.get(target, {}).get(src_name)
                found.append({"name": as_name or src_name, "concept": concept, "def": defined["id"] if defined else None})
                if defined and defined["id"] not in ids:
                    ghosts.setdefault(defined["id"], {
                        "name": defined["name"], "kind": defined["kind"], "concept": defined["concept"],
                    })
    return found


def _leaf_calls(edges, symbols, shown, top_of):
    verbs = {}
    for edge in edges:
        if edge["kind"] != "calls" or edge["attrs"].get("via") == "injection":
            continue  # a call through an injected field is evidence, not a resolved call
        src, dst = top_of(edge["src"]), top_of(edge["dst"])
        if src not in shown or dst not in shown or src == dst:
            continue
        verb = "renders" if edge["attrs"].get("via") == "jsx" else "calls"
        if verbs.get((src, dst)) != "renders":
            verbs[(src, dst)] = verb
    return verbs


def _code_records(nodes, edges, symbols, shown, owner, file_of, top_of, test_file):
    records = []
    for edge in edges:
        if edge["kind"] not in ("imports", "calls"):
            continue
        if edge["attrs"].get("type_only") or edge["attrs"].get("via") == "injection":
            continue  # stated-relationship evidence, not a resolved call or value import
        src_node, dst_node = nodes.get(edge["src"]), nodes.get(edge["dst"])
        if not src_node or not dst_node or test_file(src_node) or test_file(dst_node):
            continue
        src_file, dst_file = file_of(src_node), file_of(dst_node)
        src_leaf = owner.get(src_file["id"]) if src_file else None
        dst_leaf = owner.get(dst_file["id"]) if dst_file else None
        if not src_leaf or not dst_leaf:
            continue
        sid, sname = _end(edge["src"], src_node, shown, top_of, src_file)
        did, dname = _end(edge["dst"], dst_node, shown, top_of, dst_file)
        if sid == did:
            continue
        rec = {"kind": edge["kind"], "src": sid, "dst": did, "src_name": sname, "dst_name": dname,
               "src_leaf": src_leaf, "dst_leaf": dst_leaf, "weight": edge["weight"]}
        if edge["attrs"].get("via") == "jsx":
            rec["via"] = "jsx"
        records.append(rec)
    return records


def _end(node_id, node, shown, top_of, file):
    if node["kind"] == "symbol":
        top = top_of(node_id)
        if top in shown:
            return top, shown[top]["name"]
    if file:
        return file["id"], file["name"]
    return node_id, node["name"]


def _code_between(records, src_concept, dst_concept, parent):
    grouped = {}
    for rec in records:
        if not _under(rec["src_leaf"], src_concept, parent) or not _under(rec["dst_leaf"], dst_concept, parent):
            continue
        key = (rec["kind"], rec["src"], rec["dst"], rec.get("via") or "")
        slot = grouped.get(key)
        if slot is None:
            slot = {"kind": rec["kind"], "src": rec["src"], "dst": rec["dst"],
                    "src_name": rec["src_name"], "dst_name": rec["dst_name"], "weight": 0}
            if rec.get("via"):
                slot["via"] = rec["via"]
            grouped[key] = slot
        slot["weight"] += rec["weight"]
    return [grouped[key] for key in sorted(grouped)]


def _under(leaf, concept, parent):
    seen = set()
    while leaf and leaf not in seen:
        if leaf == concept:
            return True
        seen.add(leaf)
        leaf = parent.get(leaf)
    return False


def _backing(code):
    """What the scan resolved between two concepts. Anything else is only stated by the concept map."""
    if any(item["kind"] == "calls" for item in code):
        return "calls"
    if any(item["kind"] == "imports" for item in code):
        return "imports"
    return "stated"


def _stated_evidence(edges, nodes, shown, owner, file_of, top_of, test_file, src_concept, dst_concept, parent):
    """Type-only imports and injection calls between two concepts.

    A type-only import edge is attrs type_only, and names, line and symbol when present.
    An injection edge is a calls edge with attrs via "injection". The resolver stores
    nothing else, so the method name comes from the destination symbol. field and type
    are included only when the edge has them.
    """
    found = []
    for edge in edges:
        attrs = edge["attrs"]
        src_node, dst_node = nodes.get(edge["src"]), nodes.get(edge["dst"])
        if not src_node or not dst_node or test_file(src_node) or test_file(dst_node):
            continue
        src_file, dst_file = file_of(src_node), file_of(dst_node)
        src_leaf = owner.get(src_file["id"]) if src_file else None
        dst_leaf = owner.get(dst_file["id"]) if dst_file else None
        if not src_leaf or not dst_leaf:
            continue
        if not _under(src_leaf, src_concept, parent) or not _under(dst_leaf, dst_concept, parent):
            continue
        line = attrs.get("line") if isinstance(attrs.get("line"), int) else (src_node.get("start_line") or 0)
        path = (src_file.get("path") if src_file else "") or ""
        if edge["kind"] == "imports" and attrs.get("type_only"):
            names = attrs.get("names")
            if isinstance(names, str):
                names = [names]
            elif not isinstance(names, list):
                names = []
            symbol = attrs.get("symbol")
            found.append({
                "kind": "type import", "names": [str(n) for n in names if n], "file": path, "line": line,
                "symbol": symbol if symbol in shown else None,
            })
        elif edge["kind"] == "calls" and attrs.get("via") == "injection":
            field = attrs.get("field") or ""
            typ = attrs.get("type") or attrs.get("declared_type") or ""
            method = attrs.get("method") or (dst_node["name"] if dst_node["kind"] == "symbol" else "")
            if not method:
                continue
            sid, _name = _end(edge["src"], src_node, shown, top_of, src_file)
            item = {
                "kind": "injected", "method": str(method), "file": path, "line": line,
                "symbol": sid if sid in shown else None,
            }
            if field:
                item["field"] = str(field)
            if typ:
                item["type"] = str(typ)
            found.append(item)
    found.sort(key=lambda item: (item["file"], item["line"], item["kind"], item.get("method") or "", ",".join(item.get("names") or [])))
    return found


def _stored_entry_files(attrs):
    file = attrs.get("entry_file")
    if isinstance(file, str) and file:
        return [file]
    if isinstance(file, list):
        return [path for path in file if isinstance(path, str) and path]
    return []


def _copy_entry(node, out):
    """Copy the entry attrs apply stored. The viewer pins and marks from these, not from deployables."""
    attrs = node.get("attrs") or {}
    if attrs.get("entry") is True:
        out["entry"] = True
    files = _stored_entry_files(attrs)
    if not files:
        return
    out["entry_file"] = files[0] if len(files) == 1 else files
    out["entryFiles"] = files


def _relationship(edge, code, backing=None, evidence=None, endpoints=None):
    attrs = edge["attrs"]
    rel = {"from": edge["src"], "to": edge["dst"], "label": attrs.get("label") or ""}
    if attrs.get("kind") == "hosts":
        rel["kind"] = "hosts"
    if attrs.get("basis"):
        rel["basis"] = attrs["basis"]
    via = attrs.get("mechanism") or attrs.get("via")
    if via:
        rel["via"] = via
    if attrs.get("at"):
        rel["at"] = attrs["at"]
    if attrs.get("minor"):
        rel["minor"] = True
    if code:
        rel["code"] = code
    if backing:
        rel["backing"] = backing
    if evidence:
        rel["evidence"] = evidence
    if endpoints:
        rel["endpoints"] = endpoints
    return rel


def _case_count(nodes, path):
    return sum(1 for n in nodes.values() if n["display_kind"] == "test case" and n["path"] == path)


def _leaf_env(shown, ids, module):
    found = {}
    for sid in ids:
        for name, info in shown[sid].get("_env", {}).items():
            _merge_env(found, name, info, sid)
    for name, info in module.items():
        _merge_env(found, name, info, None)
        for sid in info.get("symbols") or []:
            if sid not in found[name]["symbols"]:
                found[name]["symbols"].append(sid)
    for sid in ids:
        shown[sid].pop("_env", None)
    return _env_items(found)


def _merge_env(found, name, info, sid):
    entry = found.setdefault(name, {"default": None, "declared": info.get("declared"), "symbols": []})
    if entry["default"] is None and info.get("default") is not None:
        entry["default"] = info["default"]
    if info.get("declared") and not entry["declared"]:
        entry["declared"] = info["declared"]
    if sid and sid not in entry["symbols"]:
        entry["symbols"].append(sid)


def _screens(nodes, symbols):
    by_ref, by_name = {}, {}
    ids = set(symbols)
    for node in symbols.values():
        if node["display_kind"] != "component":
            continue
        by_ref[f"{node['path']}#{node['name']}"] = node["id"]
        by_name.setdefault(node["name"], []).append(node["id"])

    def resolve(ref):
        if ref in ids or ref in by_ref:
            return by_ref.get(ref, ref)
        hits = by_name.get(ref) or []
        return hits[0] if len(hits) == 1 else ref

    def region(raw):
        out = {key: value for key, value in raw.items() if key != "children"}
        if out.get("component"):
            out["component"] = resolve(out["component"])
        kids = [region(kid) for kid in raw.get("children") or [] if isinstance(kid, dict)]
        if kids:
            out["children"] = kids
        return out

    screens = []
    for node in sorted((n for n in nodes.values() if n["kind"] == "screen"), key=_order):
        blob = node["attrs"]
        root = blob.get("root")
        if not isinstance(root, dict):
            root = blob if blob.get("layout") or blob.get("children") or blob.get("component") else None
        if not isinstance(root, dict):
            continue
        screens.append({"id": node["id"], "name": node["name"], "device": blob.get("device") or "desktop", "root": region(root)})
    return screens


def _file_node(nodes, node):
    seen = set()
    while node and node["id"] not in seen:
        if node["kind"] == "file":
            return node
        seen.add(node["id"])
        node = nodes.get(node.get("parent_id"))
    return None


def _env_items(found):
    out = []
    for name in sorted(found):
        entry = found[name]
        item = {"name": name, "symbols": entry["symbols"]}
        if entry["default"] is not None:
            item["default"] = entry["default"]
        if entry["declared"]:
            item["declared"] = entry["declared"]
        out.append(item)
    return out


def _env_by_file(nodes, edges):
    """reads_env edges grouped by the file that reads the variable."""
    envs = {n["id"]: n for n in nodes.values() if n["kind"] == "env"}
    found = {}
    for edge in edges:
        if edge["kind"] != "reads_env" or edge["dst"] not in envs:
            continue
        src = nodes.get(edge["src"])
        file = _file_node(nodes, src) if src else None
        if not file:
            continue
        info = {"default": edge["attrs"].get("default"), "declared": _declared(envs[edge["dst"]])}
        sid = src["id"] if src["kind"] == "symbol" else None
        _merge_env(found.setdefault(file["id"], {}), envs[edge["dst"]]["name"], info, sid)
    return found


def _env_for_files(files, by_file):
    found = {}
    for file in files:
        for name, info in by_file.get(file["id"], {}).items():
            for sid in info["symbols"] or [None]:
                _merge_env(found, name, info, sid)
    return _env_items(found)


def _member_files(nodes, edges, box_id):
    out = []
    for edge in edges:
        if edge["kind"] != "part_of" or edge["dst"] != box_id:
            continue
        node = nodes.get(edge["src"])
        if node and node["kind"] in ("file", "doc"):
            out.append(node)
    out.sort(key=lambda n: (n.get("path") or "", n["id"]))
    return out


def _split_files(nodes, files):
    code, tests = [], []
    for node in files:
        if not node.get("path"):
            continue
        if node["display_kind"] == "test file":
            tests.append({"file": node["path"], "cases": _case_count(nodes, node["path"])})
        else:
            code.append(node["path"])
    return sorted(code), tests


def _folder_concepts(nodes, box, files, by_file, role):
    """Folders that hold this box's files. A folder id is scoped to the box, so one folder can sit under two boxes."""
    folders, parent_of, root_files = {}, {}, []
    for file in files:
        chain, seen, node = [], set(), nodes.get(file.get("parent_id"))
        while node and node["id"] not in seen and node["kind"] == "group":
            seen.add(node["id"])
            chain.append(node)
            node = nodes.get(node.get("parent_id"))
        chain.reverse()
        if not chain:
            root_files.append(file)
            continue
        for i, group in enumerate(chain):
            folders.setdefault(group["id"], {"node": group, "files": []})
            parent_of.setdefault(group["id"], chain[i - 1]["id"] if i else None)
        folders[chain[-1]["id"]]["files"].append(file)

    def file_count(gid):
        return len(folders[gid]["files"]) + sum(file_count(cid) for cid, parent in parent_of.items() if parent == gid)

    def concept(gid):
        rec = folders[gid]
        kids = sorted((concept(cid) for cid, parent in parent_of.items() if parent == gid),
                      key=lambda c: (c["name"].lower(), c["id"]))
        code, tests = _split_files(nodes, rec["files"])
        n = file_count(gid)
        out = {
            "id": f"{box['id']}#{gid}", "name": rec["node"]["name"],
            "summary": rec["node"]["summary"] or f"{n} file{'' if n == 1 else 's'}", "role": role,
            "files": code, "symbols": [], "calls": [], "ghosts": {}, "tests": tests,
            "env": _env_for_files(rec["files"], by_file),
        }
        if kids:
            out["children"] = kids
        else:
            out["flat"] = True
        return out

    children = sorted((concept(gid) for gid, parent in parent_of.items() if parent is None),
                      key=lambda c: (c["name"].lower(), c["id"]))
    return children, root_files


def _fallback_relationships(edges, boxes, known):
    kinds = {n["id"]: n["kind"] for n in boxes}
    members = {}
    for edge in edges:
        if edge["kind"] == "part_of" and edge["dst"] in kinds:
            members.setdefault(edge["src"], set()).add(edge["dst"])
    shared = {(dep, pkg) for ids in members.values()
              for dep in ids if kinds.get(dep) == "deployable"
              for pkg in ids if kinds.get(pkg) == "package"}
    rels, linked = [], set()
    for edge in edges:
        if edge["kind"] != "depends_on" or edge["src"] not in known or edge["dst"] not in known:
            continue
        rels.append({"from": edge["src"], "to": edge["dst"], "label": "depends on", "basis": "depends_on"})
        linked.add((edge["src"], edge["dst"]))
    # A deployable whose entry lives in a package has no depends_on to that package. The shared files are the link.
    for dep, pkg in shared:
        if (dep, pkg) not in linked:
            rels.append({"from": dep, "to": pkg, "label": "includes", "basis": "part_of"})
    rels.sort(key=lambda r: (r["from"], r["to"], r["label"]))
    return rels


def _fallback(nodes, edges):
    ws = _workspace(nodes, [])
    boxes = sorted((n for n in nodes.values() if n["kind"] in ("deployable", "package")),
                   key=lambda n: (0 if n["kind"] == "deployable" else 1, *_order(n)))
    by_file = _env_by_file(nodes, edges)
    concepts = []
    for box in boxes:
        role = FALLBACK_ROLE.get((box["display_kind"] or "").lower(), "core")
        files = _member_files(nodes, edges, box["id"])
        children, root_files = _folder_concepts(nodes, box, files, by_file, role)
        code, tests = _split_files(nodes, root_files)
        concept = {
            "id": box["id"], "name": box["name"], "summary": box["summary"] or box["display_kind"] or "",
            "role": role, "files": code, "symbols": [], "calls": [], "ghosts": {}, "tests": tests,
            "env": _env_for_files(root_files, by_file),
        }
        if children:
            concept["children"] = children
        else:
            concept["flat"] = True
        concepts.append(concept)
    known = {n["id"] for n in boxes}
    externals = []
    for node in sorted((n for n in nodes.values() if n["kind"] == "external"), key=_order):
        known.add(node["id"])
        externals.append({"id": node["id"], "name": node["name"], "summary": node["summary"] or "",
                          "kind": _ext_kind(node) or (node["display_kind"] or "external").lower()})
    return {"workspace": ws["name"] if ws else "", "summary": (ws["summary"] if ws else "") or "",
            "concepts": concepts, "externals": externals,
            "relationships": _fallback_relationships(edges, boxes, known), "screens": []}


# --- comparison -----------------------------------------------------------------

_SOURCE_KINDS = {"function", "method"}


def compare_payload(head_conn, base_conn, changes, head_root=None, base_root=None, base_label="", head_label=""):
    """What data/diff.js carries for comparison mode.

    The change list is `cbi diff`'s object. removed is the base concepts,
    relationships and externals the head map does not have, so the viewer can
    draw what went away. sources is the base and head text of each changed
    function or method. provisional is head concept ids flagged provisional
    (the assignment itself belongs to the review command).
    """
    head_view = concept_view(head_conn, head_root)
    base_view = concept_view(base_conn, base_root)
    head_ids = _concept_ids(head_view)
    removed_ids = _concept_ids(base_view) - head_ids
    removed_rels = _removed_relationships(base_view, changes, removed_ids)
    return {
        "base": base_label,
        "head": head_label,
        "changes": changes,
        "removed": {
            "concepts": _removed_concepts(base_view, removed_ids),
            "relationships": removed_rels,
            "externals": _removed_externals(base_view, head_view, removed_rels),
        },
        "screens": _changed_screens(base_view, head_view, changes),
        "sources": _changed_sources(base_conn, head_conn, changes, base_root, head_root),
        "provisional": _provisional(head_conn),
    }


def _concept_ids(payload):
    found = set()

    def walk(nodes):
        for node in nodes or []:
            found.add(node["id"])
            walk(node.get("children"))

    walk(payload.get("concepts"))
    return found


def _removed_concepts(payload, removed_ids):
    """Graft roots: a removed concept, or a removed subtree, with parent set to the concept that still exists."""
    roots = []

    def prune(node):
        kids = [kept for child in node.get("children") or [] if (kept := prune(child))]
        if node["id"] not in removed_ids and not kids:
            return None
        out = {key: value for key, value in node.items() if key != "children"}
        if kids:
            out["children"] = kids
        return out

    def lift(nodes, parent_id):
        for node in nodes or []:
            if node["id"] in removed_ids:
                kept = prune(node)
                if kept:
                    kept["parent"] = parent_id
                    roots.append(kept)
            else:
                lift(node.get("children"), node["id"])

    lift(payload.get("concepts"), None)
    return roots


def _rel_key(rel):
    return (rel.get("from"), rel.get("to"), rel.get("label") or "")


def _change_keys(changes, kinds):
    keys = set()
    for group in changes.get("groups") or []:
        for change in group["changes"]:
            if change["kind"] not in kinds:
                continue
            record = change.get("before") or change.get("after")
            if isinstance(record, dict) and record.get("from"):
                keys.add(_rel_key(record))
    return keys


def _removed_relationships(base_view, changes, removed_ids):
    gone = _change_keys(changes, {"relationship-removed", "integration-removed"})
    found = []
    for rel in base_view.get("relationships") or []:
        if _rel_key(rel) in gone or rel.get("from") in removed_ids or rel.get("to") in removed_ids:
            found.append(rel)
    return found


def _removed_externals(base_view, head_view, relationships):
    head_ext = {ext["id"] for ext in head_view.get("externals") or []}
    head_ids = _concept_ids(head_view)
    needed = set()
    for rel in relationships:
        for end in (rel.get("from"), rel.get("to")):
            if end and end not in head_ext and end not in head_ids:
                needed.add(end)
    return [ext for ext in base_view.get("externals") or [] if ext["id"] in needed]


def _region_ids(region, found):
    if not isinstance(region, dict):
        return
    if region.get("component"):
        found.add(region["component"])
    for kid in region.get("children") or []:
        _region_ids(kid, found)


def _changed_components(changes):
    found = set()
    for group in changes.get("groups") or []:
        for change in group["changes"]:
            if change["kind"] in ("symbol-added", "symbol-removed", "symbol-changed", "symbol-moved"):
                for ref in change.get("code") or []:
                    if ref.get("display_kind") == "component":
                        found.add(ref["id"])
            elif change["kind"] in ("render-added", "render-removed"):
                record = change.get("after") or change.get("before")
                if isinstance(record, dict) and record.get("from"):
                    found.add(record["from"])
    return found


def _changed_screens(base_view, head_view, changes):
    """Base screens that match a head screen and contain a changed component."""
    components = _changed_components(changes)
    if not components:
        return []
    head_keys = set()
    for screen in head_view.get("screens") or []:
        head_keys.add(screen["id"])
        head_keys.add("name:" + (screen.get("name") or ""))
    found = []
    for screen in base_view.get("screens") or []:
        if screen["id"] not in head_keys and "name:" + (screen.get("name") or "") not in head_keys:
            continue
        ids = set()
        _region_ids(screen.get("root"), ids)
        if ids & components:
            found.append(screen)
    return found


def _provisional(conn):
    found = []
    for nid, attrs in conn.execute("SELECT id, attrs FROM nodes WHERE kind = 'concept' ORDER BY id"):
        if _obj(attrs).get("provisional") is True:
            found.append(nid)
    return found


def _spans(conn):
    return {
        row[0]: row[1:]
        for row in conn.execute(
            "SELECT id, path, start_line, end_line, display_kind FROM nodes WHERE kind = 'symbol'"
        )
    }


def _slice(root, path, start, end):
    if root is None or not path or not start or not end:
        return ""
    try:
        text = (root / path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return "\n".join(text.splitlines()[start - 1:end])


def _changed_sources(base_conn, head_conn, changes, base_root, head_root):
    """Base and head source of each changed function or method, keyed by its symbol id."""
    base_span, head_span = _spans(base_conn), _spans(head_conn)
    sources = {}
    for group in changes.get("groups") or []:
        for change in group["changes"]:
            if change["kind"] != "symbol-changed" or not change.get("code"):
                continue
            ref = change["code"][0]
            if ref.get("display_kind") not in _SOURCE_KINDS:
                continue
            nid = ref["id"]
            if nid in sources:
                continue
            left, right = base_span.get(nid), head_span.get(nid)
            if not left or not right or left[3] not in _SOURCE_KINDS:
                continue
            sources[nid] = {
                "base": _slice(base_root, left[0], left[1], left[2]),
                "head": _slice(head_root, right[0], right[1], right[2]),
            }
    return sources

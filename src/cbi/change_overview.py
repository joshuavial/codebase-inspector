"""Shared change overview projection and compact renderers.

The structural diff remains the source of truth.  This module turns that list
and the two model snapshots into the ranked hierarchy used by CLI, review and
viewer payloads.
"""

import json
import re
import subprocess
from collections import Counter, defaultdict


STRUCTURE_KINDS = {
    "concept-added", "concept-removed", "concept-split", "concept-merged",
    "file-moved-concept",
}
RELATIONSHIP_KINDS = {
    "relationship-added", "relationship-removed", "relationship-volume",
}
INTEGRATION_ATTENTION = {"integration-added", "integration-changed"}
SYMBOL_KINDS = {"symbol-added", "symbol-removed", "symbol-moved", "symbol-changed"}


def git_line_stats(root, base, head):
    """Return exact numstat and changed line numbers without touching the tree."""
    command = ["git", "-c", "core.quotePath=false", "diff", "--no-ext-diff", "-M"]
    raw = subprocess.run(
        [*command, "--numstat", "-z", base, head, "--"], cwd=root, check=True,
        capture_output=True,
    ).stdout
    parts = raw.split(b"\0")
    stats = {}
    index = 0
    while index < len(parts) and parts[index]:
        record = parts[index].decode("utf-8", "replace")
        index += 1
        fields = record.split("\t")
        if len(fields) != 3:
            continue
        added, deleted, path = fields
        old_path = new_path = path
        if not path:
            if index + 1 >= len(parts):
                break
            old_path = parts[index].decode("utf-8", "replace")
            new_path = parts[index + 1].decode("utf-8", "replace")
            index += 2
        binary = added == "-" or deleted == "-"
        row = {
            "old_path": old_path, "path": new_path,
            "additions": 0 if binary else int(added),
            "deletions": 0 if binary else int(deleted),
            "binary": binary, "added_lines": [], "deleted_lines": [],
        }
        stats[new_path or old_path] = row

    patch = subprocess.run(
        [*command, "--no-color", "--unified=0", "--no-prefix", base, head, "--"],
        cwd=root, check=True, capture_output=True, text=True, errors="replace",
    ).stdout
    current = None
    old_line = new_line = 0
    for line in patch.splitlines():
        if line.startswith("--- "):
            old_path = line[4:].split("\t", 1)[0]
            if old_path == "/dev/null":
                old_path = ""
            current = next((r for r in stats.values() if r["old_path"] == old_path), None)
        elif line.startswith("+++ "):
            new_path = line[4:].split("\t", 1)[0]
            if new_path == "/dev/null":
                new_path = ""
            current = stats.get(new_path) or current
        elif line.startswith("@@"):
            match = re.search(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
            if match:
                old_line, new_line = map(int, match.groups())
        elif current is not None and line.startswith("+"):
            current["added_lines"].append(new_line)
            new_line += 1
        elif current is not None and line.startswith("-"):
            current["deleted_lines"].append(old_line)
            old_line += 1
        elif current is not None and line.startswith(" "):
            old_line += 1
            new_line += 1
    return stats


def build(ctx, grouped, line_stats=None):
    line_stats = dict(line_stats or {})
    # Also key each row by its old path, so a base-side lookup finds a renamed or deleted file.
    for row in list(line_stats.values()):
        line_stats.setdefault(row["old_path"], row)
    changes = _unique(grouped)
    untested_ids = {c["after"]["id"] for c in changes if c["kind"] == "untested"}
    index = _EdgeIndex(ctx)
    base_files = {nid: n for nid, n in ctx.base.nodes.items() if n["kind"] in ("file", "doc")}
    head_files = {ctx.canon.get(nid, nid): n for nid, n in ctx.head.nodes.items() if n["kind"] in ("file", "doc")}
    base_files = {ctx.canon.get(nid, nid): n for nid, n in base_files.items()}
    file_ids = set(base_files) | set(head_files)
    files = []
    for fid in sorted(file_ids):
        left, right = base_files.get(fid), head_files.get(fid)
        stat = _stat_for(line_stats, left, right)
        moved = bool(left and right and left.get("path") != right.get("path"))
        changed = not left or not right or moved or left.get("content_hash") != right.get("content_hash") or bool(stat)
        if not changed:
            continue
        state = "added" if not left else "removed" if not right else "moved" if moved and left.get("content_hash") == right.get("content_hash") else "changed"
        node = right or left
        measures = _measure(additions=(stat or {}).get("additions", 0), deletions=(stat or {}).get("deletions", 0),
                            binary=1 if (stat or {}).get("binary") else 0)
        measures["files"].update({state: 1, "total": 1})
        files.append({
            "id": node["id"], "canonical_id": fid, "name": node["name"], "path": node.get("path") or "",
            "old_path": (left or {}).get("path") or "", "state": state, "measures": measures,
            "symbols": [], "relationships": [],
        })
    by_file = {row["canonical_id"]: row for row in files}
    for change in changes:
        if change["kind"] not in SYMBOL_KINDS:
            continue
        ref = _symbol_ref(change)
        if not ref:
            continue
        node = ctx.head.nodes.get(ref["id"]) or ctx.base.nodes.get(ref["id"])
        fid = ctx.canon.get(_file_id(node), _file_id(node))
        if fid not in by_file:
            continue
        sm = _symbol_measure(ctx, change, node, line_stats)
        untested = ref["id"] in untested_ids
        by_file[fid]["symbols"].append({
            "id": ref["id"], "name": ref["name"], "display_kind": ref.get("display_kind") or "symbol",
            "state": change["kind"].removeprefix("symbol-"), "measures": sm,
            "untested": untested,
            "relationships": index.context({ref["id"]}),
        })
    for row in files:
        ids = {row["id"], row["canonical_id"]}
        ids.update(s["id"] for s in row["symbols"])
        row["relationships"] = _crossing([row], index.context(ids))
        _add_symbol_counts(row["measures"], row["symbols"])

    items = _items(ctx, grouped, changes, files, index)
    total = _measure()
    for row in files:
        _roll(total, row["measures"])
    total["concepts"] = sum(1 for item in items if item["kind"] == "concept")
    total["integrations"] = sum(item["measures"]["integrations"] for item in items)
    total["env_vars"] = sum(1 for c in changes if c["kind"] in ("env-read", "env-unread"))
    total["tests"]["added"] = sum(1 for c in changes if c["kind"] == "test-added")
    total["tests"]["removed"] = sum(1 for c in changes if c["kind"] == "test-removed")
    return {"grouping": grouped["grouping"], "totals": total, "items": items}


def _items(ctx, grouped, changes, files, index):
    rel_states = _relationship_states(changes)
    records = {}
    for group in grouped["groups"]:
        gid = _top_concept(ctx, group["id"]) if grouped["grouping"] == "concept" else group["id"]
        if gid not in records:
            records[gid] = _record(ctx, gid, group["name"], group["kind"])
        records[gid]["_changes"].extend(group["changes"])
    for row in grouped.get("provisional") or []:
        gid = _top_concept(ctx, row.get("concept_id")) if row.get("concept_id") else None
        if gid in records:
            records[gid]["attention"]["provisional"] = True
    for file in files:
        gid = _file_group(ctx, file["canonical_id"])
        if gid not in records:
            records[gid] = _record(ctx, gid, gid, "folder")
        module = _module(ctx, file, index)
        target = next((m for m in records[gid]["modules"] if m["id"] == module["id"]), None)
        if target is None:
            target = {**module, "state": "changed", "measures": _measure(), "relationships": [], "files": []}
            records[gid]["modules"].append(target)
        target["files"].append(file)
    for item in records.values():
        own_changes = _dedupe(item.pop("_changes"))
        for module in item["modules"]:
            for file in module["files"]:
                _roll(module["measures"], file["measures"])
            module["relationships"] = _module_context(module)
            states = {f["state"] for f in module["files"]}
            if states in ({"added"}, {"removed"}):
                module["state"] = states.pop()
            _roll(item["measures"], module["measures"])
        item["relationships"] = _concept_context(ctx, item["id"], rel_states)
        changed = {f["path"]: {sym["name"] for sym in f["symbols"]} for m in item["modules"] for f in m["files"]}
        _attention(item, own_changes, changed)
        state_kind = next((c["kind"] for c in own_changes if c["kind"] in {"concept-added", "concept-removed"}), None)
        file_states = {f["state"] for m in item["modules"] for f in m["files"]}
        if state_kind:
            item["state"] = state_kind.removeprefix("concept-")
        elif item["kind"] == "concept" and file_states in ({"added"}, {"removed"}):
            # Current concepts on both sides: a concept that owned no files on one side was added or removed.
            item["state"] = file_states.pop()
        item["modules"].sort(key=lambda m: (m["name"].lower(), m["id"]))
        for module in item["modules"]:
            module["files"].sort(key=lambda f: f["path"])
            for file in module["files"]:
                file["symbols"].sort(key=lambda s: (s["name"].lower(), s["id"]))
    return sorted(records.values(), key=_attention_key)


def _record(ctx, gid, name, kind):
    node = ctx.head.nodes.get(gid) or ctx.base.nodes.get(gid)
    return {
        "id": gid, "name": node["name"] if node else name,
        "kind": "concept" if node and node["kind"] == "concept" else kind,
        "summary": (node or {}).get("summary") or "", "state": "changed", "measures": _measure(),
        "attention": {"integrations": [], "untested": 0, "structure": [], "relationships": [],
                      "env_vars": [], "removed_tests": 0, "provisional": False},
        "reasons": [], "relationships": [], "modules": [], "_changes": [],
    }


def _measure(additions=0, deletions=0, binary=0):
    return {
        "additions": additions, "deletions": deletions, "churn": additions + deletions + binary,
        "binary": binary, "files": Counter(), "symbols": Counter(), "tests": Counter(),
        "integrations": 0, "env_vars": 0, "untested": 0, "relationships": 0,
    }


def _roll(dst, src):
    for key in ("additions", "deletions", "churn", "binary", "integrations", "env_vars", "untested", "relationships"):
        dst[key] += src.get(key, 0)
    for key in ("files", "symbols", "tests"):
        dst[key].update(src.get(key) or {})


def _add_symbol_counts(measure, symbols):
    for symbol in symbols:
        measure["symbols"][symbol["state"]] += 1
        if symbol["untested"]:
            measure["untested"] += 1


def _attention(item, changes, changed):
    attention = item["attention"]
    attention["integrations"] = [c["summary"] for c in changes if c["kind"] in INTEGRATION_ATTENTION]
    # An unchanged integration whose evidence (`at` path, and symbol when named) changed.
    attention["integrations"] += [
        f"{r['from_name']} -> {r['to_name']}  {r['label']}  via {r['mechanism'] or '?'}  at {r['at']} (changed)"
        for r in item["relationships"]
        if r["integration"] and r["state"] == "unchanged" and _touched(r["at"], changed)
    ]
    attention["untested"] = item["measures"]["untested"]
    attention["structure"] = [c["summary"] for c in changes if c["kind"] in STRUCTURE_KINDS]
    attention["relationships"] = [c["summary"] for c in changes if c["kind"] in RELATIONSHIP_KINDS]
    attention["env_vars"] = [c["summary"] for c in changes if c["kind"] in ("env-read", "env-unread")]
    attention["removed_tests"] = sum(1 for c in changes if c["kind"] == "test-removed")
    item["measures"]["tests"].update({
        "added": sum(1 for c in changes if c["kind"] == "test-added"),
        "removed": attention["removed_tests"],
    })
    removed = sum(1 for c in changes if c["kind"] == "integration-removed")
    item["measures"]["integrations"] = len(attention["integrations"]) + removed
    item["measures"]["env_vars"] = sum(1 for c in changes if c["kind"] in ("env-read", "env-unread"))
    item["measures"]["relationships"] = len(attention["relationships"])
    reasons = []
    if attention["integrations"]:
        n = len(attention["integrations"])
        reasons.append(f"{n} integration point{'s' if n != 1 else ''} added, changed or touched")
    if attention["untested"]:
        reasons.append(f"{attention['untested']} changed production function" + ("s" if attention["untested"] != 1 else "") + " without a linked test")
    if attention["structure"]:
        reasons.append(f"{len(attention['structure'])} structural change" + ("s" if len(attention["structure"]) != 1 else ""))
    if attention["relationships"]:
        reasons.append(f"{len(attention['relationships'])} changed relationship" + ("s" if len(attention["relationships"]) != 1 else ""))
    if attention["removed_tests"]:
        reasons.append(f"{attention['removed_tests']} removed test" + ("s" if attention["removed_tests"] != 1 else ""))
    if attention["provisional"]:
        reasons.append("provisional ownership")
    item["reasons"] = reasons or [f"{item['measures']['churn']} changed lines"]


def _touched(at, changed):
    path, _, symbol = at.partition(":")
    if path not in changed:
        return False
    return not symbol or any(name == symbol or name.endswith("." + symbol) for name in changed[path])


def _attention_key(item):
    a = item["attention"]
    return (not bool(a["integrations"]), not bool(a["untested"]), not bool(a["structure"]),
            not bool(a["relationships"]), -item["measures"]["churn"], item["name"].lower(), item["id"])


def _stat_for(stats, left, right):
    for path in ((right or {}).get("path"), (left or {}).get("path")):
        if path and path in stats:
            return stats[path]
    return None


def _symbol_measure(ctx, change, node, stats):
    left = ctx.base.nodes.get(node["id"])
    right = ctx.head.nodes.get(node["id"])
    if change["kind"] == "symbol-moved":
        left = ctx.base.nodes.get(change["before"]["id"])
        right = ctx.head.nodes.get(change["after"]["id"])
    stat = _stat_for(stats, left, right) or {}
    added = sum(1 for n in stat.get("added_lines", []) if right and right.get("start_line", 0) <= n <= right.get("end_line", 0))
    deleted = sum(1 for n in stat.get("deleted_lines", []) if left and left.get("start_line", 0) <= n <= left.get("end_line", 0))
    return _measure(added, deleted)


def _module(ctx, file, index):
    candidates = []
    for side, packages in ((ctx.head, index.head_packages), (ctx.base, index.base_packages)):
        for fid in {file["id"], file["canonical_id"]}:
            for pid in packages.get(fid, ()):
                node = side.nodes[pid]
                directory = node.get("path") or node.get("attrs", {}).get("directory") or ""
                candidates.append((directory.count("/"), node))
    if candidates:
        node = max(candidates, key=lambda pair: (pair[0], pair[1]["id"]))[1]
        return {"id": node["id"], "name": node["name"], "kind": "package"}
    directory = file["path"].rsplit("/", 1)[0] if "/" in file["path"] else "."
    gid = _file_group(ctx, file["canonical_id"])
    return {"id": f"module:{gid}:{directory}", "name": directory, "kind": "module"}


def _file_group(ctx, fid):
    owner = ctx.head_owner.get(fid) or ctx.base_owner.get(fid)
    if ctx.concept_mode and owner:
        return _top_concept(ctx, ctx.rename.get(owner, owner))
    head_id = next((dst for src, dst in ctx.file_moves.items() if src == fid), fid)
    from cbi.diff import _container
    return _container(ctx.head, head_id) if head_id in ctx.head.nodes else _container(ctx.base, fid)


def _top_concept(ctx, cid):
    if not cid:
        return cid
    side = ctx.head if cid in ctx.head.nodes else ctx.base
    current = cid
    while True:
        parent = side.nodes.get(current, {}).get("parent_id")
        if not parent or side.nodes.get(parent, {}).get("kind") != "concept":
            return current
        current = parent


def _concept_context(ctx, focus, rel_states):
    descendants = {nid for side in (ctx.base, ctx.head) for nid, node in side.nodes.items()
                   if node["kind"] == "concept" and _is_under(side, nid, focus)}
    rows = _edge_context(ctx, descendants, {"relates"})
    for row in rows:
        # Concept edges come from concepts.json; the diff also sees call and import volume behind them.
        row["state"] = rel_states.get((row["from"], row["to"], row["label"]), row["state"])
    return rows


def _relationship_states(changes):
    states = {}
    for change in changes:
        kind = change["kind"]
        if kind not in RELATIONSHIP_KINDS and not kind.startswith("integration-"):
            continue
        rel = change["after"] or change["before"]
        state = "added" if kind.endswith("-added") else "removed" if kind.endswith("-removed") else "changed"
        states[(rel["from"], rel["to"], rel["label"])] = state
    return states


def _module_context(module):
    return _crossing(module["files"], [rel for f in module["files"] for rel in f["relationships"]])


def _crossing(files, rows):
    """Rows with one end outside these files; a symbol is inside its file."""
    inside = {f["id"] for f in files} | {f["canonical_id"] for f in files}
    within = lambda nid: nid in inside or nid.split("#", 1)[0] in inside
    return _dedupe([rel for rel in rows if not (within(rel["from"]) and within(rel["to"]))])


class _EdgeIndex:
    """Code edges and package membership keyed by node, built once per compare."""

    KINDS = {"imports", "calls", "tests", "reads_env"}

    def __init__(self, ctx):
        self.ctx = ctx
        translate = lambda nid: ctx.symbol_moves.get(nid, ctx.file_moves.get(nid, ctx.rename.get(nid, nid)))
        self.base = _keyed_by_node(ctx.base, self.KINDS, translate)
        self.head = _keyed_by_node(ctx.head, self.KINDS, lambda nid: nid)
        self.base_packages = _packages(ctx.base)
        self.head_packages = _packages(ctx.head)

    def context(self, focus):
        base = {k: e for nid in focus for k, e in self.base.get(nid, {}).items()}
        head = {k: e for nid in focus for k, e in self.head.get(nid, {}).items()}
        return _context_rows(self.ctx, base, head)


def _keyed_by_node(side, kinds, translate):
    out = defaultdict(dict)
    for edge in side.edges:
        if edge["kind"] not in kinds:
            continue
        src, dst = translate(edge["src"]), translate(edge["dst"])
        key = (src, dst, edge["kind"], edge["attrs"].get("label") or edge["kind"])
        out[src][key] = edge
        out[dst][key] = edge
    return out


def _packages(side):
    out = defaultdict(list)
    for edge in side.by_kind["part_of"]:
        if side.nodes.get(edge["dst"], {}).get("kind") == "package":
            out[edge["src"]].append(edge["dst"])
    return out


def _edge_context(ctx, focus, kinds):
    translate = lambda nid: ctx.symbol_moves.get(nid, ctx.file_moves.get(nid, ctx.rename.get(nid, nid)))
    base = {k: e for nid, rows in _keyed_by_node(ctx.base, kinds, translate).items() if nid in focus for k, e in rows.items()}
    head = {k: e for nid, rows in _keyed_by_node(ctx.head, kinds, lambda nid: nid).items() if nid in focus for k, e in rows.items()}
    return _context_rows(ctx, base, head)


def _context_rows(ctx, base, head):
    rows = []
    for key in sorted(set(base) | set(head)):
        left, right = base.get(key), head.get(key)
        state = "added" if not left else "removed" if not right else "changed" if (left["weight"], left["attrs"]) != (right["weight"], right["attrs"]) else "unchanged"
        src, dst, kind, label = key
        attrs = (right or left)["attrs"]
        rows.append({"from": src, "from_name": _node_name(ctx, src), "to": dst, "to_name": _node_name(ctx, dst),
                     "kind": kind, "label": label, "state": state,
                     "mechanism": attrs.get("via") or attrs.get("mechanism") or "", "at": attrs.get("at") or "",
                     "integration": bool(attrs.get("integration")) or "external" in (
                         _node_kind(ctx, src), _node_kind(ctx, dst))})
    return rows


def _is_under(side, nid, focus):
    seen = set()
    while nid and nid not in seen:
        if nid == focus:
            return True
        seen.add(nid)
        nid = side.nodes.get(nid, {}).get("parent_id")
    return False


def _node_kind(ctx, nid):
    return (ctx.head.nodes.get(nid) or ctx.base.nodes.get(nid) or {}).get("kind")


def _node_name(ctx, nid):
    return (ctx.head.nodes.get(nid) or ctx.base.nodes.get(nid) or {}).get("name", nid)


def _symbol_ref(change):
    refs = change.get("code") or []
    if not refs:
        return None
    if change["kind"] == "symbol-moved" and len(refs) > 1:
        return refs[-1]
    return refs[0]


def _file_id(node):
    if not node:
        return None
    if node["kind"] in ("file", "doc"):
        return node["id"]
    if node.get("workspace_id") and node.get("path"):
        return f"{node['workspace_id']}:{node['path']}"
    return node["id"].split("#", 1)[0]


def _unique(result):
    return _dedupe([change for group in result.get("groups") or [] for change in group["changes"]])


def _dedupe(rows):
    out, seen = [], set()
    for row in rows:
        key = json.dumps(row, sort_keys=True, default=list)
        if key not in seen:
            seen.add(key)
            out.append(row)
    return out


def select(result, concept=None, module=None, file=None, symbol=None):
    """Return the selected overview record and its level."""
    overview = result.get("overview") or {"totals": _measure(), "items": []}
    if not any((concept, module, file, symbol)):
        return "overview", overview
    for item in overview["items"]:
        if concept and item["id"] == concept:
            return "concept", item
        for mod in item["modules"]:
            if module and mod["id"] == module:
                return "module", mod
            for row in mod["files"]:
                if file and file in (row["id"], row["path"]):
                    return "file", row
                for sym in row["symbols"]:
                    if symbol and symbol in (sym["id"], sym["name"]):
                        return "symbol", sym
    return None, None


DRILL = {"overview": "--concept", "concept": "--module", "module": "--file", "file": "--symbol"}


def render(result, markdown=False, concept=None, module=None, file=None, symbol=None):
    """The ranked overview, or one drill level when an id is passed."""
    level, selected = select(result, concept, module, file, symbol)
    if selected is None:
        wanted = concept or module or file or symbol
        return f"no changed item matches {wanted}\n"
    head = "# " if markdown else ""
    sub = "## " if markdown else ""
    if level == "overview":
        if not selected["items"]:
            return "# Change overview\n\nNo architectural changes.\n" if markdown else "no architectural changes\n"
        lines = [f"{head}Change overview", ""]
        if selected.get("base") or selected.get("head"):
            lines += [f"{selected.get('base', '')[:12]} -> {selected.get('head', '')[:12]}", ""]
        totals = selected["totals"]
        concepts = sum(1 for item in selected["items"] if item["kind"] == "concept")
        groups = [(concepts, "concept"), (len(selected["items"]) - concepts, "other group" if concepts else "group")]
        lines.append(_measure_line(totals) + "".join(f"  {n} {w}{'s' if n != 1 else ''}" for n, w in groups if n))
        for number, item in enumerate(selected["items"], 1):
            lines += ["", f"{sub}{number}. {item['name']} `{item['id']}`  {item['state']}"]
            body = [_measure_line(item["measures"]), *_why(item)]
            if markdown:
                for line in body:
                    lines += [line] if line.startswith("- ") else ["", line]
            else:
                lines += [f"   {line}" for line in body]
        lines += ["", f"Drill down with {DRILL[level]} ID, or --detail for every structural change."]
        return "\n".join(lines) + "\n"
    name = selected["path"] if level == "file" else selected.get("name") or selected["id"]
    lines = [f"{head}{level.title()}: {name} `{selected['id']}`  {selected.get('state', '')}".rstrip(), "",
             _measure_line(selected["measures"])]
    if level == "concept":
        lines += _why(selected)
    relationships = selected.get("relationships") or []
    if relationships:
        lines += ["", f"{sub}Context"]
        # Test edges collapse to one line in text; json keeps every row.
        tests = sorted({r["from_name"] for r in relationships if r["kind"] == "tests"})
        lines += [f"- {r['from_name']} -> {r['to_name']}  {r['label']}"
                  + (f" via {r['mechanism']}" if r["mechanism"] else "") + f"  {r['state']}"
                  for r in relationships if r["kind"] != "tests"]
        if tests:
            lines.append(f"- tested by {len(tests)}: " + ", ".join(tests[:3]) + (", ..." if len(tests) > 3 else ""))
    children = selected.get("modules") or selected.get("files") or selected.get("symbols") or []
    if children:
        lines += ["", f"{sub}Changed items"]
        for child in children:
            label = child.get("path") or child.get("name")
            flag = "  untested" if child.get("untested") else ""
            lines.append(f"- {label} `{child['id']}`  {child['state']}  {_measure_line(child['measures'])}{flag}")
        if level in DRILL:
            lines += ["", f"Drill down with {DRILL[level]} ID."]
    return "\n".join(lines) + "\n"


def _why(item):
    """Responsibility, then the attention facts behind the item's rank."""
    out = []
    summary = item.get("summary", "").strip()
    if summary:
        out.append(re.split(r"(?<=[.!?])\s", summary, maxsplit=1)[0])
    out.append("Why: " + "; ".join(item["reasons"]))
    a = item["attention"]
    for fact in [*a["integrations"], *a["structure"], *a["relationships"], *a["env_vars"]][:5]:
        out.append(f"- {fact}")
    return out


def _measure_line(m):
    files = m.get("files") or {}
    total = files.get("total", 0)
    bits = [f"{total} {'file' if total == 1 else 'files'}"] if total else []
    bits.append(f"+{m.get('additions', 0)} -{m.get('deletions', 0)}")
    if m.get("binary"):
        bits.append(f"{m['binary']} binary")
    symbols = m.get("symbols") or {}
    counts = ", ".join(f"{symbols[k]} {k}" for k in ("added", "changed", "removed", "moved") if symbols.get(k))
    if counts:
        bits.append(f"symbols {counts}")
    tests = m.get("tests") or {}
    if tests.get("added") or tests.get("removed"):
        bits.append(f"tests +{tests.get('added', 0)} -{tests.get('removed', 0)}")
    for key, word in (("untested", "untested"), ("integrations", "integrations"), ("env_vars", "env vars")):
        if m.get(key):
            bits.append(f"{m[key]} {word}")
    return "  ".join(bits)

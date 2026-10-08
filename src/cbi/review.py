"""Write a review of two versions: review.md, a Mermaid diagram, and the judgement tasks.

`cbi review` resolves a pull request, a branch, a commit or a base..head range to
two commits, scans those refs (or reuses the stored models) and writes
`.cbi/reviews/<base>..<head>/review.md`. Nothing here checks out a branch or
writes a ref, a stash or a working tree. `--post` is the only path that talks
to GitHub, and it edits the inspector's earlier comment instead of adding one.
"""

import hashlib
import json
import re
import subprocess
from collections import defaultdict
from pathlib import Path
from urllib.parse import quote

from cbi import concepts, diff, files, render, store, tasks

HELP = """\
Write a review of the architectural changes in a pull request, branch or commit.

The target is a pull request number, a branch, a commit, or base..head.
A pull request is resolved with
`gh pr view <n> --json baseRefName,headRefOid,baseRefOid,number,url`
(read-only). A branch or commit is compared with --base, or with the
merge-base against main (then master) when --base is omitted. --base
overrides the pull request's base. Both commits are mapped with
`cbi scan --ref` into the model directory (.cbi/, or --out). A stored
model is reused. The working tree, the refs and the stash are not changed.

The review folder is .cbi/reviews/<base sha>..<head sha>/, or --out-dir.
review.md starts with the cbi://open link for that comparison, then the
summary counts, a Mermaid flowchart LR of the changed concepts and their
direct neighbours, the per-concept details, untested changes and changed
integration points. Concepts that are neither changed nor a direct
neighbour are named in text, not drawn. With no concepts, the diagram
uses deployables, packages and folders. Added, removed and changed nodes
use classDef. New relationships are solid arrows. Removed ones are dotted
and labelled as removed. An integration point is labelled with its via.
An injection call counts as a production call in those totals. A call
from or to a test file does not.

New head files that no concept owns are given a provisional owner (see
`cbi diff --help`) and a define-concepts task opens on the head model for
those files only. summarise-change takes the change list and returns a
short narrative, cached by the two commit ids. The narrative is included
when an agent has submitted it, and is never required.

--post publishes review.md with `gh pr comment`. A later run finds that
comment by the hidden marker <!-- cbi-review --> and edits it with
`gh api`. Without --post nothing is posted. before.png, after.png,
before.svg and after.svg are written in the review folder. Without
system Chrome or Chromium they are skipped and the Images section says
so. Attach the files to the pull request comment by hand. GitHub
renders the Mermaid diagram without them.

Exit codes: 0 the review was written (and posted, when --post was given),
1 the ref is unknown, gh failed, the directory is not a git repo, or it
is not initialised, 2 the arguments are incomplete (for example --post
without a pull request number)."""

MARKER = "<!-- cbi-review -->"
CLASS_DEFS = (
    "classDef added fill:#d8f3dc,stroke:#1b7f3a",
    "classDef removed fill:#fde2e1,stroke:#b42318",
    "classDef changed fill:#fff3c4,stroke:#b54708",
)
_STATUS_ORDER = {"added": 0, "removed": 1, "changed": 2, "neighbour": 3}
_ADDED = ("concept-added", "deployable-added", "package-added")
_REMOVED = ("concept-removed", "deployable-removed", "package-removed")
# (?: consumes one colon, so four colons here match Mermaid's three.
_NODE_LINE = re.compile(
    r'^([A-Za-z_][A-Za-z0-9_]*)\["([^"\n\[\]]*)"\](?::::(added|removed|changed))?$'
)
_EDGE_LINE = re.compile(
    r'^([A-Za-z_][A-Za-z0-9_]*) (-.->|-->)\|"([^"\n|]+)"\| ([A-Za-z_][A-Za-z0-9_]*)$'
)
_RESERVED = {"end", "graph", "subgraph", "flowchart", "classdef"}


class ReviewError(Exception):
    def __init__(self, message, code=1):
        super().__init__(message)
        self.code = code


def review(root, target, base=None, model=None, out_dir=None, post=False):
    """Resolve, scan, write review.md and maybe post it. Returns a short report."""
    root = Path(root)
    model = Path(model) if model else root / ".cbi"
    if not (model / "ignore").exists():
        raise ReviewError(f"{model} is not initialised. Run `cbi init` first.", code=1)
    spec = resolve_target(root, target, base)
    base_sha = files.resolve_commit(root, spec["base"])
    head_sha = files.resolve_commit(root, spec["head"])
    from cbi.cli import scan_ref
    scan_ref(root, model, base_sha)
    scan_ref(root, model, head_sha)
    base_conn = diff.open_model(model / "refs" / base_sha)
    head_conn = diff.open_model(model / "refs" / head_sha)
    try:
        result = diff.compare(base_conn, head_conn)
        diagram = build_diagram(result, base_conn, head_conn)
        mermaid = render_mermaid(diagram)
        if not valid_mermaid(mermaid):
            raise ReviewError("the review diagram is not valid Mermaid")
        repo_name = _top_name(head_conn)
    finally:
        base_conn.close()
        head_conn.close()
    narrative, change_task, define_task = _open_tasks(model / "refs" / head_sha / "model.db", base_sha, head_sha, result)
    folder = Path(out_dir) if out_dir else model / "reviews" / f"{base_sha}..{head_sha}"
    folder.mkdir(parents=True, exist_ok=True)
    images = _capture_images(model, base_sha, head_sha, result, folder)
    text = render_review(
        root, base_sha, head_sha, spec, result, diagram, mermaid, narrative, change_task, define_task, images,
        repo_name=repo_name,
    )
    path = folder / "review.md"
    path.write_text(text)
    if post:
        if not spec.get("pr"):
            raise ReviewError(f"wrote {path}\n--post needs a pull request number", code=2)
        action = post_comment(root, spec["pr"], path)
    else:
        action = None
    lines = [str(path)]
    if change_task:
        lines.append(f"summarise-change {change_task['id']} {change_task['state']}")
    if define_task:
        lines.append(f"define-concepts {define_task['id']} {define_task['files']} files")
    if images.get("skipped"):
        lines.append(images["skipped"])
    elif images.get("failed"):
        lines.append(images["failed"])
    else:
        lines.append("images: before.png, before.svg, after.png, after.svg")
    if action:
        lines.append(f"posted: {action}")
    return "\n".join(lines)


def _capture_images(model, base_sha, head_sha, result, folder):
    """before/after PNG and SVG in the review folder, or a skip or failure note."""
    try:
        return render.render_images(
            {"base": model / "refs" / base_sha, "head": model / "refs" / head_sha},
            result,
            folder,
        )
    except render.RenderError as err:
        return {"failed": str(err)}


def resolve_target(root, target, base):
    """A dict with base and head refs, plus pr and url when the target is a pull request."""
    target = (target or "").strip()
    if not target:
        raise ReviewError("pass a pull request number, a branch, a commit, or base..head", code=2)
    if re.fullmatch(r"\d+", target):
        pr = _gh_json(root, ["pr", "view", target, "--json", "baseRefName,headRefOid,baseRefOid,number,url"])
        for key in ("headRefOid", "baseRefOid", "number", "url"):
            if key not in pr:
                raise ReviewError(f"gh pr view did not return {key}")
        return {"base": base or pr["baseRefOid"], "head": pr["headRefOid"], "pr": pr["number"],
                "url": pr["url"], "base_name": pr.get("baseRefName")}
    if ".." in target:
        if base:
            raise ReviewError("pass a range or --base, not both", code=2)
        left, right = target.split("..", 1)
        if not left or not right:
            raise ReviewError("a range needs both ends, like base..head", code=2)
        return {"base": left, "head": right}
    head_sha = files.resolve_commit(root, target)
    if base:
        return {"base": base, "head": target}
    return {"base": _default_base(root, head_sha), "head": target}


def _default_base(root, head_sha):
    for name in ("main", "master"):
        try:
            sha = files.resolve_commit(root, name)
        except files.BadRef:
            continue
        if sha == head_sha:
            continue
        result = subprocess.run(
            ["git", "merge-base", "--end-of-options", sha, head_sha],
            cwd=root, capture_output=True, text=True,
        )
        found = result.stdout.strip()
        if result.returncode == 0 and found:
            return found
    raise ReviewError("pass --base REF. There is no merge-base with main or master.", code=2)


def _gh(root, args):
    try:
        result = subprocess.run(["gh", *args], cwd=root, capture_output=True, text=True)
    except FileNotFoundError:
        raise ReviewError("gh is not on PATH") from None
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "gh failed").strip()
        raise ReviewError(detail)
    return result.stdout


def _gh_json(root, args):
    text = _gh(root, args).strip()
    if not text:
        return []
    try:
        return json.loads(text)
    except json.JSONDecodeError as err:
        raise ReviewError(f"gh returned non-JSON ({err})") from None


def post_comment(root, number, path):
    """Create the pull request comment, or edit the one that carries the marker. Returns created or updated."""
    info = _gh_json(root, ["repo", "view", "--json", "nameWithOwner"])
    name = info.get("nameWithOwner") if isinstance(info, dict) else None
    if not name or "/" not in name:
        raise ReviewError("gh repo view did not return nameWithOwner")
    raw = _gh_json(root, ["api", "--paginate", f"repos/{name}/issues/{number}/comments"])
    comments = raw if isinstance(raw, list) else [raw]
    found = next((item for item in comments if isinstance(item, dict) and MARKER in (item.get("body") or "")), None)
    if found and found.get("id") is not None:
        _gh(root, ["api", "--method", "PATCH", f"repos/{name}/issues/comments/{found['id']}",
                   "--raw-field", f"body=@{path}"])
        return "updated"
    _gh(root, ["pr", "comment", str(number), "--body-file", str(path)])
    return "created"


def change_hash(base_sha, head_sha):
    """Cache key for the narrative: the protocol and the two commit ids."""
    payload = [tasks.PROTOCOL_VERSION, "summarise-change", base_sha, head_sha]
    return hashlib.sha1(json.dumps(payload).encode()).hexdigest()[:16]


def _open_tasks(db_path, base_sha, head_sha, result):
    conn = store.open_db(db_path)
    try:
        tasks.attach_cache(conn)
        with conn:
            change_task = _open_change(conn, base_sha, head_sha, result)
            define_task = _open_define(conn, result.get("provisional") or [])
        cached = tasks._cached_answer(conn, change_hash(base_sha, head_sha))
        narrative = cached.get("narrative") if isinstance(cached, dict) else None
        return narrative, change_task, define_task
    finally:
        conn.close()


def _open_change(conn, base_sha, head_sha, result):
    workspace = concepts._workspace(conn)
    if not workspace:
        return None
    digest = change_hash(base_sha, head_sha)
    task_id = "sc-" + digest[:8]
    cached = tasks._cached_answer(conn, digest)
    state = "done" if isinstance(cached, dict) and cached.get("narrative") else "open"
    inputs = {"base": base_sha, "head": head_sha, "changes": result}
    conn.execute(
        "INSERT INTO tasks (id, kind, node_id, input_hash, state, depends_on, inputs) "
        "VALUES (?, 'summarise-change', ?, ?, ?, '[]', ?) "
        "ON CONFLICT(id) DO UPDATE SET node_id = excluded.node_id, input_hash = excluded.input_hash, "
        "state = excluded.state, depends_on = '[]', inputs = excluded.inputs",
        (task_id, workspace["id"], digest, state, json.dumps(inputs)),
    )
    return {"id": task_id, "state": state}


def _open_define(conn, provisional):
    workspace = concepts._workspace(conn)
    if not workspace:
        return None
    task_id = "dcp-" + hashlib.sha1(workspace["id"].encode()).hexdigest()[:8]
    wanted = {row["file_id"] for row in provisional}
    files = [f for f in concepts._code_files(conn) if f["id"] in wanted]
    if not files:
        conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        return None
    pairs = concepts._pairs(conn, files)
    digest = concepts._input_hash(files, pairs)
    inputs = [f["id"] for f in sorted(files, key=lambda f: (f["path"], f["id"]))]
    conn.execute(
        "INSERT INTO tasks (id, kind, node_id, input_hash, state, depends_on, inputs) "
        "VALUES (?, 'define-concepts', ?, ?, 'open', '[]', ?) "
        "ON CONFLICT(id) DO UPDATE SET node_id = excluded.node_id, input_hash = excluded.input_hash, "
        "state = 'open', depends_on = '[]', inputs = excluded.inputs",
        (task_id, workspace["id"], digest, json.dumps(inputs)),
    )
    return {"id": task_id, "files": len(inputs)}


# --- diagram --------------------------------------------------------------------


def _unique(result):
    found, seen = [], set()
    for group in result["groups"]:
        for change in group["changes"]:
            key = (change["kind"], change["summary"],
                   json.dumps(change["before"], sort_keys=True), json.dumps(change["after"], sort_keys=True))
            if key not in seen:
                seen.add(key)
                found.append(change)
    return found


def _marks(result):
    added, removed = set(), set()
    for change in _unique(result):
        if change["kind"] in _ADDED and isinstance(change.get("after"), dict):
            added.add(change["after"].get("id"))
        elif change["kind"] in _REMOVED and isinstance(change.get("before"), dict):
            removed.add(change["before"].get("id"))
        elif change["kind"] == "concept-split" and isinstance(change.get("before"), dict):
            removed.add(change["before"].get("id"))
            for part in change.get("after") or []:
                if isinstance(part, dict):
                    added.add(part.get("id"))
        elif change["kind"] == "concept-merged" and isinstance(change.get("after"), dict):
            added.add(change["after"].get("id"))
            for part in change.get("before") or []:
                if isinstance(part, dict):
                    removed.add(part.get("id"))
    added.discard(None)
    removed.discard(None)
    return added, removed


def _renames(result):
    out = {}
    for change in _unique(result):
        if change["kind"] != "concept-renamed":
            continue
        before, after = change.get("before"), change.get("after")
        if isinstance(before, dict) and isinstance(after, dict) and before.get("id") and after.get("id"):
            if before["id"] != after["id"]:
                out[before["id"]] = after["id"]
    return out


def _graph(conn):
    nodes = {}
    for row in conn.execute("SELECT id, kind, display_kind, name, parent_id, path, workspace_id, attrs FROM nodes"):
        try:
            attrs = json.loads(row[7] or "{}")
        except json.JSONDecodeError:
            attrs = {}
        nodes[row[0]] = {
            "id": row[0], "kind": row[1], "display_kind": row[2], "name": row[3], "parent_id": row[4],
            "path": row[5] or "", "workspace_id": row[6], "attrs": attrs if isinstance(attrs, dict) else {},
        }
    edges = []
    for row in conn.execute(
            "SELECT src, dst, kind, attrs FROM edges WHERE kind IN ('relates', 'imports', 'depends_on', 'part_of')"):
        try:
            attrs = json.loads(row[3] or "{}")
        except json.JSONDecodeError:
            attrs = {}
        edges.append({"src": row[0], "dst": row[1], "kind": row[2], "attrs": attrs if isinstance(attrs, dict) else {}})
    return nodes, edges


def _file_of(nodes, nid):
    node = nodes.get(nid)
    if not node:
        return None
    if node["kind"] in ("file", "doc"):
        return node["id"]
    if node.get("workspace_id") and node.get("path"):
        return f"{node['workspace_id']}:{node['path']}"
    return None


def _test_file(nodes, fid):
    node = nodes.get(fid)
    return bool(node and (node["attrs"].get("role") == "test" or node["display_kind"] == "test file"))


def _container(nodes, edges, fid):
    targets = [nodes[e["dst"]] for e in edges if e["kind"] == "part_of" and e["src"] == fid and e["dst"] in nodes]
    deployables = sorted(n["id"] for n in targets if n["kind"] == "deployable")
    if deployables:
        return deployables[0]
    packages = sorted(n["id"] for n in targets if n["kind"] == "package")
    if packages:
        return packages[0]
    parent = nodes.get(fid, {}).get("parent_id")
    if parent and nodes.get(parent, {}).get("kind") == "group":
        return parent
    return fid


def build_diagram(result, base_conn, head_conn):
    """Changed nodes, the edges that touch them, and the nodes left out of the drawing.

    Concept maps draw relates edges. A direct neighbour is the other end of a
    relates edge that touches a changed concept, including an external. Without
    a changed concept, deployables, packages and folders are drawn the same way
    from depends-on and from imports between those containers.
    """
    base_nodes, base_edges = _graph(base_conn)
    head_nodes, head_edges = _graph(head_conn)
    nodes = {**base_nodes, **head_nodes}
    added, removed = _marks(result)
    renames = _renames(result)
    concept_groups = [g for g in result["groups"] if g["kind"] == "concept"]
    if concept_groups:
        return _concept_diagram(result, nodes, base_nodes, head_nodes, base_edges, head_edges,
                                concept_groups, added, removed, renames)
    return _container_diagram(result, nodes, base_nodes, head_nodes, base_edges, head_edges, added, removed)


def _status(nid, added, removed, changed):
    if nid in removed and nid not in added:
        return "removed"
    if nid in added:
        return "added"
    if nid in changed:
        return "changed"
    return "neighbour"


def _finish(result, nodes, changed, neighbours, edge_rows, added, removed, omitted_kinds):
    drawn = set(changed) | set(neighbours)
    kept = []
    for row in edge_rows:
        if row["src"] in drawn and row["dst"] in drawn and row["src"] != row["dst"]:
            if row["src"] in changed or row["dst"] in changed:
                kept.append(row)
    provisional = {row["concept_id"] for row in result.get("provisional") or [] if row.get("concept_id")}
    spec_nodes = []
    for nid in drawn:
        node = nodes.get(nid)
        name = node["name"] if node else result_name(result, nid)
        if nid in provisional:
            name = f"{name} (provisional)"
        spec_nodes.append({"id": nid, "label": name, "status": _status(nid, added, removed, changed)})
    omitted = []
    for nid, node in nodes.items():
        if node["kind"] in omitted_kinds and nid not in drawn:
            omitted.append({"id": nid, "name": node["name"], "kind": node["kind"]})
    omitted.sort(key=lambda item: (item["kind"], item["name"].lower(), item["id"]))
    mode = "concept" if "concept" in omitted_kinds else "container"
    return {"nodes": spec_nodes, "edges": _dedupe_edges(kept), "omitted": omitted, "mode": mode}


def result_name(result, nid):
    for group in result["groups"]:
        if group["id"] == nid:
            return group["name"]
    return nid


def _dedupe_edges(rows):
    found = {}
    for row in rows:
        found[(row["src"], row["dst"], row["label"], row["removed"])] = row
    return list(found.values())


def _rel_edges(side_nodes, edges, translate):
    """relates edges keyed by translated ends and label. Integration uses the side's own nodes."""
    found = {}
    for edge in edges:
        if edge["kind"] != "relates":
            continue
        src, dst = translate(edge["src"]), translate(edge["dst"])
        label = edge["attrs"].get("label") or ""
        via = edge["attrs"].get("via") or edge["attrs"].get("mechanism") or ""
        ends = (side_nodes.get(edge["src"]), side_nodes.get(edge["dst"]))
        integration = bool(edge["attrs"].get("integration")) or any(node and node["kind"] == "external" for node in ends)
        found[(src, dst, label)] = {"src": src, "dst": dst, "label": label, "via": via, "integration": integration}
    return found


def _concept_diagram(result, nodes, base_nodes, head_nodes, base_edges, head_edges,
                     concept_groups, added, removed, renames):
    translate = lambda nid: renames.get(nid, nid)
    base_rels = _rel_edges(base_nodes, base_edges, translate)
    head_rels = _rel_edges(head_nodes, head_edges, lambda nid: nid)
    changed = {g["id"] for g in concept_groups}
    changed |= {nid for nid in added | removed if nodes.get(nid, {}).get("kind") == "concept"}
    neighbours = set()
    rows = []
    for key in set(base_rels) | set(head_rels):
        removed_edge = key in base_rels and key not in head_rels
        info = base_rels[key] if removed_edge else head_rels[key]
        src, dst = info["src"], info["dst"]
        if src not in changed and dst not in changed:
            continue
        for end in (src, dst):
            kind = nodes.get(end, {}).get("kind")
            if end not in changed and kind in ("concept", "external"):
                neighbours.add(end)
        label = info["via"] if info["integration"] and info["via"] else (info["label"] or "relates")
        if removed_edge:
            label = f"{label} (removed)"
        rows.append({"src": src, "dst": dst, "label": label, "removed": removed_edge})
    renamed_away = set(renames)
    diagram = _finish(result, nodes, changed, neighbours, rows, added, removed, {"concept"})
    diagram["omitted"] = [item for item in diagram["omitted"] if item["id"] not in renamed_away]
    return diagram


def _container_diagram(result, nodes, base_nodes, head_nodes, base_edges, head_edges, added, removed):
    changed = {g["id"] for g in result["groups"]}

    def links(side_nodes, edges):
        containers = {}
        for node in side_nodes.values():
            if node["kind"] == "file":
                containers[node["id"]] = _container(side_nodes, edges, node["id"])
        found = {}
        for edge in edges:
            if edge["kind"] == "depends_on":
                found[(edge["src"], edge["dst"], "depends on")] = {
                    "src": edge["src"], "dst": edge["dst"], "label": "depends on", "removed": False,
                }
            if edge["kind"] != "imports":
                continue
            left, right = _file_of(side_nodes, edge["src"]), _file_of(side_nodes, edge["dst"])
            if not left or not right or left == right:
                continue
            if _test_file(side_nodes, left) or _test_file(side_nodes, right):
                continue
            src, dst = containers.get(left), containers.get(right)
            if not src or not dst or src == dst:
                continue
            found[(src, dst, "imports")] = {"src": src, "dst": dst, "label": "imports", "removed": False}
        return found

    base_links, head_links = links(base_nodes, base_edges), links(head_nodes, head_edges)
    neighbours = set()
    rows = []
    for key in set(base_links) | set(head_links):
        removed_edge = key in base_links and key not in head_links
        info = dict(base_links[key] if removed_edge else head_links[key])
        src, dst = info["src"], info["dst"]
        if src not in changed and dst not in changed:
            continue
        for end in (src, dst):
            if end not in changed and end in nodes:
                neighbours.add(end)
        if removed_edge:
            info["label"] = f"{info['label']} (removed)"
            info["removed"] = True
        rows.append(info)
    return _finish(result, nodes, changed, neighbours, rows, added, removed, {"deployable", "package", "group"})


def render_mermaid(diagram):
    """A flowchart LR. Node order is added, removed, changed, then neighbours."""
    ids = _mermaid_ids(node["id"] for node in diagram["nodes"])
    lines = ["flowchart LR", *(f"  {item}" for item in CLASS_DEFS)]
    nodes = sorted(diagram["nodes"], key=lambda n: (_STATUS_ORDER[n["status"]], n["label"].lower(), n["id"]))
    for node in nodes:
        label = _mermaid_label(node["label"])
        ident = ids[node["id"]]
        if node["status"] == "neighbour":
            lines.append(f'  {ident}["{label}"]')
        else:
            lines.append(f'  {ident}["{label}"]:::{node["status"]}')
    edges = []
    for edge in diagram["edges"]:
        if edge["src"] not in ids or edge["dst"] not in ids:
            continue
        edges.append(edge)
    edges.sort(key=lambda e: (
        _node_label(diagram, e["src"]).lower(), _node_label(diagram, e["dst"]).lower(),
        e["label"].lower(), e["removed"], e["src"], e["dst"],
    ))
    for edge in edges:
        arrow = "-.->" if edge["removed"] else "-->"
        lines.append(f'  {ids[edge["src"]]} {arrow}|"{_mermaid_label(edge["label"])}"| {ids[edge["dst"]]}')
    return "\n".join(lines) + "\n"


def _node_label(diagram, nid):
    for node in diagram["nodes"]:
        if node["id"] == nid:
            return node["label"]
    return nid


def _mermaid_ids(raw_ids):
    used, out = set(), {}
    for raw in sorted(set(raw_ids)):
        base = re.sub(r"[^A-Za-z0-9_]", "_", raw)
        if not base or not (base[0].isalpha() or base[0] == "_"):
            base = "n_" + base
        if base.lower() in _RESERVED:
            base = "n_" + base
        candidate, n = base, 2
        while candidate in used:
            candidate = f"{base}_{n}"
            n += 1
        used.add(candidate)
        out[raw] = candidate
    return out


def _mermaid_label(text):
    cleaned = re.sub(r'["\[\]|]+', " ", text or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or "node"


def valid_mermaid(text):
    """True when text is the flowchart this command writes. No network."""
    lines = text.splitlines()
    if len(lines) < 4 or lines[0] != "flowchart LR":
        return False
    body = []
    for line in lines[1:]:
        if len(line) < 3 or not line.startswith("  ") or line[2] == " ":
            return False
        body.append(line[2:])
    if tuple(body[:3]) != CLASS_DEFS:
        return False
    nodes, seen_edge = {}, False
    for line in body[3:]:
        if not line:
            return False
        edge = _EDGE_LINE.match(line)
        if edge:
            seen_edge = True
            src, _arrow, _label, dst = edge.groups()
            if src not in nodes or dst not in nodes:
                return False
            continue
        if seen_edge:
            return False
        node = _NODE_LINE.match(line)
        if not node:
            return False
        ident, _label, klass = node.groups()
        if ident in nodes:
            return False
        nodes[ident] = klass
    return True


def _omitted_text(diagram):
    omitted = diagram["omitted"]
    if not omitted:
        return ""
    if diagram["mode"] == "concept":
        names = [item["name"] for item in omitted]
        shown = ", ".join(names[:40])
        more = f", and {len(names) - 40} more" if len(names) > 40 else ""
        noun = "concept" if len(names) == 1 else "concepts"
        return f"Not drawn: {len(names)} {noun} with no direct link to a change ({shown}{more})."
    named = [item for item in omitted if item["kind"] in ("deployable", "package")]
    folders = [item for item in omitted if item["kind"] == "group"]
    parts = []
    if named:
        shown = ", ".join(item["name"] for item in named[:40])
        more = f", and {len(named) - 40} more" if len(named) > 40 else ""
        parts.append(f"{len(named)} deployables or packages ({shown}{more})")
    if folders:
        parts.append(f"{len(folders)} folders")
    if not parts:
        return ""
    return "Not drawn: " + "; ".join(parts) + "."


def _counts(result):
    counts = defaultdict(int)
    for change in _unique(result):
        counts[change["kind"]] += 1
    lines = [f"- {counts[kind]} {kind}" for kind in diff.KINDS if counts[kind]]
    provisional = result.get("provisional") or []
    if provisional:
        lines.append(f"- {len(provisional)} provisional files")
    return lines or ["- no architectural changes"]


def open_link(root, base_sha, head_sha):
    repo = quote(str(Path(root).resolve()), safe="/")
    return f"cbi://open?repo={repo}&compare={base_sha}..{head_sha}"


def _top_name(conn):
    row = conn.execute(
        "SELECT name FROM nodes WHERE kind = 'workspace' AND parent_id IS NULL ORDER BY id LIMIT 1"
    ).fetchone()
    return row[0] if row else ""


def render_review(root, base_sha, head_sha, spec, result, diagram, mermaid, narrative, change_task, define_task,
                  images=None, repo_name=None):
    """The review.md body."""
    heading = f"# Review {base_sha[:12]}..{head_sha[:12]}"
    if repo_name:
        heading = f"# Review {repo_name} {base_sha[:12]}..{head_sha[:12]}"
    lines = [open_link(root, base_sha, head_sha), "", MARKER, "", heading, ""]
    if spec.get("url"):
        lines += [f"Pull request: {spec['url']}", ""]
    lines += ["## Summary", ""]
    lines += _counts(result)
    lines.append("")
    if change_task:
        lines.append(f"Narrative task: `{change_task['id']}` ({change_task['state']}).")
        lines.append("")
    if define_task:
        lines.append(
            f"Provisional concepts: `{define_task['id']}` covers {define_task['files']} "
            "files on the head model."
        )
        lines.append("")
    lines += ["## Diagram", "", "```mermaid", mermaid.rstrip("\n"), "```", ""]
    omitted = _omitted_text(diagram)
    if omitted:
        lines += [omitted, ""]
    if narrative:
        lines += ["## Narrative", "", narrative.strip(), ""]
    heading = "Concepts" if diagram["mode"] == "concept" else "Deployables, packages and folders"
    lines += [f"## {heading}", ""]
    if not result["groups"]:
        lines += ["No grouped changes.", ""]
    added, removed = _marks(result)
    changed = {group["id"] for group in result["groups"]}
    provisional = result.get("provisional") or []
    for group in result["groups"]:
        status = _status(group["id"], added, removed, changed)
        suffix = status
        owned = [row for row in provisional if row.get("concept_id") == group["id"]]
        if owned:
            suffix += ", provisional files"
        lines.append(f"### {group['name']} `{group['id']}` ({suffix})")
        lines.append("")
        for row in owned:
            lines.append(f"- provisional  {row['path']}  ({row['by']})")
        for change in group["changes"]:
            lines.append(f"- {change['kind']}  {change['summary']}")
            for code in change["code"]:
                lines.append(f"  - {code['path'] or code['id']}  {code['name']}")
        lines.append("")
    unowned = [row for row in provisional if not row.get("concept_id")]
    if unowned:
        lines += ["## Provisional files with no owner", ""]
        lines += [f"- {row['path']}" for row in unowned]
        lines.append("")
    lines += ["## Untested changes", ""]
    untested = [c for c in _unique(result) if c["kind"] == "untested"]
    lines += [f"- {c['summary']}" for c in untested] or ["None."]
    lines.append("")
    lines += ["## Changed integration points", ""]
    integrations = [c for c in _unique(result) if c["kind"].startswith("integration-")]
    lines += [f"- {c['kind']}  {c['summary']}" for c in integrations] or ["None."]
    lines += ["", *_image_lines(images)]
    return "\n".join(lines)


def _image_lines(images):
    if images and "before.png" in images:
        body = [
            "- before.png",
            "- before.svg",
            "- after.png",
            "- after.svg",
            "",
            "These files are in this folder. Attach them to the pull request comment by hand. "
            "GitHub renders the Mermaid diagram above without them.",
        ]
    elif images and images.get("skipped"):
        body = [images["skipped"]]
    elif images and images.get("failed"):
        body = [f"Images were not written: {images['failed']}"]
    else:
        body = ["Images were not written."]
    return ["## Images", "", *body, ""]

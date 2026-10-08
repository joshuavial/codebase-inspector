"""Parts of a define-concepts or sketch-screens brief that is over the size budget.

Concepts split into one part per package or deployable: that area's files, summaries,
symbol outlines and the pairs inside it, then a cross-area part with the pairs between
areas and the area summaries. Screens split into one part per UI deployable, holding the
page tree reached from its entries, with each component's JSX left whole. The answer is
still one JSON document.
"""

import contextvars
import json
import os
from collections import defaultdict
from pathlib import Path

from cbi import concepts, screens, tasks

SPLIT_KINDS = ("define-concepts", "sketch-screens")
DEFAULT_BUDGET = 150 * 1024
# The model directory whose team.toml brief_budget applies. Unset leaves the env var in charge.
_brief_out = contextvars.ContextVar("cbi_brief_out", default=None)


def bind(out):
    """Read brief_budget from this model directory until unbind. Returns a reset token."""
    return _brief_out.set(Path(out) if out is not None else None)


def unbind(token):
    _brief_out.reset(token)


def budget():
    """UTF-8 byte budget for one part.

    A bound model directory's team.toml brief_budget wins. CBI_BRIEF_BUDGET
    applies when that file is absent. Otherwise the default is 150 KB.
    `cbi task` and `cbi prime` bind the model directory they read.
    """
    limit = _team_budget(_brief_out.get())
    if limit is not None:
        return limit
    raw = os.environ.get("CBI_BRIEF_BUDGET")
    if not raw:
        return DEFAULT_BUDGET
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_BUDGET
    return value if value > 0 else DEFAULT_BUDGET


def _team_budget(out):
    from cbi import team
    if out is None:
        return None
    directory = team.team_dir(out)
    if directory is None:
        return None
    cfg = team.settings(directory)
    return cfg["brief_budget"] if cfg else None


def render_text(brief):
    if brief["kind"] == "define-concepts":
        return concepts.format_brief(brief)
    if brief["kind"] == "sketch-screens":
        return screens.format_brief(brief)
    raise ValueError(brief["kind"])


def over_note(brief, text):
    """The line added to a whole brief that needs parts, or ""."""
    if brief.get("kind") not in SPLIT_KINDS:
        return ""
    size = len(text.encode())
    limit = budget()
    if size <= limit:
        return ""
    task_id = brief["id"]
    return (
        f"This brief is {size} bytes, over the {limit} byte budget. "
        f"List parts with `cbi task {task_id} --parts`, read one with `--part N`, "
        f"draft every area into one answer, check it with `cbi task {task_id} --check answer.json`, "
        f"then submit that file once."
    )


def insert_note(text, line):
    if not line:
        return text
    head, sep, tail = text.partition("\n")
    return f"{head}\n{line}{sep}{tail}"


def _fits(text, margin=0):
    return len(text.encode()) + margin <= budget()


def _fit(items, render):
    """Split items so each rendered piece fits the budget. A single item stays whole.

    The margin leaves room for the final part label, which is filled in after the split.
    """
    if not items:
        return []
    if _fits(tasks.sized(render(items)), 32) or len(items) == 1:
        return [items]
    mid = len(items) // 2
    return _fit(items[:mid], render) + _fit(items[mid:], render)


def _label(area, names):
    if area["kind"] == "package":
        label = f"package {area['name']}"
        if names.count(area["name"]) > 1 and area.get("directory"):
            label += f" ({area['directory']})"
        return label
    if area["kind"] == "deployable":
        return f"deployable {area['name']}"
    return "other"


def _row(area):
    return {
        "name": area["name"],
        "display_kind": area.get("display_kind") or "area",
        "summary": area.get("summary"),
        "path": area.get("directory") or "",
    }


def _packages(conn):
    found, root_pkg = [], None
    for name, display, summary, attrs, wid in conn.execute(
        "SELECT name, display_kind, summary, attrs, workspace_id FROM nodes WHERE kind = 'package' ORDER BY name"
    ):
        directory = json.loads(attrs or "{}").get("directory") or ""
        if directory:
            directory = tasks._read_path(conn, wid, directory).strip("/")
        area = {"name": name, "kind": "package", "directory": directory, "summary": summary, "display_kind": display}
        if directory:
            found.append(area)
        else:
            root_pkg = area
    found.sort(key=lambda area: len(area["directory"]), reverse=True)
    return found, root_pkg


def _deployables_of(conn):
    """file id -> deployable areas, the name-sorted first one first."""
    found = defaultdict(list)
    rows = conn.execute(
        "SELECT e.src, d.name, d.display_kind, d.summary FROM edges e "
        "JOIN nodes d ON d.id = e.dst WHERE e.kind = 'part_of' AND d.kind = 'deployable' "
        "ORDER BY d.name, e.src"
    )
    for src, name, display, summary in rows:
        found[src].append({"name": name, "kind": "deployable", "summary": summary, "display_kind": display})
    return found


def _area_for(node, packages, root_pkg, deployables):
    path = node["path"]
    best = None
    for pkg in packages:
        directory = pkg["directory"]
        if path == directory or path.startswith(directory + "/"):
            if best is None or len(directory) > len(best["directory"]):
                best = pkg
    if best:
        return best
    if root_pkg and "/" not in path:
        return root_pkg
    deps = deployables.get(node.get("id")) or []
    if deps:
        return deps[0]
    return {"name": "other", "kind": "other", "summary": None, "display_kind": "area", "directory": ""}


def _area_rows(brief, area):
    if area["kind"] == "package":
        rows = [row for row in brief.get("packages") or [] if row.get("name") == area["name"]]
        packages = rows or [_row(area)]
        return [], packages
    if area["kind"] == "deployable":
        rows = [row for row in brief.get("deployables") or [] if row.get("name") == area["name"]]
        return rows or [_row(area)], []
    return [], []


def _concept_body(brief, files, pairs, deployables, packages, areas, name, shared):
    body = {
        "id": brief["id"], "kind": brief["kind"], "state": brief["state"], "node_id": brief["node_id"],
        "input_hash": brief["input_hash"], "instructions": brief["instructions"],
        "answer_schema": brief["answer_schema"], "checks": brief["checks"], "workspace": brief.get("workspace"),
        "deployables": deployables, "packages": packages, "files": files,
        "pairs": [{"from": p["from"], "to": p["to"], "kind": p["kind"], "count": p["count"]} for p in pairs],
        "env": brief.get("env") if shared else [],
        "concepts": brief.get("concepts") if shared else None,
        "removed": brief.get("removed") if shared else [],
        "rescan": brief.get("rescan"),
        "part": {"index": 1, "count": 999, "name": name},
    }
    if areas is not None:
        body["areas"] = areas
    return body


def _among(pairs, paths):
    return [p for p in pairs if p["from"] in paths and p["to"] in paths]


def _concept_chunks(conn, brief):
    files = list(brief.get("files") or [])
    packages, root_pkg = _packages(conn)
    deployables = _deployables_of(conn)
    groups = {}
    for node in files:
        area = _area_for(node, packages, root_pkg, deployables)
        key = (area["kind"], area.get("directory") or area["name"])
        slot = groups.get(key)
        if slot is None:
            slot = groups[key] = {"area": area, "files": []}
        slot["files"].append(node)
    ordered = sorted(groups.values(), key=lambda slot: (
        {"package": 0, "deployable": 1, "other": 2}[slot["area"]["kind"]],
        slot["area"].get("directory") or "",
        slot["area"]["name"],
    ))
    names = [slot["area"]["name"] for slot in ordered]
    pairs = list(brief.get("pairs") or [])
    chunks = []
    covered = []
    area_meta = []
    for slot in ordered:
        area = slot["area"]
        label = _label(area, names)
        area_files = sorted(slot["files"], key=lambda node: node["path"])
        area_meta.append({"name": label, "files": len(area_files), "summary": area.get("summary")})
        deps, pkgs = _area_rows(brief, area)

        def render(subset, label=label, deps=deps, pkgs=pkgs):
            paths = {node["path"] for node in subset}
            body = _concept_body(brief, subset, _among(pairs, paths), deps, pkgs, None, label, False)
            return concepts.format_brief(body)

        subsets = _fit(area_files, render)
        width = len(subsets)
        for index, subset in enumerate(subsets, 1):
            name = label if width == 1 else f"{label} {index}/{width}"
            paths = {node["path"] for node in subset}
            covered.append(paths)
            body = _concept_body(brief, subset, _among(pairs, paths), deps, pkgs, None, name, False)
            chunks.append({"name": name, "brief": body})
    cross = [p for p in pairs if not any(p["from"] in paths and p["to"] in paths for paths in covered)]

    def render_cross(subset, shared=False):
        body = _concept_body(
            brief, [], subset, brief.get("deployables") or [], brief.get("packages") or [], area_meta, "cross-area", shared)
        return concepts.format_brief(body)

    # Pair chunks are fitted without the current map. That map is one part's payload:
    # on the first cross chunk when it still fits, otherwise on its own part. Copying it
    # onto every chunk would leave each chunk room for only a few pairs.
    subsets = _fit(cross, render_cross) if cross else [[]]
    with_map = False
    if brief.get("concepts"):
        sample = subsets[0] if subsets else []
        with_map = _fits(tasks.sized(render_cross(sample, True)), 32)
        if not with_map:
            chunks.append({"name": "current concepts", "brief": _concept_body(
                brief, [], [], [], [], None, "current concepts", True)})
    width = len(subsets)
    for index, subset in enumerate(subsets, 1):
        name = "cross-area" if width == 1 else f"cross-area {index}/{width}"
        body = _concept_body(
            brief, [], subset, brief.get("deployables") or [], brief.get("packages") or [],
            area_meta, name, with_map and index == 1)
        chunks.append({"name": name, "brief": body})
    return chunks


def _deployable_by_path(conn):
    found = {}
    rows = conn.execute(
        "SELECT e.src, d.name FROM edges e JOIN nodes d ON d.id = e.dst "
        "WHERE e.kind = 'part_of' AND d.kind = 'deployable' ORDER BY d.name, e.src"
    )
    for src, name in rows:
        info = conn.execute("SELECT path, workspace_id FROM nodes WHERE id = ?", (src,)).fetchone()
        if not info:
            continue
        found.setdefault(tasks._read_path(conn, info[1], info[0]), name)
    return found


def _reachable(roots, renders, by_ref):
    seen, got, stack = [], set(), list(roots)
    while stack:
        ref = stack.pop()
        if ref in got or ref not in by_ref:
            continue
        got.add(ref)
        seen.append(ref)
        stack.extend(renders.get(ref) or [])
    return seen


def _screen_body(full, components, name, screens_doc=None):
    refs = {comp["ref"] for comp in components}
    entries = [entry for entry in full.get("entries") or [] if entry.get("component") in refs]
    states = [state for state in full.get("states") or [] if any(ref in refs for ref in state.get("set_in") or [])]
    kept_concepts = []
    for concept in full.get("concepts") or []:
        owned = [ref for ref in concept.get("components") or [] if ref in refs]
        if owned:
            kept_concepts.append({**concept, "components": owned})
    return {
        "id": full["id"], "kind": full["kind"], "state": full["state"], "node_id": full["node_id"],
        "input_hash": full["input_hash"], "instructions": full["instructions"],
        "answer_schema": full["answer_schema"], "checks": full["checks"],
        "entries": entries, "states": states, "concepts": kept_concepts, "components": components,
        "screens": screens_doc, "part": {"index": 1, "count": 999, "name": name},
    }


def _screen_chunks(conn, brief, root):
    full = screens.brief_body(conn, brief, root, full_jsx=True)
    for key in ("id", "kind", "state", "node_id", "input_hash", "instructions", "answer_schema"):
        full[key] = brief[key]
    components = list(full.get("components") or [])
    by_ref = {comp["ref"]: comp for comp in components}
    renders = {comp["ref"]: [ref for ref in comp.get("renders") or [] if ref in by_ref] for comp in components}
    dep_of = _deployable_by_path(conn)

    def deployable(path):
        return dep_of.get(path)

    groups = defaultdict(list)
    for entry in full.get("entries") or []:
        ref = entry.get("component") or ""
        path = entry.get("from") or ref.split("#", 1)[0]
        groups[deployable(path) or deployable(ref.split("#", 1)[0]) or "ui"].append(entry)
    claimed = set()
    trees = []
    for name in sorted(groups):
        roots = [entry["component"] for entry in groups[name] if entry.get("component") in by_ref]
        seen = _reachable(roots, renders, by_ref)
        got = set(seen)
        for comp in components:
            if deployable(comp["path"]) == name and comp["ref"] not in got:
                got.add(comp["ref"])
                seen.append(comp["ref"])
        comps = [by_ref[ref] for ref in seen if ref not in claimed]
        claimed.update(seen)
        if comps:
            trees.append((f"deployable {name}", comps))
    rest = defaultdict(list)
    for comp in components:
        if comp["ref"] not in claimed:
            rest[deployable(comp["path"]) or "other"].append(comp)
    for name in sorted(rest):
        trees.append(("other" if name == "other" else f"deployable {name}", rest[name]))
    if not trees and components:
        trees.append(("ui", components))
    chunks = []
    for label, comps in trees:
        def render(subset, label=label):
            return screens.format_brief(_screen_body(full, subset, label))

        subsets = _fit(comps, render)
        width = len(subsets)
        for index, subset in enumerate(subsets, 1):
            name = label if width == 1 else f"{label} {index}/{width}"
            chunks.append({"name": name, "brief": _screen_body(full, subset, name)})
    document = full.get("screens")
    if document and chunks:
        last = chunks[-1]["brief"]
        last["screens"] = document
        if not _fits(tasks.sized(screens.format_brief(last))) and last.get("components"):
            last["screens"] = None
            chunks.append({"name": "current screens", "brief": _screen_body(full, [], "current screens", document)})
    elif document:
        chunks.append({"name": "current screens", "brief": _screen_body(full, [], "current screens", document)})
    return chunks


def _number(chunks):
    total = len(chunks)
    parts = []
    for index, chunk in enumerate(chunks, 1):
        body = chunk["brief"]
        body["part"] = {"index": index, "count": total, "name": chunk["name"]}
        text = tasks.sized(render_text(body))
        parts.append({"name": chunk["name"], "text": text, "bytes": len(text.encode()), "brief": body})
    return parts


def split_brief(conn, brief, root):
    """Parts for one brief. Under the budget this is the whole brief as a single part."""
    whole = render_text(brief)
    nbytes = len(whole.encode())
    limit = budget()
    over = nbytes > limit
    if over and brief["kind"] == "define-concepts":
        chunks = _concept_chunks(conn, brief)
    elif over and brief["kind"] == "sketch-screens":
        chunks = _screen_chunks(conn, brief, root)
    else:
        chunks = None
    if not chunks:
        text = tasks.sized(whole)
        parts = [{"name": "full", "text": text, "bytes": len(text.encode()), "brief": brief}]
        over = False
    else:
        parts = _number(chunks)
    return {
        "id": brief["id"], "kind": brief["kind"], "budget": limit, "brief_bytes": nbytes,
        "split": over, "parts": parts,
    }


def index_payload(spec):
    return {
        "id": spec["id"], "kind": spec["kind"], "budget": spec["budget"],
        "brief_bytes": spec["brief_bytes"], "split": spec["split"],
        "parts": [{"index": index, "name": part["name"], "bytes": part["bytes"]}
                  for index, part in enumerate(spec["parts"], 1)],
    }


def index_text(spec):
    payload = index_payload(spec)
    count = len(spec["parts"])
    lines = [
        f"# Parts for {spec['id']}: {spec['kind']}",
        f"budget: {spec['budget']} bytes",
        f"full brief: {spec['brief_bytes']} bytes",
        f"{count} part" if count == 1 else f"{count} parts",
    ]
    if spec["split"]:
        lines.append("The answer is still one JSON file. Draft each part into it, then check and submit once.")
    else:
        lines.append("The brief is under the budget, so it is one part.")
    lines += [f"{part['index']:>3}  {part['bytes']:>8} bytes  {part['name']}" for part in payload["parts"]]
    lines.append(f"Read a part with `cbi task {spec['id']} --part N`.")
    return "\n".join(lines) + "\n"


def large_lines(conn, root, out_flag):
    """Prime lines for a repo whose concept or screen brief exceeds the budget, or which has many file tasks."""
    lines = []
    rows = conn.execute(
        "SELECT id, kind FROM tasks WHERE state = 'open' AND kind IN ('define-concepts', 'sketch-screens') "
        "ORDER BY kind, id"
    )
    for task_id, kind in rows:
        brief = tasks.brief(conn, task_id, root)
        text = render_text(brief)
        size = len(text.encode())
        if size <= budget():
            continue
        lines += [
            f"{kind} {task_id} is {size} bytes, over the {budget()} byte budget. "
            "The answer is one JSON file. Read each part, draft that area into the file, check, then submit once:",
            "",
            f"  cbi task {task_id} --parts{out_flag}",
            f"  cbi task {task_id} --part 1{out_flag}",
            f"  cbi task {task_id} --check answer.json{out_flag}",
            f"  cbi submit {task_id} answer.json{out_flag}",
            "",
        ]
        if kind == "define-concepts":
            lines += [concepts.PLACEMENT, ""]
    pending = conn.execute(
        "SELECT count(*) FROM tasks WHERE state = 'open' AND kind = 'summarise-files'"
    ).fetchone()[0]
    if pending > tasks.FILES_PER_TASK:
        lines += [
            f"{pending} summarise-files tasks are open. Batch the list:",
            "",
            f"  cbi tasks --kind summarise-files --json --limit 20 --offset 0{out_flag}",
            "",
        ]
    if not lines:
        return []
    return ["## Large briefs", ""] + lines

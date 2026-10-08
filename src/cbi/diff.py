"""Structural diff between two model databases.

Compares stable node IDs. A file or symbol whose content hash is unchanged,
while its path or qualified name moved, is a move: the hash has to be unique
among the removed nodes and among the added ones, so two copies of the same
body are not paired. Symbol content hashes are the body, the source after
the signature, which is why a rename still matches.

`cbi diff <base> <head>` scans both git refs, or reuses the stored models,
and compares them. `--out` chooses the model directory.
"""

import json
import posixpath
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

from cbi import files, store

HELP = """\
Print the architectural changes between two models.

Pass --base-model and --head-model, each a model.db from `cbi scan --out`
or the directory that contains it. Or pass two git refs:
`cbi diff <base> <head>` scans each ref (or reuses the stored model) into
the model directory, `.cbi/` or `--out`, at refs/<commit>/model.db. The
directory must already be initialised (`cbi init`). Stdout is only the diff.

--format text (default) groups changes with the most significant group
first. markdown is the same text with headings. json prints the object
below. --concept ID keeps changes for that concept: a group with that id,
and changes whose before, after or code mention it.

With concepts on either side, changes are grouped by concept. A deployable,
package or unowned file keeps its own group. With no concepts, grouping is
"deployable": a deployable that contains the file, else its package, else
its folder.

Order, most significant first: concept structure, integration points,
relationships, files moving between concepts, deployables, packages,
dependencies, file moves, env vars, symbols, untested code, component
renders, tests.

JSON shape, keys sorted, groups and changes in the order above:

  {"grouping": "concept" | "deployable",
   "groups": [{"id", "name", "kind": "concept"|"deployable"|"package"|"folder",
                "changes": [Change]}]}

  Change is {"kind", "summary", "before", "after", "code"}.
  before and after are null when that side has nothing.
  code is [{"id", "name", "path", "display_kind"}], the nodes behind the change.

  concept-added        after {id, name}
  concept-removed      before {id, name}
  concept-renamed      before {id, name}, after {id, name}
  concept-split        before {id, name}, after [{id, name}, ...]
  concept-merged       before [{id, name}, ...], after {id, name}
  file-moved-concept   before and after {id, name, path}  (the concept, and the file path)
  file-moved           before and after {id, path}
  relationship-added   after {from, to, label, calls, imports}
  relationship-removed before {from, to, label, calls, imports}
  relationship-volume  before and after {from, to, label, calls, imports}
  integration-added    after {from, to, label, mechanism, at}
  integration-removed  before {from, to, label, mechanism, at}
  integration-changed  before and after {from, to, label, mechanism, at}
  deployable-added     after {id, name}     deployable-removed before {id, name}
  package-added        after {id, name}     package-removed before {id, name}
  depends-on-added     after {from, to}     depends-on-removed before {from, to}
  env-read             after {name}         env-unread before {name}
  symbol-added         after {id, name, path, display_kind}
  symbol-removed       before {id, name, path, display_kind}
  symbol-moved         before and after {id, name, path, signature}
  symbol-changed       before and after {signature, body}  body is the body hash
  test-added           after {id, name, path}
  test-removed         before {id, name, path}
  untested             after {id, name, path}  a changed symbol with no linked test
  render-added         after {from, to}     render-removed before {from, to}
                       from and to are symbol ids; the source is a component

A relationship is keyed by its ends and its label. calls and imports are the
total weight of those edges from files under `from` to files under `to`,
test files left out. An injection call counts as a call. An integration is a relates edge flagged integration
or with an external at one end; mechanism is its `via` (or `mechanism`) and
at is where it happens. A concept rename is the same owned files under a new
id, or the same id with a new name. A split is one removed concept whose
files are exactly the files of two or more new concepts; a merge is the
reverse. Those files are not also reported as moving between concepts.

A head code or test file that no concept owns, and that the base does not
already contain, is given a provisional owner when the head has concepts:
the concept that owns the most of its import neighbours, otherwise the
concept that owns the majority of the files in its folder, walking up while
a folder has none. A tie takes the smaller concept id. The json then has
"provisional": [{file_id, path, concept_id, concept_name, by}]. by is
"imports" or "folder". concept_id is null when nothing owns a neighbour or
a folder. Files that already exist on the base are left as they are.

Exit codes: 0 the diff was printed, including an empty one, 1 a model path
is missing or not a model from this schema, the ref is unknown, the
directory is not a git repo, or it is not initialised, 2 the arguments
were mixed or incomplete."""

KINDS = (
    "concept-removed", "concept-added", "concept-split", "concept-merged", "concept-renamed",
    "integration-removed", "integration-added", "integration-changed",
    "relationship-removed", "relationship-added", "relationship-volume",
    "file-moved-concept", "deployable-removed", "deployable-added",
    "package-removed", "package-added", "depends-on-removed", "depends-on-added",
    "file-moved", "env-unread", "env-read",
    "symbol-removed", "symbol-added", "symbol-moved", "symbol-changed", "untested",
    "render-removed", "render-added", "test-removed", "test-added",
)
RANK = {kind: index for index, kind in enumerate(KINDS)}

_PUBLIC = ("kind", "summary", "before", "after", "code")


class DiffError(Exception):
    def __init__(self, message, code=2):
        super().__init__(message)
        self.code = code


def models_for_refs(base_ref, head_ref, root=None, out=None):
    """Scan both refs, or reuse their stored models, and open them read-only.

    Models land at <out>/refs/<sha>/model.db. out defaults to <root>/.cbi.
    The directory must already contain an ignore file (`cbi init`).
    """
    # cli imports this module, so the scan entry point is imported here.
    from cbi.cli import scan_ref

    root = Path(root) if root else files.repo_root(Path.cwd())
    out = Path(out) if out else root / ".cbi"
    if not (out / "ignore").exists():
        raise DiffError(f"{out} is not initialised. Run `cbi init` first.", code=1)
    paths = []
    for ref in (base_ref, head_ref):
        try:
            sha, _reused, _counts, _open = scan_ref(root, out, ref)
        except files.BadRef as err:
            raise DiffError(str(err), code=1) from err
        paths.append(out / "refs" / sha / "model.db")
    base = open_model(paths[0])
    try:
        return base, open_model(paths[1])
    except DiffError:
        base.close()
        raise


def open_model(path):
    """Open a model database read-only. Accepts the db file or its directory."""
    path = Path(path).expanduser().resolve()
    if path.is_dir():
        path = path / "model.db"
    if not path.is_file():
        raise DiffError(f"no model at {path}", code=1)
    conn = None
    try:
        conn = store.read_only(path)
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version != store.SCHEMA_VERSION:
            raise DiffError(
                f"{path} is schema {version}; this cbi expects {store.SCHEMA_VERSION}. Rescan it.",
                code=1,
            )
        conn.execute("SELECT 1 FROM nodes LIMIT 1")
    except DiffError:
        if conn is not None:
            conn.close()
        raise
    except sqlite3.DatabaseError as err:
        if conn is not None:
            conn.close()
        raise DiffError(f"{path} is not a cbi model ({err})", code=1) from err
    return conn


def open_pair(base_model, head_model, base_ref, head_ref, root=None, out=None):
    """Return (base conn, head conn) from model paths or from two git refs."""
    if base_model or head_model:
        if base_ref or head_ref:
            raise DiffError("pass model paths or refs, not both")
        if not base_model or not head_model:
            raise DiffError("pass both --base-model and --head-model")
        base = open_model(base_model)
        try:
            return base, open_model(head_model)
        except DiffError:
            base.close()
            raise
    if bool(base_ref) ^ bool(head_ref):
        raise DiffError("pass both refs, or --base-model and --head-model")
    if base_ref:
        return models_for_refs(base_ref, head_ref, root, out)
    raise DiffError("pass --base-model and --head-model, or two refs")


def compare(base_conn, head_conn):
    """The grouped change list for two open models."""
    base, head = _load(base_conn), _load(head_conn)
    file_moves = {}
    for kind in ("file", "doc"):
        file_moves.update(_pair(base, head, kind))
    symbol_moves = _pair(base, head, "symbol")
    test_moves = _pair(base, head, "test")
    canon = {}
    for src, dst in file_moves.items():
        canon[src] = src
        canon[dst] = src
    base_owner = _owners(base, canon)
    head_owner = _owners(head, canon)
    rename, split_src, split_dst, merge_src, merge_dst = _concept_sets(base, head, base_owner, head_owner)
    concept_mode = any(n["kind"] == "concept" for n in (*base.nodes.values(), *head.nodes.values()))
    # After split and merge detection: a provisional file must not change those file sets.
    provisional = _provisional(base, head, canon, base_owner, head_owner) if concept_mode else []
    _apply_provisional(head, head_owner, canon, provisional)
    ctx = _Ctx(base, head, canon, file_moves, symbol_moves, test_moves,
               base_owner, head_owner, rename, split_src, split_dst, merge_src, merge_dst, concept_mode)
    changes = []
    changes += _concept_changes(ctx)
    changes += _ownership_moves(ctx)
    changes += _path_moves(ctx)
    changes += _relationship_changes(ctx)
    changes += _node_kind_changes(ctx, "deployable")
    changes += _node_kind_changes(ctx, "package")
    changes += _depends_changes(ctx)
    changes += _env_changes(ctx)
    changes += _symbol_changes(ctx)
    changes += _test_changes(ctx)
    changes += _untested(ctx, changes)
    changes += _render_changes(ctx)
    result = _group(ctx, changes)
    if provisional:
        result["provisional"] = provisional
    return result


def render(result, fmt="text", concept=None):
    """Text, markdown or json for a compare() result. concept filters by id."""
    shown = _filter(result, concept)
    if fmt == "json":
        return json.dumps(shown, indent=2, sort_keys=True) + "\n"
    if fmt == "markdown":
        return _markdown(shown)
    return _text(shown)


# --- load -----------------------------------------------------------------------


class _Side:
    def __init__(self, nodes, edges):
        self.nodes = nodes
        self.edges = edges
        self.by_kind = defaultdict(list)
        for edge in edges:
            self.by_kind[edge["kind"]].append(edge)


class _Ctx:
    def __init__(self, base, head, canon, file_moves, symbol_moves, test_moves,
                 base_owner, head_owner, rename, split_src, split_dst, merge_src, merge_dst, concept_mode):
        self.base = base
        self.head = head
        self.canon = canon
        self.file_moves = file_moves
        self.symbol_moves = symbol_moves
        self.test_moves = test_moves
        self.base_owner = base_owner
        self.head_owner = head_owner
        self.rename = rename
        self.split_src = split_src
        self.split_dst = split_dst
        self.merge_src = merge_src
        self.merge_dst = merge_dst
        self.concept_mode = concept_mode
        self.base_parents = _parents(base)
        self.head_parents = _parents(head)
        self.base_volume = _leaf_volume(base, _raw_owners(base))
        self.head_volume = _leaf_volume(head, _raw_owners(head))


def _load(conn):
    nodes = {}
    for row in conn.execute(
            "SELECT id, parent_id, kind, display_kind, name, path, workspace_id, content_hash, signature, attrs "
            "FROM nodes"):
        attrs = {}
        if row[9]:
            try:
                parsed = json.loads(row[9])
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict):
                attrs = parsed
        nodes[row[0]] = {
            "id": row[0], "parent_id": row[1], "kind": row[2], "display_kind": row[3],
            "name": row[4], "path": row[5] or "", "workspace_id": row[6],
            "content_hash": row[7], "signature": row[8] or "", "attrs": attrs,
        }
    edges = []
    for row in conn.execute("SELECT src, dst, kind, weight, attrs, ordinal FROM edges"):
        attrs = {}
        if row[4]:
            try:
                parsed = json.loads(row[4])
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict):
                attrs = parsed
        edges.append({"src": row[0], "dst": row[1], "kind": row[2], "weight": row[3] or 1,
                      "attrs": attrs, "ordinal": row[5] or 0})
    edges.sort(key=lambda e: (e["kind"], e["src"], e["dst"], e["ordinal"]))
    return _Side(nodes, edges)


def _pair(base, head, kind):
    """base id -> head id for nodes of this kind whose content hash is unique on each side."""
    def hanging(side, other):
        return [(node["id"], node["content_hash"]) for node in side.nodes.values()
                if node["kind"] == kind and node["id"] not in other.nodes and node["content_hash"]]
    left, right = defaultdict(list), defaultdict(list)
    for nid, digest in hanging(base, head):
        left[digest].append(nid)
    for nid, digest in hanging(head, base):
        right[digest].append(nid)
    moves = {}
    for digest, ids in left.items():
        other = right.get(digest)
        if other and len(ids) == 1 and len(other) == 1:
            moves[ids[0]] = other[0]
    return moves


def _parents(side):
    return {n["id"]: n["parent_id"] for n in side.nodes.values() if n["kind"] == "concept"}


def _under(leaf, concept, parent):
    seen = set()
    while leaf and leaf not in seen:
        if leaf == concept:
            return True
        seen.add(leaf)
        leaf = parent.get(leaf)
    return False


def _raw_owners(side):
    """file id -> concept id, in this model's own ids."""
    out = {}
    for edge in sorted(side.by_kind["owns"], key=lambda e: (e["src"], e["dst"])):
        out.setdefault(edge["dst"], edge["src"])
    return out


def _owners(side, canon):
    """canonical file id -> concept id."""
    out = {}
    for edge in sorted(side.by_kind["owns"], key=lambda e: (e["src"], e["dst"])):
        out.setdefault(canon.get(edge["dst"], edge["dst"]), edge["src"])
    return out


def _winner(votes):
    """The concept id with the most votes. A tie takes the smaller id."""
    if not votes:
        return None
    best = max(votes.values())
    return sorted(cid for cid, count in votes.items() if count == best)[0]


def _provisional(base, head, canon, base_owner, head_owner):
    """New head files the base concepts do not own, with a provisional owner when one can be chosen.

    A file that already exists on the base is left alone, so a repo whose map never
    covered everything does not gain an owner for that history on every diff.
    """
    head_concepts = {n["id"] for n in head.nodes.values() if n["kind"] == "concept"}
    if not head_concepts:
        return []
    names = {n["id"]: n["name"] for n in head.nodes.values() if n["kind"] == "concept"}

    def owned(fid):
        canon_id = canon.get(fid, fid)
        cid = head_owner.get(canon_id)
        if cid in head_concepts:
            return cid
        cid = base_owner.get(canon_id)
        if cid in head_concepts:
            return cid
        return None

    candidates = []
    for node in head.nodes.values():
        if node["kind"] != "file" or node["attrs"].get("role") not in ("code", "test"):
            continue
        canon_id = canon.get(node["id"], node["id"])
        if head_owner.get(canon_id) or base_owner.get(canon_id) or node["id"] in base.nodes:
            continue
        candidates.append(node)
    if not candidates:
        return []

    neighbours = defaultdict(set)
    for edge in head.edges:
        if edge["kind"] != "imports":
            continue
        src, dst = head.nodes.get(edge["src"]), head.nodes.get(edge["dst"])
        left, right = _file_id(src), _file_id(dst)
        if left and right and left != right:
            neighbours[left].add(right)
            neighbours[right].add(left)
    by_folder = defaultdict(list)
    for node in head.nodes.values():
        if node["kind"] != "file":
            continue
        cid = owned(node["id"])
        if cid:
            by_folder[posixpath.dirname(node["path"])].append(cid)

    def folder_owner(path):
        folder = posixpath.dirname(path)
        seen = set()
        while folder not in seen:
            seen.add(folder)
            choice = _winner(Counter(by_folder.get(folder, ())))
            if choice:
                return choice
            if folder == "":
                return None
            folder = posixpath.dirname(folder)
        return None

    rows = []
    for node in sorted(candidates, key=lambda n: (n["path"], n["id"])):
        votes = Counter()
        for other in neighbours.get(node["id"], ()):
            cid = owned(other)
            if cid:
                votes[cid] += 1
        choice = _winner(votes)
        how = "imports" if choice else None
        if not choice:
            choice = folder_owner(node["path"])
            how = "folder" if choice else None
        rows.append({
            "file_id": node["id"], "path": node["path"], "concept_id": choice,
            "concept_name": names.get(choice) if choice else None, "by": how,
        })
    return rows


def _apply_provisional(head, head_owner, canon, rows):
    for row in rows:
        cid = row.get("concept_id")
        if not cid:
            continue
        edge = {"src": cid, "dst": row["file_id"], "kind": "owns", "weight": 1,
                "attrs": {"provisional": True}, "ordinal": 0}
        head.edges.append(edge)
        head.by_kind["owns"].append(edge)
        head_owner[canon.get(row["file_id"], row["file_id"])] = cid


def _file_id(node):
    if not node:
        return None
    if node["kind"] in ("file", "doc"):
        return node["id"]
    if node.get("workspace_id") and node.get("path"):
        return f"{node['workspace_id']}:{node['path']}"
    return node["id"].split("#", 1)[0] if "#" in node["id"] else None


def _test_file(node):
    return bool(node and (node["display_kind"] == "test file" or node["attrs"].get("role") == "test"))


def _qual(node):
    if "#" in node["id"]:
        return node["id"].split("#", 1)[1]
    return node["name"]


def _ref(node):
    return {"id": node["id"], "name": node["name"], "path": node.get("path") or "", "display_kind": node["display_kind"]}


def _node(ctx, nid):
    return ctx.head.nodes.get(nid) or ctx.base.nodes.get(nid)


def _name(ctx, nid):
    node = _node(ctx, nid)
    return node["name"] if node else nid


def _change(kind, summary, groups, before=None, after=None, code=None):
    return {"kind": kind, "summary": summary, "before": before, "after": after,
            "code": list(code or []), "groups": list(dict.fromkeys(g for g in groups if g))}


# --- concepts -------------------------------------------------------------------


def _file_sets(owner):
    sets = defaultdict(set)
    for fid, concept in owner.items():
        sets[concept].add(fid)
    return sets


def _concept_sets(base, head, base_owner, head_owner):
    """Rename map and the concepts explained by a split or a merge."""
    base_ids = {n["id"] for n in base.nodes.values() if n["kind"] == "concept"}
    head_ids = {n["id"] for n in head.nodes.values() if n["kind"] == "concept"}
    base_files, head_files = _file_sets(base_owner), _file_sets(head_owner)
    rename = {}
    base_by, head_by = defaultdict(list), defaultdict(list)
    for cid in base_ids - head_ids:
        if base_files.get(cid):
            base_by[frozenset(base_files[cid])].append(cid)
    for cid in head_ids - base_ids:
        if head_files.get(cid):
            head_by[frozenset(head_files[cid])].append(cid)
    for fileset in sorted(base_by, key=lambda s: (len(s), sorted(s))):
        bids, hids = base_by[fileset], head_by.get(fileset, [])
        if len(bids) == 1 and len(hids) == 1:
            rename[bids[0]] = hids[0]

    used_base, used_head = set(rename), set(rename.values())
    split_src, split_dst = {}, {}
    for cid in sorted(base_ids - head_ids - used_base, key=lambda c: (-len(base_files.get(c, ())), c)):
        fileset = base_files.get(cid) or set()
        if len(fileset) < 2:
            continue
        parts = [hid for hid in head_ids - base_ids - used_head if head_files.get(hid) and head_files[hid] <= fileset]
        union, overlap = set(), False
        for hid in parts:
            if union & head_files[hid]:
                overlap = True
                break
            union |= head_files[hid]
        if overlap or len(parts) < 2 or union != fileset:
            continue
        split_src[cid] = parts
        for hid in parts:
            split_dst[hid] = cid
        used_base.add(cid)
        used_head.update(parts)

    merge_src, merge_dst = {}, {}
    for cid in sorted(head_ids - base_ids - used_head, key=lambda c: (-len(head_files.get(c, ())), c)):
        fileset = head_files.get(cid) or set()
        if len(fileset) < 2:
            continue
        parts = [bid for bid in base_ids - head_ids - used_base if base_files.get(bid) and base_files[bid] <= fileset]
        union, overlap = set(), False
        for bid in parts:
            if union & base_files[bid]:
                overlap = True
                break
            union |= base_files[bid]
        if overlap or len(parts) < 2 or union != fileset:
            continue
        merge_dst[cid] = parts
        for bid in parts:
            merge_src[bid] = cid
        used_base.add(cid)  # the head id is not a base id; the parts are
        used_base.update(parts)
        used_head.add(cid)
    return rename, split_src, split_dst, merge_src, merge_dst


def _concept_names(side):
    return {n["id"]: n["name"] for n in side.nodes.values() if n["kind"] == "concept"}


def _concept_changes(ctx):
    base_ids = {n["id"] for n in ctx.base.nodes.values() if n["kind"] == "concept"}
    head_ids = {n["id"] for n in ctx.head.nodes.values() if n["kind"] == "concept"}
    base_name, head_name = _concept_names(ctx.base), _concept_names(ctx.head)
    out = []
    for cid in sorted(base_ids & head_ids):
        if base_name[cid] != head_name[cid]:
            out.append(_change(
                "concept-renamed", f"{base_name[cid]} -> {head_name[cid]}", [cid],
                before={"id": cid, "name": base_name[cid]}, after={"id": cid, "name": head_name[cid]},
                code=_owned_refs(ctx.head, cid),
            ))
    for src, dst in sorted(ctx.rename.items()):
        left, right = base_name[src], head_name[dst]
        summary = f"{left} -> {right}" if left != right else f"{left}  {src} -> {dst}"
        out.append(_change(
            "concept-renamed", summary, [dst],
            before={"id": src, "name": left}, after={"id": dst, "name": right},
            code=_owned_refs(ctx.head, dst),
        ))
    for src, parts in sorted(ctx.split_src.items()):
        named = sorted(({"id": pid, "name": head_name[pid]} for pid in parts), key=lambda n: (n["name"], n["id"]))
        out.append(_change(
            "concept-split", f"{base_name[src]} -> {', '.join(n['name'] for n in named)}", [src],
            before={"id": src, "name": base_name[src]}, after=named, code=_owned_refs(ctx.base, src),
        ))
    for dst, parts in sorted(ctx.merge_dst.items()):
        named = sorted(({"id": pid, "name": base_name[pid]} for pid in parts), key=lambda n: (n["name"], n["id"]))
        out.append(_change(
            "concept-merged", f"{', '.join(n['name'] for n in named)} -> {head_name[dst]}", [dst],
            before=named, after={"id": dst, "name": head_name[dst]}, code=_owned_refs(ctx.head, dst),
        ))
    explained_base = set(ctx.rename) | set(ctx.split_src) | set(ctx.merge_src)
    explained_head = set(ctx.rename.values()) | set(ctx.split_dst) | set(ctx.merge_dst)
    for cid in sorted(head_ids - base_ids - explained_head):
        out.append(_change(
            "concept-added", head_name[cid], [cid],
            after={"id": cid, "name": head_name[cid]}, code=_owned_refs(ctx.head, cid),
        ))
    for cid in sorted(base_ids - head_ids - explained_base):
        out.append(_change(
            "concept-removed", base_name[cid], [cid],
            before={"id": cid, "name": base_name[cid]}, code=_owned_refs(ctx.base, cid),
        ))
    return out


def _owned_refs(side, concept):
    refs = [_ref(side.nodes[e["dst"]]) for e in side.by_kind["owns"]
            if e["src"] == concept and e["dst"] in side.nodes]
    return sorted(refs, key=lambda r: (r["path"], r["name"], r["id"]))


def _ownership_moves(ctx):
    out = []
    seen = set()
    for fid, concept in sorted(ctx.base_owner.items()):
        head_concept = ctx.head_owner.get(fid)
        if not head_concept:
            continue
        translated = ctx.rename.get(concept, concept)
        if translated == head_concept:
            continue
        if concept in ctx.split_src or head_concept in ctx.split_dst:
            continue
        if concept in ctx.merge_src or head_concept in ctx.merge_dst:
            continue
        if (fid, concept, head_concept) in seen:
            continue
        seen.add((fid, concept, head_concept))
        node = _file_node(ctx, fid)
        path = node["path"] if node else fid
        out.append(_change(
            "file-moved-concept",
            f"{path}  {_name(ctx, concept)} -> {_name(ctx, head_concept)}",
            [translated, head_concept],
            before={"id": concept, "name": _name(ctx, concept), "path": path},
            after={"id": head_concept, "name": _name(ctx, head_concept), "path": path},
            code=[_ref(node)] if node else [],
        ))
    return out


def _file_node(ctx, canon_id):
    head_id = _head_file(ctx, canon_id)
    if head_id and head_id in ctx.head.nodes:
        return ctx.head.nodes[head_id]
    return ctx.base.nodes.get(canon_id)


def _head_file(ctx, canon_id):
    for src, dst in ctx.file_moves.items():
        if src == canon_id:
            return dst
    if canon_id in ctx.head.nodes:
        return canon_id
    return None


def _path_moves(ctx):
    out = []
    for src, dst in sorted(ctx.file_moves.items()):
        left, right = ctx.base.nodes[src], ctx.head.nodes[dst]
        out.append(_change(
            "file-moved", f"{left['path']} -> {right['path']}", _place(ctx, src, dst),
            before={"id": src, "path": left["path"]}, after={"id": dst, "path": right["path"]},
            code=[_ref(right)],
        ))
    return out


# --- relationships, deployables, env --------------------------------------------


def _leaf_volume(side, owners):
    totals = defaultdict(lambda: {"calls": 0, "imports": 0})
    for edge in side.edges:
        if edge["kind"] not in ("imports", "calls"):
            continue
        src, dst = side.nodes.get(edge["src"]), side.nodes.get(edge["dst"])
        sf, df = _file_id(src), _file_id(dst)
        if _test_file(side.nodes.get(sf)) or _test_file(side.nodes.get(df)):
            continue
        sl, dl = owners.get(sf), owners.get(df)
        if not sl or not dl or sl == dl:
            continue
        totals[(sl, dl)]["calls" if edge["kind"] == "calls" else "imports"] += edge["weight"]
    return totals


def _rollup(totals, parents, src, dst):
    calls = imports = 0
    for (left, right), counts in totals.items():
        if _under(left, src, parents) and _under(right, dst, parents):
            calls += counts["calls"]
            imports += counts["imports"]
    return calls, imports


def _crossing(side, parents, src, dst, owners):
    refs, seen = [], set()
    for edge in side.edges:
        if edge["kind"] not in ("imports", "calls"):
            continue
        snode, dnode = side.nodes.get(edge["src"]), side.nodes.get(edge["dst"])
        sf, df = _file_id(snode), _file_id(dnode)
        if _test_file(side.nodes.get(sf)) or _test_file(side.nodes.get(df)):
            continue
        sl, dl = owners.get(sf), owners.get(df)
        if not sl or not dl or not _under(sl, src, parents) or not _under(dl, dst, parents):
            continue
        if snode and snode["id"] not in seen:
            seen.add(snode["id"])
            refs.append(_ref(snode))
    return sorted(refs, key=lambda r: (r["path"], r["name"], r["id"]))


def _rel_index(side, translate):
    found = {}
    for edge in side.by_kind["relates"]:
        key = (translate(edge["src"]), translate(edge["dst"]), edge["attrs"].get("label") or "")
        found.setdefault(key, edge)
    return found


def _mechanism(attrs):
    return attrs.get("via") or attrs.get("mechanism") or ""


def _is_integration(edge, nodes):
    if edge["attrs"].get("integration"):
        return True
    return any(nodes.get(end, {}).get("kind") == "external" for end in (edge["src"], edge["dst"]))


def _rel_record(src, dst, label, calls, imports):
    return {"from": src, "to": dst, "label": label, "calls": calls, "imports": imports}


def _int_record(src, dst, label, attrs):
    return {"from": src, "to": dst, "label": label, "mechanism": _mechanism(attrs), "at": attrs.get("at") or ""}


def _relationship_changes(ctx):
    translate = lambda nid: ctx.rename.get(nid, nid)
    base_rels = _rel_index(ctx.base, translate)
    head_rels = _rel_index(ctx.head, lambda nid: nid)
    out = []
    for key in sorted(set(base_rels) | set(head_rels)):
        src, dst, label = key
        left, right = base_rels.get(key), head_rels.get(key)
        # Volume on the base uses the ids stored on that side, before the rename map.
        b_src = left["src"] if left else src
        b_dst = left["dst"] if left else dst
        b_calls, b_imports = _rollup(ctx.base_volume, ctx.base_parents, b_src, b_dst) if left else (0, 0)
        h_calls, h_imports = _rollup(ctx.head_volume, ctx.head_parents, src, dst) if right else (0, 0)
        integrated = (left and _is_integration(left, ctx.base.nodes)) or (right and _is_integration(right, ctx.head.nodes))
        groups = _rel_groups(ctx, src, dst)
        arrow = f"{_name(ctx, src)} -> {_name(ctx, dst)}  {label}".rstrip()
        if left and right:
            if integrated and (_mechanism(left["attrs"]) != _mechanism(right["attrs"]) or (left["attrs"].get("at") or "") != (right["attrs"].get("at") or "")):
                out.append(_change(
                    "integration-changed",
                    f"{arrow}  {_mechanism(left['attrs']) or '—'} -> {_mechanism(right['attrs']) or '—'}"
                    + (f"  at {left['attrs'].get('at') or '—'} -> {right['attrs'].get('at') or '—'}"
                       if (left["attrs"].get("at") or "") != (right["attrs"].get("at") or "") else ""),
                    groups, before=_int_record(src, dst, label, left["attrs"]),
                    after=_int_record(src, dst, label, right["attrs"]),
                    code=_crossing(ctx.head, ctx.head_parents, src, dst, _raw_owners(ctx.head)),
                ))
            if (b_calls, b_imports) != (h_calls, h_imports):
                out.append(_change(
                    "relationship-volume",
                    f"{arrow}  calls {b_calls} -> {h_calls}  imports {b_imports} -> {h_imports}",
                    groups, before=_rel_record(src, dst, label, b_calls, b_imports),
                    after=_rel_record(src, dst, label, h_calls, h_imports),
                    code=_crossing(ctx.head, ctx.head_parents, src, dst, _raw_owners(ctx.head)),
                ))
        elif right:
            kind = "integration-added" if integrated else "relationship-added"
            record = _int_record(src, dst, label, right["attrs"]) if integrated else _rel_record(src, dst, label, h_calls, h_imports)
            extra = f"  {_mechanism(right['attrs'])}" if integrated and _mechanism(right["attrs"]) else ""
            if not integrated:
                extra = f"  calls {h_calls}  imports {h_imports}"
            out.append(_change(
                kind, f"{arrow}{extra}", groups, after=record,
                code=_crossing(ctx.head, ctx.head_parents, src, dst, _raw_owners(ctx.head)),
            ))
        else:
            kind = "integration-removed" if integrated else "relationship-removed"
            record = _int_record(src, dst, label, left["attrs"]) if integrated else _rel_record(src, dst, label, b_calls, b_imports)
            extra = f"  {_mechanism(left['attrs'])}" if integrated and _mechanism(left["attrs"]) else ""
            if not integrated:
                extra = f"  calls {b_calls}  imports {b_imports}"
            out.append(_change(
                kind, f"{arrow}{extra}", groups, before=record,
                code=_crossing(ctx.base, ctx.base_parents, b_src, b_dst, _raw_owners(ctx.base)),
            ))
    return out


def _rel_groups(ctx, src, dst):
    groups = []
    for nid in (src, dst):
        node = _node(ctx, nid)
        if node and node["kind"] == "concept":
            groups.append(nid)
            break
    return groups or _place(ctx, None, None)


def _node_kind_changes(ctx, kind):
    base = {n["id"]: n for n in ctx.base.nodes.values() if n["kind"] == kind}
    head = {n["id"]: n for n in ctx.head.nodes.values() if n["kind"] == kind}
    out = []
    for nid in sorted(set(head) - set(base)):
        out.append(_change(f"{kind}-added", head[nid]["name"], [nid], after={"id": nid, "name": head[nid]["name"]}))
    for nid in sorted(set(base) - set(head)):
        out.append(_change(f"{kind}-removed", base[nid]["name"], [nid], before={"id": nid, "name": base[nid]["name"]}))
    return out


def _depends_changes(ctx):
    def keys(side):
        return {(e["src"], e["dst"]) for e in side.by_kind["depends_on"]}
    base, head = keys(ctx.base), keys(ctx.head)
    out = []
    for src, dst in sorted(head - base):
        out.append(_change("depends-on-added", _dep_summary(ctx, src, dst), [src], after={"from": src, "to": dst}))
    for src, dst in sorted(base - head):
        out.append(_change("depends-on-removed", _dep_summary(ctx, src, dst), [src], before={"from": src, "to": dst}))
    return out


def _dep_summary(ctx, src, dst):
    def bit(nid):
        node = _node(ctx, nid)
        if not node:
            return nid
        return f"{node['display_kind']} {node['name']}"
    return f"{bit(src)} -> {bit(dst)}"


def _env_names(side):
    found = defaultdict(list)
    for edge in side.by_kind["reads_env"]:
        node = side.nodes.get(edge["dst"])
        if node:
            found[node["name"]].append(edge["src"])
    return found


def _env_changes(ctx):
    base, head = _env_names(ctx.base), _env_names(ctx.head)
    out = []
    for name in sorted(set(head) - set(base)):
        readers = [_node_ref(ctx.head, nid) for nid in head[name]]
        readers = [r for r in readers if r]
        out.append(_change(
            "env-read", name, _reader_groups(ctx, head[name], "head"),
            after={"name": name}, code=sorted(readers, key=lambda r: (r["path"], r["name"], r["id"])),
        ))
    for name in sorted(set(base) - set(head)):
        readers = [r for r in (_node_ref(ctx.base, nid) for nid in base[name]) if r]
        out.append(_change(
            "env-unread", name, _reader_groups(ctx, base[name], "base"),
            before={"name": name}, code=sorted(readers, key=lambda r: (r["path"], r["name"], r["id"])),
        ))
    return out


def _node_ref(side, nid):
    node = side.nodes.get(nid)
    return _ref(node) if node else None


def _reader_groups(ctx, readers, which):
    groups = []
    side = ctx.head if which == "head" else ctx.base
    owners = ctx.head_owner if which == "head" else ctx.base_owner
    for nid in readers:
        node = side.nodes.get(nid)
        fid = _file_id(node)
        if not fid:
            continue
        canon = ctx.canon.get(fid, fid)
        owner = owners.get(canon)
        if ctx.concept_mode and owner:
            groups.append(ctx.rename.get(owner, owner) if which == "base" else owner)
        else:
            groups.append(_container(side, fid))
    return groups


# --- symbols, tests, renders ----------------------------------------------------


def _symbol_changes(ctx):
    out = []
    for src, dst in sorted(ctx.symbol_moves.items(), key=lambda item: item[0]):
        left, right = ctx.base.nodes[src], ctx.head.nodes[dst]
        out.append(_change(
            "symbol-moved", f"{left['path']}#{_qual(left)} -> {right['path']}#{_qual(right)}",
            _place(ctx, src.split("#", 1)[0], dst.split("#", 1)[0]),
            before={"id": src, "name": left["name"], "path": left["path"], "signature": left["signature"]},
            after={"id": dst, "name": right["name"], "path": right["path"], "signature": right["signature"]},
            code=[_ref(left), _ref(right)],
        ))
    both = set(ctx.base.nodes) & set(ctx.head.nodes)
    moved_from, moved_to = set(ctx.symbol_moves), set(ctx.symbol_moves.values())
    for nid in sorted(set(ctx.base.nodes) - set(ctx.head.nodes)):
        node = ctx.base.nodes[nid]
        if node["kind"] != "symbol" or nid in moved_from:
            continue
        out.append(_change(
            "symbol-removed", f"{node['path']}#{_qual(node)}", _place(ctx, _file_id(node), None),
            before={"id": nid, "name": node["name"], "path": node["path"], "display_kind": node["display_kind"]},
            code=[_ref(node)],
        ))
    for nid in sorted(set(ctx.head.nodes) - set(ctx.base.nodes)):
        node = ctx.head.nodes[nid]
        if node["kind"] != "symbol" or nid in moved_to:
            continue
        out.append(_change(
            "symbol-added", f"{node['path']}#{_qual(node)}", _place(ctx, None, _file_id(node)),
            after={"id": nid, "name": node["name"], "path": node["path"], "display_kind": node["display_kind"]},
            code=[_ref(node)],
        ))
    for nid in sorted(both):
        left, right = ctx.base.nodes[nid], ctx.head.nodes[nid]
        if left["kind"] != "symbol":
            continue
        sig = left["signature"] != right["signature"]
        body = (left["content_hash"] or "") != (right["content_hash"] or "")
        if not sig and not body:
            continue
        what = "+".join(part for part, flag in (("signature", sig), ("body", body)) if flag)
        out.append(_change(
            "symbol-changed", f"{what}  {right['path']}#{_qual(right)}",
            _place(ctx, _file_id(left), _file_id(right)),
            before={"signature": left["signature"], "body": left["content_hash"]},
            after={"signature": right["signature"], "body": right["content_hash"]},
            code=[_ref(right)],
        ))
    return out


def _test_changes(ctx):
    out = []
    moved_from, moved_to = set(ctx.test_moves), set(ctx.test_moves.values())
    for nid in sorted(set(ctx.base.nodes) - set(ctx.head.nodes)):
        node = ctx.base.nodes[nid]
        if node["kind"] != "test" or nid in moved_from:
            continue
        out.append(_change(
            "test-removed", f"{node['path']}#{_qual(node)}", _place(ctx, _file_id(node), None),
            before={"id": nid, "name": node["name"], "path": node["path"]}, code=[_ref(node)],
        ))
    for nid in sorted(set(ctx.head.nodes) - set(ctx.base.nodes)):
        node = ctx.head.nodes[nid]
        if node["kind"] != "test" or nid in moved_to:
            continue
        out.append(_change(
            "test-added", f"{node['path']}#{_qual(node)}", _place(ctx, None, _file_id(node)),
            after={"id": nid, "name": node["name"], "path": node["path"]}, code=[_ref(node)],
        ))
    return out


def _tested(side):
    hits = {e["dst"] for e in side.by_kind["tests"]}
    def linked(node):
        current = node
        seen = set()
        while current and current["id"] not in seen:
            if current["id"] in hits:
                return True
            seen.add(current["id"])
            current = side.nodes.get(current["parent_id"]) if current.get("parent_id") else None
        fid = _file_id(node)
        return bool(fid and fid in hits)
    return linked


def _untested(ctx, changes):
    linked = _tested(ctx.head)
    out = []
    seen = set()
    for change in changes:
        if change["kind"] != "symbol-changed":
            continue
        for ref in change["code"]:
            node = ctx.head.nodes.get(ref["id"])
            if not node or node["id"] in seen or linked(node):
                continue
            seen.add(node["id"])
            out.append(_change(
                "untested", f"{node['path']}#{_qual(node)}", change["groups"],
                after={"id": node["id"], "name": node["name"], "path": node["path"]}, code=[_ref(node)],
            ))
    return out


def _render_changes(ctx):
    def ends(side, translate):
        found = set()
        for edge in side.by_kind["calls"]:
            if edge["attrs"].get("via") != "jsx":
                continue
            src = side.nodes.get(edge["src"])
            if not src or src["display_kind"] != "component":
                continue
            found.add((translate(edge["src"]), translate(edge["dst"])))
        return found
    translate = lambda nid: ctx.symbol_moves.get(nid, nid)
    base, head = ends(ctx.base, translate), ends(ctx.head, lambda nid: nid)
    out = []
    for src, dst in sorted(head - base):
        out.append(_render(ctx, "render-added", src, dst, after=True))
    for src, dst in sorted(base - head):
        out.append(_render(ctx, "render-removed", src, dst, after=False))
    return [item for item in out if item]


def _render(ctx, kind, src, dst, after):
    snode, dnode = _node(ctx, src), _node(ctx, dst)
    if not snode or not dnode:
        return None
    record = {"from": src, "to": dst}
    summary = f"{snode['path']}#{_qual(snode)} -> {dnode['path']}#{_qual(dnode)}"
    return _change(
        kind, summary, _place(ctx, _file_id(snode), _file_id(dnode)),
        before=None if after else record, after=record if after else None,
        code=[_ref(snode), _ref(dnode)],
    )


def _place(ctx, base_file, head_file):
    """Concept ids that own these files, or a deployable, package or folder."""
    groups = []
    if ctx.concept_mode:
        if base_file:
            owner = ctx.base_owner.get(ctx.canon.get(base_file, base_file))
            if owner:
                groups.append(ctx.rename.get(owner, owner))
        if head_file:
            owner = ctx.head_owner.get(ctx.canon.get(head_file, head_file))
            if owner:
                groups.append(owner)
        if groups:
            return groups
    if base_file:
        groups.append(_container(ctx.base, base_file))
    if head_file:
        groups.append(_container(ctx.head, head_file))
    return groups


def _container(side, fid):
    if fid not in side.nodes:
        return None
    targets = []
    for edge in side.by_kind["part_of"]:
        if edge["src"] == fid and edge["dst"] in side.nodes:
            targets.append(side.nodes[edge["dst"]])
    deployables = sorted(n["id"] for n in targets if n["kind"] == "deployable")
    if deployables:
        return deployables[0]
    packages = sorted(n["id"] for n in targets if n["kind"] == "package")
    if packages:
        return packages[0]
    parent = side.nodes[fid].get("parent_id")
    if parent and side.nodes.get(parent, {}).get("kind") == "group":
        return parent
    return fid


# --- group and render -----------------------------------------------------------


def _group(ctx, changes):
    buckets = defaultdict(list)
    for change in changes:
        public = {key: change[key] for key in _PUBLIC}
        homes = change["groups"] or ["(ungrouped)"]
        for gid in dict.fromkeys(homes):
            buckets[gid].append(public)
    groups = []
    for gid, items in buckets.items():
        items.sort(key=lambda ch: (RANK.get(ch["kind"], 999), ch["summary"], json.dumps(ch["before"], sort_keys=True, default=str)))
        node = _node(ctx, gid)
        if node and node["kind"] == "concept":
            gkind = "concept"
        elif node and node["kind"] in ("deployable", "package"):
            gkind = node["kind"]
        else:
            gkind = "folder"
        groups.append({"id": gid, "name": node["name"] if node else gid, "kind": gkind, "changes": items})
    groups.sort(key=lambda g: (min(RANK.get(c["kind"], 999) for c in g["changes"]), g["name"].lower(), g["id"]))
    grouping = "concept" if ctx.concept_mode else "deployable"
    return {"grouping": grouping, "groups": groups}


def _filter(result, concept):
    if not concept:
        return result
    groups = []
    for group in result["groups"]:
        if group["id"] == concept:
            groups.append(group)
            continue
        kept = [change for change in group["changes"] if concept in _ids(change)]
        if kept:
            groups.append({**group, "changes": kept})
    out = {"grouping": result["grouping"], "groups": groups}
    rows = [row for row in result.get("provisional") or [] if row.get("concept_id") == concept]
    if rows:
        out["provisional"] = rows
    return out


def _ids(value):
    found = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in ("id", "from", "to") and isinstance(item, str):
                found.append(item)
            found.extend(_ids(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_ids(item))
    return found


def _provisional_lines(result):
    rows = result.get("provisional") or []
    lines = []
    for row in rows:
        if row.get("concept_id"):
            lines.append(f"{row['path']}  {row['concept_name']}  {row['by']}")
        else:
            lines.append(f"{row['path']}  (no owner)")
    return lines


def _text(result):
    if not result["groups"]:
        body = "no architectural changes"
    else:
        blocks = []
        for group in result["groups"]:
            lines = [f"{group['id']}  {group['name']}"]
            for change in group["changes"]:
                lines.append(f"  {change['kind']}  {change['summary']}")
                for code in change["code"]:
                    lines.append(f"    {code['path'] or code['id']}  {code['name']}")
            blocks.append("\n".join(lines))
        body = "\n\n".join(blocks)
    extra = _provisional_lines(result)
    if extra:
        body += "\n\nprovisional\n" + "\n".join(f"  {line}" for line in extra)
    return body + "\n"


def _markdown(result):
    lines = ["# structural diff", ""]
    if not result["groups"]:
        lines.append("no architectural changes")
        lines.append("")
    for group in result["groups"]:
        lines.append(f"## {group['id']}  {group['name']}")
        lines.append("")
        for change in group["changes"]:
            lines.append(f"- {change['kind']}  {change['summary']}")
            for code in change["code"]:
                lines.append(f"  - {code['path'] or code['id']}  {code['name']}")
        lines.append("")
    extra = _provisional_lines(result)
    if extra:
        lines.append("## Provisional")
        lines.append("")
        lines.extend(f"- {line}" for line in extra)
        lines.append("")
    return "\n".join(lines)

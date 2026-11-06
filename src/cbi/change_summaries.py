"""Grounded, agent-authored explanations shared by every comparison surface."""

import hashlib
import json
from pathlib import Path

from cbi import change_overview, store
from cbi.task_cache import _cached_answer, attach_cache

KIND = "summarise-architecture-change"
VERSION = 3
INSTRUCTIONS = (
    "Use only the supplied diff facts, ranked overview and direct relationship context. "
    "Write one plain-language paragraph explaining what changed, why it matters, who or what "
    "it affects (callers/users), and risk. Mark inferences as inferences; when intent, user impact "
    "or risk is unknown, say so. Do not invent motivation or claim tests prove safety. "
    "Cite the symbol IDs or file paths you rely on in citations, copied exactly from the allowed "
    "citations list. Do not read extra source or use outside facts. Copy input_hash."
)
ANSWER_SCHEMA = {
    "type": "object", "required": ["input_hash", "narrative", "citations"],
    "additionalProperties": False,
    "properties": {
        "input_hash": {"type": "string"},
        "narrative": {"type": "string", "minLength": 1, "maxLength": 2400},
        "citations": {"type": "array", "minItems": 1,
                      "items": {"type": "string", "minLength": 1}},
    },
}


def model_hash(conn):
    """Hash semantic model content, independent of rebuild time and task/answer state."""
    digest = hashlib.sha256()
    for query in (
        "SELECT id,parent_id,kind,display_kind,name,workspace_id,path,start_line,end_line,"
        "lang,loc,content_hash,signature,doc,attrs FROM nodes ORDER BY id",
        "SELECT src,dst,kind,source,confidence,weight,attrs,ordinal FROM edges "
        "ORDER BY src,dst,kind,source,ordinal",
    ):
        for row in conn.execute(query):
            digest.update(json.dumps(list(row), ensure_ascii=True).encode())
            digest.update(b"\n")
    return digest.hexdigest()


def change_hash(base_model_hash, head_model_hash, concept_id=None, evidence=None):
    return hashlib.sha256(json.dumps(
        [VERSION, KIND, base_model_hash, head_model_hash, concept_id, evidence], sort_keys=True
    ).encode()).hexdigest()


def citations(value):
    """Only file paths and node IDs actually carried in this task's diff/context."""
    found = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key in ("id", "path", "old_path", "from", "to", "file_id") and isinstance(item, str) and item:
                found.add(item)
            found.update(citations(item))
    elif isinstance(value, list):
        for item in value:
            found.update(citations(item))
    return found


def problems(task, answer):
    allowed = set(task["inputs"].get("citations") or [])
    return [f"$.citations[{i}]: {item!r} is not in this diff's evidence"
            for i, item in enumerate(answer["citations"]) if item not in allowed]


def _writer(head):
    path = next((row[2] for row in head.execute("PRAGMA database_list") if row[1] == "main"), "")
    if not path:
        return head, False
    path = Path(path)
    # Comparisons' tasks belong to the ordinary task inbox, not a hidden ref-only inbox.
    if path.parent.parent.name == "refs":
        out = path.parents[2]
        if (out / "model.db").is_file():
            path = out / "model.db"
        else:
            (out / "refs" / "comparison-inbox.json").write_text(json.dumps({"head": path.parent.name}) + "\n", encoding="utf-8")
    return store.open_db(path), True


def _workspace(conn):
    row = conn.execute(
        "SELECT id, name, summary FROM nodes WHERE kind = 'workspace' AND parent_id IS NULL ORDER BY id LIMIT 1"
    ).fetchone()
    return {"id": row[0], "name": row[1], "summary": row[2]} if row else None


def enrich(base, head, result):
    """Open one task per changed concept plus the whole diff, and attach cached answers."""
    base_hash, head_hash = model_hash(base), model_hash(head)
    groups = {g["id"]: g for g in result.get("groups", [])}
    items = {g["id"]: g for g in result.get("overview", {}).get("items", [])}
    parent_models, nodes, owners = [], {}, {}
    for model in (base, head):
        nodes.update({row[0]: {"kind": row[1], "path": row[2], "name": row[3]}
                      for row in model.execute("SELECT id,kind,path,name FROM nodes")})
        parent_models.append(dict(model.execute("SELECT id,parent_id FROM nodes WHERE kind='concept'")))
        for owner, fid in model.execute("SELECT src,dst FROM edges WHERE kind='owns'"):
            owners.setdefault(fid, set()).add(owner)

    def ancestors(cid):
        seen = set()
        for parents in parent_models:
            current, visited = cid, set()
            while current in parents and current not in visited:
                visited.add(current)
                seen.add(current)
                current = parents[current]
        return seen

    def file_concepts(file):
        found = set()
        for fid in (file["id"], file.get("canonical_id")):
            for owner in owners.get(fid, ()):
                found.update(ancestors(owner))
        return found

    changed_files = [f for item in items.values() for module in item.get("modules", [])
                     for f in module.get("files", [])]
    # A structural edit can change ownership/hierarchy with identical source bytes.
    # Discover every participant, and preserve ancestors from both sides of a move.
    change_scopes = {}
    ids = set(groups) | set(items)
    for group in groups.values():
        for change in group["changes"]:
            participants = {group["id"]}
            for side in ("before", "after"):
                participants.update(nid for nid in citations(change.get(side))
                                    if nodes.get(nid, {}).get("kind") == "concept")
            scopes = set(participants)
            for participant in participants:
                scopes.update(ancestors(participant))
            key = json.dumps(change, sort_keys=True)
            change_scopes.setdefault(key, set()).update(scopes)
            ids.update(scopes)
    for file in changed_files:
        ids.update(file_concepts(file))
    ids = sorted(ids)
    references = {nid for nid, node in nodes.items() if node["kind"] in ("file", "doc", "symbol", "test")}
    references.update(node["path"] for node in nodes.values()
                      if node["kind"] in ("file", "doc", "symbol", "test") and node["path"])

    def ranked_context(cid):
        if cid in items:
            return items[cid]
        scoped = []
        for rank, item in enumerate(items.values(), 1):
            modules = []
            for module in item.get("modules", []):
                files = [f for f in module.get("files", []) if cid in file_concepts(f)]
                if files:
                    measures = change_overview._measure()
                    for file in files:
                        change_overview._roll(measures, file["measures"])
                    modules.append({**module, "files": files, "measures": measures,
                                    "relationships": change_overview._module_context({"files": files})})
            if modules:
                scoped.append({"rank": rank, "modules": modules})
        return {"id": cid, "name": nodes.get(cid, {}).get("name", cid), "ranked_modules": scoped}
    if not ids:
        result["summaries"] = {"overall": None, "concepts": {}}
        return result
    conn, owned = _writer(head)
    try:
        if not any(row[1] == "cache" for row in conn.execute("PRAGMA database_list")):
            attach_cache(conn)
        workspace = _workspace(conn)
        summaries = {"overall": None, "concepts": {}}
        with conn:
            for cid in [None, *ids]:
                scoped_groups = []
                for group in groups.values():
                    changes = [change for change in group["changes"] if cid is None or cid in
                               change_scopes[json.dumps(change, sort_keys=True)]]
                    if changes:
                        scoped_groups.append({**group, "changes": changes})
                facts = {"groups": scoped_groups,
                         "overview": result.get("overview", {}) if cid is None else ranked_context(cid)}
                allowed = sorted(citations(facts) & references)
                if not allowed:
                    # Pure concept/relationship edits may have no changed source. Supply their
                    # owning files as explicit model context so the citation still names code.
                    selected_ids = set(groups) | set(items) if cid is None else {cid}
                    supporting = [{"id": fid, "path": nodes[fid]["path"]}
                                  for fid, homes in owners.items() if fid in nodes
                                  and any(selected_ids & ancestors(home) for home in homes)]
                    facts["ownership_context"] = supporting
                    allowed = sorted(citations(supporting) & references)
                if not allowed:
                    # Empty concepts have no symbols or files; require an explicit structural
                    # reference rather than pretending there is source evidence.
                    facts["structural_only"] = True
                    allowed = sorted(citations(facts))
                digest = change_hash(base_hash, head_hash, cid, facts)
                task_id = "sac-" + digest[:16]
                answer = _cached_answer(conn, digest)
                accepted = isinstance(answer, dict) and answer.get("narrative") and answer.get("citations")
                if accepted and not set(answer["citations"]).issubset(allowed):
                    accepted = False
                state = "done" if accepted else "open"
                inputs = {"base_model_hash": base_hash, "head_model_hash": head_hash,
                          "concept_id": cid, "changes": facts, "citations": allowed}
                conn.execute(
                    "INSERT INTO tasks(id,kind,node_id,input_hash,state,depends_on,inputs) VALUES(?,?,?,?,?,'[]',?) "
                    "ON CONFLICT(id) DO UPDATE SET state=excluded.state, inputs=excluded.inputs",
                    (task_id, KIND, workspace["id"] if workspace else None, digest, state, json.dumps(inputs)),
                )
                entry = {"state": "answered" if accepted else "pending", "task_id": task_id,
                         "input_hash": digest, "evidence_citations": allowed,
                         "narrative": answer["narrative"] if accepted else None,
                         "citations": answer["citations"] if accepted else []}
                if cid is None:
                    summaries["overall"] = entry
                else:
                    summaries["concepts"][cid] = entry
        result["summaries"] = summaries
    finally:
        if owned:
            conn.close()
    return result


def refresh(conn, result):
    """Reload answers without recomputing the structural diff or opening old models.

    The persisted hash identifies the immutable model pair/scope. Its evidence list
    preserves the same grounding boundary even if rebuilding removed the task rows.
    Older payloads can recover that metadata from their original task inbox;
    when neither scoped evidence nor the task survives, they remain pending.
    """
    summaries = result.get("summaries") or {}
    entries = [summaries.get("overall"), *summaries.get("concepts", {}).values()]
    changed = False
    has_cache = any(row[1] == "cache" for row in conn.execute("PRAGMA database_list"))
    for entry in entries:
        if not entry:
            continue
        before = dict(entry)
        digest = entry.get("input_hash")
        allowed = entry.get("evidence_citations")
        if not digest or allowed is None:
            row = conn.execute("SELECT input_hash, inputs FROM tasks WHERE id = ?",
                               (entry.get("task_id"),)).fetchone()
            if row:
                digest = row[0]
                allowed = json.loads(row[1]).get("citations", [])
        if digest and allowed is not None:
            entry.update(input_hash=digest, evidence_citations=allowed)
        answer = _cached_answer(conn, digest) if has_cache and digest else None
        accepted = (isinstance(answer, dict) and answer.get("narrative") and answer.get("citations")
                    and allowed is not None and set(answer["citations"]).issubset(allowed))
        entry.update(state="answered" if accepted else "pending",
                     narrative=answer["narrative"] if accepted else None,
                     citations=answer["citations"] if accepted else [])
        changed |= entry != before
    return changed


def render(result, concept=None, markdown=False):
    summaries = result.get("summaries")
    if not summaries:
        return ""
    selected = [(concept, summaries["concepts"].get(concept))] if concept else [
        (None, summaries.get("overall")), *summaries["concepts"].items()]
    names = {g["id"]: g["name"] for g in result.get("overview", {}).get("items", [])}
    names.update({g["id"]: g["name"] for g in result.get("groups", [])})
    lines = []
    for cid, entry in selected:
        if entry is None:
            continue
        title = names.get(cid, cid) if cid else "Whole diff"
        lines += [f"{'## ' if markdown else ''}Architecture summary: {title}", ""]
        if entry["state"] == "answered":
            lines += [entry["narrative"], "", "Evidence: " + ", ".join(entry["citations"]), ""]
        else:
            lines += ["Summary pending: run cbi tasks", ""]
    return "\n".join(lines) + ("\n" if lines else "")

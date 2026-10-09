"""Architecture history from immutable models of the default branch."""

import copy
import datetime as dt
import hashlib
import json
import posixpath
import re
import shutil
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

from cbi import diff, review, store, tasks

VERSION = 1
DEFAULT_DAYS = 183
PR_RE = re.compile(r"(?:Merge pull request #|\(#)(\d+)\)?")


class HistoryError(Exception):
    def __init__(self, message, code=1):
        super().__init__(message)
        self.code = code


def _git(root, *args, check=True):
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
    if check and result.returncode:
        raise HistoryError((result.stderr or result.stdout or "git failed").strip())
    return result


def default_branch(root):
    remote = _git(root, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD", check=False)
    if remote.returncode == 0 and remote.stdout.strip():
        return remote.stdout.strip()
    for name in ("main", "master"):
        if _git(root, "rev-parse", "--verify", "--quiet", f"{name}^{{commit}}", check=False).returncode == 0:
            return name
    raise HistoryError("cannot find the default branch (tried origin/HEAD, main and master)")


def history_points(root, since=None, until=None):
    """Return default-branch history points oldest first."""
    branch = default_branch(root)
    common = ["log", "--first-parent", "--format=%H%x00%P%x00%cI%x00%an%x00%s"]
    if since:
        common.append(f"--since={since}")
    if until:
        common.append(f"--until={until}")
    merged = _git(root, *common, "--merges", branch).stdout
    raw = merged or _git(root, *common, branch).stdout
    points = []
    for line in raw.splitlines():
        fields = line.split("\0", 4)
        if len(fields) != 5:
            continue
        sha, parents, date, author, subject = fields
        match = PR_RE.search(subject)
        points.append({
            "sha": sha, "parents": parents.split(), "date": date, "author": author,
            "subject": subject, "pr": int(match.group(1)) if match else None,
        })
    points.reverse()
    return points


def _pull_requests(root, out):
    """Merged pull requests by merge commit. gh is optional and read-only."""
    cache = Path(out) / "history" / "pulls.json"
    if cache.is_file():
        try:
            value = json.loads(cache.read_text())
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            pass
    remote = _git(root, "remote", "get-url", "origin", check=False).stdout.strip()
    if "github.com" not in remote or not shutil.which("gh"):
        return {}
    try:
        result = subprocess.run(
            ["gh", "pr", "list", "--state", "merged", "--limit", "1000", "--json",
             "number,mergeCommit,title"], cwd=root, capture_output=True, text=True, timeout=10,
        )
        rows = json.loads(result.stdout) if result.returncode == 0 else []
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return {}
    found = {}
    for row in rows if isinstance(rows, list) else []:
        commit = row.get("mergeCommit") if isinstance(row, dict) else None
        oid = commit.get("oid") if isinstance(commit, dict) else None
        if oid:
            found[oid] = {"number": row.get("number"), "title": row.get("title")}
    _write_json(cache, found)
    return found


def _leaf_files(document):
    found = {}

    def walk(items):
        for item in items or []:
            children = item.get("children") or []
            if children:
                walk(children)
            else:
                for path in item.get("files") or []:
                    found[path] = item["id"]
    walk(document.get("concepts") or [])
    return found


def _point_files(conn):
    rows = conn.execute(
        "SELECT id, path, content_hash FROM nodes WHERE kind IN ('file', 'doc') AND path != ''"
    )
    return {row[0]: {"id": row[0], "path": row[1], "hash": row[2]} for row in rows}


def _current_owners(conn):
    return dict(conn.execute("SELECT f.path, e.src FROM edges e JOIN nodes f ON f.id = e.dst WHERE e.kind = 'owns'"))


def _choose(values):
    counts = Counter(v for v in values if v)
    return min(counts, key=lambda value: (-counts[value], value)) if counts else None


def project_concepts(current, point_conn, current_conn=None):
    """Project the current concepts document onto files in a historical model."""
    document = json.loads(current) if isinstance(current, str) else copy.deepcopy(current)
    current_owner = _leaf_files(document)
    if current_conn is not None:
        current_owner.update(_current_owners(current_conn))
    point_files = _point_files(point_conn)
    path_to_id = {item["path"]: fid for fid, item in point_files.items()}

    hashes = defaultdict(list)
    if current_conn is not None:
        for path, content_hash in current_conn.execute(
                "SELECT path, content_hash FROM nodes WHERE kind IN ('file', 'doc')"):
            if content_hash and current_owner.get(path):
                hashes[content_hash].append(current_owner[path])

    assigned, provisional = {}, []
    for fid, item in sorted(point_files.items(), key=lambda pair: pair[1]["path"]):
        path = item["path"]
        owner = current_owner.get(path)
        by = "path"
        if not owner and item["hash"]:
            owner = _choose(hashes.get(item["hash"], []))
            by = "content"
        if not owner:
            folder = posixpath.dirname(path)
            owner = _choose(current_owner.get(other["path"]) for other in point_files.values()
                            if posixpath.dirname(other["path"]) == folder and other["path"] != path)
            by = "folder"
        if not owner:
            neighbours = []
            for src, dst in point_conn.execute(
                    "SELECT src, dst FROM edges WHERE kind = 'imports' AND (src = ? OR dst = ?)", (fid, fid)):
                other = dst if src == fid else src
                node = point_files.get(other)
                if node:
                    neighbours.append(current_owner.get(node["path"]) or assigned.get(other))
            owner = _choose(neighbours)
            by = "imports"
        if owner:
            assigned[fid] = owner
            if by not in ("path", "content"):
                provisional.append({"file_id": fid, "path": path, "concept_id": owner, "by": by})

    paths_by_owner = defaultdict(list)
    for fid, owner in assigned.items():
        paths_by_owner[owner].append(point_files[fid]["path"])

    def prune(items):
        kept = []
        for raw in items or []:
            item = copy.deepcopy(raw)
            children = prune(item.get("children") or [])
            item.pop("files", None)
            if children:
                item["children"] = children
            else:
                item.pop("children", None)
                owned = sorted(paths_by_owner.get(item["id"], []))
                if owned:
                    item["files"] = owned
            if children or item.get("files"):
                kept.append(item)
        return kept

    projected = {**document, "concepts": prune(document.get("concepts") or [])}
    known = {item["id"] for item in _walk(projected["concepts"])}
    externals = projected.get("externals") or []
    known.update(item.get("id") for item in externals)
    projected["relationships"] = [rel for rel in projected.get("relationships") or []
                                  if rel.get("from") in known and rel.get("to") in known]
    return projected, provisional


def _walk(items):
    for item in items or []:
        yield item
        yield from _walk(item.get("children") or [])


def _has_changes(result):
    return any(group.get("changes") for group in result.get("groups") or [])


def _concept_token(text):
    return hashlib.sha1(text.encode()).hexdigest()


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _narrative(out, entry):
    conn = store.read_only(Path(out) / "refs" / entry["sha"] / "model.db")
    try:
        tasks.attach_cache(conn, readonly=True)
        answer = tasks._cached_answer(conn, review.change_hash(entry["base"], entry["sha"]))
        return answer.get("narrative") if isinstance(answer, dict) else None
    finally:
        conn.close()


def _project_model(root, out, sha, current_text, current_conn, seed=None):
    """Scan one immutable ref, then apply today's concepts to its file set."""
    from cbi.cli import scan_ref

    resolved, reused, _counts, _open = scan_ref(root, out, sha, seed=seed)
    home = out / "refs" / resolved
    conn = store.open_db(home / "model.db")
    try:
        projected, provisional = project_concepts(current_text, conn, current_conn)
    finally:
        conn.close()
    text = json.dumps(projected, indent=2) + "\n"
    concept_path = home / "concepts.json"
    changed = not concept_path.exists() or concept_path.read_text() != text
    if changed:
        concept_path.write_text(text)
        resolved, _again, _counts, _open = scan_ref(root, out, sha, force=True)
        reused = False
    return resolved, reused, provisional


def build_history(root, out, since=None, until=None):
    """Build or update history and return the full oldest-first index."""
    root, out = Path(root), Path(out)
    if not (out / "ignore").exists():
        raise HistoryError(f"{out} is not initialised. Run `cbi init` first.")
    concept_path = out / "concepts.json"
    if not concept_path.is_file():
        raise HistoryError(f"no concept map at {concept_path}. Complete define-concepts first.")
    model_path = out / "model.db"
    if not model_path.is_file():
        raise HistoryError(f"no model at {model_path}. Run `cbi scan` first.")
    current_text = concept_path.read_text()
    token = _concept_token(current_text)
    points = history_points(root, since, until)
    pulls = _pull_requests(root, out)
    for point in points:
        pull = pulls.get(point["sha"])
        if pull:
            point["pr"] = point.get("pr") or pull.get("number")
            point["title"] = pull.get("title")
    if not points:
        _write_json(out / "history" / "index.json", {"version": VERSION, "concepts": token, "entries": []})
        return []
    current_conn = diff.open_model(model_path)
    entries, previous_sha, previous_db = [], None, None
    try:
        first_parent = points[0]["parents"][0] if points[0]["parents"] else None
        sequence = ([{"sha": first_parent}] if first_parent else []) + points
        for number, point in enumerate(sequence):
            sha = point["sha"]
            entry_path = out / "history" / f"{sha}.json"
            cached = None
            if number and entry_path.is_file():
                try:
                    cached = json.loads(entry_path.read_text())
                except (OSError, json.JSONDecodeError):
                    cached = None
                if cached and (cached.get("version") != VERSION or cached.get("concepts") != token
                               or cached.get("base") != previous_sha):
                    cached = None
            seed = previous_db
            resolved, _reused, provisional = _project_model(root, out, sha, current_text, current_conn, seed)
            point_db = out / "refs" / resolved / "model.db"
            if number:
                if cached is None:
                    base = diff.open_model(previous_db)
                    head = diff.open_model(point_db)
                    try:
                        changes = diff.compare(base, head)
                    finally:
                        base.close()
                        head.close()
                    if provisional:
                        changes["history_provisional"] = provisional
                    cached = {**point, "version": VERSION, "concepts": token, "base": previous_sha,
                              "changes": changes, "change_count": sum(len(g["changes"]) for g in changes["groups"])}
                    _write_json(entry_path, cached)
                narrative = _narrative(out, cached)
                if narrative != cached.get("narrative"):
                    if narrative:
                        cached["narrative"] = narrative
                    else:
                        cached.pop("narrative", None)
                    _write_json(entry_path, cached)
                if _has_changes(cached["changes"]):
                    entries.append(cached)
            previous_sha, previous_db = resolved, point_db
    finally:
        current_conn.close()
    _write_json(out / "history" / "index.json", {"version": VERSION, "concepts": token, "entries": entries})
    return entries


def _date(value):
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as err:
        raise HistoryError(f"invalid date {value!r}", code=2) from err


def select(entries, since=None, until=None, concept=None, limit=None):
    low, high = _date(since), _date(until)
    shown = []
    for entry in reversed(entries):
        when = _date(entry["date"])
        if low and when.date() < low.date():
            continue
        if high and when.date() > high.date():
            continue
        item = copy.deepcopy(entry)
        if concept:
            item["changes"] = json.loads(diff.render(item["changes"], "json", concept))
            if not _has_changes(item["changes"]):
                continue
        shown.append(item)
        if limit is not None and len(shown) >= limit:
            break
    return shown


def render(entries, fmt="text"):
    if fmt == "json":
        return json.dumps({"entries": entries}, indent=2, sort_keys=True) + "\n"
    markdown = fmt == "markdown"
    lines = ["# Architecture changelog", ""] if markdown else []
    if not entries:
        lines.append("No architectural changes.")
        return "\n".join(lines) + "\n"
    for entry in entries:
        pr = f" PR #{entry['pr']}" if entry.get("pr") else ""
        title = f"{entry['date'][:10]} {entry['sha'][:12]}{pr} by {entry['author']}"
        lines += ([f"## {title}", ""] if markdown else [title])
        if entry.get("narrative"):
            lines += [entry["narrative"], ""]
        body = diff.render(entry["changes"], "markdown" if markdown else "text").strip()
        if markdown:
            body = "\n".join("##" + line if line.startswith("#") else line for line in body.splitlines())
        lines += [body, ""]
    return "\n".join(lines).rstrip() + "\n"


def write_changelog(out, entries):
    path = Path(out) / "CHANGELOG-ARCHITECTURE.md"
    path.write_text(render(entries, "markdown"))
    return path


def narrate(out, sha):
    """Open the existing summarise-change protocol for one history entry."""
    out = Path(out)
    index_path = out / "history" / "index.json"
    if not index_path.is_file():
        raise HistoryError("history has not been built. Run `cbi history` first.")
    entries = json.loads(index_path.read_text()).get("entries") or []
    matches = [entry for entry in entries if entry["sha"].startswith(sha)]
    if len(matches) != 1:
        state = "ambiguous" if matches else "not found"
        raise HistoryError(f"history entry {sha!r} is {state}", code=2)
    entry = matches[0]
    narrative, task, _define = review._open_tasks(
        out / "refs" / entry["sha"] / "model.db", entry["base"], entry["sha"], entry["changes"])
    if narrative:
        return f"{entry['sha'][:12]} already has a narrative"
    return f"summarise-change {task['id']} {task['state']}" if task else "could not open summarise-change"

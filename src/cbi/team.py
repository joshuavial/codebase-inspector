"""Team mode: commit the judgement, rebuild the model.

`.cbi/team.toml` opts in. `answers.jsonl` is the shared answer cache for this
repo's keys, one compact JSON object per line, sorted by kind then key. Lines
already in the file are kept when the model no longer uses that key, so two
branches add different lines and git can merge them. Import replaces cache rows
for those keys. `cbi check` reads `check` from team.toml. The part splitter
reads `brief_budget` from the same file.
"""

import hashlib
import json
import os
import sqlite3
import subprocess
import tomllib
import uuid
from pathlib import Path

from cbi import files, store

# Same byte budget as an unsplit brief. parts.budget reads it from team.toml.
DEFAULT_BRIEF_BUDGET = 150 * 1024
DEFAULT_CHECK = "fail"
FILE_KIND = "summarise-files"
ANSWERS_NAME = "answers.jsonl"
# merge=union keeps lines both branches add. A sorted insert at the same place
# otherwise conflicts, which fails the two-branch check.
ATTR_LINE = ".cbi/answers.jsonl linguist-generated=true merge=union\n"
SCAN_IGNORE = ("/.cbi/", "/.gitattributes")
DERIVED_GITIGNORE = """\
model.db*
viewer/
refs/
reviews/
history/
ignore.local
"""
TEMPLATE = (
    "# Team mode. The judgement in this directory is committed. Derived files stay ignored.\n"
    f'check = "{DEFAULT_CHECK}"\n'
    f"brief_budget = {DEFAULT_BRIEF_BUDGET}\n"
)
CI_SNIPPET = """\
  - uses: astral-sh/setup-uv@v5
  - run: uv tool install .
  - run: cbi check"""
# Committable names inside the model directory, in the order `git add` prints them.
JUDGEMENT = (
    ".gitignore",
    "team.toml",
    ANSWERS_NAME,
    "ignore",
    "structure.json",
    "concepts.json",
    "screens.json",
    "CHANGELOG-ARCHITECTURE.md",
)


def team_dir(out):
    """The model directory that holds team.toml, or None.

    A ref model uses the judgement copied from that commit into its own home.
    It must not import or export answers through the current worktree.
    """
    if out is None:
        return None
    out = Path(out)
    if (out / "team.toml").is_file():
        return out
    return None


def settings(out):
    """`{"check", "brief_budget"}` from team.toml, or None when the file is missing or not TOML.

    An unknown check value becomes "fail". A missing or unusable budget becomes the default.
    The file still opts the repo in either way; only this parsed view is None.
    """
    path = Path(out) / "team.toml"
    if not path.is_file():
        return None
    try:
        data = tomllib.loads(path.read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    check = data.get("check", DEFAULT_CHECK)
    if check not in ("fail", "warn"):
        check = DEFAULT_CHECK
    budget = data.get("brief_budget", DEFAULT_BRIEF_BUDGET)
    if isinstance(budget, bool) or not isinstance(budget, int) or budget <= 0:
        budget = DEFAULT_BRIEF_BUDGET
    return {"check": check, "brief_budget": budget}


def import_answers(conn, out):
    """Load answers.jsonl into the attached cache. Returns how many rows were applied.

    Rows whose protocol is not the current one are left in the file and not applied.
    A committed row replaces the shared cache for that key.
    """
    directory = team_dir(out)
    if directory is None:
        return 0
    path = directory / ANSWERS_NAME
    if not path.is_file():
        return 0
    from cbi import tasks
    applied = 0
    rows = _parse(path.read_text())
    _remember_revisions(conn, rows.values())
    for row in rows.values():
        if row.get("superseded_by") or row.get("conflicts"):
            conn.execute("DELETE FROM cache.summary_answers WHERE input_hash = ?", (row["key"],))
            continue
        if row["protocol"] != tasks.PROTOCOL_VERSION:
            continue
        if row["kind"] == FILE_KIND:
            if row["key"] == tasks.EMPTY_BLOB_ID:
                continue
            if not isinstance(row["answer"], str) or not row["answer"].strip():
                continue
            conn.execute(
                "INSERT OR REPLACE INTO cache.file_summaries (content_hash, protocol, summary) "
                "VALUES (?, ?, ?)",
                (row["key"], row["protocol"], row["answer"]),
            )
        elif isinstance(row["answer"], (dict, list)):
            conn.execute(
                "INSERT OR REPLACE INTO cache.summary_answers (input_hash, answer) VALUES (?, ?)",
                (row["key"], json.dumps(row["answer"], sort_keys=True, ensure_ascii=False)),
            )
        else:
            continue
        applied += 1
    return applied


def _committed_row(out, kind, key):
    directory = team_dir(out)
    path = directory / ANSWERS_NAME if directory is not None else None
    if path is None or not path.is_file():
        return None
    return _parse(path.read_text()).get((kind, key))


def committed_answer(out, kind, key, protocol):
    """The unambiguous live answer for this task key, or None."""
    row = _committed_row(out, kind, key)
    return row["answer"] if (row and not row.get("superseded_by") and not row.get("conflicts")
                             and row["protocol"] == protocol) else None


def answer_superseded(out, kind, key):
    """Whether this model's history forbids automatically restoring a key."""
    row = _committed_row(out, kind, key)
    return bool(row and (row.get("superseded_by") or row.get("conflicts")))


def answer_conflicts(out, kind, key=None):
    if key is not None:
        row = _committed_row(out, kind, key)
        return row.get("conflicts", []) if row else []
    directory = team_dir(out)
    path = directory / ANSWERS_NAME if directory is not None else None
    rows = _parse(path.read_text()) if path is not None and path.is_file() else {}
    return [candidate for (task_kind, _), row in rows.items() if task_kind == kind
            for candidate in row.get("conflicts", [])]


def committed_answers_changed(conn, out):
    """Whether team answers differ from the answers in this model's last scan."""
    directory = team_dir(out)
    path = directory / ANSWERS_NAME if directory is not None else None
    if path is None or not path.is_file():
        return False
    try:
        fingerprint = json.loads(store.get_meta(conn, "fingerprint") or "{}")
    except json.JSONDecodeError:
        return False
    previous = fingerprint.get("answers") if isinstance(fingerprint, dict) else None
    return isinstance(previous, str) and previous != files.ignore_token(path.read_text())


def supersede(conn, out, kind, key):
    """Retire older document judgements when a replacement is explicitly accepted.

    Tombstones survive team cache imports and union merges. Content-keyed file
    and group summaries remain reusable; document replacement is explicit.
    """
    directory = team_dir(out)
    path = directory / ANSWERS_NAME if directory else None
    rows = _parse(path.read_text()) if path and path.is_file() else {}
    meta_key = "accepted_keys:" + kind
    previous = set(json.loads(store.get_meta(conn, meta_key) or "[]"))
    revisions = _answer_revisions(conn)
    known = revisions.get(kind, {})
    previous.update(known)
    previous.update(k for (task_kind, k) in rows if task_kind == kind)
    clock = json.loads(store.get_meta(conn, "answer_generation_clock") or "{}")
    generation = max(
        [clock.get(kind, 0)] + [revision.get("generation", 0) for revision in known.values()]
        + [_generation(row) for (task_kind, _), row in rows.items() if task_kind == kind]
    ) + 1
    revised = []
    retired_current = set()
    for old in previous:
        observed = rows.get((kind, old))
        revision = known.get(old, {})
        if observed is None and (revision.get("acceptance_id") or revision.get("conflicts")):
            observed = {**_canon(kind, old, 0, {}), **revision}
        targets = _retired_ids(observed) | set(_acceptance_candidates(observed)) if observed else set()
        if old == key:
            retired_current.update(targets)
            continue
        conn.execute("DELETE FROM cache.summary_answers WHERE input_hash = ?", (old,))
        retired = {"kind": kind, "key": old, "generation": generation,
                   "superseded_by": key, "retired_acceptances": sorted(targets)}
        revised.append(retired)
        if (kind, old) in rows:
            rows[(kind, old)] = {**rows[(kind, old)], **retired}
            rows[(kind, old)].pop("conflicts", None)
    from cbi import tasks
    accepted = conn.execute(
        "SELECT answer FROM cache.summary_answers WHERE input_hash = ?", (key,)
    ).fetchone()
    if accepted is None:
        raise ValueError("cannot accept an uncached document answer")
    rows[(kind, key)] = {**_canon(kind, key, tasks.PROTOCOL_VERSION, json.loads(accepted[0])),
                         "generation": generation, "acceptance_id": uuid.uuid4().hex,
                         "retired_acceptances": sorted(retired_current)}
    revised.append(rows[(kind, key)])
    _remember_revisions(conn, revised)
    store.set_meta(conn, meta_key, json.dumps(sorted(previous | {key})))
    if path:
        _atomic(path, _dump(rows))


def sync(conn, out):
    """Rewrite answers.jsonl from the cache when this model is a team repo. Otherwise do nothing."""
    directory = team_dir(out)
    if directory is None:
        return False
    _store(directory, _collect(conn))
    return True


def cmd_init(root, out):
    """Write the opt-in files and print the git commands. Does not run git."""
    root, out = Path(root), Path(out)
    out.mkdir(parents=True, exist_ok=True)
    lines = []
    ignore = out / "ignore"
    ignore_existed = ignore.exists()
    if not ignore_existed:
        ignore.write_text(files.default_ignore(root))
    attr_note, created_attr = _attributes(root, out)
    ignore_changed = _scan_ignore(ignore, created_attr)
    if not ignore_existed:
        lines.append(f"Wrote {_show(root, ignore)}")
    elif ignore_changed:
        lines.append(f"Updated {_show(root, ignore)}")
    else:
        lines.append(f"Kept {_show(root, ignore)}")
    toml_path = out / "team.toml"
    if toml_path.exists():
        lines.append(f"Kept {_show(root, toml_path)}")
    else:
        toml_path.write_text(TEMPLATE)
        lines.append(f"Wrote {_show(root, toml_path)}")
    (out / ".gitignore").write_text(DERIVED_GITIGNORE)
    lines.append(f"Wrote {_show(root, out / '.gitignore')}")
    rows, problem = _model_rows(out / "model.db")
    path, count, changed = _store(out, rows)
    verb = "Wrote" if changed else "Kept"
    lines.append(f"{verb} {_show(root, path)} ({count} answers)")
    if problem:
        lines.append(problem)
    lines.append(attr_note)
    removed, ignored = ensure_judgement_visible(root, out)
    if removed:
        lines.append(f"Removed {removed['pattern']!r} from {_show(root, removed['source'])} line {removed['line']} so .cbi/ is visible to git.")
    if ignored:
        lines.append(
            f"{ignored['path']} is ignored by {ignored['source']} line {ignored['line']} "
            f"({ignored['pattern']!r}). Remove that rule so the judgement files can be committed."
        )
    listed = _commit_paths(root, out)
    if removed and ".gitignore" not in listed:
        listed.insert(0, ".gitignore")
    lines += [
        "",
        "Commit the judgement. This command does not commit or push.",
        "",
        "  git add -- " + " ".join(listed),
        "",
        "GitHub Actions:",
        "",
        *CI_SNIPPET.splitlines(),
    ]
    print("\n".join(lines))
    return 0


def ensure_judgement_visible(root, out):
    """Remove one exact root ignore rule and return `(removed, remaining)`.

    Git's own matcher covers parent repositories, global excludes and rules
    whose effect is not obvious from the root .gitignore. Only a plain root
    `.cbi` line is safe to change automatically.
    """
    root, out = Path(root), Path(out)
    if not _is_repo_cbi(root, out):
        return None, None
    ignored = judgement_ignore(root)
    removed = None
    if ignored and _plain_root_rule(root, ignored):
        source = Path(ignored["source"])
        if not source.is_absolute():
            source = root / source
        lines = source.read_text().splitlines(keepends=True)
        index = ignored["line"] - 1
        if 0 <= index < len(lines) and lines[index].rstrip("\r\n") in (".cbi", ".cbi/"):
            del lines[index]
            source.write_text("".join(lines))
            removed = {**ignored, "source": source}
            ignored = judgement_ignore(root)
    return removed, ignored


def judgement_ignore(root):
    """The git rule ignoring a committed judgement file, or None."""
    target = ".cbi/concepts.json"
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "-v", "--", target],
        cwd=root, capture_output=True, text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    detail, _tab, path = result.stdout.rstrip("\n").partition("\t")
    source, line, pattern = detail.rsplit(":", 2)
    try:
        number = int(line)
    except ValueError:
        return {"source": source, "line": 0, "pattern": pattern, "path": path or target}
    return {"source": source, "line": number, "pattern": pattern, "path": path or target}


def _plain_root_rule(root, ignored):
    source = Path(ignored["source"])
    if not source.is_absolute():
        source = Path(root) / source
    return source.resolve() == (Path(root) / ".gitignore").resolve() and ignored["pattern"] in (".cbi", ".cbi/")


def _model_rows(path):
    """`(rows, problem)`. problem is a sentence when the model was not read."""
    if not path.exists():
        return {}, None
    conn = store.read_only(path)
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version != store.SCHEMA_VERSION:
            return {}, f"{path.name} is schema {version}; exported no new answers"
        from cbi import tasks
        tasks.attach_cache(conn)
        return _collect(conn), None
    except sqlite3.Error as err:
        return {}, f"{path.name} could not be read ({err}); exported no new answers"
    finally:
        conn.close()


def _collect(conn):
    """Cache rows this model uses, keyed by (kind, key). The cache is attached as `cache`."""
    from cbi import tasks
    found = {}
    revisions = _answer_revisions(conn)
    protocol = tasks.PROTOCOL_VERSION
    hashes = [
        row[0] for row in conn.execute(
            "SELECT DISTINCT content_hash FROM nodes "
            "WHERE kind = 'file' AND content_hash IS NOT NULL "
            "AND content_hash != ? AND json_extract(attrs, '$.role') IN ('code', 'test')",
            (tasks.EMPTY_BLOB_ID,),
        )
    ]
    if hashes:
        for key, summary in conn.execute(
            "SELECT content_hash, summary FROM cache.file_summaries "
            "WHERE protocol = ? AND content_hash IN (SELECT value FROM json_each(?))",
            (protocol, json.dumps(hashes)),
        ):
            if isinstance(summary, str) and summary:
                found[(FILE_KIND, key)] = _canon(FILE_KIND, key, protocol, summary)
    for kind, key in conn.execute(
        "SELECT kind, input_hash FROM tasks WHERE kind != ?", (FILE_KIND,)
    ):
        row = conn.execute(
            "SELECT answer FROM cache.summary_answers WHERE input_hash = ?", (key,)
        ).fetchone()
        if not row:
            continue
        try:
            answer = json.loads(row[0])
        except json.JSONDecodeError:
            continue
        if isinstance(answer, (dict, list)):
            revision = revisions.get(kind, {}).get(key, {})
            if revision.get("superseded_by") or revision.get("conflicts"):
                continue
            if (revision.get("generation")
                    and revision.get("answer_digest") != _answer_digest(answer)):
                continue
            found[(kind, key)] = {**_canon(kind, key, protocol, answer),
                                  **{name: revision[name] for name in _REVISION_FIELDS if name in revision}}
    return found


def _answer_revisions(conn):
    return json.loads(store.get_meta(conn, "answer_revisions") or "{}")


def _remember_revisions(conn, rows):
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'meta'").fetchone():
        return  # cache-only import callers have no model metadata to retain
    revisions = _answer_revisions(conn)
    clock = json.loads(store.get_meta(conn, "answer_generation_clock") or "{}")
    for row in rows:
        kind, key = row["kind"], row["key"]
        revision = {name: row[name] for name in _REVISION_FIELDS if name in row}
        clock[kind] = max(clock.get(kind, 0), _generation(row))
        if revision and "answer" in row:
            revision["answer_digest"] = _answer_digest(row["answer"])
        if revision or key in revisions.get(kind, {}):
            revisions.setdefault(kind, {})[key] = revision
    store.set_meta(conn, "answer_revisions", json.dumps(revisions, sort_keys=True))
    store.set_meta(conn, "answer_generation_clock", json.dumps(clock, sort_keys=True))


def _answer_digest(answer):
    text = json.dumps(answer, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()


def _generation(row):
    return row.get("generation", 0)


_REVISION_FIELDS = ("generation", "superseded_by", "acceptance_id", "retired_acceptances", "conflicts")


def _legacy_acceptance_id(row):
    value = [row["kind"], row["key"], row["protocol"], _answer_digest(row["answer"])]
    return "legacy-" + _answer_digest(value)


def _acceptance_candidates(row):
    if not row:
        return {}
    if row.get("conflicts"):
        return {candidate["acceptance_id"]: candidate for candidate in row["conflicts"]}
    if "retired_acceptances" in row and not row.get("acceptance_id"):
        return {}
    candidate = {name: row[name] for name in ("kind", "key", "protocol", "answer", "generation") if name in row}
    candidate["acceptance_id"] = row.get("acceptance_id") or _legacy_acceptance_id(row)
    return {candidate["acceptance_id"]: candidate}


def _retired_ids(row):
    if not row:
        return set()
    retired = set(row.get("retired_acceptances", []))
    if row.get("superseded_by") and not retired:
        retired.update(_acceptance_candidates(row))
    return retired


def _prefer_row(current, candidate):
    if current is None:
        return candidate
    causal = any(row.get("acceptance_id") or row.get("conflicts") or "retired_acceptances" in row
                 for row in (current, candidate))
    if not causal:
        rank = lambda row: (_generation(row), bool(row.get("superseded_by")))
        return candidate if rank(candidate) >= rank(current) else current
    retired = _retired_ids(current) | _retired_ids(candidate)
    choices = _acceptance_candidates(current)
    choices.update(_acceptance_candidates(candidate))
    live = [choices[key] for key in sorted(choices) if key not in retired]
    if live:
        row = dict(live[0])
        if len(live) > 1:
            row.pop("acceptance_id", None)
            row["conflicts"] = live
            row["generation"] = max(_generation(value) for value in live)
        row["retired_acceptances"] = sorted(retired)
        return row
    row = dict(max((current, candidate), key=lambda item: (_generation(item), _answer_digest(item))))
    row.pop("conflicts", None)
    row["superseded_by"] = row.get("superseded_by") or "retired acceptance"
    row["retired_acceptances"] = sorted(retired)
    return row


def _canon(kind, key, protocol, answer):
    return {"kind": kind, "key": key, "protocol": protocol, "answer": answer}


def _parse(text):
    """Merge records by acceptance identity and observed retirement targets.

    Legacy rows without causal fields retain generation ordering. Concurrent
    live identities at one input key are preserved as an explicit conflict.
    """
    rows = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        row = _valid(data)
        if row:
            key = (row["kind"], row["key"])
            rows[key] = _prefer_row(rows.get(key), row)
    return rows


def _valid(data, allow_conflicts=True):
    if not isinstance(data, dict):
        return None
    kind, key, protocol, answer = (data.get("kind"), data.get("key"), data.get("protocol"), data.get("answer"))
    if not isinstance(kind, str) or not kind or not isinstance(key, str) or not key:
        return None
    if isinstance(protocol, bool) or not isinstance(protocol, int):
        return None
    if answer is None:
        return None
    row = _canon(kind, key, protocol, answer)
    generation = data.get("generation")
    if isinstance(generation, int) and not isinstance(generation, bool) and generation >= 0:
        row["generation"] = generation
    if isinstance(data.get("superseded_by"), str) and data["superseded_by"]:
        row["superseded_by"] = data["superseded_by"]
    if isinstance(data.get("acceptance_id"), str) and data["acceptance_id"]:
        row["acceptance_id"] = data["acceptance_id"]
    if isinstance(data.get("retired_acceptances"), list):
        row["retired_acceptances"] = sorted({value for value in data["retired_acceptances"] if isinstance(value, str)})
    if allow_conflicts and isinstance(data.get("conflicts"), list):
        candidates = [_valid(value, allow_conflicts=False) for value in data["conflicts"]]
        candidates = [value for value in candidates if value and value.get("acceptance_id")
                      and (value["kind"], value["key"]) == (kind, key)]
        if candidates:
            row["conflicts"] = sorted(candidates, key=lambda value: value["acceptance_id"])
    return row


def _dump(rows):
    ordered = [rows[key] for key in sorted(rows)]
    return "".join(
        json.dumps(row, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n" for row in ordered
    )


def _store(directory, rows):
    """Merge collected rows into answers.jsonl without inventing acceptance events."""
    path = Path(directory) / ANSWERS_NAME
    merged = _parse(path.read_text()) if path.is_file() else {}
    for key, row in rows.items():
        current = merged.get(key)
        if (current and (current.get("acceptance_id") or current.get("conflicts") or "retired_acceptances" in current)
                and not (row.get("acceptance_id") or row.get("conflicts") or "retired_acceptances" in row)):
            continue  # an unversioned cache export is not a new acceptance event
        merged[key] = _prefer_row(current, row)
    changed = _atomic(path, _dump(merged))
    return path, len(merged), changed


def _atomic(path, text):
    if path.is_file() and path.read_text() == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)
    return True


def _attributes(root, out):
    """(message, created). created is true when this call adds a new .gitattributes file."""
    if not _is_repo_cbi(root, out):
        return "Left .gitattributes unchanged because the model directory is not .cbi/.", False
    path = Path(root) / ".gitattributes"
    existed = path.exists()
    text = path.read_text() if existed else ""
    if _marked(text):
        return "Kept .gitattributes", False
    kept = []
    replaced = False
    for line in text.splitlines():
        parts = line.split()
        if parts and not line.strip().startswith("#") and parts[0] == ".cbi/answers.jsonl":
            kept.append(ATTR_LINE.rstrip("\n"))
            replaced = True
        else:
            kept.append(line)
    if not replaced:
        kept.append(ATTR_LINE.rstrip("\n"))
    path.write_text("\n".join(kept) + "\n")
    return ("Wrote .gitattributes", not existed)


def _marked(text):
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split()
        if parts and parts[0] == ".cbi/answers.jsonl" and "linguist-generated=true" in parts and "merge=union" in parts:
            return True
    return False


def _scan_ignore(path, created_attr):
    """Leave the committed judgement out of the map. Returns True when the file changed.

    `/.cbi/` would otherwise become a folder once it is tracked, and a new
    `.gitattributes` would become a root file. Either one changes the workspace
    summary hash, so a clone would open that task again.
    """
    text = path.read_text() if path.exists() else ""
    lines = text.splitlines()
    directory, attributes = SCAN_IGNORE
    extra = []
    if directory not in lines:
        extra.append(directory)
    if created_attr and attributes not in lines:
        extra.append(attributes)
    if not extra:
        return False
    if text and not text.endswith("\n"):
        text += "\n"
    text += "# Team mode. The committed judgement is not part of the map.\n"
    text += "".join(f"{line}\n" for line in extra)
    path.write_text(text)
    return True


def _is_repo_cbi(root, out):
    return Path(out).resolve() == (Path(root) / ".cbi").resolve()


def _show(root, path):
    path = Path(path).resolve()
    try:
        return path.relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return str(path)


def _commit_paths(root, out):
    listed = []
    if _is_repo_cbi(root, out) and _marked((Path(root) / ".gitattributes").read_text()
                                           if (Path(root) / ".gitattributes").exists() else ""):
        listed.append(".gitattributes")
    for name in JUDGEMENT:
        path = Path(out) / name
        if path.is_file():
            listed.append(_show(root, path))
    return listed

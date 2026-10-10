"""Team mode: commit the judgement, rebuild the model.

`.cbi/team.toml` opts in. `answers.jsonl` is the shared answer cache for this
repo's keys, one compact JSON object per line, sorted by kind then key. Lines
already in the file are kept when the model no longer uses that key, so two
branches add different lines and git can merge them. Import replaces cache rows
for those keys. `cbi check` reads `check` from team.toml. The part splitter
reads `brief_budget` from the same file.
"""

import json
import os
import sqlite3
import subprocess
import tomllib
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

    A ref model lives at `.cbi/refs/<sha>/` and uses the worktree's `.cbi/`.
    """
    if out is None:
        return None
    out = Path(out)
    if (out / "team.toml").is_file():
        return out
    if out.parent.name == "refs" and (out.parent.parent / "team.toml").is_file():
        return out.parent.parent
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
    for row in _parse(path.read_text()).values():
        if row["protocol"] != tasks.PROTOCOL_VERSION:
            continue
        if row["kind"] == FILE_KIND:
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
    protocol = tasks.PROTOCOL_VERSION
    hashes = [
        row[0] for row in conn.execute(
            "SELECT DISTINCT content_hash FROM nodes "
            "WHERE kind = 'file' AND content_hash IS NOT NULL "
            "AND json_extract(attrs, '$.role') IN ('code', 'test')"
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
            found[(kind, key)] = _canon(kind, key, protocol, answer)
    return found


def _canon(kind, key, protocol, answer):
    return {"kind": kind, "key": key, "protocol": protocol, "answer": answer}


def _parse(text):
    """Valid rows keyed by (kind, key). The last copy of a key wins. Broken lines are dropped."""
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
            rows[(row["kind"], row["key"])] = row
    return rows


def _valid(data):
    if not isinstance(data, dict):
        return None
    kind, key, protocol, answer = (data.get("kind"), data.get("key"), data.get("protocol"), data.get("answer"))
    if not isinstance(kind, str) or not kind or not isinstance(key, str) or not key:
        return None
    if isinstance(protocol, bool) or not isinstance(protocol, int):
        return None
    if answer is None:
        return None
    return _canon(kind, key, protocol, answer)


def _dump(rows):
    ordered = [rows[key] for key in sorted(rows)]
    return "".join(
        json.dumps(row, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n" for row in ordered
    )


def _store(directory, rows):
    """Union `rows` into answers.jsonl. Current rows replace the same kind and key. Returns (path, count, changed)."""
    path = Path(directory) / ANSWERS_NAME
    merged = _parse(path.read_text()) if path.is_file() else {}
    merged.update(rows)
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

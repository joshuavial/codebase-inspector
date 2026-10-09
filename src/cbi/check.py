"""`cbi check`: the committed map matches the files changed since the merge base.

The command scans, which writes the derived model, then puts the judgement
files back so answers.jsonl and the JSON files stay as they were. It does
not fetch, commit or push.
"""

import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path

from cbi import concepts, files, screens, store, tasks, team

HELP = """\
Scan this repo and fail when the map is behind the files changed since the
merge base with the default branch. The default branch is origin's HEAD when
that ref exists locally, otherwise main, otherwise master. --base REF uses
the merge base with that ref instead. Nothing is fetched.

A changed code or test file needs a summary. When the repo has concepts, it
also needs one concept owner. structure.json, concepts.json and screens.json
must pass the checks their tasks use. In a team repo, answers.jsonl must
hold every accepted answer, and answer text must not look like a key or a
token (a known prefix, or a high-entropy token).

Prints each file and how to fix it. --format github prints GitHub Actions
annotations. team.toml can set check = "warn": the same list is printed and
the command exits 0.

The scan writes the derived model. Judgement files are restored afterwards,
so this command does not rewrite answers.jsonl or the JSON files.

Exit codes: 0 passed, or problems while check = "warn"; 1 a check failed,
not inside a git repo, not initialised, or an unknown base."""

KEPT = ("structure.json", "concepts.json", "screens.json", team.ANSWERS_NAME)
_PREFIXES = (
    ("aws access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b|\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("gitlab token", re.compile(r"\bglpat-[A-Za-z0-9_-]{16,}\b")),
    ("slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("stripe key", re.compile(r"\b(?:sk|rk)_live_[A-Za-z0-9]{10,}\b")),
    ("google api key", re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b")),
    ("npm token", re.compile(r"\bnpm_[A-Za-z0-9]{20,}\b")),
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
)
_TOKEN = re.compile(r"[A-Za-z0-9+/_=-]{24,}")


def run(root, out, base_ref, fmt, scan):
    """Scan, report, and restore judgement files. `scan` is `cbi.cli.scan`."""
    root, out = Path(root), Path(out)
    if not (out / "ignore").exists():
        print(f"{out} is not initialised. Run `cbi init` first.", file=sys.stderr)
        return 1
    base = base_sha(root, base_ref)
    saved = snapshot(out)
    try:
        scan(root, out)
        return _report(root, out, base, fmt)
    finally:
        restore(out, saved)


def base_sha(root, ref):
    """The commit the change is measured from. Raises files.BadRef."""
    head = files.resolve_commit(root, "HEAD")
    if ref:
        other = files.resolve_commit(root, ref)
        label = ref
    else:
        other = _default_tip(root)
        label = "the default branch"
        if other is None:
            raise files.BadRef("pass --base REF. There is no merge-base with the default branch.")
    if other == head:
        return head
    result = subprocess.run(
        ["git", "merge-base", "--end-of-options", other, head],
        cwd=root, capture_output=True, text=True,
    )
    found = result.stdout.strip()
    if result.returncode != 0 or not found:
        raise files.BadRef(f"no merge-base between {label} and HEAD")
    return found


def changed_paths(root, base):
    """Tracked paths added, copied, modified or renamed since `base`, worktree included."""
    result = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=ACMR", "-z", "--end-of-options", base],
        cwd=root, capture_output=True,
    )
    if result.returncode != 0:
        detail = result.stderr.decode().strip() or "git diff failed"
        raise files.BadRef(detail)
    return [os.fsdecode(part) for part in result.stdout.split(b"\0") if part]


def snapshot(out):
    """Bytes of the judgement files, or None when a file is absent."""
    saved = {}
    out = Path(out)
    for name in KEPT:
        path = out / name
        saved[name] = path.read_bytes() if path.is_file() else None
    return saved


def restore(out, saved):
    """Put the judgement files back. A derived model.db is left as the scan wrote it."""
    out = Path(out)
    for name, data in saved.items():
        path = out / name
        if data is None:
            if path.is_file():
                path.unlink()
            continue
        if path.is_file() and path.read_bytes() == data:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def secret_kind(text):
    """The name of the first key or token pattern in text, or None.

    Hex strings are skipped: file keys and blob ids are hex, and a uniform hex
    string is at most 4 bits per character. The cut sits just above that. A
    32-character url-safe token can land near 4.5, so 4.5 misses some of them.
    A known prefix still matches.
    """
    if not isinstance(text, str) or not text:
        return None
    for name, pattern in _PREFIXES:
        if pattern.search(text):
            return name
    for match in _TOKEN.finditer(text):
        token = match.group(0)
        if re.fullmatch(r"[0-9a-fA-F]+", token):
            continue
        if not any(ch.isalpha() for ch in token) or not any(ch.isdigit() for ch in token):
            continue
        if _entropy(token) >= 4.2:
            return "high-entropy token"
    return None


def _default_tip(root):
    """SHA of the local default branch, or None. Does not fetch."""
    names = []
    origin = _git_text(root, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if origin:
        names.append(origin)
    names.extend(name for name in ("main", "master") if name not in names)
    for name in names:
        try:
            return files.resolve_commit(root, name)
        except files.BadRef:
            continue
    return None


def _git_text(root, *args):
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
    text = result.stdout.strip()
    return text if result.returncode == 0 and text else None


def _report(root, out, base, fmt):
    conn = store.open_db(out / "model.db")
    try:
        tasks.attach_cache(conn)
        findings = _findings(conn, root, out, changed_paths(root, base))
    finally:
        conn.close()
    mode = _mode(out)
    print(_render(findings, mode, fmt))
    if findings and mode != "warn":
        return 1
    return 0


def _mode(out):
    cfg = team.settings(out)
    return cfg["check"] if cfg else team.DEFAULT_CHECK


def _findings(conn, root, out, changed):
    found = []
    found.extend(_file_findings(conn, changed))
    found.extend(_json_findings(conn, root, out))
    found.extend(_stale_findings(conn, root, out))
    found.extend(_secret_findings(conn, root, out))
    return found


def _file_findings(conn, changed):
    by_path = {row["path"]: row for row in concepts._code_files(conn)}
    has_concepts = conn.execute("SELECT 1 FROM nodes WHERE kind = 'concept' LIMIT 1").fetchone() is not None
    owned = set()
    if has_concepts:
        owned = {row[0] for row in conn.execute(
            "SELECT e.dst FROM edges e JOIN nodes c ON c.id = e.src "
            "WHERE e.kind = 'owns' AND c.kind = 'concept'"
        )}
    found = []
    for path in sorted(set(changed)):
        row = by_path.get(path)
        if row is None:
            continue
        if not isinstance(row["summary"], str) or not row["summary"].strip():
            role = "test" if row["role"] == "test" else "code"
            found.append(_finding("summary", path, f"changed {role} file has no summary", "missing summary"))
        if has_concepts and row["id"] not in owned:
            found.append(_finding("owner", path, "no concept owns this changed file", "missing owner"))
    return found


def _json_findings(conn, root, out):
    found = []
    for name, checker in (
        ("structure.json", _structure_errors),
        ("concepts.json", _concept_errors),
        ("screens.json", lambda conn, text: _screen_errors(conn, text, root)),
    ):
        path = Path(out) / name
        if not path.is_file() or not path.read_text().strip():
            continue
        for message in checker(conn, path.read_text()):
            found.append(_finding("json", _show(root, path), message, name))
    return found


def _structure_errors(conn, text):
    try:
        data = json.loads(text)
    except json.JSONDecodeError as err:
        return [f"not valid JSON ({err})"]
    if not isinstance(data, dict):
        return ["expected a JSON object"]
    errors = []
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "deployables": {"type": "array", "items": tasks._STRUCTURE_ITEM["deployables"]},
            "packages": {"type": "array", "items": tasks._STRUCTURE_ITEM["packages"]},
        },
    }
    tasks._check(
        {"deployables": data.get("deployables", []), "packages": data.get("packages", [])},
        schema, "$", errors,
    )
    tracked = tasks._tracked_paths(conn)
    for kind in ("deployables", "packages"):
        items = data.get(kind)
        if not isinstance(items, list):
            continue
        for index, item in enumerate(items):
            if not isinstance(item, dict) or item.get("remove") is True:
                continue
            if kind == "packages":
                directory = item.get("directory")
                if isinstance(directory, str) and directory.strip():
                    before = len(errors)
                    tasks._repo_path(directory, f"$.packages[{index}].directory", errors)
                    if len(errors) == before and not tasks._under(tracked, directory):
                        errors.append(
                            f"$.packages[{index}].directory: no tracked file under {directory.strip()!r}"
                        )
            entries = item.get("entry_points")
            if isinstance(entries, list):
                for entry_index, entry in enumerate(entries):
                    if isinstance(entry, str) and entry.strip():
                        tasks._repo_path(entry, f"$.{kind}[{index}].entry_points[{entry_index}]", errors)
    return errors


def _concept_errors(conn, text):
    data, errors = _object(text)
    if data is None:
        return errors
    body = dict(data)
    body.setdefault("input_hash", "check")
    tasks._check(body, tasks.SCHEMAS["define-concepts"], "$", errors)
    if errors:
        return errors
    try:
        failed, _warnings = concepts.problems(conn, body)
    except (KeyError, TypeError) as err:
        return [f"failed its checks ({err})"]
    return failed


def _screen_errors(conn, text, root=None):
    data, errors = _object(text)
    if data is None:
        return errors
    body = dict(data)
    body.setdefault("input_hash", "check")
    tasks._check(body, tasks.SCHEMAS["sketch-screens"], "$", errors)
    if errors:
        return errors
    try:
        return screens.problems(conn, body, root)
    except (KeyError, TypeError) as err:
        return [f"failed its checks ({err})"]


def _object(text):
    try:
        data = json.loads(text)
    except json.JSONDecodeError as err:
        return None, [f"not valid JSON ({err})"]
    if not isinstance(data, dict):
        return None, ["expected a JSON object"]
    return data, []


def _stale_findings(conn, root, out):
    if team.team_dir(out) is None:
        return []
    path = _answers_file(out)
    have = team._parse(path.read_text()) if path.is_file() else {}
    found = []
    shown = _show(root, path)
    for key, row in sorted(team._collect(conn).items()):
        current = have.get(key)
        if current is None:
            found.append(_finding(
                "stale", shown,
                f"missing accepted answer {row['kind']} {row['key']}",
                "stale answers",
            ))
        elif current.get("answer") != row["answer"] or current.get("protocol") != row["protocol"]:
            found.append(_finding(
                "stale", shown,
                f"accepted answer {row['kind']} {row['key']} is not the text in this file",
                "stale answers",
            ))
    return found


def _secret_findings(conn, root, out):
    path = _answers_file(out)
    found = []
    seen = set()
    if path.is_file():
        shown = _show(root, path)
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if not line.strip():
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            answer = data.get("answer") if isinstance(data, dict) else None
            kind = _answer_secret(answer)
            if not kind:
                continue
            key = (data.get("kind"), data.get("key"), kind)
            seen.add(key)
            found.append(_finding("secret", shown, f"answer looks like a {kind}", "secret", line=number))
    if team.team_dir(out) is None:
        return found
    shown = _show(root, path)
    for (task_kind, key), row in sorted(team._collect(conn).items()):
        kind = _answer_secret(row["answer"])
        if not kind or (task_kind, key, kind) in seen:
            continue
        found.append(_finding(
            "secret", shown,
            f"accepted answer {task_kind} {key} looks like a {kind}",
            "secret",
        ))
    return found


def _answer_secret(answer):
    for text in _strings(answer):
        kind = secret_kind(text)
        if kind:
            return kind
    return None


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _answers_file(out):
    directory = team.team_dir(out) or Path(out)
    return Path(directory) / team.ANSWERS_NAME


def _finding(kind, path, message, title, line=None):
    return {"kind": kind, "file": path, "line": line, "message": message, "title": title}


def _show(root, path):
    path = Path(path).resolve()
    try:
        return path.relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return str(path)


def _render(findings, mode, fmt):
    if not findings:
        return "cbi check: passed"
    if fmt == "github":
        lines = [_annotation(item, mode) for item in findings]
    else:
        noun = "warning" if mode == "warn" else "problem"
        if len(findings) != 1:
            noun += "s"
        lines = [f"cbi check: {len(findings)} {noun}"]
        for item in findings:
            where = item["file"] if not item["line"] else f"{item['file']}:{item['line']}"
            lines.append(f"{where}: {item['message']}")
    lines.extend(_fix_lines(findings))
    if mode == "warn":
        lines.append('team.toml sets check = "warn", so this exits 0.')
    return "\n".join(lines)


def _fix_lines(findings):
    kinds = {item["kind"] for item in findings}
    lines = []
    if kinds & {"summary", "owner", "json"}:
        lines.append("Fix with: cbi prime")
    if "stale" in kinds:
        lines.append("Write the accepted answers with: cbi team init")
    if "secret" in kinds:
        lines.append("Rewrite the answer so it does not contain a key or token, then submit it again.")
    return lines


def _annotation(item, mode):
    level = "warning" if mode == "warn" else "error"
    loc = f"file={item['file']}"
    if item["line"]:
        loc += f",line={item['line']}"
    title = _escape(item["title"])
    message = _escape(item["message"])
    return f"::{level} {loc},title={title}::{message}"


def _escape(text):
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _entropy(text):
    counts = {}
    for char in text:
        counts[char] = counts.get(char, 0) + 1
    total = len(text)
    return -sum((count / total) * math.log2(count / total) for count in counts.values())

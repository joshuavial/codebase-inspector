"""Build and open a cbi:// link. Nothing here writes the repo or its model."""

import json
import os
import re
import subprocess
import sys
import urllib.parse
from pathlib import Path

from cbi import files, query, store

NO_HANDLER = (
    "No application handles cbi:// links. The link is printed above. "
    "Install Codebase Inspector and open it once so it can register the scheme."
)

# A node id is a concept id (segments) or a structured id: local:<dir>[:path],
# host/owner/repo[:path], then an optional #qualified name. Test names may contain
# spaces and " > ". Shell metacharacters and ".." are refused.
_SEGMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:+-]*")
_QUAL_PART = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._+~-]*")
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._+/-]{0,199}")
_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/@~^{}-]*")
_COMPARE = re.compile(r"([A-Za-z0-9][A-Za-z0-9._/@~^{}-]*)\.\.([A-Za-z0-9][A-Za-z0-9._/@~^{}-]*)")
_PR = re.compile(r"[1-9][0-9]{0,8}")


class OpenError(Exception):
    pass


def valid_node_id(value):
    """True when value matches the node id grammar used in cbi:// links."""
    if not isinstance(value, str) or not value or len(value) > 512:
        return False
    if ".." in value or "//" in value or any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        return False
    head, sep, tail = value.partition("#")
    if sep and not _valid_qual(tail):
        return False
    if not head or " " in head or head.startswith(("/", "-")):
        return False
    if head.startswith("local:"):
        dirname, colon, path = head[6:].partition(":")
        if not _SEGMENT.fullmatch(dirname or ""):
            return False
        return not colon or _valid_path(path)
    workspace, colon, path = head.partition(":")
    parts = workspace.split("/")
    if not parts or any(not _SEGMENT.fullmatch(part) for part in parts):
        return False
    if colon:
        return len(parts) >= 3 and _valid_path(path)
    return True


def valid_name(value):
    """A display name `cbi open --node` may resolve. Not an id, and not a command."""
    if not isinstance(value, str) or not _NAME.fullmatch(value):
        return False
    return ".." not in value and "//" not in value and "  " not in value


def parse_compare(value):
    """(base, head) for a base..head range, or None when the shape is wrong."""
    if not isinstance(value, str) or "..." in value:
        return None
    match = _COMPARE.fullmatch(value)
    if not match:
        return None
    return match.group(1), match.group(2)


def valid_pr(value):
    return isinstance(value, str) and bool(_PR.fullmatch(value))


def build_url(repo, ref, node=None):
    """cbi://open?repo=<abs path>&ref=<ref or worktree path>&node=<id>."""
    pairs = [("repo", str(repo)), ("ref", str(ref))]
    if node:
        pairs.append(("node", node))
    return "cbi://open?" + urllib.parse.urlencode(pairs)


def build_compare_url(repo, compare, node=None):
    """cbi://open?repo=<abs path>&compare=<base>..<head>&node=<id>."""
    pairs = [("repo", str(repo)), ("compare", compare)]
    if node:
        pairs.append(("node", node))
    return "cbi://open?" + urllib.parse.urlencode(pairs)


def run(args, launch=None):
    """Print the link and hand it to the OS. Returns a process exit code."""
    try:
        return _run(args, launch)
    except OpenError as err:
        print(err, file=sys.stderr)
        return 1


def _run(args, launch):
    if (args.compare or args.pr is not None) and (args.worktree or args.branch or args.commit):
        print("pass a version or a comparison, not both", file=sys.stderr)
        return 2
    if args.compare and args.pr is not None:
        print("pass --compare or --pr, not both", file=sys.stderr)
        return 2
    root = _root(args.path)
    if args.pr is not None:
        if not valid_pr(args.pr):
            print("pr must be a pull request number", file=sys.stderr)
            return 2
        base, head = _pull_request(root, args.pr)
        url = build_compare_url(root, f"{base}..{head}", _node(root, head, args.node) if args.node else None)
    elif args.compare:
        sides = parse_compare(args.compare)
        if not sides:
            print("compare must be base..head", file=sys.stderr)
            return 2
        base, head = sides
        files.resolve_commit(root, base)
        files.resolve_commit(root, head)
        url = build_compare_url(root, args.compare, _node(root, head, args.node) if args.node else None)
    else:
        ref = _version(root, args)
        node = _node(root, ref, args.node) if args.node else None
        url = build_url(root, ref, node)
    print(url)
    opener = launch or open_url
    code, _detail = opener(url)
    if code != 0:
        print(NO_HANDLER, file=sys.stderr)
        return 1
    return 0


def _valid_path(path):
    if not path:
        return False
    parts = path.split("/")
    if parts[-1] == "":
        parts.pop()
    return bool(parts) and all(_SEGMENT.fullmatch(part) for part in parts)


def _valid_qual(tail):
    if not tail or tail.startswith(" ") or tail.endswith(" "):
        return False
    parts = tail.split(" > ")
    if " > ".join(parts) != tail:
        return False
    return all(
        _QUAL_PART.fullmatch(part) and "  " not in part and not part.startswith(" ") and not part.endswith(" ")
        for part in parts
    )


def _root(path):
    start = Path(path).expanduser() if path else Path.cwd()
    if not start.is_absolute():
        start = (Path.cwd() / start).resolve()
    else:
        start = start.resolve()
    if start.is_file():
        start = start.parent
    return files.repo_root(start).resolve()


def _version(root, args):
    if args.worktree:
        return str(_worktree(root, args.worktree))
    if args.branch:
        _check_ref(args.branch)
        files.resolve_commit(root, f"refs/heads/{args.branch}")
        return args.branch
    if args.commit:
        _check_ref(args.commit)
        return files.resolve_commit(root, args.commit)
    return str(root)


def _check_ref(value):
    if not isinstance(value, str) or not _REF.fullmatch(value) or ".." in value:
        raise files.BadRef(f"unknown ref {value}")


def _worktree(root, name):
    if not isinstance(name, str) or not name or any(ord(ch) < 32 for ch in name):
        raise OpenError(f"unknown worktree {name!r}")
    data = files.inventory(root, root / ".cbi")
    given = Path(name)
    want = given.resolve() if given.is_absolute() else None
    by_path, by_name, by_lane = [], [], []
    for item in data["worktrees"]:
        path = Path(item["path"]).resolve()
        if want and path == want:
            by_path.append(path)
        if path.name == name:
            by_name.append(path)
        if item.get("lane") == name:
            by_lane.append(path)
    for group in (by_path, by_name, by_lane):
        if len(group) == 1:
            return group[0]
        if len(group) > 1:
            listed = ", ".join(str(path) for path in group)
            raise OpenError(f"worktree {name!r} matches more than one checkout: {listed}")
    raise OpenError(f"unknown worktree {name}")


def _model_path(root, ref):
    candidate = Path(ref)
    if candidate.is_absolute() and candidate.is_dir():
        return candidate / ".cbi" / "model.db"
    sha = files.resolve_commit(root, ref)
    return root / ".cbi" / "refs" / sha / "model.db"


def _node(root, ref, token):
    if not valid_node_id(token) and not valid_name(token):
        raise OpenError("That node id is not valid.")
    path = _model_path(root, ref)
    if not path.exists():
        if valid_node_id(token):
            return token
        raise OpenError(f"no model to resolve {token!r}. Run `cbi scan` first.")
    conn = store.read_only(path)
    try:
        found = query.resolve(conn, token)
        if len(found) == 1:
            if not valid_node_id(found[0]):
                raise OpenError("That node id is not valid.")
            return found[0]
        if not found:
            if valid_node_id(token):
                return token
            raise OpenError(f"no node matches {token!r}")
        lines = [f"{token!r} matches {len(found)} nodes; pick one by ID"]
        for nid in found:
            row = conn.execute(
                "SELECT display_kind, name, path FROM nodes WHERE id = ?", (nid,)
            ).fetchone()
            if row:
                lines.append(f"  {row[0]:<12} {row[1]}  {row[2] or ''}\n    {nid}")
            else:
                lines.append(f"    {nid}")
        raise OpenError("\n".join(lines))
    finally:
        conn.close()


def _oid(value):
    return isinstance(value, str) and len(value) == 40 and all(ch in "0123456789abcdef" for ch in value)


def _pull_request(root, number):
    """(base oid, head oid) from `gh pr view`. Raises OpenError. Does not guess a missing side."""
    try:
        result = subprocess.run(
            ["gh", "pr", "view", number, "--json", "baseRefOid,headRefOid"],
            cwd=root, capture_output=True, text=True,
        )
    except FileNotFoundError:
        raise OpenError("gh is not on PATH") from None
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "gh failed").strip()
        raise OpenError(detail)
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise OpenError("gh pr view did not return JSON") from None
    if not isinstance(data, dict):
        raise OpenError("gh pr view did not return baseRefOid and headRefOid")
    base, head = data.get("baseRefOid"), data.get("headRefOid")
    if not _oid(base) or not _oid(head):
        raise OpenError("gh pr view did not return baseRefOid and headRefOid")
    files.resolve_commit(root, base)
    files.resolve_commit(root, head)
    return base, head


def open_url(url):
    """Hand a URL to the OS. The URL is one argument, never a shell command.

    macOS uses `open`. Linux uses `xdg-open`. Windows uses `os.startfile`
    when it exists, and `cmd /c start` otherwise. The empty title is required:
    `start` treats the first quoted string as a window title.
    """
    if sys.platform == "win32":
        return _windows_open(url)
    if sys.platform == "darwin":
        return _mac_open(url)
    return _xdg_open(url)


def _windows_open(url):
    startfile = getattr(os, "startfile", None)
    if startfile is not None:
        try:
            startfile(url)
        except OSError as err:
            return 1, str(err)
        return 0, ""
    result = subprocess.run(["cmd", "/c", "start", "", url], capture_output=True, text=True)
    return result.returncode, (result.stderr or result.stdout).strip()


def _xdg_open(url):
    result = subprocess.run(["xdg-open", url], capture_output=True, text=True)
    return result.returncode, (result.stderr or result.stdout).strip()


def _mac_open(url):
    """Hand a URL to Launch Services. Fixed argv, so the URL is never a shell command."""
    result = subprocess.run(["open", url], capture_output=True, text=True)
    return result.returncode, (result.stderr or result.stdout).strip()

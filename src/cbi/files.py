"""Git enumeration, submodules, content hashing, ignore rules and file classification.

git is always run with a fixed argv list, never through a shell. Tracked symlinks
are recorded but never followed.
"""

import hashlib
import json
import os
import posixpath
import re
import stat
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

from cbi.ids import file_id, group_id, local_id, normalise_remote, resolve_relative_url

# Bumped by the parsers when their output changes, so every file is reparsed.
PARSER_VERSION = 2

CODE_LANGS = {
    ".py": "python",
    ".ts": "typescript", ".mts": "typescript", ".cts": "typescript",
    ".tsx": "tsx",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
}
DOC_EXTS = {".md", ".mdx", ".markdown"}
DATA_EXTS = {".json", ".txt", ".csv", ".jsonl"}
MINIFIABLE_EXTS = {".js", ".mjs", ".cjs", ".css"}
TEST_NAME = re.compile(r"^test_.*\.py$|^.*_test\.py$|^.*\.(test|spec)\.[cm]?[jt]sx?$")

DATA_DIR_MIN_FILES = 200  # a data dir has more files than this
DATA_DIR_SHARE = 0.9  # and more than this share of data files
DOC_DIR_MIN_FILES = 100  # a doc collection has more files than this,
DOC_DIR_MAX_CODE = 0.1  # at most this share of code,
DOC_DIR_MIN_DOCS = 0.5  # and at least this share of markdown
MINIFIED_LINE = 1000  # a js or css file with a line this long looks minified

DISPLAY = {"code": "source file", "test": "test file", "doc": "doc", "other": "file"}

BASE_IGNORE = """\
# cbi ignore file, gitignore syntax, paths relative to the repo root.
# Tracked files that match are left out of the model. Edit freely:
# `cbi init` never overwrites this file, and `cbi scan` rescans when it changes.

# Fixtures, eval snapshots and build output
fixtures/
evals/
test-data/
dist*/
build/
*.min.js
*.min.css
"""


class NotARepo(Exception):
    pass


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True).stdout


def _try_git(cwd, *args):
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True)
    return result.stdout.decode().strip() or None if result.returncode == 0 else None


def repo_root(cwd):
    top = _try_git(cwd, "rev-parse", "--show-toplevel")
    if not top:
        raise NotARepo(f"{cwd} is not inside a git repository")
    return Path(top)


# --- ignore rules ---------------------------------------------------------------


def _glob_to_regex(pattern):
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        elif pattern[i] == "[" and "]" in pattern[i + 2 :]:
            end = pattern.index("]", i + 2)
            body = pattern[i + 1 : end]
            out.append("[" + ("^" + body[1:] if body.startswith("!") else body) + "]")
            i = end + 1
        elif pattern[i] == "\\" and i + 1 < len(pattern):
            out.append(re.escape(pattern[i + 1]))
            i += 2
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return "".join(out)


class Ignore:
    """Matches repo-relative paths against gitignore-syntax lines."""

    def __init__(self, text):
        self.rules = []
        for line in text.splitlines():
            line = line.rstrip()
            if not line or line.startswith("#"):
                continue
            negate = line.startswith("!")
            line = line[1:] if negate else line
            line = line[1:] if line.startswith(("\\!", "\\#")) else line
            dir_only = line.endswith("/")
            line = line.rstrip("/")
            anchored = "/" in line
            body = _glob_to_regex(line.lstrip("/"))
            regex = re.compile(body if anchored else "(?:.*/)?" + body)
            self.rules.append((negate, dir_only, regex))
        self._dirs = {}

    def _match(self, path, is_dir):
        ignored = False
        for negate, dir_only, regex in self.rules:
            if (is_dir or not dir_only) and regex.fullmatch(path):
                ignored = not negate
        return ignored

    def _dir_ignored(self, path):
        if path not in self._dirs:
            parent = posixpath.dirname(path)
            self._dirs[path] = (bool(parent) and self._dir_ignored(parent)) or self._match(path, True)
        return self._dirs[path]

    def __call__(self, path, is_dir=False):
        """True if the path, or any directory above it, is ignored."""
        if not self.rules:
            return False
        if is_dir:
            return self._dir_ignored(path)
        parent = posixpath.dirname(path)
        return (bool(parent) and self._dir_ignored(parent)) or self._match(path, False)


# --- enumeration ----------------------------------------------------------------


def _gitmodule_urls(ws_dir):
    """{submodule path: url} from the workspace's .gitmodules."""
    out = subprocess.run(
        ["git", "config", "-f", ".gitmodules", "-z", "--get-regexp", r"^submodule\..*\.(path|url)$"],
        cwd=ws_dir, capture_output=True,
    ).stdout.decode()
    by_name = defaultdict(dict)
    for record in filter(None, out.split("\0")):
        key, _, value = record.partition("\n")
        name, _, field = key[len("submodule."):].rpartition(".")
        by_name[name][field] = value
    return {entry["path"]: entry.get("url") for entry in by_name.values() if "path" in entry}


def enumerate_repo(root, ignore=None):
    """List workspaces and tracked files of the repo and every initialised submodule.

    Returns (workspaces, files). A workspace is a dict; `root` is its path from the
    top repo ("" for the top repo) and `mount` its path inside its parent workspace.
    Each file is (top-relative path, workspace, workspace-relative path).
    """
    ignore = ignore or Ignore("")
    workspaces, files = [], []

    def walk(rel_root, url, parent, mount, pinned, initialised):
        ws_dir = root / rel_root if rel_root else root
        ws_id = normalise_remote(url) if url else local_id(posixpath.basename(mount) if mount else root.name)
        head = _try_git(ws_dir, "rev-parse", "HEAD") if initialised else None
        ws = {
            "id": ws_id,
            "root": rel_root,
            "mount": mount,
            "name": posixpath.basename(mount) if mount else root.name,
            "parent": parent,
            "attrs": {
                "remote": ws_id if url else None,
                "pinned_commit": pinned,
                "checked_out_commit": head,
                "drift": bool(pinned and head and pinned != head),
                "initialised": initialised,
                "root": rel_root,
            },
        }
        workspaces.append(ws)
        if not initialised:
            return
        submodules, seen = [], set()
        for record in _git(ws_dir, "ls-files", "-s", "-z").split(b"\0"):
            if not record:
                continue
            info, _, raw_path = record.partition(b"\t")
            path = os.fsdecode(raw_path)
            if path in seen:  # merge conflicts list one path per stage
                continue
            seen.add(path)
            top = f"{rel_root}/{path}" if rel_root else path
            mode, sha = info.split(b" ")[:2]
            if mode == b"160000":
                if not ignore(top, is_dir=True):
                    submodules.append((path, top, sha.decode()))
            elif not ignore(top):
                files.append((top, ws, path))
        gitmodules = None
        for path, top, sha in submodules:
            sub_dir = ws_dir / path
            sub_init = (sub_dir / ".git").exists()
            sub_url = _try_git(sub_dir, "config", "--get", "remote.origin.url") if sub_init else None
            if not sub_url:
                if gitmodules is None:
                    gitmodules = _gitmodule_urls(ws_dir)
                sub_url = gitmodules.get(path)
                sub_url = sub_url and resolve_relative_url(sub_url, url)
            walk(top, sub_url, ws, path, sha, sub_init)

    walk("", _try_git(root, "config", "--get", "remote.origin.url"), None, None, None, True)
    return workspaces, files


def hash_files(root, files, old_states):
    """Hash the working-tree content of each file, reusing old hashes when stat matches.

    Returns {top path: (mtime_ns, size, content_hash, parser_version, is_symlink)}.
    Tracked files missing from disk are left out. Symlinks hash their target text.
    """
    states = {}
    for top, _, _ in files:
        full = root / top
        try:
            st = os.lstat(full)
        except FileNotFoundError:
            continue
        is_link = stat.S_ISLNK(st.st_mode)
        if not is_link and not stat.S_ISREG(st.st_mode):
            continue
        old = old_states.get(top)
        if old and old[0] == st.st_mtime_ns and old[1] == st.st_size:
            digest = old[2]
        elif is_link:
            digest = hashlib.sha1(os.fsencode(os.readlink(full))).hexdigest()
        else:
            with open(full, "rb") as f:
                digest = hashlib.file_digest(f, "sha1").hexdigest()
        states[top] = (st.st_mtime_ns, st.st_size, digest, PARSER_VERSION, is_link)
    return states


# --- classification -------------------------------------------------------------


def classify(path):
    """Return (role, lang): role is code, test, doc or other."""
    name = posixpath.basename(path)
    ext = posixpath.splitext(name)[1].lower()
    if ext in DOC_EXTS:
        return "doc", "markdown"
    lang = CODE_LANGS.get(ext)
    if not lang:
        return "other", None
    if TEST_NAME.match(name) or "__tests__" in path.split("/"):
        return "test", lang
    return "code", lang


def _ancestors(path):
    while (path := posixpath.dirname(path)):
        yield path


def _heavy_dirs(paths, tag, min_files, keep):
    """Outermost directories with more than min_files files whose tag counts pass keep(counts, total)."""
    counts = defaultdict(Counter)
    for path in paths:
        t = tag(path)
        for d in _ancestors(path):
            counts[d][t] += 1
    found = set()
    for d in sorted(counts):
        total = counts[d].total()
        if total > min_files and keep(counts[d], total) and not any(a in found for a in _ancestors(d)):
            found.add(d)
    return sorted(found)


def doc_collections(paths):
    return set(_heavy_dirs(
        paths, lambda p: classify(p)[0], DOC_DIR_MIN_FILES,
        lambda c, total: c["code"] + c["test"] <= DOC_DIR_MAX_CODE * total and c["doc"] >= DOC_DIR_MIN_DOCS * total,
    ))


def _escape(path):
    return re.sub(r"([*?\[\\])", r"\\\1", path)


def _looks_minified(full):
    try:
        if os.lstat(full).st_size <= MINIFIED_LINE or os.path.islink(full):
            return False
        with open(full, "rb") as f:
            return any(len(line) >= MINIFIED_LINE for line in f)
    except OSError:
        return False


def default_ignore(root):
    """Text of a fresh .cbi/ignore: fixed patterns plus data dirs and minified files found in the repo."""
    _, files = enumerate_repo(root, Ignore(BASE_IGNORE))
    paths = [top for top, _, _ in files]
    data_dirs = _heavy_dirs(
        paths, lambda p: posixpath.splitext(p)[1].lower() in DATA_EXTS, DATA_DIR_MIN_FILES,
        lambda c, total: c[True] > DATA_DIR_SHARE * total,
    )
    in_data = Ignore("\n".join(f"/{_escape(d)}/" for d in data_dirs))
    minified = [
        p for p in paths
        if posixpath.splitext(p)[1].lower() in MINIFIABLE_EXTS and not in_data(p) and _looks_minified(root / p)
    ]
    text = BASE_IGNORE
    text += "\n# Directories of mostly data files (json, txt, csv, jsonl)\n"
    text += "".join(f"/{_escape(d)}/\n" for d in data_dirs)
    text += "\n# Files with minified-looking lines\n"
    text += "".join(f"/{_escape(p)}\n" for p in minified)
    return text


# --- nodes ----------------------------------------------------------------------


def _parent_id(ws_id, path):
    d = posixpath.dirname(path)
    return group_id(ws_id, d) if d else ws_id


def build_nodes(workspaces, files, states):
    """Workspace, group and file nodes for the enumerated files present on disk."""
    nodes = []
    by_ws = defaultdict(list)
    for top, ws, rel in files:
        if top in states:
            by_ws[id(ws)].append((top, rel))
    children = defaultdict(list)
    for ws in workspaces:
        if ws["parent"]:
            children[id(ws["parent"])].append(ws)

    for ws in workspaces:
        wid, parent = ws["id"], ws["parent"]
        nodes.append({
            "id": wid,
            "parent_id": _parent_id(parent["id"], ws["mount"]) if parent else None,
            "kind": "workspace",
            "display_kind": "workspace",
            "name": ws["name"],
            "workspace_id": parent["id"] if parent else None,
            "path": ws["mount"] or "",
            "attrs": ws["attrs"],
        })
        ws_files = by_ws[id(ws)]
        collections = doc_collections([rel for _, rel in ws_files])
        dirs = {d for _, rel in ws_files for d in _ancestors(rel)}
        dirs |= {d for sub in children[id(ws)] for d in _ancestors(sub["mount"])}
        for d in dirs:
            nodes.append({
                "id": group_id(wid, d),
                "parent_id": _parent_id(wid, d),
                "kind": "group",
                "display_kind": "doc collection" if d in collections else "folder",
                "name": posixpath.basename(d),
                "workspace_id": wid,
                "path": d,
            })
        for top, rel in ws_files:
            _, _, digest, _, is_link = states[top]
            role, lang = classify(rel)
            nodes.append({
                "id": file_id(wid, rel),
                "parent_id": _parent_id(wid, rel),
                "kind": "doc" if role == "doc" and not is_link else "file",
                "display_kind": "symlink" if is_link else DISPLAY[role],
                "name": posixpath.basename(rel),
                "workspace_id": wid,
                "path": rel,
                "lang": None if is_link else lang,
                "content_hash": digest,
                "attrs": {"role": role, "symlink": True} if is_link else {"role": role},
            })
    return nodes


def fingerprint(workspaces, ignore_text, structure_text):
    """Everything besides file hashes that decides whether a rescan is needed."""
    sha = lambda text: hashlib.sha1((text or "").encode()).hexdigest()
    return json.dumps({
        "ignore": sha(ignore_text),
        "structure": sha(structure_text),
        "parser_version": PARSER_VERSION,
        "workspaces": [
            [ws["id"], ws["root"], ws["attrs"]["pinned_commit"], ws["attrs"]["checked_out_commit"], ws["attrs"]["initialised"]]
            for ws in workspaces
        ],
    }, sort_keys=True)

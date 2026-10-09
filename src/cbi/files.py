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

from cbi.ids import file_id, group_id, local_id, normalise_remote, repo_name, resolve_relative_url

# Bumped by the parsers when their output changes, so every file is reparsed.
PARSER_VERSION = 18

CODE_LANGS = {
    ".py": "python",
    ".ts": "typescript", ".mts": "typescript", ".cts": "typescript",
    ".tsx": "tsx",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".cs": "csharp",
    ".vue": "vue",
}
DOC_EXTS = {".md", ".mdx", ".markdown"}
DATA_EXTS = {".json", ".txt", ".csv", ".jsonl"}
DUMP_EXTS = DATA_EXTS | {".sql"}
NAMED_DATA_DIRS = {"fixtures", "test-data"}
MINIFIABLE_EXTS = {".js", ".mjs", ".cjs", ".css"}
TEST_NAME = re.compile(
    r"^test_.*\.py$|^.*_test\.py$|^.*\.(test|spec)\.[cm]?[jt]sx?$|^.*\.cy\.[cm]?[jt]sx?$"
)

DATA_DIR_MIN_FILES = 200  # a data dir has more files than this
DATA_DIR_SHARE = 0.9  # and more than this share of data files
DOC_DIR_MIN_FILES = 100  # a doc collection has more files than this,
DOC_DIR_MAX_CODE = 0.1  # at most this share of code,
DOC_DIR_MIN_DOCS = 0.5  # and at least this share of markdown
MINIFIED_LINE = 1000  # a js or css file looks minified when lines this long
MINIFIED_SHARE = 0.5  # hold more than this share of its bytes

DISPLAY = {"code": "source file", "test": "test file", "doc": "doc", "other": "file"}
# Real env files hold secrets. Example and sample files are the only forms that are read.
ENV_EXAMPLES = {".env.example", ".env.sample"}

BASE_IGNORE = """\
# cbi ignore file, gitignore syntax, paths relative to the repo root.
# Tracked files that match are left out of the model. Edit freely:
# `cbi init` never overwrites this file, and `cbi scan` rescans when it changes.

# Eval snapshots and build output. fixtures/ and test-data/ are added below
# when most of their files are data, so a directory of source stays in the model.
evals/
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


def main_worktree_dirname(root):
    """Folder name of the main worktree. A linked worktree does not use its own folder."""
    common = _try_git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if common:
        path = Path(common)
        if path.name == ".git" and path.parent.name:
            return path.parent.name
    return Path(root).name


def workspace_title(root, url, mount=None):
    """Name shown for a workspace.

    The remote's repository name when there is one. Otherwise the main worktree's
    folder name. A submodule with no remote keeps the directory it is mounted at.
    """
    name = repo_name(url) if url else None
    if name:
        return name
    if mount:
        return posixpath.basename(mount)
    return main_worktree_dirname(root)


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
            "name": workspace_title(root, url, mount),
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
    content_hash is the git blob id of the raw bytes (no clean filter), so a clean
    file matches `git rev-parse HEAD:path` and a ref scan of the same blob.
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
        if is_private_env(top):
            continue  # never open a real env file, so it stays out of the model
        old = old_states.get(top)
        if old and old[0] == st.st_mtime_ns and old[1] == st.st_size:
            digest = old[2]
        elif is_link:
            digest = blob_id(os.fsencode(os.readlink(full)))
        else:
            with open(full, "rb") as f:
                digest = blob_id_file(f)
        states[top] = (st.st_mtime_ns, st.st_size, digest, PARSER_VERSION, is_link)
    return states


# --- classification -------------------------------------------------------------


def is_private_env(path):
    """True for `.env` and `.env.<anything>` other than `.env.example` and `.env.sample`.

    Nothing in a scan may open these: their values are never read or stored.
    """
    name = posixpath.basename(path)
    return name == ".env" or (name.startswith(".env.") and name not in ENV_EXAMPLES)


def _cs_test_project(path):
    """A test or test-helper project: `*Tests.csproj` or `*Testing.csproj`.

    `Foo.IntegrationTests` and `Foo.UnitTests` count, not only `Foo.Tests`.
    """
    name = posixpath.basename(path).lower()
    return name.endswith("tests.csproj") or name.endswith("testing.csproj")


def cs_test_roots(paths):
    """Directories of test projects, longest first. A project file at the repo root is not a root."""
    roots = []
    for path in paths:
        if _cs_test_project(path):
            directory = posixpath.dirname(path)
            if directory:
                roots.append(directory)
    return sorted(set(roots), key=len, reverse=True)


def _under_root(path, roots):
    return any(path == root or path.startswith(root + "/") for root in roots)


def _cypress_e2e(path):
    """True when a path sits under a `cypress/e2e` directory."""
    parts = posixpath.normpath(path).split("/")
    return any(left == "cypress" and right == "e2e" for left, right in zip(parts, parts[1:]))


def classify(path, test_roots=()):
    """Return (role, lang): role is code, test, doc or other.

    `test_roots` are directories of `*Tests.csproj` and `*Testing.csproj`. A `.cs`
    file under one of them is a test, as is a file named `*Test.cs` or `*Tests.cs`.
    `*.cy.ts` and `*.cy.js` are Cypress specs, and so is any code file under a
    `cypress/e2e` directory. `cypress/support` stays code: it defines commands.
    """
    name = posixpath.basename(path)
    ext = posixpath.splitext(name)[1].lower()
    if ext in DOC_EXTS:
        return "doc", "markdown"
    lang = CODE_LANGS.get(ext)
    if not lang:
        return "other", None
    if (TEST_NAME.match(name) or "__tests__" in path.split("/") or _cypress_e2e(path)
            or re.search(r"Tests?\.cs$", name) or _under_root(path, test_roots)):
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
            lines = [len(line) for line in f]
        return sum(n for n in lines if n >= MINIFIED_LINE) > MINIFIED_SHARE * sum(lines)
    except OSError:
        return False


def _named_data_dirs(paths):
    """fixtures/ and test-data/ directories whose files are mostly data, not code.

    A file counts for every such directory above it. Most means more than half of the
    files are json, csv, txt, jsonl or sql. A directory of TypeScript or C# is kept.
    """
    groups = defaultdict(list)
    for path in paths:
        parts = path.split("/")
        for i, name in enumerate(parts[:-1]):
            if name in NAMED_DATA_DIRS:
                groups["/".join(parts[: i + 1])].append(path)
    found = []
    for directory, files in groups.items():
        data = sum(1 for path in files if posixpath.splitext(path)[1].lower() in DUMP_EXTS)
        if data * 2 > len(files):
            found.append(directory)
    kept = []
    for directory in sorted(found):
        if any(directory.startswith(parent + "/") for parent in kept):
            continue
        kept.append(directory)
    return kept


def default_ignore(root):
    """Text of a fresh .cbi/ignore: fixed patterns plus data dirs and minified files found in the repo."""
    _, files = enumerate_repo(root, Ignore(BASE_IGNORE))
    paths = [top for top, _, _ in files]
    named = _named_data_dirs(paths)
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
    text += "\n# fixtures/ and test-data/ when most of their files are data (json, csv, txt, sql)\n"
    text += "".join(f"/{_escape(d)}/\n" for d in named)
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
        test_roots = cs_test_roots(rel for _, rel in ws_files)
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
            role, lang = classify(rel, test_roots)
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


def ignore_token(text):
    """Identity of an ignore file, structure file, concepts file or screens file."""
    return hashlib.sha1((text or "").encode()).hexdigest()


def fingerprint(workspaces, ignore_text, structure_text, concepts_text=None, screens_text=None,
                 answers_text=None, *, team=False):
    """Everything besides file hashes that decides whether a rescan is needed.

    Team mode also hashes answers.jsonl. Leaving it out keeps a non-team fingerprint
    the same as before team mode existed.
    """
    payload = {
        "ignore": ignore_token(ignore_text),
        "structure": ignore_token(structure_text),
        "concepts": ignore_token(concepts_text),
        "screens": ignore_token(screens_text),
        "parser_version": PARSER_VERSION,
        "workspaces": [
            [ws["id"], ws["root"], ws["name"], ws["attrs"]["pinned_commit"],
             ws["attrs"]["checked_out_commit"], ws["attrs"]["initialised"]]
            for ws in workspaces
        ],
    }
    if team:
        payload["answers"] = ignore_token(answers_text)
    return json.dumps(payload, sort_keys=True)


def blob_id(data):
    """Git blob object id of raw bytes. Matches `git hash-object` with no filters."""
    header = f"blob {len(data)}\0".encode()
    return hashlib.sha1(header + data).hexdigest()


def blob_id_file(handle):
    """blob_id of an open binary file, read from the start."""
    handle.seek(0, os.SEEK_END)
    size = handle.tell()
    handle.seek(0)
    digest = hashlib.sha1()
    digest.update(f"blob {size}\0".encode())
    while chunk := handle.read(1 << 20):
        digest.update(chunk)
    return digest.hexdigest()


# --- commits, without a checkout ------------------------------------------------


class BadRef(Exception):
    pass


def resolve_commit(root, ref):
    """The full commit SHA a branch, tag or commit names. Does not touch the worktree."""
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}"],
        cwd=root, capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise BadRef(f"unknown ref {ref}")
    return result.stdout.strip()


def _abs_git(root, *args):
    text = _try_git(root, *args)
    if not text:
        return None
    path = Path(text)
    if not path.is_absolute():
        path = Path(root) / path
    return path.resolve()


def _git_bytes(git_dir, *args):
    return subprocess.run(
        ["git", "--git-dir", str(git_dir), *args], check=True, capture_output=True,
    ).stdout


def _ls_tree(git_dir, sha):
    """(mode, type, oid, path) for every blob and gitlink at sha. No checkout."""
    raw = _git_bytes(git_dir, "ls-tree", "-r", "-z", sha)
    for record in raw.split(b"\0"):
        if not record:
            continue
        meta, path = record.split(b"\t", 1)
        mode, kind, oid = meta.decode().split(" ")
        yield mode, kind, oid, os.fsdecode(path)


def _parse_gitmodules(text):
    """{submodule path: url} from a .gitmodules blob. Missing fields are left out."""
    urls, path, url = {}, None, None

    def flush():
        if path:
            urls[path] = url

    for line in text.splitlines():
        line = line.strip()
        if line.startswith("[submodule "):
            flush()
            path, url = None, None
        elif line.startswith("path ") or line.startswith("path="):
            path = line.split("=", 1)[1].strip()
        elif line.startswith("url ") or line.startswith("url="):
            url = line.split("=", 1)[1].strip()
    flush()
    return urls


class _Batch:
    """One long-running `git cat-file --batch` for a single object database."""

    def __init__(self, git_dir):
        self.proc = subprocess.Popen(
            ["git", "--git-dir", str(git_dir), "cat-file", "--batch"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        )
        self.cache = {}

    def get(self, oid):
        if oid not in self.cache:
            self.proc.stdin.write(f"{oid}\n".encode())
            self.proc.stdin.flush()
            header = self.proc.stdout.readline()
            if not header:
                raise OSError(f"git cat-file closed while reading {oid}")
            parts = header.split()
            if len(parts) < 3 or parts[1] == b"missing":
                self.cache[oid] = None
            else:
                size = int(parts[2])
                data = self.proc.stdout.read(size)
                self.proc.stdout.read(1)  # the newline cat-file writes after the body
                self.cache[oid] = data
        return self.cache[oid]

    def close(self):
        if self.proc.poll() is None:
            self.proc.stdin.close()
            self.proc.wait()


class GitPath:
    """A path inside a CommitTree. `/` joins; read_bytes and read_text come from cat-file."""

    def __init__(self, tree, rel):
        self.tree, self.rel = tree, rel

    def __truediv__(self, other):
        other = str(other).replace("\\", "/")
        if other in ("", "."):
            return GitPath(self.tree, self.rel)
        joined = posixpath.normpath(posixpath.join(self.rel, other) if self.rel else other)
        if joined == ".":
            joined = ""
        return GitPath(self.tree, joined)

    def read_bytes(self):
        if self.rel == ".." or self.rel.startswith("../"):
            raise FileNotFoundError(self.rel)
        return self.tree.read(self.rel)

    def read_text(self, encoding="utf-8", errors=None):
        return self.read_bytes().decode(encoding, errors or "strict")


class CommitTree:
    """The file tree of one commit, read from git objects.

    `workspaces` and `tracked` match enumerate_repo. `blobs` maps a top-relative
    path to (git dir, blob oid); the oid is the content hash. One cat-file
    process stays open per object database (the superproject, and each submodule
    whose gitlink we can read). Private env files are omitted and never read.
    """

    def __init__(self, root, sha, ignore=None):
        self.root = Path(root)
        self.sha = sha
        self.ignore = ignore or Ignore("")
        self.git_dir = _abs_git(root, "rev-parse", "--absolute-git-dir") or _abs_git(root, "rev-parse", "--git-dir")
        self.common_dir = _abs_git(root, "rev-parse", "--git-common-dir")
        self.origin = _try_git(root, "config", "--get", "remote.origin.url")
        self.batches = {}
        self.blobs = {}
        self.links = set()
        self.workspaces = []
        self.tracked = []
        try:
            self._walk("", sha, self.git_dir, self.origin, None, None, None)
        except Exception:
            self.close()
            raise

    def __truediv__(self, other):
        return GitPath(self, "") / other

    def _batch(self, git_dir):
        key = str(Path(git_dir).resolve())
        if key not in self.batches:
            self.batches[key] = _Batch(key)
        return self.batches[key]

    def read(self, rel):
        found = self.blobs.get(rel.strip("/"))
        if not found:
            raise FileNotFoundError(rel)
        data = self._batch(found[0]).get(found[1])
        if data is None:
            raise FileNotFoundError(rel)
        return data

    def close(self):
        for batch in self.batches.values():
            batch.close()
        self.batches.clear()

    def file_states(self):
        """{top path: (mtime_ns, size, blob id, parser version, is_symlink)} for the pipeline."""
        return {
            top: (0, 0, oid, PARSER_VERSION, top in self.links)
            for top, (_, oid) in self.blobs.items()
        }

    def _sub_git_dir(self, git_dir, path):
        base = self.common_dir if Path(git_dir).resolve() == Path(self.git_dir).resolve() else Path(git_dir)
        candidate = Path(base) / "modules" / path
        return candidate if candidate.is_dir() else None

    def _is_commit(self, git_dir, sha):
        result = subprocess.run(
            ["git", "--git-dir", str(git_dir), "cat-file", "-t", sha],
            capture_output=True, text=True,
        )
        return result.returncode == 0 and result.stdout.strip() == "commit"

    def _workspace(self, rel_root, sha, url, parent, mount, pinned, initialised):
        ws_id = normalise_remote(url) if url else local_id(
            posixpath.basename(mount) if mount else self.root.name)
        # A ref model is the tree at this commit, not a checkout, so a submodule
        # mapped at its gitlink does not drift.
        return {
            "id": ws_id,
            "root": rel_root,
            "mount": mount,
            "name": workspace_title(self.root, url, mount),
            "parent": parent,
            "attrs": {
                "remote": ws_id if url else None,
                "pinned_commit": pinned,
                "checked_out_commit": sha if initialised else None,
                "drift": False,
                "initialised": initialised,
                "root": rel_root,
            },
        }

    def _walk(self, rel_root, sha, git_dir, url, parent, mount, pinned):
        entries = list(_ls_tree(git_dir, sha))
        gitmodules = {}
        for _mode, kind, oid, path in entries:
            if path == ".gitmodules" and kind == "blob":
                data = self._batch(git_dir).get(oid)
                if data:
                    gitmodules = _parse_gitmodules(data.decode(errors="replace"))
                break
        ws = self._workspace(rel_root, sha, url, parent, mount, pinned, True)
        self.workspaces.append(ws)
        subs = []
        for mode, kind, oid, path in entries:
            top = f"{rel_root}/{path}" if rel_root else path
            if kind == "commit" or mode == "160000":
                if not self.ignore(top, is_dir=True):
                    subs.append((path, top, oid))
                continue
            if self.ignore(top) or is_private_env(top):
                continue
            self.tracked.append((top, ws, path))
            self.blobs[top] = (str(Path(git_dir).resolve()), oid)
            if mode == "120000":
                self.links.add(top)
        for path, top, oid in subs:
            sub_url = gitmodules.get(path)
            sub_url = sub_url and resolve_relative_url(sub_url, url)
            sub_git = self._sub_git_dir(git_dir, path)
            if sub_git and self._is_commit(sub_git, oid):
                self._walk(top, oid, sub_git, sub_url, ws, path, oid)
            else:
                self.workspaces.append(self._workspace(top, None, sub_url, ws, path, oid, False))


# --- worktrees and branches -----------------------------------------------------


def _lane_handles(root):
    """Worktree directory names recorded under local git config cbi.worktree.<handle>."""
    raw = _try_git(root, "config", "--local", "--get-regexp", r"^cbi\.worktree\.")
    handles = set()
    for line in (raw or "").splitlines():
        key, _, _value = line.partition(" ")
        rest = key.removeprefix("cbi.worktree.")
        handle, dot, _field = rest.rpartition(".")
        if dot and handle:
            handles.add(handle)
    return handles


def _worktree_list(root):
    raw = _git(root, "worktree", "list", "--porcelain").decode()
    items, cur = [], {}
    for line in raw.splitlines():
        if line.startswith("worktree "):
            if cur.get("head"):
                items.append(cur)
            cur = {"path": line[len("worktree "):], "branch": None, "head": None}
        elif line.startswith("HEAD "):
            cur["head"] = line[len("HEAD "):]
        elif line.startswith("branch "):
            cur["branch"] = line[len("branch "):].removeprefix("refs/heads/")
        elif line == "detached":
            cur["branch"] = None
    if cur.get("head"):
        items.append(cur)
    return items


def _local_branches(root):
    raw = _git(root, "for-each-ref", "--format=%(refname:short)%00%(objectname)", "refs/heads").decode()
    branches = []
    for line in raw.splitlines():
        if line:
            name, _, head = line.partition("\0")
            branches.append((name, head))
    return branches


def inventory(root, model_dir):
    """Worktrees and local branches for `cbi worktrees`.

    A worktree model is that worktree's own `.cbi/model.db`. A branch has a ref
    model when `<model dir>/refs/<head>/model.db` exists. `model_complete` means
    the model has no open or blocked task. The lane is the worktree's directory
    name when local git config has cbi.worktree.<handle> for it, otherwise the
    branch name.
    """
    from cbi.store import model_flags

    root = Path(root)
    here = root.resolve()
    handles = _lane_handles(root)
    current_branch = _try_git(root, "symbolic-ref", "--short", "HEAD")
    worktrees = []
    branch_lane = {}
    for item in _worktree_list(root):
        path = Path(item["path"])
        name = path.name
        branch = item["branch"]
        lane = name if name in handles else branch
        if name in handles and branch:
            branch_lane[branch] = name
        has_model, complete = model_flags(path / ".cbi" / "model.db")
        worktrees.append({
            "path": str(path),
            "branch": branch,
            "head": item["head"],
            "lane": lane,
            "has_model": has_model,
            "model_complete": complete,
            "current": path.resolve() == here,
        })
    worktrees.sort(key=lambda w: (not w["current"], w["path"]))
    branches = []
    for name, head in _local_branches(root):
        branches.append({
            "name": name,
            "head": head,
            "lane": branch_lane.get(name, name),
            "has_ref_model": (Path(model_dir) / "refs" / head / "model.db").exists(),
            "current": name == current_branch,
        })
    branches.sort(key=lambda b: (not b["current"], b["name"]))
    return {"worktrees": worktrees, "branches": branches}

"""Open one file in an editor.

`cbi open-file` and the desktop app use the same command shape. A template
is split into argv first, then `{project}`, `{file}` and `{line}` are
substituted, so a path with spaces stays one argument and nothing is run
through a shell.

VS Code: `code --reuse-window {project} --goto {file}:{line}`.
The static viewer cannot run a command. It uses `vscode://file/<path>:<line>`
(or Cursor's scheme) for a file on disk. A ref view copies `git show`
instead of opening a link. That URL is built in the viewer; this module
builds the argv the CLI runs.

A ref is opened from a worktree that already has that branch or commit.
Otherwise the bytes come from `git show <sha>:<path>` into a read-only
snapshot outside the repository. Nothing is checked out or switched.
"""

import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

from cbi import files, query

EDITORS = ("vscode", "cursor", "none")
TEMPLATES = {
    "vscode": "code --reuse-window {project} --goto {file}:{line}",
    "cursor": "cursor --reuse-window {project} --goto {file}:{line}",
}
# Display kinds that are one file. Folders, concepts, deployables, packages
# and externals are not in this set. A grey node is one of these symbols
# drawn in another concept; the viewer treats that as the same open.
OPEN_DISPLAY_KINDS = frozenset({
    "file", "source file", "test file",
    "class", "function", "method", "component", "interface",
    "test case",
})
CLOSED_KINDS = frozenset({
    "concept", "group", "deployable", "package", "external",
    "workspace", "env", "screen", "doc",
})
NOT_CHECKED_OUT = "This file is not checked out."
NOT_ON_DISK = "This file is not on disk."
NOT_IN_COMMIT = "This file is not in that commit."
OUTSIDE = "That path is outside the project."
NO_EDITOR = "No editor is configured."
BAD_COMMIT = "That commit is not a snapshot we can open."
_SHA = re.compile(r"^[0-9a-fA-F]{40}$")
_BIN_LABEL = {"code": "VS Code", "cursor": "Cursor"}
_MAC_APP = {
    "code": "Visual Studio Code.app/Contents/Resources/app/bin/code",
    "cursor": "Cursor.app/Contents/Resources/app/bin/cursor",
}


class EditorError(Exception):
    def __init__(self, message, code=1):
        super().__init__(message)
        self.code = code


def opens_in_editor(kind, display_kind, path):
    """True when this node is one file the editor can open."""
    if not path or not isinstance(path, str):
        return False
    if kind in CLOSED_KINDS:
        return False
    return display_kind in OPEN_DISPLAY_KINDS


def split_template(template):
    """Split a command template into argv. Quotes group one argument. No shell."""
    if not isinstance(template, str) or not template.strip():
        raise EditorError("The editor command is empty.", code=2)
    tokens, buf = [], []
    quote = None
    escape = False
    for ch in template:
        if escape:
            buf.append(ch)
            escape = False
            continue
        if ch == "\\" and quote != "'":
            escape = True
            continue
        if quote:
            if ch == quote:
                quote = None
            else:
                buf.append(ch)
            continue
        if ch in ("'", '"'):
            quote = ch
            continue
        if ch.isspace():
            if buf:
                tokens.append("".join(buf))
                buf = []
            continue
        buf.append(ch)
    if escape:
        buf.append("\\")
    if quote:
        raise EditorError("The editor command has an unclosed quote.", code=2)
    if buf:
        tokens.append("".join(buf))
    if not tokens:
        raise EditorError("The editor command is empty.", code=2)
    return tokens


def _subst(token, project, file, line):
    keys = {"{project}": project, "{file}": file, "{line}": line}
    out, i = [], 0
    while i < len(token):
        matched = False
        for key, value in keys.items():
            if token.startswith(key, i):
                out.append(value)
                i += len(key)
                matched = True
                break
        if not matched:
            out.append(token[i])
            i += 1
    return "".join(out)


def fill_template(template, project, file, line):
    """argv for template after `{project}`, `{file}` and `{line}` are filled in."""
    line_s = str(line if line else 1)
    return [_subst(token, str(project), str(file), line_s) for token in split_template(template)]


def _executable(path):
    try:
        candidate = Path(path)
        return candidate.is_file() and os.access(candidate, os.X_OK)
    except OSError:
        return False


def mac_candidates(name, home):
    """App-bundle binaries used when `code` or `cursor` is not on PATH."""
    rel = _MAC_APP.get(name)
    if not rel:
        return []
    roots = [Path("/Applications"), Path(home) / "Applications"]
    return [root / rel for root in roots]


def find_program(name, *, path_env, home, is_executable=None):
    """Absolute path of name on PATH, else the macOS app bundle, else None."""
    check = _executable if is_executable is None else is_executable
    for directory in (path_env or "").split(os.pathsep):
        if not directory:
            continue
        candidate = str(Path(directory) / name)
        if check(candidate):
            return candidate
    for candidate in mac_candidates(name, home):
        if check(str(candidate)):
            return str(candidate)
    return None


def resolve_program(token, *, path_env, home, is_executable=None):
    """argv[0]: an absolute path is used as given; a bare name is looked up."""
    check = _executable if is_executable is None else is_executable
    if "/" in token or "\\" in token:
        if check(token):
            return token
        raise EditorError(f"The editor command was not found: {token}")
    found = find_program(token, path_env=path_env, home=home, is_executable=check)
    if found:
        return found
    label = _BIN_LABEL.get(token)
    if label:
        raise EditorError(f"{label} was not found. Install it, or set a custom editor command.")
    raise EditorError(f"The editor command was not found: {token}")


def template_text(editor, template):
    if template:
        return template
    if editor == "none":
        raise EditorError(NO_EDITOR)
    try:
        return TEMPLATES[editor]
    except KeyError:
        raise EditorError(f"Unknown editor {editor}.", code=2) from None


def command_argv(editor, template, project, file, line, *, path_env=None, home=None, is_executable=None):
    """The argv that opens file:line in project. The program is an absolute path."""
    if path_env is None:
        path_env = os.environ.get("PATH", "")
    if home is None:
        home = str(Path.home())
    argv = fill_template(template_text(editor, template), project, file, line)
    argv[0] = resolve_program(argv[0], path_env=path_env, home=home, is_executable=is_executable)
    return argv


def _safe_parts(rel_path):
    """Repo-relative parts. `..`, an absolute path, or a null is refused."""
    if not isinstance(rel_path, str) or "\x00" in rel_path:
        raise EditorError("This item has no file.")
    rel = rel_path.strip().replace("\\", "/")
    if not rel or rel.startswith("/") or (len(rel) >= 2 and rel[1] == ":"):
        raise EditorError(OUTSIDE)
    parts = []
    for part in rel.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            raise EditorError(OUTSIDE)
        parts.append(part)
    if not parts:
        raise EditorError("This item has no file.")
    return parts


def _line_number(line):
    number = int(line) if line else 1
    return number if number >= 1 else 1


def resolve_target(rel_path, line, *, project, worktree, ref, exists=None):
    """Absolute project and file to open inside one directory.

    project is the folder handed to the editor. worktree is where the file
    is looked up. `ref` only changes the error when that directory does not
    have the file; a ref open uses `resolve_ref_target` instead.
    """
    check = Path.exists if exists is None else exists
    parts = _safe_parts(rel_path)
    root = Path(worktree).resolve()
    candidate = root.joinpath(*parts).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        raise EditorError(OUTSIDE) from None
    if candidate == root:
        raise EditorError("This item has no file.")
    number = _line_number(line)
    if check(candidate):
        return {"project": str(Path(project).resolve()), "file": str(candidate), "line": number}
    raise EditorError(NOT_CHECKED_OUT if ref else NOT_ON_DISK)


def _commit_sha(sha):
    if not isinstance(sha, str) or not _SHA.fullmatch(sha):
        raise EditorError(BAD_COMMIT)
    return sha.lower()


def snapshot_component(text):
    """One path segment. Slashes and `..` cannot leave the snapshot directory."""
    raw = str(text or "").replace("\\", "-")
    while ".." in raw:
        raw = raw.replace("..", ".")
    raw = raw.replace("/", "-")
    cleaned = re.sub(r"[^A-Za-z0-9._+-]+", "-", raw).strip(".-")
    return (cleaned or "ref")[:80]


def snapshot_notice(branch, sha):
    label = branch or sha[:12]
    return f"Opened a read-only copy from {label} ({sha[:7]}); not checked out locally."


def snapshot_cache(cache_dir=None, home=None):
    """Where read-only copies live. Tests set `CBI_SNAPSHOT_DIR` or cache_dir."""
    if cache_dir:
        return Path(cache_dir)
    env = os.environ.get("CBI_SNAPSHOT_DIR")
    if env:
        return Path(env)
    base = Path(home) if home else Path.home()
    return base / "Library" / "Caches" / "codebase-inspector" / "snapshots"


def repo_snapshot_name(repo):
    return snapshot_component(files.main_worktree_dirname(Path(repo)))


def parse_worktrees(text):
    """`git worktree list --porcelain` rows: path, branch name, full HEAD."""
    items, cur = [], {}
    for line in (text or "").splitlines():
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


def git_worktrees(repo):
    result = subprocess.run(
        ["git", "-C", str(repo), "worktree", "list", "--porcelain"],
        capture_output=True,
    )
    if result.returncode != 0:
        raise EditorError("Could not list worktrees.")
    return parse_worktrees(result.stdout.decode())


def git_show_blob(repo, sha, rel):
    """Bytes of `git show <sha>:<path>`. No checkout and no smudge filter."""
    result = subprocess.run(
        ["git", "-C", str(repo), "--no-pager", "show", "--no-textconv", f"{sha}:{rel}"],
        capture_output=True,
    )
    if result.returncode != 0:
        raise EditorError(NOT_IN_COMMIT)
    return result.stdout


def branch_name(repo, ref):
    """Branch a ref names, or "" when the ref is a raw commit.

    `rev-parse --abbrev-ref` treats `--end-of-options` as a revision, so a
    ref that starts with `-` is refused instead of passed through.
    """
    if not isinstance(ref, str) or not ref or _SHA.fullmatch(ref):
        return ""
    if ref.startswith("-") or any(ch.isspace() for ch in ref):
        return ""
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--abbrev-ref", "--verify", ref],
        capture_output=True, text=True,
    )
    name = result.stdout.strip() if result.returncode == 0 else ""
    if not name or name == "HEAD" or _SHA.fullmatch(name):
        return ""
    return name


def _ranked_worktrees(entries, branch, sha):
    """Branch match first, then a worktree whose HEAD is this commit."""
    branch_hits, commit_hits = [], []
    for item in entries:
        if branch and item.get("branch") == branch:
            branch_hits.append(item)
        elif (item.get("head") or "").lower() == sha:
            commit_hits.append(item)
    return branch_hits + commit_hits


def _contained(root, candidate):
    root = Path(root).resolve()
    candidate = Path(candidate).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        raise EditorError(OUTSIDE) from None
    if candidate == root:
        raise EditorError("This item has no file.")
    return candidate


def materialize_snapshot(repo, parts, sha, branch, *, cache_dir=None, home=None, show_blob=None):
    """Write the blob once, mode 0444, and reuse the file when it is already there.

    Returns (snapshot directory, file, reused).
    """
    rel = "/".join(parts)
    folder = snapshot_cache(cache_dir, home) / (
        f"{repo_snapshot_name(repo)}@{snapshot_component(branch)}-{sha[:12]}"
    )
    dest = _contained(folder, folder.joinpath(*parts))
    if dest.exists() or dest.is_symlink():
        if dest.is_symlink() or not dest.is_file():
            raise EditorError(OUTSIDE)
        return folder.resolve(), dest, True
    data = (show_blob or git_show_blob)(repo, sha, rel)
    if not isinstance(data, (bytes, bytearray)):
        raise EditorError(NOT_IN_COMMIT)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.parent / (dest.name + ".cbi-tmp")
    if tmp.is_symlink() or tmp.exists():
        tmp.unlink()
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    os.chmod(tmp, 0o444)
    os.replace(tmp, dest)
    return folder.resolve(), dest, False


def resolve_ref_target(rel_path, line, *, repo, branch, sha, cache_dir=None, home=None,
                       list_worktrees=None, show_blob=None, exists=None):
    """Open a ref from a matching worktree, or from a read-only snapshot.

    `notice` is set only for the snapshot. The worktree file has none.
    """
    parts = _safe_parts(rel_path)
    number = _line_number(line)
    sha = _commit_sha(sha)
    rel = "/".join(parts)
    entries = (list_worktrees or git_worktrees)(repo)
    for item in _ranked_worktrees(entries, branch or "", sha):
        try:
            opened = resolve_target(
                rel, number, project=item["path"], worktree=item["path"], ref=False, exists=exists,
            )
        except EditorError as err:
            if str(err) == NOT_ON_DISK:
                continue
            raise
        opened["notice"] = None
        return opened
    folder, dest, _reused = materialize_snapshot(
        repo, parts, sha, branch or sha[:12], cache_dir=cache_dir, home=home, show_blob=show_blob,
    )
    return {
        "project": str(folder),
        "file": str(dest),
        "line": number,
        "notice": snapshot_notice(branch, sha),
    }


def launch(argv):
    """Start argv detached. No shell. The editor outlives this process."""
    subprocess.Popen(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def format_argv(argv):
    return " ".join(shlex.quote(part) for part in argv)


def open_node(conn, ref, *, project, worktree, ref_model, editor="vscode", template=None,
              path_env=None, home=None, exists=None, is_executable=None, run=None,
              sha=None, branch=None, cache_dir=None, list_worktrees=None, show_blob=None):
    """Print the editor command and run it. Returns a process exit code.

    ref_model is true when the model is a commit. A worktree that has that
    branch or commit supplies the file. Otherwise a read-only snapshot does,
    and the notice is printed to stderr.
    """
    node_id = query._one(conn, ref, as_json=False)
    if not node_id:
        return 1
    kind, display, path, line = conn.execute(
        "SELECT kind, display_kind, path, start_line FROM nodes WHERE id = ?", (node_id,)
    ).fetchone()
    if not opens_in_editor(kind, display, path):
        print(f"A {display} does not map to one file.", file=sys.stderr)
        return 1
    if editor == "none" and not template:
        print(NO_EDITOR, file=sys.stderr)
        return 1
    try:
        if ref_model:
            target = resolve_ref_target(
                path, line, repo=project, branch=branch or "", sha=sha,
                cache_dir=cache_dir, home=home, list_worktrees=list_worktrees,
                show_blob=show_blob, exists=exists,
            )
        else:
            target = resolve_target(path, line, project=project, worktree=worktree, ref=False, exists=exists)
            target["notice"] = None
        argv = command_argv(
            editor, template, target["project"], target["file"], target["line"],
            path_env=path_env, home=home, is_executable=is_executable,
        )
    except EditorError as err:
        print(err, file=sys.stderr)
        return err.code
    if target.get("notice"):
        print(target["notice"], file=sys.stderr)
    print(format_argv(argv))
    try:
        (run or launch)(argv)
    except OSError as err:
        print(err, file=sys.stderr)
        return 1
    return 0

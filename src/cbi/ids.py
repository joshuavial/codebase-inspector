"""Node ID rules and the git remote URL normaliser."""

import hashlib
import posixpath
import re
from collections import Counter


def normalise_remote(url):
    """Turn a git remote URL into `host/owner/repo`, lowercased.

    Scheme, user, password, port, trailing slash and `.git` are dropped, so the ssh
    and https forms of one repo give one ID. A local path or `file://` remote gives
    `local:<repo dir name>`, which keeps IDs the same on every machine.
    """
    url = url.strip().rstrip("/")
    if url.startswith("file://") or url.startswith(("/", ".", "~")) or re.match(r"^[A-Za-z]:[\\/]", url):
        return local_id(posixpath.basename(url.replace("\\", "/")))
    if "://" in url:
        rest = url.split("://", 1)[1]
        host, _, path = rest.partition("/")
        host = host.rsplit("@", 1)[-1].split(":", 1)[0]
    else:
        # scp-like form: [user@]host:owner/repo
        host, _, path = url.partition(":")
        host = host.rsplit("@", 1)[-1]
    path = path.strip("/")
    path = path.removesuffix(".git")
    return f"{host}/{path}".lower()


def local_id(dirname):
    return f"local:{dirname.removesuffix('.git').lower()}"


def repo_name(url):
    """The repository's name from a remote URL, case preserved, without `.git`.

    None when `url` is empty. A local path or `file://` URL uses its directory name.
    """
    if not url or not str(url).strip():
        return None
    text = str(url).strip().rstrip("/")
    if text.endswith(".git"):
        text = text[:-4]
    if text.startswith("file://"):
        text = text[len("file://"):]
    local = text.startswith(("/", ".", "~")) or re.match(r"^[A-Za-z]:[\\/]", text)
    if local:
        name = posixpath.basename(text.replace("\\", "/"))
        return name or None
    if "://" in text:
        path = text.split("://", 1)[1].partition("/")[2]
    else:
        _host, sep, path = text.partition(":")
        if not sep:
            path = text
    name = posixpath.basename(path.strip("/").replace("\\", "/"))
    return name or None


def resolve_relative_url(url, parent_remote):
    """Resolve a `.gitmodules` URL like `../lib.git` against the parent's remote URL."""
    if not url.startswith(("./", "../")) or not parent_remote:
        return url
    if "://" not in parent_remote and ":" in parent_remote and not parent_remote.startswith("/"):
        host, _, path = parent_remote.partition(":")
        return f"{host}:{posixpath.normpath(posixpath.join(path, url))}"
    return posixpath.normpath(posixpath.join(parent_remote, url)).replace(":/", "://", 1)


def file_id(workspace_id, path):
    return f"{workspace_id}:{path}"


def group_id(workspace_id, dir_path):
    return f"{workspace_id}:{dir_path}/"


def symbol_ids(file_node_id, defs):
    """IDs for (qualified name, signature) pairs in source order.

    A qualified name used once gives `<file>#<name>`. Repeated names get a suffix
    of the first 8 hex characters of the signature's sha1; repeats with identical
    signatures add `~2`, `~3` by source order after that.
    """
    names = Counter(q for q, _ in defs)
    seen = Counter()
    out = []
    for qualname, signature in defs:
        key = qualname
        if names[qualname] > 1:
            key = f"{qualname}~{hashlib.sha1(signature.encode()).hexdigest()[:8]}"
            seen[key] += 1
            if seen[key] > 1:
                key = f"{key}~{seen[key]}"
        out.append(f"{file_node_id}#{key}")
    return out

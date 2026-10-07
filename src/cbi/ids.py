"""Node ID rules and the git remote URL normaliser."""

import posixpath
import re


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

"""Literal SQL enumeration contracts over tracked model paths only."""

import ast
import fnmatch
import posixpath
from functools import lru_cache

from cbi.testing_paths import GlobValue, PathValue, contexts, read_value


def _matches(path, pattern, recursive=False):
    parts = tuple(path.split("/"))
    wanted = tuple((["**"] if recursive else []) + pattern.split("/"))

    @lru_cache(None)
    def match(i, j):
        if j == len(wanted):
            return i == len(parts)
        if wanted[j] == "**":
            return match(i, j + 1) or (i < len(parts) and match(i + 1, j))
        return i < len(parts) and fnmatch.fnmatchcase(parts[i], wanted[j]) and match(i + 1, j + 1)

    return match(0, 0)


def _targets(context, glob):
    if glob.pattern.startswith("/") or ".." in glob.pattern.split("/"):
        return []
    model = context.model
    wid, own, _role = model.files[context.fid]
    if glob.base.anchored:
        directories = [glob.base.path]
    else:
        # Use the same possible working directories as literal read resolution.
        directory = posixpath.dirname(own)
        directories = []
        while True:
            directories.append(posixpath.normpath(posixpath.join(directory, glob.base.path)))
            if not directory:
                break
            directory = posixpath.dirname(directory)
    for directory in directories:
        prefix = directory.rstrip("/") + "/" if directory not in ("", ".") else ""
        selected = []
        for path, fid in model.by_path[wid].items():
            if path.lower().endswith(".sql") and path.startswith(prefix):
                relative = path[len(prefix):]
                if _matches(relative, glob.pattern, glob.recursive):
                    selected.append(fid)
        if selected:
            return sorted(selected)
    return []


def link(model, edges, add):
    diagnostics = set()
    for context in contexts(model):
        call = context.call
        value, _mechanism = read_value(context)
        if isinstance(call.func, ast.Attribute) and call.func.attr in {"glob", "rglob"}:
            value = context.value(call)
            if not isinstance(value, GlobValue):
                base = context.value(call.func.value)
                if isinstance(base, PathValue):
                    path = model.files[context.fid][1]
                    diagnostics.add((context.fid, "unsupported_test_mechanism",
                                     f"{path}:{call.lineno}:{call.col_offset + 1}: file_glob: dynamic pattern or directory prevents tracked SQL binding"))
        if not isinstance(value, GlobValue):
            continue
        for dst in _targets(context, value):
            src = context.owner()
            existing = edges.get((src, dst, "tests", "treesitter"))
            if not existing or existing[0] < 0.8:
                add(src, dst, "tests", "treesitter", 0.8, {"via": "sql_glob"})
    return sorted(diagnostics)

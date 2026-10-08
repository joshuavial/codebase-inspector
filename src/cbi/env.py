"""Env var nodes and the reads_env edges that point at them.

Reads come from parse facts (`envs`: symbol id or None, name, string default or
None). The name `*` is a `...process.env` spread: it is not an env var. The file
gets one `env_passthrough` diagnostic, "passes whole environment". Declarations come from `.env.example`,
`.env.sample`, a compose service `environment` (a list of `NAME` or `NAME=value`,
or a map) and the top-level `[vars]` table of `wrangler.toml`. `declared_in`
lists those paths. `example` is set only from example and sample files, and when
several of them name one variable the lexicographically first path supplies the
value. A file named `.env` or `.env.<anything>` other than the example and sample
forms is never opened.
"""

import json
import posixpath
import re
import tomllib
from pathlib import Path

from cbi.files import ENV_EXAMPLES, is_private_env
from cbi.manifests import COMPOSE, _yaml

# ASP.NET maps GetConnectionString("SampleApp") to ConnectionStrings__SampleApp,
# keeping the connection name's case. Other reads stay all-caps.
NAME = re.compile(r"[A-Z_][A-Z0-9_]*|ConnectionStrings__[A-Za-z0-9_]+")
PASSTHROUGH = "*"
_LINE = re.compile(r"^(?:export[ \t]+)?([A-Z_][A-Z0-9_]*)[ \t]*=[ \t]*(.*)$")
_MISSING = object()


def example_vars(text):
    """`{NAME: example value}` from a dotenv example file. Quotes are not unescaped."""
    found = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = _LINE.match(line)
        if match:
            found[match.group(1)] = _dotenv_value(match.group(2).strip())
    return found


def _dotenv_value(raw):
    if raw[:1] in ("'", '"'):
        end = raw.find(raw[0], 1)
        if end > 0:
            return raw[1:end]
    return re.sub(r"[ \t]+#.*$", "", raw).rstrip()


def compose_vars(text):
    """Env names declared by services' `environment` in one compose file, list or map form."""
    data = _yaml(text or "")
    services = data.get("services") if isinstance(data, dict) else None
    names = []
    for svc in services.values() if isinstance(services, dict) else ():
        if isinstance(svc, dict):
            names.extend(_environment_names(svc.get("environment")))
    return names


def _environment_names(env):
    if isinstance(env, dict):
        return [key for key in env if isinstance(key, str) and NAME.fullmatch(key)]
    if isinstance(env, list):
        found = []
        for item in env:
            if isinstance(item, str) and NAME.fullmatch((key := item.split("=", 1)[0].strip())):
                found.append(key)
        return found
    return []


def wrangler_vars(text):
    """Names in the top-level `[vars]` table. `[env.*.vars]` is not a declaration."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return []
    found = data.get("vars") if isinstance(data, dict) else None
    if not isinstance(found, dict):
        return []
    return [key for key in found if isinstance(key, str) and NAME.fullmatch(key)]


def _decl_kind(path):
    if is_private_env(path):
        return None
    name = posixpath.basename(path)
    if name in ENV_EXAMPLES:
        return "example"
    if name == "wrangler.toml":
        return "wrangler"
    if COMPOSE.search(path):
        return "compose"
    return None


def _read(repo, top):
    if is_private_env(top):
        return None
    try:
        base = Path(repo) if isinstance(repo, (str, bytes)) else repo
        return (base / top).read_text(errors="replace")
    except OSError:
        return None


def _attrs(wid, name, paths, examples):
    attrs = {}
    declared = sorted(paths.get((wid, name), ()))
    if declared:
        attrs["declared_in"] = declared
    values = examples.get((wid, name))
    if values:
        attrs["example"] = values[min(values)]
    return attrs


def apply(conn, root):
    """Replace env nodes and reads_env edges from facts and declaration files."""
    roots = {
        wid: json.loads(attrs or "{}").get("root") or ""
        for wid, attrs in conn.execute("SELECT id, attrs FROM nodes WHERE kind = 'workspace'")
    }
    reads = {}  # (reader id, name) -> [weight, default or None, workspace id]
    passthrough = set()
    for fid, wid, data in conn.execute(
            "SELECT f.file_id, n.workspace_id, f.data FROM facts f JOIN nodes n ON n.id = f.file_id"):
        for item in json.loads(data).get("envs") or []:
            if not isinstance(item, (list, tuple)) or len(item) < 2 or not isinstance(item[1], str):
                continue
            src, name, default = item[0], item[1], item[2] if len(item) > 2 else None
            if name == PASSTHROUGH:
                passthrough.add(fid)
                continue
            if not NAME.fullmatch(name):
                continue
            reader = src or fid
            slot = reads.setdefault((reader, name), [0, None, wid])
            slot[0] += 1
            if slot[1] is None and isinstance(default, str):
                slot[1] = default

    paths, examples = {}, {}
    for wid, path in conn.execute("SELECT workspace_id, path FROM nodes WHERE kind = 'file'"):
        kind = _decl_kind(path)
        if not kind:
            continue
        top = posixpath.join(roots.get(wid, ""), path) if roots.get(wid) else path
        text = _read(root, top)
        if text is None:
            continue
        if kind == "example":
            for name, value in example_vars(text).items():
                paths.setdefault((wid, name), set()).add(path)
                examples.setdefault((wid, name), {})[path] = value
        else:
            names = compose_vars(text) if kind == "compose" else wrangler_vars(text)
            for name in names:
                paths.setdefault((wid, name), set()).add(path)

    by_ws = {}
    for (_, name), (_, _, wid) in reads.items():
        by_ws.setdefault(wid, set()).add(name)
    for wid, name in paths:
        by_ws.setdefault(wid, set()).add(name)

    rows, ids = [], []
    for wid, found in by_ws.items():
        for name in found:
            nid = f"{wid}:env:{name}"
            ids.append(nid)
            attrs = _attrs(wid, name, paths, examples)
            rows.append((nid, name, wid, json.dumps(attrs, sort_keys=True) if attrs else None))
    conn.executemany(
        "INSERT INTO nodes (id, parent_id, kind, display_kind, name, workspace_id, attrs) "
        "VALUES (?, NULL, 'env', 'env var', ?, ?, ?) ON CONFLICT(id) DO UPDATE SET "
        "parent_id = NULL, kind = 'env', display_kind = 'env var', name = excluded.name, "
        "workspace_id = excluded.workspace_id, attrs = excluded.attrs",
        rows,
    )
    conn.execute(
        "DELETE FROM nodes WHERE kind = 'env' AND id NOT IN (SELECT value FROM json_each(?))",
        (json.dumps(ids),),
    )
    conn.execute("DELETE FROM edges WHERE kind = 'reads_env'")
    conn.executemany(
        "INSERT INTO edges (src, dst, kind, source, confidence, weight, attrs) "
        "VALUES (?, ?, 'reads_env', 'treesitter', 1.0, ?, ?)",
        [(src, f"{wid}:env:{name}", weight, json.dumps({"default": default}, sort_keys=True) if default is not None else None)
         for (src, name), (weight, default, wid) in reads.items()],
    )
    conn.execute("DELETE FROM diagnostics WHERE kind = 'env_passthrough'")
    conn.executemany(
        "INSERT INTO diagnostics (node_id, kind, detail) VALUES (?, 'env_passthrough', ?)",
        [(fid, "passes whole environment") for fid in sorted(passthrough)],
    )

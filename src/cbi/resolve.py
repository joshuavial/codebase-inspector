"""Import and call resolution and test linking over the stored parse facts.

Runs over the whole model on every scan the no-change shortcut does not stop.
Edges it owns (source `treesitter` and `naming`) and the `ambiguous_call` and
`unmatched_test` diagnostics are replaced each time.
"""

import json
import posixpath
import re
from collections import Counter, defaultdict

from cbi.files import CODE_LANGS

EXTS = (".ts", ".tsx", ".d.ts", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts")
# A compiled-extension import (`./x.js`) names the TypeScript source (`./x.ts`).
TS_FOR_JS = {".js": (".ts", ".tsx"), ".jsx": (".tsx",), ".mjs": (".mts",), ".cjs": (".cts",)}
TEST_DIRS = {"__tests__", "test", "tests"}
TEST_SUFFIX = re.compile(r"[._-](test|spec)$")
THIS_CONFIDENCE = 0.6
IMPORT_TEST_CONFIDENCE = 0.5
NAMING_CONFIDENCE = 0.8
OWNED_SOURCES = ("treesitter", "naming")


def _jsonc(text):
    """Parse tsconfig-style JSON: comments and trailing commas allowed."""
    strings_or_comments = r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*.*?\*/'
    text = re.sub(strings_or_comments, lambda m: m.group(0) if m.group(0)[0] == '"' else "", text, flags=re.S)
    text = re.sub(r'"(?:\\.|[^"\\])*"|,(\s*[}\]])', lambda m: m.group(1) if m.group(1) is not None else m.group(0), text)
    return json.loads(text)


class _Model:
    def __init__(self, conn, root):
        self.root = root
        self.ws_dir = {
            wid: root / (json.loads(attrs or "{}").get("root") or "")
            for wid, attrs in conn.execute("SELECT id, attrs FROM nodes WHERE kind = 'workspace'")
        }
        self.files = {}  # file id -> (workspace id, path, role)
        self.by_path = defaultdict(dict)  # workspace id -> {path: file id}
        for fid, wid, path, attrs in conn.execute(
                "SELECT id, workspace_id, path, attrs FROM nodes WHERE kind IN ('file', 'doc')"):
            self.files[fid] = (wid, path, json.loads(attrs or "{}").get("role"))
            self.by_path[wid][path] = fid
        self.facts = {fid: json.loads(data) for fid, data in conn.execute("SELECT file_id, data FROM facts")}
        self.nodes = {}  # symbol or test id -> (parent id, kind, display kind, file id)
        self.members = defaultdict(list)  # (parent id, name) -> symbol ids
        for nid, parent, kind, display, name, wid, path in conn.execute(
                "SELECT id, parent_id, kind, display_kind, name, workspace_id, path FROM nodes "
                "WHERE kind IN ('symbol', 'test') ORDER BY id"):
            self.nodes[nid] = (parent, kind, display, self.by_path[wid].get(path))
            if kind == "symbol":
                self.members[(parent, name)].append(nid)
        self.bindings = {
            fid: {local: (imp["spec"], imported) for imp in f["imports"] for local, imported in imp["names"].items()}
            for fid, f in self.facts.items()
        }
        self._specs, self._tsconfigs = {}, {}

    # --- module specifiers ------------------------------------------------------

    def _find(self, wid, path):
        """The file a resolved module path names, trying extensions and index files."""
        if path == ".." or path.startswith("../"):
            return None
        paths = self.by_path[wid]
        stem, ext = posixpath.splitext(path)
        candidates = [path, *(path + e for e in EXTS), *(f"{path}/index{e}" for e in EXTS)]
        candidates += [stem + e for e in TS_FOR_JS.get(ext, ())]
        return next((paths[c] for c in candidates if c in paths), None)

    def _tsconfig(self, wid, path):
        """compilerOptions `paths` and `baseUrl` of a tsconfig, following relative `extends`."""
        key = (wid, path)
        if key in self._tsconfigs:
            return self._tsconfigs[key]
        self._tsconfigs[key] = {}  # guards against extends cycles
        try:
            data = _jsonc((self.ws_dir[wid] / path).read_text())
        except (OSError, ValueError):
            return {}
        out = {}
        extends = data.get("extends") or []
        for parent in [extends] if isinstance(extends, str) else extends:
            if parent.startswith("."):
                parent = posixpath.normpath(posixpath.join(posixpath.dirname(path), parent))
                parent = parent if parent.endswith(".json") else parent + ".json"
                if parent in self.by_path[wid]:
                    out.update(self._tsconfig(wid, parent))
        options = data.get("compilerOptions") or {}
        here = posixpath.dirname(path)
        if isinstance(options.get("baseUrl"), str):
            out["baseUrl"] = posixpath.normpath(posixpath.join(here, options["baseUrl"]))
        if isinstance(options.get("paths"), dict):
            out["paths"] = (options["paths"], here)
        self._tsconfigs[key] = out
        return out

    def _nearest_tsconfig(self, wid, directory):
        while True:
            path = posixpath.join(directory, "tsconfig.json")
            if path in self.by_path[wid]:
                return self._tsconfig(wid, path)
            if not directory:
                return {}
            directory = posixpath.dirname(directory)

    def spec(self, fid, spec):
        """The file ID an import specifier in file fid resolves to, or None (external or not tracked)."""
        key = (fid, spec)
        if key not in self._specs:
            wid, path, _ = self.files[fid]
            if spec.startswith("."):
                found = self._find(wid, posixpath.normpath(posixpath.join(posixpath.dirname(path), spec)))
            elif spec.startswith("/"):
                found = None
            else:
                found = self._aliased(wid, posixpath.dirname(path), spec)
            self._specs[key] = found
        return self._specs[key]

    def _aliased(self, wid, directory, spec):
        """A bare specifier through tsconfig `paths` (longest matching prefix wins), then `baseUrl`."""
        config = self._nearest_tsconfig(wid, directory)
        if "paths" in config:
            patterns, paths_dir = config["paths"]
            best = None
            for pattern, targets in patterns.items():
                prefix, star, suffix = pattern.partition("*")
                if star and spec.startswith(prefix) and spec.endswith(suffix) and len(spec) >= len(prefix) + len(suffix):
                    match = spec[len(prefix):len(spec) - len(suffix)]
                elif not star and spec == pattern:
                    match = ""
                else:
                    continue
                if best is None or len(prefix) > len(best[0]):
                    best = (prefix, match, targets)
            if best:
                base = config.get("baseUrl", paths_dir)
                for target in best[2] if isinstance(best[2], list) else ():
                    found = self._find(wid, posixpath.normpath(posixpath.join(base, target.replace("*", best[1]))))
                    if found:
                        return found
        if "baseUrl" in config:
            return self._find(wid, posixpath.normpath(posixpath.join(config["baseUrl"], spec)))
        return None

    # --- exports ----------------------------------------------------------------

    def _local(self, fid, local, seen):
        """Where a top-level name of fid is defined: (file id, name), or (file id, None) for a whole module."""
        bound = self.bindings.get(fid, {}).get(local)
        if not bound:
            return fid, local
        target = self.spec(fid, bound[0])
        if not target:
            return None
        return (target, None) if bound[1] == "*" else self.export(target, bound[1], seen)

    def export(self, fid, name, seen=None, first=True):
        """Follow an exported name through re-exports to (defining file id, local name or None)."""
        facts = self.facts.get(fid)
        seen = seen if seen is not None else set()
        if facts is None or (fid, name) in seen:
            return None
        seen.add((fid, name))
        if name in facts["exports"]:
            return self._local(fid, facts["exports"][name], seen)
        for re_ in facts["reexports"]:
            if re_["names"] and name in re_["names"]:
                target = self.spec(fid, re_["spec"])
                if not target:
                    return None
                imported = re_["names"][name]
                return (target, None) if imported == "*" else self.export(target, imported, seen, False)
        for re_ in facts["reexports"]:
            target = re_["names"] is None and name != "default" and self.spec(fid, re_["spec"])
            found = target and self.export(target, name, seen, False)
            if found:
                return found
        # A file with no ES exports is CommonJS, or a script: any top-level name may be what it exports.
        if first and not facts["exports"] and not facts["reexports"] and name in facts["locals"]:
            return self._local(fid, name, seen)
        return None

    # --- calls ------------------------------------------------------------------

    def _named(self, fid, name):
        """Symbols a bare name in fid binds to: same-file definitions first, then an import."""
        same = self.members.get((fid, name))
        if same:
            return same
        found = name in self.bindings.get(fid, {}) and self._local(fid, name, set())
        return self.members.get(found, []) if found and found[1] else []

    def bind(self, fid, cls, shape, name, member):
        """Candidate symbol IDs and confidence for one call site."""
        if shape == "name":
            return self._named(fid, name), 1.0
        if shape == "this":
            return self.members.get((cls, name), []), THIS_CONFIDENCE
        bound = self.bindings.get(fid, {}).get(name)
        if bound and bound[1] == "*":
            target = self.spec(fid, bound[0])
            found = target and self.export(target, member)
            return (self.members.get(found, []) if found and found[1] else []), 1.0
        classes = [c for c in self._named(fid, name) if self.nodes[c][2] == "class"]
        return [m for c in classes for m in self.members.get((c, member), [])], 1.0

    def test_owner(self, nid):
        """The innermost test node at or around nid, or the file when there is none."""
        while nid in self.nodes:
            parent, kind, _, _ = self.nodes[nid]
            if kind == "test":
                return nid
            nid = parent
        return nid

    def read_target(self, fid, path):
        """The tracked file a literal read names. Tried from the file's directory, then, with leading
        `./` and `../` dropped, from each directory above it: a test's working directory and the
        compiled output `__dirname` points at are unknown."""
        wid, own, _ = self.files[fid]
        directory = posixpath.dirname(own)
        paths = self.by_path[wid]
        first = posixpath.normpath(posixpath.join(directory, path))
        if first in paths:
            return paths[first]
        stripped = re.sub(r"^(\.\.?/)+", "", path)
        while True:
            candidate = posixpath.normpath(posixpath.join(directory, stripped))
            if candidate in paths:
                return paths[candidate]
            if not directory:
                return None
            directory = posixpath.dirname(directory)

    def name_matches(self, fid):
        """Code files named like the test file: x.test.ts -> x.ts beside it, or one folder up from __tests__."""
        wid, path, _ = self.files[fid]
        directory, name = posixpath.split(path)
        stem = TEST_SUFFIX.sub("", posixpath.splitext(name)[0])
        dirs = [directory] + ([posixpath.dirname(directory)] if posixpath.basename(directory) in TEST_DIRS else [])
        out = []
        for d in dirs:
            for ext in CODE_LANGS:
                found = self.by_path[wid].get(posixpath.join(d, stem + ext))
                if found and self.files[found][2] == "code":
                    out.append(found)
        return out


def resolve(conn, root):
    """Replace import, call and test edges and the ambiguous_call and unmatched_test diagnostics."""
    m = _Model(conn, root)
    edges = {}

    def add(src, dst, kind, source, confidence):
        edge = edges.setdefault((src, dst, kind, source), [confidence, 0])
        edge[0] = max(edge[0], confidence)
        edge[1] += 1

    ambiguous, test_imports, external, unread = Counter(), defaultdict(set), defaultdict(list), defaultdict(list)
    for fid, facts in m.facts.items():
        for imp in facts["imports"] + facts["reexports"]:
            target = m.spec(fid, imp["spec"])
            if not target:
                external[fid].append(imp["spec"])
                continue
            names = (imp["names"] or {}).values()
            found = {m.export(target, n) for n in names if n != "*"}
            dsts = {f[0] for f in found if f} or {target}
            for dst in dsts - {fid}:
                add(fid, dst, "imports", "treesitter", 1.0)
                test_imports[fid].add(dst)

        is_test = m.files[fid][2] == "test"
        for src, cls, shape, name, member in facts["calls"]:
            candidates, confidence = m.bind(fid, cls, shape, name, member)
            if len(candidates) > 1:
                ambiguous[fid] += 1
            elif candidates:
                src = src or fid
                add(src, candidates[0], "calls", "treesitter", confidence)
                if is_test and m.nodes[candidates[0]][3] != fid:
                    add(m.test_owner(src), candidates[0], "tests", "treesitter", confidence)

        if not is_test:
            continue
        for dst in test_imports[fid]:
            if m.files[dst][2] == "code":
                add(fid, dst, "tests", "treesitter", IMPORT_TEST_CONFIDENCE)
        for dst in m.name_matches(fid):
            add(fid, dst, "tests", "naming", NAMING_CONFIDENCE)
        for src, path in facts["reads"]:
            dst = m.read_target(fid, path)
            if dst and dst != fid:
                add(m.test_owner(src or fid), dst, "tests", "treesitter", 1.0)
            elif not dst:
                unread[fid].append(path)

    linked = {src if src in m.files else m.nodes[src][3] for src, _, kind, _ in edges if kind == "tests"}
    unmatched = []
    for fid in sorted(m.facts):
        if m.files[fid][2] == "test" and fid not in linked:
            specs, reads = sorted(set(external[fid])), sorted(set(unread[fid]))
            detail = "no call, import, file read or file name reaches tracked code; "
            detail += f"imports only {', '.join(specs)}" if specs else "imports nothing"
            if reads:
                detail += f"; reads {', '.join(reads)}, not in the model (ignored or untracked)"
            unmatched.append((fid, "unmatched_test", detail))

    conn.execute(f"DELETE FROM edges WHERE source IN ({', '.join('?' * len(OWNED_SOURCES))})", OWNED_SOURCES)
    conn.executemany(
        "INSERT INTO edges (src, dst, kind, source, confidence, weight) VALUES (?, ?, ?, ?, ?, ?)",
        [(*key, conf, weight) for key, (conf, weight) in edges.items()],
    )
    conn.execute("DELETE FROM diagnostics WHERE kind IN ('ambiguous_call', 'unmatched_test')")
    conn.executemany(
        "INSERT INTO diagnostics (node_id, kind, detail) VALUES (?, ?, ?)",
        [(fid, "ambiguous_call", f"{n} calls with more than one candidate") for fid, n in sorted(ambiguous.items())]
        + unmatched,
    )

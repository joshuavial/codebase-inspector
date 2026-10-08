"""Import and call resolution and test linking over the stored parse facts.

Runs over the whole model on every scan the no-change shortcut does not stop.
Edges it owns (source `treesitter`, `naming` and `html`) and the `ambiguous_call`,
`unmatched_test` and `unresolved_injection` diagnostics are replaced each time.
A test case that calls a helper defined in its own file inherits that helper's
calls, one level.
A production literal path, and a script tag in an HTML file, become a
`references` edge. `__dirname` is the compiled directory from tsconfig
`outDir`/`rootDir`, so `preload.js` maps back to `preload.ts`.
Env nodes and `reads_env` edges are replaced at the end, from the same facts
plus declaration files.
"""

import json
import posixpath
import re
import tomllib
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from html.parser import HTMLParser

from cbi import http, manifests
from cbi.files import CODE_LANGS

EXTS = (".ts", ".tsx", ".d.ts", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts")
# A compiled-extension import (`./x.js`) names the TypeScript source (`./x.ts`).
TS_FOR_JS = {".js": (".ts", ".tsx"), ".jsx": (".tsx",), ".mjs": (".mts",), ".cjs": (".cts",)}
TEST_DIRS = {"__tests__", "test", "tests"}
TEST_SUFFIX = re.compile(r"[._-](test|spec)$")
THIS_CONFIDENCE = 0.6
IMPORT_TEST_CONFIDENCE = 0.5
NAMING_CONFIDENCE = 0.8
# `patch("pkg.mod.attr")` names the module. It is not a call the test makes.
PATCH_CONFIDENCE = 0.8
# A declared type names one class or interface. Below this, define-concepts ignores the call.
INJECT_KNOWN = 0.6
INJECT_STRUCTURAL = 0.4  # split across production classes that provide the local interface or Protocol
INJECT_CONSTRUCT = 0.7
# A C# type mention is weaker than a using: it names a type, not a namespace the file imported.
TYPE_REF_CONFIDENCE = 0.4
# `object` is an exported object literal, so `api.raiseInvoice()` resolves like a method call.
TYPE_KINDS = {"class", "record", "struct", "interface", "enum", "object"}
CONCRETE_KINDS = {"class", "record", "struct"}
OWNED_SOURCES = ("treesitter", "naming", "html")


def _jsonc(text):
    """Parse tsconfig-style JSON: comments and trailing commas allowed."""
    strings_or_comments = r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*.*?\*/'
    text = re.sub(strings_or_comments, lambda m: m.group(0) if m.group(0)[0] == '"' else "", text, flags=re.S)
    text = re.sub(r'"(?:\\.|[^"\\])*"|,(\s*[}\]])', lambda m: m.group(1) if m.group(1) is not None else m.group(0), text)
    return json.loads(text)


def _norm(path):
    path = posixpath.normpath(path)
    return "" if path == "." else path


class _ScriptSrcs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.srcs = []

    def handle_starttag(self, tag, attrs):
        if tag != "script":
            return
        for key, value in attrs:
            if key == "src" and value:
                self.srcs.append(value)


def _script_srcs(text):
    parser = _ScriptSrcs()
    parser.feed(text)
    return parser.srcs


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
        self._specs, self._tsconfigs, self._packages = {}, {}, {}
        self._pyprojects, self._py_roots_cache, self._by_name = {}, {}, None
        self._maps = {}
        self._cy = None  # (workspace, command name) -> symbol ids under cypress/support
        self._cs_types = defaultdict(list)  # (workspace, namespace, simple name) -> type symbol ids
        self._cs_ns_files = defaultdict(set)  # (workspace, namespace) -> file ids that declare it
        self._cs_file_types = defaultdict(set)  # (workspace, namespace, file id) -> simple names declared there
        self._cs_partials = defaultdict(list)  # (workspace, qualname stem) -> type symbol ids
        self._csproj_by_dir = None
        self._csproj_usings_cache = {}
        self._cs_name_cache = {}
        self._cs_by_name = None
        self._index_csharp()

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
        for key_name in ("outDir", "rootDir"):
            if isinstance(options.get(key_name), str):
                out[key_name] = _norm(posixpath.join(here, options[key_name]))
        if "outDir" in out:
            out.setdefault("rootDir", here)
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
            if path.endswith(".py"):
                found = self._py_spec(wid, path, spec)
            elif spec.startswith("."):
                found = self._find(wid, posixpath.normpath(posixpath.join(posixpath.dirname(path), spec)))
            elif spec.startswith("/"):
                found = None
            else:
                found = self._aliased(wid, posixpath.dirname(path), spec) or self._package(wid, spec)
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

    def _package(self, wid, spec):
        """A package of this workspace imported by name: its source entry, its index, or a path inside it."""
        if wid not in self._packages:
            self._packages[wid] = manifests.npm_packages(self.ws_dir[wid], self.by_path[wid].keys())
        for name, (directory, entry) in self._packages[wid].items():
            if spec == name:
                return self.by_path[wid].get(entry) or self._find(wid, directory) or self._find(wid, directory + "/src")
            if spec.startswith(name + "/"):
                rest = spec[len(name) + 1:]
                return self._find(wid, f"{directory}/{rest}") or self._find(wid, f"{directory}/src/{rest}")
        return None

    # --- exports ----------------------------------------------------------------

    def _local(self, fid, local, seen):
        """Where a top-level name of fid is defined: (file id, name), or (file id, None) for a whole module."""
        bound = self.bindings.get(fid, {}).get(local)
        if not bound:
            return fid, local
        if bound[1] != "*" and self.files[fid][1].endswith(".py"):
            return self.py_name(fid, bound[0], bound[1], seen)
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
        """Symbols a bare name in fid binds to: same-file definitions first, then a C# type, then an import."""
        same = self.members.get((fid, name))
        if same:
            return same
        cs = self._cs_names(fid, name)
        if cs:
            return cs
        found = name in self.bindings.get(fid, {}) and self._local(fid, name, set())
        return self.members.get(found, []) if found and found[1] else []

    def _cy_commands(self, fid, name):
        """Symbols named `name` defined under a `cypress/support` directory in this workspace."""
        if self._cy is None:
            index = defaultdict(list)
            for (parent, command), ids in self.members.items():
                del parent
                for nid in ids:
                    file_id = self.nodes[nid][3]
                    if file_id not in self.files:
                        continue
                    fwid, path, _role = self.files[file_id]
                    parts = path.split("/")
                    if any(left == "cypress" and right == "support" for left, right in zip(parts, parts[1:])):
                        index[(fwid, command)].append(nid)
            self._cy = index
        return self._cy.get((self.files[fid][0], name), [])

    def bind(self, fid, cls, shape, name, member):
        """Candidate symbol IDs and confidence for one call site."""
        if shape == "cy":
            return self._cy_commands(fid, name), 1.0
        if shape == "name":
            found = self._named(fid, name)
            collapsed = _collapse_partials(self, found)
            return ([collapsed] if collapsed else found), 1.0
        if shape == "this":
            return self.members.get((cls, name), []), THIS_CONFIDENCE
        found = name in self.bindings.get(fid, {}) and self._local(fid, name, set())
        if found and found[1] is None:  # a whole module: ns.f(), mod.f()
            found = self.export(found[0], member)
            return (self.members.get(found, []) if found and found[1] else []), 1.0
        classes = [c for c in self._named(fid, name) if self.nodes[c][2] in TYPE_KINDS]
        expanded, seen = [], set()
        for cid in classes:
            for part in self._partial_group(cid):
                if part not in seen and self.nodes[part][2] in TYPE_KINDS:
                    seen.add(part)
                    expanded.append(part)
        return [mid for cid in expanded for mid in self.members.get((cid, member), [])], 1.0

    def test_owner(self, nid):
        """The innermost test node at or around nid, or the file when there is none."""
        while nid in self.nodes:
            parent, kind, _, _ = self.nodes[nid]
            if kind == "test":
                return nid
            nid = parent
        return nid

    def _output_maps(self, wid):
        """(outDir, rootDir) of every tsconfig that emits, longest outDir first."""
        if wid not in self._maps:
            found = []
            for path in self.by_path[wid]:
                if manifests.TSCONFIG.search(path):
                    config = self._tsconfig(wid, path)
                    if config.get("outDir"):
                        found.append((config["outDir"], config.get("rootDir") or ""))
            self._maps[wid] = sorted(set(found), key=lambda m: (-len(m[0]), m))
        return self._maps[wid]

    def _output_dir(self, wid, file_path):
        """Directory of the compiled file. The source directory when nothing emits it."""
        directory = posixpath.dirname(file_path)
        while True:
            config_path = posixpath.join(directory, "tsconfig.json")
            if config_path in self.by_path[wid]:
                config = self._tsconfig(wid, config_path)
                out_dir = config.get("outDir")
                if out_dir:
                    root_dir = config.get("rootDir") or ""
                    if not root_dir or file_path == root_dir or file_path.startswith(root_dir + "/"):
                        rel = file_path[len(root_dir) + 1:] if root_dir else file_path
                        return _norm(posixpath.join(out_dir, posixpath.dirname(rel)))
                    return posixpath.dirname(file_path)
            if not directory:
                return posixpath.dirname(file_path)
            directory = posixpath.dirname(directory)

    def _compiled_source(self, wid, path):
        """The tracked file a path names, mapping build output back through outDir."""
        path = _norm(path)
        if not path or path.startswith("../"):
            return None
        found = self._find(wid, path)
        if found:
            return found
        stem, ext = posixpath.splitext(path)
        for out_dir, root_dir in self._output_maps(wid):
            if not out_dir or not (stem == out_dir or stem.startswith(out_dir + "/")):
                continue
            rest = stem[len(out_dir) + 1:] if stem.startswith(out_dir + "/") else ""
            if not rest and not root_dir:
                continue
            stem_in_src = _norm(posixpath.join(root_dir, rest)) if rest else root_dir
            for src_ext in manifests.SOURCE_EXTS.get(ext, ()):
                candidate = f"{stem_in_src}{src_ext}" if stem_in_src else None
                hit = candidate and self.by_path[wid].get(candidate)
                if hit:
                    return hit
        return None

    def path_target(self, fid, anchor, rel):
        """The file a literal path build in fid names. `__dirname` is the compiled directory."""
        if not rel or rel in (".", ".."):
            return None
        wid, own, _role = self.files[fid]
        if anchor == "dirname":
            base = self._output_dir(wid, own)
        elif anchor == "cwd":
            base = ""
        else:
            base = posixpath.dirname(own)
        return self._compiled_source(wid, posixpath.join(base, rel))

    def html_target(self, wid, html_path, src):
        """The file a script src in an HTML file names. A leading slash is tried beside the HTML, then at the root."""
        src = src.split("?", 1)[0].split("#", 1)[0].strip()
        if not src or "://" in src or src.startswith(("//", "data:", "javascript:", "mailto:")):
            return None
        if src.startswith("/"):
            absolute = src.lstrip("/")
            here = posixpath.dirname(html_path)
            rels = [posixpath.join(here, absolute) if here else absolute, absolute]
        else:
            rels = [posixpath.join(posixpath.dirname(html_path), src)]
        for rel in rels:
            found = self._compiled_source(wid, rel)
            if found:
                return found
        return None

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
        stem = posixpath.splitext(name)[0]
        if path.endswith(".cs"):
            stem = re.sub(r"Tests?$", "", stem)
        stem = TEST_SUFFIX.sub("", stem)
        if path.endswith(".py"):
            stem = stem.removeprefix("test_")
        if path.endswith(".cs") and not stem:
            return []
        dirs = [directory] + ([posixpath.dirname(directory)] if posixpath.basename(directory) in TEST_DIRS else [])
        out = []
        for d in dirs:
            for ext in CODE_LANGS:
                found = self.by_path[wid].get(posixpath.join(d, stem + ext))
                if found and self.files[found][2] == "code":
                    out.append(found)
        if not out and path.endswith(".py"):
            out = self._py_name_match(wid, directory, stem)
        if not out and path.endswith(".cs"):
            out = self._cs_name_match(wid, stem)
        return out

    # --- Python modules ---------------------------------------------------------

    def _py_find(self, wid, path):
        """The file a Python module path names: `path.py`, else the package's `path/__init__.py`."""
        if path == ".." or path.startswith("../"):
            return None
        paths = self.by_path[wid]
        return (paths.get(path + ".py") if path else None) or paths.get(posixpath.join(path, "__init__.py"))

    def _pyproject(self, wid, directory):
        """(directory, uv path source directories) of the nearest pyproject.toml at or above directory."""
        while True:
            path = posixpath.join(directory, "pyproject.toml")
            if path in self.by_path[wid]:
                break
            if not directory:
                return None
            directory = posixpath.dirname(directory)
        key = (wid, path)
        if key not in self._pyprojects:
            try:
                data = tomllib.loads((self.ws_dir[wid] / path).read_text())
            except (OSError, ValueError):
                data = {}
            sources = data.get("tool", {}).get("uv", {}).get("sources", {})
            dirs = []
            for entry in sources.values() if isinstance(sources, dict) else ():
                for e in entry if isinstance(entry, list) else [entry]:
                    if isinstance(e, dict) and isinstance(e.get("path"), str):
                        dirs.append(_norm(posixpath.join(directory, e["path"])))
            self._pyprojects[key] = (directory, dirs)
        return self._pyprojects[key]

    def _py_roots(self, wid, directory):
        """Directories an absolute import from a file in directory is looked up under, in order:
        the directory itself when it is not a package (scripts, pytest's rootdir insertion), the
        nearest pyproject's `src/` and directory, the same for each of its `[tool.uv.sources]`
        path sources, then the workspace's `src/` and root."""
        key = (wid, directory)
        if key not in self._py_roots_cache:
            roots = [] if posixpath.join(directory, "__init__.py") in self.by_path[wid] else [directory]
            project = self._pyproject(wid, directory)
            if project:
                for d in [project[0], *project[1]]:
                    roots += [posixpath.join(d, "src"), d]
            roots += ["src", ""]
            self._py_roots_cache[key] = list(dict.fromkeys(roots))
        return self._py_roots_cache[key]

    def _py_spec(self, wid, path, spec):
        """The file a Python module specifier (`pkg.mod`, `.mod`, `..`) in the file at path names."""
        directory = posixpath.dirname(path)
        dots = len(spec) - len(spec.lstrip("."))
        rest = spec[dots:].replace(".", "/")
        if dots:
            return self._py_find(wid, _norm(posixpath.join(directory, *[".."] * (dots - 1), rest)))
        for root in self._py_roots(wid, directory):
            found = self._py_find(wid, _norm(posixpath.join(root, rest)))
            if found:
                return found
        return None

    def py_name(self, fid, spec, name, seen):
        """Where `from spec import name` in Python file fid leads: (file id, name) for a name the
        module defines or imports, else (file id, None) for the submodule `spec.name`."""
        target = self.spec(fid, spec)
        found = target and self.export(target, name, seen)
        if found:
            return found
        sub = self.spec(fid, spec + name if spec.endswith(".") else f"{spec}.{name}")
        return (sub, None) if sub else None

    def _py_name_match(self, wid, directory, stem):
        """The one code file named `<stem>.py` in the test's pyproject (or workspace), for tests
        that do not mirror the source tree. Several candidates give no match."""
        if self._by_name is None:
            self._by_name = defaultdict(list)
            for fid, (w, path, role) in self.files.items():
                if role == "code" and path.endswith(".py"):
                    self._by_name[(w, posixpath.basename(path))].append(fid)
        project = (self._pyproject(wid, directory) or ("",))[0]
        found = [f for f in self._by_name[(wid, stem + ".py")]
                 if not project or self.files[f][1].startswith(project + "/")]
        return found if len(found) == 1 else []

    def _cs_name_match(self, wid, stem):
        """The one production file named `<stem>.cs` in the workspace. Several candidates give no match."""
        if not stem:
            return []
        if self._cs_by_name is None:
            self._cs_by_name = defaultdict(list)
            for fid, (w, path, role) in self.files.items():
                if role == "code" and path.endswith(".cs"):
                    self._cs_by_name[(w, posixpath.basename(path))].append(fid)
        found = self._cs_by_name[(wid, stem + ".cs")]
        return found if len(found) == 1 else []

    def _index_csharp(self):
        for nid, (_parent, kind, display, fid) in self.nodes.items():
            if kind != "symbol" or display not in TYPE_KINDS or not fid:
                continue
            wid, path, _role = self.files[fid]
            if not path.endswith(".cs"):
                continue
            self._cs_partials[(wid, _stem(nid))].append(nid)
        for fid, facts in self.facts.items():
            wid, path, _role = self.files[fid]
            if not path.endswith(".cs"):
                continue
            for ns in facts.get("namespaces") or []:
                if ns:
                    self._cs_ns_files[(wid, ns)].add(fid)
            for pair in facts.get("types") or []:
                if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                    continue
                ns, name = pair
                expect = f"{ns}.{name}" if ns else name
                for nid in self.members.get((fid, name), ()):
                    if self.nodes[nid][2] in TYPE_KINDS and _stem(nid) == expect:
                        self._cs_types[(wid, ns, name)].append(nid)
                        declared = self.nodes[nid][3]
                        if declared:
                            self._cs_file_types[(wid, ns, declared)].add(name)

    def _partial_group(self, nid):
        node = self.nodes.get(nid)
        if not node or not _is_cs_type(self, nid):
            return [nid]
        wid = self.files[node[3]][0]
        return self._cs_partials.get((wid, _stem(nid))) or [nid]

    def _visible_namespaces(self, fid):
        facts = self.facts.get(fid) or {}
        wid, path, _role = self.files[fid]
        spaces = set(facts.get("namespaces") or [])
        spaces.add("")
        spaces.update(facts.get("usings") or [])
        spaces.update(self._csproj_usings(wid, posixpath.dirname(path)))
        return spaces

    def _cs_names(self, fid, name):
        key = (fid, name)
        if key in self._cs_name_cache:
            return self._cs_name_cache[key]
        found = []
        path = self.files[fid][1]
        if path.endswith(".cs"):
            wid = self.files[fid][0]
            facts = self.facts.get(fid) or {}
            seen = set()
            for ns in self._visible_namespaces(fid):
                for nid in self._cs_types.get((wid, ns, name), ()):
                    if nid not in seen:
                        seen.add(nid)
                        found.append(nid)
            for alias, target in facts.get("aliases") or []:
                if alias != name or not isinstance(target, str):
                    continue
                ns, _, tname = target.rpartition(".")
                for nid in self._cs_types.get((wid, ns, tname), ()):
                    if nid not in seen:
                        seen.add(nid)
                        found.append(nid)
        self._cs_name_cache[key] = found
        return found

    def _csproj_dirs(self):
        if self._csproj_by_dir is None:
            found = defaultdict(list)
            for wid, paths in self.by_path.items():
                for path in paths:
                    if path.lower().endswith(".csproj"):
                        found[(wid, posixpath.dirname(path))].append(path)
            self._csproj_by_dir = found
        return self._csproj_by_dir

    def _csproj_usings(self, wid, directory):
        key = (wid, directory)
        if key in self._csproj_usings_cache:
            return self._csproj_usings_cache[key]
        dirs = self._csproj_dirs()
        names = []
        current = directory
        while True:
            hits = dirs.get((wid, current))
            if hits:
                names = _csproj_using_names(self.ws_dir[wid] / sorted(hits)[0])
                break
            if not current:
                break
            current = posixpath.dirname(current)
        self._csproj_usings_cache[key] = names
        return names

    def cs_type_files(self, fid, ref):
        """Files whose top-level type `ref` names. A dotted ref is that namespace; a bare name searches the visible ones."""
        wid = self.files[fid][0]
        if "." in ref:
            ns, name = ref.rsplit(".", 1)
            spaces = [ns]
        else:
            name = ref
            spaces = self._visible_namespaces(fid)
        files = []
        for ns in spaces:
            for nid in self._cs_types.get((wid, ns, name), ()):
                target = self.nodes[nid][3]
                if target and target not in files:
                    files.append(target)
        return files


def _stem(nid):
    return nid.split("#", 1)[-1].split("~", 1)[0]


def _is_cs_type(m, nid):
    node = m.nodes.get(nid)
    if not node or node[2] not in TYPE_KINDS or not node[3]:
        return False
    return m.files[node[3]][1].endswith(".cs")


def _collapse_partials(m, found):
    """One id when every candidate is a C# type of the same qualname, else None."""
    if len(found) <= 1 or not all(_is_cs_type(m, nid) for nid in found):
        return None
    stems = {_stem(nid) for nid in found}
    return found[0] if len(stems) == 1 else None


def _csproj_using_names(path):
    """`<Using Include="Namespace" />` from a csproj. Static usings are types, not namespaces."""
    try:
        text = path.read_text()
    except OSError:
        return []
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []
    out = []
    for el in root.iter():
        if el.tag.rsplit("}", 1)[-1].lower() != "using":
            continue
        if (el.attrib.get("Static") or "").lower() == "true":
            continue
        include = (el.attrib.get("Include") or "").strip()
        if include:
            out.append(include)
    return out


def _inherit_helper_calls(m, edges, add):
    """A test that calls a same-file helper inherits that helper's calls into production code.

    One level only: a helper that only calls another helper does not pass those calls on.
    """
    local_calls, test_calls = defaultdict(list), defaultdict(list)
    for (src, dst, kind, _source), (conf, _weight, _attrs) in list(edges.items()):
        if kind != "calls" or src not in m.nodes:
            continue
        _parent, src_kind, _display, src_file = m.nodes[src]
        if not src_file or m.files[src_file][2] != "test":
            continue
        dst_node = m.nodes.get(dst)
        if not dst_node or dst_node[1] != "symbol":
            continue
        dst_file = dst_node[3]
        if dst_file == src_file:
            if src_kind == "test":
                test_calls[dst].append(src)
            continue
        if src_kind == "symbol" and dst_file and m.files[dst_file][2] == "code":
            local_calls[src].append((dst, conf))
    for helper, callers in test_calls.items():
        for dst, conf in local_calls.get(helper, ()):
            for test_id in dict.fromkeys(callers):
                add(test_id, dst, "tests", "treesitter", conf)


def _import_targets(m, fid, imp):
    """(file id, type_only) for each file one import or re-export resolves to.

    A name that resolves wins. The module file is the target only when no name does,
    which is also how a namespace or side-effect import lands.
    """
    target = m.spec(fid, imp["spec"])
    pairs = list((imp["names"] or {}).items())
    type_names = set(imp.get("type_names") or [])
    whole = bool(imp.get("type_only"))
    py = m.files[fid][1].endswith(".py")
    resolved = []
    for local, imported in ((local, imported) for local, imported in pairs if imported != "*"):
        found = m.py_name(fid, imp["spec"], imported, set()) if py else (m.export(target, imported) if target else None)
        if found:
            resolved.append((found[0], whole or local in type_names))
    if resolved:
        return resolved
    if not target:
        return []
    type_only = whole or bool(pairs) and all(local in type_names for local, _ in pairs)
    return [(target, type_only)]


def _one_type(m, fid, name):
    """The one class, record, struct or interface `name` binds to in fid, or None when it is missing or ambiguous.

    Partials of one C# type are one candidate. Two different types are ambiguous.
    """
    if not name:
        return None
    found = [i for i in m._named(fid, name) if m.nodes[i][2] in ("class", "interface", "record", "struct")]
    collapsed = _collapse_partials(m, found)
    if collapsed:
        return collapsed
    return found[0] if len(found) == 1 else None


def _method_ids(m, parent, name):
    parents = m._partial_group(parent) if parent else [parent]
    return [i for pid in parents for i in m.members.get((pid, name), []) if m.nodes[i][2] == "method"]


def _arg_type(args, field):
    """The type name of the argument that fills this injected parameter, or None."""
    if not field:
        return None
    _, param, index = field
    positionals, keywords = [], {}
    for name, typ in args:
        if name:
            keywords[name] = typ
        else:
            positionals.append(typ)
    if param in keywords:
        return keywords[param]
    if index < len(positionals) and positionals[index]:
        return positionals[index]
    return None


def _code_symbol(m, nid):
    """True when nid is defined in a production file. A file id counts as itself."""
    fid = m.nodes[nid][3] if nid in m.nodes else nid
    return fid in m.files and m.files[fid][2] == "code"


def _injection(m, add, unresolved):
    """Bind `this.field.method()` / `self.field.method()` from the field's declared type and from constructors.

    An edge from a production symbol only targets a production symbol. A constructor in a
    test file counts only when the class it passes is production code, and structural
    candidates leave out classes defined in test files.
    """
    protocols = {pid for facts in m.facts.values() for pid in facts.get("protocols") or []}
    fields = defaultdict(dict)
    constructs = defaultdict(list)
    for fid, facts in m.facts.items():
        for cls, name, typ, param, index in facts.get("fields") or []:
            if cls:
                fields[cls][name] = (typ, param, index)
        for class_name, args in facts.get("constructs") or []:
            classes = [cid for cid in m._named(fid, class_name)
                       if m.nodes[cid][2] in CONCRETE_KINDS and cid not in protocols]
            chosen = _collapse_partials(m, classes) or (classes[0] if len(classes) == 1 else None)
            if chosen:
                constructs[chosen].append((fid, args))
    methods = defaultdict(set)
    by_method = defaultdict(set)
    for (parent, name), ids in m.members.items():
        if not any(m.nodes[i][2] == "method" for i in ids):
            continue
        methods[parent].add(name)
        parent_node = m.nodes.get(parent)
        if not parent_node or parent_node[2] not in CONCRETE_KINDS or parent in protocols or not parent_node[3]:
            continue
        by_method[(m.files[parent_node[3]][0], name)].add(parent)

    for fid, facts in m.facts.items():
        wid, is_test = m.files[fid][0], m.files[fid][2] == "test"
        for src, cls, field, type_name, method in facts.get("uses") or []:
            found = {}

            def keep(dsts, confidence):
                for dst in dsts:
                    found[dst] = max(found.get(dst, 0), confidence)

            tid = _one_type(m, fid, type_name)
            if tid:
                display, type_file = m.nodes[tid][2], m.nodes[tid][3]
                # C# constructor injection of an interface is structural even when the interface
                # lives in another file. A remote TS interface still binds to the interface method.
                cs_file = m.files[fid][1].endswith(".cs")
                local_shape = (type_file == fid and (display == "interface" or tid in protocols)
                               ) or (cs_file and display == "interface")
                if local_shape:
                    needed = methods.get(tid, ())
                    if method in needed:
                        cands = None
                        for name in needed:
                            got = by_method.get((wid, name), set())
                            cands = set(got) if cands is None else cands & got
                        cands = {cid for cid in (cands or ()) if _code_symbol(m, cid)}
                        if cands:
                            confidence = INJECT_STRUCTURAL / len(cands)
                            for cid in cands:
                                keep(_method_ids(m, cid, method), confidence)
                else:
                    keep(_method_ids(m, tid, method), INJECT_KNOWN)
            info = fields.get(cls, {}).get(field)
            for cfid, args in constructs.get(cls, ()):
                arg_type = _arg_type(args, info)
                classes = [cid for cid in m._named(cfid, arg_type)
                           if m.nodes[cid][2] in CONCRETE_KINDS and cid not in protocols] if arg_type else []
                passed = _collapse_partials(m, classes) or (classes[0] if len(classes) == 1 else None)
                if not passed:
                    continue
                if m.files[cfid][2] == "test" and not _code_symbol(m, passed):
                    continue
                keep(_method_ids(m, passed, method), INJECT_CONSTRUCT)
            origin = src or cls or fid
            emitted = False
            for dst, confidence in found.items():
                if _code_symbol(m, origin) and not _code_symbol(m, dst):
                    continue
                emitted = True
                add(origin, dst, "calls", "treesitter", confidence, {"via": "injection"})
                if is_test and m.nodes[dst][3] != fid:
                    add(m.test_owner(origin), dst, "tests", "treesitter", confidence)
            if not emitted:
                unresolved[fid] += 1


def _mentioned_simple(facts):
    """Simple type names this file writes. A qualified mention contributes its last segment."""
    names = set()
    for ref in facts.get("type_refs") or []:
        if isinstance(ref, str) and ref:
            names.add(ref.rsplit(".", 1)[-1])
    return names


def _csharp_imports(m, fid, facts, add, external, test_imports):
    """A namespace using links the files in it whose types this file names, at 1.0.

    Mentioning a type the file did not import that way stays a 0.4 type reference.
    A using that names no file in the model is external. An unused using is neither.
    """
    wid, path, _role = m.files[fid]
    own = m._csproj_usings(wid, posixpath.dirname(path))
    usings = list(dict.fromkeys([*(facts.get("usings") or []), *own]))
    mentioned = _mentioned_simple(facts)
    linked = set()
    for ns in usings:
        declared = m._cs_ns_files.get((wid, ns), ())
        targets = [target for target in declared if target != fid]
        if not targets:
            if fid not in declared:
                external[fid].append(ns)
            continue
        for dst in targets:
            if not (m._cs_file_types.get((wid, ns, dst), ()) & mentioned):
                continue
            add(fid, dst, "imports", "treesitter", 1.0, None)
            test_imports[fid].add(dst)
            linked.add(dst)
    for ref in facts.get("type_refs") or []:
        if not isinstance(ref, str):
            continue
        for dst in m.cs_type_files(fid, ref):
            if dst == fid or dst in linked:
                continue
            add(fid, dst, "imports", "treesitter", TYPE_REF_CONFIDENCE, {"type_ref": True})
            test_imports[fid].add(dst)


def _segs(path):
    """URL path segments. `/` is empty. A query or hash is dropped."""
    if not path:
        return None
    path = path.split("?", 1)[0].split("#", 1)[0]
    if path in ("", "/"):
        return []
    if path == "*":
        return ["*"]
    return [part for part in path.split("/") if part]


def _route_score(route, visit):
    """(param count, negative static length) when `visit` matches `route`, else None.

    A visit hole matches a `:param` or `*` segment and not a literal. A route path of `*` matches
    anything and sorts after a specific route.
    """
    if route == ["*"]:
        return (1000 + len(visit), 0)
    if len(route) != len(visit):
        return None
    params = static = 0
    for left, right in zip(route, visit):
        param = left.startswith(":") or left == "*"
        if param:
            params += 1
        elif right == "*":
            return None
        elif left == right:
            static += len(left)
        else:
            return None
    return (params, -static)


def _module_file(m, fid, spec):
    """The file a route's `import()` names, trying `.vue` when the spec has no extension."""
    found = m.spec(fid, spec)
    if found or not spec.startswith("."):
        return found
    if posixpath.splitext(spec)[1]:
        return None
    return m.spec(fid, spec + ".vue")


def _default_symbols(m, fid):
    facts = m.facts.get(fid) or {}
    name = (facts.get("exports") or {}).get("default")
    if not name:
        return []
    ids = m.members.get((fid, name), [])
    components = [nid for nid in ids if m.nodes[nid][2] == "component"]
    return components or ids


def _route_components(m, fid, item, calls):
    """Symbols a route renders. JSX and identifier components are already calls; a lazy import is not."""
    components = []
    route_id = item.get("def")
    for call in calls:
        src, cls, shape, name, member, *extra = call
        if src != route_id or not extra or extra[0] != "jsx":
            continue
        found, _confidence = m.bind(fid, cls, shape, name, member)
        if len(found) == 1 and m.nodes[found[0]][2] != "route" and found[0] not in components:
            components.append(found[0])
    imported = None
    spec = item.get("import")
    if spec:
        target = _module_file(m, fid, spec)
        exported = _default_symbols(m, target) if target else []
        if len(exported) == 1 and exported[0] not in components:
            imported = exported[0]
            components.append(imported)
    return components, imported


def _link_routes(m, add):
    """Lazy `import()` renders, and `cy.visit` tests edges onto the matched route's component."""
    tables = defaultdict(list)
    visits = []
    for fid, facts in m.facts.items():
        wid, _path, role = m.files[fid]
        calls = facts.get("calls") or []
        for item in facts.get("routes") or []:
            components, imported = _route_components(m, fid, item, calls)
            if imported and item.get("def"):
                add(item["def"], imported, "calls", "treesitter", 1.0, {"via": "jsx"})
            if item.get("path"):
                tables[wid].append((item["path"], item.get("redirect"), components, role))
        if role == "test":
            for src, pattern in facts.get("visits") or []:
                visits.append((wid, fid, src, pattern))
    for wid, fid, src, pattern in visits:
        owner = m.test_owner(src or fid)
        for dst in _match_visit(tables[wid], pattern):
            if dst in m.nodes and m.nodes[dst][3] != fid:
                add(owner, dst, "tests", "treesitter", 1.0)


def _match_visit(rows, pattern, depth=0, seen=None):
    """Component symbols of the routes `pattern` matches. A redirect is followed when the route renders nothing."""
    if depth >= 3:
        return []
    visit = _segs(pattern)
    if visit is None:
        return []
    seen = set() if seen is None else seen
    if pattern in seen:
        return []
    seen.add(pattern)
    scored = []
    for path, redirect, components, role in rows:
        route = _segs(path)
        if route is None:
            continue
        score = _route_score(route, visit)
        if score is not None:
            scored.append((role == "test", score, components, redirect))
    if not scored:
        return []
    best = min((role, score) for role, score, _components, _redirect in scored)
    winners = [item for item in scored if (item[0], item[1]) == best]
    found = []
    for _role, _score, components, redirect in winners:
        if components:
            found.extend(components)
        elif redirect and redirect not in seen:
            found.extend(_match_visit(rows, redirect, depth + 1, seen))
    return list(dict.fromkeys(found))


def _patch_file(m, fid, spec):
    """The tracked module a `patch("pkg.mod.attr")` target names. Trailing attributes are dropped."""
    parts = [part for part in spec.split(".") if part]
    for n in range(len(parts), 0, -1):
        found = m.spec(fid, ".".join(parts[:n]))
        if found:
            return found
    return None


def _write_http_routes(conn, routes):
    """Replace `http_routes` on node attrs. Handlers that lost their routes drop the key."""
    stale = []
    for nid, text in conn.execute("SELECT id, attrs FROM nodes WHERE attrs LIKE '%\"http_routes\"%'"):
        if nid not in routes:
            stale.append(nid)
            attrs = json.loads(text) if text else {}
            if isinstance(attrs, dict):
                attrs.pop("http_routes", None)
                conn.execute(
                    "UPDATE nodes SET attrs = ? WHERE id = ?",
                    (json.dumps(attrs, sort_keys=True) if attrs else None, nid),
                )
    for nid, items in routes.items():
        row = conn.execute("SELECT attrs FROM nodes WHERE id = ?", (nid,)).fetchone()
        if row is None:
            continue
        attrs = json.loads(row[0]) if row[0] else {}
        if not isinstance(attrs, dict):
            attrs = {}
        attrs["http_routes"] = items
        conn.execute("UPDATE nodes SET attrs = ? WHERE id = ?", (json.dumps(attrs, sort_keys=True), nid))
    del stale


def resolve(conn, root):
    """Replace import, call and test edges and the ambiguous_call, unmatched_test and unresolved_injection diagnostics."""
    m = _Model(conn, root)
    edges = {}

    def add(src, dst, kind, source, confidence, attrs=None):
        edge = edges.setdefault((src, dst, kind, source), [confidence, 0, None])
        if confidence > edge[0]:
            edge[0] = confidence
            edge[2] = attrs
        elif confidence == edge[0] and attrs and edge[2] is None:
            edge[2] = attrs
        edge[1] += 1

    ambiguous, test_imports, external, unread = Counter(), defaultdict(set), defaultdict(list), defaultdict(list)
    unresolved = Counter()
    for fid, facts in m.facts.items():
        counted = {}
        for imp in facts["imports"] + facts["reexports"]:
            targets = _import_targets(m, fid, imp)
            if not targets:
                external[fid].append(imp["spec"])
                continue
            seen = {}
            for dst, type_only in targets:
                if dst == fid:
                    continue
                seen[dst] = type_only if dst not in seen else seen[dst] and type_only
            for dst, type_only in seen.items():
                slot = counted.setdefault(dst, [0, True])
                slot[0] += 1
                slot[1] = slot[1] and type_only
                test_imports[fid].add(dst)
        for dst, (weight, type_only) in counted.items():
            attrs = {"type_only": True} if type_only else None
            for _ in range(weight):
                add(fid, dst, "imports", "treesitter", 1.0, attrs)
        if m.files[fid][1].endswith(".cs"):
            _csharp_imports(m, fid, facts, add, external, test_imports)

        is_test = m.files[fid][2] == "test"
        for call in facts["calls"]:
            src, cls, shape, name, member, *extra = call
            via = extra[0] if extra else None
            candidates, confidence = m.bind(fid, cls, shape, name, member)
            if len(candidates) > 1:
                ambiguous[fid] += 1
            elif candidates:
                src = src or fid
                add(src, candidates[0], "calls", "treesitter", confidence, {"via": "jsx"} if via == "jsx" else None)
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
        for src, spec in facts.get("patches") or []:
            dst = _patch_file(m, fid, spec)
            if dst and dst != fid and m.files[dst][2] == "code":
                add(m.test_owner(src or fid), dst, "tests", "treesitter", PATCH_CONFIDENCE)

    _link_routes(m, add)
    _injection(m, add, unresolved)
    for fid, facts in m.facts.items():
        if m.files[fid][2] != "code":
            continue
        for anchor, rel in facts.get("paths") or []:
            dst = m.path_target(fid, anchor, rel)
            if dst and dst != fid:
                add(fid, dst, "references", "treesitter", 1.0)
    for fid, (wid, path, _role) in m.files.items():
        if posixpath.splitext(path)[1].lower() not in (".html", ".htm"):
            continue
        try:
            text = (m.ws_dir[wid] / path).read_text(errors="replace")
        except OSError:
            continue
        for src in _script_srcs(text):
            dst = m.html_target(wid, path, src)
            if dst and dst != fid:
                add(fid, dst, "references", "html", 1.0)

    _inherit_helper_calls(m, edges, add)

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

    http_edges, http_diags, http_routes = http.link(m)
    conn.execute(f"DELETE FROM edges WHERE source IN ({', '.join('?' * len(OWNED_SOURCES))})", OWNED_SOURCES)
    conn.executemany(
        "INSERT INTO edges (src, dst, kind, source, confidence, weight, attrs) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [(*key, conf, weight, json.dumps(attrs, sort_keys=True) if attrs else None)
         for key, (conf, weight, attrs) in edges.items()],
    )
    ordinal = defaultdict(int)
    http_rows = []
    for src, dst, method, path, confidence, weight in sorted(http_edges):
        slot = ordinal[(src, dst)]
        ordinal[(src, dst)] += 1
        attrs = json.dumps({"confidence": confidence, "method": method, "path": path}, sort_keys=True)
        http_rows.append((src, dst, "http_calls", "treesitter", confidence, weight, attrs, slot))
    conn.executemany(
        "INSERT INTO edges (src, dst, kind, source, confidence, weight, attrs, ordinal) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        http_rows,
    )
    _write_http_routes(conn, http_routes)
    conn.execute(
        "DELETE FROM diagnostics WHERE kind IN "
        "('ambiguous_call', 'unmatched_test', 'unresolved_injection', 'unmatched_http_call')"
    )
    conn.executemany(
        "INSERT INTO diagnostics (node_id, kind, detail) VALUES (?, ?, ?)",
        [(fid, "ambiguous_call", f"{n} calls with more than one candidate") for fid, n in sorted(ambiguous.items())]
        + unmatched
        + [(fid, "unresolved_injection", f"{n} injected calls with no candidate") for fid, n in sorted(unresolved.items())]
        + http_diags,
    )
    from cbi.env import apply as apply_env  # local: env imports manifests, which imports this module
    apply_env(conn, root)

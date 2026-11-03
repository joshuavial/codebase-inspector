"""Deployable and package detection from manifests, structure overrides, part_of and depends_on.

Runs after resolution, because membership follows import edges. Each rule in
RULES reads one manifest type in one workspace and returns deployables and
packages; `.cbi/structure.json` then adds, renames or removes them. This step
owns the deployable and package nodes, edges with source `manifest` and the
`unresolved_entry` diagnostics, and replaces them on every scan.
"""

import json
import posixpath
import re
import shlex
import tomllib
import xml.etree.ElementTree as ET
from collections import defaultdict
from html.parser import HTMLParser
from fnmatch import fnmatchcase
from glob import has_magic
from urllib.parse import unquote, urlsplit

from cbi import resolve

# A build-output extension maps back to these source extensions, in order.
SOURCE_EXTS = {".js": (".ts", ".tsx", ".js", ".jsx"), ".mjs": (".mts", ".mjs"), ".cjs": (".cts", ".cjs"),
               ".jsx": (".tsx", ".jsx")}
SCRIPT_ENTRY = re.compile(
    r"(?:^|[\s;&|(])(?:node|tsx|ts-node(?:-esm)?|bun(?:\s+run)?|(?:uv\s+run\s+)?python3?)\s+"
    r"(?:-[-\w]+(?:=\S+)?\s+)*([\w./@-]+\.(?:py|[cm]?[jt]sx?))\b"
)
VITE_CONFIG = re.compile(r"(^|/)vite\.config\.[cm]?[jt]s$")
VITE_ROOT = re.compile(r"""\broot\s*:\s*["'`]([^"'`$]+)["'`]""")
TSCONFIG = re.compile(r"(^|/)tsconfig[^/]*\.json$")


class _Workspace:
    """The tracked paths of one workspace and readers for its manifests."""

    def __init__(self, wid, name, directory, paths, root=""):
        self.id, self.name, self.dir, self.paths, self.root = wid, name, directory, paths, root
        self._json = {}
        self._maps = None

    def json(self, path):
        if path not in self._json:
            try:
                self._json[path] = resolve._jsonc((self.dir / path).read_text())
            except (OSError, ValueError):
                self._json[path] = None
        return self._json[path]

    def toml(self, path):
        try:
            return tomllib.loads((self.dir / path).read_text())
        except (OSError, ValueError):
            return {}

    def top(self, path):
        """A workspace path as a path from the top repo."""
        return _join(self.root, path)

    def text(self, path):
        try:
            return (self.dir / path).read_text()
        except OSError:
            return None

    def _ts_options(self, path, seen=()):
        """outDir and rootDir of a tsconfig, as workspace paths, following relative `extends`."""
        data = self.json(path)
        if not isinstance(data, dict) or path in seen:
            return {}
        out = {}
        extends = data.get("extends") or []
        for parent in [extends] if isinstance(extends, str) else extends:
            if parent.startswith("."):
                parent = posixpath.normpath(posixpath.join(posixpath.dirname(path), parent))
                out.update(self._ts_options(parent if parent.endswith(".json") else parent + ".json", (*seen, path)))
        options = data.get("compilerOptions") or {}
        for key in ("outDir", "rootDir"):
            if isinstance(options.get(key), str):
                out[key] = _join(posixpath.dirname(path), options[key])
        out.setdefault("rootDir", posixpath.dirname(path))  # ponytail: tsc infers it from the inputs
        return out

    def output_maps(self):
        """(outDir, rootDir) of every tracked tsconfig that emits, longest outDir first."""
        if self._maps is None:
            maps = {(o["outDir"], o["rootDir"]) for p in self.paths if TSCONFIG.search(p)
                    for o in [self._ts_options(p)] if "outDir" in o}
            self._maps = sorted(maps, key=lambda m: (-len(m[0]), m))
        return self._maps

    def to_source(self, path):
        """The tracked source file a (possibly build-output) workspace path stands for, or None."""
        if path in self.paths:
            return path
        stem, ext = posixpath.splitext(path)
        for out_dir, root_dir in self.output_maps():
            if out_dir and stem.startswith(out_dir + "/"):
                stem_in_src = _join(root_dir, stem[len(out_dir) + 1:])
                for src_ext in SOURCE_EXTS.get(ext, ()):
                    if stem_in_src + src_ext in self.paths:
                        return stem_in_src + src_ext
        return None


def _join(directory, path):
    joined = posixpath.normpath(posixpath.join(directory, path))
    return "" if joined == "." else joined


def _deployable(name, display_kind, manifest, evidence, entries):
    """entries: [(raw value, resolved workspace path or None)]"""
    return {"name": name, "display_kind": display_kind, "manifest": manifest, "evidence": evidence, "entries": entries}


# --- rules ----------------------------------------------------------------------


def _verify_target(raw):
    """A node path that is a test, smoke or e2e file, not an app entry."""
    parts = [p for p in raw.replace("\\", "/").split("/") if p not in ("", ".")]
    if not parts:
        return False
    if {p.lower() for p in parts[:-1]} & {"test", "tests", "__tests__", "e2e", "smoke"}:
        return True
    name = parts[-1].lower()
    if ".test." in name or ".spec." in name or ".e2e." in name:
        return True
    stem = name.rsplit(".", 1)[0]
    return stem in {"smoke", "e2e"} or stem.endswith(("-smoke", "-e2e", ".smoke", ".e2e", "_smoke", "_e2e"))


def _tooling_script(name, raws=()):
    """Dev and verify tooling is not a deployable.

    That is a script named lint or test, a name starting with dev: or verify:,
    or a node command whose every target is a test, smoke or e2e file.
    """
    if name in ("lint", "test") or name.startswith(("dev:", "verify:")):
        return True
    return bool(raws) and all(_verify_target(r) for r in raws)


def package_json(ws):
    """`main`, `bin` and scripts run through Node, TS or Python become deployables. Scripts named
    `lint` or `test`, starting with `dev:` or `verify:`, or running only a test, smoke or
    e2e file, do not, unless structure.json names them. A package.json below the workspace
    root is a package. The `main` of a package that another package.json depends on is a
    library entry, not a deployable."""
    deployables, packages = [], []
    manifests = {p: ws.json(p) for p in sorted(ws.paths) if posixpath.basename(p) == "package.json"}
    manifests = {p: d for p, d in manifests.items() if isinstance(d, dict)}
    _deps = lambda d: {**(d.get("dependencies") or {}), **(d.get("devDependencies") or {})}
    libraries = {name for d in manifests.values() for name in _deps(d)}
    for path, data in manifests.items():
        here = posixpath.dirname(path)
        name = data.get("name") if isinstance(data.get("name"), str) else posixpath.basename(here) or ws.name
        entry = lambda raw: (raw, ws.to_source(_join(here, raw)))
        if here:
            packages.append({"name": name, "directory": here, "manifest": path})
        if isinstance(data.get("main"), str) and name not in libraries:
            kind = "electron app" if "electron" in _deps(data) else "node app"
            deployables.append(_deployable(name, kind, path, "package.json main", [entry(data["main"])]))
        bins = data.get("bin")
        bins = {name: bins} if isinstance(bins, str) else bins if isinstance(bins, dict) else {}
        for bin_name, raw in sorted(bins.items()):
            if isinstance(raw, str):
                deployables.append(_deployable(bin_name, "cli", path, "package.json bin", [entry(raw)]))
        for script, command in (data.get("scripts") or {}).items():
            raws = SCRIPT_ENTRY.findall(command) if isinstance(command, str) else []
            if _tooling_script(script, raws):
                continue
            raws = [r for r in raws if not _verify_target(r)]
            if raws:
                deployables.append(_deployable(script, "node app", path, f"package.json script {script}",
                                               [entry(r) for r in raws]))
    return deployables, packages


class _ModuleScripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.srcs = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script" and attrs.get("type") == "module" and attrs.get("src"):
            self.srcs.append(attrs["src"])


def vite(ws):
    """Each Vite config's `<script type="module" src>` entries from the index.html at its `root`
    (a string literal in the config, or the config's directory)."""
    deployables = []
    for path in sorted(p for p in ws.paths if VITE_CONFIG.search(p)):
        here = posixpath.dirname(path)
        match = VITE_ROOT.search(ws.text(path) or "")
        root = _join(here, match.group(1)) if match else here
        html = posixpath.join(root, "index.html") if root else "index.html"
        name = f"{posixpath.basename(root) or ws.name}-web"
        if html not in ws.paths:
            deployables.append(_deployable(name, "web app", path, "vite config", [(html, None)]))
            continue
        parser = _ModuleScripts()
        parser.feed(ws.text(html) or "")
        entries = [(src, ws.to_source(_join(root, src.lstrip("/")))) for src in parser.srcs]
        deployables.append(_deployable(name, "web app", path, f"vite config, {html}", entries or [(html, None)]))
    return deployables, []


def _py_module(ws, here, dotted):
    """The tracked file of a dotted module under `here`, src layout first, or None."""
    for base in (_join(here, "src"), here):
        stem = _join(base, dotted.replace(".", "/"))
        for path in (stem + ".py", stem + "/__init__.py"):
            if path in ws.paths:
                return path
    return None


def _project_table(data):
    """PEP 621 `[project]`, filled from `[tool.poetry]` where the project table is silent.

    Poetry's `package-mode = false` is an application, not a package. Its scripts are still
    commands. A project table name wins over the poetry name.
    """
    project = data.get("project") if isinstance(data.get("project"), dict) else {}
    tool = data.get("tool") if isinstance(data.get("tool"), dict) else {}
    poetry = tool.get("poetry") if isinstance(tool.get("poetry"), dict) else {}
    name = project.get("name") if isinstance(project.get("name"), str) else None
    if name is None and isinstance(poetry.get("name"), str) and poetry.get("package-mode") is not False:
        name = poetry["name"]
    scripts = project.get("scripts") if isinstance(project.get("scripts"), dict) else None
    if scripts is None and isinstance(poetry.get("scripts"), dict):
        scripts = poetry["scripts"]
    return name, scripts or {}


def pyproject(ws):
    """`[project.scripts]` entries are deployables whose entry is the module file of `pkg.mod:func`;
    the project is a package; `[tool.uv.sources]` path entries are depends_on links between packages.
    `[tool.poetry]` supplies the name and scripts when `[project]` does not."""
    deployables, packages = [], []
    for path in sorted(p for p in ws.paths if posixpath.basename(p) == "pyproject.toml"):
        data, here = ws.toml(path), posixpath.dirname(path)
        name, scripts = _project_table(data)
        for script, target in sorted(scripts.items()):
            if isinstance(target, str):
                module = target.split(":")[0].strip()
                deployables.append(_deployable(script, "cli", path, "pyproject.toml scripts",
                                               [(target, _py_module(ws, here, module))]))
        if isinstance(name, str):
            sources = ((data.get("tool") or {}).get("uv") or {}).get("sources") or {}
            links = [f"dir:{ws.top(_join(here, s['path']))}" for s in sources.values()
                     if isinstance(s, dict) and isinstance(s.get("path"), str)]
            packages.append({"name": name, "directory": here, "manifest": path,
                             "ref": f"dir:{ws.top(here)}", "depends_on": links})
    return deployables, packages


DOCKERFILE = re.compile(r"(^|/)(Dockerfile|Dockerfile\.[^/]+|Containerfile)$")


def _tokens(value):
    """Literal exec argv or shell words, without executing or expanding anything."""
    if isinstance(value, list):
        return [str(v) for v in value]
    try:
        value = json.loads(value) if value and value.startswith("[") else value
        return [str(v) for v in value] if isinstance(value, list) else shlex.split(value or "")
    except ValueError:
        return (value or "").split()


def _docker_command(value):
    """Retain Docker's exec versus shell form until command resolution."""
    try:
        parsed = json.loads(value)
    except ValueError:
        return value
    return [str(part) for part in parsed] if isinstance(parsed, list) else value


def _effective_command(commands):
    entry, command = commands.get("ENTRYPOINT"), commands.get("CMD")
    if isinstance(entry, str) and entry:
        return entry  # a shell ENTRYPOINT ignores CMD arguments
    if entry:
        args = ["/bin/sh", "-c", command] if isinstance(command, str) and command else command or []
        return entry + args
    return command or []


def _shell_argv(text):
    """Read one literal shell command, preserving quoted/escaped operators as argument data.

    Compound programs, redirections and substitutions stay unresolved. Nothing is executed.
    """
    tokens, word, quote, active, i = [], [], None, False, 0
    while i < len(text):
        char = text[i]
        if quote == "'":
            if char == "'":
                quote = None
            else:
                word.append(char)
        elif char == "\\":
            if i + 1 == len(text):
                return []
            following = text[i + 1]
            if quote == '"' and following not in '$`"\\\n':
                word.append(char)
                i += 1
                continue
            if following != "\n":
                word.append(following)
                active = True
            i += 2
            continue
        elif quote == '"' and char == '"':
            quote = None
        elif quote is None and char in "\"'":
            quote, active = char, True
        elif quote is None and char in "\n;&|<>()":
            if char == "\n" and not text[i:].strip():
                break
            return []
        elif char == "`" or char == "$" and text[i:i + 2] == "$(":
            return []
        elif quote is None and char.isspace():
            if active:
                tokens.append("".join(word))
                word, active = [], False
        elif quote is None and char == "#" and not active:
            end = text.find("\n", i)
            if end >= 0 and text[end:].strip():
                return []
            break
        else:
            word.append(char)
            active = True
        i += 1
    if quote:
        return []
    if active:
        tokens.append("".join(word))
    return tokens


def _image_path(workdir, path):
    return posixpath.normpath(posixpath.join(workdir, path))


def _forget_image_destination(state, dest, *, directory=False, basename=None):
    """Drop only paths an unknown copy may overwrite, retaining constrained siblings."""
    prefix = dest.rstrip("/") + "/"

    def affected(path):
        if path == dest:
            return True
        if not path.startswith(prefix):
            return False
        child = path[len(prefix):].split("/", 1)[0]
        return not directory or basename is None or fnmatchcase(child, basename)

    state["files"] = {f: tracked for f, tracked in state["files"].items() if not affected(f)}


def _copy_pattern_matches(path, pattern):
    """COPY globs match individual path components, not across directory separators."""
    parts, patterns = path.split("/"), pattern.split("/")
    return len(parts) == len(patterns) and all(fnmatchcase(p, g) for p, g in zip(parts, patterns))


def _remember_image_directory(state, directory):
    """WORKDIR and COPY create directories whose identity survives later WORKDIR changes."""
    while directory not in state["dirs"]:
        state["dirs"].add(directory)
        directory = posixpath.dirname(directory)


def _docker_state(ws, path, context, target=None):
    """Track literal files in each build stage; remote, dynamic and generated copies stay unknown."""
    stages, named = [], {}
    state = {"files": {}, "workdir": "/", "commands": {}, "copies": False, "cmd_inherited": False, "dirs": {"/"}}
    text = re.sub(r"\\\n", " ", (ws.text(path) or "") if path in ws.paths else "")
    for line in text.splitlines():
        parts = line.split(None, 1)
        if not parts:
            continue
        instruction, value = parts[0].upper(), parts[1].strip() if len(parts) > 1 else ""
        if instruction == "FROM":
            words = _tokens(value)
            words = [w for w in words if not w.startswith("--")]
            parent = named.get(words[0]) if words else None
            state = {"files": dict(parent["files"]) if parent else {},
                     "dirs": set(parent["dirs"]) if parent else {"/"},
                     "workdir": parent["workdir"] if parent else "/",
                     "commands": dict(parent["commands"]) if parent else {},
                     "copies": parent["copies"] if parent else False,
                     "cmd_inherited": bool(parent and "CMD" in parent["commands"])}
            stages.append(state)
            named[str(len(stages) - 1)] = state
            if len(words) >= 3 and words[-2].upper() == "AS":
                named[words[-1]] = state
        elif instruction == "WORKDIR" and value and not re.search(r"[$*?]", value):
            state["workdir"] = _image_path(state["workdir"], value)
            _remember_image_directory(state, state["workdir"])
        elif instruction in ("CMD", "ENTRYPOINT"):
            state["commands"][instruction] = _docker_command(value)
            if instruction == "CMD":
                state["cmd_inherited"] = False
            if instruction == "ENTRYPOINT" and state["cmd_inherited"]:
                state["commands"].pop("CMD", None)  # a new entrypoint clears an inherited CMD
        elif instruction in ("COPY", "ADD"):
            state["copies"] = True
            flags = {}
            while value.startswith("--"):
                parts = value.split(None, 1)
                flag, value = parts[0], parts[1] if len(parts) > 1 else ""
                key, _, val = flag[2:].partition("=")
                flags[key] = val
                value = value.lstrip()
            words = _tokens(value)
            if len(words) < 2:
                continue
            sources, dest = words[:-1], words[-1]
            if re.search(r"[$*?]", dest):
                state["files"].clear()  # the destination could overwrite any mapped path
                continue
            dest = _image_path(state["workdir"], dest)
            origin = named.get(flags["from"]) if "from" in flags else None
            external = "from" in flags and origin is None
            available = dict(origin["files"]) if origin else {"/" + p: p for p in ws.paths
                if not context or p.startswith(context + "/")}
            if external:
                available = {}
            dest_dir = dest in state["dirs"] or words[-1].endswith("/") or len(sources) > 1
            if dest_dir:
                _remember_image_directory(state, dest)
            for source in sources:
                if "$" in source:
                    _forget_image_destination(state, dest)
                    continue
                if "://" in source:
                    try:
                        basename = posixpath.basename(unquote(urlsplit(source).path)) or None
                    except ValueError:
                        basename = None
                    _forget_image_destination(state, dest, directory=dest_dir, basename=basename)
                    continue
                if has_magic(source):
                    basename = None
                    if instruction == "COPY" and not external and not source.endswith("/"):
                        pattern = _image_path("/" if origin else "/" + context, source.lstrip("/"))
                        directories = set(origin["dirs"]) if origin else {"/"}
                        for file in available:
                            directory = posixpath.dirname(file)
                            while directory not in directories:
                                directories.add(directory)
                                directory = posixpath.dirname(directory)
                        if not any(_copy_pattern_matches(d, pattern) for d in directories):
                            basename = posixpath.basename(source)
                    _forget_image_destination(state, dest, directory=dest_dir, basename=basename)
                    continue
                if external:
                    _forget_image_destination(state, dest)
                    continue
                source = _image_path("/" if origin else "/" + context, source.lstrip("/"))
                prefix = source.rstrip("/") + "/"
                directory = any(f.startswith(prefix) for f in available)
                matches = [(f, tracked) for f, tracked in available.items() if f == source or f.startswith(prefix)]
                if not matches:
                    _forget_image_destination(state, dest)
                for f, tracked in matches:
                    suffix = f[len(prefix):] if directory else posixpath.basename(source)
                    destination = _join(dest, suffix) if directory or dest_dir or len(sources) > 1 else dest
                    _remember_image_directory(state, posixpath.dirname(destination))
                    state["files"][destination] = tracked
    return named.get(target, state) if target else state


def _compose_services(ws, path):
    """Malformed document and service shapes contribute no services to any manifest reader."""
    data = _yaml(ws.text(path) or "")
    services = data.get("services") if isinstance(data, dict) else None
    return services if isinstance(services, dict) else {}


def _docker_builds(ws):
    """Known local build contexts, relative to each Compose file."""
    builds = defaultdict(list)
    for path in sorted(p for p in ws.paths if COMPOSE.search(p)):
        for svc in _compose_services(ws, path).values():
            build = svc.get("build") if isinstance(svc, dict) else None
            build = {"context": build} if isinstance(build, str) else build
            if not isinstance(build, dict):
                continue
            context = _join(posixpath.dirname(path), build.get("context") or ".")
            docker = _join(context, build.get("dockerfile") or "Dockerfile")
            builds[docker].append((context, build.get("target")))
    return builds


def _shell_invocation(tokens):
    """Separate shell options from a script path or the command argument selected by -c."""
    args, command, stdin = tokens[1:], False, False
    while args:
        option = args[0]
        if option == "--":
            args = args[1:]
            break
        if option == "-":
            return None  # read standard input, not a script named by the next argument
        if not option.startswith(("-", "+")):
            break
        args = args[1:]
        if option in ("--noprofile", "--norc", "--posix", "--login"):
            continue
        if option in ("--rcfile", "--init-file"):
            if not args:
                return None
            args = args[1:]
            continue
        flags = option[1:]
        if not flags or any(flag not in "abCefhiklmnoprstuvxBDEHOPTc" for flag in flags):
            return None
        if "c" in flags:
            if option.startswith("+"):
                return None
            command = True
        if "s" in flags and option.startswith("-"):
            stdin = True
        if "o" in flags or "O" in flags:
            if flags[-1] not in "oO" or not args:
                return None
            args = args[1:]
    if not args or stdin and not command:
        return None
    return ("command", args[:1]) if command else ("file", args)


def _runtime_argv(command):
    """Keep argv boundaries and unwrap only literal exec, shell -c and project runners."""
    tokens = _shell_argv(command) if isinstance(command, str) else _tokens(command)
    for _ in range(8):
        if not tokens:
            return []
        executable = posixpath.basename(tokens[0])
        if executable in ("sh", "bash", "ash"):
            invocation = _shell_invocation(tokens)
            if invocation is None:
                return []
            mode, args = invocation
            if mode == "command":
                tokens = _shell_argv(args[0])
            else:
                tokens = [tokens[0], *args]
                return tokens
        elif tokens[0] == "exec":
            tokens = tokens[1:]
        elif executable in ("uv", "poetry") and tokens[1:2] == ["run"]:
            tokens = tokens[2:]
        else:
            return tokens
    return []


def _script_argument(tokens):
    """The file argument of a supported interpreter, excluding inline code and module modes."""
    if not tokens or posixpath.basename(tokens[0]) not in (
            "python", "python3", "node", "tsx", "ts-node", "ts-node-esm", "bun", "sh", "bash", "ash"):
        return None
    args = tokens[1:]
    if posixpath.basename(tokens[0]) == "bun" and args[:1] == ["run"]:
        args = args[1:]
    while args and args[0].startswith("-") and posixpath.basename(tokens[0]) not in ("sh", "bash", "ash"):
        if args[0] in ("-m", "-c", "-e", "--eval", "-p", "--print"):
            return None
        args = args[1:]
    return args[0] if args and not re.search(r"[$`*?]", args[0]) else None


def _module_argument(tokens):
    if not tokens:
        return None
    executable = posixpath.basename(tokens[0])
    args = tokens[1:]
    if executable in ("python", "python3"):
        while args and args[0] in ("-u", "-B", "-O", "-OO", "-I", "-s", "-S", "-E"):
            args = args[1:]
        target = args[1] if len(args) >= 2 and args[0] == "-m" else ""
        return target if re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", target) else None
    if executable in ("uvicorn", "gunicorn", "hypercorn") and args:
        match = re.fullmatch(r"([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)(?::[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*(?:\(\))?)?", args[0])
        return match.group(1) if match else None
    return None


def _docker_entry(ws, here, tokens, scripts, state=None):
    """Resolve only executable paths and supported interpreter file arguments."""
    if not tokens:
        return None
    if tokens[0] in scripts:
        return scripts[tokens[0]]
    for token in (tokens[0], _script_argument(tokens)):
        if not token or re.search(r"[$`*?]", token):
            continue
        if state:
            source = state["files"].get(_image_path(state["workdir"], token))
            if source:
                return source
        if ("/" in token or "." in token) and not (state and state["copies"]):
            # Legacy images without literal copies may still name a source path directly.
            parts = [p for p in token.split("/") if p not in ("", ".")]
            for k in range(len(parts)):
                for base in (here, ""):
                    found = ws.to_source(_join(base, "/".join(parts[k:])))
                    if found:
                        return found
    return None


def _project_scripts(ws):
    return {d["name"]: d["entries"][0][1] for d in pyproject(ws)[0] + package_json(ws)[0]
            if d["display_kind"] == "cli" and d["entries"][0][1]}


def _idle_command(tokens):
    """Known intentional keepalive commands, with literal shell/exec wrappers only."""
    tokens = _runtime_argv(tokens)
    if not tokens:
        return False
    command = [posixpath.basename(tokens[0]), *tokens[1:]]
    return command in (["tail", "-f", "/dev/null"], ["tail", "-F", "/dev/null"],
                       ["tail", "--follow", "/dev/null"], ["sleep", "infinity"], ["sleep", "inf"])


def dockerfile(ws):
    """Container image entries resolved through literal stage-local COPY/ADD paths and argv."""
    deployables, builds = [], _docker_builds(ws)
    for path in sorted(p for p in ws.paths if DOCKERFILE.search(p) and not p.endswith((".tmpl", ".dockerignore"))):
        here, base = posixpath.dirname(path), posixpath.basename(path)
        name = posixpath.basename(here) or ws.name
        if "." in base:
            name += "-" + base.split(".", 1)[1]
        entries, artifacts = [], []
        for context, target in dict.fromkeys(builds.get(path) or [(here, None)]):
            state = _docker_state(ws, path, context, target)
            command = _effective_command(state["commands"])
            raw = " ".join(_tokens(command)) or "no CMD or ENTRYPOINT"
            if _idle_command(command):
                artifacts.append(raw)
                continue
            resolved = _command_entries(ws, context, command, state) if command else _compose_image_entries(ws, path)
            entries += resolved or [(raw, None)]
        deployables.append({**_deployable(name + "-image", "container image", path, "Dockerfile", entries),
                            "ref": f"file:{ws.top(path)}",
                            **({"artifact_command": "; ".join(artifacts)} if artifacts else {})})
    return deployables, []


COMPOSE = re.compile(r"(^|/)(docker-compose[^/]*|compose[^/]*)\.ya?ml$")
def _npm_entries(ws, here, tokens, state, seen):
    """Follow package scripts at the runtime package, with a cycle guard and tracked web roots."""
    if not tokens or posixpath.basename(tokens[0]) != "npm":
        return []
    package = state["files"].get(_image_path(state["workdir"], "package.json")) if state else None
    package = package or _join(here, "package.json")
    data = ws.json(package) if package in ws.paths else None
    if not isinstance(data, dict):
        return []
    script = tokens[2] if len(tokens) > 2 and tokens[1] in ("run", "run-script") else tokens[1] if len(tokens) > 1 else ""
    key = (package, script)
    command = (data.get("scripts") or {}).get(script)
    if key in seen or not isinstance(command, str):
        return []
    here = posixpath.dirname(package)
    found = _command_entries(ws, here, command, state, (*seen, key))
    script_tokens = _runtime_argv(command)
    raw = _script_argument(script_tokens)
    if raw:
        path = ws.to_source(_join(here, raw))
        if path:
            found.append((raw, path))
    if script_tokens and script_tokens[0] == "vite":
        configs = [d for d in vite(ws)[0] if posixpath.dirname(d["manifest"]) == here]
        if configs:
            found += [entry for d in configs for entry in d["entries"] if entry[1]]
        else:
            html = _join(here, "index.html")
            if html in ws.paths:
                parser = _ModuleScripts()
                parser.feed(ws.text(html) or "")
                found += [(src, ws.to_source(_join(here, src.lstrip("/")))) for src in parser.srcs]
    return [(raw, path) for raw, path in found if path]


def _command_entries(ws, here, command, state=None, seen=()):
    """Resolve literal module commands and simple shell wrappers without running target code."""
    tokens = _runtime_argv(command)
    if not tokens or _idle_command(tokens):
        return []
    text = " ".join(_tokens(command))
    module = _module_argument(tokens)
    found = []
    if module:
        path = None
        if state:
            stem = _image_path(state["workdir"], module.replace(".", "/"))
            path = state["files"].get(stem + ".py") or state["files"].get(stem + "/__init__.py")
        path = path or _py_module(ws, here, module) or _py_module(ws, "", module)
        if path:
            found.append((module, path))
    found += _npm_entries(ws, here, tokens, state, seen)
    entry = _docker_entry(ws, here, tokens, _project_scripts(ws), state)
    if entry:
        found.append((text, entry))
        if entry not in seen and (entry.endswith(".sh") or (ws.text(entry) or "").startswith("#!/bin/sh")):
            for line in (ws.text(entry) or "").splitlines():
                # Only literal executable lines, including branches, not comments or echoed commands.
                if re.match(r"^\s*(?:exec\s+|uvicorn\s+|gunicorn\s+|hypercorn\s+|python3?\s+)", line):
                    found += _command_entries(ws, here, line, state, (*seen, entry))
    return [(raw, path) for path, raw in {path: raw for raw, path in found}.items()]


def _service_entries(ws, svc, docker, context):
    state = _docker_state(ws, docker, context, (svc.get("build") or {}).get("target")
                          if isinstance(svc.get("build"), dict) else None)
    if isinstance(svc.get("working_dir"), str):
        state["workdir"] = _image_path(state["workdir"], svc["working_dir"])
    commands = dict(state["commands"])
    if svc.get("entrypoint") is not None:
        commands["ENTRYPOINT"] = _tokens(svc["entrypoint"])
        commands.pop("CMD", None)
    if svc.get("command") is not None:
        commands["CMD"] = _tokens(svc["command"])
    return _command_entries(ws, context, _effective_command(commands), state)


def _compose_image_entries(ws, docker):
    """A commandless build gets startup evidence from its Compose services."""
    entries = []
    for path in sorted(p for p in ws.paths if COMPOSE.search(p)):
        for svc in _compose_services(ws, path).values():
            build = svc.get("build") if isinstance(svc, dict) else None
            build = {"context": build} if isinstance(build, str) else build
            if not isinstance(build, dict):
                continue
            context = _join(posixpath.dirname(path), build.get("context") or ".")
            if _join(context, build.get("dockerfile") or "Dockerfile") == docker:
                entries += _service_entries(ws, svc, docker, context)
    return list(dict.fromkeys(entries))


def _yaml_scalar(text):
    text = re.sub(r"^[&!]\S+\s*", "", text.strip())  # anchors and tags
    if text in ("null", "Null", "NULL", "~"):
        return None
    if text.startswith("[") and text.endswith("]"):
        return [_yaml_scalar(t) for t in text[1:-1].split(",") if t.strip()]
    if text.startswith("{") and text.endswith("}"):
        pairs = (t.split(":", 1) for t in text[1:-1].split(",") if ":" in t)
        return {_yaml_scalar(k): _yaml_scalar(v) for k, v in pairs}
    return text[1:-1] if len(text) > 1 and text[0] == text[-1] and text[0] in "'\"" else text


_BLOCK = re.compile(r"^([|>])([-+]?)([1-9])?$")


def _block_scalar(lines, i, parent_indent, style):
    """The body of a `|` or `>` scalar. Folded style joins wrapped lines with a space."""
    chunk = []
    while i < len(lines) and lines[i][0] > parent_indent:
        chunk.append(lines[i])
        i += 1
    if not chunk:
        return "", i
    base = min(ind for ind, _ in chunk)
    parts = [" " * (ind - base) + text for ind, text in chunk]
    if style == "|":
        return "\n".join(parts), i
    out, buf = [], []
    for line in parts:
        if line.strip():
            buf.append(line.strip())
        elif buf:
            out.append(" ".join(buf))
            buf = []
    if buf:
        out.append(" ".join(buf))
    return "\n".join(out), i


def _yaml(text):
    """A minimal block-YAML reader for compose files: mappings, lists, flow collections and
    scalars. Anchors are dropped, aliases and multi-line strings are kept as raw text."""
    lines = []
    for line in text.splitlines():
        line = re.sub(r"(^|\s)#.*$", "", line).rstrip()
        content = line.lstrip()
        if not content or content in ("---", "..."):
            continue
        indent = len(line) - len(content)
        if content.startswith("- ") and re.match(r"[\w.-]+:(\s|$)", content[2:]):
            lines += [(indent, "-"), (indent + 2, content[2:])]
        else:
            lines.append((indent, content))

    def skip(i, indent):  # past what this reader does not understand
        while i < len(lines) and lines[i][0] > indent:
            i += 1
        return i

    def block(i, indent):
        if i >= len(lines) or lines[i][0] < indent:
            return None, i
        indent = lines[i][0]
        is_item = lambda i: i < len(lines) and lines[i][0] == indent and lines[i][1].split(" ")[0] == "-"
        if is_item(i):
            items = []
            while is_item(i):
                rest = lines[i][1][2:]
                if rest:
                    items.append(_yaml_scalar(rest))
                    i = skip(i + 1, indent)
                else:
                    value, i = block(i + 1, indent + 1)
                    items.append(value)
            return items, i
        mapping = {}
        while i < len(lines) and lines[i][0] == indent:
            key, _, raw = lines[i][1].partition(":")
            raw = raw.strip()
            i += 1
            marker = _BLOCK.match(raw)
            if marker:
                rest, i = _block_scalar(lines, i, indent, marker.group(1))
            elif raw == "" and i < len(lines) and lines[i][0] > indent:
                rest, i = block(i, indent + 1)
            elif raw == "" and is_item(i):
                rest, i = block(i, indent)
            else:
                rest = _yaml_scalar(raw) if raw else ""
            mapping[_yaml_scalar(key)] = rest
            i = skip(i, indent)
        return mapping, i

    return block(0, 0)[0]


def compose(ws):
    """Compose services with `build` are deployables linked to their Dockerfile's deployable; services
    with only `image` are external services. Service `depends_on` become depends_on links. A `command`
    that runs a Python module is that service's entry, so several services can share one image and
    still name different programs. Compose files in one directory merge, as `docker compose -f a -f b`
    would: a service is defined by the file with the shortest name that gives it a `build` or `image`,
    and collects every file's depends_on."""
    found, links = {}, defaultdict(list)
    paths = sorted((p for p in ws.paths if COMPOSE.search(p)), key=lambda p: (posixpath.dirname(p), len(p), p))
    for path in paths:
        here = posixpath.dirname(path)
        for name, svc in _compose_services(ws, path).items():
            if not isinstance(svc, dict):
                continue
            ref = f"compose:{ws.top(here)}:{{}}"
            deps = svc.get("depends_on")
            links[ref.format(name)] += [ref.format(d) for d in deps if isinstance(d, str)] if isinstance(deps, (list, dict)) else []
            build = svc.get("build")
            if ref.format(name) in found:
                continue
            if isinstance(build, (str, dict)):
                build = {"context": build} if isinstance(build, str) else build
                context = _join(here, build.get("context") or ".")
                docker = _join(context, build.get("dockerfile") or "Dockerfile")
                entries = (_service_entries(ws, svc, docker, context)
                           if any(svc.get(key) is not None for key in ("command", "entrypoint", "working_dir")) else [])
                if not entries:
                    entries = [] if docker in ws.paths else [(docker, None)]
                found[ref.format(name)] = {**_deployable(name, "service", path, f"compose service {name}", entries),
                                           "ref": ref.format(name), "depends_on": [f"file:{ws.top(docker)}"]}
            elif isinstance(svc.get("image"), str):
                found[ref.format(name)] = {"name": name, "display_kind": "service", "manifest": path,
                                           "image": svc["image"], "ref": ref.format(name), "depends_on": [], "external": 1}
    for ref, node in found.items():
        node["depends_on"] += links[ref]
    return ([n for n in found.values() if "external" not in n], [],
            [n for n in found.values() if "external" in n])


# A generated OpenNext worker has no source twin. The app root, in this order, is the entry.
_NEXT_ROOTS = (
    "src/app/layout.tsx", "app/layout.tsx", "src/app/layout.jsx", "app/layout.jsx",
    "src/pages/_app.tsx", "pages/_app.tsx", "src/pages/_app.jsx", "pages/_app.jsx",
    "src/app/page.tsx", "app/page.tsx", "src/pages/index.tsx", "pages/index.tsx",
    "src/middleware.ts", "middleware.ts",
)


def _next_root(ws, here):
    for rel in _NEXT_ROOTS:
        path = _join(here, rel)
        if path in ws.paths:
            return path
    return None


def wrangler(ws):
    """A wrangler.toml `main` is a worker's entry point.

    A path under a tsconfig outDir maps back to source, as a package.json `bin` does.
    `.open-next/worker.js` is generated by OpenNext, so the entry is the Next.js app root.
    """
    deployables = []
    for path in sorted(p for p in ws.paths if posixpath.basename(p) == "wrangler.toml"):
        data, here = ws.toml(path), posixpath.dirname(path)
        raw = data.get("main")
        if isinstance(raw, str):
            source = ws.to_source(_join(here, raw))
            if source is None and posixpath.normpath(raw).startswith(".open-next/"):
                source = _next_root(ws, here)
            name = data.get("name") if isinstance(data.get("name"), str) else posixpath.basename(here) or ws.name
            deployables.append(_deployable(name, "worker", path, "wrangler.toml main", [(raw, source)]))
    return deployables, []


AGENT_ASSET = re.compile(r"((?:[^/]+/)*?(\.claude/skills|\.agents?/skills|repertoires)/([^/]+))/")


def agent_assets(ws):
    """Each directory under a skills dir or `repertoires/` is a package. A tracked symlink is one
    path with nothing below it, so a symlinked skills dir is never counted twice."""
    packages = {}
    for path in sorted(ws.paths):
        match = AGENT_ASSET.match(path)
        if match:
            kind = "repertoire" if match.group(2) == "repertoires" else "skill"
            packages.setdefault(match.group(1), {"name": match.group(3), "directory": match.group(1),
                                                 "manifest": match.group(1), "display_kind": kind})
    return [], list(packages.values())


# tsconfig projects contribute the outDir/rootDir map used by to_source.
# Container images come after the rules whose scripts they can name.
_SLN_PROJECT = re.compile(r'^Project\("\{([^}"]+)\}"\)\s*=\s*"[^"]*"\s*,\s*"([^"]+)"', re.MULTILINE)
_SOLUTION_FOLDER = "2150e333-8fdc-42a3-9474-1a3956d46de8"


def _local_name(tag):
    return tag.rsplit("}", 1)[-1]


def _program_cs(ws, directory, project_dirs):
    """`Program.cs` in the project directory, else the nearest one not owned by a nested project."""
    direct = posixpath.join(directory, "Program.cs") if directory else "Program.cs"
    if direct in ws.paths:
        return direct
    nested = [d for d in project_dirs if d and d != directory and (not directory or d.startswith(directory + "/"))]
    prefix = f"{directory}/" if directory else ""
    found = []
    for path in ws.paths:
        if posixpath.basename(path) != "Program.cs":
            continue
        if prefix and not path.startswith(prefix):
            continue
        if any(path.startswith(d + "/") for d in nested):
            continue
        found.append(path)
    if not found:
        return None
    depth = min(path.count("/") for path in found)
    near = [path for path in found if path.count("/") == depth]
    return near[0] if len(near) == 1 else None


def _sdk_text(root):
    parts = [root.attrib.get("Sdk") or ""]
    for el in root.iter():
        if _local_name(el.tag) != "Sdk":
            continue
        parts.append(el.attrib.get("Name") or "")
        parts.append(el.text or "")
    return " ".join(parts)


def dotnet(ws):
    """Each `*.csproj` is a package. ProjectReference is depends_on. Web SDK and Exe projects are deployables.

    A `*.sln` is a solution package that depends on the projects it lists. Solution folders are skipped.
    A test project (`*.Tests.csproj`) is a package and not a deployable.
    """
    deployables, packages = [], []
    csprojs = sorted(path for path in ws.paths if path.lower().endswith(".csproj"))
    all_dirs = [posixpath.dirname(path) for path in csprojs]
    by_path, taken = {}, set()
    for path in csprojs:
        text = ws.text(path)
        if text is None:
            continue
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            continue
        stem = posixpath.splitext(posixpath.basename(path))[0]
        name = stem
        n = 2
        while name in taken:
            name = f"{stem}-{n}"
            n += 1
        taken.add(name)
        directory = posixpath.dirname(path)
        requires = []
        output = ""
        for el in root.iter():
            local = _local_name(el.tag)
            if local == "OutputType" and (el.text or "").strip():
                output = el.text.strip()
            elif local == "ProjectReference":
                include = (el.attrib.get("Include") or "").replace("\\", "/")
                if include:
                    requires.append(posixpath.normpath(posixpath.join(directory, include)))
        packages.append({
            "name": name, "directory": directory, "manifest": path, "display_kind": "package", "requires": requires,
        })
        by_path[path] = name
        test_project = posixpath.basename(path).lower().endswith(".tests.csproj")
        sdk = _sdk_text(root)
        if test_project:
            continue
        if "Microsoft.NET.Sdk.Web" in sdk:
            kind = "web app"
        elif output.lower() in ("exe", "winexe"):
            kind = "program"
        else:
            continue
        entry = _program_cs(ws, directory, all_dirs)
        deployables.append(_deployable(name, kind, path, path, [("Program.cs", entry)]))
    for package in packages:
        package["requires"] = [
            by_path.get(ref) or posixpath.splitext(posixpath.basename(ref))[0] for ref in package["requires"]
        ]
    for path in sorted(p for p in ws.paths if p.lower().endswith(".sln")):
        text = ws.text(path) or ""
        requires = []
        for guid, rel in _SLN_PROJECT.findall(text):
            if guid.lower() == _SOLUTION_FOLDER:
                continue
            rel = posixpath.normpath(posixpath.join(posixpath.dirname(path), rel.replace("\\", "/")))
            if rel == ".":
                rel = ""
            requires.append(by_path.get(rel) or posixpath.splitext(posixpath.basename(rel))[0])
        stem = posixpath.splitext(posixpath.basename(path))[0]
        name = f"{stem}-sln" if stem in taken else stem
        taken.add(name)
        packages.append({
            "name": name, "directory": posixpath.dirname(path), "manifest": path,
            "display_kind": "solution", "requires": requires,
        })
    return deployables, packages


RULES = (package_json, vite, pyproject, wrangler, agent_assets, dockerfile, compose, dotnet)


# --- structure.json -------------------------------------------------------------


def _owner(workspaces, top_path):
    """The deepest workspace containing a top-repo path, and the path inside it."""
    best = max((w for w in workspaces if not w.root or top_path.startswith(w.root + "/")), key=lambda w: len(w.root))
    return best, top_path[len(best.root) + 1:] if best.root else top_path


def _apply_structure(structure, workspaces, deployables, packages):
    """Apply overrides to {id: node dict} maps in place. Paths in structure.json are from the top repo."""
    for kind, found in (("deployable", deployables), ("package", packages)):
        for item in structure.get(kind + "s") or []:
            if not isinstance(item, dict):
                continue
            paths = item.get("entry_points") if kind == "deployable" else [item.get("directory")]
            paths = [p for p in paths or [] if isinstance(p, str)]
            nid = item.get("id")
            if not nid and isinstance(item.get("name"), str):
                ws = _owner(workspaces, paths[0])[0] if paths else workspaces[0]
                nid = f"{ws.id}:{kind}:{item['name']}"
            if not nid:
                continue
            if item.get("remove"):
                found.pop(nid, None)
                continue
            node = found.setdefault(nid, {"id": nid, "ws": workspaces[0], "display_kind": kind, "entries": [],
                                          "evidence": "structure.json", "manifest": None})
            if paths:
                node["ws"] = _owner(workspaces, paths[0])[0]
                ws_paths = [_owner(workspaces, p)[1] for p in paths]
                if kind == "deployable":
                    node["entries"] = [(p, node["ws"].to_source(rel)) for p, rel in zip(paths, ws_paths)]
                else:
                    node["directory"] = ws_paths[0]
            node["name"] = item.get("name") or node.get("name") or nid.rsplit(":", 1)[-1]
            node["display_kind"] = item.get("display_kind") or node["display_kind"]
            if node["evidence"] != "structure.json":
                node["evidence"] += ", structure.json"


# --- detection ------------------------------------------------------------------


def _detect(conn, root, structure_text):
    workspaces, paths = [], defaultdict(set)
    for wid, path in conn.execute("SELECT workspace_id, path FROM nodes WHERE kind IN ('file', 'doc')"):
        paths[wid].add(path)
    for wid, name, attrs in conn.execute("SELECT id, name, attrs FROM nodes WHERE kind = 'workspace' ORDER BY id"):
        ws_root = json.loads(attrs or "{}").get("root") or ""
        workspaces.append(_Workspace(wid, name, root / ws_root, paths[wid], ws_root))
    workspaces.sort(key=lambda w: (len(w.root), w.id))  # the top repo first

    deployables, packages, externals = {}, {}, {}
    for ws in workspaces:
        seen_entries = set()
        for rule in RULES:
            found_deps, found_pkgs, *found_exts = rule(ws)
            for d in found_deps:
                resolved = {e for _, e in d["entries"] if e}
                if resolved and resolved <= seen_entries and d["display_kind"] not in ("container image", "service"):
                    continue  # the same program reached through another manifest field
                seen_entries |= resolved
                name, n = d["name"], 1
                while f"{ws.id}:deployable:{name}" in deployables:
                    n += 1
                    name = f"{d['name']}-{n}"
                deployables[f"{ws.id}:deployable:{name}"] = {**d, "id": f"{ws.id}:deployable:{name}", "name": name, "ws": ws}
            for p in found_pkgs:
                packages.setdefault(f"{ws.id}:package:{p['name']}", {
                    **p, "id": f"{ws.id}:package:{p['name']}", "ws": ws, "display_kind": p.get("display_kind", "package"),
                    "evidence": p["manifest"]})
            for e in (found_exts or [[]])[0]:
                externals.setdefault(f"{ws.id}:service:{e['name']}", {**e, "id": f"{ws.id}:service:{e['name']}", "ws": ws})
    try:
        structure = json.loads(structure_text) if structure_text else {}
    except ValueError:
        structure = {}
    if isinstance(structure, dict):
        _apply_structure(structure, workspaces, deployables, packages)
    return deployables, packages, externals


def npm_packages(ws_dir, paths):
    """{package name: (directory, source entry or None)} for the package.json files below the workspace root."""
    ws = _Workspace(None, "", ws_dir, paths)
    out = {}
    for p in package_json(ws)[1]:
        data = ws.json(p["manifest"])
        main = next((data[k] for k in ("source", "main") if isinstance(data.get(k), str)), None)
        out[p["name"]] = (p["directory"], main and ws.to_source(_join(p["directory"], main)))
    return out


def apply(conn, root, structure_text):
    """Replace deployable, package and compose service nodes, manifest edges and unresolved_entry diagnostics."""
    deployables, packages, externals = _detect(conn, root, structure_text)
    nodes, edges, diagnostics = [], set(), []

    def add(src, dst, kind, via=None):
        attrs = json.dumps({"via": via}, sort_keys=True) if via else None
        edges.add((src, dst, kind, attrs))
    imports = defaultdict(set)
    for src, dst in conn.execute("SELECT src, dst FROM edges WHERE kind = 'imports'"):
        imports[src].add(dst)

    # Each file belongs to the package with the deepest directory containing it.
    package_of = {}
    for pid, p in sorted(packages.items(), key=lambda kv: (
            len(kv[1].get("directory") or ""), kv[1].get("display_kind") != "solution")):
        directory = p.get("directory") or ""
        for path in p["ws"].paths:
            if not directory or path.startswith(directory + "/"):
                package_of[f"{p['ws'].id}:{path}"] = pid
    for fid, pid in package_of.items():
        add(fid, pid, "part_of", "direct")
    for fid, pid in package_of.items():
        for dst in imports[fid]:
            if package_of.get(dst, pid) != pid:
                add(pid, package_of[dst], "depends_on")
    for pid, p in packages.items():
        for req in p.get("requires") or []:
            target = f"{p['ws'].id}:package:{req}"
            if target in packages and target != pid:
                add(pid, target, "depends_on")

    for did, d in sorted(deployables.items()):
        ws = d["ws"]
        entries = [f"{ws.id}:{e}" for _, e in d["entries"] if e]
        members, todo = set(entries), list(entries)
        while todo:
            for dst in imports[todo.pop()] - members:
                members.add(dst)
                todo.append(dst)
        own = {package_of.get(e) for e in entries}
        entry_ids = set(entries)
        for fid in members:
            add(fid, did, "part_of", "direct" if fid in entry_ids else "transitive")
            if fid in package_of and package_of[fid] not in own:
                add(did, package_of[fid], "depends_on")
        for raw, resolved in d["entries"]:
            if not resolved:
                diagnostics.append((did, f"{d['evidence']}: {raw} maps to no tracked source file"))
        nodes.append({"id": did, "display_kind": d["display_kind"], "name": d["name"], "ws": ws.id,
                      "path": d.get("manifest"), "kind": "deployable",
                      "attrs": {"entry_points": [e for _, e in d["entries"] if e], "evidence": d["evidence"],
                                "members": len(members),
                                **({"artifact_command": d["artifact_command"]} if d.get("artifact_command") else {})}})
    for pid, p in sorted(packages.items()):
        nodes.append({"id": pid, "display_kind": p["display_kind"], "name": p["name"], "ws": p["ws"].id,
                      "path": p.get("directory"), "kind": "package",
                      "attrs": {"directory": p.get("directory"), "evidence": p["evidence"],
                                "members": sum(1 for v in package_of.values() if v == pid)}})
    for eid, e in sorted(externals.items()):
        nodes.append({"id": eid, "display_kind": e["display_kind"], "name": e["name"], "ws": e["ws"].id,
                      "path": e["manifest"], "kind": "external",
                      "attrs": {"image": e["image"], "evidence": f"{e['manifest']} service {e['name']}"}})
    # Links named by rules (uv path sources, compose services and their Dockerfiles).
    found = {**deployables, **packages, **externals}
    refs = {n["ref"]: nid for nid, n in found.items() if "ref" in n}
    for nid, n in found.items():
        for ref in n.get("depends_on") or []:
            if refs.get(ref, nid) != nid:
                add(nid, refs[ref], "depends_on")

    conn.executemany(
        "INSERT INTO nodes (id, parent_id, kind, display_kind, name, workspace_id, path, attrs) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET parent_id = excluded.parent_id, "
        "kind = excluded.kind, display_kind = excluded.display_kind, name = excluded.name, "
        "workspace_id = excluded.workspace_id, path = excluded.path, attrs = excluded.attrs",
        [(n["id"], n["ws"], n["kind"], n["display_kind"], n["name"], n["ws"], n["path"],
          json.dumps(n["attrs"], sort_keys=True)) for n in nodes],
    )
    keep = json.dumps([n["id"] for n in nodes])
    conn.execute("DELETE FROM nodes WHERE (kind IN ('deployable', 'package') OR kind = 'external' AND id GLOB '*:service:*') "
                 "AND id NOT IN (SELECT value FROM json_each(?))", (keep,))
    conn.execute("DELETE FROM edges WHERE source = 'manifest'")
    conn.executemany(
        "INSERT INTO edges (src, dst, kind, source, attrs) VALUES (?, ?, ?, 'manifest', ?)",
        sorted(edges, key=lambda e: (*e[:3], e[3] or "")),
    )
    conn.execute("DELETE FROM diagnostics WHERE kind = 'unresolved_entry'")
    conn.executemany("INSERT INTO diagnostics (node_id, kind, detail) VALUES (?, 'unresolved_entry', ?)", diagnostics)
    from cbi.graph import record_cycles  # local: graph does not import manifests
    record_cycles(conn)

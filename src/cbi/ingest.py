"""Load lcov, coverage.py JSON and JUnit XML into coverage_lines, results and coverage `tests` edges."""

import json
import os
import posixpath
import re
import tomllib
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

from cbi import store

# Commands `cbi prime` prints for a runner named by package.json or pyproject.toml.
# The service recipe in HELP is one worked example of the node:test shape.
PYTEST_COMMANDS = (
    "coverage run --context=test -m pytest",
    'coverage json --show-contexts -o "$OUT/coverage.json"',
    'pytest --junitxml="$OUT/junit.xml"',
    'cbi ingest "$OUT/coverage.json" "$OUT/junit.xml"',
)
VITEST_COMMANDS = (
    "npx vitest run --coverage --coverage.reporter=lcov "
    '--coverage.reportsDirectory="$OUT" --reporter=junit --outputFile="$OUT/junit.xml"',
    'cbi ingest "$OUT/lcov.info" "$OUT/junit.xml"',
)
JEST_COMMANDS = (
    'npx jest --coverage --coverageReporters=lcov --coverageDirectory="$OUT"',
    'cbi ingest "$OUT/lcov.info"',
)
NODE_TEST_COMMANDS = (
    "OUT=$(mktemp -d)",
    "node --enable-source-maps --test --experimental-test-coverage \\",
    '--test-reporter=lcov --test-reporter-destination="$OUT/suite.lcov" \\',
    '--test-reporter=junit --test-reporter-destination="$OUT/suite.junit.xml" \\',
    '"<compiled tests>"',
    'cbi ingest "$OUT/suite.lcov" "$OUT/suite.junit.xml"',
)
_RUNNER_COMMANDS = {
    "node:test": NODE_TEST_COMMANDS,
    "vitest": VITEST_COMMANDS,
    "jest": JEST_COMMANDS,
    "pytest": PYTEST_COMMANDS,
}
_RUNNER_ORDER = ("node:test", "vitest", "jest", "pytest")
_NODE_TEST = re.compile(r"\bnode\s+--test(?:\s|$)")
_TOOL_CALL = {
    "vitest": re.compile(r"(?:^|[\s;&|])vitest(?:\s|$)"),
    "jest": re.compile(r"(?:^|[\s;&|])jest(?:\s|$)"),
}


def _render_commands(commands, indent, out_flag=""):
    """Shell lines. A line after a trailing backslash is indented as a continuation."""
    lines, cont = [], False
    for command in commands:
        text = _with_out(command, out_flag)
        lines.append(" " * (indent + (2 if cont else 0)) + text)
        cont = text.endswith("\\")
    return lines


def _with_out(command, out_flag):
    if out_flag and command.startswith("cbi ingest "):
        return "cbi ingest" + out_flag + command[len("cbi ingest"):]
    return command


def _help_block(commands):
    return "\n".join(_render_commands(commands, 4))


HELP = f"""\
Load coverage and test result files into the model. The format is detected
from the content. Load several suites one after another: each file's rows
replace only the rows from an earlier load of the same path, and a line
counts as covered if any loaded file hit it. Paths and test cases that match
nothing in the model become unmapped_coverage diagnostics and are counted
in the output.

Producing each format:

  lcov         most JS runners (c8, nyc, vitest, jest --coverage,
               node --test-reporter=lcov) and pytest-cov --cov-report=lcov.
  coverage.py  coverage run --context=test -m pytest  (or pytest --cov
               --cov-context=test), then coverage json --show-contexts.
               The contexts link each test to the code it ran.
  JUnit XML    pytest --junitxml=FILE, node --test-reporter=junit,
               vitest --reporter=junit, jest-junit.

Commands for the runners `cbi prime` detects from package.json and
pyproject.toml. Write the reports outside the repo. Coverage paths must
name tracked source files.

  pytest:
{_help_block(PYTEST_COMMANDS)}

  vitest:
{_help_block(VITEST_COMMANDS)}

  jest:
{_help_block(JEST_COMMANDS)}
    jest-junit adds a JUnit file when that reporter is installed.

  node:test:
{_help_block(NODE_TEST_COMMANDS)}
    For TypeScript, compile with tsc --sourceMap into $OUT first and run
    node --enable-source-maps. Rewriting paths is not enough when the
    compiler moves lines.

Example: a TypeScript service suite, one node:test run that compiles first.
Other suites in the same repo use the same shape with their own tsconfig.
When the tests expect the repo layout around their cwd, mirror that layout
in the temp dir with read-only symlinks and run from there. Run from the
repo root:

  REPO=$PWD OUT=$(cd "$(mktemp -d)" && pwd -P)
  for p in node_modules service; do
    ln -s "$REPO/$p" "$OUT/$p"
  done
  npx tsc -p service/tsconfig.test.json --sourceMap --outDir "$OUT/dist-service-test"
  (cd "$OUT" && node --enable-source-maps --test \\
    --test-force-exit --test-timeout=60000 --experimental-test-coverage \\
    --test-reporter=lcov --test-reporter-destination=service.lcov \\
    --test-reporter=junit --test-reporter-destination=service.junit.xml \\
    "dist-service-test/service/**/*.test.js")
  cbi ingest "$OUT/service.lcov" "$OUT/service.junit.xml"

--test-force-exit and --test-timeout stop one hanging test from keeping the
run alive, which would leave the report files empty. pwd -P matters on
macOS: mktemp returns a /var path that is really /private/var, and source
maps written against the one do not resolve from the other, which also
leaves the lcov file empty.

Exit codes: 0 done, 1 no model, 2 a file could not be read or parsed."""


def _dist_name(spec):
    """The distribution name in a PEP 508 requirement, without extras or version."""
    if not isinstance(spec, str):
        return ""
    token = spec.strip().split(";", 1)[0].strip()
    return re.split(r"[\[<>=!~\s]", token, maxsplit=1)[0].lower()


def _add_specs(items, names):
    for spec in items or []:
        name = _dist_name(spec)
        if name:
            names.add(name)


def _add_poetry(block, names):
    if isinstance(block, dict):
        names.update(key.lower() for key in block)


def runners_in_package(text, path):
    """Runners named by this package.json: node:test, vitest, jest."""
    try:
        data = json.loads(text)
    except ValueError:
        return []
    if not isinstance(data, dict):
        return []
    deps = {}
    for key in ("dependencies", "devDependencies", "optionalDependencies"):
        block = data.get(key) or {}
        if isinstance(block, dict):
            deps.update(block)
    scripts = data.get("scripts") if isinstance(data.get("scripts"), dict) else {}
    found = []
    node_scripts = [
        (name, command) for name, command in scripts.items()
        if isinstance(command, str) and _NODE_TEST.search(command)
    ]
    if node_scripts:
        found.append({"runner": "node:test", "source": path, "scripts": node_scripts})
    for runner in ("vitest", "jest"):
        called = any(isinstance(command, str) and _TOOL_CALL[runner].search(command) for command in scripts.values())
        if runner in deps or called:
            found.append({"runner": runner, "source": path, "scripts": []})
    return found


def runners_in_pyproject(text, path):
    """pytest, when pyproject.toml depends on it or configures tool.pytest."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return []
    if not isinstance(data, dict):
        return []
    names = set()
    project = data.get("project") or {}
    _add_specs(project.get("dependencies"), names)
    for group in (project.get("optional-dependencies") or {}).values():
        _add_specs(group, names)
    for group in (data.get("dependency-groups") or {}).values():
        _add_specs(group, names)
    tool = data.get("tool") or {}
    if isinstance(tool, dict) and "pytest" in tool:
        names.add("pytest")
    poetry = tool.get("poetry") if isinstance(tool, dict) else None
    if isinstance(poetry, dict):
        _add_poetry(poetry.get("dependencies"), names)
        _add_poetry(poetry.get("dev-dependencies"), names)
        for group in (poetry.get("group") or {}).values():
            if isinstance(group, dict):
                _add_poetry(group.get("dependencies"), names)
    if "pytest" not in names:
        return []
    return [{"runner": "pytest", "source": path, "scripts": []}]


def _script_hint(command):
    """The env, tsc project and node --test tail of a package.json script."""
    bits = []
    env = re.search(r"\bNODE_ENV=\S+", command)
    if env:
        bits.append(env.group(0))
    tsc = re.search(r"\btsc\s+-p\s+\S+", command)
    if tsc:
        bits.append(tsc.group(0))
    node = re.search(r"\bnode\s+--test\b.*", command)
    if node:
        bits.append(node.group(0).strip())
    return " && ".join(bits) if bits else command.strip()


def _manifest_rows(conn):
    return conn.execute(
        "SELECT n.name, n.path, coalesce(json_extract(w.attrs, '$.root'), '') "
        "FROM nodes n LEFT JOIN nodes w ON w.id = n.workspace_id "
        "WHERE n.kind = 'file' AND n.name IN ('package.json', 'pyproject.toml') "
        "ORDER BY n.path, n.name"
    )


def guide_lines(conn, root, out_flag=""):
    """Ingest lines for `cbi prime`, from the manifests stored in the model."""
    grouped = {}
    for name, path, ws_root in _manifest_rows(conn):
        rel = posixpath.join(ws_root, path) if ws_root else path
        try:
            text = (Path(root) / rel).read_text(encoding="utf-8")
        except OSError:
            continue
        hits = runners_in_package(text, rel) if name == "package.json" else runners_in_pyproject(text, rel)
        for hit in hits:
            grouped.setdefault(hit["runner"], []).append(hit)
    if not grouped:
        return [
            "No test runner detected in package.json or pyproject.toml.",
            "`cbi ingest --help` lists lcov, coverage.py JSON and JUnit XML.",
        ]
    lines = ["Runners named in the manifests. Write the reports outside the repo."]
    for runner in _RUNNER_ORDER:
        hits = grouped.get(runner)
        if not hits:
            continue
        where = ", ".join(dict.fromkeys(hit["source"] for hit in hits))
        lines.append(f"{runner} ({where}):")
        lines.extend(_render_commands(_RUNNER_COMMANDS[runner], 2, out_flag))
        if runner == "node:test":
            lines.append("  TypeScript: compile with tsc --sourceMap into $OUT and keep --enable-source-maps.")
            lines.append("  `cbi ingest --help` has one suite written out (a TypeScript service).")
            hints = [f"{hit['source']} {name}: {_script_hint(command)}" for hit in hits for name, command in hit["scripts"]]
            if hints:
                lines.append("  scripts here:")
                lines.extend(f"  {hint}" for hint in hints)
    return lines


class UnknownFormat(Exception):
    pass


def detect(text):
    """The artifact format from its content: lcov, coverage.py or junit."""
    head = text.lstrip()
    if head.startswith("<"):
        if "<testsuite" in head or "<testcase" in head:
            return "junit"
    elif head.startswith("{"):
        try:
            data = json.loads(head)
        except ValueError:
            data = None
        if isinstance(data, dict) and "format" in (data.get("meta") or {}):
            return "coverage.py"
    elif re.search(r"^(TN|SF):", head, re.M):
        return "lcov"
    raise UnknownFormat("not lcov, coverage.py JSON or JUnit XML")


def parse_lcov(text):
    """{path: {line: hits}} from SF/DA records."""
    out = {}
    lines = None
    for raw in text.splitlines():
        if raw.startswith("SF:"):
            lines = out.setdefault(raw[3:].strip(), {})
        elif raw.startswith("DA:") and lines is not None:
            line, hits = raw[3:].split(",")[:2]
            lines[int(line)] = max(lines.get(int(line), 0), int(hits))
        elif raw.startswith("end_of_record"):
            lines = None
    return out


def parse_coverage_py(text):
    """({path: {line: hits}}, {path: {line: [context, ...]}}) from `coverage json` output.

    coverage.py records whether a line ran, not how often, so hits are 1 or 0.
    Contexts appear only with `coverage json --show-contexts`.
    """
    data = json.loads(text)
    lines, contexts = {}, {}
    for path, f in (data.get("files") or {}).items():
        hits = {n: 0 for n in f.get("missing_lines", [])}
        hits.update({n: 1 for n in f.get("executed_lines", [])})
        lines[path] = hits
        if f.get("contexts"):
            contexts[path] = {int(n): c for n, c in f["contexts"].items()}
    return lines, contexts


def parse_junit(text):
    """[{file, classname, suites, name, status, duration_ms}] for every testcase."""
    cases = []

    def walk(el, suites):
        for child in el:
            if child.tag == "testsuite":
                walk(child, suites + [child.get("name", "")])
            elif child.tag == "testcase":
                tags = {c.tag for c in child}
                status = "failed" if tags & {"failure", "error"} else "skipped" if "skipped" in tags else "passed"
                time = child.get("time")
                cases.append({
                    "file": child.get("file"), "classname": child.get("classname"), "suites": suites,
                    "name": child.get("name", ""), "status": status,
                    "duration_ms": float(time) * 1000 if time else None,
                })
            else:
                walk(child, suites)

    root = ET.fromstring(text)
    walk(root, [root.get("name", "")] if root.tag == "testsuite" else [])
    return cases


class Model:
    """Lookups from artifact paths and test names to model nodes."""

    def __init__(self, conn, repo_root, cwd, artifact_dir=None):
        self.conn = conn
        # roots[1] is the repo root; the artifact's folder catches paths relative to the runner's cwd.
        self.roots = [Path(os.path.realpath(cwd)), Path(os.path.realpath(repo_root))]
        if artifact_dir:
            self.roots.append(Path(artifact_dir))
        self.files = {}  # path from the repo root -> file node ID
        for fid, path, ws_root in conn.execute(
            "SELECT n.id, n.path, json_extract(w.attrs, '$.root') FROM nodes n "
            "LEFT JOIN nodes w ON w.id = n.workspace_id WHERE n.kind = 'file'"
        ):
            self.files[f"{ws_root}/{path}" if ws_root else path] = fid
        self.workspace = conn.execute(
            "SELECT id FROM nodes WHERE kind = 'workspace' AND parent_id IS NULL ORDER BY id").fetchone()

    def file(self, path):
        """The file node ID for an artifact path (absolute, or relative to cwd, the repo root or the artifact), or None."""
        path = path.removeprefix("file://")
        for base in self.roots:
            full = os.path.realpath(os.path.join(base, path))
            # Stored paths use forward slashes. relpath uses the host separator.
            # On Windows a coverage file on another drive raises ValueError here.
            # That path is outside the repo, so it stays unmapped.
            try:
                rel = os.path.relpath(full, self.roots[1])
            except ValueError:
                continue
            rel = rel.replace("\\", "/")
            if rel in self.files:
                return self.files[rel]
        return None

    def tests_in(self, file_id):
        """[(node ID, name)] of test nodes in a file."""
        return self.conn.execute(
            "SELECT n.id, n.name FROM nodes n JOIN nodes f ON f.id = ? "
            "WHERE n.kind = 'test' AND n.workspace_id = f.workspace_id AND n.path = f.path ORDER BY n.id",
            (file_id,)).fetchall()

    def test_named(self, file_id, chain):
        """The test node in file_id whose ID ends with the name chain, else the one test named (or templated) chain[-1]."""
        tests = self.tests_in(file_id) if file_id else self.conn.execute(
            "SELECT id, name FROM nodes WHERE kind = 'test' ORDER BY id").fetchall()
        for i in range(len(chain)):
            suffix = "#" + " > ".join(chain[i:])
            hits = [t for t, _ in tests if t.endswith(suffix) or t.endswith("." + suffix[1:])]
            if len(hits) == 1:
                return hits[0]
        hits = [t for t, name in tests if name == chain[-1]]
        if not hits:  # test(`rejects ${kind}`) in a loop: each ${...} matches any text
            hits = [t for t, name in tests if "${" in name and re.fullmatch(
                ".+?".join(map(re.escape, re.split(r"\$\{[^}]*\}", name))), chain[-1])]
        return hits[0] if len(hits) == 1 else None

    def innermost_symbols(self, file_id, lines):
        """{symbol ID: line count} giving each line to the smallest symbol containing it."""
        spans = self.conn.execute(
            "SELECT n.id, n.start_line, n.end_line FROM nodes n JOIN nodes f ON f.id = ? "
            "WHERE n.kind = 'symbol' AND n.workspace_id = f.workspace_id AND n.path = f.path "
            "ORDER BY n.end_line - n.start_line", (file_id,)).fetchall()
        out = defaultdict(int)
        for line in lines:
            # ponytail: linear scan of spans per line; index by line if files grow huge.
            for sid, start, end in spans:
                if start <= line <= end:
                    out[sid] += 1
                    break
        return out


def _context_test(model, context):
    """The test node a coverage.py context names, or None.

    pytest-cov writes `tests/test_x.py::TestA::test_b|run`; coverage's
    dynamic_context = test_function writes `tests.test_x.TestA.test_b`.
    """
    context = context.split("|")[0]
    if "::" in context:
        path, *chain = context.split("::")
        fid = model.file(path)
        return model.test_named(fid, chain) if fid else None
    parts = context.split(".")
    for i in range(len(parts) - 1, 0, -1):
        fid = model.file("/".join(parts[:i]) + ".py")
        if fid:
            return model.test_named(fid, parts[i:])
    return None


def _junit_file(model, case):
    if case["file"]:
        return model.file(case["file"])
    classname = case["classname"] or ""
    for i in range(classname.count(".") + 1, 0, -1):  # pytest: tests.test_x.TestA
        fid = model.file("/".join(classname.split(".")[:i]) + ".py")
        if fid:
            return fid
    return None


def ingest(conn, repo_root, cwd, artifact):
    """Load one artifact file, replacing rows from an earlier load of the same path. Returns counts."""
    artifact = Path(os.path.realpath(artifact))
    key = str(artifact)
    text = artifact.read_text()
    fmt = detect(text)
    model = Model(conn, repo_root, cwd, artifact.parent)
    ws = model.workspace[0] if model.workspace else ""
    rows, results, edges, diagnostics = [], [], defaultdict(int), []
    lines, contexts = ({}, {})
    if fmt == "lcov":
        lines = parse_lcov(text)
    elif fmt == "coverage.py":
        lines, contexts = parse_coverage_py(text)
    for path, hits in lines.items():
        fid = model.file(path)
        if not fid:
            diagnostics.append((ws, "unmapped_coverage", f"{key}: coverage path {path} matches no tracked file"))
            continue
        rows += [(fid, line, n, key) for line, n in hits.items()]
        by_test = defaultdict(list)
        for line, names in contexts.get(path, {}).items():
            for name in names:
                if name:  # "" is coverage.py's context for code run outside any test
                    by_test[name].append(line)
        for name, test_lines in by_test.items():
            tid = _context_test(model, name)
            if not tid:
                diagnostics.append((fid, "unmapped_coverage", f"{key}: context {name} matches no test case"))
                continue
            for sid, count in model.innermost_symbols(fid, test_lines).items():
                edges[(tid, sid)] += count
    if fmt == "junit":
        for case in parse_junit(text):
            fid = _junit_file(model, case)
            tid = model.test_named(fid, [s for s in case["suites"] if s] + [case["name"]])
            if tid:
                results.append((tid, case["status"], case["duration_ms"], key))
            else:
                where = case["file"] or case["classname"] or "no file"
                diagnostics.append((fid or ws, "unmapped_coverage",
                                    f"{key}: test {case['name']!r} ({where}) matches no test case"))
    diagnostics = list(dict.fromkeys(diagnostics))
    record = {"format": fmt, "edges": [[s, d, w] for (s, d), w in sorted(edges.items())], "diagnostics": diagnostics}
    with conn:
        old = store.get_meta(conn, "ingest:" + key)
        if old:
            for d in json.loads(old)["diagnostics"]:
                conn.execute("DELETE FROM diagnostics WHERE rowid IN (SELECT rowid FROM diagnostics "
                             "WHERE node_id = ? AND kind = ? AND detail = ? LIMIT 1)", d)
        conn.execute("DELETE FROM coverage_lines WHERE artifact = ?", (key,))
        conn.execute("DELETE FROM results WHERE artifact = ?", (key,))
        conn.executemany("INSERT INTO coverage_lines (file_id, line, hits, artifact) VALUES (?, ?, ?, ?)", rows)
        conn.executemany("INSERT INTO results (test_node_id, status, duration_ms, artifact) VALUES (?, ?, ?, ?)", results)
        conn.executemany("INSERT INTO diagnostics (node_id, kind, detail) VALUES (?, ?, ?)", diagnostics)
        store.set_meta(conn, "ingest:" + key, json.dumps(record))
        _rebuild_edges(conn)
    return {"artifact": key, "format": fmt, "files": len({r[0] for r in rows}), "lines": len(rows),
            "results": len(results), "edges": len(edges), "unmapped": len(diagnostics)}


def _rebuild_edges(conn):
    """Coverage `tests` edges as the union over every ingested artifact, so artifacts merge."""
    edges = defaultdict(int)
    for (value,) in conn.execute("SELECT value FROM meta WHERE key LIKE 'ingest:%'"):
        for src, dst, weight in json.loads(value)["edges"]:
            edges[(src, dst)] = max(edges[(src, dst)], weight)
    conn.execute("DELETE FROM edges WHERE source = 'coverage'")
    conn.executemany(
        "INSERT INTO edges (src, dst, kind, source, confidence, weight) VALUES (?, ?, 'tests', 'coverage', 1.0, ?)",
        [(s, d, w) for (s, d), w in edges.items()])


def coverage(conn, node_id):
    """(covered lines, measured lines) for a file or symbol, a line counting as covered if any artifact hit it."""
    node = conn.execute("SELECT kind, workspace_id, path, start_line, end_line FROM nodes WHERE id = ?",
                        (node_id,)).fetchone()
    if not node:
        return 0, 0
    kind, ws, path, start, end = node
    fid = node_id if kind == "file" else conn.execute(
        "SELECT id FROM nodes WHERE kind = 'file' AND workspace_id = ? AND path = ?", (ws, path)).fetchone()[0]
    lo, hi = (start, end) if kind != "file" else (0, 1 << 31)
    return conn.execute(
        "SELECT count(*) FILTER (WHERE h > 0), count(*) FROM (SELECT max(hits) AS h FROM coverage_lines "
        "WHERE file_id = ? AND line BETWEEN ? AND ? GROUP BY line)", (fid, lo, hi)).fetchone()

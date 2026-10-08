"""Reviewer queries: hotspots, orphans, cycles, deps, and the show and test-link fixes."""

import json
import sqlite3

import pytest

from cbi.cli import main

WS = "local:review"

FILES = {
    "package.json": json.dumps({
        "name": "app",
        "main": "dist/service/main.js",
        "scripts": {
            "start:job": "node dist/worker/job.js",
            "dev:web": "node scripts/dev.js",
            "verify:pkg": "node scripts/verify.js",
            "lint": "node scripts/lint.js",
            "test": "node scripts/run-tests.js",
            "dev": "node scripts/bare-dev.js",
            "lint:strict": "node scripts/lint-strict.js",
        },
    }),
    "tsconfig.json": json.dumps({"compilerOptions": {"outDir": "dist", "rootDir": "."}}),
    "service/main.ts": """\
import { start } from "./server";
import { hub } from "../shared/hub";
export function main() { start(); hub(); }
""",
    "service/server.ts": """\
import { hub } from "../shared/hub";
export function start() { return hub(); }
export function childEnv() { return { ...process.env }; }
""",
    "service/server.test.ts": """\
import { test } from "node:test";
import { start } from "./server";
function service() { return start(); }
function inner() { return start(); }
function wrap() { return inner(); }
test("one", () => { service(); });
test("two", () => { service(); });
test("outer", () => { wrap(); });
""",
    "service/tail.ts": "export function preflight() { return 1; }\n",
    "service/tail.test.ts": """\
import { test } from "node:test";
import { preflight } from "./tail";
function boot() { return preflight(); }
test("guards", () => { boot(); });
""",
    "service/other.test.ts": """\
import { test } from "node:test";
import { preflight } from "./tail";
test("unused", () => { return 1; });
""",
    "core/package.json": json.dumps({"name": "core"}),
    "core/a.ts": """\
import { b } from "./b";
import { hub } from "../shared/hub";
export function a() { return b() + hub(); }
""",
    "core/b.ts": """\
import { a } from "./a";
export function b() { return a(); }
""",
    "shared/package.json": json.dumps({"name": "shared"}),
    "shared/hub.ts": """\
export function hub() { return 1; }
export interface Hub { id: number }
export interface Hub2 { name: string }
""",
    "shared/back.ts": """\
import { b } from "../core/b";
export function back() { return b(); }
""",
    "src/ui.ts": """\
import { a } from "../core/a";
import { hub } from "../shared/hub";
export function ui() { return a() + hub(); }
""",
    "src/mobile/widget.ts": """\
import { a } from "../../core/a";
export function widget() { return a(); }
""",
    "worker/job.ts": "export function job() { return 1; }\n",
    "scripts/dev.js": "console.log(1);\n",
    "scripts/verify.js": "console.log(1);\n",
    "scripts/lint.js": "console.log(1);\n",
    "scripts/run-tests.js": "console.log(1);\n",
    "scripts/bare-dev.js": "console.log(1);\n",
    "scripts/lint-strict.js": "console.log(1);\n",
}


def run(capsys, *argv):
    capsys.readouterr()
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def run_json(capsys, *argv, code=0):
    got, out, err = run(capsys, *argv, "--json")
    assert got == code, err
    return json.loads(out)


@pytest.fixture
def repo(make_repo, monkeypatch, capsys):
    root = make_repo(FILES, name="review")
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    capsys.readouterr()
    return root


def db(root):
    return sqlite3.connect(root / ".cbi" / "model.db")


def test_help(capsys):
    for name in ("hotspots", "orphans", "cycles", "deps"):
        with pytest.raises(SystemExit) as exit_info:
            main([name, "--help"])
        assert exit_info.value.code == 0
        out = capsys.readouterr().out
        assert "--json" in out and "Exit codes:" in out and "Example: cbi " + name in out


def test_tooling_scripts_are_not_deployables_until_structure_says_so(repo, capsys):
    conn = db(repo)
    names = {r[0] for r in conn.execute("SELECT name FROM nodes WHERE kind = 'deployable'")}
    assert names == {"app", "start:job", "dev", "lint:strict"}
    via = dict(conn.execute(
        "SELECT src, json_extract(attrs, '$.via') FROM edges WHERE kind = 'part_of' AND dst = ?",
        (f"{WS}:deployable:app",)))
    assert via[f"{WS}:service/main.ts"] == "direct"
    assert via[f"{WS}:service/server.ts"] == "transitive"
    assert via[f"{WS}:shared/hub.ts"] == "transitive"
    assert conn.execute("SELECT count(*) FROM nodes WHERE kind = 'env' AND name = '*'").fetchone()[0] == 0
    (repo / ".cbi" / "structure.json").write_text(json.dumps({
        "deployables": [{"name": "dev:web", "display_kind": "node app", "entry_points": ["scripts/dev.js"]}],
        "packages": [],
    }))
    assert main(["scan"]) == 0
    names = {r[0] for r in db(repo).execute("SELECT name FROM nodes WHERE kind = 'deployable'")}
    assert "dev:web" in names


def test_hotspots_rank_files_folders_packages_and_concepts(repo, capsys):
    top = run_json(capsys, "hotspots", "--kind", "source file", "--by", "fan-in", "--limit", "1")
    assert top["nodes"][0]["path"] == "shared/hub.ts"
    assert top["nodes"][0]["fan_in"] == 4
    assert "test_files" not in top["nodes"][0]
    ranked = run_json(capsys, "hotspots", "--kind", "source file", "--by", "symbols")
    counts = [n["symbols"] for n in ranked["nodes"]]
    assert counts == sorted(counts, reverse=True)
    assert ranked["nodes"][0]["path"] == "shared/hub.ts" and ranked["nodes"][0]["symbols"] == 3
    code, out, _ = run(capsys, "hotspots", "--limit", "20")
    assert code == 0 and "files by fan-in:" in out and "shared/hub.ts" in out
    assert "server.test.ts" not in out and "folders by fan-in:" in out and "packages by fan-in:" in out
    assert "concepts by fan-in:" not in out
    code, out, _ = run(capsys, "hotspots", "--kind", "nope")
    assert code == 0 and "no nodes of kind 'nope'" in out

    conn = db(repo)
    with conn:
        conn.execute("INSERT INTO nodes (id, kind, display_kind, name, workspace_id) "
                     "VALUES (?, 'concept', 'concept', 'Hub', ?)", (f"{WS}:concept:hub", WS))
        conn.execute("INSERT INTO edges (src, dst, kind, source) VALUES (?, ?, 'owns', 'manifest')",
                     (f"{WS}:concept:hub", f"{WS}:shared/hub.ts"))
    conn.close()
    found = run_json(capsys, "hotspots", "--kind", "concept")
    assert found["nodes"][0]["name"] == "Hub" and found["nodes"][0]["fan_in"] == 4
    assert found["nodes"][0]["test_files"] == 0


def test_orphans_lists_unreferenced_test_only_and_unreachable(repo, capsys):
    body = run_json(capsys, "orphans")
    assert body["entries"] is True
    unreferenced = {r["path"] for r in body["unreferenced"]}
    assert unreferenced == {
        "service/tail.ts", "src/ui.ts", "src/mobile/widget.ts", "shared/back.ts",
        "scripts/dev.js", "scripts/verify.js", "scripts/lint.js", "scripts/run-tests.js",
    }
    assert {(r["path"], r["name"]) for r in body["test_only_symbols"]} == {("service/tail.ts", "preflight")}
    unreachable = {r["path"] for r in body["unreachable"]}
    assert "service/main.ts" not in unreachable and "service/server.ts" not in unreachable
    assert "shared/hub.ts" not in unreachable and "worker/job.ts" not in unreachable
    assert "scripts/bare-dev.js" not in unreachable and "scripts/lint-strict.js" not in unreachable
    assert {"service/tail.ts", "src/ui.ts", "src/mobile/widget.ts", "core/a.ts", "core/b.ts", "shared/back.ts",
            "scripts/dev.js"} <= unreachable
    untested = {(n["kind"], n["name"]) for n in body["untested"]}
    assert untested == {("package", "core"), ("package", "shared"), ("group", "scripts"), ("group", "src"),
                        ("group", "worker")}
    assert all(n["outside_tests"] == 0 for n in body["untested"])
    code, out, _ = run(capsys, "orphans")
    assert "service/tail.ts" in out and "service/tail.ts#preflight" in out
    assert "no test files of their own:" in out and "\n  core  0 test files\n" in out

    conn = db(repo)
    with conn:
        conn.execute("DELETE FROM nodes WHERE kind = 'deployable'")
    conn.close()
    body = run_json(capsys, "orphans")
    assert body["entries"] is False and body["unreachable"] == []
    assert "service/tail.ts" in {r["path"] for r in body["unreferenced"]}
    code, out, _ = run(capsys, "orphans")
    assert "no deployable entry points" in out


def test_cycles_between_files_folders_and_packages(repo, capsys):
    body = run_json(capsys, "cycles")
    assert body["files"][0]["detail"] == "core/a.ts → core/b.ts → core/a.ts"
    assert {m["path"] for m in body["files"][0]["members"]} == {"core/a.ts", "core/b.ts"}
    assert body["folders"][0]["detail"] == "core → shared → core"
    assert body["packages"][0]["detail"] == "core → shared → core"
    assert {m["name"] for m in body["packages"][0]["members"]} == {"core", "shared"}
    status = run_json(capsys, "status")
    assert status["diagnostics"]["cycle"]["count"] == 6
    code, out, _ = run(capsys, "show", "core/a.ts")
    assert code == 0 and "cycle: core/a.ts → core/b.ts → core/a.ts" in out


def test_deps_matrix_and_forbid(repo, capsys):
    body = run_json(capsys, "deps", "--level", "package")
    cells = {(e["from"], e["to"]): e["count"] for e in body["edges"]}
    assert cells[("core", "shared")] == 1 and cells[("shared", "core")] == 1 and cells[("core", "core")] == 2
    assert ("service", "shared") not in cells
    folders = run_json(capsys, "deps", "--level", "folder")
    cells = {(e["from"], e["to"]): e for e in folders["edges"]}
    assert cells[("service", "service")]["count"] >= 1
    assert cells[("service", "shared")]["count"] == 2
    assert ("service/server.test.ts", "service/server.ts") not in {
        (f["from"], f["to"]) for f in cells[("service", "service")]["files"]}
    assert {e["from"] + "→" + e["to"] for e in run_json(capsys, "deps", "--level", "folder", "--from", "src")["edges"]} == {
        "src→core", "src→shared", "src/mobile→core"}
    with_tests = run_json(capsys, "deps", "--level", "folder", "--include-tests")
    service = next(e for e in with_tests["edges"] if e["from"] == "service" and e["to"] == "service")
    assert ("service/server.test.ts", "service/server.ts") in {(f["from"], f["to"]) for f in service["files"]}

    code, out, _ = run(capsys, "deps", "--level", "folder", "--forbid", "src:core")
    assert code == 1 and "src/ui.ts → core/a.ts" in out and "src/mobile/widget.ts → core/a.ts" in out
    code, out, _ = run(capsys, "deps", "--level", "folder", "--forbid", "service:src")
    assert code == 0 and "no production imports from service to src" in out
    code, out, _ = run(capsys, "deps", "--level", "folder", "--forbid", "service:core")
    assert code == 0 and "no production imports from service to core" in out
    code, _, err = run(capsys, "deps", "--level", "folder", "--forbid", "missing:core")
    assert code == 1 and "no folder 'missing'" in err
    code, _, err = run(capsys, "deps", "--forbid", "src:core")
    assert code == 1 and "no package 'src'" in err
    code, _, err = run(capsys, "deps", "--forbid", "nocolon")
    assert code == 2 and "FROM:TO" in err

    conn = db(repo)
    with conn:
        conn.execute("DELETE FROM nodes WHERE kind = 'package'")
    conn.close()
    code, out, _ = run(capsys, "deps")
    assert code == 0 and "no packages in the model" in out
    code, out, _ = run(capsys, "deps", "--forbid", "a:b")
    assert code == 1 and "no packages in the model" in out


def test_show_order_floor_part_of_and_helper_links(repo, capsys):
    code, out, _ = run(capsys, "show", "service/main.ts")
    head = out.split("incoming", 1)[0]
    assert head.index("imports") < head.index("part_of") and "direct" in out
    code, out, _ = run(capsys, "show", "service/server.ts")
    assert "transitive" in out
    assert "passes whole environment" in out and "env_passthrough" not in out
    shown = run_json(capsys, "show", "service/server.ts")
    assert shown["diagnostics"] == [{"kind": "env_passthrough", "detail": "passes whole environment"}]
    assert all(e["name"] != "*" for e in shown["outgoing"])
    code, out, _ = run(capsys, "show", "service/tail.ts")
    assert "0.5" not in out
    code, out, _ = run(capsys, "show", "service/tail.ts", "--min-confidence", "0")
    assert "0.5" in out
    incoming = run_json(capsys, "show", "service/tail.ts")["incoming"]
    assert any(e["confidence"] == 0.5 and e["kind"] == "tests" for e in incoming)
    names = [t["name"] for t in run_json(capsys, "tests-for", "service/server.ts#start")["tests"]]
    assert "one" in names and "two" in names and "outer" not in names
    assert "guards" in [t["name"] for t in run_json(capsys, "tests-for", "preflight")["tests"]]


def test_orphans_count_path_and_html_references(make_repo, monkeypatch, capsys):
    root = make_repo({
        "package.json": json.dumps({"name": "app", "main": "dist/electron/main.js"}),
        "electron/tsconfig.json": json.dumps({"compilerOptions": {"outDir": "../dist", "rootDir": ".."}}),
        "electron/main.ts": 'import path from "node:path";\nexport function open() { return path.join(__dirname, "preload.js"); }\n',
        "electron/preload.ts": "export function preload() { return 1; }\n",
        "electron/env.ts": "export function env() { return 1; }\n",
        "electron/env.test.ts": """\
import path from "node:path";
import { test } from "node:test";
const file = path.join(__dirname, "env.js");
test("reads env", () => { file; });
""",
        "src/mobile/fixture.html": '<script type="module" src="./fixture-main.tsx"></script>\n',
        "src/mobile/fixture-main.tsx": "export function fixtureMain() { return 1; }\n",
        "src/mobile/vite.config.ts": "export default {};\n",
        "src/types/preload.d.ts": "export declare function bridge(): void;\n",
        "web/index.html": '<script src="./extra.ts"></script>\n',
        "web/extra.ts": "export function extra() { return 1; }\n",
        "vite.config.ts": "export default {};\n",
        "vitest.config.ts": "export default {};\n",
        "jest.config.ts": "export default {};\n",
        "eslint.config.mjs": "export default [];\n",
        "tailwind.config.ts": "export default {};\n",
        "postcss.config.cjs": "module.exports = {};\n",
        "electron-builder.config.js": "module.exports = {};\n",
    }, name="paths")
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    capsys.readouterr()
    body = run_json(capsys, "orphans")
    unreferenced = {r["path"] for r in body["unreferenced"]}
    unreachable = {r["path"] for r in body["unreachable"]}
    assert body["entries"] is True
    assert unreferenced == {"electron/env.ts"}
    assert unreachable == {"electron/env.ts"}
    conn = sqlite3.connect(root / ".cbi" / "model.db")
    refs = {(s.split(":", 2)[-1], d.split(":", 2)[-1]) for s, d in conn.execute(
        "SELECT src, dst FROM edges WHERE kind = 'references'")}
    assert ("electron/main.ts", "electron/preload.ts") in refs
    assert ("src/mobile/fixture.html", "src/mobile/fixture-main.tsx") in refs
    assert ("web/index.html", "web/extra.ts") in refs
    assert all(src != "electron/env.test.ts" for src, _dst in refs)

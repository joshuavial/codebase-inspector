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
    assert code == 0 and "cycle: file-import SCC: core/a.ts → core/b.ts → core/a.ts" in out


def test_cycle_status_separates_components_from_projected_memberships(make_repo, monkeypatch, capsys):
    root = make_repo({
        "left/a.ts": 'import { b } from "../right/b"; export const a = b;\n',
        "right/b.ts": "export const b = 1;\n",
        "right/c.ts": 'import { d } from "../left/d"; export const c = d;\n',
        "left/d.ts": "export const d = 2;\n",
        "core/a.ts": 'import { b } from "./b"; export const a = b;\n',
        "core/b.ts": 'import { a } from "./a"; export const b = a;\n',
    }, name="projected-cycles")
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    body = run_json(capsys, "cycles")
    assert len(body["files"]) == 1
    assert len(body["folders"]) == 1
    summary = run_json(capsys, "status")["diagnostics"]["cycle"]
    assert summary["count"] == 4 and summary["count_unit"] == "memberships"
    assert summary["levels"] == {
        "files": {"scc_count": 1, "membership_count": 2, "projection": False},
        "folders": {"scc_count": 1, "membership_count": 2, "projection": True},
        "packages": {"scc_count": 0, "membership_count": 0, "projection": True},
    }
    _, out, _ = run(capsys, "status")
    assert "cycle memberships: 4" in out
    assert "file-import SCCs: 1 (2 memberships)" in out
    assert "projected folder SCCs: 1 (2 memberships)" in out
    _, out, _ = run(capsys, "cycles")
    assert "file-import SCCs: 1 (2 memberships)" in out
    assert "projected folder SCCs: 1 (2 memberships)" in out
    _, out, _ = run(capsys, "show", "left/")
    assert "cycle: projected folder SCC:" in out


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
    code, out, _ = run(capsys, "deps", "--forbid", "a:b", "--json")
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
        "babel.config.js": "module.exports = {};\n",
        "electron.vite.config.ts": "export default {};\n",
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


def test_orphans_leave_framework_discovered_files_out(make_repo, monkeypatch, capsys):
    root = make_repo({
        "package.json": json.dumps({"name": "web", "main": "server.ts", "scripts": {"boot": "python boot.py"}}),
        "server.ts": "export function serve() { return 1; }\n",
        "boot.py": "from tools.worker import work\nwork()\n",
        "tools/__init__.py": "NAME = 'tools'\n",
        "tools/worker.py": "def work():\n    return 1\n",
        "runner/__init__.py": "",
        "runner/__main__.py": "print('run')\n",
        "app/layout.tsx": "import { Frame } from '../ui/frame';\nexport default function Shell() { return <Frame />; }\n",
        "ui/frame.tsx": "export function Frame() { return <main />; }\n",
        "app/products/[sku]/page.tsx": "export default function Product() { return <p />; }\n",
        "app/api/products/route.ts": "export function GET() { return new Response('ok'); }\n",
        "app/robots.ts": "export default function robots() { return {}; }\n",
        "app/sitemap.ts": "export default function sitemap() { return []; }\n",
        "app/guide/_meta.js": "export default { start: 'Start' };\n",
        "middleware.ts": "export function middleware() { return new Response('ok'); }\n",
        "next.config.mjs": "export default {};\n",
        "open-next.config.ts": "export default {};\n",
        "mdx-components.tsx": "export function useMDXComponents() { return {}; }\n",
        "playwright.config.ts": "export default {};\n",
        "codegen.local.ts": "export default {};\n",
        "docs/.vitepress/config.mts": "export default {};\n",
        ".agents/skills/painter/SKILL.md": "# Painter\nRun `scripts/paint.py`.\n",
        ".agents/skills/painter/scripts/paint.py": "def paint():\n    return 'blue'\n",
        ".pi/extensions/status.ts": "export function status() { return 'ok'; }\n",
        ".omp/extensions/status.ts": "export function status() { return 'ok'; }\n",
        "drizzle.config.ts": "export default { schema: './schema.ts' };\n",
        "manual.ts": "export function forgotten() { return 1; }\n",
        "handbook/docusaurus.config.ts": "export default { title: 'Handbook' };\n",
        "handbook/sidebars.ts": "export default { docs: [] };\n",
        "handbook/src/pages/index.tsx": "export default function Home() { return <h1>Hi</h1>; }\n",
    }, name="framework-roots")
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    capsys.readouterr()
    body = run_json(capsys, "orphans")
    expected = {"manual.ts"}
    assert {row["path"] for row in body["unreferenced"]} == expected
    assert {row["path"] for row in body["unreachable"]} == expected


def test_orphans_count_a_barrel_an_import_passes_through(make_repo, monkeypatch, capsys):
    root = make_repo({
        "package.json": json.dumps({"name": "web", "main": "main.ts"}),
        "main.ts": "import { Card } from './cards';\nexport function start() { return Card(); }\n",
        "cards/index.ts": "export { Card } from './Card';\n",
        "cards/Card.ts": "export function Card() { return 1; }\n",
        "spare/index.ts": "export { Spare } from './Spare';\n",
        "spare/Spare.ts": "export function Spare() { return 2; }\n",
    }, name="barrels")
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    capsys.readouterr()
    body = run_json(capsys, "orphans")
    assert {row["path"] for row in body["unreferenced"]} == {"spare/index.ts"}
    assert {row["path"] for row in body["unreachable"]} == {"spare/index.ts", "spare/Spare.ts"}


def test_review_surfaces_database_schema_and_api_route_changes(tmp_path):
    from cbi import diff, review, store

    base_db = tmp_path / "base.db"
    head_db = tmp_path / "head.db"

    base_nodes = [
        {"id": "local:repo:migrations/001_users.sql", "parent_id": None, "kind": "file",
         "display_kind": "source file", "name": "001_users.sql", "workspace_id": "local:repo",
         "path": "migrations/001_users.sql", "content_hash": None, "signature": "", "attrs": None},
        {"id": "local:repo:table:users", "parent_id": "local:repo", "kind": "table",
         "display_kind": "table", "name": "users", "workspace_id": "local:repo",
         "path": "migrations/001_users.sql", "content_hash": None, "signature": "", "attrs": None},
        {"id": "local:repo:table:users#id", "parent_id": "local:repo:table:users", "kind": "column",
         "display_kind": "column", "name": "id", "workspace_id": "local:repo",
         "path": "migrations/001_users.sql", "content_hash": None, "signature": "",
         "attrs": json.dumps({"type": "INTEGER", "primary_key": True})},
        {"id": "local:repo:table:users#name", "parent_id": "local:repo:table:users", "kind": "column",
         "display_kind": "column", "name": "name", "workspace_id": "local:repo",
         "path": "migrations/001_users.sql", "content_hash": None, "signature": "",
         "attrs": json.dumps({"type": "TEXT"})},
        {"id": "local:repo:table:legacy", "parent_id": "local:repo", "kind": "table",
         "display_kind": "table", "name": "legacy", "workspace_id": "local:repo",
         "path": "migrations/000_legacy.sql", "content_hash": None, "signature": "", "attrs": None},
        {"id": "local:repo:src/api.py", "parent_id": None, "kind": "file",
         "display_kind": "source file", "name": "api.py", "workspace_id": "local:repo",
         "path": "src/api.py", "content_hash": None, "signature": "", "attrs": None},
        {"id": "local:repo:src/api.py#get_users", "parent_id": "local:repo:src/api.py", "kind": "symbol",
         "display_kind": "function", "name": "get_users", "workspace_id": "local:repo",
         "path": "src/api.py", "content_hash": "v1", "signature": "def get_users():",
         "attrs": json.dumps({"http_routes": [{"method": "GET", "path": "/api/users"}]})},
        {"id": "local:repo:src/api.py#del_users", "parent_id": "local:repo:src/api.py", "kind": "symbol",
         "display_kind": "function", "name": "del_users", "workspace_id": "local:repo",
         "path": "src/api.py", "content_hash": "v1", "signature": "def del_users():",
         "attrs": json.dumps({"http_routes": [{"method": "DELETE", "path": "/api/users/:id"}]})},
    ]

    head_nodes = [
        {"id": "local:repo:migrations/001_users.sql", "parent_id": None, "kind": "file",
         "display_kind": "source file", "name": "001_users.sql", "workspace_id": "local:repo",
         "path": "migrations/001_users.sql", "content_hash": None, "signature": "", "attrs": None},
        {"id": "local:repo:migrations/002_orders.sql", "parent_id": None, "kind": "file",
         "display_kind": "source file", "name": "002_orders.sql", "workspace_id": "local:repo",
         "path": "migrations/002_orders.sql", "content_hash": None, "signature": "", "attrs": None},
        {"id": "local:repo:table:users", "parent_id": "local:repo", "kind": "table",
         "display_kind": "table", "name": "users", "workspace_id": "local:repo",
         "path": "migrations/001_users.sql", "content_hash": None, "signature": "", "attrs": None},
        {"id": "local:repo:table:users#id", "parent_id": "local:repo:table:users", "kind": "column",
         "display_kind": "column", "name": "id", "workspace_id": "local:repo",
         "path": "migrations/001_users.sql", "content_hash": None, "signature": "",
         "attrs": json.dumps({"type": "INTEGER", "primary_key": True})},
        {"id": "local:repo:table:users#name", "parent_id": "local:repo:table:users", "kind": "column",
         "display_kind": "column", "name": "name", "workspace_id": "local:repo",
         "path": "migrations/001_users.sql", "content_hash": None, "signature": "",
         "attrs": json.dumps({"type": "VARCHAR(100)", "nullable": False})},
        {"id": "local:repo:table:users#email", "parent_id": "local:repo:table:users", "kind": "column",
         "display_kind": "column", "name": "email", "workspace_id": "local:repo",
         "path": "migrations/001_users.sql", "content_hash": None, "signature": "",
         "attrs": json.dumps({"type": "VARCHAR(255)"})},
        {"id": "local:repo:table:orders", "parent_id": "local:repo", "kind": "table",
         "display_kind": "table", "name": "orders", "workspace_id": "local:repo",
         "path": "migrations/002_orders.sql", "content_hash": None, "signature": "", "attrs": None},
        {"id": "local:repo:src/api.py", "parent_id": None, "kind": "file",
         "display_kind": "source file", "name": "api.py", "workspace_id": "local:repo",
         "path": "src/api.py", "content_hash": None, "signature": "", "attrs": None},
        {"id": "local:repo:src/api.py#get_users", "parent_id": "local:repo:src/api.py", "kind": "symbol",
         "display_kind": "function", "name": "get_users", "workspace_id": "local:repo",
         "path": "src/api.py", "content_hash": "v2_mod", "signature": "def get_users():",
         "attrs": json.dumps({"http_routes": [{"method": "GET", "path": "/api/users"}]})},
        {"id": "local:repo:src/api.py#post_orders", "parent_id": "local:repo:src/api.py", "kind": "symbol",
         "display_kind": "function", "name": "post_orders", "workspace_id": "local:repo",
         "path": "src/api.py", "content_hash": "v1", "signature": "def post_orders():",
         "attrs": json.dumps({"http_routes": [{"method": "POST", "path": "/api/orders"}]})},
    ]

    for path, nodes in [(base_db, base_nodes), (head_db, head_nodes)]:
        conn = store.open_db(path)
        conn.executemany(
            "INSERT INTO nodes (id, parent_id, kind, display_kind, name, workspace_id, path, content_hash, signature, attrs) "
            "VALUES (:id, :parent_id, :kind, :display_kind, :name, :workspace_id, :path, :content_hash, :signature, :attrs)",
            nodes,
        )
        conn.commit()
        conn.close()

    base_conn, head_conn = diff.open_model(base_db), diff.open_model(head_db)
    try:
        result = diff.compare(base_conn, head_conn)
        diagram = review.build_diagram(result, base_conn, head_conn)
        mermaid = review.render_mermaid(diagram)
    finally:
        base_conn.close()
        head_conn.close()

    assert review.valid_mermaid(mermaid)

    rendered = review.render_review(
        tmp_path, "base" * 10, "head" * 10, {}, result, diagram, mermaid, None, None, None
    )

    # 1. Structural counts include table and endpoint changes
    assert "- 1 table-added" in rendered
    assert "- 1 table-removed" in rendered
    assert "- 1 table-changed" in rendered
    assert "- 1 endpoint-added" in rendered
    assert "- 1 endpoint-removed" in rendered
    assert "- 1 endpoint-changed" in rendered

    # 2. Database schema changes section
    assert "### Database schema changes" in rendered
    assert "- table-added  orders" in rendered
    assert "migrations/002_orders.sql  orders" in rendered
    assert "- table-removed  legacy" in rendered
    assert "migrations/000_legacy.sql  legacy" in rendered
    assert "- table-changed  users (+email, altered: name)" in rendered
    assert "migrations/001_users.sql  users" in rendered

    # 3. API route changes section
    assert "### API route changes" in rendered
    assert "- endpoint-added  POST /api/orders" in rendered
    assert "src/api.py  post_orders" in rendered
    assert "- endpoint-removed  DELETE /api/users/:id" in rendered
    assert "src/api.py  del_users" in rendered
    assert "- endpoint-changed  GET /api/users  handler get_users modified" in rendered
    assert "src/api.py  get_users" in rendered


def _git_cmd(cwd, *args):
    from cbi import files
    return files._git(
        cwd, "-c", "user.name=test", "-c", "user.email=test@example.com", "-c", "commit.gpgsign=false", *args,
    ).decode().strip()


def _commit_files(root, files_map, message="commit"):
    for rel, content in files_map.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    _git_cmd(root, "add", "-A")
    _git_cmd(root, "commit", "-q", "-m", message)


def test_resolve_target_merge_base_range(make_repo):
    from cbi import review
    root = make_repo({"a.txt": "v1\n"})
    initial_sha = _git_cmd(root, "rev-parse", "HEAD")

    # Create feature branch with a commit
    _git_cmd(root, "checkout", "-q", "-b", "feat")
    _commit_files(root, {"feat.txt": "feature\n"}, "feat commit")

    # Switch back to main and add another commit
    _git_cmd(root, "checkout", "-q", "main")
    _commit_files(root, {"main.txt": "main line\n"}, "main commit")

    # 1. main...feat resolves merge-base as base
    spec1 = review.resolve_target(root, "main...feat", None)
    assert spec1["base"] == initial_sha
    assert spec1["head"] == "feat"

    # 2. feat...main resolves merge-base as base
    spec2 = review.resolve_target(root, "feat...main", None)
    assert spec2["base"] == initial_sha
    assert spec2["head"] == "main"

    # 3. Two-dot notation preserves left as base
    spec_two_dot = review.resolve_target(root, "main..feat", None)
    assert spec_two_dot["base"] == "main"
    assert spec_two_dot["head"] == "feat"

    # 4. Error if both range and --base passed
    with pytest.raises(review.ReviewError, match="pass a range or --base, not both"):
        review.resolve_target(root, "main...feat", base="HEAD~1")

    # 5. Missing ends or extra dots raise range format error
    for invalid in ("...feat", "main...", "...", "....", "main....feat", "main...mid...feat"):
        with pytest.raises(review.ReviewError, match="a range needs both ends"):
            review.resolve_target(root, invalid, None)


def test_resolve_target_equals_default_base(make_repo):
    from cbi import review
    root = make_repo({"a.txt": "v1\n"})
    main_sha = _git_cmd(root, "rev-parse", "HEAD")

    # Target explicitly equal to default base resolves gracefully to itself
    spec = review.resolve_target(root, "main", None)
    assert spec["base"] == main_sha
    assert spec["head"] == "main"

    # Target HEAD on main resolves gracefully
    spec_head = review.resolve_target(root, "HEAD", None)
    assert spec_head["base"] == main_sha
    assert spec_head["head"] == "HEAD"


def test_review_json_structured_output(make_repo, monkeypatch, capsys, tmp_path):
    from cbi import review
    monkeypatch.setattr(
        "cbi.render.render_images",
        lambda *args, **kwargs: {"skipped": "skipped"},
    )
    root = make_repo({"app/b.ts": "export function b() { return 1; }\n"})
    monkeypatch.chdir(root)
    assert main(["init"]) == 0

    base = _git_cmd(root, "rev-parse", "HEAD")
    _git_cmd(root, "checkout", "-q", "-b", "feat")
    _commit_files(root, {"app/b.ts": "export function b() { return 2; }\nexport function c() { return 3; }\n"})
    head = _git_cmd(root, "rev-parse", "HEAD")

    # Test via CLI with --json
    code, out, err = run(capsys, "review", "main...feat", "--json", "--out-dir", str(tmp_path / "out_json"))
    assert code == 0, err
    data = json.loads(out)

    assert "review_file" in data
    assert data["review_file"].endswith("review.md")
    assert (tmp_path / "out_json" / "review.md").exists()
    assert "report" in data
    assert "base" in data and data["base"] == base
    assert "head" in data and data["head"] == head
    assert "spec" in data and data["spec"]["base"] == base and data["spec"]["head"] == "feat"
    assert "result" in data
    assert "overview" in data["result"]
    assert "groups" in data["result"]
    assert "diagram" in data
    assert "nodes" in data["diagram"]
    assert "edges" in data["diagram"]
    assert "mermaid" in data
    assert "flowchart LR" in data["mermaid"]

    # Test review_data Python API directly
    direct_data = review.review_data(root, "main...feat", out_dir=tmp_path / "out_direct")
    assert isinstance(direct_data, dict)
    assert direct_data["base"] == base
    assert direct_data["head"] == head
    assert direct_data["review_file"].endswith("review.md")

    # Test review(..., format="json")
    json_str = review.review(root, "main...feat", out_dir=tmp_path / "out_direct_str", format="json")
    loaded = json.loads(json_str)
    assert loaded["base"] == base
    assert loaded["head"] == head


def test_review_target_equals_default_base_cli(make_repo, monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(
        "cbi.render.render_images",
        lambda *args, **kwargs: {"skipped": "skipped"},
    )
    root = make_repo({"app/b.ts": "export function b() { return 1; }\n"})
    monkeypatch.chdir(root)
    assert main(["init"]) == 0

    code, out, err = run(capsys, "review", "main", "--json", "--out-dir", str(tmp_path / "out_same"))
    assert code == 0, err
    data = json.loads(out)
    assert data["base"] == data["head"]
    assert (tmp_path / "out_same" / "review.md").exists()


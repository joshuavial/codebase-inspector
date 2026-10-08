"""Deployables and packages from package.json, Vite and tsconfig, structure.json overrides and membership."""

import json
import sqlite3

import pytest

from cbi import manifests
from cbi.cli import main

FILES = {
    # main under an outDir set in server/tsconfig.json, with rootDir inherited through extends
    "package.json": json.dumps({
        "name": "acme",
        "main": "dist-server/server/main.js",
        "bin": {"acme-tool": "bin/missing.js"},
        "scripts": {"start:worker": "cross-env X=1 node --enable-source-maps worker/run.mjs",
                    "clean": "node -e \"require('fs')\""},
        "dependencies": {"@acme/lib": "*"},
        "devDependencies": {"vite": "7"},
    }),
    "tsconfig.base.json": '{ "compilerOptions": { "rootDir": "." } }',
    "server/tsconfig.json": '{ "extends": "../tsconfig.base.json", "compilerOptions": { "outDir": "../dist-server" } }',
    "server/main.ts": 'import { route } from "./routes";\nimport { greet } from "@acme/lib";\nroute(); greet();\n',
    "server/routes.ts": "export function route() {}\n",
    "server/unused.ts": "export const unused = 1;\n",
    "worker/run.mjs": "console.log(1);\n",
    # Vite with a non-default root
    "vite.config.ts": 'import { defineConfig } from "vite";\nexport default defineConfig({ root: "web", base: "./" });\n',
    "web/index.html": '<html><body><script type="module" src="/main.tsx"></script></body></html>\n',
    "web/main.tsx": 'import { helper } from "../common/helper";\nhelper();\n',
    # a manifest-less directory, added as a package by structure.json
    "common/helper.ts": "export function helper() {}\n",
    # a workspace package imported by name, its main under its own outDir
    "packages/lib/package.json": json.dumps({"name": "@acme/lib", "main": "dist/index.js"}),
    "packages/lib/tsconfig.json": '{ "compilerOptions": { "outDir": "dist", "rootDir": "src" } }',
    "packages/lib/src/index.ts": "export function greet() {}\n",
}


@pytest.fixture
def repo(make_repo, monkeypatch):
    root = make_repo(FILES, name="acme")
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    assert main(["scan"]) == 0
    return root


def _db(root):
    return sqlite3.connect(root / ".cbi" / "model.db")


def _deployables(conn):
    return {r[0]: (r[1], r[2], json.loads(r[3])["entry_points"]) for r in conn.execute(
        "SELECT id, name, display_kind, attrs FROM nodes WHERE kind = 'deployable'")}


def _members(conn, node_id):
    return {r[0].removeprefix("local:acme:") for r in conn.execute(
        "SELECT src FROM edges WHERE kind = 'part_of' AND dst = ?", (node_id,))}


def test_entry_points_map_to_source(repo):
    conn = _db(repo)
    assert _deployables(conn) == {
        "local:acme:deployable:acme": ("acme", "node app", ["server/main.ts"]),
        "local:acme:deployable:acme-tool": ("acme-tool", "cli", []),
        "local:acme:deployable:start:worker": ("start:worker", "node app", ["worker/run.mjs"]),
        "local:acme:deployable:web-web": ("web-web", "web app", ["web/main.tsx"]),
    }
    parents = {r[0] for r in conn.execute("SELECT parent_id FROM nodes WHERE kind IN ('deployable', 'package')")}
    assert parents == {"local:acme"}


def test_unresolved_entry_diagnostic(repo):
    rows = _db(repo).execute("SELECT node_id, detail FROM diagnostics WHERE kind = 'unresolved_entry'").fetchall()
    assert rows == [("local:acme:deployable:acme-tool", "package.json bin: bin/missing.js maps to no tracked source file")]


def test_part_of_follows_imports_and_package_names(repo):
    conn = _db(repo)
    assert _members(conn, "local:acme:deployable:acme") == {
        "server/main.ts", "server/routes.ts", "packages/lib/src/index.ts"}
    via = {r[0].removeprefix("local:acme:"): r[1] for r in conn.execute(
        "SELECT src, json_extract(attrs, '$.via') FROM edges WHERE kind = 'part_of' AND dst = ?",
        ("local:acme:deployable:acme",))}
    assert via == {"server/main.ts": "direct", "server/routes.ts": "transitive", "packages/lib/src/index.ts": "transitive"}
    package_via = {r[1] for r in conn.execute(
        "SELECT src, json_extract(attrs, '$.via') FROM edges WHERE kind = 'part_of' AND dst = ?",
        ("local:acme:package:@acme/lib",))}
    assert package_via == {"direct"}
    assert conn.execute("SELECT count(*) FROM edges WHERE kind = 'depends_on' AND attrs IS NOT NULL").fetchone()[0] == 0
    assert _members(conn, "local:acme:deployable:web-web") == {"web/main.tsx", "common/helper.ts"}
    assert _members(conn, "local:acme:package:@acme/lib") == {
        "packages/lib/package.json", "packages/lib/tsconfig.json", "packages/lib/src/index.ts"}
    depends = conn.execute("SELECT src, dst FROM edges WHERE kind = 'depends_on'").fetchall()
    assert depends == [("local:acme:deployable:acme", "local:acme:package:@acme/lib")]


def test_reachability_over_inserted_import_edges(repo):
    conn = _db(repo)
    with conn:
        conn.execute("INSERT INTO edges (src, dst, kind, source) VALUES "
                     "('local:acme:server/routes.ts', 'local:acme:server/unused.ts', 'imports', 'treesitter')")
        manifests.apply(conn, repo, None)
    assert "server/unused.ts" in _members(conn, "local:acme:deployable:acme")
    assert "server/unused.ts" not in _members(conn, "local:acme:deployable:web-web")


def test_verify_file_scripts_are_not_deployables():
    assert manifests._verify_target("test/smoke.mjs")
    assert manifests._verify_target("app/test/smoke.mjs")
    assert manifests._verify_target("e2e/run.mjs")
    assert manifests._verify_target("src/client.test.ts")
    assert manifests._verify_target("src/adds.spec.ts")
    assert manifests._verify_target("smoke.mjs")
    assert manifests._verify_target("web/flow.e2e.mjs")
    assert not manifests._verify_target("scripts/copy-pdf-worker.mjs")
    assert not manifests._verify_target("dist/server.js")
    assert manifests._tooling_script("lint", ())
    assert manifests._tooling_script("test", ())
    assert manifests._tooling_script("dev:web", ())
    assert manifests._tooling_script("verify:pkg", ())
    assert manifests._tooling_script("smoke", ("test/smoke.mjs",))
    assert manifests._tooling_script("e2e", ("e2e/run.mjs",))
    # A script named smoke that starts a server is still a deployable.
    assert not manifests._tooling_script("smoke", ("scripts/server.mjs",))
    assert not manifests._tooling_script("dev", ())
    assert not manifests._tooling_script("start", ("dist/server.js", "test/smoke.mjs"))


def test_shared_package_dist_bin_open_next_and_verify_scripts(make_repo, monkeypatch):
    """Two apps share a package, a dist bin, an OpenNext worker, and verify scripts."""
    files = {
        "package.json": json.dumps({"name": "sample-apps", "private": True}),
        "portal-app/package.json": json.dumps({
            "name": "portal-app",
            "dependencies": {"shared": "workspace:*", "next": "14"},
            "scripts": {"smoke": "npm run build && node test/smoke.mjs", "dev": "next dev"},
        }),
        "portal-app/test/smoke.mjs": "console.log(1)\n",
        "portal-app/app/layout.tsx": "export default function Layout() { return null }\n",
        "portal-app/app/page.tsx": "export default function Page() { return null }\n",
        "portal-app/wrangler.toml": 'name = "portal"\nmain = ".open-next/worker.js"\n',
        "portal-app/src/boot.ts": 'import { greet } from "shared";\nexport class Portal { hi() { return greet(); } }\n',
        "admin-app/package.json": json.dumps({
            "name": "admin-app",
            "dependencies": {"shared": "workspace:*"},
        }),
        "admin-app/src/boot.ts": 'import { greet } from "shared";\nexport function teach() { return greet(); }\n',
        "shared/package.json": json.dumps({"name": "shared", "main": "dist/index.js"}),
        "shared/tsconfig.json": json.dumps({"compilerOptions": {"outDir": "./dist", "rootDir": "."}}),
        "shared/index.ts": 'export function greet() { return "hi"; }\n',
        "cli/package.json": json.dumps({
            "name": "@sample/cli",
            "bin": {"sample": "./dist/index.js"},
            "scripts": {
                "test": "vitest",
                "e2e": "node e2e/run.mjs",
                "start": "node dist/server.js && node test/smoke.mjs",
            },
        }),
        "cli/tsconfig.json": json.dumps({"compilerOptions": {"outDir": "./dist", "rootDir": "./src"}}),
        "cli/src/index.ts": "export function main() {}\n",
        "cli/src/server.ts": "export function serve() {}\n",
        "cli/e2e/run.mjs": "console.log(1)\n",
        "cli/test/smoke.mjs": "console.log(1)\n",
        "app/package.json": json.dumps({
            "name": "app",
            "scripts": {"smoke": "npm run build && node test/smoke.mjs"},
        }),
        "app/test/smoke.mjs": "console.log(1)\n",
        "edge/wrangler.toml": 'name = "edge"\nmain = "dist/worker.js"\n',
        "edge/tsconfig.json": json.dumps({"compilerOptions": {"outDir": "dist", "rootDir": "src"}}),
        "edge/src/worker.ts": "export default {};\n",
        "bare/wrangler.toml": 'name = "bare"\nmain = ".open-next/worker.js"\n',
    }
    root = make_repo(files, name="sample-apps")
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    assert main(["scan"]) == 0
    conn = sqlite3.connect(root / ".cbi" / "model.db")
    found = {r[0]: (r[1], json.loads(r[2])["entry_points"]) for r in conn.execute(
        "SELECT name, display_kind, attrs FROM nodes WHERE kind = 'deployable' ORDER BY name")}
    assert found == {
        "bare": ("worker", []),
        "sample": ("cli", ["cli/src/index.ts"]),
        "edge": ("worker", ["edge/src/worker.ts"]),
        "start": ("node app", ["cli/src/server.ts"]),
        "portal": ("worker", ["portal-app/app/layout.tsx"]),
    }
    packages = {r[0] for r in conn.execute("SELECT name FROM nodes WHERE kind = 'package'")}
    assert packages == {"portal-app", "admin-app", "shared", "@sample/cli", "app"}
    assert "shared" not in found
    depends = {(s, d) for s, d in conn.execute("SELECT src, dst FROM edges WHERE kind = 'depends_on'")}
    assert ("local:sample-apps:package:portal-app", "local:sample-apps:package:shared") in depends
    assert ("local:sample-apps:package:admin-app", "local:sample-apps:package:shared") in depends
    unresolved = [r[0] for r in conn.execute(
        "SELECT node_id FROM diagnostics WHERE kind = 'unresolved_entry' ORDER BY node_id")]
    assert unresolved == ["local:sample-apps:deployable:bare"]


def test_structure_json_adds_package_renames_and_removes(repo, capsys):
    (repo / ".cbi" / "structure.json").write_text(json.dumps({
        "deployables": [
            {"id": "local:acme:deployable:web-web", "name": "storefront", "display_kind": "web app"},
            {"id": "local:acme:deployable:start:worker", "remove": True},
            {"name": "tool", "display_kind": "cli", "entry_points": ["server/routes.ts"]},
        ],
        "packages": [{"name": "common", "directory": "common"}],
    }))
    capsys.readouterr()
    assert main(["scan"]) == 0
    assert "no changes" not in capsys.readouterr().out  # a structure change defeats the shortcut
    conn = _db(repo)
    found = _deployables(conn)
    assert found["local:acme:deployable:web-web"] == ("storefront", "web app", ["web/main.tsx"])
    assert found["local:acme:deployable:tool"] == ("tool", "cli", ["server/routes.ts"])
    assert "local:acme:deployable:start:worker" not in found
    assert _members(conn, "local:acme:package:common") == {"common/helper.ts"}
    assert ("local:acme:deployable:web-web", "local:acme:package:common") in conn.execute(
        "SELECT src, dst FROM edges WHERE kind = 'depends_on'").fetchall()
    assert main(["show", "local:acme:deployable:web-web"]) == 0
    assert "storefront (web app)" in capsys.readouterr().out

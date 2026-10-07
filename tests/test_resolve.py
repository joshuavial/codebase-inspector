"""Imports, calls and test links over a small TS, TSX and JS repo, checked against a golden dump."""

import json
import os
import sqlite3
from pathlib import Path

import pytest

from cbi.cli import main
from cbi.resolve import _jsonc

GOLDEN = Path(__file__).parent / "golden" / "resolve.txt"

FILES = {
    "tsconfig.json": """\
{
  // Aliases: the "/*" inside strings must survive comment stripping.
  "compilerOptions": {
    "baseUrl": ".",
    "paths": { "@lib/*": ["src/lib/*"], },
  },
}
""",
    "src/lib/shapes.ts": """\
export class Circle {
  constructor(readonly radius: number) {}
  area(): number { return Math.PI * this.scale(this.radius) ** 2; }
  scale(n: number) { return n; }
  static unit() { return new Circle(1); }
}
""",
    "src/lib/math.ts": """\
export const double = (n: number) => n * 2;
export function square(n: number) { return n * n; }
""",
    "src/lib/index.ts": """\
export { Circle } from "./shapes";
export * from "./math";
""",
    "src/ui/Badge.tsx": """\
import { double } from "@lib/math";

export function Badge({ n }: { n: number }) {
  return <span>{double(n)}</span>;
}

export const Card = () => (
  <div><Badge n={1} /></div>
);
""",
    "src/ui/theme.css": ".badge { color: red; }\n",
    "src/app.ts": """\
import { Circle, square } from "./lib";
import * as math from "./lib/math";

export function main() {
  const c = new Circle(1);
  Circle.unit();
  return square(2) + math.double(c.radius);
}

export function run(square: (n: number) => number) {
  return square(3);
}

export function other() {
  const double = (x: number) => x;
  return double(1);
}
""",
    "src/legacy.js": """\
const { square } = require("./lib/math");

function pick(a) { return a; }
function pick(a, b) { return b; }

function use() { return pick(square(1)); }
""",
    "src/lib/shapes.test.ts": """\
import test from "node:test";
import { Circle } from "@lib/shapes";

test("area", () => {
  new Circle(2).area();
});
""",
    "src/ui/styles.test.ts": """\
import { readFileSync } from "node:fs";
import test from "node:test";

const css = readFileSync(new URL("./theme.css", import.meta.url), "utf8");

test("badge is red", () => {
  css.includes("red");
});
""",
    "src/__tests__/app.test.ts": """\
import test from "node:test";
import { main } from "../app";

test("main", () => main());
""",
    "src/orphan.test.ts": """\
import assert from "node:assert/strict";
import test from "node:test";

test("nothing", () => assert.ok(true));
""",
}


def dump(root):
    conn = sqlite3.connect(root / ".cbi" / "model.db")
    lines = [json.dumps(["node", *r]) for r in conn.execute(
        "SELECT id, display_kind FROM nodes WHERE kind IN ('symbol', 'test') ORDER BY id")]
    lines += [json.dumps(["edge", *r]) for r in conn.execute(
        "SELECT kind, source, src, dst, confidence, weight FROM edges ORDER BY kind, source, src, dst")]
    lines += [json.dumps(["diagnostic", *r]) for r in conn.execute(
        "SELECT kind, node_id, detail FROM diagnostics ORDER BY kind, node_id")]
    return "".join(line + "\n" for line in lines)


@pytest.fixture
def repo(make_repo, monkeypatch, capsys):
    root = make_repo(FILES)
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    assert main(["scan"]) == 0
    capsys.readouterr()
    return root


def test_golden_resolution(repo):
    text = dump(repo)
    if os.environ.get("CBI_UPDATE_GOLDEN"):
        GOLDEN.write_text(text)
    assert text == GOLDEN.read_text()


def edges(root, kind):
    conn = sqlite3.connect(root / ".cbi" / "model.db")
    return {(s.split(":", 2)[2], d.split(":", 2)[2]) for s, d in conn.execute(
        "SELECT src, dst FROM edges WHERE kind = ?", (kind,))}


def test_resolution_rules(repo):
    imports = edges(repo, "imports")
    # Through index.ts to the defining files, through the tsconfig alias, through require().
    assert {("src/app.ts", "src/lib/shapes.ts"), ("src/app.ts", "src/lib/math.ts")} <= imports
    assert ("src/app.ts", "src/lib/index.ts") not in imports
    assert ("src/ui/Badge.tsx", "src/lib/math.ts") in imports
    assert ("src/legacy.js", "src/lib/math.ts") in imports
    assert ("src/lib/index.ts", "src/lib/shapes.ts") in imports

    calls = edges(repo, "calls")
    assert ("src/app.ts#main", "src/lib/shapes.ts#Circle") in calls  # new, via re-export
    assert ("src/app.ts#main", "src/lib/shapes.ts#Circle.unit") in calls  # static member
    assert ("src/app.ts#main", "src/lib/math.ts#square") in calls  # export * through index.ts
    assert ("src/app.ts#main", "src/lib/math.ts#double") in calls  # namespace import
    assert ("src/ui/Badge.tsx#Card", "src/ui/Badge.tsx#Badge") in calls  # JSX
    assert ("src/legacy.js#use", "src/lib/math.ts#square") in calls
    # A parameter and a local variable shadow the imported names.
    assert not {c for c in calls if c[0] in ("src/app.ts#run", "src/app.ts#other")}

    conn = sqlite3.connect(repo / ".cbi" / "model.db")
    assert conn.execute(
        "SELECT confidence FROM edges WHERE kind = 'calls' AND src LIKE '%#Circle.area' AND dst LIKE '%#Circle.scale'"
    ).fetchone() == (0.6,)

    tests = edges(repo, "tests")
    assert ("src/lib/shapes.test.ts#area", "src/lib/shapes.ts#Circle") in tests
    assert ("src/ui/styles.test.ts", "src/ui/theme.css") in tests
    assert ("src/__tests__/app.test.ts", "src/app.ts") in tests  # naming, one folder up


def test_diagnostics(repo):
    conn = sqlite3.connect(repo / ".cbi" / "model.db")
    rows = conn.execute("SELECT kind, node_id, detail FROM diagnostics ORDER BY kind").fetchall()
    assert rows == [
        ("ambiguous_call", "local:repo:src/legacy.js", "1 calls with more than one candidate"),
        ("unmatched_test", "local:repo:src/orphan.test.ts",
         "no call, import, file read or file name reaches tracked code; imports only node:assert/strict, node:test"),
    ]


def test_unchanged_importer_is_reresolved(repo, capsys):
    (repo / "src/lib/math.ts").write_text("export const double = (n: number) => n * 2;\n")
    main(["scan"])
    calls = edges(repo, "calls")
    assert ("src/app.ts#main", "src/lib/math.ts#square") not in calls
    assert ("src/app.ts#main", "src/lib/math.ts#double") in calls


def run_json(capsys, *argv):
    capsys.readouterr()
    assert main([*argv, "--json"]) == 0
    return json.loads(capsys.readouterr().out)


def test_show_relationships_and_tests_for(repo, capsys):
    shown = run_json(capsys, "show", "src/lib/shapes.ts#Circle")
    incoming = {(e["kind"], e["source"], e["id"].split(":", 2)[2]) for e in shown["incoming"]}
    assert ("calls", "treesitter", "src/app.ts#main") in incoming
    assert ("tests", "treesitter", "src/lib/shapes.test.ts#area") in incoming
    assert [e["id"] for e in run_json(capsys, "show", "src/app.ts")["outgoing"] if e["kind"] == "imports"] == [
        "local:repo:src/lib/math.ts", "local:repo:src/lib/shapes.ts"]

    found = run_json(capsys, "tests-for", "src/lib/shapes.ts")
    assert [(t["name"], t["sources"]) for t in found] == [
        ("area", ["treesitter"]), ("shapes.test.ts", ["naming", "treesitter"])]
    assert run_json(capsys, "tests-for", "src/lib/math.ts") == []
    assert [t["name"] for t in run_json(capsys, "tests-for", "src/ui/")] == ["styles.test.ts"]

    capsys.readouterr()
    assert main(["show", "Circle"]) == 0
    out = capsys.readouterr().out
    assert "incoming (" in out and "tests    test case    area  src/lib/shapes.test.ts:4" in out
    assert main(["tests-for", "Circle"]) == 0
    assert "test case    area  src/lib/shapes.test.ts:4  (treesitter 1)" in capsys.readouterr().out


def test_jsonc():
    assert _jsonc('{"a/*": ["b/*"], // c\n "d": [1, 2,], /* e */ "f": "g//h",}') == {
        "a/*": ["b/*"], "d": [1, 2], "f": "g//h"}

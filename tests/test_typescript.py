import json
import os
import sqlite3
from pathlib import Path

from cbi.cli import main

GOLDEN = Path(__file__).parent / "golden" / "typescript.txt"

SHAPES = '''\
import { thing } from "./thing";

/** Something that can be drawn. */
export interface Shape {
  area(): number;
}

/**
 * A circle.
 * Radius is in pixels.
 */
export class Circle implements Shape {
  constructor(readonly radius: number) {}

  /** Area in square pixels. */
  area(): number {
    return Math.PI * this.radius ** 2;
  }

  private grow = (by: number) => {
    return new Circle(this.radius + by);
  };

  static unit() { return new Circle(1); }
}

export const double = (n: number): number => n * 2;

const label = function (s: string) { return s.trim(); };

const notAFunction = 1;

function pick(a: string): string { return a; }
function pick(a: number): number { return a; }
function same() { return 1; }
function same() { return 2; }
'''

BADGE = '''\
type Props = { text: string };

/** Shows a short label. */
export function Badge({ text }: Props) {
  return <span className="badge">{text}</span>;
}

export const Card = ({ text }: Props) => (
  <div>
    <Badge text={text} />
  </div>
);

export function formatText(text: string) { return text.toUpperCase(); }
'''

SHAPES_TEST = '''\
import assert from "node:assert/strict";
import { describe, it, test } from "node:test";
import { Circle, double } from "./shapes";

function setup() { return new Circle(2); }

test("circle area", () => {
  assert.equal(Math.round(setup().area()), 13);
});

describe("double", () => {
  it("doubles", () => assert.equal(double(2), 4));
  it.skip("ignores strings", () => {});
});

test("subtests", async (t) => {
  await t.test("inner", () => {});
  assert.ok(/x/.test("x"));
});

test.todo(`later`);
'''


def symbol_dump(root):
    conn = sqlite3.connect(root / ".cbi" / "model.db")
    rows = conn.execute(
        "SELECT id, parent_id, kind, display_kind, name, start_line, end_line, signature, doc "
        "FROM nodes WHERE kind IN ('symbol', 'test') ORDER BY id"
    ).fetchall()
    return "".join(json.dumps(row) + "\n" for row in rows)


def test_golden_symbols(make_repo, monkeypatch, capsys):
    root = make_repo({"src/shapes.ts": SHAPES, "src/badge.tsx": BADGE, "src/shapes.test.ts": SHAPES_TEST})
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    assert main(["scan"]) == 0
    text = symbol_dump(root)
    if os.environ.get("CBI_UPDATE_GOLDEN"):
        GOLDEN.write_text(text)
    assert text == GOLDEN.read_text()


def test_symbols_follow_edits_and_deletions(make_repo, monkeypatch, capsys):
    root = make_repo({"src/shapes.ts": SHAPES})
    monkeypatch.chdir(root)
    main(["init"])
    main(["scan"])
    (root / "src" / "shapes.ts").write_text("export function only() {}\n")
    main(["scan"])
    conn = sqlite3.connect(root / ".cbi" / "model.db")
    names = [r[0] for r in conn.execute("SELECT name FROM nodes WHERE kind = 'symbol'")]
    assert names == ["only"]
    (root / "src" / "shapes.ts").unlink()
    main(["scan"])
    assert conn.execute("SELECT count(*) FROM nodes WHERE kind = 'symbol'").fetchone() == (0,)


EACH = '''\
import { describe, it, test } from "vitest";

describe.each([["suite"]])("suite %s", () => {
  it.each([["a"], ["b"]])("handles %s", () => {});
});

test.each([[1]])("adds %s", () => {});

test("plain", () => {
  /x/.test("x");
});
'''

JEST = '''\
test.each([[1, 2]])("sums %s", () => {});
'''


def test_each_calls_are_vitest_and_jest_cases(make_repo, monkeypatch):
    root = make_repo({
        "src/client.test.ts": EACH,
        "src/adds.spec.ts": JEST,
    })
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    assert main(["scan"]) == 0
    conn = sqlite3.connect(root / ".cbi" / "model.db")
    rows = conn.execute(
        "SELECT path, display_kind, name FROM nodes WHERE kind = 'test' ORDER BY path, name"
    ).fetchall()
    assert rows == [
        ("src/adds.spec.ts", "test case", "sums %s"),
        ("src/client.test.ts", "test case", "adds %s"),
        ("src/client.test.ts", "test case", "handles %s"),
        ("src/client.test.ts", "test case", "plain"),
        ("src/client.test.ts", "test suite", "suite %s"),
    ]
    assert conn.execute(
        "SELECT display_kind FROM nodes WHERE path = 'src/adds.spec.ts' AND kind = 'file'"
    ).fetchone() == ("test file",)


def test_parse_error_is_a_diagnostic(make_repo, monkeypatch, capsys):
    root = make_repo({"src/broken.ts": "export class Half {}\nconst = ;\n", "src/ok.ts": "export function ok() {}\n"})
    monkeypatch.chdir(root)
    main(["init"])
    assert main(["scan"]) == 0
    conn = sqlite3.connect(root / ".cbi" / "model.db")
    rows = conn.execute("SELECT node_id, kind FROM diagnostics").fetchall()
    assert rows == [("local:repo:src/broken.ts", "parse_error")]
    assert conn.execute("SELECT name FROM nodes WHERE kind = 'symbol' ORDER BY name").fetchall() == [("Half",), ("ok",)]

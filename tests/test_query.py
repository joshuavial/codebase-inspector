"""search, show, tests-for and status in text and --json, on a scanned repo with extra rows inserted."""

import json
import re
import sqlite3

import pytest

from cbi.cli import main

FILES = {
    "src/shapes/circle.ts": """\
/** A round shape. */
export class Circle {
  constructor(readonly radius: number) {}
  area(): number { return Math.PI * this.radius ** 2; }
}

export function makeCircle(r: number) { return new Circle(r); }
""",
    "src/shapes/circle.test.ts": """\
import { test } from "node:test";
import { makeCircle } from "./circle";

test("measures the area", () => {
  makeCircle(2).area();
});
""",
    "src/other/area.ts": "export function area() { return 0; }\n",
}

WS = "local:repo"
CIRCLE = f"{WS}:src/shapes/circle.ts"
TEST_CASE = f"{WS}:src/shapes/circle.test.ts#measures the area"


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
    root = make_repo(FILES)
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    conn = sqlite3.connect(root / ".cbi" / "model.db")
    with conn:
        # A deployable from another deliverable, with kinds this module has never heard of.
        conn.execute("INSERT INTO nodes (id, parent_id, kind, display_kind, name, workspace_id, path) "
                     "VALUES (?, ?, 'deployable', 'web app', 'shapes-web', ?, '')", (f"{WS}:deployable:web", WS, WS))
        conn.execute("INSERT INTO edges (src, dst, kind, source, confidence) VALUES (?, ?, 'part_of', 'manifest', 0.7)",
                     (CIRCLE, f"{WS}:deployable:web"))
        # Receiver calls (makeCircle(2).area()) are not bound statically; per-test coverage would link them.
        conn.execute("INSERT INTO edges (src, dst, kind, source) VALUES (?, ?, 'tests', 'coverage')",
                     (TEST_CASE, f"{CIRCLE}#Circle.area"))
        conn.execute("INSERT INTO diagnostics (node_id, kind, detail) VALUES (?, 'unresolved_entry', 'dist/main.js')",
                     (f"{WS}:deployable:web",))
        conn.executemany("INSERT INTO coverage_lines (file_id, line, hits, artifact) VALUES (?, ?, ?, ?)", [
            (CIRCLE, 2, 1, "a.lcov"), (CIRCLE, 4, 0, "a.lcov"), (CIRCLE, 4, 3, "b.lcov"), (CIRCLE, 7, 0, "a.lcov")])
        conn.execute("INSERT INTO results (test_node_id, status, duration_ms, artifact) VALUES (?, 'passed', 4.5, 'r.xml')",
                     (TEST_CASE,))
    conn.close()
    return root


@pytest.mark.parametrize("text, kind, want", [
    ("Circle", "class", f"{CIRCLE}#Circle"),
    ("makeCirc", "function", f"{CIRCLE}#makeCircle"),
    ("measures area", "test case", TEST_CASE),
    ("shapes", "folder", f"{WS}:src/shapes/"),
])
def test_search_finds_each_kind(repo, capsys, text, kind, want):
    hits = run_json(capsys, "search", text)
    assert want in [h["id"] for h in hits]
    filtered = run_json(capsys, "search", text, "--kind", kind)
    assert filtered and {h["display_kind"] for h in filtered} == {kind} and want in [h["id"] for h in filtered]
    code, out, _ = run(capsys, "search", text, "--kind", kind)
    assert code == 0 and want in out and out.startswith(kind)


def test_search_takes_several_words_unquoted(repo, capsys):
    assert run_json(capsys, "search", "measures", "area")[0]["id"] == TEST_CASE


def test_search_kind_filter_accepts_internal_kind_and_reports_no_hits(repo, capsys):
    assert {h["kind"] for h in run_json(capsys, "search", "circle", "--kind", "symbol")} == {"symbol"}
    code, out, _ = run(capsys, "search", "circle", "--kind", "interface")
    assert code == 0 and "no matches for 'circle' with kind 'interface'" in out


def test_show_text_groups_relationships_and_lists_tests_and_diagnostics(repo, capsys):
    code, out, _ = run(capsys, "show", "src/shapes/circle.ts")
    assert code == 0 and out.startswith("circle.ts (source file)")
    assert re.search(r"outgoing \(1\): part_of 1\n    part_of  web app      shapes-web  \(manifest 0.7\)", out)
    assert re.search(r"incoming \(\d+\): imports 1, tests \d+", out)
    assert "    tests    " not in out  # incoming tests edges print once, under tests
    assert "tests (2):" in out and "measures the area  src/shapes/circle.test.ts:4  (coverage, treesitter 1)  last: passed" in out
    code, out, _ = run(capsys, "show", f"{WS}:deployable:web")
    assert code == 0 and "shapes-web (web app)" in out and "diagnostics (1):\n    unresolved_entry: dist/main.js" in out
    assert "deployable" not in out.replace(f"{WS}:deployable:web", "")  # internal kind never printed


def test_show_json(repo, capsys):
    shown = run_json(capsys, "show", "Circle.area")
    assert shown["id"] == f"{CIRCLE}#Circle.area" and shown["kind"] == "symbol" and shown["display_kind"] == "method"
    assert [t["id"] for t in shown["tests"]] == [TEST_CASE]
    whole = run_json(capsys, "show", "src/shapes/circle.ts")
    assert [e["kind"] for e in whole["incoming"]] == sorted(e["kind"] for e in whole["incoming"])
    assert whole["outgoing"] == [{"kind": "part_of", "source": "manifest", "confidence": 0.7, "weight": 1,
                                  "attrs": None, "id": f"{WS}:deployable:web", "display_kind": "web app",
                                  "name": "shapes-web", "path": "", "start_line": None}]
    assert run_json(capsys, "show", "shapes-web")["diagnostics"] == [{"kind": "unresolved_entry", "detail": "dist/main.js"}]


def test_ambiguous_name_lists_candidates(repo, capsys):
    code, out, err = run(capsys, "show", "area")
    assert code == 1 and out == "" and "'area' matches 2 nodes; pick one by ID" in err
    assert f"{CIRCLE}#Circle.area" in err and f"{WS}:src/other/area.ts#area" in err and "method" in err
    found = run_json(capsys, "tests-for", "area", code=1)
    assert [c["id"] for c in found["candidates"]] == [f"{WS}:src/other/area.ts#area", f"{CIRCLE}#Circle.area"]
    assert run_json(capsys, "show", "no-such-thing", code=1) == {"error": "no node matches 'no-such-thing'", "candidates": []}


def test_tests_for_with_results_and_coverage(repo, capsys):
    found = run_json(capsys, "tests-for", "src/shapes/")
    assert found["node"] == f"{WS}:src/shapes/"
    case = next(t for t in found["tests"] if t["id"] == TEST_CASE)
    assert case["results"] == [{"status": "passed", "duration_ms": 4.5, "artifact": "r.xml"}]
    # line 4 is hit by b.lcov though a.lcov missed it; line 7 is never hit
    assert found["coverage"] == [{"file_id": CIRCLE, "path": "src/shapes/circle.ts", "covered": 2, "lines": 3,
                                  "percent": 66.7, "artifacts": ["a.lcov", "b.lcov"]}]
    method = run_json(capsys, "tests-for", "Circle.area")
    assert [t["id"] for t in method["tests"]] == [TEST_CASE] and method["coverage"][0]["lines"] == 1
    assert run_json(capsys, "tests-for", "src/other/area.ts") == {"node": f"{WS}:src/other/area.ts", "tests": [], "coverage": []}

    code, out, _ = run(capsys, "tests-for", "src/shapes/")
    assert code == 0 and "test case    measures the area  src/shapes/circle.test.ts:4  (coverage, treesitter 1)  last: passed" in out
    assert "coverage     src/shapes/circle.ts  2/3 lines (66.7%)" in out
    assert run(capsys, "tests-for", "src/other/area.ts")[1] == f"no tests linked to {WS}:src/other/area.ts\n"


def test_tests_for_unknown_kind_does_not_match_id_prefix(repo, capsys):
    conn = sqlite3.connect(repo / ".cbi" / "model.db")
    with conn:
        conn.execute("INSERT INTO edges (src, dst, kind, source) VALUES (?, ?, 'tests', 'agent')",
                     (TEST_CASE, f"{WS}:deployable:web-admin"))
    conn.close()
    assert run_json(capsys, "tests-for", f"{WS}:deployable:web")["tests"] == []


def test_status(repo, capsys):
    got = run_json(capsys, "status")
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d{4}", got["scanned_at"])
    assert got["nodes"]["class"] == 1 and got["nodes"]["web app"] == 1 and got["nodes"]["test case"] == 1
    assert got["open_tasks"] == {"confirm-structure": 1, "summarise-files": 2}
    assert got["diagnostics"]["unresolved_entry"] == {
        "count": 1, "examples": [{"node_id": f"{WS}:deployable:web", "path": "", "detail": "dist/main.js"}]}

    code, out, _ = run(capsys, "status")
    assert code == 0 and out.startswith(f"last scan: {got['scanned_at']}\n")
    assert "  class: 1\n" in out and "  confirm-structure: 1\n" in out and "  summarise-files: 2\n" in out
    assert f"  unresolved_entry: 1\n    {WS}:deployable:web: dist/main.js\n" in out


def test_show_confidence_floor_and_all(repo, capsys):
    conn = sqlite3.connect(repo / ".cbi" / "model.db")
    with conn:
        for i in range(12):
            nid = f"{WS}:note:{i}"
            conn.execute("INSERT INTO nodes (id, kind, display_kind, name, path) VALUES (?, 'symbol', 'function', ?, ?)",
                         (nid, f"note{i}", f"notes/n{i}.ts"))
            conn.execute("INSERT INTO edges (src, dst, kind, source, confidence) VALUES (?, ?, 'mentions', 'treesitter', 1)",
                         (CIRCLE, nid))
        conn.execute("INSERT INTO edges (src, dst, kind, source, confidence) VALUES (?, ?, 'imports', 'treesitter', 0.4)",
                     (CIRCLE, f"{WS}:src/other/area.ts"))
    conn.close()
    code, out, _ = run(capsys, "show", "src/shapes/circle.ts")
    assert code == 0 and "mentions 12" in out and "part_of 1" in out and "0.4" not in out and "more mentions" in out
    code, out, _ = run(capsys, "show", "src/shapes/circle.ts", "--all")
    assert code == 0 and "more mentions" not in out and out.count("\n    mentions ") == 12
    shown = run_json(capsys, "show", "src/shapes/circle.ts")
    assert any(e["kind"] == "imports" and e["confidence"] == 0.4 for e in shown["outgoing"])
    code, out, _ = run(capsys, "show", "src/shapes/circle.ts", "--min-confidence", "0")
    assert code == 0 and "0.4" in out
    code, _, err = run(capsys, "show", "src/shapes/circle.ts", "--min-confidence", "2")
    assert code == 2 and "between 0 and 1" in err


def test_show_keeps_an_injection_call_under_the_confidence_floor(repo, capsys):
    src = f"{CIRCLE}#makeCircle"
    injected = f"{WS}:src/other/area.ts#area"
    plain = f"{CIRCLE}#Circle.area"
    conn = sqlite3.connect(repo / ".cbi" / "model.db")
    with conn:
        conn.execute(
            "INSERT INTO edges (src, dst, kind, source, confidence, attrs) VALUES (?, ?, 'calls', 'treesitter', 0.4, ?)",
            (src, injected, json.dumps({"via": "injection"})),
        )
        conn.execute(
            "INSERT INTO edges (src, dst, kind, source, confidence) VALUES (?, ?, 'calls', 'treesitter', 0.4)",
            (src, plain),
        )
    conn.close()
    code, out, _ = run(capsys, "show", "makeCircle")
    assert code == 0 and out.count("0.4") == 1 and "src/other/area.ts" in out
    assert "Circle.area" not in out


def test_status_needs_a_model(make_repo, monkeypatch, capsys):
    monkeypatch.chdir(make_repo({"a.ts": "export {};\n"}))
    code, _, err = run(capsys, "status")
    assert code == 1 and "cbi scan" in err


@pytest.mark.parametrize("command", ["search", "show", "tests-for", "status"])
def test_help_is_written_for_agents(capsys, command):
    with pytest.raises(SystemExit):
        main([command, "--help"])
    out = capsys.readouterr().out
    assert "--json" in out and "Exit codes:" in out and "Example: cbi " + command in out


def test_query_rejects_pragma(repo, capsys):
    code, out, err = run(capsys, "query", "PRAGMA database_list")
    assert code == 1
    assert "only read-only queries are permitted (got PRAGMA)" in err


def test_query_authorizer_blocks_attach_and_pragma(repo, capsys):
    # Direct ATTACH
    code, out, err = run(capsys, "query", "ATTACH DATABASE 'test.db' AS test")
    assert code == 1
    assert "only read-only queries are permitted (got ATTACH)" in err

    # EXPLAIN ATTACH (authorizer denies)
    code, out, err = run(capsys, "query", "EXPLAIN ATTACH DATABASE 'test.db' AS test")
    assert code == 1
    assert "not authorized" in err

    # PRAGMA table-valued function (authorizer denies)
    code, out, err = run(capsys, "query", "SELECT * FROM pragma_database_list()")
    assert code == 1
    assert "not authorized" in err


def test_query_execution_timeout(repo, capsys):
    code, out, err = run(capsys, "query", "WITH RECURSIVE cnt(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM cnt) SELECT count(*) FROM cnt;")
    assert code == 1
    assert "timeout limit (5.0s)" in err


def test_query_bounds_limit_and_json(repo, capsys):
    hits = run_json(capsys, "query", "SELECT id FROM nodes", "--limit", "999999")
    assert hits["row_count"] > 0
    assert hits["row_count"] <= 500


def test_cli_search_offset(repo, capsys):
    first = run_json(capsys, "search", "Circle", "--limit", "1", "--offset", "0")
    second = run_json(capsys, "search", "Circle", "--limit", "1", "--offset", "1")
    assert len(first) == 1
    assert len(second) == 1
    assert first[0]["id"] != second[0]["id"]

    code0, out0, _ = run(capsys, "search", "Circle", "--limit", "1", "--offset", "0")
    code1, out1, _ = run(capsys, "search", "Circle", "--limit", "1", "--offset", "1")
    assert code0 == 0 and code1 == 0
    assert out0 != out1

    # Negative offset rejected
    code_neg, _, err_neg = run(capsys, "search", "Circle", "--offset", "-1")
    assert code_neg == 2
    assert "offset must be 0 or greater" in err_neg


def test_cli_query_offset(repo, capsys):
    first = run_json(capsys, "query", "SELECT id FROM nodes ORDER BY id", "--limit", "1", "--offset", "0")
    second = run_json(capsys, "query", "SELECT id FROM nodes ORDER BY id", "--limit", "1", "--offset", "1")
    assert first["row_count"] == 1
    assert second["row_count"] == 1
    assert first["rows"][0]["id"] != second["rows"][0]["id"]

    code0, out0, _ = run(capsys, "query", "SELECT id FROM nodes ORDER BY id", "--limit", "1", "--offset", "0")
    code1, out1, _ = run(capsys, "query", "SELECT id FROM nodes ORDER BY id", "--limit", "1", "--offset", "1")
    assert code0 == 0 and code1 == 0
    assert out0 != out1

    # Negative offset rejected
    code_neg, _, err_neg = run(capsys, "query", "SELECT 1", "--offset", "-1")
    assert code_neg == 2
    assert "offset must be 0 or greater" in err_neg


def test_cli_hotspots_offset(repo, capsys):
    first = run_json(capsys, "hotspots", "--by", "loc", "--limit", "1", "--offset", "0")
    second = run_json(capsys, "hotspots", "--by", "loc", "--limit", "1", "--offset", "1")
    assert len(first["files"]) == 1
    assert len(second["files"]) == 1
    assert first["files"][0]["id"] != second["files"][0]["id"]

    code_neg, _, err_neg = run(capsys, "hotspots", "--offset", "-1")
    assert code_neg == 2
    assert "offset must be 0 or greater" in err_neg


def test_query_search_offset(repo):
    from cbi import query as query_mod

    conn = sqlite3.connect(repo / ".cbi" / "model.db")
    try:
        all_hits = query_mod.search(conn, "Circle")
        offset_hits = query_mod.search(conn, "Circle", offset=1)
        assert len(all_hits) > 1
        assert len(offset_hits) == len(all_hits) - 1
        assert offset_hits == all_hits[1:]

        # Test with limit and offset
        first = query_mod.search(conn, "Circle", limit=1, offset=0)
        second = query_mod.search(conn, "Circle", limit=1, offset=1)
        assert len(first) == 1
        assert len(second) == 1
        assert first[0]["id"] != second[0]["id"]
        assert second[0]["id"] == all_hits[1]["id"]
    finally:
        conn.close()


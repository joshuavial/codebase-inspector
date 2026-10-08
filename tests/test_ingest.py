import json
from pathlib import Path

import pytest

from cbi import ingest, store
from cbi.cli import main

FIXTURES = Path(__file__).parent / "fixtures"
INGEST = FIXTURES / "ingest"
WS = "local:repo"


@pytest.fixture
def repo(make_repo, monkeypatch):
    """The tracer repo plus two Python files, scanned."""
    files = {p.name: p.read_text() for p in (FIXTURES / "tracer").iterdir()}
    files["pkg/calc.py"] = "def add(a, b):\n    return a + b\n\nclass Calc:\n\n    def mul(self, a, b):\n        x = a * b\n        return x\n"
    files["tests/test_calc.py"] = "def test_add():\n    pass\n\nclass TestCalc:\n    def test_mul(self):\n        pass\n"
    root = make_repo(files)
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    conn = store.open_db(root / ".cbi" / "model.db")
    yield root, conn
    conn.close()


def _load(repo, name):
    root, conn = repo
    return ingest.ingest(conn, root, root, INGEST / name)


def _unmapped(conn):
    return sorted(d for (d,) in conn.execute("SELECT detail FROM diagnostics WHERE kind = 'unmapped_coverage'"))


def test_detect_by_content():
    assert ingest.detect((INGEST / "registry.lcov").read_text()) == "lcov"
    assert ingest.detect((INGEST / "registry.junit.xml").read_text()) == "junit"
    assert ingest.detect((INGEST / "calc.coverage.json").read_text()) == "coverage.py"
    for text in ('{"files": {}}', "<html></html>", "hello"):
        with pytest.raises(ingest.UnknownFormat):
            ingest.detect(text)


def test_lcov_lines_roll_up_to_symbols_and_unmapped_paths_are_reported(repo):
    _, conn = repo
    r = _load(repo, "registry.lcov")
    assert (r["format"], r["files"], r["lines"], r["unmapped"]) == ("lcov", 1, 5, 1)
    assert ingest.coverage(conn, f"{WS}:registry.ts#DeviceRegistry.put") == (1, 1)
    assert ingest.coverage(conn, f"{WS}:registry.ts#DeviceRegistry.revoke") == (1, 2)
    assert ingest.coverage(conn, f"{WS}:registry.ts") == (3, 5)
    assert len(_unmapped(conn)) == 1 and "dist/gone.ts" in _unmapped(conn)[0]


def test_junit_results_match_test_cases_and_unmatched_cases_are_reported(repo):
    _, conn = repo
    r = _load(repo, "registry.junit.xml")
    assert (r["results"], r["unmapped"]) == (2, 1)
    assert dict(conn.execute("SELECT test_node_id, status FROM results")) == {
        f"{WS}:registry.test.ts#stores and returns a device": "passed",
        f"{WS}:registry.test.ts#revokes a device": "failed",
    }
    assert "was deleted long ago" in _unmapped(conn)[0]


def test_junit_names_match_templated_test_names(repo, tmp_path):
    root, conn = repo
    with conn:
        conn.execute(
            "INSERT INTO nodes (id, parent_id, kind, display_kind, name, workspace_id, path) "
            f"VALUES ('{WS}:registry.test.ts#rejects ${{kind}} input', '{WS}:registry.test.ts', 'test', 'test', "
            f"'rejects ${{kind}} input', '{WS}', 'registry.test.ts')")
    xml = tmp_path / "t.xml"
    xml.write_text('<testsuite><testcase name="rejects empty input" file="registry.test.ts"/>'
                   '<testcase name="rejects empty" file="registry.test.ts"/></testsuite>')
    r = ingest.ingest(conn, root, root, xml)
    assert (r["results"], r["unmapped"]) == (1, 1)


def test_coverage_py_contexts_become_tests_edges(repo):
    _, conn = repo
    r = _load(repo, "calc.coverage.json")
    assert (r["format"], r["lines"], r["unmapped"]) == ("coverage.py", 6, 2)
    edges = conn.execute("SELECT src, dst, kind, confidence, weight FROM edges WHERE source = 'coverage' ORDER BY 1, 2")
    assert edges.fetchall() == [
        (f"{WS}:tests/test_calc.py#TestCalc > test_mul", f"{WS}:pkg/calc.py#Calc.mul", "tests", 1.0, 1),
        (f"{WS}:tests/test_calc.py#test_add", f"{WS}:pkg/calc.py#Calc.mul", "tests", 1.0, 1),
        (f"{WS}:tests/test_calc.py#test_add", f"{WS}:pkg/calc.py#add", "tests", 1.0, 1),
    ]
    unmapped = _unmapped(conn)
    assert any("test_gone" in d for d in unmapped) and any("vendored.py" in d for d in unmapped)
    assert ingest.coverage(conn, f"{WS}:pkg/calc.py#Calc.mul") == (2, 3)


def test_reingest_replaces_only_its_own_rows_and_suites_merge(repo, tmp_path):
    _, conn = repo
    a, b = tmp_path / "a.lcov", tmp_path / "b.lcov"
    a.write_text("SF:registry.ts\nDA:13,1\nDA:17,0\nend_of_record\nSF:nowhere.ts\nDA:1,1\nend_of_record\n")
    b.write_text("SF:registry.ts\nDA:17,3\nend_of_record\n")
    root = repo[0]
    ingest.ingest(conn, root, root, a)
    ingest.ingest(conn, root, root, b)
    _load(repo, "calc.coverage.json")
    assert ingest.coverage(conn, f"{WS}:registry.ts") == (2, 2)  # line 17 covered by b only
    edges_before = conn.execute("SELECT count(*) FROM edges WHERE source = 'coverage'").fetchone()
    unmapped_before = len(_unmapped(conn))

    a.write_text("SF:registry.ts\nDA:13,0\nend_of_record\n")
    r = ingest.ingest(conn, root, root, a)
    assert r["unmapped"] == 0
    assert conn.execute("SELECT count(*) FROM coverage_lines WHERE artifact = ?", (str(b.resolve()),)).fetchone() == (1,)
    assert ingest.coverage(conn, f"{WS}:registry.ts") == (1, 2)
    assert len(_unmapped(conn)) == unmapped_before - 1
    assert conn.execute("SELECT count(*) FROM edges WHERE source = 'coverage'").fetchone() == edges_before


def test_cli_prints_counts_and_rejects_unknown_files(repo, tmp_path, capsys):
    assert main(["ingest", str(INGEST / "registry.lcov"), str(INGEST / "registry.junit.xml")]) == 0
    out = capsys.readouterr().out
    assert "lcov, 5 lines in 1 files" in out and "2 test results" in out
    assert "2 paths or test cases matched nothing" in out
    bad = tmp_path / "x.txt"
    bad.write_text("hello")
    assert main(["ingest", str(bad)]) == 2
    assert "not loaded" in capsys.readouterr().err


def test_help_explains_each_format(capsys):
    with pytest.raises(SystemExit):
        main(["ingest", "--help"])
    out = capsys.readouterr().out
    for word in ("lcov", "coverage json --show-contexts", "--junitxml", "--enable-source-maps", "--sourceMap"):
        assert word in out
    example = out.index("Example: a TypeScript service suite")
    for procedure in ("pytest:", "vitest:", "jest:", "node:test:"):
        assert out.index(procedure) < example
    worked = out[example:]
    assert "ln -s" in worked and "service/tsconfig.test.json" in worked


def test_runner_detection_reads_manifests_not_the_help_recipe():
    node = json.dumps({
        "scripts": {
            "test:service": 'node -e "rmSync()" && tsc -p service/tsconfig.test.json && '
                            'cross-env NODE_ENV=test node --test "dist-service-test/service/**/*.test.js"',
            "cover": "node --test-reporter=lcov other.js",
        }
    })
    hits = ingest.runners_in_package(node, "package.json")
    assert [h["runner"] for h in hits] == ["node:test"]
    assert hits[0]["scripts"][0][0] == "test:service"
    hint = ingest._script_hint(hits[0]["scripts"][0][1])
    assert "NODE_ENV=test" in hint and "tsc -p service/tsconfig.test.json" in hint
    assert 'node --test "dist-service-test/service/**/*.test.js"' in hint
    assert "rmSync" not in hint

    vitest = ingest.runners_in_package('{"devDependencies": {"vitest": "1.0.0"}}', "web/package.json")
    jest = ingest.runners_in_package('{"scripts": {"test": "jest --coverage"}}', "package.json")
    assert vitest[0]["runner"] == "vitest" and jest[0]["runner"] == "jest"
    assert ingest.runners_in_package("{", "package.json") == []

    py = '[project]\nname = "demo"\n\n[dependency-groups]\ndev = ["pytest>=8"]\n'
    assert ingest.runners_in_pyproject(py, "pyproject.toml")[0]["runner"] == "pytest"
    poetry = '[tool.poetry.group.dev.dependencies]\npytest = "^8"\n'
    assert ingest.runners_in_pyproject(poetry, "pyproject.toml")[0]["runner"] == "pytest"
    assert ingest.runners_in_pyproject("[project]\nname='x'\n", "pyproject.toml") == []
    assert ingest.runners_in_pyproject("not toml", "pyproject.toml") == []

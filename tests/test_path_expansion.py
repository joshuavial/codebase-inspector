"""Finite-loop inference is bounded and does not assume guards select every value."""
import ast
import sqlite3

from cbi import testing_paths
from cbi.cli import main


def test_guarded_loop_variables_remain_unresolved(make_repo, monkeypatch):
    root = make_repo({
        'pkg/__init__.py': '',
        'pkg/a.py': 'def run(): return 1\n',
        'pkg/b.py': 'def run(): return 2\n',
        'tests/test_loops.py': '''import importlib

def test_guard():
    for name in ("pkg.a", "pkg.b"):
        if name == "pkg.a":
            importlib.import_module(name)

def test_alias_guard():
    for name in ("pkg.a", "pkg.b"):
        chosen = name
        if chosen == "pkg.a":
            importlib.import_module(chosen)

def test_finite():
    for name in ("pkg.a", "pkg.b"):
        importlib.import_module(name)

def test_string_iteration():
    for name in "pkg.a":
        importlib.import_module(name)

def test_dynamic_else(runtime_names):
    name = "pkg.a"
    for name in runtime_names:
        pass
    else:
        importlib.import_module(name)

def test_known_else(runtime_names):
    for name in runtime_names:
        pass
    else:
        chosen = "pkg.a"
        importlib.import_module(chosen)
''',
    })
    monkeypatch.chdir(root)
    assert main(['init']) == 0 and main(['scan']) == 0
    with sqlite3.connect(root / '.cbi/model.db') as conn:
        bindings = {(src.rsplit('#', 1)[-1], dst.rsplit(':', 1)[-1]) for src, dst in conn.execute(
            "SELECT src,dst FROM edges WHERE kind='tests'")}
    assert {('test_finite', 'pkg/a.py'), ('test_finite', 'pkg/b.py'), ('test_known_else', 'pkg/a.py')} <= bindings
    assert not any(src in {'test_guard', 'test_alias_guard', 'test_string_iteration', 'test_dynamic_else'} for src, _ in bindings)


def test_nested_literal_loops_share_a_bounded_expansion_budget(make_repo, monkeypatch):
    choices = repr(tuple('pkg.worker' for _ in range(20)))
    root = make_repo({
        'pkg/__init__.py': '',
        'pkg/worker.py': 'def run(): pass\n',
        'tests/test_product.py': 'import importlib\ndef test_product():\n'
        f'    for first in {choices}:\n'
        f'        for second in {choices}:\n'
        f'            for third in {choices}:\n'
        '                importlib.import_module(third)\n',
    })
    original = testing_paths.evaluate
    evaluations = 0

    def count(node, *args):
        nonlocal evaluations
        if isinstance(node, ast.Name) and node.id == 'third':
            evaluations += 1
            assert evaluations <= 256, 'literal loop product exceeded the shared work budget'
        return original(node, *args)

    monkeypatch.setattr(testing_paths, 'evaluate', count)
    monkeypatch.chdir(root)
    assert main(['init']) == 0 and main(['scan']) == 0
    with sqlite3.connect(root / '.cbi/model.db') as conn:
        details = [d for d, in conn.execute("SELECT detail FROM diagnostics WHERE kind='unsupported_test_mechanism'")]
    assert any('expansion_limit' in detail for detail in details)


def test_loops_without_path_targets_do_not_emit_path_boundaries(make_repo, monkeypatch):
    root = make_repo({'tests/test_values.py': 'def test_values():\n    for value in (1, 2):\n        assert value > 0\n'})
    monkeypatch.chdir(root)
    assert main(['init']) == 0 and main(['scan']) == 0
    with sqlite3.connect(root / '.cbi/model.db') as conn:
        assert not conn.execute("SELECT 1 FROM diagnostics WHERE kind='unsupported_test_mechanism'").fetchone()


def test_guard_assignments_do_not_reuse_pre_guard_path_aliases(make_repo, monkeypatch):
    root = make_repo({
        'pkg/__init__.py': '',
        'pkg/a.py': 'def run(): pass\n',
        'pkg/b.py': 'def run(): pass\n',
        'tests/test_guard_alias.py': '''import importlib

def test_loop_guard():
    chosen = "pkg.b"
    for name in ("pkg.a",):
        if (chosen := name) == "pkg.a":
            importlib.import_module(chosen)

def test_condition(runtime):
    chosen = "pkg.b"
    if (chosen := runtime()):
        importlib.import_module(chosen)
''',
    })
    monkeypatch.chdir(root)
    assert main(['init']) == 0 and main(['scan']) == 0
    with sqlite3.connect(root / '.cbi/model.db') as conn:
        assert not conn.execute("SELECT 1 FROM edges WHERE kind='tests'").fetchone()


def test_known_empty_loops_skip_guarded_bodies_and_preserve_else(make_repo, monkeypatch):
    root = make_repo({
        'pkg/__init__.py': '',
        'pkg/worker.py': 'def run(): pass\n',
        'pkg/other.py': 'def run(): pass\n',
        'tests/test_empty.py': '''import importlib

def test_tuple():
    for name in ():
        assert importlib.import_module("pkg.worker")

def test_list():
    for name in []:
        if name:
            importlib.import_module("pkg.worker")

def test_alias():
    items = ()
    for name in items:
        assert importlib.import_module("pkg.worker")

def test_string():
    for name in "":
        assert importlib.import_module("pkg.worker")

def test_bytes():
    for name in b"":
        assert importlib.import_module("pkg.worker")

def test_dictionary():
    items = {}
    for name in items:
        assert importlib.import_module("pkg.worker")

def test_else():
    name = "pkg.other"
    for name in ():
        assert importlib.import_module("pkg.worker")
    else:
        importlib.import_module(name)
    importlib.import_module(name)
''',
    })
    monkeypatch.chdir(root)
    assert main(['init']) == 0 and main(['scan']) == 0
    with sqlite3.connect(root / '.cbi/model.db') as conn:
        links = {(src.rsplit('#', 1)[-1], dst.rsplit(':', 1)[-1]) for src, dst in conn.execute(
            "SELECT src,dst FROM edges WHERE kind='tests'")}
        details = [d for d, in conn.execute("SELECT detail FROM diagnostics WHERE kind='unsupported_test_mechanism'")]
    assert links == {('test_else', 'pkg/other.py')}
    assert not details


def test_temporary_fixtures_and_locally_written_files_do_not_emit_unsupported_test_mechanism(make_repo, monkeypatch):
    root = make_repo({
        "assets/view.html": "<p>production</p>\n",
        "tests/test_temp_reads.py": '''from pathlib import Path
import importlib

def test_tmp_fixture(tmp_path):
    scratch = tmp_path / "scratch.txt"
    scratch.write_text("hello")
    assert scratch.read_text() == "hello"

def test_written_artifact(tmp_path):
    out = tmp_path / "artifact.json"
    with open(out, "w") as f:
        f.write("{}")
    assert out.read_text() == "{}"

def test_loop_with_temp_read(tmp_path):
    for i in range(2):
        p = tmp_path / f"item_{i}.txt"
        p.write_text("ok")
        assert p.read_text() == "ok"

def test_genuine_production_read():
    base = Path(__file__).resolve().parents[1]
    page = base / "assets" / "view.html"
    assert "production" in page.read_text()

def test_genuine_missing_tracked_read():
    base = Path(__file__).resolve().parents[1]
    page = base / "assets" / "missing.html"
    page.read_text()

def test_genuine_dynamic_loop(runtime_items):
    for item in runtime_items:
        importlib.import_module(item)
''',
    })
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    with sqlite3.connect(root / ".cbi/model.db") as conn:
        edges = {(src.rsplit("#", 1)[-1], dst.rsplit(":", 1)[-1])
                 for src, dst in conn.execute("SELECT src, dst FROM edges WHERE kind = 'tests'")}
        diags = [d for d, in conn.execute("SELECT detail FROM diagnostics WHERE kind = 'unsupported_test_mechanism'")]

    # Legitimate production file read must be linked
    assert ("test_genuine_production_read", "assets/view.html") in edges

    # Genuine missing tracked file read on line 29 must emit unsupported_test_mechanism
    assert any("test_temp_reads.py:29:" in d and "file_read" in d for d in diags)

    # Genuine dynamic loop over dynamic import must emit dynamic_loop
    assert any("dynamic_loop" in d and "test_temp_reads.py:32:" in d for d in diags)
    assert any("dynamic_import" in d and "test_temp_reads.py:33:" in d for d in diags)

    # False-positive temporary fixture reads and loops must NOT emit diagnostics
    assert not any("test_temp_reads.py:7:" in d for d in diags)   # scratch.read_text()
    assert not any("test_temp_reads.py:11:" in d for d in diags)  # open(out, "w")
    assert not any("test_temp_reads.py:13:" in d for d in diags)  # out.read_text()
    assert not any("test_temp_reads.py:16:" in d for d in diags)  # loop over temp reads
    assert not any("test_temp_reads.py:19:" in d for d in diags)  # p.read_text()


def test_anchored_binding_named_repo_links_to_production(make_repo, monkeypatch):
    root = make_repo({
        "pkg/prod.py": "def run(): return 42\n",
        "tests/test_repo_binding.py": '''from pathlib import Path

def test_repo_anchored():
    repo = Path(__file__).resolve().parents[1]
    prod = repo / "pkg" / "prod.py"
    assert "run" in prod.read_text()
''',
    })
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    with sqlite3.connect(root / ".cbi/model.db") as conn:
        edges = {(src.rsplit("#", 1)[-1], dst.rsplit(":", 1)[-1])
                 for src, dst in conn.execute("SELECT src, dst FROM edges WHERE kind = 'tests'")}
        diags = [d for d, in conn.execute("SELECT detail FROM diagnostics WHERE kind = 'unsupported_test_mechanism'")]
    assert ("test_repo_anchored", "pkg/prod.py") in edges
    assert not diags


def test_external_and_unresolved_reads_emit_diagnostics(make_repo, monkeypatch):
    root = make_repo({
        "pkg/prod.py": "def run(): return 42\n",
        "tests/test_unresolved_reads.py": '''from pathlib import Path

def test_literal_external_open():
    open("/external/proven-input.txt")

def test_literal_external_path():
    Path("/external/proven-input.txt").read_text()

def test_dynamic_unresolved_path(runtime_path):
    Path(runtime_path).read_text()

def test_dynamic_loop_unresolved(items):
    for item in items:
        Path(item).read_text()
''',
    })
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    with sqlite3.connect(root / ".cbi/model.db") as conn:
        diags = [d for d, in conn.execute("SELECT detail FROM diagnostics WHERE kind = 'unsupported_test_mechanism'")]

    # Literal external open and Path.read_text must emit file_read diagnostics
    assert any("test_unresolved_reads.py:4:" in d and "file_read" in d for d in diags)
    assert any("test_unresolved_reads.py:7:" in d and "file_read" in d for d in diags)

    # Dynamic unresolved path read must emit file_read diagnostic
    assert any("test_unresolved_reads.py:10:" in d and "file_read" in d for d in diags)

    # Dynamic loop enclosing unresolved path read must emit dynamic_loop and file_read
    assert any("test_unresolved_reads.py:13:" in d and "dynamic_loop" in d for d in diags)
    assert any("test_unresolved_reads.py:14:" in d and "file_read" in d for d in diags)


def test_committed_fixture_reads_do_not_emit_diagnostics(make_repo, monkeypatch):
    root = make_repo({
        "pkg/prod.py": "def run(): return 1\n",
        "tests/fixtures/data.json": '{"fixture": true}\n',
        "tests/test_fixtures.py": '''from pathlib import Path

FIXTURE_DIR = Path(__file__).parent / "fixtures"

def test_read_fixture_path():
    data = (FIXTURE_DIR / "data.json").read_text()
    assert "fixture" in data

def test_read_fixture_open():
    with open(FIXTURE_DIR / "data.json") as f:
        assert "fixture" in f.read()

def test_genuine_missing_production_file():
    missing = Path(__file__).resolve().parents[1] / "pkg" / "missing.py"
    missing.read_text()
''',
    })
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    with sqlite3.connect(root / ".cbi/model.db") as conn:
        diags = [d for d, in conn.execute("SELECT detail FROM diagnostics WHERE kind = 'unsupported_test_mechanism'")]

    # Reading committed test fixtures must NOT emit diagnostics
    assert not any("test_fixtures.py:6:" in d for d in diags)
    assert not any("test_fixtures.py:10:" in d for d in diags)

    # Genuine missing production code read MUST emit file_read diagnostic
    assert any("test_fixtures.py:15:" in d and "file_read" in d for d in diags)


def test_tuple_unpacking_assignments_bind_paths(make_repo, monkeypatch):
    root = make_repo({
        "pkg/prod.py": "def run(): return 1\n",
        "tests/test_unpacking.py": '''from pathlib import Path

def test_unpacking_scratch(tmp_path):
    png, svg = tmp_path / "a.png", tmp_path / "b.svg"
    png.read_bytes()
    svg.read_text()

def test_genuine_missing_production_file():
    missing = Path(__file__).resolve().parents[1] / "pkg" / "missing.py"
    missing.read_text()
''',
    })
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    with sqlite3.connect(root / ".cbi/model.db") as conn:
        diags = [d for d, in conn.execute("SELECT detail FROM diagnostics WHERE kind = 'unsupported_test_mechanism'")]

    # Tuple unpacking of scratch paths must NOT emit diagnostics
    assert not any("a.png" in d or "b.svg" in d or "test_unpacking.py:5:" in d or "test_unpacking.py:6:" in d for d in diags)

    # Genuine missing production code read MUST emit file_read diagnostic
    assert any("test_unpacking.py:10:" in d and "file_read" in d for d in diags)


def test_comprehension_over_fixture_and_scratch_globs_binds_paths(make_repo, monkeypatch):
    root = make_repo({
        "pkg/prod.py": "def run(): return 1\n",
        "tests/fixtures/sample.txt": "sample data\n",
        "tests/test_comprehensions.py": '''from pathlib import Path

FIXTURE = Path(__file__).parent / "fixtures"

def test_fixture_dict_comp():
    files = {path.relative_to(FIXTURE).as_posix(): path.read_text()
             for path in FIXTURE.rglob("*") if path.is_file()}
    assert files

def test_scratch_list_comp(tmp_path):
    (tmp_path / "scratch.txt").write_text("hello")
    data = [p.read_bytes() for p in tmp_path.iterdir()]
    assert data

def test_dynamic_loop_unresolved(items):
    for item in items:
        Path(item).read_text()

def test_genuine_missing_production_file():
    missing = Path(__file__).resolve().parents[1] / "pkg" / "missing.py"
    missing.read_text()
''',
    })
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    with sqlite3.connect(root / ".cbi/model.db") as conn:
        diags = [d for d, in conn.execute("SELECT detail FROM diagnostics WHERE kind = 'unsupported_test_mechanism'")]

    # Fixture dict comprehension read_text must NOT emit diagnostics
    assert not any("test_comprehensions.py:6:" in d for d in diags)

    # Scratch list comprehension read_bytes must NOT emit diagnostics
    assert not any("test_comprehensions.py:12:" in d for d in diags)

    # Dynamic loop unresolved reads MUST emit dynamic_loop and file_read diagnostics
    assert any("test_comprehensions.py:16:" in d and "dynamic_loop" in d for d in diags)
    assert any("test_comprehensions.py:17:" in d and "file_read" in d for d in diags)

    # Genuine missing production code read MUST emit file_read diagnostic
    assert any("test_comprehensions.py:21:" in d and "file_read" in d for d in diags)





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


def test_custom_fixtures_and_helper_returns_bind_scratch_paths(make_repo, monkeypatch):
    root = make_repo({
        "pkg/prod.py": "def run(): return 1\n",
        "tests/test_custom_helpers.py": '''import pytest
from pathlib import Path

@pytest.fixture
def custom_repo(make_repo):
    root = make_repo({"sample.txt": "sample\\n"}, name="custom")
    return root

def helper_repo(make_repo):
    root = make_repo({"sample.txt": "sample\\n"}, name="helper")
    return root, 123

def test_via_fixture(custom_repo):
    (custom_repo / "generated.txt").read_text()

def test_via_helper(make_repo):
    root, extra = helper_repo(make_repo)
    (root / "generated.txt").read_text()

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

    # Custom fixture and helper scratch reads must NOT emit diagnostics
    assert not any("test_custom_helpers.py:14:" in d for d in diags)
    assert not any("test_custom_helpers.py:18:" in d for d in diags)

    # Dynamic loop unresolved reads MUST emit dynamic_loop and file_read diagnostics
    assert any("test_custom_helpers.py:21:" in d and "dynamic_loop" in d for d in diags)
    assert any("test_custom_helpers.py:22:" in d and "file_read" in d for d in diags)

    # Genuine missing production code read MUST emit file_read diagnostic
    assert any("test_custom_helpers.py:26:" in d and "file_read" in d for d in diags)


def test_unproven_helper_call_and_external_return_retain_diagnostics(make_repo, monkeypatch):
    root = make_repo({
        "pkg/prod.py": "def run(): return 1\n",
        "tests/test_unproven_helper.py": '''from pathlib import Path

def helper_unknown_call(tmp_path):
    result = arbitrary_external_path(tmp_path)
    return result

def helper_external_path(tmp_path):
    return Path("/external/proven-input.txt")

def test_unproven_call_retains_diagnostic(tmp_path):
    Path(helper_unknown_call(tmp_path)).read_text()

def test_external_return_retains_diagnostic(tmp_path):
    Path(helper_external_path(tmp_path)).read_text()
''',
    })
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    with sqlite3.connect(root / ".cbi/model.db") as conn:
        diags = [d for d, in conn.execute("SELECT detail FROM diagnostics WHERE kind = 'unsupported_test_mechanism'")]

    # Case A: Unknown call taking tmp_path must retain file_read diagnostic
    assert any("test_unproven_helper.py:11:" in d and "file_read" in d for d in diags)

    # Case B: Helper returning an external path must retain file_read diagnostic
    assert any("test_unproven_helper.py:14:" in d and "file_read" in d for d in diags)


def test_conditional_scratch_assignment_retains_provenance(make_repo, monkeypatch):
    root = make_repo({
        "pkg/prod.py": "def run(): return 1\n",
        "tests/test_conditional_scratch.py": '''import sys
from pathlib import Path

def test_if_elif_else_scratch(tmp_path):
    fake_home = tmp_path / "home"
    if sys.platform == "darwin":
        desktop_dir = fake_home / "Library" / "Application Support" / "Claude"
    elif sys.platform == "win32":
        desktop_dir = fake_home / "AppData" / "Roaming" / "Claude"
    else:
        desktop_dir = fake_home / ".config" / "Claude"
    desktop_json = desktop_dir / "claude_desktop_config.json"
    desktop_json.read_text()

def test_if_else_one_branch_external_retains_diagnostic(tmp_path):
    if sys.platform == "darwin":
        desktop_dir = tmp_path / "Claude"
    else:
        desktop_dir = Path("/etc/claude")
    desktop_json = desktop_dir / "claude_desktop_config.json"
    desktop_json.read_text()

def test_if_without_else_retains_diagnostic(tmp_path):
    if sys.platform == "darwin":
        desktop_dir = tmp_path / "Claude"
    desktop_json = desktop_dir / "claude_desktop_config.json"
    desktop_json.read_text()
''',
    })
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    with sqlite3.connect(root / ".cbi/model.db") as conn:
        diags = [d for d, in conn.execute("SELECT detail FROM diagnostics WHERE kind = 'unsupported_test_mechanism'")]

    # All branches scratch: NO diagnostic
    assert not any("test_conditional_scratch.py:13:" in d for d in diags)

    # One branch external: MUST retain file_read diagnostic
    assert any("test_conditional_scratch.py:21:" in d and "file_read" in d for d in diags)

    # If without else: MUST retain file_read diagnostic
    assert any("test_conditional_scratch.py:27:" in d and "file_read" in d for d in diags)


def test_build_viewer_return_paths_in_scratch_directory(make_repo, monkeypatch):
    root = make_repo({
        "pkg/prod.py": "def run(): return 1\n",
        "tests/test_build_viewer.py": '''from pathlib import Path
from cbi import build

def test_viewer_scratch_reads_suppressed(tmp_path):
    viewer = build.build("conn", tmp_path / "viewer")
    html = viewer.read_text()
    css = (viewer.parent / "style.css").read_text()
    data = (viewer.parent / "data" / "tree.js").read_text()

def test_viewer_external_read_retains_diagnostic():
    viewer = build.build("conn", Path("/external/viewer"))
    viewer.read_text()
''',
    })
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    with sqlite3.connect(root / ".cbi/model.db") as conn:
        diags = [d for d, in conn.execute("SELECT detail FROM diagnostics WHERE kind = 'unsupported_test_mechanism'")]

    # Scratch viewer reads: NO diagnostics
    assert not any("test_build_viewer.py:6:" in d for d in diags)
    assert not any("test_build_viewer.py:7:" in d for d in diags)
    assert not any("test_build_viewer.py:8:" in d for d in diags)

    # External viewer read: MUST retain file_read diagnostic
    assert any("test_build_viewer.py:12:" in d and "file_read" in d for d in diags)


def test_render_viewer_png_output_in_scratch_file(make_repo, monkeypatch):
    root = make_repo({
        "pkg/prod.py": "def run(): return 1\n",
        "tests/test_render_png.py": '''from pathlib import Path
from cbi import render

def test_viewer_png_scratch_reads_suppressed(tmp_path):
    png = render.viewer_png("index.html", "tab=database", tmp_path / "render.png")
    data = png.read_bytes()

def test_viewer_png_external_read_retains_diagnostic():
    png = render.viewer_png("index.html", "tab=database", Path("/external/render.png"))
    data = png.read_bytes()
''',
    })
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    with sqlite3.connect(root / ".cbi/model.db") as conn:
        diags = [d for d, in conn.execute("SELECT detail FROM diagnostics WHERE kind = 'unsupported_test_mechanism'")]

    # Scratch png reads: NO diagnostics
    assert not any("test_render_png.py:6:" in d for d in diags)

    # External png read: MUST retain file_read diagnostic
    assert any("test_render_png.py:10:" in d and "file_read" in d for d in diags)


def test_resolve_target_scratch_and_external_boundaries(make_repo, monkeypatch):
    root = make_repo({
        "pkg/prod.py": "def run(): return 1\n",
        "tests/test_resolve_target.py": '''from pathlib import Path
from cbi import editor

def test_resolve_target_scratch_reads_suppressed(tmp_path):
    repo = tmp_path / "repo"
    opened = editor.resolve_ref_target("src/pay.py", 1, repo=repo, branch="main", sha="1234")
    data = Path(opened["file"]).read_text()
    snap = Path(opened["file"])
    text = snap.read_text()

def test_resolve_target_external_read_retains_diagnostic():
    opened = editor.resolve_ref_target("src/pay.py", 1, repo=Path("/external/repo"), branch="main", sha="1234")
    data = Path(opened["file"]).read_text()
''',
    })
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    with sqlite3.connect(root / ".cbi/model.db") as conn:
        diags = [d for d, in conn.execute("SELECT detail FROM diagnostics WHERE kind = 'unsupported_test_mechanism'")]

    # Scratch opened file reads: NO diagnostics
    assert not any("test_resolve_target.py:7:" in d for d in diags)
    assert not any("test_resolve_target.py:9:" in d for d in diags)

    # External repo read: MUST retain file_read diagnostic
    assert any("test_resolve_target.py:13:" in d and "file_read" in d for d in diags)


def test_git_shim_scratch_and_external_boundaries(make_repo, monkeypatch):
    root = make_repo({
        "pkg/prod.py": "def run(): return 1\n",
        "tests/test_git_shim.py": '''from pathlib import Path

def _git_shim(directory):
    return directory / "git.log"

def test_git_shim_scratch_read_suppressed(tmp_path):
    shim = tmp_path / "bin"
    log = _git_shim(shim)
    data = log.read_text()

def test_git_shim_external_read_retains_diagnostic():
    log = _git_shim(Path("/external/bin"))
    data = log.read_text()
''',
    })
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    with sqlite3.connect(root / ".cbi/model.db") as conn:
        diags = [d for d, in conn.execute("SELECT detail FROM diagnostics WHERE kind = 'unsupported_test_mechanism'")]

    # Scratch git shim log read: NO diagnostic
    assert not any("test_git_shim.py:9:" in d for d in diags)

    # External git shim log read: MUST retain file_read diagnostic
    assert any("test_git_shim.py:13:" in d and "file_read" in d for d in diags)


def test_helper_scratch_parameter_and_external_boundaries(make_repo, monkeypatch):
    root = make_repo({
        "pkg/prod.py": "def run(): return 1\n",
        "tests/test_helper_reads.py": '''from pathlib import Path

def fake_gh(tmp_path):
    return tmp_path / "gh.log"

def gh_calls(log):
    return log.read_text()

def test_helper_scratch_read_suppressed(tmp_path):
    log = fake_gh(tmp_path)
    calls = gh_calls(log)

def test_helper_external_read_retains_diagnostic():
    calls = gh_calls(Path("/external/gh.log"))
''',
    })
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    with sqlite3.connect(root / ".cbi/model.db") as conn:
        diags = [d for d, in conn.execute("SELECT detail FROM diagnostics WHERE kind = 'unsupported_test_mechanism'")]

    # Scratch read via helper: line 7 inside gh_calls is NOT flagged when called with scratch
    # External read via helper: line 7 inside gh_calls MUST retain file_read diagnostic when called with external path
    assert any("test_helper_reads.py:7:" in d and "file_read" in d for d in diags)


def test_editor_launch_scratch_split_and_external_boundaries(make_repo, monkeypatch):
    root = make_repo({
        "pkg/prod.py": "def run(): return 1\n",
        "tests/test_mock_editor.py": '''from pathlib import Path

def _fake_code(tmp_path):
    code = tmp_path / "bin" / "code"
    snap = tmp_path / "snapshots" / "side" / "src" / "app.py"
    snap.parent.mkdir(parents=True, exist_ok=True)
    snap.write_text("content\\n")
    launched = [[str(code), f"{snap}:10"]]
    return code, launched

def test_scratch_editor_goto_split_suppressed(tmp_path):
    code, launched = _fake_code(tmp_path)
    goto = launched[0][-1]
    snap = Path(goto.rsplit(":", 1)[0])
    text = snap.read_text()

def test_external_editor_goto_split_retains_diagnostic(tmp_path):
    code = tmp_path / "bin" / "code"
    launched = [[str(code), "/external/file.py:10"]]
    goto = launched[0][-1]
    target = Path(goto.rsplit(":", 1)[0])
    text = target.read_text()
''',
    })
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    with sqlite3.connect(root / ".cbi/model.db") as conn:
        diags = [d for d, in conn.execute("SELECT detail FROM diagnostics WHERE kind = 'unsupported_test_mechanism'")]

    # Scratch editor launch split read: NO diagnostic
    assert not any("test_mock_editor.py:15:" in d for d in diags)

    # External editor read: MUST retain file_read diagnostic
    assert any("test_mock_editor.py:22:" in d and "file_read" in d for d in diags)


def test_cbi_scratch_metadata_read_and_external_boundaries(make_repo, monkeypatch):
    root = make_repo({
        "pkg/prod.py": "def run(): return 1\n",
        "tests/test_cbi_metadata.py": '''def test_scratch_cbi_metadata_suppressed():
    doc = open(".cbi/structure.json").read()

def test_external_cbi_metadata_retains_diagnostic():
    doc = open("/external/.cbi/structure.json").read()
''',
    })
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    with sqlite3.connect(root / ".cbi/model.db") as conn:
        diags = [d for d, in conn.execute("SELECT detail FROM diagnostics WHERE kind = 'unsupported_test_mechanism'")]

    # Scratch relative .cbi/ metadata read: NO diagnostic
    assert not any("test_cbi_metadata.py:2:" in d for d in diags)

    # External .cbi/ metadata read: MUST retain file_read diagnostic
    assert any("test_cbi_metadata.py:5:" in d and "file_read" in d for d in diags)


def test_fake_code_with_external_returns_retains_diagnostic(make_repo, monkeypatch):
    root = make_repo({
        "pkg/prod.py": "def run(): return 1\n",
        "tests/test_fake_code_external.py": '''from pathlib import Path

def _fake_code(tmp_path, monkeypatch):
    return Path("/external/real-code"), Path("/external/real-log")

def test_caller_read_external_from_fake_code(tmp_path, monkeypatch):
    code, launched = _fake_code(tmp_path, monkeypatch)
    data = code.read_text()
    log_data = launched.read_text()
''',
    })
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    with sqlite3.connect(root / ".cbi/model.db") as conn:
        diags = [d for d, in conn.execute("SELECT detail FROM diagnostics WHERE kind = 'unsupported_test_mechanism'")]

    assert any("test_fake_code_external.py:8:" in d and "file_read" in d for d in diags)
    assert any("test_fake_code_external.py:9:" in d and "file_read" in d for d in diags)


def test_absolute_and_anchored_cbi_paths_retain_diagnostics(make_repo, monkeypatch):
    root = make_repo({
        "pkg/prod.py": "def run(): return 1\n",
        "tests/test_cbi_abs_anchored.py": '''from pathlib import Path

def test_absolute_cbi_path_retains_diagnostic():
    open("/.cbi/real-code.py").read()

def test_anchored_cbi_tracked_read_retains_diagnostic():
    p = Path(__file__).parent.parent / ".cbi" / "production.py"
    p.read_text()
''',
    })
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    with sqlite3.connect(root / ".cbi/model.db") as conn:
        diags = [d for d, in conn.execute("SELECT detail FROM diagnostics WHERE kind = 'unsupported_test_mechanism'")]

    assert any("test_cbi_abs_anchored.py:4:" in d and "file_read" in d for d in diags)
    assert any("test_cbi_abs_anchored.py:8:" in d and "file_read" in d for d in diags)


def test_launch_callback_appending_external_retains_diagnostic(make_repo, monkeypatch):
    root = make_repo({
        "pkg/prod.py": "def run(): return 1\n",
        "tests/test_callback_external.py": '''from pathlib import Path
from cbi import editor

def observed(tmp_path, monkeypatch):
    paths = []
    monkeypatch.setattr(editor, "launch", lambda value: paths.append("/external/real.py"))
    return paths

def test_read_external_from_callback(tmp_path, monkeypatch):
    paths = observed(tmp_path, monkeypatch)
    data = Path(paths[0]).read_text()
''',
    })
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    with sqlite3.connect(root / ".cbi/model.db") as conn:
        diags = [d for d, in conn.execute("SELECT detail FROM diagnostics WHERE kind = 'unsupported_test_mechanism'")]

    assert any("test_callback_external.py:11:" in d and "file_read" in d for d in diags)


def test_helper_callee_defaults_do_not_inherit_caller_locals(make_repo, monkeypatch):
    root = make_repo({
        "pkg/prod.py": "def run(): return 1\n",
        "tests/test_helper_defaults.py": '''from pathlib import Path

def reader(force, log=Path("/external/value")):
    return log.read_text()

def test_caller(tmp_path):
    log = tmp_path / "safe"
    reader(True)

def test_caller_explicit_scratch(tmp_path):
    log = tmp_path / "safe"
    reader(True, log)
''',
    })
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    with sqlite3.connect(root / ".cbi/model.db") as conn:
        diags = [d for d, in conn.execute("SELECT detail FROM diagnostics WHERE kind = 'unsupported_test_mechanism'")]

    # Because reader(True) does not pass log, callee must evaluate its default log=Path("/external/value")
    # and NOT inherit caller's local variable `log` (tmp_path / "safe").
    # Therefore, line 4 in reader MUST emit a file_read diagnostic!
    assert any("test_helper_defaults.py:4:" in d and "file_read" in d for d in diags)


def test_fstring_with_external_prefix_retains_diagnostic(make_repo, monkeypatch):
    root = make_repo({
        "pkg/prod.py": "def run(): return 1\n",
        "tests/test_fstring_external.py": '''from pathlib import Path

def test_external_prefix_read(tmp_path):
    Path(f"/external/{tmp_path}/real.py").read_text()

def test_scratch_root_read(tmp_path):
    Path(f"{tmp_path}/real.py").read_text()
''',
    })
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    with sqlite3.connect(root / ".cbi/model.db") as conn:
        diags = [d for d, in conn.execute("SELECT detail FROM diagnostics WHERE kind = 'unsupported_test_mechanism'")]

    # Even though {tmp_path} is scratch, the whole path has an external absolute prefix /external/
    # and is not a scratch path. Therefore, line 4 MUST emit a file_read diagnostic!
    assert any("test_fstring_external.py:4:" in d and "file_read" in d for d in diags)
    # Scratch root f-string has NO diagnostic on line 7
    assert not any("test_fstring_external.py:7:" in d for d in diags)


def test_helper_callee_defaults_shadow_module_globals(make_repo, monkeypatch):
    root = make_repo({
        "pkg/prod.py": "def run(): return 1\n",
        "tests/test_module_shadow.py": '''import tempfile
from pathlib import Path

log = Path(tempfile.mkdtemp())

def reader(force, log=Path("/external/value")):
    return log.read_text()

def test_omitted_argument_uses_default():
    reader(True)

def test_explicit_argument_uses_scratch():
    reader(True, log)
''',
    })
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    with sqlite3.connect(root / ".cbi/model.db") as conn:
        diags = [d for d, in conn.execute("SELECT detail FROM diagnostics WHERE kind = 'unsupported_test_mechanism'")]

    # Because test_omitted_argument_uses_default calls reader(True) without log,
    # the parameter log must bind its declared default Path("/external/value")
    # shadowing the module-level scratch variable log.
    # Therefore, line 7 in reader MUST emit a file_read diagnostic!
    assert any("test_module_shadow.py:7:" in d and "file_read" in d for d in diags)


def test_helper_callee_defaults_evaluate_in_definition_scope(make_repo, monkeypatch):
    root = make_repo({
        "pkg/prod.py": "def run(): return 1\n",
        "tests/test_definition_defaults.py": '''from pathlib import Path

log = Path("/external/value")

def reader(log, target=log):
    return target.read_text()

def test_caller_argument_does_not_mutate_default(tmp_path):
    safe = tmp_path / "safe"
    reader(safe)

def test_caller_explicit_scratch_passed(tmp_path):
    safe = tmp_path / "safe"
    reader(safe, safe)
''',
    })
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    with sqlite3.connect(root / ".cbi/model.db") as conn:
        diags = [d for d, in conn.execute("SELECT detail FROM diagnostics WHERE kind = 'unsupported_test_mechanism'")]

    # Default expression target=log must evaluate in definition module scope (log = Path("/external/value")),
    # and NOT be altered by caller's actual argument log = safe.
    # Therefore, line 6 in reader MUST emit a file_read diagnostic!
    assert any("test_definition_defaults.py:6:" in d and "file_read" in d for d in diags)










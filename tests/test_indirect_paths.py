"""Literal dynamic imports and local file paths bind without executing tests."""

import sqlite3

from cbi.cli import main


def test_local_importlib_and_file_paths(make_repo, monkeypatch, capsys):
    root = make_repo({
        "pkg/__init__.py": "",
        "pkg/worker.py": "def run(): return 1\n",
        "scripts/worker.py": "raise RuntimeError('must never execute')\n",
        "assets/view.html": "<p>generic</p>\n",
        "tests/test_contract.py": '''from pathlib import Path as P
import importlib as loader
from importlib.util import spec_from_file_location as spec

def test_module():
    module = "pkg.worker"
    loader.import_module(module)

def test_file():
    base = P(__file__).resolve().parents[1]
    program = base / "scripts" / "worker.py"
    spec("worker", program)

def test_read():
    base = P(__file__).parent.parent
    page = base.joinpath("assets", "view.html")
    assert "generic" in page.read_text()

def test_dynamic(name):
    loader.import_module(name)

def test_shadow(loader):
    loader.import_module("scripts.worker")

def test_reassigned(name):
    target = "pkg.worker"
    target = name
    loader.import_module(target)

def test_conditional(flag):
    target = "pkg.worker"
    if flag:
        target = "scripts.worker"
    loader.import_module(target)

def test_branch(flag):
    if flag:
        target = "pkg.worker"
        loader.import_module(target)
''',
    })
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    assert main(["scan"]) == 0
    capsys.readouterr()
    conn = sqlite3.connect(root / ".cbi/model.db")
    bindings = {(src.split("#")[-1], dst.split(":", 2)[-1]) for src, dst in conn.execute(
        "SELECT src, dst FROM edges WHERE kind = 'tests'")}
    assert ("test_module", "pkg/worker.py") in bindings
    assert ("test_file", "scripts/worker.py") in bindings
    assert ("test_read", "assets/view.html") in bindings
    assert ("test_branch", "pkg/worker.py") in bindings
    assert not any(src in {"test_dynamic", "test_shadow", "test_reassigned", "test_conditional"} for src, _ in bindings)
    unresolved = conn.execute("SELECT detail FROM diagnostics WHERE kind = 'unsupported_test_mechanism'").fetchall()
    assert any("dynamic_import" in detail and "tests/test_contract.py:" in detail for detail, in unresolved)


def test_control_scopes_do_not_reuse_overwritten_targets(make_repo, monkeypatch, capsys):
    root = make_repo({
        "pkg/__init__.py": "",
        "pkg/worker.py": "def run(): return 1\n",
        "assets/view.html": "<p>generic</p>\n",
        "tests/test_contract.py": '''from pathlib import Path
import importlib

def test_with_path(factory):
    target = Path(__file__).parents[1] / "assets" / "view.html"
    with factory() as target:
        target.read_text()

def test_with_loader(factory):
    import importlib as loader
    with factory() as loader:
        loader.import_module("pkg.worker")

def test_finally_path(factory):
    target = Path(__file__).parents[1] / "assets" / "view.html"
    try:
        target = factory()
    finally:
        target.read_text()

def test_except_path(factory):
    target = Path(__file__).parents[1] / "assets" / "view.html"
    try:
        target = factory()
        raise ValueError()
    except ValueError:
        target.read_text()

def test_finally_loader(factory):
    import importlib as loader
    try:
        loader = factory()
    finally:
        loader.import_module("pkg.worker")

def test_branch(flag):
    if flag:
        target = Path(__file__).parents[1] / "assets" / "view.html"
        target.read_text()

def test_finally_known(factory):
    try:
        factory()
    finally:
        target = Path(__file__).parents[1] / "assets" / "view.html"
        target.read_text()
''',
    })
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    capsys.readouterr()
    with sqlite3.connect(root / ".cbi/model.db") as conn:
        bindings = {(src.split("#")[-1], dst.split(":", 2)[-1]) for src, dst in conn.execute(
            "SELECT src, dst FROM edges WHERE kind = 'tests'")}
    assert ("test_branch", "assets/view.html") in bindings
    assert ("test_finally_known", "assets/view.html") in bindings
    assert not {(src, dst) for src, dst in bindings if src in {
        "test_with_path", "test_with_loader", "test_finally_path", "test_except_path", "test_finally_loader",
    }}

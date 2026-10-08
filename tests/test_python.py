"""Python symbols, imports, calls and pytest links over two uv packages, checked against a golden dump."""

import json
import os
import sqlite3
from pathlib import Path

import pytest

from cbi.cli import main

GOLDEN = Path(__file__).parent / "golden" / "python.txt"

FILES = {
    "core/pyproject.toml": '[project]\nname = "core"\n',
    "core/src/core/__init__.py": '''\
"""Geometry core."""
from .shapes import Circle
from core.util import *
''',
    "core/src/core/shapes.py": '''\
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Point:
    """A point.

    In pixels.
    """
    x: int = 0
    y: int = field(default=0)


class Circle:
    class Style:
        """How a circle is drawn."""
        class Stroke:
            width = 1

        def colour(self):
            return "red"

    def __init__(self, radius):
        self.radius = radius

    @property
    def area(self) -> float:
        return 3.14 * self.scale(self.radius) ** 2

    @area.setter
    def area(self, value):
        pass

    def scale(self, n):
        return n

    @classmethod
    def unit(cls):
        return cls.make(1)

    @staticmethod
    def make(r):
        return Circle(r)

    async def fetch(self):
        return Point()
''',
    "core/src/core/util.py": '''\
import os


def helper():
    return pick(1)


def pick(a):
    return a


def pick(a, b=None):
    return b


def run(helper):
    return helper()


def other():
    for helper in [len]:
        helper()
    return [pick for pick in ()]


if os.name == "nt":
    def platform():
        return "nt"
else:
    def platform():
        return "posix"
''',
    "core/src/core/io/loader.py": '''\
from ..util import helper
from .. import shapes
from . import formats


def load():
    helper()
    formats.parse()
    return shapes.Circle(2)
''',
    "core/src/core/io/formats.py": "def parse():\n    return {}\n",
    "core/tests/test_geometry.py": '''\
import json
from pathlib import Path

import pytest

from core import Circle
from core.util import helper

DATA = json.loads((Path(__file__).parent / "data" / "circle.json").read_text())


def make():
    return Circle(DATA["radius"])


class TestCircle:
    def setup_value(self):
        return 2

    def test_area(self):
        assert make().area

    class TestNested:
        def test_unit(self):
            Circle.unit()


@pytest.mark.asyncio
async def test_fetch():
    await Circle(1).fetch()


def test_helper():
    with open("tests/data/circle.json") as fh:
        assert helper() is None and fh
''',
    "core/tests/data/circle.json": '{"radius": 2}\n',
    "core/tests/test_scripts.py": '''\
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("tool", ROOT / "scripts" / "tool.py")


def test_run_script():
    assert "echo" in (ROOT / "scripts/run.sh").read_text()
''',
    "core/scripts/tool.py": "def main():\n    pass\n",
    "core/scripts/run.sh": "echo hi\n",
    "core/tests/test_orphan.py": "import json\n\n\ndef test_nothing():\n    assert json.dumps(1)\n",
    "app/pyproject.toml": '''\
[project]
name = "app"
dependencies = ["core"]

[tool.uv.sources]
core = { path = "../core", editable = true }
''',
    "app/src/app/__init__.py": "",
    "app/src/app/main.py": '''\
import core.util
import core.util as u
from core import shapes
from core.shapes import Point
from core import pick


def main():
    u.helper()
    core.util.pick(1)
    return shapes.Circle(1), Point(1, 2)


def lazy():
    from core.io.loader import load
    return load()
''',
    "app/tests/test_main.py": "def test_main():\n    pass\n",
}


def dump(root):
    conn = sqlite3.connect(root / ".cbi" / "model.db")
    lines = [json.dumps(["node", *r]) for r in conn.execute(
        "SELECT id, parent_id, kind, display_kind, start_line, end_line, signature, doc "
        "FROM nodes WHERE kind IN ('symbol', 'test') ORDER BY id")]
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


def test_golden_python(repo):
    text = dump(repo)
    if os.environ.get("CBI_UPDATE_GOLDEN"):
        GOLDEN.write_text(text)
    assert text == GOLDEN.read_text()


def short(node_id):
    return node_id.split(":", 2)[2]


def edges(root, kind, source=None):
    conn = sqlite3.connect(root / ".cbi" / "model.db")
    rows = conn.execute("SELECT src, dst, source, confidence FROM edges WHERE kind = ?", (kind,))
    return {(short(s), short(d)) for s, d, src, _ in rows if source in (None, src)}


def nodes(root):
    conn = sqlite3.connect(root / ".cbi" / "model.db")
    return {short(i): (k, d, s) for i, k, d, s in conn.execute(
        "SELECT id, kind, display_kind, signature FROM nodes WHERE kind IN ('symbol', 'test')")}


def test_symbols(repo):
    n = nodes(repo)
    assert n["core/src/core/shapes.py#Point"] == ("symbol", "class", "@dataclass(frozen=True) class Point")
    assert n["core/src/core/shapes.py#Circle.Style.Stroke"][1] == "class"  # nested twice
    assert n["core/src/core/shapes.py#Circle.Style.colour"][1] == "method"
    assert n["core/src/core/shapes.py#Circle.fetch"][2] == "async def fetch(self)"
    # A property and its setter share a name; the signature hash tells them apart.
    areas = sorted(k for k in n if k.startswith("core/src/core/shapes.py#Circle.area~"))
    assert len(areas) == 2
    assert n["core/src/core/util.py#platform~0f92bfa0"][2] == "def platform()"
    assert "core/src/core/util.py#platform~0f92bfa0~2" in n  # identical signatures
    tests = {k: v[1] for k, v in n.items() if v[0] == "test"}
    assert tests == {
        "core/tests/test_geometry.py#TestCircle": "test suite",
        "core/tests/test_geometry.py#TestCircle > test_area": "test case",
        "core/tests/test_geometry.py#TestCircle > TestNested": "test suite",
        "core/tests/test_geometry.py#TestCircle > TestNested > test_unit": "test case",
        "core/tests/test_geometry.py#test_fetch": "test case",
        "core/tests/test_geometry.py#test_helper": "test case",
        "core/tests/test_orphan.py#test_nothing": "test case",
        "core/tests/test_scripts.py#test_run_script": "test case",
        "app/tests/test_main.py#test_main": "test case",
    }
    assert n["core/tests/test_geometry.py#TestCircle.setup_value"][:2] == ("symbol", "method")


def test_imports(repo):
    imports = edges(repo, "imports")
    assert ("core/src/core/__init__.py", "core/src/core/shapes.py") in imports  # relative
    assert ("core/src/core/__init__.py", "core/src/core/util.py") in imports  # absolute, src layout, star
    assert ("core/src/core/io/loader.py", "core/src/core/util.py") in imports  # ..util
    assert ("core/src/core/io/loader.py", "core/src/core/shapes.py") in imports  # from .. import submodule
    assert ("core/src/core/io/loader.py", "core/src/core/io/formats.py") in imports  # namespace package
    # Through the __init__.py re-export to the defining file, not the package.
    assert ("core/tests/test_geometry.py", "core/src/core/shapes.py") in imports
    assert ("core/tests/test_geometry.py", "core/src/core/__init__.py") not in imports
    # Across uv packages through the path source, star re-export followed.
    assert {("app/src/app/main.py", "core/src/core/util.py"), ("app/src/app/main.py", "core/src/core/shapes.py"),
            ("app/src/app/main.py", "core/src/core/io/loader.py")} <= imports


def test_calls(repo):
    calls = edges(repo, "calls")
    assert ("core/src/core/io/loader.py#load", "core/src/core/util.py#helper") in calls
    assert ("core/src/core/io/loader.py#load", "core/src/core/io/formats.py#parse") in calls  # from . import mod
    assert ("core/src/core/io/loader.py#load", "core/src/core/shapes.py#Circle") in calls  # from .. import mod
    assert ("core/src/core/shapes.py#Circle.make", "core/src/core/shapes.py#Circle") in calls
    assert ("app/src/app/main.py#main", "core/src/core/util.py#helper") in calls  # import a.b as u
    assert ("app/src/app/main.py#main", "core/src/core/shapes.py#Circle") in calls
    assert ("app/src/app/main.py#main", "core/src/core/shapes.py#Point") in calls
    assert ("app/src/app/main.py#lazy", "core/src/core/io/loader.py#load") in calls  # import inside a function
    # A parameter, a loop variable and a comprehension variable shadow the module's names.
    assert not {c for c in calls if c[0] in ("core/src/core/util.py#run", "core/src/core/util.py#other")}
    conn = sqlite3.connect(repo / ".cbi" / "model.db")
    self_calls = conn.execute(
        "SELECT dst, confidence FROM edges WHERE kind = 'calls' AND src LIKE '%#Circle.unit'").fetchall()
    assert [(short(d), c) for d, c in self_calls] == [("core/src/core/shapes.py#Circle.make", 0.6)]


def test_test_links(repo):
    tests = edges(repo, "tests", "treesitter")
    assert ("core/tests/test_geometry.py", "core/src/core/shapes.py#Circle") in tests  # from a helper outside any case
    assert ("core/tests/test_geometry.py#TestCircle > test_area", "core/src/core/shapes.py#Circle") in tests  # one level through make()
    assert ("core/tests/test_geometry.py#TestCircle > TestNested > test_unit", "core/src/core/shapes.py#Circle.unit") in tests
    assert ("core/tests/test_geometry.py#test_helper", "core/src/core/util.py#helper") in tests
    assert ("core/tests/test_geometry.py", "core/tests/data/circle.json") in tests  # Path(__file__).parent / ...
    assert ("core/tests/test_geometry.py#test_helper", "core/tests/data/circle.json") in tests  # open() from the root
    # Path constants from __file__, .parents[n], and a script loaded by importlib.
    assert ("core/tests/test_scripts.py", "core/scripts/tool.py") in tests
    assert ("core/tests/test_scripts.py#test_run_script", "core/scripts/run.sh") in tests
    # tests/ does not mirror src/: the file name still finds the one main.py in the app package.
    assert edges(repo, "tests", "naming") == {("app/tests/test_main.py", "app/src/app/main.py")}


def test_diagnostics(repo):
    conn = sqlite3.connect(repo / ".cbi" / "model.db")
    rows = conn.execute("SELECT kind, node_id, detail FROM diagnostics ORDER BY kind").fetchall()
    assert [(k, short(n), d) for k, n, d in rows] == [
        ("ambiguous_call", "app/src/app/main.py", "1 calls with more than one candidate"),  # core.util.pick
        ("ambiguous_call", "core/src/core/util.py", "1 calls with more than one candidate"),
        ("unmatched_test", "core/tests/test_orphan.py",
         "no call, import, file read or file name reaches tracked code; imports only json"),
    ]


def test_patch_string_links_a_flat_test(make_repo, monkeypatch):
    root = make_repo({
        "app/utils/db.py": "def create_db_connection():\n    return None\n\ndef query_data():\n    return []\n",
        "tests/test_admin_users.py": '''\
def test_users(mocker):
    mocker.patch("app.utils.db.create_db_connection")

def test_direct():
    patch("app.utils.db.query_data")
''',
        "tests/test_env_only.py": '''\
def test_env(mocker):
    mocker.patch.dict("os.environ", {"X": "1"})
''',
    })
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    assert main(["scan"]) == 0
    conn = sqlite3.connect(root / ".cbi" / "model.db")
    rows = {(short(s), short(d), c) for s, d, c in conn.execute(
        "SELECT src, dst, confidence FROM edges WHERE kind = 'tests' AND source = 'treesitter'")}
    assert ("tests/test_admin_users.py#test_users", "app/utils/db.py", 0.8) in rows
    assert ("tests/test_admin_users.py#test_direct", "app/utils/db.py", 0.8) in rows
    unmatched = [short(n) for n, in conn.execute(
        "SELECT node_id FROM diagnostics WHERE kind = 'unmatched_test'")]
    assert unmatched == ["tests/test_env_only.py"]

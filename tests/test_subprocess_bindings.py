"""Subprocess tests bind literal child programs and expose unknown execution."""
import sqlite3
import subprocess

from cbi.cli import main


def test_literal_child_programs_and_unknown_commands(make_repo, monkeypatch):
    root = make_repo({
        'worker.py': 'def run(): return 1\n',
        'jobs.py': 'def main(): pass\n',
        'tests/test_children.py': '''import subprocess
import sys

def test_script():
    subprocess.run([sys.executable, "worker.py"])

def test_module():
    subprocess.run([sys.executable, "-m", "jobs"])

def test_inline():
    subprocess.run([sys.executable, "-c", "import worker; worker.run()"])

def test_unknown(command):
    subprocess.run(command)

def test_local_import():
    from subprocess import run as launch
    import sys as runtime
    launch([runtime.executable, "worker.py"])

def test_shadowed(subprocess):
    subprocess.run(["worker.py"])
''',
    })
    monkeypatch.chdir(root)
    assert main(['init']) == 0 and main(['scan']) == 0
    with sqlite3.connect(root / '.cbi/model.db') as conn:
        links = set(conn.execute("SELECT s.name, d.path FROM edges e JOIN nodes s ON s.id=e.src "
                                 "JOIN nodes d ON d.id=e.dst WHERE e.kind='tests'"))
        assert ('test_script', 'worker.py') in links
        assert ('test_module', 'jobs.py') in links
        assert ('test_inline', 'worker.py') in links
        assert ('test_local_import', 'worker.py') in links
        assert not any(src == 'test_shadowed' for src, _ in links)
        detail = conn.execute("SELECT detail FROM diagnostics WHERE kind='unsupported_test_mechanism'").fetchall()
        assert any('subprocess' in d and 'test_children.py:14' in d for (d,) in detail)

def test_local_subprocess_assignment_does_not_bind(make_repo, monkeypatch, capsys):
    root = make_repo({
        "worker.py": "raise RuntimeError('must not run')\n",
        "tests/test_contract.py": '''import subprocess

class Fake:
    def run(self, args):
        return args

def test_fake():
    subprocess = Fake()
    assert subprocess.run(["worker.py"]) == ["worker.py"]
''',
    })
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    assert main(["scan"]) == 0
    capsys.readouterr()
    conn = sqlite3.connect(root / ".cbi/model.db")
    links = conn.execute("SELECT src, dst, attrs FROM edges WHERE kind = 'tests' AND dst LIKE '%:worker.py'").fetchall()
    assert links == []


def test_subprocess_binding_reads_ref_objects(make_repo, monkeypatch, capsys):
    root = make_repo({
        'worker.py': "raise RuntimeError('must not execute')\n",
        'tests/test_child.py': 'import subprocess\ndef test_child(): subprocess.run(["worker.py"])\n',
    })
    monkeypatch.chdir(root)
    assert main(['init']) == 0
    assert main(['scan', '--ref', 'HEAD']) == 0
    capsys.readouterr()
    sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    with sqlite3.connect(root / '.cbi' / 'refs' / sha / 'model.db') as conn:
        assert conn.execute("SELECT 1 FROM edges WHERE kind='tests' AND dst LIKE '%:worker.py'").fetchone()


def test_companion_test_script_path_expressions(make_repo, monkeypatch, capsys):
    root = make_repo({
        'tests/layout_check.js': '// companion js test\n',
        'tests/nav_check.js': '// companion nav check\n',
        'tests/helper_check.js': '// companion helper check\n',
        'src/viewer/editor.js': '// viewer script\n',
        'tests/test_views.py': '''import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "src" / "viewer" / "editor.js"

def test_parent_slash():
    subprocess.run(["node", str(Path(__file__).parent / "layout_check.js")])

def test_with_name():
    script = Path(__file__).with_name("nav_check.js")
    subprocess.run(["node", str(script)])

def test_os_path_join():
    subprocess.run(["node", os.path.join(os.path.dirname(__file__), "helper_check.js")])

def test_driver_option():
    driver = "const fs = require('fs');"
    subprocess.run(["node", "-e", driver, str(SCRIPT)])
''',
    })
    monkeypatch.chdir(root)
    assert main(['init']) == 0
    assert main(['scan']) == 0
    capsys.readouterr()
    with sqlite3.connect(root / '.cbi/model.db') as conn:
        links = set(conn.execute("SELECT s.name, d.path FROM edges e JOIN nodes s ON s.id=e.src "
                                 "JOIN nodes d ON d.id=e.dst WHERE e.kind='tests'"))
        assert ('test_parent_slash', 'tests/layout_check.js') in links
        assert ('test_with_name', 'tests/nav_check.js') in links
        assert ('test_os_path_join', 'tests/helper_check.js') in links
        assert ('test_driver_option', 'src/viewer/editor.js') in links
        diags = conn.execute("SELECT detail FROM diagnostics WHERE kind='unsupported_test_mechanism'").fetchall()
        assert not any('test_views.py' in d for (d,) in diags)
        unmatched = conn.execute("SELECT node_id FROM diagnostics WHERE kind='unmatched_test'").fetchall()
        assert unmatched == []

"""SQL contracts bind only files selected by explicit literal paths and globs."""

import sqlite3

from cbi.cli import main


def test_schema_and_migration_globs(make_repo, monkeypatch, capsys):
    root = make_repo({
        "db/migrations/001_tables.sql": "CREATE TABLE items (id INT);\n",
        "db/migrations/002_index.sql": "CREATE INDEX item_id ON items(id);\n",
        "db/migrations/archive/old.sql": "SELECT 1;\n",
        "db/unrelated.sql": "SELECT 2;\n",
        "tests/test_contract.py": '''from pathlib import Path

def test_migrations():
    root = Path(__file__).parents[1]
    migrations = root / "db" / "migrations"
    for script in migrations.glob("*.sql"):
        assert "items" in script.read_text()

def test_recursive():
    root = Path(__file__).parents[1]
    assert list((root / "db" / "migrations").rglob("*.sql"))

def test_dynamic(pattern):
    root = Path(__file__).parents[1]
    assert list((root / "db").glob(pattern))
''',
    })
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    assert main(["scan"]) == 0
    capsys.readouterr()
    conn = sqlite3.connect(root / ".cbi/model.db")
    bindings = {(src.split("#")[-1], dst.split(":", 2)[-1]) for src, dst in conn.execute(
        "SELECT src, dst FROM edges WHERE kind = 'tests'")}
    assert {dst for src, dst in bindings if src == "test_migrations"} == {
        "db/migrations/001_tables.sql", "db/migrations/002_index.sql",
    }
    assert {dst for src, dst in bindings if src == "test_recursive"} == {
        "db/migrations/001_tables.sql", "db/migrations/002_index.sql", "db/migrations/archive/old.sql",
    }
    assert not any(src == "test_dynamic" for src, _ in bindings)
    diagnostics = conn.execute("SELECT detail FROM diagnostics WHERE kind = 'unsupported_test_mechanism'").fetchall()
    assert any("file_glob" in detail and "dynamic" in detail for detail, in diagnostics)


def test_relative_globs_require_one_possible_directory_in_tests_and_fixtures(make_repo, monkeypatch):
    root = make_repo({
        "migrations/001_root.sql": "CREATE TABLE root_records (id INT);\n",
        "tests/migrations/002_test.sql": "CREATE TABLE test_records (id INT);\n",
        "support/migrations/003_support.sql": "CREATE TABLE support_records (id INT);\n",
        "unique/001_only.sql": "SELECT 1;\n",
        "support/__init__.py": "",
        "support/contracts.py": "import pytest\nfrom pathlib import Path\n@pytest.fixture\ndef migration_contract():\n    return list(Path('migrations').glob('*.sql'))\n",
        "tests/conftest.py": "pytest_plugins = ['support.contracts']\n",
        "tests/test_contract.py": "from pathlib import Path\ndef test_unanchored():\n    assert list(Path('migrations').glob('*.sql'))\ndef test_fixture(migration_contract): assert migration_contract\ndef test_anchored():\n    root = Path(__file__).parents[1]\n    assert list((root / 'migrations').glob('*.sql'))\ndef test_unique():\n    assert list(Path('unique').glob('*.sql'))\n",
    })
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    conn = sqlite3.connect(root / ".cbi/model.db")
    bindings = {(src.split("#")[-1], dst.split(":", 2)[-1]) for src, dst in conn.execute(
        "SELECT src, dst FROM edges WHERE kind = 'tests'")}
    assert not any(src in {"test_unanchored", "test_fixture"} for src, _dst in bindings)
    assert {dst for src, dst in bindings if src == "test_anchored"} == {"migrations/001_root.sql"}
    assert {dst for src, dst in bindings if src == "test_unique"} == {"unique/001_only.sql"}
    diagnostics = conn.execute(
        "SELECT node_id, detail FROM diagnostics WHERE kind = 'unsupported_test_mechanism'").fetchall()
    for path in ("tests/test_contract.py", "support/contracts.py"):
        assert any(nid.endswith(path) and "file_glob" in detail and "multiple possible working directories" in detail
                   for nid, detail in diagnostics)

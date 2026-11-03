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

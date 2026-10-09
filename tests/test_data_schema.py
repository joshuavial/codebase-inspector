import json
import sqlite3
from pathlib import Path

from cbi import data
from cbi.cli import main


FIXTURE = Path(__file__).parent / "fixtures" / "data" / "sql"


def _repo(make_repo):
    files = {path.relative_to(FIXTURE).as_posix(): path.read_text()
             for path in FIXTURE.rglob("*") if path.is_file()}
    return make_repo(files, name="data-sql")


def test_sql_parser_handles_keys_quotes_defaults_and_alter():
    first = data.parse_sql((FIXTURE / "migrations/001_create.sql").read_text(), "migrations/001_create.sql")
    second = data.parse_sql((FIXTURE / "migrations/002_foreign_key.sql").read_text(), "migrations/002_foreign_key.sql")
    assert [table["name"] for table in first] == ["accounts", "public.invoices"]
    accounts = first[0]
    assert accounts["columns"][0]["primary_key"] is True
    assert accounts["columns"][1]["unique"] is True
    assert accounts["columns"][2]["default"] == "'active'"
    invoices = first[1]
    assert invoices["columns"][2]["type"] == "NUMERIC(10, 2)"
    assert invoices["constraints"][0] == {"kind": "primary", "columns": ["id"]}
    assert second[0]["constraints"][0]["table"] == "accounts"


def test_scan_stores_layout_free_stable_schema(make_repo, monkeypatch, capsys):
    root = _repo(make_repo)
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    capsys.readouterr()
    conn = sqlite3.connect(root / ".cbi" / "model.db")
    tables = list(conn.execute("SELECT id, name, attrs FROM nodes WHERE kind = 'table' ORDER BY name"))
    assert [(row[0], row[1]) for row in tables] == [
        ("local:data-sql:table:accounts", "accounts"),
        ("local:data-sql:table:public.invoices", "public.invoices")]
    columns = {(name, parent): json.loads(attrs) for name, parent, attrs in conn.execute(
        "SELECT name, parent_id, attrs FROM nodes WHERE kind = 'column' ORDER BY parent_id, name")}
    account = columns[("id", "local:data-sql:table:accounts")]
    assert account["primary_key"] is True and account["nullable"] is False
    invoice_account = columns[("account_id", "local:data-sql:table:public.invoices")]
    assert invoice_account["type"] == "BIGINT" and len(invoice_account["sources"]) == 1
    fks = list(conn.execute("SELECT src, dst, attrs FROM edges WHERE kind = 'foreign_key' ORDER BY ordinal"))
    assert len(fks) == 2
    assert {row[0] for row in fks} == {"local:data-sql:table:public.invoices#account_id"}
    assert {row[1] for row in fks} == {"local:data-sql:table:accounts#id"}
    for attrs, in conn.execute("SELECT attrs FROM nodes WHERE kind IN ('table', 'column')"):
        assert not (data.LAYOUT_KEYS & set(json.loads(attrs)))
    before = list(conn.execute("SELECT id FROM nodes WHERE kind IN ('table', 'column') ORDER BY id"))
    conn.close()

    migration = root / "migrations/001_create.sql"
    migration.write_text(migration.read_text() + "\n-- rescanned\n")
    assert main(["scan"]) == 0
    capsys.readouterr()
    conn = sqlite3.connect(root / ".cbi" / "model.db")
    after = list(conn.execute("SELECT id FROM nodes WHERE kind IN ('table', 'column') ORDER BY id"))
    assert after == before

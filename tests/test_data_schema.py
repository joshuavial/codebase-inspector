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


def _fixture_repo(make_repo, framework):
    fixture = Path(__file__).parent / "fixtures" / "data" / framework
    files = {path.relative_to(fixture).as_posix(): path.read_text()
             for path in fixture.rglob("*") if path.is_file()}
    return make_repo(files, name=framework)


def _schema(root):
    conn = sqlite3.connect(root / ".cbi" / "model.db")
    tables = {}
    for tid, name, attrs in conn.execute("SELECT id, name, attrs FROM nodes WHERE kind = 'table'"):
        tables[name] = {"id": tid, "attrs": json.loads(attrs), "columns": {}}
    for parent, name, attrs in conn.execute("SELECT parent_id, name, attrs FROM nodes WHERE kind = 'column'"):
        table = next(row for row in tables.values() if row["id"] == parent)
        table["columns"][name] = json.loads(attrs)
    fks = {(src, dst) for src, dst in conn.execute("SELECT src, dst FROM edges WHERE kind = 'foreign_key'")}
    return tables, fks


def test_sqlalchemy_schema(make_repo, monkeypatch, capsys):
    root = _fixture_repo(make_repo, "sqlalchemy")
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    capsys.readouterr()
    tables, fks = _schema(root)
    assert set(tables) == {"accounts", "invoices"}
    assert tables["accounts"]["columns"]["id"]["primary_key"] is True
    assert tables["accounts"]["columns"]["email"]["nullable"] is False
    assert tables["accounts"]["attrs"]["models"] == ["Account"]
    assert any(src.endswith("invoices#account_id") and dst.endswith("accounts#id") for src, dst in fks)


def test_django_schema(make_repo, monkeypatch, capsys):
    root = _fixture_repo(make_repo, "django")
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    capsys.readouterr()
    tables, fks = _schema(root)
    assert set(tables) == {"customer_accounts", "invoice"}
    assert tables["customer_accounts"]["columns"]["id"]["primary_key"] is True
    assert tables["invoice"]["columns"]["total"]["nullable"] is True
    assert any(src.endswith("invoice#account_id") and dst.endswith("customer_accounts#id") for src, dst in fks)


def test_prisma_schema(make_repo, monkeypatch, capsys):
    root = _fixture_repo(make_repo, "prisma")
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    capsys.readouterr()
    tables, fks = _schema(root)
    assert set(tables) == {"accounts", "invoices"}
    assert tables["invoices"]["columns"]["account_id"]["type"] == "Int"
    assert tables["invoices"]["columns"]["note"]["nullable"] is True
    assert any(src.endswith("invoices#account_id") and dst.endswith("accounts#id") for src, dst in fks)


def test_typeorm_schema(make_repo, monkeypatch, capsys):
    root = _fixture_repo(make_repo, "typeorm")
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    capsys.readouterr()
    tables, fks = _schema(root)
    assert set(tables) == {"accounts", "invoices"}
    assert tables["accounts"]["columns"]["id"]["primary_key"] is True
    assert tables["invoices"]["columns"]["note"]["nullable"] is True
    assert any(src.endswith("invoices#account_id") and dst.endswith("accounts#id") for src, dst in fks)


def test_ef_core_schema(make_repo, monkeypatch, capsys):
    root = _fixture_repo(make_repo, "efcore")
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    capsys.readouterr()
    tables, fks = _schema(root)
    assert set(tables) == {"accounts", "Invoices"}
    assert tables["accounts"]["columns"]["Id"]["primary_key"] is True
    assert tables["Invoices"]["columns"]["Note"]["nullable"] is True
    assert any(src.endswith("invoices#accountid") and dst.endswith("accounts#id") for src, dst in fks)


def test_migration_and_model_declarations_merge(make_repo, monkeypatch, capsys):
    files = {
        "migrations/001.sql": "CREATE TABLE accounts (id INTEGER PRIMARY KEY);\n",
        "models.py": (Path(__file__).parent / "fixtures/data/sqlalchemy/models.py").read_text(),
    }
    root = make_repo(files, name="merged-data")
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    capsys.readouterr()
    tables, _fks = _schema(root)
    assert list(name for name in tables if name == "accounts") == ["accounts"]
    assert {source["kind"] for source in tables["accounts"]["attrs"]["sources"]} == {"sql", "sqlalchemy"}


def test_sql_and_orm_table_uses_attach_to_functions(make_repo, monkeypatch, capsys):
    root = _fixture_repo(make_repo, "usage")
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    capsys.readouterr()
    conn = sqlite3.connect(root / ".cbi" / "model.db")
    rows = [(kind, src_name, table_name, json.loads(attrs)) for kind, src_name, table_name, attrs in conn.execute(
        "SELECT e.kind, s.name, t.name, e.attrs FROM edges e "
        "JOIN nodes s ON s.id = e.src JOIN nodes t ON t.id = e.dst "
        "WHERE e.kind IN ('reads_table', 'writes_table') ORDER BY e.kind, s.name, t.name")]
    triples = {(kind, source, table) for kind, source, table, _attrs in rows}
    assert ("reads_table", "report", "accounts") in triples
    assert ("reads_table", "report", "invoices") in triples
    assert ("writes_table", "change", "accounts") in triples
    assert ("writes_table", "change", "invoices") in triples
    assert ("reads_table", "prismaReads", "invoices") in triples
    assert ("writes_table", "prismaWrites", "accounts") in triples
    assert ("reads_table", "typeorm", "invoices") in triples
    assert ("writes_table", "typeorm", "invoices") in triples
    assert ("reads_table", "List", "invoices") in triples
    assert ("writes_table", "Add", "accounts") in triples
    assert ("reads_table", "supabaseReads", "accounts") in triples
    assert ("writes_table", "supabaseWrites", "invoices") in triples
    assert not any(source == "unrelated" for _kind, source, _table, _attrs in rows)
    report_invoices = next(attrs for kind, source, table, attrs in rows
                           if kind == "reads_table" and source == "report" and table == "invoices")
    assert {location["via"] for location in report_invoices["locations"]} == {"orm", "sql"}

    before = conn.execute(
        "SELECT e.weight FROM edges e JOIN nodes s ON s.id = e.src JOIN nodes t ON t.id = e.dst "
        "WHERE e.kind = 'writes_table' AND s.name = 'change' AND t.name = 'invoices'").fetchone()[0]
    conn.close()
    operation = root / "operations.py"
    operation.write_text(operation.read_text().replace("session.add(Invoice())", "pass"))
    assert main(["scan"]) == 0
    capsys.readouterr()
    conn = sqlite3.connect(root / ".cbi" / "model.db")
    after = conn.execute(
        "SELECT e.weight FROM edges e JOIN nodes s ON s.id = e.src JOIN nodes t ON t.id = e.dst "
        "WHERE e.kind = 'writes_table' AND s.name = 'change' AND t.name = 'invoices'").fetchone()[0]
    assert after == before - 1

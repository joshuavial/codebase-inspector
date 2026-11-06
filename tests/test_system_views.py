import json
import sqlite3
from pathlib import Path

from cbi import build, system_views
from cbi.cli import main


FIXTURE = Path(__file__).parent / "fixtures" / "data" / "system"


def _repo(make_repo):
    return make_repo({path.relative_to(FIXTURE).as_posix(): path.read_text()
                      for path in FIXTURE.rglob("*") if path.is_file()}, name="system-views")


def _scan(make_repo, monkeypatch, capsys):
    root = _repo(make_repo)
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    capsys.readouterr()
    return root, sqlite3.connect(root / ".cbi/model.db")


def test_database_payload_is_sorted_and_layout_free(make_repo, monkeypatch, capsys):
    _root, conn = _scan(make_repo, monkeypatch, capsys)
    payload = system_views.database_view(conn)
    assert [table["name"] for table in payload["tables"]] == ["accounts"]
    table = payload["tables"][0]
    assert [column["name"] for column in table["columns"]] == ["id", "email"]
    assert table["columns"][0]["primaryKey"] is True
    assert [(row["name"], row["file"]) for row in table["reads"]] == [("list_accounts", "service.py")]
    encoded = json.dumps(payload)
    assert not any(f'"{key}"' in encoded for key in ("x", "y", "width", "height", "position", "route"))


def test_endpoint_payload_reuses_routes_calls_summaries_and_table_uses(make_repo, monkeypatch, capsys):
    _root, conn = _scan(make_repo, monkeypatch, capsys)
    conn.execute("UPDATE nodes SET summary = 'Lists customer accounts. It includes active rows.' WHERE name = 'accounts'")
    payload = system_views.endpoint_view(conn)
    assert [(row["method"], row["path"]) for row in payload["endpoints"]] == [
        ("GET", "/api/accounts"), ("POST", "/api/accounts")]
    get = payload["endpoints"][0]
    assert get["note"] == "Lists customer accounts."
    assert get["handler"]["name"] == "accounts"
    assert [row["name"] for row in get["callers"]] == ["loadAccounts"]
    assert any(row["name"] == "list_accounts" and row["via"] == "call" for row in get["code"])
    assert get["tables"] == [{
        "id": "local:system-views:table:accounts", "name": "accounts", "mode": "read",
        "direct": False, "via": "local:system-views:service.py#list_accounts", "depth": 1}]
    post = payload["endpoints"][1]
    assert post["callers"] == []
    assert post["note"] == "Create one customer account."


def test_build_writes_system_view_scripts(make_repo, monkeypatch, capsys):
    root, conn = _scan(make_repo, monkeypatch, capsys)
    viewer = root / ".cbi/viewer"
    build.build(conn, viewer, root)
    database = (viewer / "data/database.js").read_text()
    endpoints = (viewer / "data/endpoints.js").read_text()
    assert database.startswith('cbiLoad("database", {"tables":')
    assert endpoints.startswith('cbiLoad("endpoints", {"endpoints":')
    assert '"path":"/api/accounts"' in endpoints


def test_cli_endpoints_text_and_json(make_repo, monkeypatch, capsys):
    _root, _conn = _scan(make_repo, monkeypatch, capsys)

    # Default text output
    assert main(["endpoints"]) == 0
    out = capsys.readouterr().out
    assert "GET    /api/accounts" in out
    assert "POST   /api/accounts" in out
    assert "handler: accounts" in out
    assert "callers: loadAccounts" in out
    assert "tables:  accounts (read)" in out

    # Structured JSON output
    assert main(["endpoints", "--json"]) == 0
    json_out = capsys.readouterr().out
    data = json.loads(json_out)
    assert "endpoints" in data
    assert len(data["endpoints"]) == 2
    paths = [(ep["method"], ep["path"]) for ep in data["endpoints"]]
    assert ("GET", "/api/accounts") in paths
    assert ("POST", "/api/accounts") in paths


def test_cli_endpoints_filters(make_repo, monkeypatch, capsys):
    _root, _conn = _scan(make_repo, monkeypatch, capsys)

    # Filter by method
    assert main(["endpoints", "--method", "get", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert len(data["endpoints"]) == 1
    assert data["endpoints"][0]["method"] == "GET"

    assert main(["endpoints", "--method", "POST", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert len(data["endpoints"]) == 1
    assert data["endpoints"][0]["method"] == "POST"

    # Filter by path
    assert main(["endpoints", "--path", "accounts", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert len(data["endpoints"]) == 2

    # Filter by handler
    assert main(["endpoints", "--handler", "create_account", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert len(data["endpoints"]) == 1
    assert data["endpoints"][0]["handler"]["name"] == "create_account"

    # Filter by table
    assert main(["endpoints", "--table", "accounts", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert len(data["endpoints"]) == 1
    assert data["endpoints"][0]["method"] == "GET"

    # Filter with no matches
    assert main(["endpoints", "--table", "nonexistent"]) == 0
    assert "no endpoints found" in capsys.readouterr().out

    assert main(["endpoints", "--table", "nonexistent", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["endpoints"] == []


def test_cli_tables_text_and_json(make_repo, monkeypatch, capsys):
    _root, _conn = _scan(make_repo, monkeypatch, capsys)

    # Default text output
    assert main(["tables"]) == 0
    out = capsys.readouterr().out
    assert "table accounts (2 columns)" in out
    assert "id" in out
    assert "email" in out
    assert "PRIMARY KEY" in out
    assert "NOT NULL" in out
    assert "reads:   list_accounts" in out

    # JSON output
    assert main(["tables", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert "tables" in data
    assert "relationships" in data
    assert len(data["tables"]) == 1
    assert data["tables"][0]["name"] == "accounts"


def test_cli_tables_filters(make_repo, monkeypatch, capsys):
    _root, _conn = _scan(make_repo, monkeypatch, capsys)

    # Filter matching table
    assert main(["tables", "--table", "accounts", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert len(data["tables"]) == 1
    assert data["tables"][0]["name"] == "accounts"

    # Filter with no matches
    assert main(["tables", "--table", "nonexistent"]) == 0
    assert "no tables found" in capsys.readouterr().out

    assert main(["tables", "--table", "nonexistent", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["tables"] == []
    assert data["relationships"] == []


def test_filter_and_format_units():
    # Unit tests for formatters and filters
    assert system_views.format_endpoints_text([]) == "no endpoints found"
    assert system_views.format_tables_text([]) == "no tables found"

    dummy_tables = [
        {
            "id": "t1",
            "name": "users",
            "columns": [
                {"id": "c_id", "name": "id", "type": "INTEGER", "primaryKey": True},
                {"id": "c_name", "name": "name", "type": "TEXT", "nullable": False},
            ],
            "foreignKeys": [],
            "referencedBy": [
                {"from": "t2", "column": "c_user", "to": "t1", "targetColumn": "c_id"}
            ],
            "reads": [{"name": "get_user", "file": "users.py", "line": 5}],
            "writes": [{"name": "save_user", "file": "users.py", "line": 20}],
        },
        {
            "id": "t2",
            "name": "orders",
            "columns": [
                {"id": "c_order_id", "name": "id", "type": "INTEGER", "primaryKey": True},
                {"id": "c_user", "name": "user_id", "type": "INTEGER", "nullable": False},
            ],
            "foreignKeys": [
                {"from": "t2", "column": "c_user", "to": "t1", "targetColumn": "c_id"}
            ],
            "referencedBy": [],
            "reads": [],
            "writes": [],
        },
    ]
    dummy_rels = [{"from": "t2", "column": "c_user", "to": "t1", "targetColumn": "c_id"}]

    text = system_views.format_tables_text(dummy_tables, dummy_rels)
    assert "table users (2 columns)" in text
    assert "table orders (2 columns)" in text
    assert "foreign keys:" in text
    assert "referenced by:" in text
    assert "reads:   get_user (users.py:5)" in text
    assert "writes:  save_user (users.py:20)" in text

    matched_t, matched_r = system_views.filter_tables(dummy_tables, dummy_rels, table="users")
    assert len(matched_t) == 1
    assert matched_t[0]["name"] == "users"
    assert len(matched_r) == 1


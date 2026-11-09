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


def test_format_tables_text_preserves_cased_fk_names_when_filtered():
    all_tables = [
        {
            "id": "local:repo:table:accounts",
            "name": "Accounts",
            "columns": [{"id": "local:repo:table:accounts#AccountID", "name": "AccountID", "type": "INTEGER", "primaryKey": True}],
            "foreignKeys": [],
            "referencedBy": [{"from": "local:repo:table:orders", "column": "local:repo:table:orders#AccountID", "to": "local:repo:table:accounts", "targetColumn": "local:repo:table:accounts#AccountID"}],
        },
        {
            "id": "local:repo:table:orders",
            "name": "Orders",
            "columns": [
                {"id": "local:repo:table:orders#OrderID", "name": "OrderID", "type": "INTEGER", "primaryKey": True},
                {"id": "local:repo:table:orders#AccountID", "name": "AccountID", "type": "INTEGER"},
            ],
            "foreignKeys": [{"from": "local:repo:table:orders", "column": "local:repo:table:orders#AccountID", "to": "local:repo:table:accounts", "targetColumn": "local:repo:table:accounts#AccountID"}],
            "referencedBy": [],
        },
    ]
    # Filter only Orders
    filtered, rels = system_views.filter_tables(all_tables, table="Orders")
    text = system_views.format_tables_text(filtered, rels, all_tables=all_tables)
    assert "AccountID -> Accounts(AccountID)" in text

    # Filter only Accounts (referenced by)
    filtered_acc, rels_acc = system_views.filter_tables(all_tables, table="Accounts")
    text_acc = system_views.format_tables_text(filtered_acc, rels_acc, all_tables=all_tables)
    assert "Orders(AccountID) -> AccountID" in text_acc


def test_cli_endpoints_formats(make_repo, monkeypatch, capsys):
    _root, _conn = _scan(make_repo, monkeypatch, capsys)

    # Markdown format
    assert main(["endpoints", "--format", "markdown"]) == 0
    out = capsys.readouterr().out
    assert "| Method | Route | Handler | Callers | Tables |" in out
    assert "| GET | /api/accounts | accounts" in out
    assert "loadAccounts" in out
    assert "accounts (read)" in out
    assert "| POST | /api/accounts | create_account" in out

    # JSON format via --format json
    assert main(["endpoints", "--format", "json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert len(data["endpoints"]) == 2
    paths = [(ep["method"], ep["path"]) for ep in data["endpoints"]]
    assert ("GET", "/api/accounts") in paths


def test_cli_tables_formats(make_repo, monkeypatch, capsys):
    _root, _conn = _scan(make_repo, monkeypatch, capsys)

    # Markdown format
    assert main(["tables", "--format", "markdown"]) == 0
    md_out = capsys.readouterr().out
    assert "## Tables" in md_out
    assert "| Table | Columns | Primary Key |" in md_out
    assert "| accounts | 2 | id |" in md_out
    assert "### `accounts`" in md_out
    assert "| Column | Type | Primary Key | Nullable | Default |" in md_out
    assert "| id | INTEGER | Yes |" in md_out
    assert "| email | TEXT | No |" in md_out
    assert "- **Reads:** `list_accounts`" in md_out

    # Mermaid format
    assert main(["tables", "--format", "mermaid"]) == 0
    mermaid_out = capsys.readouterr().out
    assert mermaid_out.startswith("erDiagram")
    assert "accounts {" in mermaid_out
    assert "INTEGER id PK" in mermaid_out
    assert "TEXT email" in mermaid_out
    assert system_views.valid_mermaid_er(mermaid_out)

    # JSON format via --format json
    assert main(["tables", "--format", "json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert len(data["tables"]) == 1
    assert data["tables"][0]["name"] == "accounts"


def test_format_endpoints_markdown_unit():
    assert system_views.format_endpoints_markdown([]) == "no endpoints found"

    sample = [
        {
            "method": "GET",
            "path": "/api/users",
            "handler": {"name": "get_users", "file": "api.py", "line": 15},
            "callers": [{"name": "fetchUsers", "file": "client.js", "line": 8}],
            "tables": [{"name": "users", "mode": "read"}],
        },
        {
            "method": "POST",
            "path": "/api/users",
            "handler": {"name": "create_user"},
            "callers": [],
            "tables": [{"name": "users", "mode": "write"}, {"name": "logs", "mode": "write"}],
        },
    ]
    md = system_views.format_endpoints_markdown(sample)
    assert "| Method | Route | Handler | Callers | Tables |" in md
    assert "| GET | /api/users | get_users (api.py:15) | fetchUsers (client.js:8) | users (read) |" in md
    assert "| POST | /api/users | create_user | - | users (write), logs (write) |" in md


def test_format_tables_markdown_and_mermaid_units():
    assert system_views.format_tables_markdown([]) == "no tables found"
    assert system_views.format_tables_mermaid([]) == "erDiagram\n"

    dummy_tables = [
        {
            "id": "t1",
            "name": "users",
            "columns": [
                {"id": "c_id", "name": "id", "type": "INTEGER", "primaryKey": True},
                {"id": "c_email", "name": "email", "type": "VARCHAR(255)", "unique": True},
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

    # Markdown format
    md = system_views.format_tables_markdown(dummy_tables, dummy_rels)
    assert "## Tables" in md
    assert "| Table | Columns | Primary Key |" in md
    assert "| users | 2 | id |" in md
    assert "| orders | 2 | id |" in md
    assert "### `users`" in md
    assert "### `orders`" in md
    assert "## Relationships" in md
    assert "| From Table | Column | To Table | Target Column |" in md
    assert "| orders | user_id | users | id |" in md
    assert "- **Reads:** `get_user` (users.py:5)" in md
    assert "- **Writes:** `save_user` (users.py:20)" in md

    # Mermaid format
    mermaid = system_views.format_tables_mermaid(dummy_tables, dummy_rels)
    assert mermaid.startswith("erDiagram")
    assert 'users ||--o{ orders : "user_id"' in mermaid
    assert "users {" in mermaid
    assert "INTEGER id PK" in mermaid
    assert "VARCHAR(255) email UK" in mermaid
    assert "orders {" in mermaid
    assert "INTEGER user_id FK" in mermaid
    assert system_views.valid_mermaid_er(mermaid)


def test_valid_mermaid_er_validator():
    assert system_views.valid_mermaid_er("erDiagram\n")
    assert system_views.valid_mermaid_er('erDiagram\n    users ||--o{ orders : "user_id"\n    users {\n        int id PK\n    }\n')
    assert not system_views.valid_mermaid_er("flowchart LR\n  a --> b")
    assert not system_views.valid_mermaid_er("erDiagram\n    users {\n        broken line here with too many words and bad key\n    }\n")



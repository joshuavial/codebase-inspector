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

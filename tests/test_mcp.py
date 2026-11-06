"""Tests for the native stdio MCP server."""

import io
import json
import sqlite3
from pathlib import Path
import pytest

from cbi import prime
from cbi.cli import main
from cbi.mcp import MCPServer, PROTOCOL_VERSION, SERVER_NAME, SERVER_VERSION, read_message, write_message

FILES = {
    "src/shapes/circle.ts": """\
/** A round shape. */
export class Circle {
  constructor(readonly radius: number) {}
  area(): number { return Math.PI * this.radius ** 2; }
}

export function makeCircle(r: number) { return new Circle(r); }
""",
    "src/shapes/circle.test.ts": """\
import { test } from "node:test";
import { makeCircle } from "./circle";

test("measures the area", () => {
  makeCircle(2).area();
});
""",
    "src/other/area.ts": "export function area() { return 0; }\n",
}

WS = "local:repo"
CIRCLE = f"{WS}:src/shapes/circle.ts"
TEST_CASE = f"{WS}:src/shapes/circle.test.ts#measures the area"


@pytest.fixture
def repo(make_repo, monkeypatch):
    root = make_repo(FILES)
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    conn = sqlite3.connect(root / ".cbi" / "model.db")
    with conn:
        conn.execute(
            "INSERT INTO edges (src, dst, kind, source) VALUES (?, ?, 'tests', 'coverage')",
            (TEST_CASE, f"{CIRCLE}#Circle.area"),
        )
    conn.close()
    return root


def test_initialize():
    server = MCPServer()
    req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1.0"},
        },
    }
    resp = server.handle_request(req)
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == 1
    result = resp["result"]
    assert result["protocolVersion"] == PROTOCOL_VERSION
    assert result["capabilities"] == {"tools": {}}
    assert result["serverInfo"] == {"name": SERVER_NAME, "version": SERVER_VERSION}


def test_initialized_notification():
    server = MCPServer()
    # Notification has no id: server returns None (no response emitted)
    req = {
        "jsonrpc": "2.0",
        "method": "notifications/initialized",
        "params": {},
    }
    assert server.handle_request(req) is None

    # Alternative form: "initialized"
    assert server.handle_request({"jsonrpc": "2.0", "method": "initialized"}) is None

    # If sent with an id, returns empty result
    resp = server.handle_request({"jsonrpc": "2.0", "id": 42, "method": "notifications/initialized"})
    assert resp == {"jsonrpc": "2.0", "id": 42, "result": {}}


def test_ping():
    server = MCPServer()
    req = {"jsonrpc": "2.0", "id": 99, "method": "ping"}
    resp = server.handle_request(req)
    assert resp == {"jsonrpc": "2.0", "id": 99, "result": {}}


def test_tools_list():
    server = MCPServer()
    req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
    resp = server.handle_request(req)
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == 2
    tools = resp["result"]["tools"]
    tool_names = {t["name"] for t in tools}
    expected = {
        "cbi_scan",
        "cbi_status", "cbi_context", "cbi_show", "cbi_tests_for", "cbi_search", "cbi_hotspots",
        "cbi_diff", "cbi_tasks", "cbi_submit", "cbi_query", "cbi_concepts",
        "cbi_cycles", "cbi_orphans", "cbi_deps", "cbi_endpoints", "cbi_tables",
        "cbi_history", "cbi_review", "cbi_check", "cbi_worktrees",
        "cbi_prime", "cbi_task", "cbi_ingest", "cbi_init",
    }
    assert len(expected) == 25
    assert len(tools) == 25
    assert expected == tool_names

    for tool in tools:
        assert "description" in tool
        assert "inputSchema" in tool
        assert tool["inputSchema"]["type"] == "object"


def test_tool_scan(repo):
    server = MCPServer(root=repo)

    # 1. Text format on current repo (default)
    req = {
        "jsonrpc": "2.0",
        "id": 100,
        "method": "tools/call",
        "params": {"name": "cbi_scan", "arguments": {}},
    }
    resp = server.handle_request(req)
    assert resp["id"] == 100
    assert not resp["result"]["isError"]
    text = resp["result"]["content"][0]["text"]
    assert "no changes since the last scan" in text or "scanned" in text
    assert "judgement tasks" in text

    # Explicit text format
    res_text_exp = server.execute_tool("cbi_scan", {"format": "text"})
    assert not res_text_exp["isError"]
    assert "judgement tasks" in res_text_exp["content"][0]["text"]

    # 2. JSON format on current repo
    res_json = server.execute_tool("cbi_scan", {"format": "json"})
    assert not res_json["isError"]
    data = json.loads(res_json["content"][0]["text"])
    assert data["ref"] is None
    assert isinstance(data["shortcut"], bool)
    assert isinstance(data["counts"], dict)
    assert "source file" in data["counts"]
    assert "open_tasks" in data
    assert "blocked_tasks" in data

    # 3. Git ref scan (HEAD) - text format
    res_ref_text = server.execute_tool("cbi_scan", {"ref": "HEAD", "format": "text"})
    assert not res_ref_text["isError"]
    ref_text = res_ref_text["content"][0]["text"]
    assert "scanned" in ref_text or "reused" in ref_text
    assert "judgement tasks" in ref_text

    # 4. Git ref scan (HEAD) - JSON format
    res_ref_json = server.execute_tool("cbi_scan", {"ref": "HEAD", "format": "json"})
    assert not res_ref_json["isError"]
    data_ref = json.loads(res_ref_json["content"][0]["text"])
    assert data_ref["ref"] is not None
    assert len(data_ref["ref"]) == 40
    assert isinstance(data_ref["shortcut"], bool)
    assert isinstance(data_ref["counts"], dict)
    assert "open_tasks" in data_ref
    assert "blocked_tasks" in data_ref

    # 5. Invalid git ref returns clean error
    res_bad = server.execute_tool("cbi_scan", {"ref": "nonexistent-branch-ref"})
    assert res_bad["isError"]
    assert "unknown revision" in res_bad["content"][0]["text"] or "Error:" in res_bad["content"][0]["text"]


def test_tools_call_status(repo):
    server = MCPServer(root=repo)

    # Text format
    req = {
        "jsonrpc": "2.0",
        "id": 10,
        "method": "tools/call",
        "params": {"name": "cbi_status", "arguments": {}},
    }
    resp = server.handle_request(req)
    assert resp["id"] == 10
    assert not resp["result"]["isError"]
    content = resp["result"]["content"]
    assert len(content) == 1
    assert content[0]["type"] == "text"
    assert "nodes:" in content[0]["text"]

    # JSON format
    req_json = {
        "jsonrpc": "2.0",
        "id": 11,
        "method": "tools/call",
        "params": {"name": "cbi_status", "arguments": {"format": "json"}},
    }
    resp_json = server.handle_request(req_json)
    assert not resp_json["result"]["isError"]
    data = json.loads(resp_json["result"]["content"][0]["text"])
    assert "nodes" in data
    assert "scanned_at" in data


def test_tools_call_context(repo):
    server = MCPServer(root=repo)

    # Valid node
    req = {
        "jsonrpc": "2.0",
        "id": 20,
        "method": "tools/call",
        "params": {"name": "cbi_context", "arguments": {"node": "src/shapes/circle.ts"}},
    }
    resp = server.handle_request(req)
    assert resp["id"] == 20
    assert not resp["result"]["isError"]
    text = resp["result"]["content"][0]["text"]
    assert "# circle.ts" in text or "Circle" in text
    assert "Project:" in text

    # Omitted node argument returns system architecture overview
    req_missing = {
        "jsonrpc": "2.0",
        "id": 21,
        "method": "tools/call",
        "params": {"name": "cbi_context", "arguments": {}},
    }
    resp_missing = server.handle_request(req_missing)
    assert not resp_missing["result"]["isError"]
    text_sys = resp_missing["result"]["content"][0]["text"]
    assert "Architecture Overview" in text_sys
    assert "Project:" in text_sys

    # node='system' returns system architecture overview
    req_sys = {
        "jsonrpc": "2.0",
        "id": 23,
        "method": "tools/call",
        "params": {"name": "cbi_context", "arguments": {"node": "system"}},
    }
    resp_sys = server.handle_request(req_sys)
    assert not resp_sys["result"]["isError"]
    text_sys2 = resp_sys["result"]["content"][0]["text"]
    assert "Architecture Overview" in text_sys2

    # Nonexistent node
    req_unknown = {
        "jsonrpc": "2.0",
        "id": 22,
        "method": "tools/call",
        "params": {"name": "cbi_context", "arguments": {"node": "nonexistent/file.ts"}},
    }
    resp_unknown = server.handle_request(req_unknown)
    assert resp_unknown["result"]["isError"]
    assert "No node matches" in resp_unknown["result"]["content"][0]["text"]


def test_tools_call_show(repo):
    server = MCPServer(root=repo)

    # 1. Text format (default)
    req_text = {
        "jsonrpc": "2.0",
        "id": 25,
        "method": "tools/call",
        "params": {"name": "cbi_show", "arguments": {"node": "src/shapes/circle.ts"}},
    }
    resp_text = server.handle_request(req_text)
    assert resp_text["id"] == 25
    assert not resp_text["result"]["isError"]
    text = resp_text["result"]["content"][0]["text"]
    assert "src/shapes/circle.ts" in text
    assert "children" in text
    assert "Circle" in text

    # Explicit format: text
    res_text_explicit = server.execute_tool("cbi_show", {"node": "src/shapes/circle.ts", "format": "text"})
    assert not res_text_explicit["isError"]
    assert "src/shapes/circle.ts" in res_text_explicit["content"][0]["text"]

    # 2. JSON format
    req_json = {
        "jsonrpc": "2.0",
        "id": 26,
        "method": "tools/call",
        "params": {"name": "cbi_show", "arguments": {"node": "src/shapes/circle.ts", "format": "json"}},
    }
    resp_json = server.handle_request(req_json)
    assert not resp_json["result"]["isError"]
    parsed = json.loads(resp_json["result"]["content"][0]["text"])
    assert parsed["path"] == "src/shapes/circle.ts"
    assert parsed["kind"] == "file"
    assert isinstance(parsed["children"], list)
    assert any(c["name"] == "Circle" for c in parsed["children"])
    assert "outgoing" in parsed
    assert "incoming" in parsed
    assert "tests" in parsed
    assert "diagnostics" in parsed

    # 3. Symbol node lookup by name
    res_sym = server.execute_tool("cbi_show", {"node": "Circle"})
    assert not res_sym["isError"]
    assert "Circle (class)" in res_sym["content"][0]["text"]

    # 4. Confidence filtering
    res_conf = server.execute_tool(
        "cbi_show",
        {"node": "src/shapes/circle.ts", "min_confidence": 0.9, "format": "json"},
    )
    assert not res_conf["isError"]
    parsed_conf = json.loads(res_conf["content"][0]["text"])
    for edge in parsed_conf["outgoing"] + parsed_conf["incoming"]:
        assert edge["confidence"] >= 0.9 or edge.get("attrs", {}).get("via") == "injection"

    # 5. Invalid min_confidence
    res_bad_conf = server.execute_tool("cbi_show", {"node": "src/shapes/circle.ts", "min_confidence": 1.5})
    assert res_bad_conf["isError"]
    assert "min_confidence must be between 0 and 1" in res_bad_conf["content"][0]["text"]

    # 6. 'all' toggle (relationships/tests cap)
    res_all = server.execute_tool("cbi_show", {"node": "src/shapes/circle.ts", "all": True})
    assert not res_all["isError"]
    assert "src/shapes/circle.ts" in res_all["content"][0]["text"]

    # 7. Missing required 'node' argument
    res_missing_arg = server.execute_tool("cbi_show", {})
    assert res_missing_arg["isError"]
    assert "Missing required argument: 'node'" in res_missing_arg["content"][0]["text"]

    # 8. Non-existent node error
    res_unknown = server.execute_tool("cbi_show", {"node": "nonexistent/file.ts"})
    assert res_unknown["isError"]
    assert "no node matches 'nonexistent/file.ts'" in res_unknown["content"][0]["text"]

    # 9. Non-existent node in JSON format still returns isError
    res_unknown_json = server.execute_tool("cbi_show", {"node": "nonexistent/file.ts", "format": "json"})
    assert res_unknown_json["isError"]
    assert "no node matches 'nonexistent/file.ts'" in res_unknown_json["content"][0]["text"]

    # 10. Ambiguous node error
    res_ambig = server.execute_tool("cbi_show", {"node": "area"})
    assert res_ambig["isError"]
    assert "matches" in res_ambig["content"][0]["text"]
    assert "pick one by ID" in res_ambig["content"][0]["text"]


def test_tools_call_tests_for(repo):
    server = MCPServer(root=repo)

    req = {
        "jsonrpc": "2.0",
        "id": 30,
        "method": "tools/call",
        "params": {"name": "cbi_tests_for", "arguments": {"target": "src/shapes/circle.ts"}},
    }
    resp = server.handle_request(req)
    assert resp["id"] == 30
    assert not resp["result"]["isError"]
    text = resp["result"]["content"][0]["text"]
    assert "circle.test.ts" in text or "measures the area" in text

    # Missing target argument
    req_missing = {
        "jsonrpc": "2.0",
        "id": 31,
        "method": "tools/call",
        "params": {"name": "cbi_tests_for", "arguments": {}},
    }
    resp_missing = server.handle_request(req_missing)
    assert resp_missing["result"]["isError"]


def test_tools_call_search(repo):
    server = MCPServer(root=repo)

    req = {
        "jsonrpc": "2.0",
        "id": 40,
        "method": "tools/call",
        "params": {"name": "cbi_search", "arguments": {"query": "Circle"}},
    }
    resp = server.handle_request(req)
    assert resp["id"] == 40
    assert not resp["result"]["isError"]
    text = resp["result"]["content"][0]["text"]
    assert "Circle" in text

    # Missing query argument
    req_missing = {
        "jsonrpc": "2.0",
        "id": 41,
        "method": "tools/call",
        "params": {"name": "cbi_search", "arguments": {}},
    }
    resp_missing = server.handle_request(req_missing)
    assert resp_missing["result"]["isError"]


def test_tools_call_hotspots(repo):
    server = MCPServer(root=repo)

    req = {
        "jsonrpc": "2.0",
        "id": 50,
        "method": "tools/call",
        "params": {"name": "cbi_hotspots", "arguments": {"metric": "fan-in"}},
    }
    resp = server.handle_request(req)
    assert resp["id"] == 50
    assert not resp["result"]["isError"]
    text = resp["result"]["content"][0]["text"]
    assert "by fan-in" in text or "fan-in" in text


def test_unknown_method_and_unknown_tool():
    server = MCPServer()

    # Unknown method
    req_m = {"jsonrpc": "2.0", "id": 60, "method": "unknown/method", "params": {}}
    resp_m = server.handle_request(req_m)
    assert resp_m["error"]["code"] == -32601

    # Unknown tool
    req_t = {
        "jsonrpc": "2.0",
        "id": 61,
        "method": "tools/call",
        "params": {"name": "nonexistent_tool", "arguments": {}},
    }
    resp_t = server.handle_request(req_t)
    assert resp_t["result"]["isError"]
    assert "Unknown tool" in resp_t["result"]["content"][0]["text"]


def test_framing_newline_delimited():
    msg = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
    buf = io.BytesIO()
    write_message(buf, msg, content_length=False)
    raw_data = buf.getvalue()
    assert raw_data.endswith(b"\n")
    assert not raw_data.startswith(b"Content-Length:")

    buf.seek(0)
    parsed, is_cl = read_message(buf)
    assert parsed == msg
    assert is_cl is False


def test_framing_content_length():
    msg = {"jsonrpc": "2.0", "id": 2, "method": "ping"}
    buf = io.BytesIO()
    write_message(buf, msg, content_length=True)
    raw_data = buf.getvalue()
    assert raw_data.startswith(b"Content-Length: ")
    assert b"\r\n\r\n" in raw_data

    buf.seek(0)
    parsed, is_cl = read_message(buf)
    assert parsed == msg
    assert is_cl is True


def test_stdio_loop(repo):
    server = MCPServer(root=repo)

    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "cbi_status", "arguments": {}}},
    ]

    input_lines = [json.dumps(m) + "\n" for m in messages]
    stdin_stream = io.StringIO("".join(input_lines))
    stdout_stream = io.StringIO()

    exit_code = server.run(stdin=stdin_stream, stdout=stdout_stream)
    assert exit_code == 0

    stdout_stream.seek(0)
    output_lines = [line.strip() for line in stdout_stream.getvalue().splitlines() if line.strip()]

    # We expect exactly 3 responses (notification produces no response)
    assert len(output_lines) == 3
    resp1 = json.loads(output_lines[0])
    resp2 = json.loads(output_lines[1])
    resp3 = json.loads(output_lines[2])

    assert resp1["id"] == 1
    assert resp1["result"]["serverInfo"]["name"] == "cbi"

    assert resp2["id"] == 2
    assert "tools" in resp2["result"]

    assert resp3["id"] == 3
    assert not resp3["result"]["isError"]


def test_cbi_mcp_cli_help(capsys):
    with pytest.raises(SystemExit) as caught:
        main(["mcp", "--help"])
    assert caught.value.code == 0
    out = capsys.readouterr().out
    assert "mcp" in out
    assert "--out" in out
    assert "--config" in out


def test_cbi_mcp_cli_config(capsys):
    assert main(["mcp", "--config"]) == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert "mcpServers" in data
    assert "codebase-inspector" in data["mcpServers"]
    assert "clients" in data

    assert main(["mcp", "--config", "claude"]) == 0
    out_claude = capsys.readouterr().out
    claude_data = json.loads(out_claude)
    assert "mcpServers" in claude_data
    assert claude_data["mcpServers"]["codebase-inspector"]["command"] == "cbi"

    assert main(["mcp", "--config", "cursor"]) == 0
    out_cursor = capsys.readouterr().out
    cursor_data = json.loads(out_cursor)
    assert "mcpServers" in cursor_data


def test_tool_tasks(repo):
    server = MCPServer(root=repo)
    resp = server.execute_tool("cbi_tasks", {})
    assert not resp["isError"]
    # In fixture repo with initial scan, tasks may exist or be empty
    assert isinstance(resp["content"][0]["text"], str)

    resp_json = server.execute_tool("cbi_tasks", {"format": "json"})
    assert not resp_json["isError"]
    parsed = json.loads(resp_json["content"][0]["text"])
    assert isinstance(parsed, list)


def test_tools_call_submit(repo):
    server = MCPServer(root=repo)

    # 1. Missing required task_id
    res_no_tid = server.execute_tool("cbi_submit", {"answer": {}})
    assert res_no_tid["isError"]
    assert "Missing required argument: 'task_id'" in res_no_tid["content"][0]["text"]

    # 2. Missing required answer
    res_no_ans = server.execute_tool("cbi_submit", {"task_id": "some-id"})
    assert res_no_ans["isError"]
    assert "Missing required argument: 'answer'" in res_no_ans["content"][0]["text"]

    # 3. Unknown task ID
    res_unknown = server.execute_tool("cbi_submit", {"task_id": "nonexistent-task", "answer": {}})
    assert res_unknown["isError"]
    assert "nonexistent-task" in res_unknown["content"][0]["text"]

    # 4. Query open tasks
    tasks_res = server.execute_tool("cbi_tasks", {"format": "json"})
    assert not tasks_res["isError"]
    open_tasks = json.loads(tasks_res["content"][0]["text"])
    assert len(open_tasks) > 0, "Expected open tasks in fixture repo"

    task = open_tasks[0]
    task_id = task["id"]

    # Retrieve brief to get task details and input_hash
    brief_res = server.execute_tool("cbi_tasks", {"task_id": task_id, "format": "json"})
    assert not brief_res["isError"]
    brief = json.loads(brief_res["content"][0]["text"])

    # 5. Malformed answer: invalid JSON string
    res_malformed = server.execute_tool("cbi_submit", {"task_id": task_id, "answer": "{not valid json"})
    assert res_malformed["isError"]
    assert "not valid JSON" in res_malformed["content"][0]["text"]

    # 6. Invalid schema / stale input_hash
    res_bad_hash = server.execute_tool("cbi_submit", {"task_id": task_id, "answer": {"input_hash": "bad-hash"}})
    assert res_bad_hash["isError"]

    # 7. Construct valid answer matching schema
    if brief["kind"] == "summarise-files":
        answer = {
            "input_hash": brief["input_hash"],
            "files": [{"path": f["path"], "summary": f"Summary for {f['path']}."} for f in brief["files"]],
        }
    elif brief["kind"] == "summarise-group":
        answer = {"input_hash": brief["input_hash"], "summary": "Group summary."}
    elif brief["kind"] == "confirm-structure":
        answer = {"input_hash": brief["input_hash"], "deployables": [], "packages": []}
    elif brief["kind"] == "define-concepts":
        answer = {
            "input_hash": brief["input_hash"],
            "summary": "Concepts summary.",
            "concepts": [],
            "externals": [],
            "relationships": [],
        }
    else:
        answer = {"input_hash": brief["input_hash"], "summary": "Task summary."}

    # 8. Submit as JSON object (dict)
    res_good = server.execute_tool("cbi_submit", {"task_id": task_id, "answer": answer})
    assert not res_good["isError"]
    report = res_good["content"][0]["text"]
    assert "accepted" in report or task_id in report

    # 9. Submit as serialized JSON string (idempotent / already accepted)
    res_str = server.execute_tool("cbi_submit", {"task_id": task_id, "answer": json.dumps(answer)})
    assert not res_str["isError"]
    report_str = res_str["content"][0]["text"]
    assert "accepted" in report_str or "already accepted" in report_str

    # 10. JSON-RPC 2.0 tools/call round-trip
    req = {
        "jsonrpc": "2.0",
        "id": 88,
        "method": "tools/call",
        "params": {"name": "cbi_submit", "arguments": {"task_id": task_id, "answer": answer}},
    }
    resp = server.handle_request(req)
    assert resp["id"] == 88
    assert not resp["result"]["isError"]


def test_tools_call_submit_mismatched_schema(tmp_path):
    cbi_dir = tmp_path / ".cbi"
    cbi_dir.mkdir()
    db = cbi_dir / "model.db"
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA user_version = 999")
    conn.execute("CREATE TABLE sentinel (value TEXT)")
    conn.execute("INSERT INTO sentinel VALUES ('keep')")
    conn.commit()
    conn.close()

    server = MCPServer(root=tmp_path)
    res = server.execute_tool("cbi_submit", {"task_id": "any-id", "answer": {}})
    assert res["isError"]
    assert "schema 999" in res["content"][0]["text"]
    assert "Rescan it" in res["content"][0]["text"]

    # Verify model.db was not destroyed or wiped
    conn = sqlite3.connect(db)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 999
    rows = conn.execute("SELECT name FROM sqlite_master WHERE name = 'sentinel'").fetchall()
    assert len(rows) == 1
    conn.close()


def test_tool_diff(repo):
    server = MCPServer(root=repo)
    model_file = str(repo / ".cbi" / "model.db")
    resp = server.execute_tool("cbi_diff", {"base_model": model_file, "head_model": model_file})
    assert not resp["isError"]
    assert "no architectural changes" in resp["content"][0]["text"]


def test_tool_diff_drilldown(repo):
    import subprocess

    git = lambda *args: subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@example.com", "-c", "commit.gpgsign=false", *args],
        cwd=repo, check=True, capture_output=True, text=True,
    )

    # Modify src/shapes/circle.ts and commit to create a diff
    circle_file = repo / "src" / "shapes" / "circle.ts"
    circle_file.write_text("""\
/** A round shape. */
export class Circle {
  constructor(readonly radius: number) {}
  area(): number { return Math.PI * this.radius ** 2; }
  circumference(): number { return 2 * Math.PI * this.radius; }
}

export function makeCircle(r: number) { return new Circle(r); }
""")
    git("add", "src/shapes/circle.ts")
    git("commit", "-m", "add circumference method to Circle")

    server = MCPServer(root=repo)

    # First get the full diff in JSON to extract module id
    overview_resp = server.execute_tool("cbi_diff", {
        "base": "HEAD~1",
        "head": "HEAD",
        "format": "json",
    })
    assert not overview_resp["isError"]
    overview_data = json.loads(overview_resp["content"][0]["text"])
    item = overview_data["overview"]["items"][0]
    mod = item["modules"][0]
    module_id = mod["id"]

    # 1. Drill down into module (text and json)
    res_mod_text = server.execute_tool("cbi_diff", {
        "base": "HEAD~1",
        "head": "HEAD",
        "module": module_id,
        "format": "text",
    })
    assert not res_mod_text["isError"]
    assert mod["name"] in res_mod_text["content"][0]["text"]

    res_mod_json = server.execute_tool("cbi_diff", {
        "base": "HEAD~1",
        "head": "HEAD",
        "module": module_id,
        "format": "json",
    })
    assert not res_mod_json["isError"]
    data_mod = json.loads(res_mod_json["content"][0]["text"])
    assert "selection" in data_mod
    assert data_mod["selection"]["level"] == "module"
    assert data_mod["selection"]["item"]["id"] == module_id

    # 2. Drill down into file (text and json)
    res_file_text = server.execute_tool("cbi_diff", {
        "base": "HEAD~1",
        "head": "HEAD",
        "file": "src/shapes/circle.ts",
        "format": "text",
    })
    assert not res_file_text["isError"]
    assert "circle.ts" in res_file_text["content"][0]["text"]

    res_file_json = server.execute_tool("cbi_diff", {
        "base": "HEAD~1",
        "head": "HEAD",
        "file": "src/shapes/circle.ts",
        "format": "json",
    })
    assert not res_file_json["isError"]
    data_file = json.loads(res_file_json["content"][0]["text"])
    assert "selection" in data_file
    assert data_file["selection"]["level"] == "file"
    assert data_file["selection"]["item"]["path"] == "src/shapes/circle.ts"

    # 3. Drill down into symbol (text and json)
    res_sym_text = server.execute_tool("cbi_diff", {
        "base": "HEAD~1",
        "head": "HEAD",
        "symbol": "circumference",
        "format": "text",
    })
    assert not res_sym_text["isError"]
    assert "circumference" in res_sym_text["content"][0]["text"]

    res_sym_json = server.execute_tool("cbi_diff", {
        "base": "HEAD~1",
        "head": "HEAD",
        "symbol": "circumference",
        "format": "json",
    })
    assert not res_sym_json["isError"]
    data_sym = json.loads(res_sym_json["content"][0]["text"])
    assert "selection" in data_sym
    assert data_sym["selection"]["level"] == "symbol"
    assert data_sym["selection"]["item"]["name"] == "circumference"


def test_tool_query(repo):
    server = MCPServer(root=repo)

    # JSON format
    resp_json = server.execute_tool("cbi_query", {
        "sql": "SELECT id, kind, name FROM nodes WHERE kind = 'symbol' ORDER BY name",
        "format": "json",
    })
    assert not resp_json["isError"]
    data = json.loads(resp_json["content"][0]["text"])
    assert data["row_count"] > 0
    assert "Circle" in [r["name"] for r in data["rows"]]
    assert "columns" in data
    assert data["columns"] == ["id", "kind", "name"]

    # Text format
    resp_text = server.execute_tool("cbi_query", {
        "sql": "SELECT id, kind, name FROM nodes WHERE kind = 'symbol' ORDER BY name",
        "format": "text",
    })
    assert not resp_text["isError"]
    text = resp_text["content"][0]["text"]
    assert "Circle" in text
    assert "id" in text and "name" in text

    # Missing SQL argument
    resp_err = server.execute_tool("cbi_query", {})
    assert resp_err["isError"]

    # Reject non-read operations
    resp_insert = server.execute_tool("cbi_query", {"sql": "INSERT INTO nodes (id) VALUES ('fake')"})
    assert resp_insert["isError"]
    assert "Only read-only queries are permitted" in resp_insert["content"][0]["text"]

    resp_drop = server.execute_tool("cbi_query", {"sql": "DROP TABLE nodes"})
    assert resp_drop["isError"]
    assert "Only read-only queries are permitted" in resp_drop["content"][0]["text"]


def test_tool_concepts(repo):
    server = MCPServer(root=repo)

    # Empty concepts in fresh test repo
    resp_empty = server.execute_tool("cbi_concepts", {"format": "json"})
    assert not resp_empty["isError"]
    assert json.loads(resp_empty["content"][0]["text"]) == []

    resp_empty_text = server.execute_tool("cbi_concepts", {"format": "text"})
    assert not resp_empty_text["isError"]
    assert "No concepts defined" in resp_empty_text["content"][0]["text"]

    # Insert sample concept nodes and edges
    db_path = repo / ".cbi" / "model.db"
    conn = sqlite3.connect(db_path)
    with conn:
        conn.execute(
            "INSERT INTO nodes (id, kind, display_kind, name, summary, attrs) VALUES (?, ?, ?, ?, ?, ?)",
            ("shapes", "concept", "core", "Shapes", "Shape calculations", json.dumps({"role": "core", "entry": False})),
        )
        conn.execute(
            "INSERT INTO edges (src, dst, kind, source) VALUES (?, ?, 'owns', 'concept')",
            ("shapes", f"local:repo:src/shapes/circle.ts"),
        )
    conn.close()

    # Query all concepts as JSON
    resp_all_json = server.execute_tool("cbi_concepts", {"format": "json"})
    assert not resp_all_json["isError"]
    concepts = json.loads(resp_all_json["content"][0]["text"])
    assert len(concepts) == 1
    assert concepts[0]["id"] == "shapes"
    assert concepts[0]["files_count"] == 1

    # Query all concepts as Text
    resp_all_text = server.execute_tool("cbi_concepts", {"format": "text"})
    assert not resp_all_text["isError"]
    assert "Shapes" in resp_all_text["content"][0]["text"]
    assert "shapes" in resp_all_text["content"][0]["text"]

    # Query specific concept by ID
    resp_single = server.execute_tool("cbi_concepts", {"concept_id": "shapes", "format": "json"})
    assert not resp_single["isError"]
    single = json.loads(resp_single["content"][0]["text"])
    assert single["id"] == "shapes"
    assert single["name"] == "Shapes"
    assert "local:repo:src/shapes/circle.ts" in single["files"]

    # Non-existent concept ID
    resp_missing = server.execute_tool("cbi_concepts", {"concept_id": "nonexistent"})
    assert resp_missing["isError"]
    assert "not found" in resp_missing["content"][0]["text"]


def test_tools_call_cycles(repo):
    server = MCPServer(root=repo)

    # Text format
    resp_text = server.execute_tool("cbi_cycles", {})
    assert not resp_text["isError"]
    text = resp_text["content"][0]["text"]
    assert "SCCs:" in text and "memberships" in text

    resp_text2 = server.execute_tool("cbi_cycles", {"format": "text"})
    assert not resp_text2["isError"]
    assert resp_text2["content"][0]["text"] == text

    # JSON format
    resp_json = server.execute_tool("cbi_cycles", {"format": "json"})
    assert not resp_json["isError"]
    data = json.loads(resp_json["content"][0]["text"])
    assert "files" in data and "folders" in data and "packages" in data
    assert isinstance(data["files"], list)


def test_tools_call_orphans(repo):
    server = MCPServer(root=repo)

    # Text format
    resp_text = server.execute_tool("cbi_orphans", {})
    assert not resp_text["isError"]
    text = resp_text["content"][0]["text"]
    assert "production code with no production importer" in text

    # JSON format
    resp_json = server.execute_tool("cbi_orphans", {"format": "json"})
    assert not resp_json["isError"]
    data = json.loads(resp_json["content"][0]["text"])
    assert "unreferenced" in data
    assert "test_only_symbols" in data
    assert "untested" in data
    assert isinstance(data["unreferenced"], list)


def test_tools_call_deps(repo):
    server = MCPServer(root=repo)

    # Default level (package) in text format
    resp_text = server.execute_tool("cbi_deps", {})
    assert not resp_text["isError"]
    text = resp_text["content"][0]["text"]
    assert isinstance(text, str)

    # Absent container in JSON format returns structured empty JSON
    resp_empty_json = server.execute_tool("cbi_deps", {"format": "json"})
    assert not resp_empty_json["isError"]
    empty_data = json.loads(resp_empty_json["content"][0]["text"])
    assert empty_data["level"] == "package"
    assert empty_data["nodes"] == []
    assert empty_data["edges"] == []

    # Folder level text format
    resp_folder = server.execute_tool("cbi_deps", {"level": "folder", "format": "text"})
    assert not resp_folder["isError"]

    # Folder level JSON format
    resp_json = server.execute_tool("cbi_deps", {"level": "folder", "format": "json"})
    assert not resp_json["isError"]
    data = json.loads(resp_json["content"][0]["text"])
    assert data["level"] == "folder"
    assert "nodes" in data
    assert "edges" in data

    # With include_tests
    resp_tests = server.execute_tool("cbi_deps", {"level": "folder", "include_tests": True, "format": "json"})
    assert not resp_tests["isError"]
    data_tests = json.loads(resp_tests["content"][0]["text"])
    assert data_tests["tests"] is True

    # Endpoint filtering with node ID and repo path
    resp_id = server.execute_tool("cbi_deps", {
        "level": "folder",
        "start": "local:repo:src/shapes",
        "format": "json",
    })
    assert not resp_id["isError"]
    id_data = json.loads(resp_id["content"][0]["text"])
    assert id_data["level"] == "folder"

    resp_path = server.execute_tool("cbi_deps", {
        "level": "folder",
        "start": "src/shapes",
        "end": "src/shapes",
        "format": "json",
    })
    assert not resp_path["isError"]
    path_data = json.loads(resp_path["content"][0]["text"])
    assert path_data["level"] == "folder"

    # Unknown start endpoint returns error
    resp_bad = server.execute_tool("cbi_deps", {"level": "folder", "start": "nonexistent_dir"})
    assert resp_bad["isError"]
    assert "no folder" in resp_bad["content"][0]["text"]


def test_concurrent_requests_stress(repo):
    import concurrent.futures

    concepts_doc = {
        "summary": "Concepts for concurrent stress test",
        "concepts": [{"id": "shapes", "name": "Shapes", "summary": "Shapes", "role": "core", "files": ["src/shapes/circle.ts"]}],
        "externals": [],
        "relationships": [],
    }
    (repo / ".cbi" / "concepts.json").write_text(json.dumps(concepts_doc))
    (repo / "coverage.lcov").write_text("TN:\nSF:src/shapes/circle.ts\nDA:18,1\nend_of_record\n")

    server = MCPServer(root=repo)

    tools_and_args = [
        ("cbi_scan", {"format": "text"}),
        ("cbi_scan", {"format": "json"}),
        ("cbi_status", {"format": "text"}),
        ("cbi_search", {"query": "Circle"}),
        ("cbi_show", {"node": "src/shapes/circle.ts"}),
        ("cbi_show", {"node": "src/shapes/circle.ts", "format": "json"}),
        ("cbi_tests_for", {"target": "src/shapes/circle.ts"}),
        ("cbi_hotspots", {"metric": "fan-in"}),
        ("cbi_query", {"sql": "SELECT id, name FROM nodes WHERE kind = 'symbol'", "format": "json"}),
        ("cbi_tasks", {"format": "json"}),
        ("cbi_cycles", {"format": "json"}),
        ("cbi_orphans", {"format": "json"}),
        ("cbi_deps", {"level": "folder", "format": "json"}),
        ("cbi_endpoints", {"format": "json"}),
        ("cbi_tables", {"format": "json"}),
        ("cbi_history", {"format": "json"}),
        ("cbi_history", {"format": "markdown"}),
        ("cbi_review", {"target": "HEAD", "base": "HEAD", "format": "json"}),
        ("cbi_review", {"target": "HEAD", "base": "HEAD", "format": "markdown"}),
        ("cbi_check", {"format": "text"}),
        ("cbi_check", {"format": "json"}),
        ("cbi_worktrees", {"format": "text"}),
        ("cbi_worktrees", {"format": "json"}),
        ("cbi_prime", {}),
        ("cbi_task", {"task_id": "test"}),
        ("cbi_init", {"format": "json"}),
        ("cbi_ingest", {"files": ["coverage.lcov"]}),
    ]

    def make_call(pair):
        tool, args = pair
        res = server.execute_tool(tool, args)
        return tool, res

    work_items = [tools_and_args[i % len(tools_and_args)] for i in range(60)]

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(make_call, item) for item in work_items]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    assert len(results) == 60
    for tool_name, res in results:
        assert not res["isError"], f"Tool {tool_name} failed: {res['content']}"
        assert len(res["content"]) > 0
        assert len(res["content"][0]["text"]) > 0


def test_tools_call_endpoints_empty_repo(repo):
    server = MCPServer(root=repo)
    req = {
        "jsonrpc": "2.0",
        "id": 80,
        "method": "tools/call",
        "params": {"name": "cbi_endpoints", "arguments": {}},
    }
    resp = server.handle_request(req)
    assert not resp["result"]["isError"]
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert payload == {"endpoints": []}


def test_tools_call_tables_empty_repo(repo):
    server = MCPServer(root=repo)
    req = {
        "jsonrpc": "2.0",
        "id": 81,
        "method": "tools/call",
        "params": {"name": "cbi_tables", "arguments": {}},
    }
    resp = server.handle_request(req)
    assert not resp["result"]["isError"]
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert payload == {"tables": [], "relationships": []}


def test_tools_call_system_views_with_data(make_repo, monkeypatch):
    system_fixture = Path(__file__).parent / "fixtures" / "data" / "system"
    root = make_repo({
        p.relative_to(system_fixture).as_posix(): p.read_text()
        for p in system_fixture.rglob("*") if p.is_file()
    }, name="system-mcp")
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0

    server = MCPServer(root=root)

    # cbi_endpoints: default json output
    res = server.execute_tool("cbi_endpoints", {})
    assert not res["isError"]
    data = json.loads(res["content"][0]["text"])
    assert len(data["endpoints"]) == 2

    # cbi_endpoints: filtering by method
    res = server.execute_tool("cbi_endpoints", {"method": "GET"})
    data = json.loads(res["content"][0]["text"])
    assert len(data["endpoints"]) == 1
    assert data["endpoints"][0]["method"] == "GET"

    # cbi_endpoints: filtering by path
    res = server.execute_tool("cbi_endpoints", {"path": "/api/accounts"})
    data = json.loads(res["content"][0]["text"])
    assert len(data["endpoints"]) == 2

    # cbi_endpoints: filtering by handler
    res = server.execute_tool("cbi_endpoints", {"handler": "create_account"})
    data = json.loads(res["content"][0]["text"])
    assert len(data["endpoints"]) == 1
    assert data["endpoints"][0]["handler"]["name"] == "create_account"

    # cbi_endpoints: filtering by table
    res = server.execute_tool("cbi_endpoints", {"table": "accounts"})
    data = json.loads(res["content"][0]["text"])
    assert len(data["endpoints"]) == 1
    assert data["endpoints"][0]["method"] == "GET"

    # cbi_endpoints: text format
    res = server.execute_tool("cbi_endpoints", {"format": "text"})
    assert not res["isError"]
    assert "GET    /api/accounts" in res["content"][0]["text"]

    # cbi_tables: default json output
    res = server.execute_tool("cbi_tables", {})
    assert not res["isError"]
    data = json.loads(res["content"][0]["text"])
    assert len(data["tables"]) == 1
    assert data["tables"][0]["name"] == "accounts"

    # cbi_tables: filtering by table
    res = server.execute_tool("cbi_tables", {"table": "accounts"})
    data = json.loads(res["content"][0]["text"])
    assert len(data["tables"]) == 1

    res = server.execute_tool("cbi_tables", {"table": "nonexistent"})
    data = json.loads(res["content"][0]["text"])
    assert len(data["tables"]) == 0

    # cbi_tables: text format
    res = server.execute_tool("cbi_tables", {"format": "text"})
    assert not res["isError"]
    assert "table accounts (2 columns)" in res["content"][0]["text"]


def test_tool_history(make_repo, monkeypatch):
    import subprocess
    root = make_repo({"a.py": "def a():\n    return 1\n"}, name="mcp-history-repo")

    def commit_file(rel, content, msg):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        subprocess.run(["git", "add", "-A"], cwd=root, check=True)
        subprocess.run([
            "git", "-c", "user.name=test", "-c", "user.email=test@example.com",
            "-c", "commit.gpgsign=false", "commit", "-q", "-m", msg,
        ], cwd=root, check=True)

    commit_file("b.py", "def b():\n    return 2\n", "feat: add b (#1)")
    commit_file("c.py", "def c():\n    return 3\n", "feat: add c (#2)")

    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    concepts = {
        "summary": "History test concepts",
        "concepts": [
            {"id": "core", "name": "Core", "summary": "Core logic", "role": "core", "files": ["a.py"]},
            {"id": "app", "name": "App", "summary": "App logic", "role": "app", "files": ["b.py", "c.py"]},
        ],
        "externals": [],
        "relationships": [],
    }
    (root / ".cbi" / "concepts.json").write_text(json.dumps(concepts))
    assert main(["scan"]) == 0

    server = MCPServer(root=root)

    # Default markdown format
    res_md = server.execute_tool("cbi_history", {})
    assert not res_md["isError"]
    text_md = res_md["content"][0]["text"]
    assert "# Architecture changelog" in text_md
    assert "PR #1" in text_md or "PR #2" in text_md

    # JSON format
    res_json = server.execute_tool("cbi_history", {"format": "json"})
    assert not res_json["isError"]
    payload = json.loads(res_json["content"][0]["text"])
    assert "entries" in payload
    assert len(payload["entries"]) >= 2

    # Limit option
    res_limit = server.execute_tool("cbi_history", {"limit": 1, "format": "json"})
    assert not res_limit["isError"]
    payload_limit = json.loads(res_limit["content"][0]["text"])
    assert len(payload_limit["entries"]) == 1

    # Concept filter
    res_concept = server.execute_tool("cbi_history", {"concept": "app", "format": "json"})
    assert not res_concept["isError"]
    payload_concept = json.loads(res_concept["content"][0]["text"])
    for entry in payload_concept["entries"]:
        groups = entry.get("changes", {}).get("groups", [])
        assert any(g.get("id") == "app" for g in groups)

    # Text format
    res_text = server.execute_tool("cbi_history", {"format": "text"})
    assert not res_text["isError"]
    text = res_text["content"][0]["text"]
    assert "Architecture changelog" not in text

    # Relative dates ("1 month ago", "now", "1 hour ago")
    res_relative = server.execute_tool("cbi_history", {"since": "1 month ago", "until": "now", "format": "json"})
    assert not res_relative["isError"]
    payload_rel = json.loads(res_relative["content"][0]["text"])
    assert len(payload_rel["entries"]) >= 2

    res_hour = server.execute_tool("cbi_history", {"since": "2 hours ago", "until": "now", "format": "json"})
    assert not res_hour["isError"]
    payload_hour = json.loads(res_hour["content"][0]["text"])
    assert len(payload_hour["entries"]) >= 2

    # Error handling: invalid limit
    res_err_limit = server.execute_tool("cbi_history", {"limit": -1})
    assert res_err_limit["isError"]
    assert "limit" in res_err_limit["content"][0]["text"]

    # Error handling: invalid date
    res_err_date = server.execute_tool("cbi_history", {"since": "not-a-date"})
    assert res_err_date["isError"]
    assert "invalid date" in res_err_date["content"][0]["text"]


def test_tool_review(make_repo, monkeypatch):
    import subprocess
    root = make_repo({"core/a.ts": "export function a() { return 1; }\n"}, name="mcp-review-repo")

    def commit_file(rel, content, msg):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        subprocess.run(["git", "add", "-A"], cwd=root, check=True)
        subprocess.run([
            "git", "-c", "user.name=test", "-c", "user.email=test@example.com",
            "-c", "commit.gpgsign=false", "commit", "-q", "-m", msg,
        ], cwd=root, check=True)

    commit_file("app/b.ts", "import { a } from '../core/a';\nexport function b() { return a(); }\n", "feat: add app caller")

    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    concepts = {
        "summary": "Review test concepts",
        "concepts": [
            {"id": "core", "name": "Core", "summary": "Core logic", "role": "core", "files": ["core/a.ts"]},
            {"id": "app", "name": "App", "summary": "App logic", "role": "app", "files": ["app/b.ts"]},
        ],
        "externals": [],
        "relationships": [{"from": "app", "to": "core", "label": "calls", "basis": "imports"}],
    }
    (root / ".cbi" / "concepts.json").write_text(json.dumps(concepts))
    assert main(["scan"]) == 0

    server = MCPServer(root=root)

    # Markdown format with target/base: verify Mermaid diagram
    res_md = server.execute_tool("cbi_review", {
        "target": "HEAD",
        "base": "HEAD~1",
        "format": "markdown",
    })
    assert not res_md["isError"]
    text_md = res_md["content"][0]["text"]
    assert "cbi://open?" in text_md
    assert "<!-- cbi-review -->" in text_md
    assert "```mermaid" in text_md
    assert "flowchart LR" in text_md
    assert "classDef added" in text_md
    assert 'app["App"]' in text_md
    assert "## Details" in text_md

    # JSON format with target/base
    res_json = server.execute_tool("cbi_review", {
        "target": "HEAD",
        "base": "HEAD~1",
        "format": "json",
    })
    assert not res_json["isError"]
    data = json.loads(res_json["content"][0]["text"])
    assert "base" in data and "head" in data
    assert "spec" in data
    assert "result" in data
    assert "diagram" in data
    assert "mermaid" in data
    assert "flowchart LR" in data["mermaid"]
    assert any(n["id"] == "app" for n in data["diagram"]["nodes"])

    # Branch target with automatic merge-base default
    subprocess.run(["git", "checkout", "-q", "-b", "feature-branch"], cwd=root, check=True)
    commit_file("app/c.ts", "export function c() { return 3; }\n", "feat: branch commit")
    res_branch = server.execute_tool("cbi_review", {
        "target": "HEAD",
        "format": "markdown",
    })
    assert not res_branch["isError"]
    assert "flowchart LR" in res_branch["content"][0]["text"]

    # Target range syntax (HEAD~1..HEAD)
    res_range = server.execute_tool("cbi_review", {
        "target": "HEAD~1..HEAD",
        "format": "json",
    })
    assert not res_range["isError"]
    range_data = json.loads(res_range["content"][0]["text"])
    assert range_data["spec"]["base"] == "HEAD~1"
    assert range_data["spec"]["head"] == "HEAD"

    # Error handling: invalid target ref
    res_bad = server.execute_tool("cbi_review", {"target": "nonexistent_ref_9999"})
    assert res_bad["isError"]


def test_tool_check(repo):
    server = MCPServer(root=repo)

    # 1. Clean pass in text format (default)
    res_text = server.execute_tool("cbi_check", {})
    assert not res_text["isError"]
    assert "cbi check: passed" in res_text["content"][0]["text"]

    # Explicit text format
    res_text_exp = server.execute_tool("cbi_check", {"format": "text"})
    assert not res_text_exp["isError"]
    assert "cbi check: passed" in res_text_exp["content"][0]["text"]

    # 2. Clean pass in JSON format
    res_json = server.execute_tool("cbi_check", {"format": "json"})
    assert not res_json["isError"]
    data = json.loads(res_json["content"][0]["text"])
    assert data["passed"] is True
    assert data["problems"] == []

    # 3. Clean pass with explicit base
    res_base = server.execute_tool("cbi_check", {"base": "main", "format": "json"})
    assert not res_base["isError"]
    data_base = json.loads(res_base["content"][0]["text"])
    assert data_base["passed"] is True
    assert data_base["problems"] == []

    # 4. Bad ref error handling
    res_bad = server.execute_tool("cbi_check", {"base": "nonexistent_ref_9999"})
    assert res_bad["isError"]
    assert "Error:" in res_bad["content"][0]["text"]

    # 5. Problem detection when code file is changed
    (repo / "src/shapes/circle.ts").write_text("export class Circle { constructor(readonly r: number) {} }\n")
    res_prob_json = server.execute_tool("cbi_check", {"format": "json"})
    assert not res_prob_json["isError"]
    data_prob = json.loads(res_prob_json["content"][0]["text"])
    assert data_prob["passed"] is False
    assert len(data_prob["problems"]) > 0
    assert any("src/shapes/circle.ts" in p for p in data_prob["problems"])

    res_prob_text = server.execute_tool("cbi_check", {"format": "text"})
    assert not res_prob_text["isError"]
    assert "problem" in res_prob_text["content"][0]["text"]
    assert "src/shapes/circle.ts" in res_prob_text["content"][0]["text"]


def test_tool_worktrees(repo, tmp_path):
    import subprocess
    lane = tmp_path / "wt-lane"
    subprocess.run(["git", "worktree", "add", "-q", "-b", "lane", str(lane)], cwd=repo, check=True)

    server = MCPServer(root=repo)

    # 1. Text format (default)
    res_text = server.execute_tool("cbi_worktrees", {})
    assert not res_text["isError"]
    text = res_text["content"][0]["text"]
    assert "worktrees:" in text
    assert "branches:" in text
    assert "main" in text
    assert "lane" in text

    # Explicit format: text
    res_text_exp = server.execute_tool("cbi_worktrees", {"format": "text"})
    assert not res_text_exp["isError"]
    assert "worktrees:" in res_text_exp["content"][0]["text"]

    # 2. JSON format
    res_json = server.execute_tool("cbi_worktrees", {"format": "json"})
    assert not res_json["isError"]
    data = json.loads(res_json["content"][0]["text"])
    assert "worktrees" in data and "branches" in data
    assert isinstance(data["worktrees"], list) and len(data["worktrees"]) >= 2
    assert isinstance(data["branches"], list) and len(data["branches"]) >= 2

    # Verify worktree properties
    current_wt = next(w for w in data["worktrees"] if w["current"])
    assert current_wt["branch"] == "main"
    assert current_wt["has_model"] is True
    assert Path(current_wt["path"]).resolve() == repo.resolve()

    lane_wt = next(w for w in data["worktrees"] if Path(w["path"]).resolve() == lane.resolve())
    assert lane_wt["branch"] == "lane"
    assert lane_wt["current"] is False

    # Verify branches properties
    main_b = next(b for b in data["branches"] if b["name"] == "main")
    assert main_b["current"] is True
    lane_b = next(b for b in data["branches"] if b["name"] == "lane")
    assert lane_b["current"] is False


def test_tool_prime(repo, tmp_path):
    server = MCPServer(root=repo)

    # 1. Default guide generation in mapped repo
    res_default = server.execute_tool("cbi_prime", {})
    assert not res_default["isError"]
    guide_text = res_default["content"][0]["text"]
    assert "# cbi: codebase inspector" in guide_text
    assert "cbi tasks" in guide_text

    # 2. Explicit markdown format
    res_md = server.execute_tool("cbi_prime", {"format": "markdown"})
    assert not res_md["isError"]
    assert "# cbi: codebase inspector" in res_md["content"][0]["text"]

    # 3. Explicit text format
    res_text = server.execute_tool("cbi_prime", {"format": "text"})
    assert not res_text["isError"]
    assert "# cbi: codebase inspector" in res_text["content"][0]["text"]

    # 4. Unmapped repo returns not-initialised guide
    unmapped_server = MCPServer(root=tmp_path)
    res_unmapped = unmapped_server.execute_tool("cbi_prime", {})
    assert not res_unmapped["isError"]
    assert "This repo is not mapped yet" in res_unmapped["content"][0]["text"]

    # 5. Incompatible schema returns error and does not erase the database
    incompat_dir = tmp_path / "incompat"
    (incompat_dir / ".cbi").mkdir(parents=True)
    db_path = incompat_dir / ".cbi" / "model.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE sentinel(val TEXT)")
    conn.execute("INSERT INTO sentinel VALUES ('keep-me')")
    conn.execute("PRAGMA user_version = 999")
    conn.commit()
    conn.close()

    incompat_server = MCPServer(root=incompat_dir)
    res_incompat = incompat_server.execute_tool("cbi_prime", {})
    assert res_incompat["isError"]
    assert "schema 999" in res_incompat["content"][0]["text"]

    conn_check = sqlite3.connect(db_path)
    try:
        rows = conn_check.execute("SELECT val FROM sentinel").fetchall()
        assert rows == [("keep-me",)]
    finally:
        conn_check.close()

    # 6. Shared answer cache is not redundantly attached
    conn_orig = server._get_connection()
    try:
        assert any(row[1] == "cache" for row in conn_orig.execute("PRAGMA database_list"))
        guide_text = prime.render(server.root, server.out, conn=conn_orig)
        assert len(guide_text) > 0
        assert any(row[1] == "cache" for row in conn_orig.execute("PRAGMA database_list"))
    finally:
        conn_orig.close()


def test_tool_task(repo):
    server = MCPServer(root=repo)

    # 1. Missing required task_id
    res_no_tid = server.execute_tool("cbi_task", {})
    assert res_no_tid["isError"]
    assert "Missing required argument: 'task_id'" in res_no_tid["content"][0]["text"]

    # 2. Unknown task handling
    res_unknown = server.execute_tool("cbi_task", {"task_id": "nonexistent-task"})
    assert "Unknown task" in res_unknown["content"][0]["text"]

    # Retrieve open tasks from fixture repo
    tasks_res = server.execute_tool("cbi_tasks", {"format": "json"})
    assert not tasks_res["isError"]
    open_tasks = json.loads(tasks_res["content"][0]["text"])
    assert len(open_tasks) > 0
    task = open_tasks[0]
    task_id = task["id"]

    # 3. Brief retrieval in text format (default)
    res_text = server.execute_tool("cbi_task", {"task_id": task_id})
    assert not res_text["isError"]
    text_content = res_text["content"][0]["text"]
    assert f"# Task {task_id}:" in text_content or "node:" in text_content or "instructions" in text_content.lower()

    # 4. JSON format brief retrieval
    res_json = server.execute_tool("cbi_task", {"task_id": task_id, "format": "json"})
    assert not res_json["isError"]
    brief_data = json.loads(res_json["content"][0]["text"])
    assert brief_data["id"] == task_id
    assert "input_hash" in brief_data
    assert "bytes" in brief_data

    # 5. Part handling on non-split task kind (e.g. summarise-files or confirm-structure)
    if task["kind"] not in ("define-concepts", "sketch-screens"):
        res_parts = server.execute_tool("cbi_task", {"task_id": task_id, "parts": True})
        assert res_parts["isError"]
        assert "briefs are not split" in res_parts["content"][0]["text"]

        res_part = server.execute_tool("cbi_task", {"task_id": task_id, "part": 1})
        assert res_part["isError"]
        assert "briefs are not split" in res_part["content"][0]["text"]

    # 6. Answer check validation
    # 6a. Malformed JSON check draft
    res_check_bad_json = server.execute_tool(
        "cbi_task", {"task_id": task_id, "check": "{not-valid-json", "format": "json"}
    )
    assert not res_check_bad_json["isError"]
    bad_json_data = json.loads(res_check_bad_json["content"][0]["text"])
    assert bad_json_data["ok"] is False
    assert any("not valid JSON" in e for e in bad_json_data["errors"])

    # 6b. Invalid schema / bad input hash check draft
    res_check_bad_schema = server.execute_tool(
        "cbi_task", {"task_id": task_id, "check": {"input_hash": "stale-hash"}, "format": "json"}
    )
    assert not res_check_bad_schema["isError"]
    bad_schema_data = json.loads(res_check_bad_schema["content"][0]["text"])
    assert bad_schema_data["ok"] is False
    assert len(bad_schema_data["errors"]) > 0

    # 6c. Valid answer check draft
    if task["kind"] == "summarise-files":
        valid_answer = {
            "input_hash": brief_data["input_hash"],
            "files": [{"path": f["path"], "summary": f"Summary for {f['path']}."} for f in brief_data["files"]],
        }
    elif task["kind"] == "confirm-structure":
        valid_answer = {
            "input_hash": brief_data["input_hash"],
            "deployables": [],
            "packages": [],
        }
    else:
        valid_answer = {"input_hash": brief_data["input_hash"], "summary": "Valid summary."}

    # JSON format valid check
    res_check_valid = server.execute_tool(
        "cbi_task", {"task_id": task_id, "check": json.dumps(valid_answer), "format": "json"}
    )
    assert not res_check_valid["isError"]
    valid_data = json.loads(res_check_valid["content"][0]["text"])
    assert valid_data["ok"] is True
    assert valid_data["warnings"] == []

    # Text format valid check
    res_check_valid_text = server.execute_tool(
        "cbi_task", {"task_id": task_id, "check": json.dumps(valid_answer), "format": "text"}
    )
    assert not res_check_valid_text["isError"]
    assert res_check_valid_text["content"][0]["text"] == "ok"

    # 7. Part handling on a split-capable brief (define-concepts)
    # Find or open confirm-structure, answer it to open define-concepts
    cs_tasks = [t for t in open_tasks if t["kind"] == "confirm-structure"]
    if cs_tasks:
        cs_id = cs_tasks[0]["id"]
        cs_brief = json.loads(server.execute_tool("cbi_task", {"task_id": cs_id, "format": "json"})["content"][0]["text"])
        cs_ans = {"input_hash": cs_brief["input_hash"], "deployables": [], "packages": []}
        submit_res = server.execute_tool("cbi_submit", {"task_id": cs_id, "answer": cs_ans})
        assert not submit_res["isError"]

        new_tasks = json.loads(server.execute_tool("cbi_tasks", {"format": "json"})["content"][0]["text"])
        dc_tasks = [t for t in new_tasks if t["kind"] == "define-concepts"]
        if dc_tasks:
            dc_id = dc_tasks[0]["id"]
            # Index of parts in text format
            res_dc_parts = server.execute_tool("cbi_task", {"task_id": dc_id, "parts": True})
            assert not res_dc_parts["isError"]
            assert f"# Parts for {dc_id}:" in res_dc_parts["content"][0]["text"]

            # Index of parts in JSON format
            res_dc_parts_json = server.execute_tool("cbi_task", {"task_id": dc_id, "parts": True, "format": "json"})
            assert not res_dc_parts_json["isError"]
            parts_payload = json.loads(res_dc_parts_json["content"][0]["text"])
            assert "parts" in parts_payload
            assert len(parts_payload["parts"]) >= 1

            # Retrieve part 1 in text format
            res_p1 = server.execute_tool("cbi_task", {"task_id": dc_id, "part": 1})
            assert not res_p1["isError"]
            assert len(res_p1["content"][0]["text"]) > 0

            # Retrieve part 1 in JSON format
            res_p1_json = server.execute_tool("cbi_task", {"task_id": dc_id, "part": 1, "format": "json"})
            assert not res_p1_json["isError"]

            # Out of bounds part
            res_p_bad = server.execute_tool("cbi_task", {"task_id": dc_id, "part": 99})
            assert res_p_bad["isError"]
            assert "outside 1.." in res_p_bad["content"][0]["text"]


def test_tool_ingest(repo):
    server = MCPServer(root=repo)

    # 1. Successful ingest of an lcov file in text format
    lcov_content = """\
TN:
SF:src/shapes/circle.ts
DA:18,1
end_of_record
"""
    (repo / "coverage.lcov").write_text(lcov_content)

    res_text = server.execute_tool("cbi_ingest", {"files": ["coverage.lcov"]})
    assert not res_text["isError"]
    text = res_text["content"][0]["text"]
    assert "lcov" in text
    assert "1 lines in 1 files" in text
    assert "0 test results" in text

    # 2. Ingest in JSON format
    res_json = server.execute_tool("cbi_ingest", {"files": ["coverage.lcov"], "format": "json"})
    assert not res_json["isError"]
    data = json.loads(res_json["content"][0]["text"])
    assert data["total_lines"] == 1
    assert data["total_files"] == 1
    assert len(data["files"]) == 1
    assert data["files"][0]["format"] == "lcov"
    assert data["files"][0]["lines"] == 1
    assert data["files"][0]["files"] == 1

    # 3. Missing 'files' argument
    res_err1 = server.execute_tool("cbi_ingest", {})
    assert res_err1["isError"]
    assert "Missing or invalid required argument: 'files'" in res_err1["content"][0]["text"]

    # 4. Empty 'files' argument
    res_err2 = server.execute_tool("cbi_ingest", {"files": []})
    assert res_err2["isError"]

    # 5. Non-existent file
    res_err3 = server.execute_tool("cbi_ingest", {"files": ["nonexistent.lcov"]})
    assert res_err3["isError"]
    assert "not loaded" in res_err3["content"][0]["text"]

    # 6. Invalid file format
    (repo / "bad.txt").write_text("not coverage or test results data")
    res_err4 = server.execute_tool("cbi_ingest", {"files": ["bad.txt"]})
    assert res_err4["isError"]
    assert "not loaded" in res_err4["content"][0]["text"]


def test_tool_init(make_repo, tmp_path):
    files_map = {"main.py": "print('hello')\n"}
    root = make_repo(files_map)

    server = MCPServer(root=root)

    # 1. Execute cbi_init in default text mode
    res_text = server.execute_tool("cbi_init", {})
    assert not res_text["isError"]
    text = res_text["content"][0]["text"]
    assert "Created" in text or "ignore" in text
    assert (root / ".cbi" / "ignore").is_file()
    assert (root / ".cbi" / ".gitignore").is_file()

    # 2. Execute cbi_init again in json mode (already initialised)
    res_json = server.execute_tool("cbi_init", {"format": "json"})
    assert not res_json["isError"]
    data = json.loads(res_json["content"][0]["text"])
    assert data["status"] == "ok"
    assert "already initialised" in data["output"]

    # 3. Initialize in team mode
    res_team = server.execute_tool("cbi_init", {"team": True, "format": "json"})
    assert not res_team["isError"]
    team_data = json.loads(res_team["content"][0]["text"])
    assert team_data["team"] is True
    assert (root / ".cbi" / "team.toml").is_file()


def test_install_client_config(tmp_path, monkeypatch):
    from cbi.mcp import install_client_config

    fake_home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(fake_home))
    root = tmp_path / "workspace"
    root.mkdir()

    # 1. Install cursor config
    res_cursor = install_client_config("cursor", root=root)
    assert res_cursor == 0
    cursor_json = fake_home / ".cursor" / "mcp.json"
    assert cursor_json.is_file()
    c_data = json.loads(cursor_json.read_text())
    assert "codebase-inspector" in c_data["mcpServers"]
    assert c_data["mcpServers"]["codebase-inspector"]["command"] == "cbi"

    # 2. Safe merge with existing custom config in cursor
    c_data["mcpServers"]["my-custom-mcp"] = {"command": "custom", "args": ["serve"]}
    c_data["otherSetting"] = True
    cursor_json.write_text(json.dumps(c_data))

    res_cursor2 = install_client_config("cursor", root=root)
    assert res_cursor2 == 0
    c_data2 = json.loads(cursor_json.read_text())
    assert c_data2["otherSetting"] is True
    assert "my-custom-mcp" in c_data2["mcpServers"]
    assert "codebase-inspector" in c_data2["mcpServers"]

    # 3. Install gemini / antigravity
    res_gemini = install_client_config("gemini", root=root)
    assert res_gemini == 0
    gemini_json = fake_home / ".gemini" / "antigravity-cli" / "mcp_config.json"
    assert gemini_json.is_file()
    g_data = json.loads(gemini_json.read_text())
    assert "codebase-inspector" in g_data["mcpServers"]
    gemini_settings = fake_home / ".gemini" / "settings.json"
    assert gemini_settings.is_file()
    s_data = json.loads(gemini_settings.read_text())
    assert "codebase-inspector" in s_data["mcpServers"]

    # 4. Install windsurf
    res_windsurf = install_client_config("windsurf", root=root)
    assert res_windsurf == 0
    windsurf_json = fake_home / ".codeium" / "windsurf" / "mcp_config.json"
    assert windsurf_json.is_file()
    w_data = json.loads(windsurf_json.read_text())
    assert "codebase-inspector" in w_data["mcpServers"]

    # 5. Install vscode (both servers and mcpServers)
    res_vscode = install_client_config("vscode", root=root)
    assert res_vscode == 0
    vscode_json = root / ".vscode" / "mcp.json"
    assert vscode_json.is_file()
    v_data = json.loads(vscode_json.read_text())
    assert "codebase-inspector" in v_data["mcpServers"]
    assert "codebase-inspector" in v_data["servers"]

    # 6. Install claude (Claude Code and Desktop when directory exists)
    desktop_dir = fake_home / "Library" / "Application Support" / "Claude"
    desktop_dir.mkdir(parents=True, exist_ok=True)
    res_claude = install_client_config("claude", root=root)
    assert res_claude == 0
    claude_json = fake_home / ".claude.json"
    assert claude_json.is_file()
    cl_data = json.loads(claude_json.read_text())
    assert "codebase-inspector" in cl_data["mcpServers"]
    desktop_json = desktop_dir / "claude_desktop_config.json"
    assert desktop_json.is_file()
    d_data = json.loads(desktop_json.read_text())
    assert d_data["mcpServers"]["codebase-inspector"]["args"] == ["mcp", "--repo", str(root)]

    # 7. Install all
    res_all = install_client_config("all", root=root)
    assert res_all == 0
    assert len(res_all) >= 5

    # 8. Unparseable/corrupted config is preserved, not overwritten, and returns failure
    corrupt_file = fake_home / ".cursor" / "mcp.json"
    corrupt_file.write_text("{bad json syntax")
    res_corrupt = install_client_config("cursor", root=root)
    assert res_corrupt != 0
    assert corrupt_file.read_text() == "{bad json syntax"

    # 9. Test CLI integration
    monkeypatch.chdir(root)
    assert main(["mcp", "--install", "cursor"]) == 1
    # Restore valid config
    corrupt_file.write_text(json.dumps({"mcpServers": {}}))
    assert main(["mcp", "--install", "cursor"]) == 0
    assert main(["mcp", "--install"]) == 0






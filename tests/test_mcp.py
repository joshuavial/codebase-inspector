"""Tests for the native stdio MCP server."""

import io
import json
import sqlite3
import pytest

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
    expected = {"cbi_status", "cbi_context", "cbi_tests_for", "cbi_search", "cbi_hotspots"}
    assert expected.issubset(tool_names)

    for tool in tools:
        assert "description" in tool
        assert "inputSchema" in tool
        assert tool["inputSchema"]["type"] == "object"


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

    # Missing node argument
    req_missing = {
        "jsonrpc": "2.0",
        "id": 21,
        "method": "tools/call",
        "params": {"name": "cbi_context", "arguments": {}},
    }
    resp_missing = server.handle_request(req_missing)
    assert resp_missing["result"]["isError"]
    assert "Missing required argument" in resp_missing["result"]["content"][0]["text"]

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


def test_tool_diff(repo):
    server = MCPServer(root=repo)
    model_file = str(repo / ".cbi" / "model.db")
    resp = server.execute_tool("cbi_diff", {"base_model": model_file, "head_model": model_file})
    assert not resp["isError"]
    assert "no architectural changes" in resp["content"][0]["text"]


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


def test_concurrent_requests_stress(repo):
    import concurrent.futures

    server = MCPServer(root=repo)

    tools_and_args = [
        ("cbi_status", {"format": "text"}),
        ("cbi_search", {"query": "Circle"}),
        ("cbi_tests_for", {"target": "src/shapes/circle.ts"}),
        ("cbi_hotspots", {"metric": "fan-in"}),
        ("cbi_query", {"sql": "SELECT id, name FROM nodes WHERE kind = 'symbol'", "format": "json"}),
        ("cbi_tasks", {"format": "json"}),
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


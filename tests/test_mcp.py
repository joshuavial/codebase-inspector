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

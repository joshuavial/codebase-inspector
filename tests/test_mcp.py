"""Tests for the native stdio MCP server."""

import io
import json
import sqlite3
import sys
import urllib.parse
from pathlib import Path
import pytest

from cbi import files, prime
from cbi.cli import main
from cbi.mcp import (
    MAX_MULTILINE_LINES,
    MCPServer,
    MessageParseError,
    NULL_PAYLOAD,
    PROMPTS,
    PROTOCOL_VERSION,
    RESOURCE_TEMPLATES,
    RESOURCES,
    SERVER_NAME,
    SERVER_VERSION,
    TOOLS,
    read_message,
    write_message,
)

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
    assert result["capabilities"] == {
        "tools": {},
        "resources": {"subscribe": False, "listChanged": False},
        "prompts": {"listChanged": False},
    }
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

    tools_by_name = {t["name"]: t for t in tools}
    assert "kind" in tools_by_name["cbi_status"]["inputSchema"]["properties"]
    assert "kind" in tools_by_name["cbi_check"]["inputSchema"]["properties"]
    assert "offset" in tools_by_name["cbi_tasks"]["inputSchema"]["properties"]
    assert tools_by_name["cbi_tasks"]["inputSchema"]["properties"]["offset"]["type"] == "integer"
    assert "offset" in tools_by_name["cbi_query"]["inputSchema"]["properties"]
    assert tools_by_name["cbi_query"]["inputSchema"]["properties"]["offset"]["type"] == "integer"
    assert "offset" in tools_by_name["cbi_search"]["inputSchema"]["properties"]
    assert tools_by_name["cbi_search"]["inputSchema"]["properties"]["offset"]["type"] == "integer"
    assert "offset" in tools_by_name["cbi_hotspots"]["inputSchema"]["properties"]
    assert tools_by_name["cbi_hotspots"]["inputSchema"]["properties"]["offset"]["type"] == "integer"
    assert "base_model" in tools_by_name["cbi_diff"]["inputSchema"]["properties"]
    assert tools_by_name["cbi_diff"]["inputSchema"]["properties"]["base_model"]["type"] == "string"
    assert "head_model" in tools_by_name["cbi_diff"]["inputSchema"]["properties"]
    assert tools_by_name["cbi_diff"]["inputSchema"]["properties"]["head_model"]["type"] == "string"
    assert "forbid" in tools_by_name["cbi_deps"]["inputSchema"]["properties"]
    assert tools_by_name["cbi_deps"]["inputSchema"]["properties"]["forbid"]["type"] == "array"
    assert tools_by_name["cbi_deps"]["inputSchema"]["properties"]["forbid"]["items"]["type"] == "string"

    query_tools_with_ref = [
        "cbi_show",
        "cbi_context",
        "cbi_search",
        "cbi_tests_for",
        "cbi_endpoints",
        "cbi_tables",
        "cbi_query",
        "cbi_concepts",
        "cbi_deps",
        "cbi_cycles",
        "cbi_orphans",
        "cbi_hotspots",
        "cbi_status",
        "cbi_tasks",
        "cbi_task",
        "cbi_submit",
    ]
    for name in query_tools_with_ref:
        assert "ref" in tools_by_name[name]["inputSchema"]["properties"]
        assert tools_by_name[name]["inputSchema"]["properties"]["ref"]["type"] == "string"

    for name in ("cbi_tests_for", "cbi_search", "cbi_hotspots"):
        props = tools_by_name[name]["inputSchema"]["properties"]
        assert "format" in props
        assert props["format"]["type"] == "string"
        assert props["format"]["enum"] == ["text", "json"]


def test_resources_list():
    server = MCPServer()
    req = {"jsonrpc": "2.0", "id": 10, "method": "resources/list"}
    resp = server.handle_request(req)
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == 10
    resources = resp["result"]["resources"]
    uris = {r["uri"] for r in resources}
    expected_uris = {
        "cbi://system/overview",
        "cbi://model/status",
        "cbi://model/schema",
        "cbi://concepts",
        "cbi://tasks",
    }
    assert uris == expected_uris
    for r in resources:
        assert "name" in r
        assert "description" in r
        assert "mimeType" in r


def test_resources_templates_list():
    server = MCPServer()
    req = {"jsonrpc": "2.0", "id": 11, "method": "resources/templates/list"}
    resp = server.handle_request(req)
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == 11
    templates = resp["result"]["resourceTemplates"]
    template_uris = {t["uriTemplate"] for t in templates}
    assert template_uris == {
        "cbi://node/{id}",
        "cbi://context/{node}",
        "cbi://tasks/{id}",
        "cbi://diagnostics/{kind}",
    }
    for t in templates:
        assert "name" in t
        assert "description" in t
        assert "mimeType" in t


def test_resources_read_static(repo):
    server = MCPServer(root=repo)

    # 1. cbi://system/overview
    req = {"jsonrpc": "2.0", "id": 20, "method": "resources/read", "params": {"uri": "cbi://system/overview"}}
    resp = server.handle_request(req)
    assert resp["id"] == 20
    assert "error" not in resp
    contents = resp["result"]["contents"]
    assert len(contents) == 1
    assert contents[0]["uri"] == "cbi://system/overview"
    assert contents[0]["mimeType"] == "text/markdown"
    assert "Architecture" in contents[0]["text"] or "System" in contents[0]["text"] or "#" in contents[0]["text"]

    # 2. cbi://model/status
    req = {"jsonrpc": "2.0", "id": 21, "method": "resources/read", "params": {"uri": "cbi://model/status"}}
    resp = server.handle_request(req)
    assert resp["id"] == 21
    assert "error" not in resp
    contents = resp["result"]["contents"]
    assert len(contents) == 1
    assert contents[0]["uri"] == "cbi://model/status"
    assert contents[0]["mimeType"] == "application/json"
    status_data = json.loads(contents[0]["text"])
    assert isinstance(status_data, dict)

    # 3. cbi://model/schema
    req = {"jsonrpc": "2.0", "id": 22, "method": "resources/read", "params": {"uri": "cbi://model/schema"}}
    resp = server.handle_request(req)
    assert resp["id"] == 22
    assert "error" not in resp
    contents = resp["result"]["contents"]
    assert len(contents) == 1
    assert contents[0]["uri"] == "cbi://model/schema"
    assert contents[0]["mimeType"] == "text/plain"
    schema_text = contents[0]["text"]
    assert "CREATE TABLE" in schema_text
    assert "nodes" in schema_text
    assert "edges" in schema_text

    # 4. cbi://concepts
    req = {"jsonrpc": "2.0", "id": 23, "method": "resources/read", "params": {"uri": "cbi://concepts"}}
    resp = server.handle_request(req)
    assert resp["id"] == 23
    assert "error" not in resp
    contents = resp["result"]["contents"]
    assert len(contents) == 1
    assert contents[0]["uri"] == "cbi://concepts"
    assert contents[0]["mimeType"] == "application/json"
    concepts_data = json.loads(contents[0]["text"])
    assert isinstance(concepts_data, list)

    # 5. cbi://tasks
    req = {"jsonrpc": "2.0", "id": 24, "method": "resources/read", "params": {"uri": "cbi://tasks"}}
    resp = server.handle_request(req)
    assert resp["id"] == 24
    assert "error" not in resp
    contents = resp["result"]["contents"]
    assert len(contents) == 1
    assert contents[0]["uri"] == "cbi://tasks"
    assert contents[0]["mimeType"] == "application/json"
    tasks_data = json.loads(contents[0]["text"])
    assert isinstance(tasks_data, list)

    # 6. Aliases: cbi://overview, cbi://stats, cbi://schema, cbi://hotspots
    for alias, expected_mime in [
        ("cbi://overview", "text/markdown"),
        ("cbi://stats", "application/json"),
        ("cbi://schema", "text/plain"),
        ("cbi://hotspots", "application/json"),
    ]:
        req = {"jsonrpc": "2.0", "id": 25, "method": "resources/read", "params": {"uri": alias}}
        resp = server.handle_request(req)
        assert resp["id"] == 25
        assert "error" not in resp
        assert resp["result"]["contents"][0]["mimeType"] == expected_mime


def test_resources_read_templates(repo):
    server = MCPServer(root=repo)

    # 1. cbi://node/{id} with plain path
    req = {"jsonrpc": "2.0", "id": 30, "method": "resources/read", "params": {"uri": "cbi://node/src/shapes/circle.ts"}}
    resp = server.handle_request(req)
    assert resp["id"] == 30
    assert "error" not in resp
    contents = resp["result"]["contents"]
    assert len(contents) == 1
    assert contents[0]["uri"] == "cbi://node/src/shapes/circle.ts"
    assert contents[0]["mimeType"] == "application/json"
    node_data = json.loads(contents[0]["text"])
    assert node_data["path"] == "src/shapes/circle.ts"

    # 2. cbi://node/{id} with full node id URL-encoded
    encoded_uri = f"cbi://node/{urllib.parse.quote(CIRCLE, safe='')}"
    req = {"jsonrpc": "2.0", "id": 31, "method": "resources/read", "params": {"uri": encoded_uri}}
    resp = server.handle_request(req)
    assert resp["id"] == 31
    assert "error" not in resp
    contents = resp["result"]["contents"]
    node_data = json.loads(contents[0]["text"])
    assert node_data["id"] == CIRCLE

    # 3. cbi://context/{node}
    req = {"jsonrpc": "2.0", "id": 32, "method": "resources/read", "params": {"uri": "cbi://context/src/shapes/circle.ts"}}
    resp = server.handle_request(req)
    assert resp["id"] == 32
    assert "error" not in resp
    contents = resp["result"]["contents"]
    assert len(contents) == 1
    assert contents[0]["uri"] == "cbi://context/src/shapes/circle.ts"
    assert contents[0]["mimeType"] == "text/markdown"
    assert "Circle" in contents[0]["text"] or "circle.ts" in contents[0]["text"]

    # 4. cbi://tasks/{id}
    tasks_req = {"jsonrpc": "2.0", "id": 33, "method": "resources/read", "params": {"uri": "cbi://tasks"}}
    tasks_resp = server.handle_request(tasks_req)
    open_tasks = json.loads(tasks_resp["result"]["contents"][0]["text"])
    assert len(open_tasks) > 0
    task_id = open_tasks[0]["id"]

    req = {"jsonrpc": "2.0", "id": 34, "method": "resources/read", "params": {"uri": f"cbi://tasks/{task_id}"}}
    resp = server.handle_request(req)
    assert resp["id"] == 34
    assert "error" not in resp
    contents = resp["result"]["contents"]
    assert len(contents) == 1
    assert contents[0]["uri"] == f"cbi://tasks/{task_id}"
    assert contents[0]["mimeType"] == "application/json"
    task_detail = json.loads(contents[0]["text"])
    assert task_detail["id"] == task_id
    assert "instructions" in task_detail

    # 5. cbi://diagnostics/{kind}
    conn = sqlite3.connect(repo / ".cbi" / "model.db")
    with conn:
        conn.execute(
            "INSERT INTO diagnostics (node_id, kind, detail) VALUES (?, 'unmatched_test', 'test does not match')",
            (f"{WS}:src/shapes/circle.ts",),
        )
        conn.execute(
            "INSERT INTO diagnostics (node_id, kind, detail) VALUES (?, 'unsupported_test_mechanism', 'framework not supported')",
            (f"{WS}:src/shapes/circle.ts",),
        )
    conn.close()

    req = {"jsonrpc": "2.0", "id": 35, "method": "resources/read", "params": {"uri": "cbi://diagnostics/unmatched_test"}}
    resp = server.handle_request(req)
    assert resp["id"] == 35
    assert "error" not in resp
    contents = resp["result"]["contents"]
    assert len(contents) == 1
    assert contents[0]["uri"] == "cbi://diagnostics/unmatched_test"
    assert contents[0]["mimeType"] == "application/json"
    diag_data = json.loads(contents[0]["text"])
    assert diag_data["kind"] == "unmatched_test"
    assert diag_data["count"] >= 1
    assert any(d["node_id"] == f"{WS}:src/shapes/circle.ts" for d in diag_data["diagnostics"])

    req = {"jsonrpc": "2.0", "id": 36, "method": "resources/read", "params": {"uri": "cbi://diagnostics/unsupported_test_mechanism"}}
    resp = server.handle_request(req)
    assert resp["id"] == 36
    assert "error" not in resp
    diag_data = json.loads(resp["result"]["contents"][0]["text"])
    assert diag_data["kind"] == "unsupported_test_mechanism"
    assert diag_data["count"] >= 1

    # Nonexistent kind returns count=0
    req = {"jsonrpc": "2.0", "id": 37, "method": "resources/read", "params": {"uri": "cbi://diagnostics/nonexistent_kind"}}
    resp = server.handle_request(req)
    assert resp["id"] == 37
    assert "error" not in resp
    diag_data = json.loads(resp["result"]["contents"][0]["text"])
    assert diag_data["kind"] == "nonexistent_kind"
    assert diag_data["count"] == 0


def test_resources_read_errors(repo):
    server = MCPServer(root=repo)

    # 1. Unknown resource URI
    req = {"jsonrpc": "2.0", "id": 40, "method": "resources/read", "params": {"uri": "cbi://unknown/resource"}}
    resp = server.handle_request(req)
    assert resp["id"] == 40
    assert "error" in resp
    assert resp["error"]["code"] == -32602
    assert "Unknown resource URI" in resp["error"]["message"]

    # 2. Missing URI param
    req = {"jsonrpc": "2.0", "id": 41, "method": "resources/read", "params": {}}
    resp = server.handle_request(req)
    assert resp["id"] == 41
    assert "error" in resp
    assert resp["error"]["code"] == -32602

    # 3. Nonexistent node
    req = {"jsonrpc": "2.0", "id": 42, "method": "resources/read", "params": {"uri": "cbi://node/nonexistent.py"}}
    resp = server.handle_request(req)
    assert resp["id"] == 42
    assert "error" in resp
    assert resp["error"]["code"] == -32602

    # 4. Nonexistent task
    req = {"jsonrpc": "2.0", "id": 43, "method": "resources/read", "params": {"uri": "cbi://tasks/nonexistent-task-id"}}
    resp = server.handle_request(req)
    assert resp["id"] == 43
    assert "error" in resp
    assert resp["error"]["code"] == -32602
    assert "Unknown task" in resp["error"]["message"]

    # 5. Empty task id
    req = {"jsonrpc": "2.0", "id": 44, "method": "resources/read", "params": {"uri": "cbi://tasks/"}}
    resp = server.handle_request(req)
    assert resp["id"] == 44
    assert "error" in resp
    assert resp["error"]["code"] == -32602

    # 6. Empty diagnostic kind
    req = {"jsonrpc": "2.0", "id": 45, "method": "resources/read", "params": {"uri": "cbi://diagnostics/"}}
    resp = server.handle_request(req)
    assert resp["id"] == 45
    assert "error" in resp
    assert resp["error"]["code"] == -32602


def test_prompts_list():
    server = MCPServer()
    req = {"jsonrpc": "2.0", "id": 50, "method": "prompts/list"}
    resp = server.handle_request(req)
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == 50
    prompts = resp["result"]["prompts"]
    names = {p["name"] for p in prompts}
    assert names == {
        "cbi_architecture_orientation",
        "cbi_review_pr",
        "cbi_judgement_task",
    }
    for p in prompts:
        assert "description" in p
        assert "arguments" in p


def test_prompts_get_architecture_orientation():
    server = MCPServer()

    # Without arguments
    req = {
        "jsonrpc": "2.0",
        "id": 60,
        "method": "prompts/get",
        "params": {"name": "cbi_architecture_orientation"},
    }
    resp = server.handle_request(req)
    assert resp["id"] == 60
    assert "error" not in resp
    result = resp["result"]
    assert "Guide an agent" in result["description"]
    msg = result["messages"][0]
    assert msg["role"] == "user"
    assert "cbi_prime" in msg["content"]["text"]
    assert "cbi_status" in msg["content"]["text"]
    assert "cbi_concepts" in msg["content"]["text"]
    assert "cbi_context" in msg["content"]["text"]

    # With focus argument
    req = {
        "jsonrpc": "2.0",
        "id": 61,
        "method": "prompts/get",
        "params": {"name": "cbi_architecture_orientation", "arguments": {"focus": "auth-layer"}},
    }
    resp = server.handle_request(req)
    assert resp["id"] == 61
    assert "error" not in resp
    msg = resp["result"]["messages"][0]
    assert "auth-layer" in msg["content"]["text"]


def test_prompts_get_review_pr():
    server = MCPServer()

    # Without arguments (defaults base=main, head=HEAD)
    req = {
        "jsonrpc": "2.0",
        "id": 70,
        "method": "prompts/get",
        "params": {"name": "cbi_review_pr"},
    }
    resp = server.handle_request(req)
    assert resp["id"] == 70
    assert "error" not in resp
    result = resp["result"]
    assert "Perform an architectural code review" in result["description"]
    msg = result["messages"][0]
    assert msg["role"] == "user"
    assert "main" in msg["content"]["text"]
    assert "HEAD" in msg["content"]["text"]
    assert "cbi_diff" in msg["content"]["text"]
    assert "cbi_review" in msg["content"]["text"]
    assert "cbi_check" in msg["content"]["text"]

    # With custom base and head
    req = {
        "jsonrpc": "2.0",
        "id": 71,
        "method": "prompts/get",
        "params": {"name": "cbi_review_pr", "arguments": {"base": "release-1.0", "head": "feature-x"}},
    }
    resp = server.handle_request(req)
    assert resp["id"] == 71
    msg = resp["result"]["messages"][0]
    assert "release-1.0" in msg["content"]["text"]
    assert "feature-x" in msg["content"]["text"]


def test_prompts_get_judgement_task(repo):
    server = MCPServer(root=repo)

    # Missing task_id -> error -32602
    req = {
        "jsonrpc": "2.0",
        "id": 80,
        "method": "prompts/get",
        "params": {"name": "cbi_judgement_task"},
    }
    resp = server.handle_request(req)
    assert resp["id"] == 80
    assert "error" in resp
    assert resp["error"]["code"] == -32602
    assert "Missing required argument" in resp["error"]["message"]

    # With task_id
    req = {
        "jsonrpc": "2.0",
        "id": 81,
        "method": "prompts/get",
        "params": {"name": "cbi_judgement_task", "arguments": {"task_id": "test-task-123"}},
    }
    resp = server.handle_request(req)
    assert resp["id"] == 81
    assert "error" not in resp
    msg = resp["result"]["messages"][0]
    assert "test-task-123" in msg["content"]["text"]
    assert "cbi_task(task_id='test-task-123', parts=True)" in msg["content"]["text"]
    assert "cbi_submit" in msg["content"]["text"]


def test_prompts_get_unknown():
    server = MCPServer()

    # Unknown prompt name
    req = {
        "jsonrpc": "2.0",
        "id": 90,
        "method": "prompts/get",
        "params": {"name": "nonexistent_prompt"},
    }
    resp = server.handle_request(req)
    assert resp["id"] == 90
    assert "error" in resp
    assert resp["error"]["code"] == -32602
    assert "Unknown prompt: nonexistent_prompt" in resp["error"]["message"]

    # Missing name
    req = {
        "jsonrpc": "2.0",
        "id": 91,
        "method": "prompts/get",
        "params": {},
    }
    resp = server.handle_request(req)
    assert resp["id"] == 91
    assert "error" in resp
    assert resp["error"]["code"] == -32602


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


def test_tools_call_status_kind(repo):
    server = MCPServer(root=repo)
    conn = sqlite3.connect(repo / ".cbi" / "model.db")
    with conn:
        conn.execute(
            "INSERT INTO diagnostics (node_id, kind, detail) VALUES (?, 'unmatched_test', 'test does not match')",
            (f"{WS}:src/shapes/circle.ts",),
        )
        conn.execute(
            "INSERT INTO diagnostics (node_id, kind, detail) VALUES (?, 'unsupported_test_mechanism', 'framework not supported')",
            (f"{WS}:src/shapes/circle.ts",),
        )
    conn.close()

    # Filter by diagnostic kind in JSON
    resp_filtered = server.execute_tool("cbi_status", {"kind": "unmatched_test", "format": "json"})
    assert not resp_filtered["isError"]
    data = json.loads(resp_filtered["content"][0]["text"])
    assert "unmatched_test" in data["diagnostics"]
    assert "unsupported_test_mechanism" not in data["diagnostics"]

    # Filter by diagnostic kind in text
    resp_text = server.execute_tool("cbi_status", {"kind": "unmatched_test", "format": "text"})
    assert not resp_text["isError"]
    assert "unmatched_test" in resp_text["content"][0]["text"]
    assert "unsupported_test_mechanism" not in resp_text["content"][0]["text"]


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

    # JSON format
    req_json = {
        "jsonrpc": "2.0",
        "id": 32,
        "method": "tools/call",
        "params": {"name": "cbi_tests_for", "arguments": {"target": "src/shapes/circle.ts", "format": "json"}},
    }
    resp_json = server.handle_request(req_json)
    assert resp_json["id"] == 32
    assert not resp_json["result"]["isError"]
    data = json.loads(resp_json["result"]["content"][0]["text"])
    assert "node" in data
    assert "tests" in data
    assert any("circle.test.ts" in t["path"] or "measures the area" in t["name"] for t in data["tests"])

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

    # JSON format
    req_json = {
        "jsonrpc": "2.0",
        "id": 42,
        "method": "tools/call",
        "params": {"name": "cbi_search", "arguments": {"query": "Circle", "format": "json"}},
    }
    resp_json = server.handle_request(req_json)
    assert resp_json["id"] == 42
    assert not resp_json["result"]["isError"]
    data = json.loads(resp_json["result"]["content"][0]["text"])
    assert isinstance(data, list)
    assert any("Circle" in item["name"] for item in data)

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

    # JSON format
    req_json = {
        "jsonrpc": "2.0",
        "id": 51,
        "method": "tools/call",
        "params": {"name": "cbi_hotspots", "arguments": {"metric": "fan-in", "format": "json"}},
    }
    resp_json = server.handle_request(req_json)
    assert resp_json["id"] == 51
    assert not resp_json["result"]["isError"]
    data = json.loads(resp_json["result"]["content"][0]["text"])
    assert data["by"] == "fan-in"
    assert "files" in data


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


def test_read_message_malformed_newline_fails_fast():
    """Verify malformed newline-delimited JSON raises MessageParseError without consuming subsequent lines."""
    raw_stream = io.BytesIO(
        b"{invalid json\n"
        b'{"jsonrpc": "2.0", "id": 1, "method": "ping"}\n'
    )
    with pytest.raises(MessageParseError) as exc_info:
        read_message(raw_stream)
    assert exc_info.value.is_content_length is False

    # The next line on the stream remains intact and parses cleanly
    parsed, is_cl = read_message(raw_stream)
    assert parsed == {"jsonrpc": "2.0", "id": 1, "method": "ping"}
    assert is_cl is False


def test_read_message_multiline_buffering_and_limits():
    """Verify multiline pretty-printed JSON parses and buffering limits are enforced."""
    # 1. Valid multiline pretty-printed JSON
    pretty_json = (
        b"{\n"
        b'  "jsonrpc": "2.0",\n'
        b'  "id": 10,\n'
        b'  "method": "ping"\n'
        b"}\n"
    )
    buf = io.BytesIO(pretty_json)
    parsed, is_cl = read_message(buf)
    assert parsed == {"jsonrpc": "2.0", "id": 10, "method": "ping"}
    assert is_cl is False

    # 2. Multiline with unparseable token on line 2 fails fast without reading line 3
    bad_multiline = io.BytesIO(
        b"{\n"
        b"  invalid: token\n"
        b'{"jsonrpc": "2.0", "id": 11, "method": "ping"}\n'
    )
    with pytest.raises(MessageParseError) as exc_info:
        read_message(bad_multiline)
    assert exc_info.value.is_content_length is False

    # 3. Multiline exceeding MAX_MULTILINE_LINES raises MessageParseError
    unclosed = io.BytesIO(b"[\n" + (b"  1,\n" * (MAX_MULTILINE_LINES + 5)))
    with pytest.raises(MessageParseError):
        read_message(unclosed)


def test_read_message_null_and_non_dict_payloads():
    """Verify 'null' payload returns NULL_PAYLOAD and non-dict inputs produce -32600."""
    server = MCPServer()

    # 1. 'null' newline input returns NULL_PAYLOAD
    buf = io.BytesIO(b"null\n")
    parsed, is_cl = read_message(buf)
    assert parsed is NULL_PAYLOAD
    assert is_cl is False

    # handle_request on NULL_PAYLOAD returns -32600 Invalid Request
    resp = server.handle_request(parsed)
    assert resp["error"]["code"] == -32600
    assert "Invalid Request" in resp["error"]["message"]

    # 2. Number input
    buf = io.BytesIO(b"9999\n")
    parsed, _ = read_message(buf)
    assert parsed == 9999
    resp = server.handle_request(parsed)
    assert resp["error"]["code"] == -32600

    # 3. String input
    buf = io.BytesIO(b'"just a string"\n')
    parsed, _ = read_message(buf)
    assert parsed == "just a string"
    resp = server.handle_request(parsed)
    assert resp["error"]["code"] == -32600

    # 4. List input
    buf = io.BytesIO(b'["list", "not", "dict"]\n')
    parsed, _ = read_message(buf)
    assert isinstance(parsed, list)
    resp = server.handle_request(parsed)
    assert resp["error"]["code"] == -32600

    # 5. Missing or invalid 'method' member in request object
    resp = server.handle_request({"jsonrpc": "2.0", "id": 1})
    assert resp["error"]["code"] == -32600
    assert "method" in resp["error"]["message"]

    resp = server.handle_request({"jsonrpc": "2.0", "id": 2, "method": 1234})
    assert resp["error"]["code"] == -32600

    # 6. Non-dict 'params' member returns -32602
    resp = server.handle_request({"jsonrpc": "2.0", "id": 3, "method": "ping", "params": "not a dict"})
    assert resp["error"]["code"] == -32602
    assert "params" in resp["error"]["message"]


def test_resources_read_unsupported_schemes_and_edge_cases(repo):
    """Verify unsupported URI schemes and empty URIs return clean -32602 errors."""
    server = MCPServer(root=repo)

    for bad_uri in [
        "file:///etc/passwd",
        "file:///path/to/repo/src/calc.py",
        "http://example.com/api",
        "https://example.com/resource",
        "ftp://ftp.example.com/file",
        "custom://scheme/foo",
        "cbi:no-slashes",
        "",
        "   ",
    ]:
        req = {"jsonrpc": "2.0", "id": 50, "method": "resources/read", "params": {"uri": bad_uri}}
        resp = server.handle_request(req)
        assert resp["id"] == 50
        assert "error" in resp
        assert resp["error"]["code"] == -32602

    # Non-string URI
    req = {"jsonrpc": "2.0", "id": 51, "method": "resources/read", "params": {"uri": 12345}}
    resp = server.handle_request(req)
    assert resp["id"] == 51
    assert resp["error"]["code"] == -32602


def test_prompts_get_invalid_parameters_hardening():
    """Verify prompt parameter validation for invalid names and arguments."""
    server = MCPServer()

    # 1. Non-string prompt names
    for bad_name in [1234, None, "", "   "]:
        req = {"jsonrpc": "2.0", "id": 60, "method": "prompts/get", "params": {"name": bad_name}}
        resp = server.handle_request(req)
        assert resp["id"] == 60
        assert resp["error"]["code"] == -32602

    # 2. Non-dict arguments parameter
    req = {
        "jsonrpc": "2.0",
        "id": 61,
        "method": "prompts/get",
        "params": {"name": "cbi_architecture_orientation", "arguments": "not-a-dict"},
    }
    resp = server.handle_request(req)
    assert resp["id"] == 61
    assert resp["error"]["code"] == -32602

    # 3. cbi_judgement_task with missing or empty task_id
    for bad_id in [None, "", "   "]:
        args = {"task_id": bad_id} if bad_id is not None else {}
        req = {
            "jsonrpc": "2.0",
            "id": 62,
            "method": "prompts/get",
            "params": {"name": "cbi_judgement_task", "arguments": args},
        }
        resp = server.handle_request(req)
        assert resp["id"] == 62
        assert resp["error"]["code"] == -32602


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

    # Assert offset is declared in cbi_tasks inputSchema properties
    tool_def = next(t for t in TOOLS if t["name"] == "cbi_tasks")
    assert "offset" in tool_def["inputSchema"]["properties"]
    assert tool_def["inputSchema"]["properties"]["offset"]["type"] == "integer"

    resp = server.execute_tool("cbi_tasks", {})
    assert not resp["isError"]
    # In fixture repo with initial scan, tasks may exist or be empty
    assert isinstance(resp["content"][0]["text"], str)

    resp_json = server.execute_tool("cbi_tasks", {"format": "json"})
    assert not resp_json["isError"]
    parsed = json.loads(resp_json["content"][0]["text"])
    assert isinstance(parsed, list)

    # Test invoking cbi_tasks with offset
    resp_offset_0 = server.execute_tool("cbi_tasks", {"format": "json", "offset": 0})
    assert not resp_offset_0["isError"]
    assert json.loads(resp_offset_0["content"][0]["text"]) == parsed

    resp_offset_1 = server.execute_tool("cbi_tasks", {"format": "json", "offset": 1})
    assert not resp_offset_1["isError"]
    parsed_offset_1 = json.loads(resp_offset_1["content"][0]["text"])
    assert isinstance(parsed_offset_1, list)
    if len(parsed) > 1:
        assert parsed_offset_1 == parsed[1:]
    else:
        assert parsed_offset_1 == []

    res_err = server.execute_tool("cbi_tasks", {"task_id": "nonexistent-task"})
    assert res_err["isError"] is True
    assert "Unknown task" in res_err["content"][0]["text"]


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

    res_err = server.execute_tool("cbi_diff", {"base_model": "nonexistent_model.db", "head_model": model_file})
    assert res_err["isError"] is True
    assert "Diff error" in res_err["content"][0]["text"]


def test_tool_diff_drilldown(repo):
    git = lambda *args: files._git(
        repo, "-c", "user.name=test", "-c", "user.email=test@example.com", "-c", "commit.gpgsign=false", *args,
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


def test_tool_query_security_hardening(repo):
    server = MCPServer(root=repo)

    # 1. PRAGMA is disallowed in first_token
    resp_pragma = server.execute_tool("cbi_query", {"sql": "PRAGMA database_list"})
    assert resp_pragma["isError"] is True
    assert "Only read-only queries are permitted (got PRAGMA)." in resp_pragma["content"][0]["text"]

    resp_pragma_schema = server.execute_tool("cbi_query", {"sql": "PRAGMA table_info(nodes)"})
    assert resp_pragma_schema["isError"] is True
    assert "Only read-only queries are permitted (got PRAGMA)." in resp_pragma_schema["content"][0]["text"]

    # 2. SQLite authorizer blocks ATTACH / DETACH / PRAGMA
    # Direct ATTACH
    resp_attach = server.execute_tool("cbi_query", {"sql": "ATTACH DATABASE 'foo.db' AS foo"})
    assert resp_attach["isError"] is True
    assert "Only read-only queries are permitted (got ATTACH)." in resp_attach["content"][0]["text"]

    # EXPLAIN ATTACH (bypasses first token check, blocked by authorizer)
    resp_exp_attach = server.execute_tool("cbi_query", {"sql": "EXPLAIN ATTACH DATABASE 'foo.db' AS foo"})
    assert resp_exp_attach["isError"] is True
    assert "not authorized" in resp_exp_attach["content"][0]["text"]

    # EXPLAIN PRAGMA (bypasses first token check, blocked by authorizer)
    resp_exp_pragma = server.execute_tool("cbi_query", {"sql": "EXPLAIN PRAGMA database_list"})
    assert resp_exp_pragma["isError"] is True
    assert "not authorized" in resp_exp_pragma["content"][0]["text"]

    # Table-valued function pragma_database_list (bypasses first token check, blocked by authorizer)
    resp_tvf_pragma = server.execute_tool("cbi_query", {"sql": "SELECT * FROM pragma_database_list()"})
    assert resp_tvf_pragma["isError"] is True
    assert "not authorized" in resp_tvf_pragma["content"][0]["text"]


def test_tool_query_timeout(repo):
    server = MCPServer(root=repo)

    # Runaway recursive query hits 5.0s execution timeout
    resp_timeout = server.execute_tool("cbi_query", {
        "sql": "WITH RECURSIVE cnt(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM cnt) SELECT count(*) FROM cnt;"
    })
    assert resp_timeout["isError"] is True
    assert "Query execution exceeded timeout limit (5.0s)" in resp_timeout["content"][0]["text"]


def test_mcp_pagination_bounds(repo):
    server = MCPServer(root=repo)

    # Negative offset rejection across tools
    res_tasks_neg = server.execute_tool("cbi_tasks", {"offset": -1})
    assert res_tasks_neg["isError"] is True
    assert "offset must be non-negative" in res_tasks_neg["content"][0]["text"]

    res_search_neg = server.execute_tool("cbi_search", {"query": "Circle", "offset": -5})
    assert res_search_neg["isError"] is True
    assert "offset must be non-negative" in res_search_neg["content"][0]["text"]

    res_hotspots_neg = server.execute_tool("cbi_hotspots", {"offset": -10})
    assert res_hotspots_neg["isError"] is True
    assert "offset must be non-negative" in res_hotspots_neg["content"][0]["text"]

    res_query_neg = server.execute_tool("cbi_query", {"sql": "SELECT 1", "offset": -1})
    assert res_query_neg["isError"] is True
    assert "offset must be non-negative" in res_query_neg["content"][0]["text"]

    # Clamping excessively large limit and offset
    # cbi_tasks
    res_tasks_large = server.execute_tool("cbi_tasks", {"limit": 999999, "offset": 999999, "format": "json"})
    assert not res_tasks_large["isError"]
    assert json.loads(res_tasks_large["content"][0]["text"]) == []

    # cbi_search with limit / max_results
    res_search_large = server.execute_tool("cbi_search", {"query": "Circle", "limit": 999999, "format": "json"})
    assert not res_search_large["isError"]

    res_search_mr = server.execute_tool("cbi_search", {"query": "Circle", "max_results": 999999, "format": "json"})
    assert not res_search_mr["isError"]

    # cbi_hotspots with limit
    res_hotspots_large = server.execute_tool("cbi_hotspots", {"limit": 999999, "format": "json"})
    assert not res_hotspots_large["isError"]

    # cbi_query with limit and offset
    res_query_large = server.execute_tool("cbi_query", {"sql": "SELECT 1 AS num", "limit": 999999, "format": "json"})
    assert not res_query_large["isError"]
    data_query = json.loads(res_query_large["content"][0]["text"])
    assert data_query["row_count"] == 1

    res_query_offset = server.execute_tool("cbi_query", {
        "sql": "SELECT id FROM nodes ORDER BY id",
        "limit": 2,
        "offset": 1,
        "format": "json",
    })
    assert not res_query_offset["isError"]
    data_offset = json.loads(res_query_offset["content"][0]["text"])
    assert len(data_offset["rows"]) <= 2


def test_mcp_search_and_hotspots_offset(repo):
    server = MCPServer(root=repo)

    # cbi_search with limit=1, offset=0 vs limit=1, offset=1
    res_search_0 = server.execute_tool("cbi_search", {"query": "Circle", "limit": 1, "offset": 0, "format": "json"})
    assert not res_search_0["isError"]
    hits_0 = json.loads(res_search_0["content"][0]["text"])

    res_search_1 = server.execute_tool("cbi_search", {"query": "Circle", "limit": 1, "offset": 1, "format": "json"})
    assert not res_search_1["isError"]
    hits_1 = json.loads(res_search_1["content"][0]["text"])

    assert len(hits_0) == 1
    assert len(hits_1) == 1
    assert hits_0[0]["id"] != hits_1[0]["id"]

    # Text format returns distinct output
    res_search_txt_0 = server.execute_tool("cbi_search", {"query": "Circle", "limit": 1, "offset": 0, "format": "text"})
    res_search_txt_1 = server.execute_tool("cbi_search", {"query": "Circle", "limit": 1, "offset": 1, "format": "text"})
    assert not res_search_txt_0["isError"]
    assert not res_search_txt_1["isError"]
    assert res_search_txt_0["content"][0]["text"] != res_search_txt_1["content"][0]["text"]

    # cbi_hotspots with limit=1, offset=0 vs limit=1, offset=1
    res_hot_0 = server.execute_tool("cbi_hotspots", {"metric": "loc", "kind": "source file", "limit": 1, "offset": 0, "format": "json"})
    assert not res_hot_0["isError"]
    hot_0 = json.loads(res_hot_0["content"][0]["text"])

    res_hot_1 = server.execute_tool("cbi_hotspots", {"metric": "loc", "kind": "source file", "limit": 1, "offset": 1, "format": "json"})
    assert not res_hot_1["isError"]
    hot_1 = json.loads(res_hot_1["content"][0]["text"])

    assert len(hot_0["nodes"]) == 1
    assert len(hot_1["nodes"]) == 1
    assert hot_0["nodes"][0]["id"] != hot_1["nodes"][0]["id"]

    # Sections format (without kind filter)
    res_sec_0 = server.execute_tool("cbi_hotspots", {"metric": "loc", "limit": 1, "offset": 0, "format": "json"})
    assert not res_sec_0["isError"]
    sec_0 = json.loads(res_sec_0["content"][0]["text"])

    res_sec_1 = server.execute_tool("cbi_hotspots", {"metric": "loc", "limit": 1, "offset": 1, "format": "json"})
    assert not res_sec_1["isError"]
    sec_1 = json.loads(res_sec_1["content"][0]["text"])

    assert len(sec_0["files"]) == 1
    assert len(sec_1["files"]) == 1
    assert sec_0["files"][0]["id"] != sec_1["files"][0]["id"]


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
    assert "passed" in data
    assert "unreferenced" in data
    assert "test_only_symbols" in data
    assert "untested" in data
    assert isinstance(data["unreferenced"], list)

    # With fail parameter
    resp_fail = server.execute_tool("cbi_orphans", {"fail": True, "format": "json"})
    assert not resp_fail["isError"]
    data_fail = json.loads(resp_fail["content"][0]["text"])
    assert "passed" in data_fail


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


def test_tools_call_deps_forbid(repo):
    server = MCPServer(root=repo)

    # 1. Passing case: no forbidden dependencies exist
    resp_pass = server.execute_tool("cbi_deps", {
        "level": "folder",
        "forbid": ["src/shapes->src/other"],
    })
    assert not resp_pass["isError"]
    assert "no production imports from src/shapes to src/other" in resp_pass["content"][0]["text"]

    # Passing case with single string forbid
    resp_pass_str = server.execute_tool("cbi_deps", {
        "level": "folder",
        "forbid": "src/shapes->src/other",
    })
    assert not resp_pass_str["isError"]
    assert "no production imports from src/shapes to src/other" in resp_pass_str["content"][0]["text"]

    # Passing case with colon syntax
    resp_pass_colon = server.execute_tool("cbi_deps", {
        "level": "folder",
        "forbid": ["src/shapes:src/other"],
    })
    assert not resp_pass_colon["isError"]
    assert "no production imports from src/shapes to src/other" in resp_pass_colon["content"][0]["text"]

    # Passing case with format=json
    resp_pass_json = server.execute_tool("cbi_deps", {
        "level": "folder",
        "forbid": ["src/shapes->src/other"],
        "format": "json",
    })
    assert not resp_pass_json["isError"]
    data_pass = json.loads(resp_pass_json["content"][0]["text"])
    assert data_pass["passed"] is True
    assert data_pass["violations"] == []

    # 2. Failing case: create an import between folders that violates forbidden constraint
    (repo / "src/other/area.ts").write_text("import { Circle } from '../shapes/circle';\nexport function area() { return 0; }\n")
    assert main(["scan"]) == 0

    resp_fail = server.execute_tool("cbi_deps", {
        "level": "folder",
        "forbid": ["src/other->src/shapes"],
    })
    assert resp_fail["isError"] is True
    text = resp_fail["content"][0]["text"]
    assert "Forbidden dependencies detected" in text
    assert "src/other/area.ts → src/shapes/circle.ts" in text

    # Failing case with single string forbid
    resp_fail_str = server.execute_tool("cbi_deps", {
        "level": "folder",
        "forbid": "src/other->src/shapes",
    })
    assert resp_fail_str["isError"] is True
    assert "src/other/area.ts → src/shapes/circle.ts" in resp_fail_str["content"][0]["text"]

    # Failing case with colon syntax
    resp_fail_colon = server.execute_tool("cbi_deps", {
        "level": "folder",
        "forbid": ["src/other:src/shapes"],
    })
    assert resp_fail_colon["isError"] is True
    assert "src/other/area.ts → src/shapes/circle.ts" in resp_fail_colon["content"][0]["text"]

    # JSON-RPC handle_request call for forbid violation
    req = {
        "jsonrpc": "2.0",
        "id": 42,
        "method": "tools/call",
        "params": {
            "name": "cbi_deps",
            "arguments": {
                "level": "folder",
                "forbid": ["src/other->src/shapes"],
            },
        },
    }
    resp_rpc = server.handle_request(req)
    assert resp_rpc["result"]["isError"] is True
    assert "src/other/area.ts → src/shapes/circle.ts" in resp_rpc["result"]["content"][0]["text"]

    # Invalid forbid syntax returns error
    resp_bad_syntax = server.execute_tool("cbi_deps", {
        "level": "folder",
        "forbid": ["nocolon"],
    })
    assert resp_bad_syntax["isError"] is True
    assert "FROM:TO" in resp_bad_syntax["content"][0]["text"]


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

    tasks_res = server.execute_tool("cbi_tasks", {"format": "json"})
    open_tasks = json.loads(tasks_res["content"][0]["text"])
    stress_task_id = open_tasks[0]["id"] if open_tasks else "test"

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
        ("cbi_task", {"task_id": stress_task_id}),
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

    res_md = server.execute_tool("cbi_endpoints", {"format": "markdown"})
    assert res_md["content"][0]["text"] == "no endpoints found"


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

    res_md = server.execute_tool("cbi_tables", {"format": "markdown"})
    assert res_md["content"][0]["text"] == "no tables found"
    res_mm = server.execute_tool("cbi_tables", {"format": "mermaid"})
    assert res_mm["content"][0]["text"] == "erDiagram"


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

    # cbi_endpoints: markdown format
    res = server.execute_tool("cbi_endpoints", {"format": "markdown"})
    assert not res["isError"]
    assert "| Method | Route | Handler | Callers | Tables |" in res["content"][0]["text"]
    assert "| GET | /api/accounts | accounts" in res["content"][0]["text"]

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

    # cbi_tables: markdown format
    res = server.execute_tool("cbi_tables", {"format": "markdown"})
    assert not res["isError"]
    assert "## Tables" in res["content"][0]["text"]
    assert "| Table | Columns | Primary Key |" in res["content"][0]["text"]
    assert "### `accounts`" in res["content"][0]["text"]

    # cbi_tables: mermaid format
    res = server.execute_tool("cbi_tables", {"format": "mermaid"})
    assert not res["isError"]
    assert res["content"][0]["text"].startswith("erDiagram")
    assert "accounts {" in res["content"][0]["text"]
    assert "INTEGER id PK" in res["content"][0]["text"]


def test_tool_history(make_repo, monkeypatch):
    root = make_repo({"a.py": "def a():\n    return 1\n"}, name="mcp-history-repo")

    def commit_file(rel, content, msg):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        files._git(root, "add", "-A")
        files._git(
            root, "-c", "user.name=test", "-c", "user.email=test@example.com",
            "-c", "commit.gpgsign=false", "commit", "-q", "-m", msg,
        )

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
    root = make_repo({"core/a.ts": "export function a() { return 1; }\n"}, name="mcp-review-repo")

    def commit_file(rel, content, msg):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        files._git(root, "add", "-A")
        files._git(
            root, "-c", "user.name=test", "-c", "user.email=test@example.com",
            "-c", "commit.gpgsign=false", "commit", "-q", "-m", msg,
        )

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
    files._git(root, "checkout", "-q", "-b", "feature-branch")
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
    assert data["findings"] == []

    # 3. Clean pass with explicit base
    res_base = server.execute_tool("cbi_check", {"base": "main", "format": "json"})
    assert not res_base["isError"]
    data_base = json.loads(res_base["content"][0]["text"])
    assert data_base["passed"] is True
    assert data_base["problems"] == []
    assert data_base["findings"] == []

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
    assert len(data_prob["findings"]) > 0
    assert any(f["file"] == "src/shapes/circle.ts" for f in data_prob["findings"])

    res_prob_text = server.execute_tool("cbi_check", {"format": "text"})
    assert not res_prob_text["isError"]
    assert "problem" in res_prob_text["content"][0]["text"]
    assert "src/shapes/circle.ts" in res_prob_text["content"][0]["text"]

    # 6. Kind filtering in cbi_check
    # Filter by matching kind ("summary"): problem reported
    res_kind_match = server.execute_tool("cbi_check", {"kind": "summary", "format": "json"})
    assert not res_kind_match["isError"]
    data_match = json.loads(res_kind_match["content"][0]["text"])
    assert data_match["passed"] is False
    assert len(data_match["problems"]) > 0
    assert len(data_match["findings"]) > 0
    assert all(f["kind"] == "summary" for f in data_match["findings"])

    # Filter by non-matching kind ("secret"): passed is True, no problems
    res_kind_nonmatch = server.execute_tool("cbi_check", {"kind": "secret", "format": "json"})
    assert not res_kind_nonmatch["isError"]
    data_nonmatch = json.loads(res_kind_nonmatch["content"][0]["text"])
    assert data_nonmatch["passed"] is True
    assert data_nonmatch["problems"] == []
    assert data_nonmatch["findings"] == []

    # Non-matching kind in text format: passed
    res_kind_text = server.execute_tool("cbi_check", {"kind": "secret", "format": "text"})
    assert not res_kind_text["isError"]
    assert "cbi check: passed" in res_kind_text["content"][0]["text"]

    # 7. Invalid kind error handling
    res_bad_kind = server.execute_tool("cbi_check", {"kind": "cycles"})
    assert res_bad_kind["isError"]
    assert "invalid check kind: 'cycles'" in res_bad_kind["content"][0]["text"]


def test_tool_worktrees(repo, tmp_path):
    lane = tmp_path / "wt-lane"
    files._git(repo, "worktree", "add", "-q", "-b", "lane", str(lane))

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
    assert res_unknown["isError"] is True
    assert "Unknown task" in res_unknown["content"][0]["text"]

    res_check_unknown = server.execute_tool("cbi_task", {"task_id": "nonexistent-task", "check": "{}"})
    assert res_check_unknown["isError"] is True
    assert "Unknown task" in res_check_unknown["content"][0]["text"]

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

    # 7. Ingest with cwd argument
    res_cwd = server.execute_tool("cbi_ingest", {"files": ["coverage.lcov"], "cwd": str(repo)})
    assert not res_cwd["isError"]


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
    ag_json = fake_home / ".gemini" / "antigravity" / "mcp_config.json"
    assert ag_json.is_file()
    ag_data = json.loads(ag_json.read_text())
    assert "codebase-inspector" in ag_data["mcpServers"]
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

    # 5b. Safe merge into existing VS Code JSONC (comments and trailing commas)
    jsonc_content = """{\n  // VS Code comment\n  "servers": {\n    "custom-server": { "command": "serve" },\n  },\n}"""
    vscode_json.write_text(jsonc_content)
    res_vscode_jsonc = install_client_config("vscode", root=root)
    assert res_vscode_jsonc == 0
    v_data_jsonc = json.loads(vscode_json.read_text())
    assert "custom-server" in v_data_jsonc["servers"]
    assert "codebase-inspector" in v_data_jsonc["servers"]

    # 6. Install claude (Claude Code and Desktop when directory exists)
    if sys.platform == "darwin":
        desktop_dir = fake_home / "Library" / "Application Support" / "Claude"
    elif sys.platform == "win32":
        desktop_dir = fake_home / "AppData" / "Roaming" / "Claude"
    else:
        desktop_dir = fake_home / ".config" / "Claude"
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


def test_query_tools_ref_parameter(repo):
    server = MCPServer(root=repo)

    # 1. Scan HEAD into refs/<head_sha>/model.db
    scan_res = server.execute_tool("cbi_scan", {"ref": "HEAD", "format": "json"})
    assert not scan_res["isError"]
    scan_data = json.loads(scan_res["content"][0]["text"])
    head_sha = scan_data["ref"]
    assert head_sha is not None and len(head_sha) == 40

    circle_node = "src/shapes/circle.ts"

    # 2. Verify all 8 query tools work with ref="HEAD"
    # cbi_context (with node)
    ctx_res = server.execute_tool("cbi_context", {"node": circle_node, "ref": "HEAD"})
    assert not ctx_res["isError"]
    assert "# circle.ts" in ctx_res["content"][0]["text"]
    assert "--ref HEAD" in ctx_res["content"][0]["text"]

    # cbi_context (system overview when node omitted)
    ctx_sys_res = server.execute_tool("cbi_context", {"ref": "HEAD"})
    assert not ctx_sys_res["isError"]
    assert "Architecture Overview" in ctx_sys_res["content"][0]["text"]

    # cbi_show
    show_res = server.execute_tool("cbi_show", {"node": circle_node, "ref": "HEAD"})
    assert not show_res["isError"]
    assert "Circle" in show_res["content"][0]["text"]

    # cbi_search
    search_res = server.execute_tool("cbi_search", {"query": "Circle", "ref": "HEAD"})
    assert not search_res["isError"]
    assert "Circle" in search_res["content"][0]["text"]

    # cbi_tests_for
    tests_res = server.execute_tool("cbi_tests_for", {"target": circle_node, "ref": "HEAD"})
    assert not tests_res["isError"]

    # cbi_endpoints
    ep_res = server.execute_tool("cbi_endpoints", {"ref": "HEAD"})
    assert not ep_res["isError"]

    # cbi_tables
    tables_res = server.execute_tool("cbi_tables", {"ref": "HEAD"})
    assert not tables_res["isError"]

    # cbi_query
    query_res = server.execute_tool("cbi_query", {"sql": "SELECT count(*) FROM nodes", "ref": "HEAD"})
    assert not query_res["isError"]
    query_data = json.loads(query_res["content"][0]["text"])
    assert query_data["row_count"] == 1

    # cbi_concepts
    concepts_res = server.execute_tool("cbi_concepts", {"ref": "HEAD"})
    assert not concepts_res["isError"]

    # 3. Verify tools work with explicit commit SHA ref
    show_sha_res = server.execute_tool("cbi_show", {"node": circle_node, "ref": head_sha})
    assert not show_sha_res["isError"]
    assert "Circle" in show_sha_res["content"][0]["text"]

    query_sha_res = server.execute_tool("cbi_query", {"sql": "SELECT count(*) FROM nodes", "ref": head_sha})
    assert not query_sha_res["isError"]

    # 4. Verify non-existent ref returns isError: True across all 8 query tools
    bad_ref_cases = [
        ("cbi_show", {"node": circle_node, "ref": "nonexistent-ref"}),
        ("cbi_context", {"node": circle_node, "ref": "nonexistent-ref"}),
        ("cbi_context", {"ref": "nonexistent-ref"}),
        ("cbi_search", {"query": "Circle", "ref": "nonexistent-ref"}),
        ("cbi_tests_for", {"target": circle_node, "ref": "nonexistent-ref"}),
        ("cbi_endpoints", {"ref": "nonexistent-ref"}),
        ("cbi_tables", {"ref": "nonexistent-ref"}),
        ("cbi_query", {"sql": "SELECT count(*) FROM nodes", "ref": "nonexistent-ref"}),
        ("cbi_concepts", {"ref": "nonexistent-ref"}),
    ]
    for tool_name, args in bad_ref_cases:
        res = server.execute_tool(tool_name, args)
        assert res["isError"] is True, f"Expected {tool_name} with nonexistent ref to return isError=True"
        assert "No CBI model found for ref" in res["content"][0]["text"]

    # Empty string ref returns isError: True
    res_empty = server.execute_tool("cbi_query", {"sql": "SELECT 1", "ref": "   "})
    assert res_empty["isError"] is True


def test_graph_analysis_tools_ref_parameter(repo):
    server = MCPServer(root=repo)

    # 1. Scan HEAD into refs/<head_sha>/model.db
    scan_res = server.execute_tool("cbi_scan", {"ref": "HEAD", "format": "json"})
    assert not scan_res["isError"]
    scan_data = json.loads(scan_res["content"][0]["text"])
    head_sha = scan_data["ref"]
    assert head_sha is not None and len(head_sha) == 40

    # 2. Verify all 5 dependency and graph analysis tools work with ref="HEAD"
    # cbi_status
    status_res = server.execute_tool("cbi_status", {"ref": "HEAD", "format": "json"})
    assert not status_res["isError"]
    status_data = json.loads(status_res["content"][0]["text"])
    assert "nodes" in status_data
    assert "open_tasks" in status_data

    status_txt_res = server.execute_tool("cbi_status", {"ref": "HEAD", "format": "text"})
    assert not status_txt_res["isError"]

    # cbi_hotspots
    hotspots_res = server.execute_tool("cbi_hotspots", {"metric": "fan-in", "ref": "HEAD"})
    assert not hotspots_res["isError"]
    assert "fan-in" in hotspots_res["content"][0]["text"]

    # cbi_cycles
    cycles_res = server.execute_tool("cbi_cycles", {"ref": "HEAD", "format": "json"})
    assert not cycles_res["isError"]
    cycles_data = json.loads(cycles_res["content"][0]["text"])
    assert "files" in cycles_data

    cycles_txt_res = server.execute_tool("cbi_cycles", {"ref": "HEAD", "format": "text"})
    assert not cycles_txt_res["isError"]

    # cbi_orphans
    orphans_res = server.execute_tool("cbi_orphans", {"ref": "HEAD", "format": "json"})
    assert not orphans_res["isError"]
    orphans_data = json.loads(orphans_res["content"][0]["text"])
    assert "unreferenced" in orphans_data

    orphans_txt_res = server.execute_tool("cbi_orphans", {"ref": "HEAD", "format": "text"})
    assert not orphans_txt_res["isError"]

    # cbi_deps
    deps_res = server.execute_tool("cbi_deps", {"level": "folder", "ref": "HEAD", "format": "json"})
    assert not deps_res["isError"]
    deps_data = json.loads(deps_res["content"][0]["text"])
    assert deps_data["level"] == "folder"

    deps_txt_res = server.execute_tool("cbi_deps", {"level": "folder", "ref": "HEAD", "format": "text"})
    assert not deps_txt_res["isError"]

    # 3. Verify tools work with explicit commit SHA ref
    status_sha_res = server.execute_tool("cbi_status", {"ref": head_sha, "format": "json"})
    assert not status_sha_res["isError"]

    hotspots_sha_res = server.execute_tool("cbi_hotspots", {"metric": "fan-in", "ref": head_sha})
    assert not hotspots_sha_res["isError"]

    cycles_sha_res = server.execute_tool("cbi_cycles", {"ref": head_sha, "format": "json"})
    assert not cycles_sha_res["isError"]

    orphans_sha_res = server.execute_tool("cbi_orphans", {"ref": head_sha, "format": "json"})
    assert not orphans_sha_res["isError"]

    deps_sha_res = server.execute_tool("cbi_deps", {"level": "folder", "ref": head_sha, "format": "json"})
    assert not deps_sha_res["isError"]

    # 4. Verify non-existent ref returns isError: True across all 5 graph analysis tools
    bad_ref_cases = [
        ("cbi_status", {"ref": "nonexistent-ref"}),
        ("cbi_hotspots", {"metric": "fan-in", "ref": "nonexistent-ref"}),
        ("cbi_cycles", {"ref": "nonexistent-ref"}),
        ("cbi_orphans", {"ref": "nonexistent-ref"}),
        ("cbi_deps", {"ref": "nonexistent-ref"}),
    ]
    for tool_name, args in bad_ref_cases:
        res = server.execute_tool(tool_name, args)
        assert res["isError"] is True, f"Expected {tool_name} with nonexistent ref to return isError=True"
        assert "No CBI model found for ref" in res["content"][0]["text"]

    # Empty string ref returns isError: True
    for tool_name in ["cbi_status", "cbi_hotspots", "cbi_cycles", "cbi_orphans", "cbi_deps"]:
        res_empty = server.execute_tool(tool_name, {"ref": "   "})
        assert res_empty["isError"] is True, f"Expected {tool_name} with empty ref to return isError=True"


def test_get_connection_prevents_path_traversal(repo):
    server = MCPServer(root=repo)

    # 1. Direct _get_connection with path traversal raises ValueError
    traversal_refs = [
        "../../outside",
        "../../../etc/passwd",
        "../../etc/passwd",
        "../",
        "..",
        "/etc/passwd",
        "/tmp/evil",
        "refs/../../evil",
        r"..\..\evil",
        r"..\win",
    ]
    for ref in traversal_refs:
        with pytest.raises(ValueError, match="path traversal outside refs directory is forbidden"):
            server._resolve_model_path(ref=ref)
        with pytest.raises(ValueError, match="path traversal outside refs directory is forbidden"):
            server._get_connection(ref=ref)
        with pytest.raises(ValueError, match="path traversal outside refs directory is forbidden"):
            server._source(ref=ref)

    # 2. Query tools with traversal ref return isError=True with clear message
    res_query = server.execute_tool("cbi_query", {"sql": "SELECT 1", "ref": "../../outside"})
    assert res_query["isError"] is True
    assert "path traversal outside refs directory is forbidden" in res_query["content"][0]["text"]

    res_show = server.execute_tool("cbi_show", {"node": "Circle", "ref": "/etc/passwd"})
    assert res_show["isError"] is True
    assert "path traversal outside refs directory is forbidden" in res_show["content"][0]["text"]

    res_context = server.execute_tool("cbi_context", {"ref": ".."})
    assert res_context["isError"] is True
    assert "path traversal outside refs directory is forbidden" in res_context["content"][0]["text"]

    # 3. Nonexistent valid ref format still raises "No CBI model found for ref"
    res_nonexistent = server.execute_tool("cbi_query", {"sql": "SELECT 1", "ref": "nonexistent-branch"})
    assert res_nonexistent["isError"] is True
    assert "No CBI model found for ref" in res_nonexistent["content"][0]["text"]

    # 4. Valid ref functions as expected
    scan_res = server.execute_tool("cbi_scan", {"ref": "HEAD", "format": "json"})
    head_sha = json.loads(scan_res["content"][0]["text"])["ref"]
    conn_sha = server._get_connection(ref=head_sha)
    assert conn_sha is not None
    conn_sha.close()


def test_tool_ingest_prevents_path_traversal(repo, tmp_path):
    server = MCPServer(root=repo)

    lcov_content = """\
TN:
SF:src/shapes/circle.ts
DA:18,1
end_of_record
"""
    # 1. Path traversal via relative path with ..
    res_dotdot = server.execute_tool("cbi_ingest", {"files": ["../../outside.json"]})
    assert res_dotdot["isError"] is True
    assert "traverses outside allowed directories" in res_dotdot["content"][0]["text"]

    # 2. Path traversal via absolute path outside allowed directories
    res_abs = server.execute_tool("cbi_ingest", {"files": ["/etc/passwd"]})
    assert res_abs["isError"] is True
    assert "traverses outside allowed directories" in res_abs["content"][0]["text"]

    # 3. Path escaping repo root
    res_outside = server.execute_tool("cbi_ingest", {"files": ["../outside.lcov"]})
    assert res_outside["isError"] is True
    assert "traverses outside allowed directories" in res_outside["content"][0]["text"]

    # 4. Ingest from tempdir (tmp_path) is allowed
    temp_lcov = tmp_path / "coverage.lcov"
    temp_lcov.write_text(lcov_content)
    res_temp = server.execute_tool("cbi_ingest", {"files": [str(temp_lcov)]})
    assert res_temp["isError"] is False
    assert "lcov" in res_temp["content"][0]["text"]

    # 5. Ingest from custom runner_cwd is allowed
    sub_dir = repo / "sub_project"
    sub_dir.mkdir()
    sub_lcov = sub_dir / "sub_coverage.lcov"
    sub_lcov.write_text(lcov_content)
    res_cwd = server.execute_tool("cbi_ingest", {"files": ["sub_coverage.lcov"], "cwd": str(sub_dir)})
    assert res_cwd["isError"] is False
    assert "lcov" in res_cwd["content"][0]["text"]

    # 6. Ingest from repo root is allowed
    root_lcov = repo / "root_coverage.lcov"
    root_lcov.write_text(lcov_content)
    res_root = server.execute_tool("cbi_ingest", {"files": ["root_coverage.lcov"]})
    assert res_root["isError"] is False

    # 7. Symlink pointing outside allowed directories is rejected
    symlink_etc = repo / "symlink_etc.lcov"
    symlink_etc.symlink_to(Path("/etc/passwd"))
    try:
        res_sym = server.execute_tool("cbi_ingest", {"files": ["symlink_etc.lcov"]})
        assert res_sym["isError"] is True
        assert "traverses outside allowed directories" in res_sym["content"][0]["text"]
    finally:
        if symlink_etc.is_symlink():
            symlink_etc.unlink()

    # 8. Mixed valid and invalid files are rejected
    res_mixed = server.execute_tool("cbi_ingest", {"files": ["root_coverage.lcov", "/etc/passwd"]})
    assert res_mixed["isError"] is True
    assert "traverses outside allowed directories" in res_mixed["content"][0]["text"]

    # 9. Empty path string is rejected
    res_empty = server.execute_tool("cbi_ingest", {"files": ["   "]})
    assert res_empty["isError"] is True
    assert "cannot be empty" in res_empty["content"][0]["text"]


def test_task_tools_ref_parameter(repo):
    server = MCPServer(root=repo)

    # 1. Scan HEAD into refs/<head_sha>/model.db
    scan_res = server.execute_tool("cbi_scan", {"ref": "HEAD", "format": "json"})
    assert not scan_res["isError"]
    head_sha = json.loads(scan_res["content"][0]["text"])["ref"]

    # 2. cbi_tasks returns open tasks from historical ref (using ref="HEAD" and explicit SHA)
    tasks_res = server.execute_tool("cbi_tasks", {"ref": "HEAD", "format": "json"})
    assert not tasks_res["isError"]
    open_tasks = json.loads(tasks_res["content"][0]["text"])
    assert len(open_tasks) > 0, "Expected open tasks in historical ref model"

    tasks_sha_res = server.execute_tool("cbi_tasks", {"ref": head_sha, "format": "json"})
    assert not tasks_sha_res["isError"]
    assert json.loads(tasks_sha_res["content"][0]["text"]) == open_tasks

    tasks_txt_res = server.execute_tool("cbi_tasks", {"ref": "HEAD", "format": "text"})
    assert not tasks_txt_res["isError"]
    assert len(tasks_txt_res["content"][0]["text"].splitlines()) == len(open_tasks)

    target_task = open_tasks[0]
    task_id = target_task["id"]

    # Filter tasks by kind with ref
    kind_res = server.execute_tool("cbi_tasks", {"ref": "HEAD", "kind": target_task["kind"], "format": "json"})
    assert not kind_res["isError"]
    assert any(t["id"] == task_id for t in json.loads(kind_res["content"][0]["text"]))

    # Retrieve brief via cbi_tasks with task_id and ref
    brief_tasks_res = server.execute_tool("cbi_tasks", {"task_id": task_id, "ref": "HEAD", "format": "json"})
    assert not brief_tasks_res["isError"]
    assert json.loads(brief_tasks_res["content"][0]["text"])["id"] == task_id

    # 3. cbi_task loads task brief from historical ref
    task_txt_res = server.execute_tool("cbi_task", {"task_id": task_id, "ref": "HEAD"})
    assert not task_txt_res["isError"]
    text_content = task_txt_res["content"][0]["text"]
    assert f"# Task {task_id}:" in text_content or "node:" in text_content or "instructions" in text_content.lower()

    task_json_res = server.execute_tool("cbi_task", {"task_id": task_id, "ref": head_sha, "format": "json"})
    assert not task_json_res["isError"]
    brief = json.loads(task_json_res["content"][0]["text"])
    assert brief["id"] == task_id
    assert "input_hash" in brief
    assert "bytes" in brief

    # Pre-validate answer schema using check on historical ref
    check_bad = server.execute_tool("cbi_task", {"task_id": task_id, "check": "{not-valid", "ref": "HEAD", "format": "json"})
    assert not check_bad["isError"]
    assert json.loads(check_bad["content"][0]["text"])["ok"] is False

    # 4. cbi_submit writes answer to historical ref and resolves task
    if brief["kind"] == "summarise-files":
        answer = {
            "input_hash": brief["input_hash"],
            "files": [{"path": f["path"], "summary": f"Summary for {f['path']}."} for f in brief["files"]],
        }
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

    submit_res = server.execute_tool("cbi_submit", {"task_id": task_id, "answer": answer, "ref": "HEAD"})
    assert not submit_res["isError"]
    report = submit_res["content"][0]["text"]
    assert "accepted" in report or task_id in report

    # Verify task is now resolved in historical ref
    after_res = server.execute_tool("cbi_tasks", {"ref": "HEAD", "format": "json"})
    assert not after_res["isError"]
    remaining_ids = [t["id"] for t in json.loads(after_res["content"][0]["text"])]
    assert task_id not in remaining_ids

    conn = server._get_connection(ref=head_sha)
    state = conn.execute("SELECT state FROM tasks WHERE id = ?", (task_id,)).fetchone()[0]
    assert state == "done"
    conn.close()

    # 5. Path traversal safeguards and nonexistent ref errors
    for tool_name, args in [
        ("cbi_tasks", {"ref": "nonexistent-ref"}),
        ("cbi_task", {"task_id": task_id, "ref": "nonexistent-ref"}),
        ("cbi_submit", {"task_id": task_id, "answer": answer, "ref": "nonexistent-ref"}),
    ]:
        res_bad = server.execute_tool(tool_name, args)
        assert res_bad["isError"] is True
        assert "No CBI model found for ref" in res_bad["content"][0]["text"]

    for tool_name, args in [
        ("cbi_tasks", {"ref": "../../outside"}),
        ("cbi_task", {"task_id": task_id, "ref": "/etc/passwd"}),
        ("cbi_submit", {"task_id": task_id, "answer": answer, "ref": "../evil"}),
    ]:
        res_trav = server.execute_tool(tool_name, args)
        assert res_trav["isError"] is True
        assert "path traversal outside refs directory is forbidden" in res_trav["content"][0]["text"]


def test_task_tools_change_task_ref_resolution(repo):
    server = MCPServer(root=repo)

    # Add a file and create a second commit
    new_file = repo / "src" / "shapes" / "square.ts"
    new_file.write_text("export class Square {}\n", encoding="utf-8")
    files._git(repo, "add", ".")
    files._git(repo, "commit", "-m", "feat: add square")
    head_sha = files.resolve_commit(repo, "HEAD")

    # Run cbi_review to compare HEAD with HEAD~1, opening change tasks in refs/<head_sha>/model.db
    rev_res = server.execute_tool("cbi_review", {"target": "HEAD", "base": "HEAD~1"})
    assert not rev_res["isError"]

    # Verify cbi_tasks returns tasks from HEAD ref
    tasks_res = server.execute_tool("cbi_tasks", {"ref": "HEAD", "format": "json"})
    assert not tasks_res["isError"]
    tasks_list = json.loads(tasks_res["content"][0]["text"])
    assert len(tasks_list) > 0

    sac_tasks = [t for t in tasks_list if t["kind"] == "summarise-architecture-change"]
    if sac_tasks:
        sac = sac_tasks[0]
        # Verify cbi_task loads brief from historical ref
        brief_res = server.execute_tool("cbi_task", {"task_id": sac["id"], "ref": "HEAD", "format": "json"})
        assert not brief_res["isError"]
        brief = json.loads(brief_res["content"][0]["text"])
        assert brief["id"] == sac["id"]

        # Verify cbi_submit resolves task on historical ref
        answer = {
            "input_hash": brief["input_hash"],
            "narrative": "Square was added to the shapes module to support box shapes.",
            "citations": [f"{sac['node_path']}#Square"] if sac.get("node_path") else [],
        }
        sub_res = server.execute_tool("cbi_submit", {"task_id": sac["id"], "answer": answer, "ref": "HEAD"})
        assert not sub_res["isError"]
        assert "accepted" in sub_res["content"][0]["text"]


def test_resolve_model_path_git_branch_refs_with_slashes(repo):
    server = MCPServer(root=repo)

    # 1. Create a branch with slashes: 'feature/test-branch'
    files._git(repo, "checkout", "-b", "feature/test-branch")
    branch_sha = files.resolve_commit(repo, "feature/test-branch")

    # Scan the branch ref into .cbi/refs/<branch_sha>/model.db
    scan_res = server.execute_tool("cbi_scan", {"ref": "feature/test-branch", "format": "json"})
    assert not scan_res["isError"], scan_res["content"][0]["text"]
    assert json.loads(scan_res["content"][0]["text"])["ref"] == branch_sha

    # 2. _resolve_model_path resolves 'feature/test-branch' directly
    resolved = server._resolve_model_path("feature/test-branch")
    assert resolved == (repo / ".cbi" / "refs" / branch_sha / "model.db").resolve()

    # 3. _get_connection resolves 'feature/test-branch'
    conn = server._get_connection(ref="feature/test-branch")
    assert conn is not None
    conn.close()

    # 4. MCP tools resolve 'feature/test-branch'
    res_status = server.execute_tool("cbi_status", {"ref": "feature/test-branch"})
    assert not res_status["isError"]

    res_show = server.execute_tool("cbi_show", {"node": "Circle", "ref": "feature/test-branch"})
    assert not res_show["isError"]

    res_query = server.execute_tool("cbi_query", {"sql": "SELECT count(*) FROM nodes", "ref": "feature/test-branch"})
    assert not res_query["isError"]

    # 5. Remote-style branch ref with slash: 'origin/main'
    files._git(repo, "branch", "origin/main", branch_sha)
    resolved_origin = server._resolve_model_path("origin/main")
    assert resolved_origin == (repo / ".cbi" / "refs" / branch_sha / "model.db").resolve()

    res_origin_status = server.execute_tool("cbi_status", {"ref": "origin/main"})
    assert not res_origin_status["isError"]

    # 6. _source resolves branch with slash
    source = server._source(ref="feature/test-branch")
    assert source is not None
    source.close()


def test_cbi_diff_resolves_default_base_branch_without_main(tmp_path, monkeypatch):
    # Create a repo whose default branch is 'master' (not 'main')
    root = tmp_path / "repo_master"
    root.mkdir()
    files._git(root, "init", "-q", "-b", "master")
    files._git(root, "config", "core.autocrlf", "false")
    files._git(root, "config", "user.name", "test")
    files._git(root, "config", "user.email", "test@example.com")
    files._git(root, "config", "commit.gpgsign", "false")

    code_file = root / "calculator.py"
    code_file.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    files._git(root, "add", "-A")
    files._git(root, "commit", "-q", "-m", "initial commit on master")

    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    assert main(["scan"]) == 0

    # Create a feature branch with changes
    files._git(root, "checkout", "-b", "feature/multiply")
    code_file.write_text(
        "def add(a, b):\n    return a + b\n\ndef multiply(a, b):\n    return a * b\n",
        encoding="utf-8",
    )
    files._git(root, "add", "-A")
    files._git(root, "commit", "-q", "-m", "add multiply")

    # Confirm that 'main' does NOT exist in this repo
    with pytest.raises(files.BadRef):
        files.resolve_commit(root, "main")

    server = MCPServer(root=root)

    # Call cbi_diff with no base specified (resolves 'master' dynamically via history.default_branch)
    res_diff = server.execute_tool("cbi_diff", {})
    assert not res_diff["isError"], f"Expected cbi_diff to succeed on master repo, but got error: {res_diff}"
    diff_text = res_diff["content"][0]["text"]
    assert "calculator.py" in diff_text or "multiply" in diff_text or "add" in diff_text

    # Call cbi_diff with empty base
    res_diff_empty = server.execute_tool("cbi_diff", {"base": ""})
    assert not res_diff_empty["isError"]












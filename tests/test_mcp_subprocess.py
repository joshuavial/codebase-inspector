"""Subprocess integration tests and pipelined pipe load tests for CBI stdio MCP server."""

import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from cbi.cli import main
from cbi.mcp import (
    PROTOCOL_VERSION,
    SERVER_NAME,
    SERVER_VERSION,
    read_message,
    write_message,
)

FILES = {
    "src/calc.py": """\
def add(a: int, b: int) -> int:
    '''Add two integers.'''
    return a + b

def multiply(a: int, b: int) -> int:
    '''Multiply two integers.'''
    return a * b
""",
    "tests/test_calc.py": """\
from src.calc import add, multiply

def test_add():
    assert add(2, 3) == 5

def test_multiply():
    assert multiply(2, 3) == 6
""",
}


@pytest.fixture
def mcp_repo(make_repo, monkeypatch):
    """Fixture initializing and scanning a test repo with code and tests."""
    root = make_repo(FILES)
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    assert main(["scan"]) == 0
    return root


class MCPSubprocessClient:
    """Manages an active MCP subprocess communicating via real OS pipes."""

    def __init__(self, proc: subprocess.Popen):
        self.proc = proc
        self._responses: queue.Queue = queue.Queue()
        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_thread.start()

    def _reader_loop(self):
        try:
            while True:
                msg, is_cl = read_message(self.proc.stdout)
                if msg is None:
                    self._responses.put((None, False))
                    break
                self._responses.put((msg, is_cl))
        except Exception as exc:
            self._responses.put(exc)

    def send(self, msg: dict, content_length: bool = False):
        write_message(self.proc.stdin, msg, content_length=content_length)

    def send_raw(self, data: bytes):
        raw = getattr(self.proc.stdin, "buffer", self.proc.stdin)
        raw.write(data)
        raw.flush()

    def receive(self, timeout: float = 10.0) -> tuple[dict, bool]:
        item = self._responses.get(timeout=timeout)
        if isinstance(item, Exception):
            raise item
        msg, is_cl = item
        if msg is None:
            raise EOFError("MCP subprocess stdout closed unexpectedly (EOF)")
        return msg, is_cl

    def request(
        self,
        method: str,
        params: dict | None = None,
        req_id: int | str = 1,
        content_length: bool = False,
        timeout: float = 10.0,
    ) -> tuple[dict, bool]:
        req = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}}
        self.send(req, content_length=content_length)
        return self.receive(timeout=timeout)

    def notify(self, method: str, params: dict | None = None, content_length: bool = False):
        req = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        self.send(req, content_length=content_length)

    def close_stdin(self):
        try:
            self.proc.stdin.close()
        except OSError:
            pass

    def wait_clean_shutdown(self, timeout: float = 5.0) -> int:
        self.close_stdin()
        ret = self.proc.wait(timeout=timeout)
        self._reader_thread.join(timeout=timeout)
        return ret


@pytest.fixture
def spawn_mcp_client(mcp_repo):
    """Spawns an MCPSubprocessClient and guarantees process cleanup."""
    clients: list[MCPSubprocessClient] = []

    def _spawn(extra_args=None, repo_dir=None) -> MCPSubprocessClient:
        root = repo_dir or mcp_repo
        env = os.environ.copy()
        src_dir = str(Path(__file__).resolve().parents[1] / "src")
        existing_pythonpath = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = f"{src_dir}{os.pathsep}{existing_pythonpath}" if existing_pythonpath else src_dir

        cmd = [sys.executable, "-m", "cbi.cli", "mcp", "--repo", str(root)]
        if extra_args:
            cmd.extend(extra_args)

        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(root),
            env=env,
        )
        client = MCPSubprocessClient(proc)
        clients.append(client)
        return client

    yield _spawn

    for client in clients:
        proc = client.proc
        if proc.poll() is None:
            try:
                proc.stdin.close()
            except OSError:
                pass
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except Exception:
                try:
                    proc.kill()
                    proc.wait(timeout=2)
                except Exception:
                    pass


def _assert_process_terminated(proc: subprocess.Popen):
    """Verify that process has completely exited with no lingering OS process."""
    assert proc.poll() is not None, "Process is still running"
    if sys.platform != "win32":
        try:
            os.kill(proc.pid, 0)
            raise AssertionError(f"Process {proc.pid} still exists in OS process table")
        except OSError:
            pass


def test_handshake_newline_framing(spawn_mcp_client):
    """Verify full JSON-RPC 2.0 handshake over real OS pipes with newline framing."""
    client = spawn_mcp_client()

    # 1. initialize
    resp, is_cl = client.request(
        "initialize",
        {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "test-client", "version": "1.0"}},
        req_id=1,
        content_length=False,
    )
    assert not is_cl
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == 1
    result = resp["result"]
    assert result["protocolVersion"] == PROTOCOL_VERSION
    assert result["serverInfo"]["name"] == SERVER_NAME
    assert result["serverInfo"]["version"] == SERVER_VERSION
    assert "tools" in result["capabilities"]
    assert "resources" in result["capabilities"]
    assert "prompts" in result["capabilities"]

    # 2. notifications/initialized (produces no response)
    client.notify("notifications/initialized", {}, content_length=False)

    # 3. tools/list
    resp, is_cl = client.request("tools/list", req_id=2, content_length=False)
    assert not is_cl
    assert resp["id"] == 2
    tools = resp["result"]["tools"]
    tool_names = {t["name"] for t in tools}
    assert "cbi_status" in tool_names
    assert "cbi_scan" in tool_names
    assert "cbi_context" in tool_names

    # 4. resources/list
    resp, is_cl = client.request("resources/list", req_id=3, content_length=False)
    assert not is_cl
    assert resp["id"] == 3
    resources = resp["result"]["resources"]
    uris = {r["uri"] for r in resources}
    assert "cbi://system/overview" in uris
    assert "cbi://model/status" in uris

    # 5. prompts/list
    resp, is_cl = client.request("prompts/list", req_id=4, content_length=False)
    assert not is_cl
    assert resp["id"] == 4
    prompts = resp["result"]["prompts"]
    prompt_names = {p["name"] for p in prompts}
    assert "cbi_architecture_orientation" in prompt_names

    # 6. tools/call
    resp, is_cl = client.request(
        "tools/call",
        {"name": "cbi_status", "arguments": {}},
        req_id=5,
        content_length=False,
    )
    assert not is_cl
    assert resp["id"] == 5
    assert not resp["result"]["isError"]
    assert len(resp["result"]["content"]) > 0
    assert resp["result"]["content"][0]["type"] == "text"

    # 7. resources/read
    resp, is_cl = client.request(
        "resources/read",
        {"uri": "cbi://system/overview"},
        req_id=6,
        content_length=False,
    )
    assert not is_cl
    assert resp["id"] == 6
    contents = resp["result"]["contents"]
    assert len(contents) >= 1
    assert contents[0]["uri"] == "cbi://system/overview"
    assert "text" in contents[0]

    # 8. prompts/get
    resp, is_cl = client.request(
        "prompts/get",
        {"name": "cbi_architecture_orientation"},
        req_id=7,
        content_length=False,
    )
    assert not is_cl
    assert resp["id"] == 7
    messages = resp["result"]["messages"]
    assert len(messages) > 0
    assert messages[0]["role"] == "user"

    # Clean termination
    exit_code = client.wait_clean_shutdown()
    assert exit_code == 0
    _assert_process_terminated(client.proc)


def test_handshake_content_length_framing(spawn_mcp_client):
    """Verify full JSON-RPC 2.0 handshake over real OS pipes with Content-Length header framing."""
    client = spawn_mcp_client()

    # 1. initialize
    resp, is_cl = client.request(
        "initialize",
        {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "test-client", "version": "1.0"}},
        req_id=101,
        content_length=True,
    )
    assert is_cl is True
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == 101
    result = resp["result"]
    assert result["protocolVersion"] == PROTOCOL_VERSION
    assert result["serverInfo"]["name"] == SERVER_NAME

    # 2. notifications/initialized
    client.notify("notifications/initialized", {}, content_length=True)

    # 3. tools/list
    resp, is_cl = client.request("tools/list", req_id=102, content_length=True)
    assert is_cl is True
    assert resp["id"] == 102
    assert any(t["name"] == "cbi_status" for t in resp["result"]["tools"])

    # 4. resources/list
    resp, is_cl = client.request("resources/list", req_id=103, content_length=True)
    assert is_cl is True
    assert resp["id"] == 103
    assert any(r["uri"] == "cbi://system/overview" for r in resp["result"]["resources"])

    # 5. prompts/list
    resp, is_cl = client.request("prompts/list", req_id=104, content_length=True)
    assert is_cl is True
    assert resp["id"] == 104
    assert any(p["name"] == "cbi_architecture_orientation" for p in resp["result"]["prompts"])

    # 6. tools/call
    resp, is_cl = client.request(
        "tools/call",
        {"name": "cbi_status", "arguments": {}},
        req_id=105,
        content_length=True,
    )
    assert is_cl is True
    assert resp["id"] == 105
    assert not resp["result"]["isError"]

    # 7. resources/read
    resp, is_cl = client.request(
        "resources/read",
        {"uri": "cbi://model/status"},
        req_id=106,
        content_length=True,
    )
    assert is_cl is True
    assert resp["id"] == 106
    contents = resp["result"]["contents"]
    assert contents[0]["uri"] == "cbi://model/status"
    model_status = json.loads(contents[0]["text"])
    assert isinstance(model_status, dict)

    # 8. prompts/get
    resp, is_cl = client.request(
        "prompts/get",
        {"name": "cbi_architecture_orientation"},
        req_id=107,
        content_length=True,
    )
    assert is_cl is True
    assert resp["id"] == 107
    assert len(resp["result"]["messages"]) > 0

    exit_code = client.wait_clean_shutdown()
    assert exit_code == 0
    _assert_process_terminated(client.proc)


def test_mixed_framing_dynamic_switching(spawn_mcp_client):
    """Verify switching between newline framing and Content-Length framing in one session."""
    client = spawn_mcp_client()

    # Step 1: Content-Length framing initialize
    resp, is_cl = client.request("initialize", req_id="init-cl", content_length=True)
    assert is_cl is True
    assert resp["id"] == "init-cl"

    # Step 2: Newline framing ping
    resp, is_cl = client.request("ping", req_id="ping-nl", content_length=False)
    assert not is_cl
    assert resp["id"] == "ping-nl"

    # Step 3: Content-Length framing with non-ASCII UTF-8 multibyte payload
    unicode_note = "Testing utf-8 symbols: → 🚀 ⚡ 漢字"
    resp, is_cl = client.request(
        "tools/call",
        {"name": "cbi_search", "arguments": {"query": unicode_note}},
        req_id="search-unicode-cl",
        content_length=True,
    )
    assert is_cl is True
    assert resp["id"] == "search-unicode-cl"

    # Step 4: Back to Newline framing tools/list
    resp, is_cl = client.request("tools/list", req_id="tools-nl", content_length=False)
    assert not is_cl
    assert resp["id"] == "tools-nl"

    # Step 5: Back to Content-Length framing resources/list
    resp, is_cl = client.request("resources/list", req_id="resources-cl", content_length=True)
    assert is_cl is True
    assert resp["id"] == "resources-cl"

    exit_code = client.wait_clean_shutdown()
    assert exit_code == 0
    _assert_process_terminated(client.proc)


def test_pipelined_burst_newline(spawn_mcp_client):
    """Send 40+ requests in a rapid pipelined burst (newline framing) without waiting."""
    client = spawn_mcp_client()

    # Initialize first
    client.request("initialize", req_id=0, content_length=False)
    client.notify("notifications/initialized", {}, content_length=False)

    num_requests = 42
    # Mix different request types
    requests = []
    for i in range(1, num_requests + 1):
        rem = i % 5
        if rem == 0:
            requests.append({"jsonrpc": "2.0", "id": i, "method": "tools/list", "params": {}})
        elif rem == 1:
            requests.append({"jsonrpc": "2.0", "id": i, "method": "ping", "params": {}})
        elif rem == 2:
            requests.append({"jsonrpc": "2.0", "id": i, "method": "resources/list", "params": {}})
        elif rem == 3:
            requests.append({"jsonrpc": "2.0", "id": i, "method": "prompts/list", "params": {}})
        else:
            requests.append(
                {"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": {"name": "cbi_status", "arguments": {}}}
            )

    # Send all requests rapidly in pipeline without waiting for any response
    for req in requests:
        client.send(req, content_length=False)

    # Collect all responses
    responses = [client.receive(timeout=10.0) for _ in range(num_requests)]

    # Verify counts, ordering, and integrity
    assert len(responses) == num_requests
    received_ids = [resp["id"] for resp, is_cl in responses]
    assert received_ids == list(range(1, num_requests + 1))
    assert all(not is_cl for _, is_cl in responses)

    # Verify no response is corrupted or carries an unhandled internal error
    for resp, _ in responses:
        assert resp["jsonrpc"] == "2.0"
        assert "result" in resp

    exit_code = client.wait_clean_shutdown()
    assert exit_code == 0
    _assert_process_terminated(client.proc)


def test_pipelined_burst_content_length(spawn_mcp_client):
    """Send 40+ requests in a rapid pipelined burst (Content-Length framing) without waiting."""
    client = spawn_mcp_client()

    client.request("initialize", req_id=0, content_length=True)
    client.notify("notifications/initialized", {}, content_length=True)

    num_requests = 40
    requests = []
    for i in range(1, num_requests + 1):
        rem = i % 4
        if rem == 0:
            requests.append({"jsonrpc": "2.0", "id": i, "method": "ping", "params": {}})
        elif rem == 1:
            requests.append(
                {"jsonrpc": "2.0", "id": i, "method": "resources/read", "params": {"uri": "cbi://system/overview"}}
            )
        elif rem == 2:
            requests.append(
                {"jsonrpc": "2.0", "id": i, "method": "prompts/get", "params": {"name": "cbi_architecture_orientation"}}
            )
        else:
            requests.append(
                {"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": {"name": "cbi_status", "arguments": {}}}
            )

    # Send all in a rapid burst
    for req in requests:
        client.send(req, content_length=True)

    responses = [client.receive(timeout=10.0) for _ in range(num_requests)]

    assert len(responses) == num_requests
    received_ids = [resp["id"] for resp, is_cl in responses]
    assert received_ids == list(range(1, num_requests + 1))
    assert all(is_cl is True for _, is_cl in responses)

    for resp, _ in responses:
        assert resp["jsonrpc"] == "2.0"
        assert "result" in resp

    exit_code = client.wait_clean_shutdown()
    assert exit_code == 0
    _assert_process_terminated(client.proc)


def test_clean_shutdown_on_stdin_close(spawn_mcp_client):
    """Close stdin on the subprocess and verify clean exit code 0 and zero leaked processes."""
    client = spawn_mcp_client()

    # Perform handshake
    resp, _ = client.request("initialize", req_id=1, content_length=False)
    assert resp["id"] == 1

    # Close stdin to trigger EOF in server run loop
    client.close_stdin()

    # Server must terminate cleanly with 0
    exit_code = client.proc.wait(timeout=5.0)
    assert exit_code == 0
    _assert_process_terminated(client.proc)

    # Stderr must be clean
    stderr_out = client.proc.stderr.read()
    assert b"Traceback" not in stderr_out


def test_clean_shutdown_immediate_eof(spawn_mcp_client):
    """Close stdin immediately after spawn without sending messages and verify clean exit."""
    client = spawn_mcp_client()

    client.close_stdin()
    exit_code = client.proc.wait(timeout=5.0)
    assert exit_code == 0
    _assert_process_terminated(client.proc)


def test_clean_shutdown_after_burst(spawn_mcp_client):
    """Verify clean shutdown after a burst load session."""
    client = spawn_mcp_client()

    client.request("initialize", req_id=0, content_length=False)
    for i in range(1, 35):
        client.send({"jsonrpc": "2.0", "id": i, "method": "ping", "params": {}}, content_length=False)

    for i in range(1, 35):
        resp, _ = client.receive(timeout=5.0)
        assert resp["id"] == i

    exit_code = client.wait_clean_shutdown(timeout=5.0)
    assert exit_code == 0
    _assert_process_terminated(client.proc)


def test_error_handling_and_recovery_over_pipes(spawn_mcp_client):
    """Verify JSON parse error, method not found, and invalid params do not kill the server."""
    client = spawn_mcp_client()

    # 1. Send malformed JSON body with Content-Length header
    bad_payload = b"{not: valid json"
    hdr = f"Content-Length: {len(bad_payload)}\r\n\r\n".encode("utf-8")
    client.send_raw(hdr + bad_payload)
    resp, _ = client.receive(timeout=5.0)
    assert resp["error"]["code"] == -32700  # Parse error

    # 2. Send invalid JSON-RPC structure (JSON array instead of object)
    client.send_raw(b'["not", "an", "object"]\n')
    resp, _ = client.receive(timeout=5.0)
    assert resp["error"]["code"] == -32600  # Invalid Request

    # 3. Server remains responsive: send unknown method
    resp, _ = client.request("nonexistent/method", req_id=42, content_length=False)
    assert resp["id"] == 42
    assert resp["error"]["code"] == -32601  # Method not found

    # 4. Server remains responsive: missing required param
    resp, _ = client.request("resources/read", {}, req_id=43, content_length=False)
    assert resp["id"] == 43
    assert resp["error"]["code"] == -32602  # Invalid params

    # 5. Server remains responsive: call nonexistent tool
    resp, _ = client.request(
        "tools/call",
        {"name": "nonexistent_tool", "arguments": {}},
        req_id=44,
        content_length=False,
    )
    assert resp["id"] == 44
    assert resp["result"]["isError"] is True

    # 6. Valid request succeeds after errors
    resp, _ = client.request("ping", req_id=45, content_length=False)
    assert resp["id"] == 45
    assert resp["result"] == {}

    # 7. Clean shutdown
    exit_code = client.wait_clean_shutdown()
    assert exit_code == 0
    _assert_process_terminated(client.proc)

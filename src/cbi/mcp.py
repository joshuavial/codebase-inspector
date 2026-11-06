"""Native Model Context Protocol (MCP) server for CBI over stdio JSON-RPC 2.0.

Allows AI coding agents (Claude Code, Cursor, Codex, Antigravity) to query
CBI's local codebase model directly via stdio JSON-RPC.
"""

import argparse
import contextlib
import io
import json
import sqlite3
import sys
from pathlib import Path

from cbi import context, files, graph, query, store, tasks

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "cbi"
SERVER_VERSION = "0.2.0"

TOOLS = [
    {
        "name": "cbi_status",
        "description": "Show CBI scan state, task counts, and codebase diagnostics.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "format": {
                    "type": "string",
                    "description": "Output format: 'text' or 'json' (default: text)",
                    "enum": ["text", "json"],
                }
            },
            "required": [],
        },
    },
    {
        "name": "cbi_context",
        "description": "Print a short Markdown description of a node (file, symbol, concept, package) for agent context.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "node": {
                    "type": "string",
                    "description": "A node ID, repo-relative path, path#symbol, or symbol name.",
                }
            },
            "required": ["node"],
        },
    },
    {
        "name": "cbi_tests_for",
        "description": "List the tests linked to a node (file, function, class, or folder).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "A node ID, repo-relative path, path#symbol, or symbol name to find tests for.",
                }
            },
            "required": ["target"],
        },
    },
    {
        "name": "cbi_search",
        "description": "Full-text search over every node in the codebase model.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search words/text to find matching nodes.",
                },
                "kind": {
                    "type": "string",
                    "description": "Filter by node kind or display kind (e.g. 'class', 'function', 'test file').",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default: 20).",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "cbi_hotspots",
        "description": "Rank files, folders, packages, and concepts by fan-in, fan-out, size (loc), or symbols.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "metric": {
                    "type": "string",
                    "description": "Metric to rank by: 'fan-in', 'fan-out', 'loc', or 'symbols' (default: 'fan-in').",
                    "enum": ["fan-in", "fan-out", "loc", "symbols"],
                },
                "kind": {
                    "type": "string",
                    "description": "Filter by node kind or display kind.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of items per section (default: 20).",
                },
            },
            "required": [],
        },
    },
]


def read_message(stream):
    """Read one JSON-RPC message from a text or binary stream.

    Supports both Content-Length header framing and newline-delimited JSON.
    Returns (message_dict, is_content_length) or (None, False) on EOF.
    """
    raw = getattr(stream, "buffer", stream)

    line = raw.readline()
    if not line:
        return None, False

    # Consume any leading blank lines / newlines
    while line in (b"\r\n", b"\n", "", "\r\n", "\n"):
        line = raw.readline()
        if not line:
            return None, False

    line_str = line.decode("utf-8") if isinstance(line, bytes) else line
    line_lower = line_str.lower().strip()

    if line_lower.startswith("content-length:"):
        length = int(line_str.split(":", 1)[1].strip())
        # Consume any extra headers until the empty line
        while True:
            hdr = raw.readline()
            hdr_str = hdr.decode("utf-8") if isinstance(hdr, bytes) else hdr
            if hdr_str in ("\r\n", "\n", ""):
                break
        payload_raw = raw.read(length)
        payload_str = payload_raw.decode("utf-8") if isinstance(payload_raw, bytes) else payload_raw
        return json.loads(payload_str), True

    # Newline-delimited JSON
    try:
        return json.loads(line_str), False
    except json.JSONDecodeError:
        # If pretty-printed across multiple lines, read until complete JSON or EOF
        lines = [line_str]
        while True:
            extra = raw.readline()
            if not extra:
                break
            lines.append(extra.decode("utf-8") if isinstance(extra, bytes) else extra)
            try:
                return json.loads("".join(lines)), False
            except json.JSONDecodeError:
                continue
        raise


def write_message(stream, message, content_length=False):
    """Write one JSON-RPC message to a text or binary stream."""
    body_str = json.dumps(message, ensure_ascii=False)
    raw = getattr(stream, "buffer", stream)
    is_binary = isinstance(raw, (io.RawIOBase, io.BufferedIOBase))

    if content_length:
        body_bytes = body_str.encode("utf-8")
        header = f"Content-Length: {len(body_bytes)}\r\n\r\n"
        if is_binary:
            raw.write(header.encode("utf-8") + body_bytes)
        else:
            raw.write(header + body_str)
    else:
        payload = body_str + "\n"
        if is_binary:
            raw.write(payload.encode("utf-8"))
        else:
            raw.write(payload)

    if hasattr(raw, "flush"):
        raw.flush()


class MCPServer:
    """Stdio JSON-RPC 2.0 MCP server for CBI."""

    def __init__(self, root=None, out=None, model_path=None):
        if root is None:
            try:
                root = files.repo_root(Path.cwd())
            except files.NotARepo:
                root = Path.cwd()
        self.root = Path(root).resolve()
        if out is None:
            self.out = self.root / ".cbi"
        else:
            self.out = Path(out).resolve()
        if model_path is None:
            self.model_path = self.out / "model.db"
        else:
            self.model_path = Path(model_path).resolve()

        self.handlers = {
            "cbi_status": self.handle_status,
            "cbi_context": self.handle_context,
            "cbi_tests_for": self.handle_tests_for,
            "cbi_search": self.handle_search,
            "cbi_hotspots": self.handle_hotspots,
        }

    def _get_connection(self):
        if not self.model_path.is_file():
            raise FileNotFoundError(f"No CBI model found at {self.model_path}. Run `cbi scan` first.")
        conn = store.read_only(self.model_path)
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version != store.SCHEMA_VERSION:
            conn.close()
            raise sqlite3.DatabaseError(
                f"{self.model_path} is schema {version}; this cbi expects {store.SCHEMA_VERSION}. Rescan it."
            )
        tasks.attach_cache(conn, readonly=True)
        return conn

    def handle_request(self, request: dict) -> dict | None:
        """Handle a JSON-RPC 2.0 request or notification."""
        if not isinstance(request, dict):
            return {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32600, "message": "Invalid Request: expected object"},
            }

        req_id = request.get("id")
        method = request.get("method")
        params = request.get("params") or {}

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": {
                        "name": SERVER_NAME,
                        "version": SERVER_VERSION,
                    },
                },
            }

        if method in ("notifications/initialized", "initialized"):
            if req_id is not None:
                return {"jsonrpc": "2.0", "id": req_id, "result": {}}
            return None

        if method == "ping":
            if req_id is not None:
                return {"jsonrpc": "2.0", "id": req_id, "result": {}}
            return None

        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": TOOLS},
            }

        if method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments") or {}
            result = self.execute_tool(tool_name, arguments)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": result,
            }

        # If it's a notification, ignore unknown methods without responding
        if req_id is None:
            return None

        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }

    def execute_tool(self, name: str, arguments: dict) -> dict:
        if name not in self.handlers:
            return {
                "content": [{"type": "text", "text": f"Unknown tool: '{name}'"}],
                "isError": True,
            }
        try:
            handler = self.handlers[name]
            text = handler(arguments)
            return {
                "content": [{"type": "text", "text": text}],
                "isError": False,
            }
        except Exception as err:
            return {
                "content": [{"type": "text", "text": f"Error: {err}"}],
                "isError": True,
            }

    def handle_status(self, args: dict) -> str:
        conn = self._get_connection()
        try:
            fmt = args.get("format", "text")
            as_json = fmt == "json"
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                query.status(conn, argparse.Namespace(json=as_json))
            return buf.getvalue().rstrip()
        finally:
            conn.close()

    def handle_context(self, args: dict) -> str:
        node = args.get("node") or args.get("target")
        if not node:
            raise ValueError("Missing required argument: 'node'")
        conn = self._get_connection()
        try:
            found = query.resolve(conn, node)
            if not found:
                raise ValueError(f"No node matches {node!r}")
            if len(found) > 1:
                candidates = query._brief(conn, found)
                lines = [f"{node!r} matches {len(found)} nodes; pick one by ID:"]
                for c in candidates:
                    where = f"{c['path']}:{c['start_line']}" if c.get("start_line") else (c.get("path") or "")
                    lines.append(f"  {c['display_kind']:<12} {c['name']}  {where}\n    {c['id']}")
                raise ValueError("\n".join(lines))
            place = context.Place(
                repo=self.root,
                model_root=self.out,
                model_db=self.model_path,
                branch=context.current_branch(self.root),
            )
            return context.render(conn, found[0], place).rstrip()
        finally:
            conn.close()

    def handle_tests_for(self, args: dict) -> str:
        target = args.get("target") or args.get("node")
        if not target:
            raise ValueError("Missing required argument: 'target'")
        conn = self._get_connection()
        try:
            as_json = args.get("format") == "json"
            out_buf = io.StringIO()
            err_buf = io.StringIO()
            with contextlib.redirect_stdout(out_buf), contextlib.redirect_stderr(err_buf):
                code = query.tests_for(conn, argparse.Namespace(node=target, json=as_json))
            out = out_buf.getvalue()
            err = err_buf.getvalue()
            if code != 0 and err and not out:
                raise ValueError(err.strip())
            return (out or err).rstrip()
        finally:
            conn.close()

    def handle_search(self, args: dict) -> str:
        q = args.get("query") or args.get("text")
        if not q:
            raise ValueError("Missing required argument: 'query'")
        conn = self._get_connection()
        try:
            words = q.split() if isinstance(q, str) else list(q)
            limit = args.get("limit", 20)
            kind = args.get("kind")
            as_json = args.get("format") == "json"
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                query.search(conn, argparse.Namespace(text=words, limit=limit, kind=kind, json=as_json))
            return buf.getvalue().rstrip()
        finally:
            conn.close()

    def handle_hotspots(self, args: dict) -> str:
        metric = args.get("metric") or args.get("by") or "fan-in"
        conn = self._get_connection()
        try:
            limit = args.get("limit", 20)
            kind = args.get("kind")
            as_json = args.get("format") == "json"
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                graph.hotspots(conn, argparse.Namespace(by=metric, limit=limit, kind=kind, json=as_json))
            return buf.getvalue().rstrip()
        finally:
            conn.close()

    def run(self, stdin=None, stdout=None):
        if stdin is None:
            stdin = sys.stdin
        if stdout is None:
            stdout = sys.stdout

        while True:
            try:
                req, is_content_length = read_message(stdin)
            except Exception as err:
                err_resp = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": f"Parse error: {err}"},
                }
                write_message(stdout, err_resp, content_length=False)
                continue

            if req is None:
                break

            resp = self.handle_request(req)
            if resp is not None:
                write_message(stdout, resp, content_length=is_content_length)

        return 0


def run_server(root=None, out=None, stdin=None, stdout=None):
    server = MCPServer(root=root, out=out)
    return server.run(stdin=stdin, stdout=stdout)


if __name__ == "__main__":
    sys.exit(run_server())

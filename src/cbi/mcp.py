"""Native Model Context Protocol (MCP) server for CBI over stdio JSON-RPC 2.0.

Allows AI coding agents (Claude Code, Cursor, Codex, Antigravity) to query
CBI's local codebase model directly via stdio JSON-RPC.
"""

import argparse
import calendar
import contextlib
import datetime as dt
import io
import json
import re
import sqlite3
import sys
import threading
from pathlib import Path

from cbi import (
    change_overview,
    change_summaries,
    concepts,
    context,
    diff,
    files,
    graph,
    history,
    query,
    review,
    store,
    system_views,
    tasks,
)

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "cbi"
SERVER_VERSION = "0.3.0"

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
        "description": "Print a short Markdown description of a node (file, symbol, concept, package) for agent context, or the system architecture overview when omitted or set to 'system'.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "node": {
                    "type": "string",
                    "description": "A node ID, repo-relative path, path#symbol, symbol name, or 'system' (omit or pass 'system' for system architecture overview).",
                }
            },
            "required": [],
        },
    },
    {
        "name": "cbi_show",
        "description": "Show detailed information about a node (file, function, class, concept, endpoint, etc.) including attributes, children, relationships, tests, and diagnostics.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "node": {
                    "type": "string",
                    "description": "Node ID, repo-relative path, path#qualified.name, or symbol name.",
                },
                "min_confidence": {
                    "type": "number",
                    "description": "Minimum edge confidence floor (e.g. 0.8).",
                },
                "all": {
                    "type": "boolean",
                    "description": "Do not cap relationships or tests at 10 (default: false).",
                },
                "format": {
                    "type": "string",
                    "description": "Output format: 'text' (default) or 'json'.",
                    "enum": ["text", "json"],
                },
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
    {
        "name": "cbi_diff",
        "description": "Architectural diff between two commits, branches, or model databases, reporting changed concepts, relationships, and untested changes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "base": {
                    "type": "string",
                    "description": "Base git ref, commit SHA, or path to base model.db (default: merge-base with main).",
                },
                "head": {
                    "type": "string",
                    "description": "Head git ref, commit SHA, or path to head model.db (default: HEAD / current working tree model).",
                },
                "concept": {
                    "type": "string",
                    "description": "Optional concept ID to focus the diff on.",
                },
                "format": {
                    "type": "string",
                    "description": "Output format: 'text' (default), 'markdown', or 'json'.",
                    "enum": ["text", "markdown", "json"],
                },
                "detail": {
                    "type": "boolean",
                    "description": "Whether to return the exhaustive structural change list instead of the summary overview.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "cbi_tasks",
        "description": "Query open judgement tasks (e.g. summarise-architecture-change, summarise-files, define-concepts) or retrieve a task brief.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string",
                    "description": "Optional filter by task kind (e.g. 'summarise-architecture-change', 'summarise-files', 'define-concepts').",
                },
                "task_id": {
                    "type": "string",
                    "description": "Specific task ID to retrieve full brief, outline, and answer schema for.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of open tasks to return (default: 20).",
                },
                "format": {
                    "type": "string",
                    "description": "Output format: 'text' (default) or 'json'.",
                    "enum": ["text", "json"],
                },
            },
            "required": [],
        },
    },
    {
        "name": "cbi_submit",
        "description": "Submit an answer for an open judgement task (e.g. summarise-architecture-change, summarise-files, define-concepts).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "ID of the open judgement task.",
                },
                "answer": {
                    "description": "Answer JSON object or serialized string matching the task's answer schema.",
                },
            },
            "required": ["task_id", "answer"],
        },
    },
    {
        "name": "cbi_query",
        "description": "Execute a read-only SQL query against the codebase model database (model.db). Schema includes nodes (id, kind, display_kind, name, path, start_line, end_line, summary, doc, attrs), edges (src, dst, kind, source, attrs, confidence), and diagnostics (node, message, path, line, kind, severity).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "sql": {
                    "type": "string",
                    "description": "SQL query to run (SELECT or EXPLAIN statement). Writes are disallowed.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of rows to return (default: 50, maximum: 500).",
                },
                "format": {
                    "type": "string",
                    "description": "Output format: 'json' (default) or 'text'.",
                    "enum": ["json", "text"],
                },
            },
            "required": ["sql"],
        },
    },
    {
        "name": "cbi_concepts",
        "description": "List concepts defined in the codebase model, their hierarchy, role, file ownership, and cross-concept dependencies.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "concept_id": {
                    "type": "string",
                    "description": "Optional concept ID to inspect (if omitted, lists all concepts).",
                },
                "format": {
                    "type": "string",
                    "description": "Output format: 'text' (default) or 'json'.",
                    "enum": ["text", "json"],
                },
            },
            "required": [],
        },
    },
    {
        "name": "cbi_cycles",
        "description": "Detect dependency cycles at the file, folder, and package levels.",
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
        "name": "cbi_orphans",
        "description": "Identify orphaned code, test-only exported symbols, unreachable files, and untested packages/folders.",
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
        "name": "cbi_deps",
        "description": "Show dependencies between containers (packages, folders, concepts, or deployables).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "level": {
                    "type": "string",
                    "description": "Container level: 'package', 'folder', 'concept', or 'deployable' (default: 'package').",
                    "enum": ["package", "folder", "concept", "deployable"],
                },
                "start": {
                    "type": "string",
                    "description": "Only dependencies that originate from this container node ID, name, or repo-relative path.",
                },
                "end": {
                    "type": "string",
                    "description": "Only dependencies that enter this container node ID, name, or repo-relative path.",
                },
                "include_tests": {
                    "type": "boolean",
                    "description": "Include imports from test files (default: false).",
                },
                "format": {
                    "type": "string",
                    "description": "Output format: 'text' or 'json' (default: text)",
                    "enum": ["text", "json"],
                },
            },
            "required": [],
        },
    },
    {
        "name": "cbi_endpoints",
        "description": "List HTTP route endpoints detected in the codebase model with their handlers, caller references, downstream code calls, and database tables.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Optional filter: match endpoint path substring.",
                },
                "method": {
                    "type": "string",
                    "description": "Optional filter: HTTP method (e.g. GET, POST).",
                },
                "handler": {
                    "type": "string",
                    "description": "Optional filter: handler function, class, or file name.",
                },
                "table": {
                    "type": "string",
                    "description": "Optional filter: database table name read or written by the endpoint.",
                },
                "format": {
                    "type": "string",
                    "description": "Output format: 'json' (default) or 'text'.",
                    "enum": ["json", "text"],
                },
            },
            "required": [],
        },
    },
    {
        "name": "cbi_tables",
        "description": "List database tables, columns, primary and foreign keys, and code references detected in the codebase model.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "table": {
                    "type": "string",
                    "description": "Optional filter: table name or id substring.",
                },
                "format": {
                    "type": "string",
                    "description": "Output format: 'json' (default) or 'text'.",
                    "enum": ["json", "text"],
                },
            },
            "required": [],
        },
    },
    {
        "name": "cbi_history",
        "description": "Show architectural evolution and changelog across history points on the default branch.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "since": {
                    "type": "string",
                    "description": "ISO date string (YYYY-MM-DD) or relative date (e.g. '1 month ago', 'now') to filter commits since (default: 183 days ago).",
                },
                "until": {
                    "type": "string",
                    "description": "ISO date string (YYYY-MM-DD) or relative date (e.g. 'now', 'yesterday') to filter commits until.",
                },
                "concept": {
                    "type": "string",
                    "description": "Optional concept ID to filter architectural changes by concept.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of history points to return.",
                },
                "format": {
                    "type": "string",
                    "description": "Output format: 'markdown' (default), 'json', or 'text'.",
                    "enum": ["markdown", "json", "text"],
                },
            },
            "required": [],
        },
    },
    {
        "name": "cbi_review",
        "description": "Architectural review between two versions (branch, commit, PR, or HEAD against base) including a Mermaid diagram, changed concepts, and untested changes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "A branch, commit SHA, PR number, or HEAD (default: current HEAD against default branch / merge-base).",
                },
                "base": {
                    "type": "string",
                    "description": "Optional base git ref (e.g. 'main', commit SHA).",
                },
                "format": {
                    "type": "string",
                    "description": "Output format: 'markdown' (default) or 'json'.",
                    "enum": ["markdown", "json"],
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
            "cbi_show": self.handle_show,
            "cbi_tests_for": self.handle_tests_for,
            "cbi_search": self.handle_search,
            "cbi_hotspots": self.handle_hotspots,
            "cbi_diff": self.handle_diff,
            "cbi_tasks": self.handle_tasks,
            "cbi_submit": self.handle_submit,
            "cbi_query": self.handle_query,
            "cbi_concepts": self.handle_concepts,
            "cbi_cycles": self.handle_cycles,
            "cbi_orphans": self.handle_orphans,
            "cbi_deps": self.handle_deps,
            "cbi_endpoints": self.handle_endpoints,
            "cbi_tables": self.handle_tables,
            "cbi_history": self.handle_history,
            "cbi_review": self.handle_review,
        }
        self._stdout_lock = threading.Lock()
        self._scan_lock = threading.Lock()

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

    def _get_write_connection(self):
        if not self.model_path.is_file():
            raise FileNotFoundError(f"No CBI model found at {self.model_path}. Run `cbi scan` first.")
        conn = store._connect(self.model_path)
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version != store.SCHEMA_VERSION:
            conn.close()
            raise sqlite3.DatabaseError(
                f"{self.model_path} is schema {version}; this cbi expects {store.SCHEMA_VERSION}. Rescan it."
            )
        tasks.attach_cache(conn, readonly=False)
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
            with self._stdout_lock:
                with contextlib.redirect_stdout(buf):
                    query.status(conn, argparse.Namespace(json=as_json))
            return buf.getvalue().rstrip()
        finally:
            conn.close()

    def handle_context(self, args: dict) -> str:
        node = args.get("node") or args.get("target")
        place = context.Place(
            repo=self.root,
            model_root=self.out,
            model_db=self.model_path,
            branch=context.current_branch(self.root),
        )
        if not node or node == "system":
            if not self.model_path.is_file():
                raise FileNotFoundError(f"No CBI model found at {self.model_path}. Run `cbi scan` first.")
            return context.render_system(self.model_path, place).rstrip()

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
            return context.render(conn, found[0], place).rstrip()
        finally:
            conn.close()

    def handle_show(self, args: dict) -> str:
        node_ref = args.get("node")
        if not node_ref:
            raise ValueError("Missing required argument: 'node'")

        min_confidence = args.get("min_confidence")
        if min_confidence is not None:
            try:
                min_confidence = float(min_confidence)
            except (TypeError, ValueError) as err:
                raise ValueError(f"Invalid min_confidence: {min_confidence}") from err
            if not (0.0 <= min_confidence <= 1.0):
                raise ValueError("min_confidence must be between 0 and 1")

        all_flag = bool(args.get("all", False))
        fmt = args.get("format", "text")
        if fmt not in ("text", "json"):
            fmt = "text"
        as_json = fmt == "json"

        conn = self._get_connection()
        try:
            err_buf = io.StringIO()
            with self._stdout_lock:
                with contextlib.redirect_stderr(err_buf):
                    found = query._one(conn, node_ref, as_json=False)
            if not found:
                err_msg = err_buf.getvalue().strip()
                raise ValueError(err_msg or f"No node matches {node_ref!r}")

            out_buf = io.StringIO()
            err_buf = io.StringIO()
            ns = argparse.Namespace(
                node=found,
                min_confidence=min_confidence,
                all=all_flag,
                json=as_json,
            )
            with self._stdout_lock:
                with contextlib.redirect_stdout(out_buf), contextlib.redirect_stderr(err_buf):
                    code = query.show(conn, ns)
            out = out_buf.getvalue()
            err = err_buf.getvalue()
            if code != 0 and err and not out:
                raise ValueError(err.strip())
            return (out or err).rstrip()
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
            with self._stdout_lock:
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
            with self._stdout_lock:
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
            with self._stdout_lock:
                with contextlib.redirect_stdout(buf):
                    graph.hotspots(conn, argparse.Namespace(by=metric, limit=limit, kind=kind, json=as_json))
            return buf.getvalue().rstrip()
        finally:
            conn.close()

    def handle_diff(self, args: dict) -> str:
        from cbi import diff
        base_model = args.get("base_model")
        head_model = args.get("head_model")
        base = args.get("base")
        head = args.get("head")
        concept = args.get("concept")
        fmt = args.get("format", "text")
        detail = bool(args.get("detail", False))

        if not base_model and not head_model and not base and not head:
            base = "main"
            head = "HEAD"
        elif not base_model and not head_model:
            base = base or "main"
            head = head or "HEAD"

        try:
            base_conn, head_conn = diff.open_pair(base_model, head_model, base, head, self.root, self.out)
        except diff.DiffError as err:
            return f"Diff error: {err}"

        try:
            if self.root is None or (base_model and head_model):
                result = diff.compare(base_conn, head_conn)
                from cbi import change_summaries
                change_summaries.enrich(base_conn, head_conn, result)
            else:
                result = diff.compare_refs(base_conn, head_conn, self.root, base, head)
        finally:
            base_conn.close()
            head_conn.close()

        rendered = diff.render(
            result, fmt, concept=concept, module=None, file=None, symbol=None, detail=detail,
        )
        return rendered.rstrip()

    def handle_tasks(self, args: dict) -> str:
        conn = self._get_connection()
        try:
            task_id = args.get("task_id")
            fmt = args.get("format", "text")
            as_json = fmt == "json"

            if task_id:
                try:
                    b = tasks.brief(conn, task_id, self.root)
                except tasks.UnknownTask as err:
                    return f"Unknown task: {err}"
                if as_json:
                    return json.dumps(b, indent=2)
                from cbi.cli import _brief_text
                return _brief_text(b).rstrip()

            kind = args.get("kind")
            limit = args.get("limit", 20)
            offset = args.get("offset", 0)
            found = tasks.open_tasks(conn, kind, limit, offset)
            if as_json:
                return json.dumps(found, indent=2)
            if not found:
                return "no open tasks"
            lines = [
                f"{t['id']}  {t['kind']}  {t['node_display_kind']} {t['node_path'] or t['node_id']}  ({t['files']} files)"
                for t in found
            ]
            return "\n".join(lines)
        finally:
            conn.close()

    def handle_submit(self, args: dict) -> str:
        task_id = args.get("task_id")
        if not task_id:
            raise ValueError("Missing required argument: 'task_id'")

        if "answer" not in args or args["answer"] is None:
            raise ValueError("Missing required argument: 'answer'")

        answer = args["answer"]
        if isinstance(answer, (dict, list)):
            text = json.dumps(answer)
        elif isinstance(answer, str):
            text = answer
        else:
            text = json.dumps(answer)

        with self._scan_lock:
            conn = self._get_write_connection()
            try:
                report = tasks.submit(conn, task_id, text, self.root, self.out)
                return report
            except (tasks.AnswerError, tasks.UnknownTask) as err:
                raise ValueError(str(err)) from err
            finally:
                conn.close()

    def handle_query(self, args: dict) -> str:
        sql = (args.get("sql") or "").strip()
        if not sql:
            raise ValueError("Missing required argument: 'sql'")
        # Enforce read-only queries
        first_token = sql.split()[0].upper() if sql.split() else ""
        if first_token not in ("SELECT", "WITH", "EXPLAIN", "PRAGMA"):
            raise ValueError(f"Only read-only queries are permitted (got {first_token}).")

        limit = min(max(int(args.get("limit", 50)), 1), 500)
        fmt = args.get("format", "json")

        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(sql)
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            rows = cursor.fetchmany(limit)

            if fmt == "json":
                results = [dict(zip(columns, row)) for row in rows]
                payload = {
                    "query": sql,
                    "columns": columns,
                    "row_count": len(results),
                    "rows": results,
                }
                return json.dumps(payload, indent=2)
            else:
                if not columns:
                    return "Query returned 0 columns."
                col_widths = [len(c) for c in columns]
                str_rows = []
                for row in rows:
                    str_row = [str(val) if val is not None else "NULL" for val in row]
                    for i, val in enumerate(str_row):
                        col_widths[i] = max(col_widths[i], len(val))
                    str_rows.append(str_row)
                header = " | ".join(columns[i].ljust(col_widths[i]) for i in range(len(columns)))
                divider = "-+-".join("-" * col_widths[i] for i in range(len(columns)))
                body = "\n".join(" | ".join(row[i].ljust(col_widths[i]) for i in range(len(columns))) for row in str_rows)
                summary = f"({len(rows)} row{'s' if len(rows) != 1 else ''})"
                return f"{header}\n{divider}\n{body}\n{summary}" if body else f"{header}\n{divider}\n(0 rows)"
        finally:
            conn.close()

    def handle_concepts(self, args: dict) -> str:
        concept_id = args.get("concept_id")
        fmt = args.get("format", "text")
        as_json = fmt == "json"

        conn = self._get_connection()
        try:
            if concept_id:
                row = conn.execute(
                    "SELECT id, name, summary, attrs FROM nodes WHERE kind = 'concept' AND id = ?",
                    (concept_id,),
                ).fetchone()
                if not row:
                    raise ValueError(f"Concept '{concept_id}' not found.")
                cid, name, summary, attrs_json = row
                attrs = json.loads(attrs_json) if attrs_json else {}

                files_list = [
                    r[0] for r in conn.execute(
                        "SELECT dst FROM edges WHERE kind = 'owns' AND src = ? ORDER BY dst",
                        (concept_id,),
                    )
                ]

                relates_out = [
                    {"target": r[0], "attrs": json.loads(r[1]) if r[1] else {}}
                    for r in conn.execute(
                        "SELECT dst, attrs FROM edges WHERE kind = 'relates' AND src = ? ORDER BY dst",
                        (concept_id,),
                    )
                ]
                relates_in = [
                    {"source": r[0], "attrs": json.loads(r[1]) if r[1] else {}}
                    for r in conn.execute(
                        "SELECT src, attrs FROM edges WHERE kind = 'relates' AND dst = ? ORDER BY src",
                        (concept_id,),
                    )
                ]

                detail = {
                    "id": cid,
                    "name": name,
                    "summary": summary or "",
                    "role": attrs.get("role", ""),
                    "entry": attrs.get("entry", False),
                    "entry_file": attrs.get("entry_file"),
                    "files": files_list,
                    "files_count": len(files_list),
                    "relates_out": relates_out,
                    "relates_in": relates_in,
                }

                if as_json:
                    return json.dumps(detail, indent=2)

                lines = [
                    f"# Concept: {name} ({cid})",
                    f"Role: {detail['role'] or 'unspecified'}",
                    f"Entry: {'yes' if detail['entry'] else 'no'}",
                ]
                if detail["summary"]:
                    lines.append(f"\n{detail['summary']}")
                lines.append(f"\nOwned files ({len(files_list)}):")
                for f in files_list:
                    lines.append(f"  - {f}")
                if relates_out:
                    lines.append("\nOutgoing relationships:")
                    for rel in relates_out:
                        label = rel["attrs"].get("label", "relates to")
                        lines.append(f"  -> {rel['target']} ({label})")
                if relates_in:
                    lines.append("\nIncoming relationships:")
                    for rel in relates_in:
                        label = rel["attrs"].get("label", "relates to")
                        lines.append(f"  <- {rel['source']} ({label})")
                return "\n".join(lines)

            # All concepts
            rows = conn.execute(
                "SELECT id, name, summary, attrs FROM nodes WHERE kind = 'concept' ORDER BY id"
            ).fetchall()
            if not rows:
                if as_json:
                    return json.dumps([], indent=2)
                return "No concepts defined in model."

            file_counts = dict(
                conn.execute("SELECT src, count(*) FROM edges WHERE kind = 'owns' GROUP BY src")
            )
            relates_counts = dict(
                conn.execute("SELECT src, count(*) FROM edges WHERE kind = 'relates' GROUP BY src")
            )

            concepts_list = []
            for cid, name, summary, attrs_json in rows:
                attrs = json.loads(attrs_json) if attrs_json else {}
                concepts_list.append({
                    "id": cid,
                    "name": name,
                    "summary": summary or "",
                    "role": attrs.get("role", ""),
                    "entry": attrs.get("entry", False),
                    "files_count": file_counts.get(cid, 0),
                    "relationships_count": relates_counts.get(cid, 0),
                })

            if as_json:
                return json.dumps(concepts_list, indent=2)

            lines = ["# Codebase Concepts\n"]
            for c in concepts_list:
                role_tag = f" [{c['role']}]" if c["role"] else ""
                entry_tag = " (entry)" if c["entry"] else ""
                lines.append(f"- **{c['name']}** (`{c['id']}`){role_tag}{entry_tag}")
                lines.append(f"  Files: {c['files_count']} | Relates: {c['relationships_count']}")
                if c["summary"]:
                    lines.append(f"  {c['summary']}")
            return "\n".join(lines)
        finally:
            conn.close()

    def handle_cycles(self, args: dict) -> str:
        fmt = args.get("format", "text")
        as_json = fmt == "json"
        conn = self._get_connection()
        try:
            buf = io.StringIO()
            with self._stdout_lock:
                with contextlib.redirect_stdout(buf):
                    graph.cycles(conn, argparse.Namespace(json=as_json))
            return buf.getvalue().rstrip()
        finally:
            conn.close()

    def handle_orphans(self, args: dict) -> str:
        fmt = args.get("format", "text")
        as_json = fmt == "json"
        conn = self._get_connection()
        try:
            buf = io.StringIO()
            with self._stdout_lock:
                with contextlib.redirect_stdout(buf):
                    graph.orphans(conn, argparse.Namespace(json=as_json))
            return buf.getvalue().rstrip()
        finally:
            conn.close()

    def handle_deps(self, args: dict) -> str:
        level = args.get("level") or "package"
        start = args.get("start")
        end = args.get("end")
        include_tests = bool(args.get("include_tests", False))
        fmt = args.get("format", "text")
        as_json = fmt == "json"

        conn = self._get_connection()
        try:
            out_buf = io.StringIO()
            err_buf = io.StringIO()
            with self._stdout_lock:
                with contextlib.redirect_stdout(out_buf), contextlib.redirect_stderr(err_buf):
                    code = graph.deps(
                        conn,
                        argparse.Namespace(
                            level=level,
                            start=start,
                            end=end,
                            forbid=[],
                            include_tests=include_tests,
                            json=as_json,
                        ),
                    )
            out = out_buf.getvalue()
            err = err_buf.getvalue()
            if code != 0 and err and not out:
                raise ValueError(err.strip())
            return (out or err).rstrip()
        finally:
            conn.close()

    def handle_endpoints(self, args: dict) -> str:
        conn = self._get_connection()
        try:
            view = system_views.endpoint_view(conn)
            endpoints = system_views.filter_endpoints(
                view["endpoints"],
                path=args.get("path"),
                method=args.get("method"),
                handler=args.get("handler"),
                table=args.get("table"),
            )
            fmt = args.get("format", "json")
            if fmt == "text":
                return system_views.format_endpoints_text(endpoints).rstrip()
            return json.dumps({"endpoints": endpoints}, indent=2)
        finally:
            conn.close()

    def handle_tables(self, args: dict) -> str:
        conn = self._get_connection()
        try:
            view = system_views.database_view(conn)
            tables, rels = system_views.filter_tables(
                view["tables"],
                view["relationships"],
                table=args.get("table"),
            )
            fmt = args.get("format", "json")
            if fmt == "text":
                return system_views.format_tables_text(tables, rels, all_tables=view["tables"]).rstrip()
            return json.dumps({"tables": tables, "relationships": rels}, indent=2)
        finally:
            conn.close()

    def _normalize_history_date(self, val: str | None) -> str | None:
        if not val:
            return None
        val = str(val).strip()
        try:
            dt.datetime.fromisoformat(val.replace("Z", "+00:00"))
            return val
        except ValueError:
            pass
        now = dt.datetime.now().astimezone()
        lower = val.lower()
        if lower == "now":
            return now.isoformat()
        if lower == "today":
            return now.date().isoformat()
        if lower == "yesterday":
            return (now - dt.timedelta(days=1)).date().isoformat()
        m = re.fullmatch(r"(\d+)\s*(hour|hours|day|days|week|weeks|month|months|year|years)\s*ago", lower)
        if m:
            n = int(m.group(1))
            unit = m.group(2)
            if "hour" in unit:
                return (now - dt.timedelta(hours=n)).isoformat()
            if "day" in unit:
                return (now - dt.timedelta(days=n)).date().isoformat()
            if "week" in unit:
                return (now - dt.timedelta(weeks=n)).date().isoformat()
            if "month" in unit:
                year = now.year
                month = now.month - n
                while month <= 0:
                    month += 12
                    year -= 1
                max_day = calendar.monthrange(year, month)[1]
                day = min(now.day, max_day)
                return now.replace(year=year, month=month, day=day).date().isoformat()
            if "year" in unit:
                year = now.year - n
                max_day = calendar.monthrange(year, now.month)[1]
                day = min(now.day, max_day)
                return now.replace(year=year, day=day).date().isoformat()
        return val

    def handle_history(self, args: dict) -> str:
        since = self._normalize_history_date(args.get("since"))
        until = self._normalize_history_date(args.get("until"))
        concept = args.get("concept")
        limit = args.get("limit")
        if limit is not None:
            try:
                limit = int(limit)
                if limit < 1:
                    raise ValueError("limit must be positive")
            except (ValueError, TypeError) as err:
                raise ValueError(f"Invalid limit: {limit!r}") from err
        fmt = args.get("format", "markdown")
        if fmt not in ("markdown", "json", "text"):
            fmt = "markdown"

        build_since = since
        if build_since is None:
            build_since = (dt.datetime.now().astimezone() - dt.timedelta(days=history.DEFAULT_DAYS)).date().isoformat()

        with self._scan_lock:
            try:
                entries = history.build_history(self.root, self.out, since=build_since, until=until)
                shown = history.select(entries, since=since, until=until, concept=concept, limit=limit)
                return history.render(shown, fmt=fmt).rstrip()
            except history.HistoryError as err:
                raise ValueError(str(err)) from err

    def handle_review(self, args: dict) -> str:
        target = args.get("target") or "HEAD"
        base = args.get("base")
        fmt = args.get("format", "markdown")
        if fmt not in ("markdown", "json"):
            fmt = "markdown"

        with self._scan_lock:
            try:
                spec = review.resolve_target(self.root, target, base)
                base_sha = files.resolve_commit(self.root, spec["base"])
                head_sha = files.resolve_commit(self.root, spec["head"])
            except (review.ReviewError, files.BadRef) as err:
                raise ValueError(str(err)) from err

            try:
                base_conn, head_conn = diff.open_pair(None, None, base_sha, head_sha, self.root, self.out)
            except diff.DiffError as err:
                raise ValueError(f"Diff error: {err}") from err

            try:
                try:
                    line_stats = change_overview.git_line_stats(self.root, base_sha, head_sha)
                except Exception:
                    line_stats = None
                result = diff.compare(base_conn, head_conn, line_stats=line_stats)
                result["overview"].update({"base": base_sha, "head": head_sha})
                change_summaries.enrich(base_conn, head_conn, result)
                diagram = review.build_diagram(result, base_conn, head_conn)
                mermaid = review.render_mermaid(diagram)
                repo_name = review._top_name(head_conn)
            finally:
                base_conn.close()
                head_conn.close()

            narrative, change_task, define_task = None, None, None
            head_db = self.out / "refs" / head_sha / "model.db"
            if head_db.is_file():
                try:
                    narrative, change_task, define_task = review._open_tasks(head_db, base_sha, head_sha, result)
                except Exception:
                    pass

            if fmt == "json":
                payload = {
                    "base": base_sha,
                    "head": head_sha,
                    "spec": spec,
                    "result": result,
                    "diagram": diagram,
                    "mermaid": mermaid,
                    "narrative": narrative,
                    "change_task": change_task,
                    "define_task": define_task,
                }
                return json.dumps(payload, indent=2)

            text = review.render_review(
                self.root,
                base_sha,
                head_sha,
                spec,
                result,
                diagram,
                mermaid,
                narrative,
                change_task,
                define_task,
                images=None,
                repo_name=repo_name,
            )
            return text.rstrip()

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


CONFIG_TEMPLATES = {
    "claude": {
        "description": "Claude Desktop configuration (merge into ~/Library/Application Support/Claude/claude_desktop_config.json)",
        "config": {
            "mcpServers": {
                "codebase-inspector": {
                    "command": "cbi",
                    "args": ["mcp"],
                }
            }
        },
    },
    "cursor": {
        "description": "Cursor MCP configuration (merge into .cursor/mcp.json)",
        "config": {
            "mcpServers": {
                "codebase-inspector": {
                    "command": "cbi",
                    "args": ["mcp"],
                }
            }
        },
    },
    "gemini": {
        "description": "Gemini CLI / Antigravity MCP configuration (merge into ~/.gemini/settings.json)",
        "config": {
            "mcpServers": {
                "codebase-inspector": {
                    "command": "cbi",
                    "args": ["mcp"],
                }
            }
        },
    },
    "windsurf": {
        "description": "Windsurf MCP configuration (merge into ~/.codeium/windsurf/mcp_config.json)",
        "config": {
            "mcpServers": {
                "codebase-inspector": {
                    "command": "cbi",
                    "args": ["mcp"],
                }
            }
        },
    },
    "vscode": {
        "description": "VS Code MCP configuration (merge into settings.json under mcp.servers)",
        "config": {
            "mcpServers": {
                "codebase-inspector": {
                    "command": "cbi",
                    "args": ["mcp"],
                }
            }
        },
    },
}


def print_config(client: str = "all") -> int:
    client = (client or "all").lower()
    if client == "all":
        wrapped = {
            "mcpServers": {
                "codebase-inspector": {
                    "command": "cbi",
                    "args": ["mcp"],
                }
            },
            "clients": list(CONFIG_TEMPLATES.keys()),
        }
        print(json.dumps(wrapped, indent=2))
        return 0
    if client not in CONFIG_TEMPLATES:
        print(
            f"Unknown client '{client}'. Choose from: {', '.join(sorted(CONFIG_TEMPLATES.keys()))}, all",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(CONFIG_TEMPLATES[client]["config"], indent=2))
    return 0


def run_server(root=None, out=None, stdin=None, stdout=None):
    server = MCPServer(root=root, out=out)
    return server.run(stdin=stdin, stdout=stdout)


if __name__ == "__main__":
    sys.exit(run_server())

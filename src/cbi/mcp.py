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
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import threading
import time
import urllib.parse
from pathlib import Path

from cbi import (
    change_overview,
    change_summaries,
    check,
    concepts,
    context,
    diff,
    files,
    graph,
    history,
    ingest,
    jsonc,
    parts,
    prime,
    query,
    review,
    store,
    system_views,
    tasks,
)

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "cbi"
SERVER_VERSION = "0.5.0"

TOOLS = [
    {
        "name": "cbi_scan",
        "description": "Scan repository into model.db and open judgement tasks. Optional ref to scan a git commit or branch.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ref": {
                    "type": "string",
                    "description": "Git branch, tag, or commit SHA to scan into refs/<commit>/model.db.",
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
        "name": "cbi_status",
        "description": "Show CBI scan state, task counts, and codebase diagnostics.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string",
                    "description": "Optional filter for diagnostics or tasks by kind (e.g. 'cycle', 'unmatched_test', 'unsupported_test_mechanism').",
                },
                "ref": {
                    "type": "string",
                    "description": "Git branch, tag, or commit SHA of a historical model database to query.",
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
        "name": "cbi_context",
        "description": "Print a short Markdown description of a node (file, symbol, concept, package) for agent context, or the system architecture overview when omitted or set to 'system'.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "node": {
                    "type": "string",
                    "description": "A node ID, repo-relative path, path#symbol, symbol name, or 'system' (omit or pass 'system' for system architecture overview).",
                },
                "ref": {
                    "type": "string",
                    "description": "Git branch, tag, or commit SHA of a historical model database to query.",
                },
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
                "ref": {
                    "type": "string",
                    "description": "Git branch, tag, or commit SHA of a historical model database to query.",
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
                },
                "ref": {
                    "type": "string",
                    "description": "Git branch, tag, or commit SHA of a historical model database to query.",
                },
                "format": {
                    "type": "string",
                    "description": "Output format: 'text' (default) or 'json'.",
                    "enum": ["text", "json"],
                },
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
                    "description": "Maximum number of results to return (default: 20, maximum: 100).",
                },
                "offset": {
                    "type": "integer",
                    "description": "Offset into search results for pagination (default: 0).",
                },
                "ref": {
                    "type": "string",
                    "description": "Git branch, tag, or commit SHA of a historical model database to query.",
                },
                "format": {
                    "type": "string",
                    "description": "Output format: 'text' (default) or 'json'.",
                    "enum": ["text", "json"],
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
                    "description": "Maximum number of items per section (default: 20, maximum: 500).",
                },
                "offset": {
                    "type": "integer",
                    "description": "Offset into hotspot list for pagination (default: 0).",
                },
                "ref": {
                    "type": "string",
                    "description": "Git branch, tag, or commit SHA of a historical model database to query.",
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
                "base_model": {
                    "type": "string",
                    "description": "Path to pre-scanned base model database.",
                },
                "head_model": {
                    "type": "string",
                    "description": "Path to pre-scanned head model database.",
                },
                "concept": {
                    "type": "string",
                    "description": "Optional concept ID to focus the diff on.",
                },
                "module": {
                    "type": "string",
                    "description": "Drill into a changed presentation module, by id.",
                },
                "file": {
                    "type": "string",
                    "description": "Drill into a changed file, by id or path.",
                },
                "symbol": {
                    "type": "string",
                    "description": "Drill into a changed function or class, by id or name.",
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
                "offset": {
                    "type": "integer",
                    "description": "Offset into task list for pagination (default 0).",
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
                "offset": {
                    "type": "integer",
                    "description": "Offset into result set for pagination (default: 0).",
                },
                "ref": {
                    "type": "string",
                    "description": "Git branch, tag, or commit SHA of a historical model database to query.",
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
                "ref": {
                    "type": "string",
                    "description": "Git branch, tag, or commit SHA of a historical model database to query.",
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
                "ref": {
                    "type": "string",
                    "description": "Git branch, tag, or commit SHA of a historical model database to query.",
                },
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
                "ref": {
                    "type": "string",
                    "description": "Git branch, tag, or commit SHA of a historical model database to query.",
                },
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
                "forbid": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Layering constraints as 'from->to' that must not exist (e.g. ['core->api', 'viewer->cli'])",
                },
                "include_tests": {
                    "type": "boolean",
                    "description": "Include imports from test files (default: false).",
                },
                "ref": {
                    "type": "string",
                    "description": "Git branch, tag, or commit SHA of a historical model database to query.",
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
                "ref": {
                    "type": "string",
                    "description": "Git branch, tag, or commit SHA of a historical model database to query.",
                },
                "format": {
                    "type": "string",
                    "description": "Output format: 'json' (default), 'text', or 'markdown'.",
                    "enum": ["json", "text", "markdown"],
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
                "ref": {
                    "type": "string",
                    "description": "Git branch, tag, or commit SHA of a historical model database to query.",
                },
                "format": {
                    "type": "string",
                    "description": "Output format: 'json' (default), 'text', 'markdown', or 'mermaid'.",
                    "enum": ["json", "text", "markdown", "mermaid"],
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
    {
        "name": "cbi_check",
        "description": "Verify that committed map and judgement files match files changed since the merge base with the default branch or a specified base ref.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "base": {
                    "type": "string",
                    "description": "Base ref or commit SHA (e.g. 'main', 'master', commit hash; default: merge-base with default branch).",
                },
                "kind": {
                    "type": "string",
                    "description": "Optional filter for check findings by kind (e.g. 'summary', 'owner', 'json', 'stale', 'secret', 'ignore').",
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
        "name": "cbi_worktrees",
        "description": "List the repository's worktrees and local branches, their head commits, lanes, and model statuses.",
        "inputSchema": {
            "type": "object",
            "properties": {
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
        "name": "cbi_prime",
        "description": "State-aware guide for an agent meeting cbi for the first time. Reports repository mapping status, open judgement tasks breakdown, the task loop, and ingest instructions.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "format": {
                    "type": "string",
                    "description": "Output format: 'markdown' (default) or 'text'.",
                    "enum": ["markdown", "text"],
                },
            },
            "required": [],
        },
    },
    {
        "name": "cbi_task",
        "description": "Print the brief for one judgement task, inspect partitioned parts for large briefs, or pre-validate an answer JSON schema before submission.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "The task ID (e.g. dc-..., sf-..., etc.).",
                },
                "parts": {
                    "type": "boolean",
                    "description": "Return the index of parts for large briefs (default: false).",
                },
                "part": {
                    "type": "integer",
                    "description": "1-based part index to read for a large brief.",
                },
                "check": {
                    "type": "string",
                    "description": "JSON string containing an answer draft to validate against the task schema without submitting.",
                },
                "format": {
                    "type": "string",
                    "description": "Output format: 'text' (default) or 'json'.",
                    "enum": ["text", "json"],
                },
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "cbi_ingest",
        "description": "Ingest test coverage and result files (lcov, coverage.py JSON, JUnit XML) into codebase model.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Array of file paths to coverage or test result files (lcov, coverage.py JSON, JUnit XML) to ingest.",
                },
                "cwd": {
                    "type": "string",
                    "description": "Optional working directory where the test runner executed (default: server launch working directory or repo root).",
                },
                "format": {
                    "type": "string",
                    "description": "Output format: 'text' (default) or 'json'.",
                    "enum": ["text", "json"],
                },
            },
            "required": ["files"],
        },
    },
    {
        "name": "cbi_init",
        "description": "Initialize .cbi directory and default ignore file in repository root.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "team": {
                    "type": "boolean",
                    "description": "Initialize in team mode (opt-in committed judgement and CI checks).",
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
]

RESOURCES = [
    {
        "uri": "cbi://system/overview",
        "name": "System Architecture Overview",
        "description": "High-level architecture overview, concepts, key components, and boundaries",
        "mimeType": "text/markdown",
    },
    {
        "uri": "cbi://model/status",
        "name": "CBI Model Status",
        "description": "Codebase scan state, task counts, and codebase diagnostics",
        "mimeType": "application/json",
    },
    {
        "uri": "cbi://model/schema",
        "name": "CBI Database Schema",
        "description": "SQLite schema of model.db",
        "mimeType": "text/plain",
    },
    {
        "uri": "cbi://concepts",
        "name": "Architecture Concepts Map",
        "description": "List of architectural concepts and mapped nodes",
        "mimeType": "application/json",
    },
    {
        "uri": "cbi://tasks",
        "name": "Judgement Tasks",
        "description": "List of open and pending architectural judgement tasks",
        "mimeType": "application/json",
    },
]

RESOURCE_TEMPLATES = [
    {
        "uriTemplate": "cbi://node/{id}",
        "name": "Node Details",
        "description": "Detailed architecture information, relationships, tests, and diagnostics for any node",
        "mimeType": "application/json",
    },
    {
        "uriTemplate": "cbi://context/{node}",
        "name": "Node Context Brief",
        "description": "Context brief for an agent working on a file, symbol, or concept",
        "mimeType": "text/markdown",
    },
    {
        "uriTemplate": "cbi://tasks/{id}",
        "name": "Judgement Task Detail",
        "description": "Inspect a specific architectural judgement task brief and answer schema by task ID",
        "mimeType": "application/json",
    },
    {
        "uriTemplate": "cbi://diagnostics/{kind}",
        "name": "Codebase Diagnostics",
        "description": "Triage codebase diagnostics filtered by diagnostic kind (e.g. unmatched_test, unsupported_test_mechanism, cycle)",
        "mimeType": "application/json",
    },
]

PROMPTS = [
    {
        "name": "cbi_architecture_orientation",
        "description": "Guide an agent through onboarding and understanding this codebase architecture using CBI.",
        "arguments": [
            {
                "name": "focus",
                "description": "Optional architectural concept, component, or area to focus on",
                "required": False,
            }
        ],
    },
    {
        "name": "cbi_review_pr",
        "description": "Perform an architectural code review of changes between git base and head.",
        "arguments": [
            {
                "name": "base",
                "description": "Base git ref (e.g. main)",
                "required": False,
            },
            {
                "name": "head",
                "description": "Head git ref or working tree",
                "required": False,
            },
        ],
    },
    {
        "name": "cbi_judgement_task",
        "description": "Investigate and answer an open architectural judgement task in the codebase.",
        "arguments": [
            {
                "name": "task_id",
                "description": "ID of the judgement task to investigate",
                "required": True,
            }
        ],
    },
]



MAX_MULTILINE_LINES = 1000
MAX_MULTILINE_BYTES = 10 * 1024 * 1024  # 10 MB


class MessageParseError(json.JSONDecodeError):
    """Raised when an incoming MCP message cannot be parsed.

    Inherits from json.JSONDecodeError and ValueError for backwards compatibility.
    Includes the framing type (is_content_length) to enable matching error framing.
    """

    def __init__(self, msg: str, doc: str = "", pos: int = 0, is_content_length: bool = False):
        super().__init__(msg, doc, pos)
        self.is_content_length = is_content_length


class _NullPayload:
    """Sentinel representing a valid JSON 'null' input.

    Distinguishes parsed 'null' from an EOF (None) on the stream.
    """

    def __repr__(self) -> str:
        return "NullPayload"


NULL_PAYLOAD = _NullPayload()


def _is_incomplete_json(err: json.JSONDecodeError, text: str) -> bool:
    """Return True only if text could be valid JSON cut off across multiple lines.

    Fails fast if the error occurred before the end of the input (indicating an unparseable
    token on the current line), if the input does not start with an opening bracket/brace,
    or if the error is due to an illegal control character (e.g. unescaped newline in a string).
    """
    stripped = text.strip()
    if not (stripped.startswith("{") or stripped.startswith("[")):
        return False
    if "Invalid control character" in err.msg:
        return False
    content_len = len(text.rstrip("\r\n"))
    return err.pos >= content_len


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

    line_str = line.decode("utf-8", errors="replace") if isinstance(line, bytes) else line
    line_lower = line_str.lower().strip()

    if line_lower.startswith("content-length:"):
        try:
            length = int(line_str.split(":", 1)[1].strip())
        except (ValueError, IndexError) as err:
            raise MessageParseError(
                f"Invalid Content-Length header: {line_str.strip()}",
                doc=line_str,
                pos=0,
                is_content_length=True,
            ) from err

        # Consume any extra headers until the empty line
        header_lines = 0
        while True:
            hdr = raw.readline()
            if not hdr:
                raise MessageParseError(
                    "Unexpected EOF while reading headers",
                    doc="",
                    pos=0,
                    is_content_length=True,
                )
            hdr_str = hdr.decode("utf-8", errors="replace") if isinstance(hdr, bytes) else hdr
            if hdr_str in ("\r\n", "\n", ""):
                break
            header_lines += 1
            if header_lines > 100:
                raise MessageParseError(
                    "Too many header lines",
                    doc="",
                    pos=0,
                    is_content_length=True,
                )

        payload_raw = raw.read(length)
        payload_str = payload_raw.decode("utf-8", errors="replace") if isinstance(payload_raw, bytes) else payload_raw
        if len(payload_raw) < length:
            raise MessageParseError(
                f"Unexpected EOF: expected {length} bytes, received {len(payload_raw)}",
                doc=payload_str,
                pos=len(payload_str),
                is_content_length=True,
            )
        try:
            parsed = json.loads(payload_str)
        except json.JSONDecodeError as err:
            raise MessageParseError(str(err), doc=err.doc, pos=err.pos, is_content_length=True) from err

        if parsed is None:
            return NULL_PAYLOAD, True
        return parsed, True

    # Newline-delimited JSON
    try:
        parsed = json.loads(line_str)
        if parsed is None:
            return NULL_PAYLOAD, False
        return parsed, False
    except json.JSONDecodeError as err:
        # Fail fast if this line has unparseable non-multiline tokens
        if not _is_incomplete_json(err, line_str):
            raise MessageParseError(str(err), doc=err.doc, pos=err.pos, is_content_length=False) from err

        # If pretty-printed across multiple lines, read until complete JSON or limit
        lines = [line_str]
        total_bytes = len(line_str.encode("utf-8") if isinstance(line_str, str) else line_str)
        while len(lines) < MAX_MULTILINE_LINES and total_bytes < MAX_MULTILINE_BYTES:
            extra = raw.readline()
            if not extra:
                break
            extra_str = extra.decode("utf-8", errors="replace") if isinstance(extra, bytes) else extra
            lines.append(extra_str)
            total_bytes += len(extra_str.encode("utf-8"))
            combined = "".join(lines)
            try:
                parsed = json.loads(combined)
                if parsed is None:
                    return NULL_PAYLOAD, False
                return parsed, False
            except json.JSONDecodeError as extra_err:
                if not _is_incomplete_json(extra_err, combined):
                    raise MessageParseError(
                        str(extra_err),
                        doc=extra_err.doc,
                        pos=extra_err.pos,
                        is_content_length=False,
                    ) from extra_err
                continue

        raise MessageParseError(str(err), doc=err.doc, pos=err.pos, is_content_length=False)


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

    def __init__(self, root=None, out=None, model_path=None, cwd=None):
        if root is None:
            try:
                root = files.repo_root(Path.cwd())
            except files.NotARepo:
                root = Path.cwd()
        self.root = Path(root).resolve()
        self.cwd = Path(cwd).resolve() if cwd else Path.cwd().resolve()
        if out is None:
            self.out = self.root / ".cbi"
        else:
            self.out = Path(out).resolve()
        if model_path is None:
            self.model_path = self.out / "model.db"
        else:
            self.model_path = Path(model_path).resolve()

        self.handlers = {
            "cbi_scan": self.handle_scan,
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
            "cbi_check": self.handle_check,
            "cbi_worktrees": self.handle_worktrees,
            "cbi_prime": self.handle_prime,
            "cbi_task": self.handle_task,
            "cbi_ingest": self.handle_ingest,
            "cbi_init": self.handle_init,
        }
        self._stdout_lock = threading.Lock()
        self._scan_lock = threading.Lock()

    def _get_connection(self, ref=None):
        if ref is not None:
            ref_str = str(ref).strip()
            if not ref_str:
                raise ValueError("ref parameter cannot be empty")
            refs_dir = (self.out / "refs").resolve()
            candidate = (self.out / "refs" / ref_str / "model.db").resolve()
            if ".." in ref_str or "/" in ref_str or "\\" in ref_str or not candidate.is_relative_to(refs_dir):
                raise ValueError(f"Invalid ref '{ref}': path traversal outside refs directory is forbidden")
            if not candidate.is_file():
                try:
                    sha = files.resolve_commit(self.root, ref_str)
                    sha_candidate = (self.out / "refs" / sha / "model.db").resolve()
                    if not sha_candidate.is_relative_to(refs_dir):
                        raise ValueError(f"Invalid ref '{ref}': path traversal outside refs directory is forbidden")
                    candidate = sha_candidate
                except ValueError:
                    raise
                except Exception:
                    pass
            if not candidate.is_file():
                raise ValueError(f"No CBI model found for ref '{ref}' at {self.out / 'refs' / ref / 'model.db'}")
            model_file = candidate
        else:
            model_file = self.model_path
            if not model_file.is_file():
                raise FileNotFoundError(f"No CBI model found at {model_file}. Run `cbi scan` first.")

        conn = store.read_only(model_file)
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version != store.SCHEMA_VERSION:
            conn.close()
            raise sqlite3.DatabaseError(
                f"{model_file} is schema {version}; this cbi expects {store.SCHEMA_VERSION}. Rescan it."
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
        if not isinstance(method, str):
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32600, "message": "Invalid Request: 'method' must be a string"},
            }

        if "params" in request and request["params"] is not None and not isinstance(request["params"], dict):
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32602, "message": "Invalid params: 'params' must be an object"},
            }

        params = request.get("params") or {}

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {
                        "tools": {},
                        "resources": {"subscribe": False, "listChanged": False},
                        "prompts": {"listChanged": False},
                    },
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
            if tool_name is None or not isinstance(tool_name, str) or not tool_name.strip():
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32602, "message": "Missing required argument: 'name'"},
                }
            arguments = params.get("arguments")
            if arguments is not None and not isinstance(arguments, dict):
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32602, "message": "Invalid params: 'arguments' must be an object"},
                }
            arguments = arguments or {}
            result = self.execute_tool(tool_name, arguments)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": result,
            }

        if method == "resources/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"resources": RESOURCES},
            }

        if method == "resources/templates/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"resourceTemplates": RESOURCE_TEMPLATES},
            }

        if method == "resources/read":
            uri = params.get("uri")
            if not uri and "arguments" in params and isinstance(params["arguments"], dict):
                uri = params["arguments"].get("uri")
            if uri is None or not isinstance(uri, str) or not uri.strip():
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32602, "message": "Missing required argument: 'uri'"},
                }
            try:
                contents = self.read_resource(uri)
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"contents": contents},
                }
            except (ValueError, FileNotFoundError) as err:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32602, "message": str(err)},
                }
            except Exception as err:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32603, "message": f"Error reading resource: {err}"},
                }

        if method == "prompts/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"prompts": PROMPTS},
            }

        if method == "prompts/get":
            prompt_name = params.get("name")
            if not prompt_name and "arguments" in params and isinstance(params["arguments"], dict):
                prompt_name = params["arguments"].get("name")
            if prompt_name is None or not isinstance(prompt_name, str) or not prompt_name.strip():
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32602, "message": "Missing required argument: 'name'"},
                }
            prompt_args = params.get("arguments")
            if prompt_args is not None and not isinstance(prompt_args, dict):
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32602, "message": "Invalid params: 'arguments' must be an object"},
                }
            arguments = prompt_args or {}
            try:
                result = self.get_prompt(prompt_name, arguments)
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": result,
                }
            except (ValueError, FileNotFoundError) as err:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32602, "message": str(err)},
                }
            except Exception as err:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32603, "message": f"Error getting prompt: {err}"},
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

    def read_resource(self, uri: str) -> list[dict]:
        """Read an MCP resource by URI, returning a list of resource contents."""
        if not isinstance(uri, str):
            raise ValueError(f"Resource URI must be a string, got {type(uri).__name__}")
        uri = uri.strip()
        if not uri:
            raise ValueError("Resource URI cannot be empty")

        parsed = urllib.parse.urlsplit(uri)
        if parsed.scheme != "cbi" or not uri.startswith("cbi://"):
            scheme_display = parsed.scheme or "none"
            raise ValueError(f"Unsupported URI scheme: '{scheme_display}'. Only 'cbi://' URIs are supported.")

        if uri in ("cbi://system/overview", "cbi://overview"):
            text = self.handle_context({"node": "system"})
            return [{"uri": uri, "mimeType": "text/markdown", "text": text}]

        if uri in ("cbi://model/status", "cbi://stats", "cbi://status"):
            text = self.handle_status({"format": "json"})
            return [{"uri": uri, "mimeType": "application/json", "text": text}]

        if uri in ("cbi://model/schema", "cbi://schema"):
            conn = self._get_connection()
            try:
                rows = conn.execute(
                    """
                    SELECT sql FROM sqlite_master
                    WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'
                    ORDER BY
                        CASE type
                            WHEN 'table' THEN 1
                            WHEN 'index' THEN 2
                            WHEN 'view' THEN 3
                            ELSE 4
                        END,
                        name ASC
                    """
                ).fetchall()
                statements = []
                for r in rows:
                    sql = (r[0] or "").strip()
                    if sql:
                        if not sql.endswith(";"):
                            sql += ";"
                        statements.append(sql)
                ddl_text = "\n\n".join(statements)
                return [{"uri": uri, "mimeType": "text/plain", "text": ddl_text}]
            finally:
                conn.close()

        if uri in ("cbi://hotspots", "cbi://model/hotspots"):
            text = self.handle_hotspots({"format": "json"})
            return [{"uri": uri, "mimeType": "application/json", "text": text}]

        if uri == "cbi://concepts":
            text = self.handle_concepts({"format": "json"})
            return [{"uri": uri, "mimeType": "application/json", "text": text}]

        if uri == "cbi://tasks":
            conn = self._get_connection()
            try:
                found = tasks.open_tasks(conn)
                return [{"uri": uri, "mimeType": "application/json", "text": json.dumps(found, indent=2)}]
            finally:
                conn.close()

        if uri.startswith("cbi://tasks/"):
            task_id = urllib.parse.unquote(uri[len("cbi://tasks/"):])
            if not task_id.strip():
                raise ValueError(f"Unknown resource URI: {uri}")
            conn = self._get_connection()
            try:
                try:
                    b = tasks.brief(conn, task_id, self.root)
                except tasks.UnknownTask as err:
                    raise ValueError(f"Unknown task: {task_id}") from err
                return [{"uri": uri, "mimeType": "application/json", "text": json.dumps(b, indent=2)}]
            finally:
                conn.close()

        if uri == "cbi://diagnostics":
            text = self.handle_status({"format": "json"})
            status_data = json.loads(text)
            diagnostics_payload = status_data.get("diagnostics", {})
            return [{"uri": uri, "mimeType": "application/json", "text": json.dumps(diagnostics_payload, indent=2)}]

        if uri.startswith("cbi://diagnostics/"):
            kind = urllib.parse.unquote(uri[len("cbi://diagnostics/"):])
            if not kind.strip():
                raise ValueError(f"Unknown resource URI: {uri}")
            kind = kind.strip()
            conn = self._get_connection()
            try:
                rows = conn.execute(
                    "SELECT d.node_id, n.path, n.name, n.display_kind, d.detail "
                    "FROM diagnostics d LEFT JOIN nodes n ON n.id = d.node_id "
                    "WHERE d.kind = ? ORDER BY n.path, d.node_id",
                    (kind,),
                ).fetchall()
                items = [
                    {
                        "node_id": r[0],
                        "path": r[1],
                        "name": r[2],
                        "display_kind": r[3],
                        "detail": r[4],
                    }
                    for r in rows
                ]
                payload = {
                    "kind": kind,
                    "count": len(items),
                    "diagnostics": items,
                    "items": items,
                }
                if kind == "cycle":
                    from cbi.graph import cycle_summary
                    payload.update(count_unit="memberships", levels=cycle_summary(conn))
                elif kind == "unmatched_http_call":
                    boundaries = {}
                    for item in items:
                        detail = item["detail"] or ""
                        boundary = detail.rsplit("[resolution=", 1)[-1].rstrip("]") if "[resolution=" in detail else "static_unresolved"
                        boundaries[boundary] = boundaries.get(boundary, 0) + 1
                    payload["resolution_boundaries"] = dict(sorted(boundaries.items()))
                return [{"uri": uri, "mimeType": "application/json", "text": json.dumps(payload, indent=2)}]
            finally:
                conn.close()

        if uri.startswith("cbi://node/"):
            node_id = urllib.parse.unquote(uri[len("cbi://node/"):])
            if not node_id.strip():
                raise ValueError(f"Unknown resource URI: {uri}")
            text = self.handle_show({"node": node_id, "format": "json"})
            return [{"uri": uri, "mimeType": "application/json", "text": text}]

        if uri.startswith("cbi://context/"):
            node = urllib.parse.unquote(uri[len("cbi://context/"):])
            if not node.strip():
                raise ValueError(f"Unknown resource URI: {uri}")
            text = self.handle_context({"node": node})
            return [{"uri": uri, "mimeType": "text/markdown", "text": text}]

        raise ValueError(f"Unknown resource URI: {uri}")

    def get_prompt(self, name: str, arguments: dict | None = None) -> dict:
        """Get an MCP prompt by name and arguments."""
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"Invalid prompt name: {name!r}")
        name = name.strip()

        if arguments is not None and not isinstance(arguments, dict):
            raise ValueError("Prompt 'arguments' must be an object")

        args = arguments or {}

        if name == "cbi_architecture_orientation":
            focus = args.get("focus")
            description = (
                "Guide an agent through onboarding and understanding this codebase architecture using CBI."
            )
            text_lines = [
                "Welcome! You are onboarding to this codebase. Use Codebase Inspector (CBI) to understand its architecture.",
                "",
                "Recommended orientation workflow:",
                "1. Start by calling `cbi_prime` (or reading resource `cbi://system/overview`) for the architecture overview, core concepts, and scan status.",
                "2. Check `cbi_status` (or resource `cbi://model/status`) to see scan state, component counts, diagnostics, and open tasks.",
                "3. Inspect `cbi_concepts` (or resource `cbi://concepts`) to discover architectural concepts, module boundaries, and relationships.",
                "4. Use `cbi_context` (or resource `cbi://context/{node}`) to drill into specific files, symbols, or concepts.",
                "5. Detect structural patterns and health with `cbi_cycles`, `cbi_orphans`, `cbi_deps`, and `cbi_endpoints`.",
            ]
            if focus:
                text_lines.extend([
                    "",
                    f"Focus Area: '{focus}'",
                    f"You have been asked to focus specifically on '{focus}'.",
                    f"Begin by inspecting `cbi_context(node='{focus}')` and `cbi_concepts(concept_id='{focus}')` to understand its role and dependencies.",
                ])
            return {
                "description": description,
                "messages": [
                    {
                        "role": "user",
                        "content": {
                            "type": "text",
                            "text": "\n".join(text_lines),
                        },
                    }
                ],
            }

        if name == "cbi_review_pr":
            base = args.get("base") or "main"
            head = args.get("head") or "HEAD"
            description = "Perform an architectural code review of changes between git base and head."
            text_lines = [
                f"Perform an architectural code review comparing base '{base}' and head '{head}'.",
                "",
                "Review checklist:",
                f"1. Run `cbi_diff(base='{base}', head='{head}')` to inspect architectural changes across concepts, components, and untested changes.",
                f"2. Run `cbi_review(target='{head}', base='{base}')` to generate the visual Mermaid change diagram and concept-level summary.",
                f"3. Run `cbi_check(base='{base}')` to verify that architectural maps and judgements are consistent with changed files (when checked out on '{head}'; use `cbi_worktrees` if an isolated worktree is needed for that head).",
                f"4. Check for boundary violations or unwanted dependencies across concepts using `cbi_deps` (on the model corresponding to '{head}').",
                "5. Verify test coverage for all modified or newly introduced code paths.",
                "6. Provide a concise architectural review summary highlighting risks, untested areas, and suggested improvements.",
            ]
            return {
                "description": description,
                "messages": [
                    {
                        "role": "user",
                        "content": {
                            "type": "text",
                            "text": "\n".join(text_lines),
                        },
                    }
                ],
            }

        if name == "cbi_judgement_task":
            task_id = args.get("task_id") or args.get("id")
            if not task_id or not str(task_id).strip():
                raise ValueError("Missing required argument: 'task_id'")
            task_id = str(task_id).strip()
            description = (
                "Investigate and answer an open architectural judgement task in the codebase."
            )
            try:
                task_info = self.handle_task({"id": task_id, "format": "text"})
            except Exception as err:
                task_info = f"(Unable to retrieve task details: {err})"

            text_lines = [
                f"You are assigned to investigate and resolve architectural judgement task '{task_id}'.",
                "",
                "Task Brief and Information:",
                task_info,
                "",
                "Resolution steps:",
                "1. Read the brief, questions, and required answer schema above.",
                "2. Investigate the codebase using `cbi_show`, `cbi_context`, `cbi_search`, or reading files.",
                f"3. If this task has large briefs or parts, use `cbi_task(task_id='{task_id}', parts=True)` to inspect parts.",
                f"4. Pre-validate your answer format with `cbi_task(task_id='{task_id}', check=...)` before submitting.",
                f"5. Submit your final answer using `cbi_submit(task_id='{task_id}', answer=...)`.",
            ]
            return {
                "description": description,
                "messages": [
                    {
                        "role": "user",
                        "content": {
                            "type": "text",
                            "text": "\n".join(text_lines),
                        },
                    }
                ],
            }

        raise ValueError(f"Unknown prompt: {name}")

    def handle_scan(self, args: dict) -> str:
        from cbi import scan as scan_pipeline

        ref = args.get("ref")
        fmt = args.get("format", "text")
        if fmt not in ("text", "json"):
            fmt = "text"

        with self._scan_lock:
            root = self.root
            out = self.out
            if root is None:
                try:
                    root = files.repo_root(Path.cwd())
                except files.NotARepo as err:
                    raise ValueError(str(err)) from err
            else:
                try:
                    root = files.repo_root(root)
                except files.NotARepo as err:
                    raise ValueError(str(err)) from err

            if out is None:
                out = root / ".cbi"

            if not (out / "ignore").exists():
                raise ValueError(f"{out} is not initialised. Run `cbi init` first.")

            start = time.perf_counter()
            try:
                if ref:
                    sha, shortcut, counts, task_counts = scan_pipeline.scan_ref(root, out, ref)
                else:
                    sha = None
                    shortcut, counts, task_counts = scan_pipeline.scan(root, out)
            except (files.NotARepo, files.BadRef) as err:
                raise ValueError(str(err)) from err

            elapsed = time.perf_counter() - start
            open_tasks, blocked_tasks = task_counts

            if fmt == "json":
                return json.dumps({
                    "ref": sha,
                    "shortcut": shortcut,
                    "counts": counts,
                    "open_tasks": open_tasks,
                    "blocked_tasks": blocked_tasks,
                }, indent=2)

            lines = []
            if ref:
                lines.append(sha)
                status = "reused" if shortcut else "scanned"
            else:
                excluded = files.excluded_source_files(root, files.Ignore(scan_pipeline._read(out / "ignore") or ""))
                lines.append(f"Excluded tracked executable files: {len(excluded)} (by ignore rules)")
                status = "no changes since the last scan" if shortcut else "scanned"
            lines.append(f"{status} in {elapsed:.1f} s")
            for kind, count in counts.items():
                lines.append(f"  {kind}: {count}")
            line = tasks.task_headline(open_tasks, blocked_tasks)
            lines.append(line + ("; run `cbi tasks`" if open_tasks else ""))
            return "\n".join(lines)

    def handle_status(self, args: dict) -> str:
        ref = args.get("ref")
        conn = self._get_connection(ref=ref)
        try:
            fmt = args.get("format", "text")
            as_json = fmt == "json"
            kind = args.get("kind")
            buf = io.StringIO()
            with self._stdout_lock:
                with contextlib.redirect_stdout(buf):
                    query.status(conn, argparse.Namespace(json=as_json, kind=kind))
            return buf.getvalue().rstrip()
        finally:
            conn.close()

    def handle_context(self, args: dict) -> str:
        ref = args.get("ref")
        conn = self._get_connection(ref=ref)
        try:
            db_path = conn.execute("PRAGMA database_list").fetchone()[2]
            place = context.Place(
                repo=self.root,
                model_root=self.out,
                model_db=Path(db_path) if db_path else self.model_path,
                branch=None if ref else context.current_branch(self.root),
                ref=ref,
            )
            node = args.get("node") or args.get("target")
            if not node or node == "system":
                return context.render_system(conn, place).rstrip()

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

        conn = self._get_connection(ref=args.get("ref"))
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
        conn = self._get_connection(ref=args.get("ref"))
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
        limit_val = args.get("limit") if args.get("limit") is not None else args.get("max_results", 20)
        try:
            limit = int(limit_val)
        except (ValueError, TypeError) as err:
            raise ValueError(f"Invalid limit: {limit_val!r}") from err
        limit = min(max(limit, 1), 100)

        offset_arg = args.get("offset")
        offset = 0
        if offset_arg is not None:
            try:
                offset = int(offset_arg)
            except (ValueError, TypeError) as err:
                raise ValueError(f"Invalid offset: {offset_arg!r}") from err
            if offset < 0:
                raise ValueError("offset must be non-negative")
            offset = min(offset, 100_000)

        conn = self._get_connection(ref=args.get("ref"))
        try:
            words = q.split() if isinstance(q, str) else list(q)
            kind = args.get("kind")
            as_json = args.get("format") == "json"
            buf = io.StringIO()
            with self._stdout_lock:
                with contextlib.redirect_stdout(buf):
                    query.search(conn, argparse.Namespace(text=words, limit=limit, offset=offset, kind=kind, json=as_json), offset=offset)
            return buf.getvalue().rstrip()
        finally:
            conn.close()

    def handle_hotspots(self, args: dict) -> str:
        metric = args.get("metric") or args.get("by") or "fan-in"
        ref = args.get("ref")
        limit_val = args.get("limit", 20)
        try:
            limit = int(limit_val)
        except (ValueError, TypeError) as err:
            raise ValueError(f"Invalid limit: {limit_val!r}") from err
        limit = min(max(limit, 1), 500)

        offset_arg = args.get("offset")
        offset = 0
        if offset_arg is not None:
            try:
                offset = int(offset_arg)
            except (ValueError, TypeError) as err:
                raise ValueError(f"Invalid offset: {offset_arg!r}") from err
            if offset < 0:
                raise ValueError("offset must be non-negative")
            offset = min(offset, 100_000)

        conn = self._get_connection(ref=ref)
        try:
            kind = args.get("kind")
            as_json = args.get("format") == "json"
            buf = io.StringIO()
            with self._stdout_lock:
                with contextlib.redirect_stdout(buf):
                    graph.hotspots(conn, argparse.Namespace(by=metric, limit=limit, offset=offset, kind=kind, json=as_json), offset=offset)
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
        module = args.get("module")
        file = args.get("file")
        symbol = args.get("symbol")
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
            raise ValueError(f"Diff error: {err}") from err

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
            result, fmt, concept=concept, module=module, file=file, symbol=symbol, detail=detail,
        )
        return rendered.rstrip()

    def handle_tasks(self, args: dict) -> str:
        conn = self._get_connection()
        try:
            task_id = args.get("task_id") or args.get("id")
            fmt = args.get("format", "text")
            as_json = fmt == "json"

            if task_id:
                try:
                    b = tasks.brief(conn, task_id, self.root)
                except tasks.UnknownTask as err:
                    raise ValueError(f"Unknown task: {err}") from err
                if as_json:
                    return json.dumps(b, indent=2)
                return tasks.brief_text(b).rstrip()

            kind = args.get("kind")
            limit_val = args.get("limit", 20)
            try:
                limit = int(limit_val)
            except (ValueError, TypeError) as err:
                raise ValueError(f"Invalid limit: {limit_val!r}") from err
            limit = min(max(limit, 1), 500)

            offset_val = args.get("offset", 0)
            try:
                offset = int(offset_val)
            except (ValueError, TypeError) as err:
                raise ValueError(f"Invalid offset: {offset_val!r}") from err
            if offset < 0:
                raise ValueError("offset must be non-negative")
            offset = min(offset, 100_000)

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
        task_id = args.get("task_id") or args.get("id")
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
        if first_token not in ("SELECT", "WITH", "EXPLAIN"):
            raise ValueError(f"Only read-only queries are permitted (got {first_token}).")

        limit_val = args.get("limit", 50)
        try:
            limit = int(limit_val)
        except (ValueError, TypeError) as err:
            raise ValueError(f"Invalid limit: {limit_val!r}") from err
        limit = min(max(limit, 1), 500)

        offset_val = args.get("offset")
        offset = 0
        if offset_val is not None:
            try:
                offset = int(offset_val)
            except (ValueError, TypeError) as err:
                raise ValueError(f"Invalid offset: {offset_val!r}") from err
            if offset < 0:
                raise ValueError("offset must be non-negative")
            offset = min(offset, 100_000)

        fmt = args.get("format", "json")

        conn = self._get_connection(ref=args.get("ref"))
        try:
            def authorizer(action, arg1, arg2, dbname, source):
                if action in (sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH, sqlite3.SQLITE_PRAGMA):
                    return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK

            conn.set_authorizer(authorizer)

            timer = threading.Timer(5.0, conn.interrupt)
            timer.start()
            try:
                cursor = conn.cursor()
                cursor.execute(sql)
                columns = [desc[0] for desc in cursor.description] if cursor.description else []
                if offset > 0:
                    cursor.fetchmany(offset)
                rows = cursor.fetchmany(limit)
            except sqlite3.OperationalError as err:
                if "interrupted" in str(err).lower():
                    raise ValueError("Query execution exceeded timeout limit (5.0s)") from err
                raise
            finally:
                timer.cancel()

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

        conn = self._get_connection(ref=args.get("ref"))
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
        ref = args.get("ref")
        conn = self._get_connection(ref=ref)
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
        ref = args.get("ref")
        conn = self._get_connection(ref=ref)
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
        forbid_raw = args.get("forbid") or []
        if isinstance(forbid_raw, str):
            forbid = [forbid_raw]
        elif isinstance(forbid_raw, (list, tuple)):
            forbid = [str(item) for item in forbid_raw]
        else:
            forbid = [str(forbid_raw)]
        include_tests = bool(args.get("include_tests", False))
        fmt = args.get("format", "text")
        as_json = fmt == "json"
        ref = args.get("ref")

        conn = self._get_connection(ref=ref)
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
                            forbid=forbid,
                            include_tests=include_tests,
                            json=as_json,
                        ),
                    )
            out = out_buf.getvalue()
            err = err_buf.getvalue()
            if code != 0:
                report_parts = []
                if out.strip():
                    report_parts.append(out.strip())
                if err.strip():
                    report_parts.append(err.strip())
                msg = "\n".join(report_parts) or f"cbi deps failed with exit code {code}"
                if forbid and out.strip():
                    msg = f"Forbidden dependencies detected:\n{msg}"
                raise ValueError(msg)
            if as_json and forbid:
                return json.dumps({
                    "level": level,
                    "forbid": forbid,
                    "passed": True,
                    "violations": [],
                    "message": out.strip(),
                }, indent=2)
            return (out or err).rstrip()
        finally:
            conn.close()

    def handle_endpoints(self, args: dict) -> str:
        conn = self._get_connection(ref=args.get("ref"))
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
            if fmt == "markdown":
                return system_views.format_endpoints_markdown(endpoints).rstrip()
            return json.dumps({"endpoints": endpoints}, indent=2)
        finally:
            conn.close()

    def handle_tables(self, args: dict) -> str:
        conn = self._get_connection(ref=args.get("ref"))
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
            if fmt == "markdown":
                return system_views.format_tables_markdown(tables, rels, all_tables=view["tables"]).rstrip()
            if fmt == "mermaid":
                return system_views.format_tables_mermaid(tables, rels, all_tables=view["tables"]).rstrip()
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

    def handle_check(self, args: dict) -> str:
        base = args.get("base")
        kind = args.get("kind")
        fmt = args.get("format", "text")
        if fmt not in ("text", "json"):
            fmt = "text"

        with self._scan_lock:
            try:
                res = check.verify(self.root, self.out, base_ref=base, kind=kind)
            except (files.BadRef, FileNotFoundError) as err:
                raise ValueError(str(err)) from err
            except SystemExit as err:
                raise ValueError(f"invalid check kind: '{kind}'. Valid kinds: {', '.join(sorted(check.VALID_KINDS))}") from err

            if fmt == "json":
                return json.dumps({
                    "passed": res["passed"],
                    "problems": res["problems"],
                    "findings": res.get("findings", []),
                }, indent=2)
            return res["report"].rstrip()

    def handle_worktrees(self, args: dict) -> str:
        fmt = args.get("format", "text")
        if fmt not in ("text", "json"):
            fmt = "text"

        data = files.inventory(self.root, self.out)
        if fmt == "json":
            return json.dumps(data, indent=2)

        lines = ["worktrees:"]
        for w in data["worktrees"]:
            mark = "*" if w["current"] else " "
            branch = w["branch"] or "(detached)"
            if w["model_complete"]:
                state = "model complete"
            elif w["has_model"]:
                state = "model"
            else:
                state = "no model"
            lines.append(f"{mark} {w['path']}  {branch}  {w['head'][:12]}  {w['lane'] or branch}  {state}")
        lines.append("branches:")
        for b in data["branches"]:
            mark = "*" if b["current"] else " "
            ref = "ref model" if b["has_ref_model"] else "no ref model"
            lines.append(f"{mark} {b['name']}  {b['head'][:12]}  {b['lane']}  {ref}")
        return "\n".join(lines)

    def handle_prime(self, args: dict) -> str:
        if not self.model_path.is_file():
            return prime.NOT_INITIALISED.rstrip()
        conn = self._get_connection()
        try:
            return prime.render(self.root, self.out, conn=conn).rstrip()
        finally:
            conn.close()

    def handle_task(self, args: dict) -> str:
        task_id = args.get("task_id") or args.get("id")
        if not task_id:
            raise ValueError("Missing required argument: 'task_id'")

        fmt = args.get("format", "text")
        as_json = fmt == "json"

        conn = self._get_connection()
        token = parts.bind(self.out)
        try:
            if "check" in args and args["check"] is not None:
                check_val = args["check"]
                if isinstance(check_val, (dict, list)):
                    check_text = json.dumps(check_val)
                elif isinstance(check_val, str):
                    check_text = check_val
                else:
                    check_text = json.dumps(check_val)

                try:
                    warnings = tasks.check(conn, task_id, check_text, self.root)
                except tasks.UnknownTask as err:
                    raise ValueError(f"Unknown task: {err}") from err
                except tasks.AnswerError as err:
                    if as_json:
                        return json.dumps({"ok": False, "errors": str(err).splitlines()}, indent=2)
                    return f"rejected:\n{err}"

                if as_json:
                    return json.dumps({"ok": True, "warnings": warnings}, indent=2)
                elif warnings:
                    return "ok\n" + "\n".join(warnings)
                else:
                    return "ok"

            try:
                b = tasks.brief(conn, task_id, self.root)
            except tasks.UnknownTask as err:
                raise ValueError(f"Unknown task: {err}") from err

            has_parts = bool(args.get("parts", False))
            part_idx = args.get("part")

            if has_parts or part_idx is not None:
                if b["kind"] not in parts.SPLIT_KINDS:
                    raise ValueError(f"{b['kind']} briefs are not split")
                try:
                    spec = parts.split_brief(conn, b, self.root)
                except ValueError as err:
                    raise ValueError(str(err)) from err

                if has_parts:
                    if as_json:
                        return json.dumps(parts.index_payload(spec), indent=2)
                    return parts.index_text(spec).rstrip()

                try:
                    part_int = int(part_idx)
                except (ValueError, TypeError):
                    raise ValueError(f"part {part_idx} is outside 1..{len(spec['parts'])}")
                if part_int < 1 or part_int > len(spec["parts"]):
                    raise ValueError(f"part {part_idx} is outside 1..{len(spec['parts'])}")
                part = spec["parts"][part_int - 1]
                if as_json:
                    return parts.json_part(part["brief"]).rstrip()
                return part["text"].rstrip()

            text = tasks.brief_text(b)
            stamped = tasks.sized(parts.insert_note(text, parts.over_note(b, text)))
            if as_json:
                payload = dict(b)
                payload["bytes"] = len(stamped.encode())
                if parts.over_note(b, text):
                    payload["over_budget"] = True
                return json.dumps(payload, indent=2)
            return stamped.rstrip()
        finally:
            parts.unbind(token)
            conn.close()

    def handle_ingest(self, args: dict) -> str:
        files_arg = args.get("files")
        if not files_arg or not isinstance(files_arg, list):
            raise ValueError("Missing or invalid required argument: 'files' (expected a non-empty array of file paths)")

        fmt = args.get("format", "text")
        if fmt not in ("text", "json"):
            fmt = "text"

        cwd_arg = args.get("cwd")
        if cwd_arg:
            runner_cwd = Path(cwd_arg)
            if not runner_cwd.is_absolute():
                runner_cwd = (self.root / runner_cwd).resolve()
            else:
                runner_cwd = runner_cwd.resolve()
        else:
            runner_cwd = Path(getattr(self, "cwd", self.root)).resolve()

        permitted_cwd_roots = [
            self.root.resolve(),
            Path(tempfile.gettempdir()).resolve(),
        ]
        try:
            permitted_cwd_roots.append(Path("/tmp").resolve())
        except Exception:
            pass

        if not any(runner_cwd.is_relative_to(r) for r in permitted_cwd_roots):
            raise ValueError(f"Path '{cwd_arg}' traverses outside allowed directories: {runner_cwd}")

        allowed_roots = [
            self.root.resolve(),
            runner_cwd.resolve(),
            Path(tempfile.gettempdir()).resolve(),
        ]
        try:
            allowed_roots.append(Path("/tmp").resolve())
        except Exception:
            pass

        resolved_files = []
        for f in files_arg:
            if not isinstance(f, (str, Path)):
                raise ValueError(f"Invalid file path: {f!r}")
            f_str = str(f).strip()
            if not f_str:
                raise ValueError("File path cannot be empty")
            path = Path(f)
            if not path.is_absolute():
                if (runner_cwd / path).is_file():
                    path = runner_cwd / path
                else:
                    path = self.root / path
                resolved = path.resolve()
                if not (resolved.is_relative_to(self.root.resolve()) or resolved.is_relative_to(runner_cwd.resolve())):
                    raise ValueError(f"Path '{f}' traverses outside allowed directories: {resolved}")
            else:
                resolved = path.resolve()
                if not any(resolved.is_relative_to(r) for r in allowed_roots):
                    raise ValueError(f"Path '{f}' traverses outside allowed directories: {resolved}")
            resolved_files.append((f, path))

        with self._scan_lock:
            conn = self._get_write_connection()
            try:
                records = []
                for f, path in resolved_files:
                    try:
                        r = ingest.ingest(conn, self.root, runner_cwd, path)
                        records.append((f, r))
                    except (ingest.UnknownFormat, OSError, ValueError, SyntaxError) as err:
                        raise ValueError(f"{f}: not loaded: {err}") from err
            finally:
                conn.close()

            total_unmapped = sum(r["unmapped"] for _, r in records)

            if fmt == "json":
                return json.dumps({
                    "files": [
                        {
                            "file": str(f),
                            "format": r["format"],
                            "lines": r["lines"],
                            "files": r["files"],
                            "results": r["results"],
                            "edges": r["edges"],
                            "unmapped": r["unmapped"],
                        }
                        for f, r in records
                    ],
                    "total_lines": sum(r["lines"] for _, r in records),
                    "total_files": sum(r["files"] for _, r in records),
                    "total_results": sum(r["results"] for _, r in records),
                    "total_edges": sum(r["edges"] for _, r in records),
                    "total_unmapped": total_unmapped,
                }, indent=2)

            lines = []
            for f, r in records:
                lines.append(
                    f"{f}: {r['format']}, {r['lines']} lines in {r['files']} files, {r['results']} test results, "
                    f"{r['edges']} coverage test links, {r['unmapped']} unmapped"
                )
            if total_unmapped:
                lines.append(f"{total_unmapped} paths or test cases matched nothing in the model; see the unmapped_coverage diagnostics")
            return "\n".join(lines)

    def handle_init(self, args: dict) -> str:
        from cbi import scan as scan_pipeline

        team = bool(args.get("team", False))
        fmt = args.get("format", "text")
        if fmt not in ("text", "json"):
            fmt = "text"

        with self._scan_lock, self._stdout_lock:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                scan_pipeline.init_repo(self.root, self.out, team_mode=team)
            output = buf.getvalue().strip()

            if fmt == "json":
                ignore_path = self.out / "ignore"
                return json.dumps({
                    "status": "ok",
                    "root": str(self.root),
                    "out": str(self.out),
                    "ignore_file": str(ignore_path),
                    "team": team,
                    "output": output,
                }, indent=2)

            return output

    def run(self, stdin=None, stdout=None):
        if stdin is None:
            stdin = sys.stdin
        if stdout is None:
            stdout = sys.stdout

        while True:
            try:
                req, is_content_length = read_message(stdin)
            except MessageParseError as err:
                err_resp = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": f"Parse error: {err}"},
                }
                write_message(stdout, err_resp, content_length=err.is_content_length)
                continue
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


class InstallResult(list):
    """List of updated config Paths that compares equal to 0 on full success."""

    def __init__(self, items=None, success=True):
        super().__init__(items or [])
        self.success = success

    def __eq__(self, other):
        if other == 0:
            return self.success
        return super().__eq__(other)


def install_client_config(client_name: str = "all", root=None):
    """Install or merge codebase-inspector MCP server configuration for AI coding clients."""
    client = (client_name or "all").lower().strip()
    valid_clients = {"claude", "cursor", "gemini", "antigravity", "windsurf", "vscode", "all"}
    if client not in valid_clients:
        print(
            f"Unknown client '{client}'. Choose from: claude, cursor, gemini, windsurf, vscode, all",
            file=sys.stderr,
        )
        return 1

    if root is None:
        try:
            root = files.repo_root(Path.cwd())
        except files.NotARepo:
            root = Path.cwd()
    root = Path(root).resolve()

    home = Path.home()
    cbi_cmd = shutil.which("cbi") or "cbi"
    default_server_entry = {
        "command": "cbi",
        "args": ["mcp"],
    }
    # Desktop apps (like Claude Desktop) need explicit repository path via --repo and resolved executable
    desktop_server_entry = {
        "command": cbi_cmd,
        "args": ["mcp", "--repo", str(root)],
    }

    claude_code_path = home / ".claude.json"
    if sys.platform == "darwin":
        claude_desktop_path = home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    elif sys.platform == "win32":
        claude_desktop_path = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming")) / "Claude" / "claude_desktop_config.json"
    else:
        claude_desktop_path = home / ".config" / "Claude" / "claude_desktop_config.json"

    targets = []
    if client in ("claude", "all"):
        targets.append((claude_code_path, default_server_entry))
        if claude_desktop_path.parent.exists() or claude_desktop_path.is_file():
            targets.append((claude_desktop_path, desktop_server_entry))

    if client in ("cursor", "all"):
        targets.append((home / ".cursor" / "mcp.json", default_server_entry))

    if client in ("gemini", "antigravity", "all"):
        targets.append((home / ".gemini" / "settings.json", default_server_entry))
        targets.append((home / ".gemini" / "antigravity" / "mcp_config.json", default_server_entry))
        targets.append((home / ".gemini" / "antigravity-cli" / "mcp_config.json", default_server_entry))

    if client in ("windsurf", "all"):
        targets.append((home / ".codeium" / "windsurf" / "mcp_config.json", default_server_entry))

    if client in ("vscode", "all"):
        targets.append((root / ".vscode" / "mcp.json", default_server_entry))

    updated_paths = []
    has_errors = False
    for target, server_entry in targets:
        data = {}
        if target.is_file():
            try:
                content = target.read_text(encoding="utf-8").strip()
                if content:
                    try:
                        data = json.loads(content)
                    except json.JSONDecodeError:
                        data = jsonc._jsonc(content)
            except Exception as err:
                print(f"Skipping {target}: existing file could not be parsed as JSON ({err})", file=sys.stderr)
                has_errors = True
                continue

        if not isinstance(data, dict):
            print(f"Skipping {target}: expected JSON object at top level", file=sys.stderr)
            has_errors = True
            continue

        target.parent.mkdir(parents=True, exist_ok=True)

        # VS Code uses "servers", whereas Claude, Cursor, Gemini, and Windsurf use "mcpServers"
        if "servers" in data or target == root / ".vscode" / "mcp.json":
            if "servers" not in data or not isinstance(data["servers"], dict):
                data["servers"] = {}
            data["servers"]["codebase-inspector"] = server_entry

        if "mcpServers" not in data or not isinstance(data["mcpServers"], dict):
            data["mcpServers"] = {}
        data["mcpServers"]["codebase-inspector"] = server_entry

        target.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        updated_paths.append(target)
        print(f"Installed codebase-inspector MCP server configuration in {target}")

    return InstallResult(updated_paths, success=not has_errors and len(updated_paths) > 0)


def run_server(root=None, out=None, stdin=None, stdout=None):
    server = MCPServer(root=root, out=out)
    return server.run(stdin=stdin, stdout=stdout)


if __name__ == "__main__":
    sys.exit(run_server())

# Codebase Inspector (cbi)

> **Fast, deterministic codebase map for AI coding agents.**
> 100% local, links tests to code, eliminates grep loops, zero LLM tokens.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)

---

## 30-Second Demo

```
$ cbi scan
scanned in 6.9 s (95 classes, 122 functions, 393 methods, 539 test cases)

$ cbi tests-for class:HTTPTransport
test case  test_transport_for_request  tests/client/test_proxies.py:34
test case  test_sync_proxy_close       tests/client/test_proxies.py:113

$ cbi cycles
files:
  httpx/__init__.py → httpx/_client.py → httpx/_transports/default.py → httpx/__init__.py
```

---

## Why CBI?

When AI coding agents enter a large codebase, they burn thousands of tokens in repetitive grep loops, lose context on module boundaries, and hallucinate import paths.

`cbi` parses your repository using `tree-sitter` into a local SQLite knowledge graph:
* **Zero Model Inside:** 100% deterministic local AST parsing with no network calls and zero token cost.
* **Tests Linked to Code (`tests-for`):** Instantly know which test files and cases cover modified symbols.
* **Architectural PR Diffs (`review`):** Structural change overviews and Mermaid diagrams for pull requests.
* **CI Gatekeeper (`check`):** Run in GitHub Actions to ensure your committed architecture map stays current.
* **MIT Forever:** Fully open source under the MIT licence. All local CLI features remain free forever.

---

## Quick Start

### One-line Run (uvx)
```bash
uvx --from git+https://github.com/joshuavial/codebase-inspector cbi prime
```

### Install CLI
```bash
uv tool install git+https://github.com/joshuavial/codebase-inspector
```

From a local checkout:
```bash
uv tool install .
```

Then run `cbi prime`, followed by `cbi init` and `cbi scan` when prompted.

---

## Essential Commands

From any repository root:

```bash
cbi prime              # Orientation guide for your agent
cbi scan               # Map repository into .cbi/model.db
cbi context [node]     # Architecture overview or node context for AI agents
cbi mcp                # Run stdio Model Context Protocol server for coding agents
cbi query "<sql>"      # Safe read-only SQL queries and schema introspection
cbi search <symbol>    # Fast full-text search across all AST nodes
cbi show <node-id>     # Detailed symbol info, callers, and children
cbi tests-for <symbol> # Find all tests exercising this symbol
cbi cycles             # Detect circular import dependencies
cbi hotspots           # Rank files and folders by coupling (fan-in/fan-out)
cbi endpoints          # List HTTP routes with handlers, callers, and database tables
cbi tables             # List database tables, columns, foreign keys, and code references
cbi review BASE..HEAD  # Generate architectural PR review & Mermaid graph
cbi build              # Export interactive static HTML viewer
cbi check              # CI gate: fail if committed map drifts from source
```

Coding agents connecting via MCP (such as Claude Code) can launch `cbi mcp` to run a stdio Model Context Protocol server exposing repository search, symbol lookup, and test linkage directly to your agent.

### Model Context Protocol (MCP) Server

AI coding agents (Claude Code, Cursor, Gemini CLI, Antigravity, Windsurf, Codex) can interact with Codebase Inspector over stdio JSON-RPC 2.0 via `cbi mcp`:

```bash
# Automatically install MCP server configuration for your AI coding client
cbi mcp --install claude    # Claude Code (~/.claude.json) / Claude Desktop
cbi mcp --install cursor    # Cursor (~/.cursor/mcp.json)
cbi mcp --install gemini    # Gemini CLI / Antigravity (~/.gemini/antigravity-cli/mcp_config.json)
cbi mcp --install windsurf  # Windsurf (~/.codeium/windsurf/mcp_config.json)
cbi mcp --install vscode    # VS Code (.vscode/mcp.json)
cbi mcp --install all       # All supported clients

# Print ready-to-use client configuration snippet
cbi mcp --config claude     # Claude Desktop
cbi mcp --config cursor     # Cursor (.cursor/mcp.json)
cbi mcp --config gemini     # Gemini CLI / Antigravity
cbi mcp --config windsurf   # Windsurf
cbi mcp --config vscode     # VS Code
cbi mcp --config all        # All client templates
```

Exposed MCP tools:
* `cbi_init`: Initialize .cbi directory and default ignore file in repository root (optional: `team`, `format`).
* `cbi_ingest`: Ingest test coverage and result files (lcov, coverage.py JSON, JUnit XML) into codebase model (`files`: array of strings, optional `format`: text or json).
* `cbi_scan`: Scan repository into model.db and open judgement tasks, with optional git ref scanning (`ref`: branch, tag, or commit SHA; `format`: text or json).
* `cbi_status`: Scan state, task counts, and codebase diagnostics.
* `cbi_context`: Markdown summary of any node (file, symbol, concept, package), or top-level system architecture overview when omitted or passed as 'system'.
* `cbi_show`: Full node details (attributes, children, relationships, tests, diagnostics, concept details, screens, and endpoints) with confidence filtering and cap toggle (format: text or json).
* `cbi_tests_for`: Tests linked to a specific function, class, file, or folder.
* `cbi_search`: Full-text search across all AST nodes in the codebase.
* `cbi_hotspots`: Rank nodes by coupling (fan-in/fan-out), size (LOC), or symbol count.
* `cbi_cycles`: Detect dependency cycles at file, folder, and package levels.
* `cbi_orphans`: Identify orphaned code, test-only exported symbols, unreachable files, and untested packages/folders.
* `cbi_deps`: Container dependency matrix between packages, folders, concepts, or deployables.
* `cbi_diff`: Architectural diff between commits, branches, or model databases, with drill-down options (`concept`, `module`, `file`, `symbol`; `format`: text, markdown, or json; `detail`: boolean).
* `cbi_tasks`: Query open judgement tasks or retrieve full task briefs with input schemas.
* `cbi_submit`: Submit an answer for an open judgement task (task_id and answer object or JSON string) with database write serialization.
* `cbi_query`: Execute read-only SQL queries against the local codebase model database.
* `cbi_concepts`: Query concept taxonomy, hierarchy, role descriptions, and file ownership.
* `cbi_endpoints`: List HTTP route endpoints detected in the codebase model with their handlers, caller references, downstream code calls, and database tables (optional filters: path, method, handler, table).
* `cbi_tables`: List database tables, columns, foreign keys, and code references detected in the codebase model (optional filter: table).
* `cbi_history`: Architecture evolution and changelog across git history points on the default branch (optional filters: since, until, concept, limit; format: markdown, json, text).
* `cbi_review`: Architectural review between two versions (branch, commit, PR, or HEAD against base) including a Mermaid diagram, changed concepts, and untested changes (format: markdown or json).
* `cbi_check`: Verify that committed map and judgement files match files changed since the merge base with default branch or a specified base ref (format: text or json).
* `cbi_worktrees`: List the repository's worktrees and local branches, their head commits, lanes, and model statuses (format: text or json).
* `cbi_prime`: State-aware guide for an agent meeting cbi for the first time. Reports repository mapping status, open judgement tasks breakdown, the task loop, and ingest instructions (format: markdown or text).
* `cbi_task`: Print the brief for one judgement task, inspect partitioned parts for large briefs, or pre-validate an answer JSON schema before submission (format: text or json).

Exposed MCP resources:
* `cbi://system/overview`: High-level architecture overview, concepts, key components, and boundaries (Markdown).
* `cbi://model/status`: Codebase scan state, task counts, and codebase diagnostics (JSON).
* `cbi://model/schema`: SQLite schema and table definitions of `model.db` (plain text DDL).
* `cbi://concepts`: Architecture concepts map and mapped nodes (JSON).
* `cbi://node/{id}`: Detailed architecture information, relationships, tests, and diagnostics for any node (JSON).
* `cbi://context/{node}`: Context brief for an agent working on a file, symbol, or concept (Markdown).

Exposed MCP prompts:
* `cbi_architecture_orientation`: Guide an agent through onboarding and understanding codebase architecture using CBI (optional `focus` argument).
* `cbi_review_pr`: Perform an architectural code review of changes between git base and head (optional `base` and `head` arguments).
* `cbi_judgement_task`: Investigate and answer an open architectural judgement task in the codebase (required `task_id` argument).

### System Views

Inspect HTTP API surface and database schemas from the command line:

```bash
# List all detected HTTP endpoints or filter by method, path, handler, or table
cbi endpoints
cbi endpoints --method GET --path /api
cbi endpoints --table accounts --json

# List database tables, columns, and foreign keys or filter by table name
cbi tables
cbi tables --table accounts
cbi tables --json
```

---

## Team mode and CI

Run `cbi team init` to opt the repository into committed judgement. You can use our reusable GitHub Action to run architecture checks and generate visual PR reviews:

```yaml
  - uses: actions/checkout@v4
    with:
      fetch-depth: 0
  - uses: joshuavial/codebase-inspector@v0.3.0
    with:
      base-ref: ${{ github.base_ref || 'main' }}
```

See [`docs/github-action.md`](docs/github-action.md) for complete action configuration, outputs, and PR commenting workflows.

The gate reads the working tree and committed answers without calling a model. Commit `.cbi/answers.jsonl`, `concepts.json`, `structure.json`, `screens.json`, `ignore`, `team.toml` and the generated `.gitignore` as appropriate for the repository.

## Explain an architectural change

Run `cbi diff BASE HEAD` or `cbi review BASE..HEAD` to open judgement tasks for each changed concept and the whole diff. The tool supplies facts; an agent supplies the explanations.

```
cbi tasks --kind summarise-architecture-change
cbi task TASK_ID --json
cbi submit TASK_ID answer.json
cbi diff BASE HEAD
cbi build --compare BASE..HEAD
```

The task commands work without `--ref`, including after a fresh `cbi init` followed by a diff: cbi records which comparison head holds that inbox when an ordinary model has not been scanned yet.

Each answer copies the brief's `input_hash`, gives a `narrative` paragraph explaining what changed, why it matters, affected callers/users and risk, and lists `citations` copied from the allowed symbol IDs/file paths. References outside the supplied diff are rejected. Answers are reused across diff, review and viewer builds until either model changes. Unanswered summaries show `Summary pending: run cbi tasks`.

## Desktop App

The app in `app/` is a thin Electron shell over the installed `cbi` CLI. It remembers recent projects, switches worktrees and branches, and shows the same viewer. See `app/README.md`.

```bash
cd app
npm install
npm start
```
Pre-built desktop packages for macOS, Windows, and Linux are available on the [Releases](https://github.com/joshuavial/codebase-inspector/releases) page.

---

## Determinism vs. Agent Judgement

CBI makes a strict guarantee: **The tool itself never calls an LLM.**

Static facts (ASTs, symbols, imports, call graphs, routes, SQL schemas, test links) are computed 100% deterministically. High-level semantic summaries (concepts, file summaries, change narratives) are populated by your coding agent through the `cbi tasks` / `cbi submit` protocol and committed under `.cbi/` in team mode (`answers.jsonl`, `concepts.json`, `structure.json` and `screens.json`).

Read the full specification: [`docs/determinism-and-enrichment.md`](docs/determinism-and-enrichment.md).

---

## Licence

MIT License. Free and open source forever.

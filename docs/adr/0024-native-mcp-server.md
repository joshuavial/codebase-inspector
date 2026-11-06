# ADR-0024: Native Model Context Protocol (MCP) server

Status: Accepted. Date: 2026-11-06.

## Context

Autonomous AI coding agents (Claude Code, Cursor, Codex, Antigravity, Windsurf) require structured, machine-readable access to codebase models to navigate dependencies, trace architecture boundaries, verify changes, and execute judgement tasks.

Previously, agent integration with CBI required running CLI commands via shell tool calls (`cbi show`, `cbi search --json`, `cbi tasks`). This pattern introduces friction in agent workflows:
- Shelling out adds process startup and subshell execution overhead for every interaction.
- Agents must parse unstructured stdout text or extract JSON with flags, leading to brittle regex heuristics or text parsing errors.
- Agents lack standardized machine-readable tool schemas, argument validation, protocol-level errors, context resource injection, and task prompt templates.
- Integrating CBI into different developer environments and AI editors requires manual edits to disparate configuration files across clients.

Agents need a direct, standardized protocol to discover capabilities, query codebase models, and execute judgements natively within their execution loops.

## Decision

Provide a native Model Context Protocol (MCP) server directly in the CBI CLI via `cbi mcp`, operating over stdio JSON-RPC 2.0 (protocol version `2024-11-05`).

The implementation comprises six core architectural components:

1. **Stdio JSON-RPC 2.0 transport and framing**:
   - Communicates over standard input and standard output (`stdin`/`stdout`), supporting both standard HTTP `Content-Length` header framing and newline-delimited JSON for broad client compatibility.
   - All diagnostic, status, and error logs are isolated to `stderr` to maintain protocol stream integrity.

2. **Zero-daemon, direct SQLite model access**:
   - The server runs on demand as a child process of the editor or agent client. No persistent background daemon, service manager, or listening TCP socket is required, avoiding port collisions, stale state across worktrees, background process leaks, and socket security/authentication concerns.
   - Queries directly access the local SQLite codebase model (`.cbi/model.db`) and shared task cache (`answers.db`) in-process using `store.read_only()` under WAL mode.
   - Mutating operations (`cbi_scan`, `cbi_submit`, `cbi_ingest`) coordinate safely through SQLite write transactions with concurrency locks.

3. **25 domain-specific MCP tools**:
   - Complete coverage of CBI functionality exposed with strict JSON Schema definitions, enum constraints, and typed outputs:
     - **Mapping & Initialization**: `cbi_init`, `cbi_scan`.
     - **Navigation & Queries**: `cbi_context`, `cbi_show`, `cbi_search`, `cbi_query`, `cbi_concepts`, `cbi_endpoints`, `cbi_tables`, `cbi_worktrees`, `cbi_prime`.
     - **Dependency & Architecture Analysis**: `cbi_deps`, `cbi_cycles`, `cbi_orphans`, `cbi_hotspots`.
     - **Diagnostics & Testing**: `cbi_status`, `cbi_tests_for`, `cbi_ingest`.
     - **Judgement Tasks**: `cbi_tasks`, `cbi_task`, `cbi_submit`.
     - **Change & Evolution**: `cbi_diff`, `cbi_history`, `cbi_review`, `cbi_check`.

4. **6 context resources and templates**:
   - Structured model artifacts exposed through the `cbi://` URI scheme:
     - `cbi://system/overview`: High-level system architecture overview, concepts, and component boundaries (Markdown).
     - `cbi://model/status`: Scan state, task counts, and codebase diagnostics (JSON).
     - `cbi://model/schema`: Database schema of `model.db` for constructing custom queries (plain text).
     - `cbi://concepts`: Architecture concept map, roles, and node assignments (JSON).
     - `cbi://node/{id}`: Detailed node attributes, dependencies, tests, and diagnostics (JSON template).
     - `cbi://context/{node}`: Targeted Markdown context brief for a given file, symbol, or concept (Markdown template).

5. **3 standardized MCP prompts**:
   - Guided agent workflows parameterized for high-frequency coding and architecture scenarios:
     - `cbi_architecture_orientation`: Orientation guide for onboarding an agent into the repository architecture, major concepts, and key interfaces.
     - `cbi_review_pr`: Architectural review of changes between git base and head, highlighting untested changes, concept impacts, and Mermaid visual summaries.
     - `cbi_judgement_task`: Guided workflow to investigate, outline, and answer open architectural judgement tasks.

6. **Automated client configuration (`cbi mcp --install <client>`)**:
   - One-step installation command that locates and merges MCP configuration for supported clients: Claude Code (`~/.claude.json`), Claude Desktop (`claude_desktop_config.json`), Cursor (`~/.cursor/mcp.json`), Antigravity/Gemini (`settings.json` and `mcp_config.json`), Windsurf (`mcp_config.json`), and VS Code (`.vscode/mcp.json`).
   - Automatically detects whether standard relative execution or explicit absolute binary paths (`--repo`) are required (such as for desktop GUI applications).

## Alternatives considered

- **Shell commands only (status quo)**: Rely on agent skills and bash subshells (`cbi show`, `cbi search --json`). Kept as an interface for humans and CI scripts, but discarded as the primary agent interface due to process overhead and lack of formal protocol schema discovery.
- **REST / HTTP daemon**: Run a background daemon listening on an HTTP port. Rejected: requires managing port allocations across multiple projects and worktrees, persistent process lifecycles, and authentication mechanisms, while risking stale models when git branches switch.
- **Third-party MCP Python SDK**: Adopt the official `mcp` Python SDK package. Rejected: introduces heavy transitive dependencies (AnyIO, Pydantic, Starlette/SSE) to a core CLI designed for zero-dependency portability and instant startup. Implementing JSON-RPC 2.0 stdio handling directly in standard library Python maintains sub-millisecond startup and zero external dependencies.

## Consequences

- AI agents interact with CBI codebase models via structured RPC calls, eliminating shell quoting, string concatenation, and output parsing errors.
- In-process SQLite model queries execute with sub-millisecond latency.
- Client setup across major coding assistants is automated with a single command.
- The MCP server surface must be maintained in sync with CLI features: new commands, queries, tasks, and diagnostic capabilities must be exposed across both CLI and MCP entry points.

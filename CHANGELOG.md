# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `cbi render`: headless Chrome diagram rendering (--view top|overview|ID, --compare, --png, --svg).
- `cbi history`: default-branch architecture history tracking (--since, --until, --concept, --limit, --write, --narrate, --json).
- Historical `ref` parameter across MCP inspection and graph analysis tools (cbi_show, cbi_context, cbi_deps, cbi_cycles, cbi_orphans, cbi_hotspots, cbi_status, etc.).
- Standardized `--json` flag across review, diff, history, and check CLI commands.
- CI flags for `cbi check` (--base, --kind, --format {text,github,json}, and --json).
- Isolated out-of-tree model directory cache in `cbi gallery` via `--cache-dir` (default: `<out-dir>/models/<repo_name>/model.db`), guaranteeing external repositories remain strictly read-only without in-tree modifications or untracked `.cbi/` directories (`cbi-5ru.2`).
- Detected Starlette and FastAPI explicit `Route` and `WebSocketRoute` declarations and Flask `app.add_url_rule` endpoint registrations in Python AST parser (`cbi-5ru.1`).
- Auto-initialization in `cbi scan` when a custom `--out` directory is clean or missing (`cbi-5ru.3`).
- `--metric` argument alias in `cbi hotspots` matching MCP parameter name (`cbi-kr7`).
- `--start` and `--end` argument aliases in `cbi deps` matching MCP parameter names (`cbi-2va.3`).

### Changed

- `cbi scan` takes the git index blob id of tracked files that `git diff-files` sees as unchanged instead of reading them from disk, cutting the hash phase on large repos several-fold. Files with filters, working-tree encodings, assume-unchanged or skip-worktree flags are still read, and line-ending conversions are checked against the blob size, so hashes stay identical to raw-bytes hashing (`cbi-4dx.1`).
- Concurrent AST symbol parsing in `_parse_changed` using a `ThreadPoolExecutor` worker pool across CPU cores (capped or overridden by `CBI_PARSE_WORKERS`), maintaining deterministic model insertion and transaction rollback on error (`cbi-4dx.2`).
- Concurrent Markdown document reading and mention extraction in `docs.py` using a `ThreadPoolExecutor`, speeding up doc indexing across repositories with extensive documentation while preserving doc ordering (`cbi-4dx.3`).

### Fixed

- Attention ranking in change overview for concept-renamed and integration-removed.
- Recognition of squash-merged pull requests as architecture history points.
- MCP domain error propagation with isError: True instead of plain text.
- Mermaid ER diagram attribute type formatting for precision/scale types and escaped double quotes.
- Diff hunk parsing in git_line_stats for content lines starting with --- or +++.
- Guarded history_points git rev-parse against root merge commits and shallow CI clones.
- MCP `cbi_tasks` schema declared `offset` integer property for pagination and `cbi_diff` declared `base_model`/`head_model` (`cbi-zfg`).
- MCP `cbi_tests_for`, `cbi_search`, and `cbi_hotspots` schemas declared `format` property with text/json enum (`cbi-2cj`).
- Architecture documentation header aligned to cover PRD-01 to PRD-08 (`cbi-2va.2`).


## [0.4.0] - 2026-11-09

### Added

- `cbi tables --format markdown` (GFM tables) and `cbi tables --format mermaid` (Mermaid `erDiagram` with tables, columns, PK/FK, relationships).
- `cbi endpoints --format markdown` (GFM tables of routes, HTTP methods, handlers, callers, and tables).
- `format` parameter on `cbi_tables` and `cbi_endpoints` MCP tools.
- Database schema migrations and HTTP endpoint impacts surfaced in `cbi diff` and `cbi review` with Mermaid visualization.
- First-class `cbi gallery` CLI subcommand compiling multi-repo architecture showcases.
- 25 native MCP tools and prompts over stdio JSON-RPC (`cbi mcp`), plus `cbi mcp --install` automated configuration generator for Claude Code, Cursor, and Windsurf.
- Unified local smoke verification harness `scripts/smoke_all.py` validating 21 end-to-end checkpoints offline.

### Changed

- Updated documentation across `docs/prd-04-change-review.md`, `docs/prd-05-system-views.md`, `docs/prd-08-change-overview.md`, `docs/architecture.md`, and `docs/github-action.md`.

### Fixed

- Hardened Playwright browser availability probe and graceful fallback in viewer tests (`cbi-ecw.1`).
- Fixed package name matching and added git shallow history depth guard in reusable GitHub Action (`cbi-ecw.2`).
- Process-group reaping and test determinism improvements.


## [0.3.0] - 2026-11-06

### Added

- Native stdio JSON-RPC Model Context Protocol (MCP) server under `cbi mcp`, enabling AI coding agents (Claude Code, Cursor, Codex, Antigravity) to query the local codebase model directly. Exposes tools `cbi_status`, `cbi_context`, `cbi_tests_for`, `cbi_search`, and `cbi_hotspots` with dual newline-delimited and Content-Length transport framing.
- Grounded `summarise-architecture-change` judgement tasks with diff evidence enforcement and citation checking across changed concepts and PR reviews.
- Option A launch headline and streamlined agent documentation.

### Changed

- Updated Electron to ~44.10.2 and resolved npm audit alerts.
- Polished CLI and review task guidance for coding agents.

### Fixed

- Preserved historical model projections during commit scans when ref models carry committed maps.
- Repaired GitHub Actions workflow artifact download permissions.


## [0.2.0] - 2026-10-29

### Added

- `cbi history` prints an architecture changelog for the default branch, built incrementally and including pre-merge commits. It filters by date or concept, writes `.cbi/CHANGELOG-ARCHITECTURE.md` with `--write`, and `--narrate` opens a task to summarise one entry. The viewer shows it as a timeline.
- System views: database diagrams from SQL migrations and common ORMs, with code reads and writes linked to tables, and an API endpoint view. The viewer shows them as system tabs, and large schemas focus on the connected columns.
- A ranked change overview in `cbi diff`, `cbi review` and the viewer. The diff viewer defaults to changed concepts and their neighbours.
- `cbi prime` guides stored ref models.
- `cbi bug` opens a public GitHub issue draft, with `--print`, `--title` and `--message` options. The desktop Help menu and map errors offer the same report flow. Drafts include a small runtime environment block and strip private details from automatic error text.

### Changed

- Long concept chains lay out as a snake grid that fills the window, with labels kept off lines.
- Orphan reports trace reachability from framework roots, package script entries, agent scripts and host extensions, Python `__main__` modules and package initializers, and barrel modules. Conventional tool configuration and test support files are no longer reported as orphans.
- Functions passed as values count as references. Empty files get a deterministic summary. Newer committed concept answers win.
- Scan, build, diff and history are faster on large repositories, and ref models share parse results.

### Fixed

- Stale or concept-less ref models no longer show unchanged concepts as removed.
- History concepts from submodule files no longer collide, history date filters are inclusive, and history navigation stays stable across system tabs.
- The screens check keeps excluded templates excluded.
- Python imports resolve under package directories that are not identifiers, and committed virtualenvs are no longer ignored by default.
- Team judgement files stay visible to Git.

## [0.1.0] - 2026-10-10

First public release.

### Added

- `cbi scan` maps a git repository into a model of the workspace, deployables, packages, folders, files, symbols and tests. The tool does not call a model and does not run the target's code.
- Judgement tasks (`cbi tasks`, `cbi submit`) ask an agent for file summaries and a concept map.
- Concepts and screen sketches (React, Vue, HTML pages and server templates), stored in the model and shown in the viewer.
- Queries: `cbi search`, `cbi show`, `cbi tests-for` and `cbi status`. Reviewer queries: `cbi hotspots`, `cbi orphans`, `cbi cycles` and `cbi deps`.
- `cbi context` writes a short markdown brief for an agent.
- `cbi diff` compares two versions of the model.
- `cbi review` writes `review.md` with a Mermaid flowchart, and before and after PNG and SVG images when Chrome or Chromium is installed.
- `cbi ingest` reads lcov, coverage.py JSON and JUnit XML.
- Team mode (`cbi team init`) and `cbi check` for CI. The check reads the working tree. It does not call a model or the network.
- `cbi open` hands the desktop app a `cbi://` link. `cbi open-file` opens one file in the editor.
- A static viewer that opens from disk, with no server: a concept map, wireframes and a comparison.
- A desktop app for recent projects, worktrees and branches, a live rescan, the same viewer, and `cbi://` links.
- The app and `cbi prime` say when a newer release is available, with release notes and a download link. Nothing installs itself.
- `cbi open` and `cbi://` links open the app in the background without taking focus.
- Languages: Python, TypeScript and JavaScript (including TSX), Vue, and C#.

### Known limits

- Release builds are unsigned. macOS Gatekeeper and Windows SmartScreen warn the first time you open one.
- macOS is the primary development and test platform. Windows and Linux builds are produced, and the command line and the app avoid macOS-only paths, but day to day testing happens on macOS.

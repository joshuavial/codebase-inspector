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
cbi mcp                # Run stdio Model Context Protocol server for coding agents
cbi search <symbol>    # Fast full-text search across all AST nodes
cbi show <node-id>     # Detailed symbol info, callers, and children
cbi tests-for <symbol> # Find all tests exercising this symbol
cbi cycles             # Detect circular import dependencies
cbi hotspots           # Rank files and folders by coupling (fan-in/fan-out)
cbi review BASE..HEAD  # Generate architectural PR review & Mermaid graph
cbi build              # Export interactive static HTML viewer
cbi check              # CI gate: fail if committed map drifts from source
```

Coding agents connecting via MCP (such as Claude Code) can launch `cbi mcp` to run a stdio Model Context Protocol server exposing repository search, symbol lookup, and test linkage directly to your agent.

---

## Team mode and CI

Run `cbi team init` to opt the repository into committed judgement. Add the printed job steps to your CI workflow:

```yaml
  - uses: actions/checkout@v4
  - uses: astral-sh/setup-uv@v5
  - run: uv tool install .
  - run: cbi check
```

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

# Codebase Inspector (cbi)

<!-- SWAPPABLE HEADLINE START -->
<!-- Option A (Recommended based on demand evidence): Agent Codebase Map -->
> **The deterministic, local codebase map for AI coding agents.**  
> Give Claude Code, Codex, and Gemini an instant structural index of your repository. 100% local AST parsing, tests linked to code, zero LLM tokens to scan.
<!-- Option B (Alternative): Deterministic Architecture PR Review -->
<!-- > **Deterministic architecture review for pull requests and CI.** -->
<!-- > See what a PR changed in your system's shape with Mermaid diagrams, before/after visual maps, and zero-token CI gates. -->
<!-- SWAPPABLE HEADLINE END -->

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)

---

## 30-Second Demo

<!-- Placeholder for docs/images/cbi-demo.gif (see docs/launch-metadata.md for storyboard) -->
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
uvx cbi prime
```

### Install CLI
```bash
uv tool install codebase-inspector
```

*(From source or git)*
```bash
uv tool install git+https://github.com/joshuavial/codebase-inspector
```

---

## Essential Commands

From any repository root:

```bash
cbi prime              # Orientation guide for your agent
cbi scan               # Map repository into .cbi/model.db
cbi search <symbol>    # Fast full-text search across all AST nodes
cbi show <node-id>     # Detailed symbol info, callers, and children
cbi tests-for <symbol> # Find all tests exercising this symbol
cbi cycles             # Detect circular import dependencies
cbi hotspots           # Rank files and folders by coupling (fan-in/fan-out)
cbi review <base..head># Generate architectural PR review & Mermaid graph
cbi build              # Export interactive static HTML viewer
cbi check              # CI gate: fail if committed map drifts from source
```

---

## Desktop App

A lightweight Electron viewer is included in `app/`:
```bash
cd app
npm install
npm start
```
Pre-built desktop packages for macOS, Windows, and Linux are available on the [Releases](https://github.com/joshuavial/codebase-inspector/releases) page.

---

## Determinism vs. Agent Judgement

CBI makes a strict guarantee: **The tool itself never calls an LLM.**

Static facts (ASTs, symbols, imports, call graphs, routes, SQL schemas, test links) are computed 100% deterministically. High-level semantic summaries (concepts, file summaries, change narratives) are populated by your coding agent through the `cbi tasks` / `cbi submit` protocol and committed to `.cbi/team/`.

Read the full specification: [`docs/determinism-and-enrichment.md`](docs/determinism-and-enrichment.md).

---

## Licence

MIT License. Free and open source forever.

# ADR-0008: Python mapper with tree-sitter and SQLite

Status: Accepted. Date: 2026-10-07.

## Context

The mapper has to parse several languages, keep going when a file has a syntax error, and answer `show` and `search` on a repository the size of sample-monorepo. Agent skills already ship Python. The model is derived from the checkout, so the store is a rebuildable file. The viewer is a separate, static page (ADR-0007).

## Decision

The mapper is Python on 3.11 or newer, installed with uv so `cbi` is on `PATH` in its own environment. Parsing uses py-tree-sitter and tree-sitter-language-pack. PRD-01 parses TypeScript, TSX, JavaScript and Python into symbols. Other languages are file nodes.

The model is one SQLite database per mapped repository, opened with the standard library, with FTS5 for search. The database path is `.cbi/model.db`, or the matching path under `--out` (ADR-0006).

The mapper does not install the target's dependencies and does not build the target. The viewer stays plain JavaScript.

## Alternatives considered

- A TypeScript mapper on web-tree-sitter. Rejected: WASM grammar management, and the skill stack does not otherwise use Node for this work.
- SCIP indexers as the way to read the code. Rejected: they need each repository's dependencies installed (ADR-0004).
- The recommendation, which was kept: Python, py-tree-sitter, tree-sitter-language-pack and uv, with a plain JavaScript viewer.

## Consequences

tree-sitter is held below 0.26. Version 0.26.0 segfaults on node access after repeated parses of one file. 0.25 does not. Runtime dependencies are floored. `uv.lock` pins them for development. A parse error on one file becomes a `parse_error` diagnostic and the scan continues. FTS5 is required. The schema version is SQLite's `user_version`.

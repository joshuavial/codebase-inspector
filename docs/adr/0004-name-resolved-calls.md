# ADR-0004: Name-resolved calls, SCIP later

Status: Accepted. Date: 2026-10-07.

## Context

Calls are how tests attach to the code they exercise, and how a later map draws arrows between parts. A type-aware index needs the repository's dependencies installed and a successful build. PRD-01 has to map a checkout that has neither. Dynamic dispatch in these repositories will leave many calls unresolved.

## Decision

Imports resolve inside the file's own workspace: relative paths, re-exports, TypeScript `paths` and `baseUrl`, and Python packages. An import edge points at the file that defines each imported name.

A call is kept when the callee name can be bound. The binding is a definition in the same file, a name imported into the file, or a method on the enclosing class (`self` or `this`), after a parameter or local with the same name wins. Each edge stores a source and a confidence from 0 to 1. A direct bind is 1.0. A `self` or `this` bind is 0.6. A call that does not bind is dropped. A call with more than one candidate is dropped and counted as an `ambiguous_call` diagnostic on the file.

SCIP ingestion is a later upgrade. It is outside PRD-01.

## Alternatives considered

- Imports only, with no call edges.
- A precise SCIP index as the PRD-01 call graph. Rejected: it needs each repository's dependencies installed.
- The recommendation, which was kept: precise imports, tree-sitter name resolution tagged with confidence, SCIP optional later.

## Consequences

The viewer hides low-confidence edges by default. Missing a dynamic call is accepted. Inventing a call is not. JSX tags and `createElement` are calls marked as renders, so a component can show what it draws (PRD-02 C5). Parse facts are stored per file so resolution can rerun without reparsing unchanged files. Package-name imports resolve inside their workspace once manifests exist. `exports` maps are not read.

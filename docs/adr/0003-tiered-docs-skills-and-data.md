# ADR-0003: Tiered handling of docs, skills and data

Status: Accepted. Date: 2026-10-07.

## Context

The sample repositories hold markdown, skills, repertoires, fixtures and generated files as well as code. Treating all of that as code would bury the map. Dropping it would hide agent assets and the docs that name the code. The split has to be editable, because a heuristic will mis-classify a directory.

## Decision

Skills, repertoires and other agent assets are packages. They display as "skill" or "repertoire" and are parsed as code.

Markdown is a `doc` node. It stays in the tree. Its title and text are searchable. A backticked path, a markdown link to a tracked file, or a unique qualified name becomes a `mentions` edge. Docs are not parsed into symbols. A directory of over 100 files, at most 10% code and at least half markdown, collapses to one `doc collection` for display. The outermost such directory wins. Files inside it are still enumerated, parsed when they are code, and searchable.

Data, fixtures, evals, generated files and tracked build output are excluded. `cbi init` writes `.cbi/ignore` in gitignore syntax, and the user can edit it. Patterns match paths from the top repository, including into submodules.

## Alternatives considered

- Every non-code file is a full node.
- Docs and skills are search-only and absent from the tree.
- Exclude docs and skills along with data.
- The recommendation, which was kept: skills as packages, docs as searchable nodes without symbols, data excluded by an ignore file the mapper writes.
- Collapse only when a directory is at least 90% markdown. That missed sample-monorepo's `docs/research` at 89.9%.

## Consequences

Doc collapse is presentation, not deletion. Init also suggests ignores for fixture and build directories, minified JS and CSS, and data-heavy directories. A doc title comes from front matter, otherwise the first heading outside a code fence. Mention confidence is 1.0 for a path or link and 0.8 for a unique qualified name. Bare names are not matched. Search text for a doc is capped.

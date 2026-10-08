# ADR-0006: In-repo self-ignoring .cbi directory

Status: Accepted. Date: 2026-10-07.

## Context

The map is derived. It has to be easy for an agent working inside the repository to find, and it must not change a tracked file. Summaries are expensive to redo and are the same for the same file bytes in any repository. The sample repositories were treated as read-only until the ignored directory itself was judged safe to write.

## Decision

`cbi init` creates `.cbi/` in the target and writes `.cbi/.gitignore` containing `*`. The model's database, the built viewer, `structure.json` and later agent-authored JSON live there. The repository's tracked files are left untouched. `--out <dir>` writes that same layout somewhere else.

`.codemap/` was the placeholder name. `.cbi/` replaces it until the product is named.

Writing this ignored directory into the sample repositories is allowed. PRD-01 uses the in-repo default on sample-desktop.

Accepted answers are cached in `~/.cache/codebase-inspector/` (`CBI_CACHE_DIR` moves it), keyed by content hash, and shared across repositories.

## Alternatives considered

- Outside the target by default, under a cache path keyed by remote and commit, with an opt-in copy in the repo. This was the recommendation. It was rejected.
- Committing the map into the target.
- Editing the target's tracked `.gitignore` instead of a directory that ignores itself.
- Keeping sample repositories read-only and always passing `--out` for them. A later entry in the same interview lifted that rule.

## Consequences

The CLI writes only under `.cbi/` or `--out`, plus the shared cache. Git commands use a fixed argument list, never a shell. A remote URL is stored only in normalised form, so credentials in the URL are not kept. Agent-authored files in `.cbi/` survive a rescan and can be edited by hand. On a schema mismatch the database is rebuilt from the repository. Cached answers are not in that database, so a rebuild keeps them.

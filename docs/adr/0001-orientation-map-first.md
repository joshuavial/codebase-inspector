# ADR-0001: Orientation map comes first

Status: Accepted. Date: 2026-10-07.

## Context

An agent or a developer in an unfamiliar repository rebuilds the picture from directories and searches, then does it again next session. The first choice was which job to serve: learning the system, day-to-day editing, or reviewing changes. Later work diffs two versions and may quiz a developer on how a part works, so the first model needs stable ids and stored summaries.

## Decision

The first increment is an orientation map (PRD-01). It records structure from the workspace down to methods, with summaries and test links, so a person can browse it and an agent can query it.

Node ids survive a rescan and a move to another machine. A workspace id is the normalised git remote: `host/owner/repo`, lowercased, with the scheme, user, port and `.git` removed. A repository with no remote, or with a `file://` remote, uses `local:<directory name>`. The pinned and checked-out commits are data on the workspace node. They are not part of the id. A file id is the workspace plus the repo-relative path. A symbol id adds the qualified name.

Summaries are stored fields on the node.

The interview named change review as the next increment. ADR-0015 gives that work a later PRD number. The orientation map stays first.

## Alternatives considered

- Day-to-day editing as the first job.
- Reviewing agent changes as the first job.
- Orientation first, with change review as PRD-02. The recommendation's order was adjusted when later increments were added (ADR-0015).
- Keying a workspace by remote plus commit. The commit stays data, so the same submodule shares ids in two superprojects.

## Consequences

Call-graph precision can wait (ADR-0004). In PRD-01 a symbol keeps its signature and docstring and gets no summary task. The model can be diffed later without a new id scheme. The product name is still open. `cbi` and `.cbi/` are placeholders.

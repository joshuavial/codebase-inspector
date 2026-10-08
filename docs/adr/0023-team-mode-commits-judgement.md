# ADR-0023: Team mode commits the judgement, not the model

Status: Accepted. Date: 2026-10-08. Supersedes ADR-0006 for repositories that opt in.

## Context

Teams want the map in the repository and current as pull requests merge. Everything in `.cbi/` is currently ignored, so every clone redoes the agent work and nobody reviews concepts. The model database is binary, cannot merge and grows with the repo; the viewer is up to 20 MB.

## Decision

A repository opts in with `cbi team init`. It then commits only the judgement: `structure.json`, `concepts.json`, `screens.json`, `answers.jsonl` (accepted summaries keyed by content hash), `CHANGELOG-ARCHITECTURE.md` and `team.toml`. Derived files (`model.db`, `viewer/`, `refs/`, `reviews/`, `history/`) stay ignored and are rebuilt by `cbi scan` and `cbi build`. Each pull request carries its own map updates, made by the author's agent, and a model-free `cbi check` in CI fails pull requests whose changed files lack summaries or owners.

## Alternatives considered

- Commit the whole `.cbi/`: binary, unmergeable and large.
- A CI job that runs an agent on merge to answer tasks: needs model credentials in CI, is slower, and puts the map outside review.
- Keep everything ignored (ADR-0006): every clone redoes the work.

## Consequences

Clones get the full map for free; concept changes are reviewed in PRs; CI needs only the CLI. Non-team repositories keep ADR-0006 behaviour. Committed answers are checked for secret-looking values.

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


## Gate consistency (2026-11-03)

`cbi check` restores the original judgement files before validating them. It
compares the concept nodes, authored externals, ownership and relationships
against a fresh projection of `concepts.json`, so a valid document with an
incomplete or different model fails the gate. This comparison rolls back its
projection and leaves the model unchanged. Concept task input hashes include
file summaries as well as source hashes and cross-file pairs; revising a summary
invalidates the previous task hash.


## Replacing concept judgements (2026-11-03)

Explicitly accepting a replacement concept map retires the older concept input
keys for that repository. Team answer rows retain a `superseded_by` marker,
which survives a fresh cache import and takes precedence over a duplicate live
row at the same or an older acceptance generation in a union merge. Retired keys are removed from the attached cache and are
never eligible for automatic restoration, even if source later returns to its
old content. A new explicit submit may accept that input again. Historical
file and group summaries remain reusable by content as before.


Automatic concept restoration checks the team retirement marker before reading
the shared cache. Deleting a retired cache row during import alone is not
sufficient: another model can subsequently publish that old input hash again.
The marker remains authoritative even when the row reappears. An explicit new
submission may still accept a reviewed answer for that input.


## Acceptance generations (2026-11-03)

Each explicit concept acceptance records a `generation` greater than every
previously observed generation for that task kind. It assigns that generation
to the accepted row and to the older keys it supersedes. Union import selects
the highest generation for each kind/key pair. A retirement marker wins a tie;
unversioned legacy rows count as generation zero. A later explicit acceptance
therefore beats an older retirement marker regardless of line order, while a
stale live row cannot erase a retirement at the same generation.

Import and export retain generation metadata in the model and team file. The
model also remembers the digest of each accepted answer, so an unrelated cache
write cannot acquire a newer acceptance generation merely by being exported.
Reaccepting an input whose cached answer and projection already match still
advances its generation when its key is marked retired. Content-keyed file and
group summary rows keep their existing unversioned behavior.

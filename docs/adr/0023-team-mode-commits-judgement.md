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
which survives a fresh cache import. Causal retirement records name the
observed acceptance identities they supersede, rather than retiring an entire
input key forever. Retired keys are removed from the attached cache and are
never eligible for automatic restoration, even if source later returns to its
old content. A new explicit submit may accept that input again. Historical
file and group summaries remain reusable by content as before.


Automatic concept restoration checks the team retirement marker before reading
the shared cache. Deleting a retired cache row during import alone is not
sufficient: another model can subsequently publish that old input hash again.
The marker remains authoritative even when the row reappears. An explicit new
submission may still accept a reviewed answer for that input.


## Acceptance identities and concurrent edits (2026-11-03)

Each explicit concept acceptance gets a unique `acceptance_id`. Its
`retired_acceptances` context names only acceptance identities already observed
for that input; replacement records likewise retire only observed identities
for the other inputs. Union import combines those contexts. An unseen
concurrent acceptance stays live even if another branch has a higher numeric
`generation`. Generations remain useful for legacy records and diagnostics,
but do not establish causality between independent branches.

Concurrent acceptances for different inputs are both retained. If multiple
live identities remain for the same input, their complete records are retained
in `conflicts`; none is imported or restored automatically. `cbi check` reports
the answer file, task kind and key, and the concept task stays open. Its brief
identifies the conflicting acceptance IDs in `answers.jsonl`. An explicit
reviewed submission retires every observed conflicting identity and resolves
the conflict without relying on line order.

Unversioned legacy rows keep their previous generation ordering until they
interact with causal records; stable identities derived from their answer
content allow a new acceptance to supersede those observed records. Import and
export preserve causal context in both model metadata and the team file. The
model retains answer digests so cache writes cannot impersonate an acceptance,
and unversioned cache exports cannot overwrite causal team history.
Export checks every retained answer digest, including causal acceptances with
an absent or zero `generation`; generation is not required to protect an
acceptance identity from a different cache body.


Secret checks inspect every raw conflict answer body, including alternatives
that are already causally resolved. Acceptance IDs and retirement metadata are
not answer text and are excluded from token heuristics.


When restoring a missing concept document, an unambiguous committed live answer
is authoritative over the shared cache. A later cache write at the same input
hash cannot replace an explicitly reviewed acceptance with an older body.

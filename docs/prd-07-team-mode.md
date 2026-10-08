# PRD-07: Team mode

Builds on PRD-01 to PRD-04. Supersedes ADR-0006 (in-repo self-ignoring `.cbi/`) for repositories that opt in.

## Problem

A team wants the map committed with the code and kept current as pull requests merge. Today `.cbi/` is entirely git-ignored, so every clone starts with an empty map and every developer's agent redoes the same judgement work (summaries, structure, concepts, screens). The expensive part is lost on every clone, and nobody reviews the concepts.

## Users

- **A team** working in one repository, each developer with their own agent.
- **Reviewers** of a pull request, who should see how a change altered the map.
- **CI**, which should keep the map honest without calling a model.

## Outcome

In a repository that opts in, the judgement half of the map is committed as small text files and changes in the same pull request as the code it describes. A fresh clone rebuilds the full map with no agent work. A CI check fails a pull request whose changed files have no summary or owner.

Success signals:

- A teammate clones the repo, opens it in the app, and sees the full concept map within a minute, with zero judgement tasks.
- A pull request that adds a module shows the map change (new file summaries, a concept gaining files) in its diff, and the reviewer can read it.
- A pull request that adds code without updating the map fails CI with a message saying which files need what, and `cbi prime` fixes it in one agent pass.

## What is committed

| Path in `.cbi/` | Committed | Why |
|---|---|---|
| `structure.json`, `concepts.json`, `screens.json` | yes | judgement, small text |
| `answers.jsonl` | yes | every accepted summary, keyed by content (git blob id) and task kind; sorted, one line each |
| `CHANGELOG-ARCHITECTURE.md` (PRD-06) | yes | readable history for people and agents |
| `team.toml` | yes | opt-in marker and settings (check strictness, budget) |
| `model.db`, `viewer/`, `refs/`, `reviews/`, `history/` | no | derived; rebuilt by `cbi scan` and `cbi build` in seconds |

## User journeys

1. **Opt in.** `cbi team init` writes `.cbi/team.toml`, rewrites `.cbi/.gitignore` to ignore only derived files, exports existing answers to `answers.jsonl`, and adds a `.gitattributes` line marking `.cbi/answers.jsonl` as generated so GitHub collapses it. It prints the files to commit and the CI snippet; it does not commit or push.
2. **Clone and open.** On a fresh clone, `cbi scan` imports `answers.jsonl` and the JSON files before opening tasks, so every unchanged file already has its summary and owner; `cbi build` gives the full map.
3. **Work in a pull request.** The developer's agent runs `cbi prime` as usual. Only files the branch changed open tasks (plus define-concepts for new files). Accepting answers updates `answers.jsonl` and the JSON files, which the agent commits with the code.
4. **CI.** `cbi check` (no model, no network) scans, then fails when a changed code or test file lacks a summary or a concept owner, when the JSON files fail the task checks, or when `answers.jsonl` is out of date with the accepted answers. It prints the files and the command to fix them. `team.toml` can set it to warn instead.
5. **Merge.** Nothing extra runs on merge. Answers merge cleanly because each line is keyed by content; a conflict in `concepts.json` is a real disagreement and is resolved like any code conflict, then `cbi check` confirms it.
6. **Review.** In the PR diff, `answers.jsonl` is collapsed; `concepts.json` and `screens.json` changes are visible. `cbi review` (PRD-04) on the PR already describes the architectural change.

## Requirements

- T1. `cbi team init` as above; idempotent; never commits or pushes.
- T2. `answers.jsonl`: one JSON object per line `{kind, key, protocol, answer}` where key is the content hash (blob id) for file summaries and the input hash for group, deployable, workspace and change tasks; sorted by kind then key; written after every accepted answer in a team repo; deduplicated.
- T3. Scan imports committed answers into the shared cache and the model before opening tasks; committed JSON files are applied as today.
- T4. `cbi check [--base REF]`: scans, compares against the base (default the merge base with the default branch) to find changed files, and exits 1 with a precise list when changed files lack summaries or owners, when the JSON files fail their task checks, or when exported answers are stale; exit 0 otherwise. `--format github` prints GitHub annotations. No model, no network, no writes outside `.cbi/` derived files.
- T5. A CI snippet for GitHub Actions in `cbi team init` output and the README: install cbi with uv, run `cbi check`.
- T6. Repositories that do not opt in behave exactly as now (ADR-0006 still applies to them).
- T7. Answer text is data: committing it must never commit secrets. Answers are summaries written by agents; `cbi check` refuses answers containing values that look like keys or tokens (simple high-entropy and known-prefix patterns) and names them.

## Acceptance criteria

- U1. On a copy of sample-desktop with its current map, `cbi team init`, commit, then a fresh clone: `cbi scan` reports zero open tasks and `cbi build` gives the same concept map.
- U2. On a branch adding one file: `cbi check` fails naming that file; after the agent answers the tasks, `cbi check` passes and the diff shows one new `answers.jsonl` line and the concept change.
- U3. Two branches each adding a different file merge without a conflict in `answers.jsonl`.
- U4. A non-team repo's `.cbi/` stays fully ignored and unchanged in behaviour.
- U5. `cbi check` finishes on sample-saas in under a minute without network access.

## Non-goals

- Running agents in CI or calling models from CI.
- Committing the derived model or viewer.
- Hosting the map outside the repository.

## Assumptions and risks

- Summaries drift from code when a file changes but its content hash is new: the check catches it in the PR that changed it.
- `concepts.json` conflicts on busy repos: expected to be rare (concept boundaries change less often than files); resolved like code.
- Teams without the CLI in CI get no gate; the map still works, it just may lag.

## Open questions

- Whether `cbi check` should also fail on a changed file whose concept owner no longer fits (it cannot judge that). Default: no; reviewers judge it from the diff.

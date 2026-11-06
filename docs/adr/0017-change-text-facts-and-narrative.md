# ADR-0017: Change text is facts plus an optional narrative

Status: Accepted. Date: 2026-10-07.

## Context

A pull request lists changed lines. It does not say which parts of the system gained or lost a responsibility, which integrations appeared, or which new code has no test. Some of that is a fact about two models with stable ids (ADR-0001). Some of it is a judgement about what the change means. Agents open most of these pull requests and can write that judgement when they are present. They are not always present.

## Decision

The structural diff is always computed, with no model in the loop. `cbi diff` compares two models by stable id and prints text, Markdown or JSON. The change list covers concepts added, removed, renamed, split or merged, files moving between concepts, relationships, integration points, deployables and packages, env vars, symbols, tests, untested changes, and what UI components render. A file or symbol whose content hash is unchanged, and whose path or qualified name moved, is a move.

`cbi review` writes that diff into `review.md`. A `summarise-change` task takes the change list and may add a short narrative. The narrative is included when an agent has submitted it. It is never required. The answer is cached for that pair of commits.

## Alternatives considered

The log does not record a second option. It records the split: deterministic structural facts every time, and an agent narrative only through a task, cached per diff. PRD-04 C6 makes the narrative optional.

## Consequences

`review.md` is useful before any agent runs. Files the base concepts do not own get a provisional owner, marked as provisional, and a `define-concepts` task opens for those files only. The facts and the narrative stay distinct sections, so a reader can see which sentences were measured. Comparing versions does not check out a branch or edit a working tree.

## Amendment: grounded comparison paragraphs (2026-11-03)

Comparison summaries now use the sibling `summarise-architecture-change` judgement task: one for the whole diff and one for each changed concept. This includes concepts whose changes appear only in the ranked file overview. cbi still never calls a model. The calling agent explains the change, its importance, affected callers/users and risk using only the diff facts and direct relationship context supplied in the brief. Unknown intent or runtime impact must stay unknown.

Answers require symbol/file citations copied from the brief. Pure structural changes include ownership context; empty concepts without source are explicitly marked structural-only and permit structural references. Draft checks and submission reject references outside that evidence. This is a grounding boundary for references; it cannot mechanically prove prose claims. Tasks cover every before/after participant of a split or merge, including when source files remain unchanged. Ancestor briefs carry the relevant descendant structural records. Both models' parent chains are retained, so a renamed and reparented concept reaches its former and current ancestors. The shared answer cache uses both models' semantic hashes and the concept ID, so unchanged rebuilds reuse the answer and changes to either side open fresh work.

Diff and review output and the comparison viewer consume the same `summaries` payload. An unanswered task shows `Summary pending: run cbi tasks`. The existing history `summarise-change` task remains supported.

Summary protocol version 2 invalidates incomplete structural briefs. History cache version 4 migrates earlier entries once. Persisted summary hashes and allowed citations let history output and standalone history viewer builds refresh accepted answers from the shared cache without rebuilding old point models or relying on surviving task rows.

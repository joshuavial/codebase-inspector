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

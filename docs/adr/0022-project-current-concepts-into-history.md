# ADR-0022: Project today's concepts into the past

Status: Accepted. Date: 2026-10-08.

## Context

Concept answers exist only for the present. Past commits have files and symbols but no concepts, and asking an agent to define concepts at every point would be slow and costly.

## Decision

Today's `concepts.json` is projected onto each history point by file ownership: a file keeps its current owner if it still exists; a file that existed only in the past takes the owner of its nearest surviving neighbour (same folder, then import neighbours) and is marked provisional. Concepts with no files at a point are absent there. Narratives per entry are optional, through `summarise-change`, on request only.

## Alternatives considered

- An agent re-runs define-concepts at milestones (tags or monthly): more faithful to how boundaries looked then, but costly, and comparisons across milestones with different concept sets get hard.

## Consequences

History is deterministic, free and comparable across points. It describes the past in today's vocabulary; provisional marks show where that is approximate.

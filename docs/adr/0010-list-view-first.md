# ADR-0010: List view before a diagram

Status: Superseded by ADR-0011. Date: 2026-10-07.

## Context

PRD-01 needed a first picture of the tree from ADR-0002. A diagram drawn before anyone had used the data would guess which picture mattered. A treemap and a node-link graph were both available. The architecture review cut views that PRD-01 did not need.

## Decision

The viewer drills from the workspace to methods as a list of children and a detail pane. Each row shows the concrete kind, size and a test chip. The detail pane shows the summary, signature, docstring, relationships rolled up to the current level, and linked tests. Search jumps to a result with its ancestors expanded. A deployable lists the files that are part of it.

A treemap and a node-link graph wait until this list has been used.

## Alternatives considered

- A treemap in PRD-01.
- A graph view (Cytoscape) in PRD-01.
- The review kept the list and deferred both pictures. Two seats deferred the treemap. Compose resources and a config file were cut in the same review. They are separate from this view.

## Consequences

PRD-01 R19 describes this list. The first viewer that was built followed it. ADR-0011 replaces the presentation. Opening the folder from disk (ADR-0007) is unchanged.

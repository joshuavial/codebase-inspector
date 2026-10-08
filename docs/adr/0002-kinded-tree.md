# ADR-0002: Kinded tree with concrete labels

Status: Accepted. Date: 2026-10-07.

## Context

The target repositories do not share a shape. One builds several deployables from a single manifest. Another is mostly markdown, with code in a submodule. A fixed ladder would invent empty levels or fail to fit. Tests need nodes of their own so later coverage and results can attach to a case. The same records are shown to people and returned as JSON, so a schema word must not be the label a person reads.

## Decision

The model is one containment tree. A kind may be absent. Groups may nest. The kinds are workspace, deployable, package, group, file, symbol and test. A submodule is a nested workspace (ADR-0001). A test file contains test cases. A file may be part of several deployables. External systems sit outside the tree.

`symbol` and `group` are internal names. The viewer and CLI text show the concrete label: class, function, method, component, interface, module, folder, and the other display kinds. `--json` includes the internal kind and the label. A chain of single-child folders is one breadcrumb step.

## Alternatives considered

- A fixed ladder of levels.
- Tests as an overlay only, with no test nodes.
- Showing the schema names `symbol` and `group` in the UI.
- A `resource` kind for compose databases, queues and caches. The architecture review cut compose resources from PRD-01. Externals remain.

## Consequences

Containment is the parent column, not an edge. Deployable membership is a `part_of` edge, so one file can sit in several deployables. PRD-01 R22 hides internal names in the UI. Doc nodes are added in ADR-0003. PRD-02 adds a second hierarchy for concepts (ADR-0011) and leaves this tree for the CLI and the drawer.

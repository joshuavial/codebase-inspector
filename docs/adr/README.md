# Architecture decision register

One file per significant decision, numbered in the order they were made. When a decision replaces an earlier one, the new file records the replacement and the earlier one is marked Superseded. Add a new ADR for any decision that changes the architecture or a product principle, and link it from `docs/architecture.md`.

| Number | Title | Status |
| --- | --- | --- |
| [0001](0001-orientation-map-first.md) | Orientation map comes first | Accepted |
| [0002](0002-kinded-tree.md) | Kinded tree with concrete labels | Accepted |
| [0003](0003-tiered-docs-skills-and-data.md) | Tiered handling of docs, skills and data | Accepted |
| [0004](0004-name-resolved-calls.md) | Name-resolved calls, SCIP later | Accepted |
| [0005](0005-static-test-linking.md) | Static test links plus ingest | Accepted |
| [0006](0006-in-repo-cbi-directory.md) | In-repo self-ignoring .cbi directory | Accepted; superseded by ADR-0023 for team repos |
| [0007](0007-static-viewer-from-file.md) | Static viewer opened from file:// | Accepted |
| [0008](0008-python-mapper-tree-sitter-sqlite.md) | Python mapper with tree-sitter and SQLite | Accepted |
| [0009](0009-deterministic-cli-and-tasks.md) | Deterministic CLI and agent tasks | Accepted |
| [0010](0010-list-view-first.md) | List view before a diagram | Superseded by ADR-0011 |
| [0011](0011-agent-defined-concepts.md) | Agent-defined concepts replace the list | Accepted |
| [0012](0012-agent-drawn-wireframes.md) | Agent-drawn wireframes | Accepted |
| [0013](0013-environment-variable-nodes.md) | Environment variables as nodes | Accepted |
| [0014](0014-two-way-navigation.md) | Two-way navigation | Accepted |
| [0015](0015-append-only-prds.md) | PRDs are an append-only sequence | Accepted |
| [0016](0016-user-runs-own-agent.md) | The user runs their own agent | Accepted |
| [0017](0017-change-text-facts-and-narrative.md) | Change text is facts plus an optional narrative | Accepted |
| [0018](0018-mermaid-and-image-files.md) | Mermaid plus image files for pull requests | Accepted |
| [0019](0019-electron-shell.md) | Electron shell over the CLI | Accepted |
| [0020](0020-headless-system-chrome.md) | Headless system Chrome for review images | Accepted |
| [0021](0021-history-points-are-merges.md) | History points are merges to main | Accepted |
| [0022](0022-project-current-concepts-into-history.md) | Project today's concepts into the past | Accepted |
| [0023](0023-team-mode-commits-judgement.md) | Team mode commits the judgement, not the model | Accepted |

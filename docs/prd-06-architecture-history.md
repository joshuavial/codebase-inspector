# PRD-06: Architecture history

Builds on PRD-02 (concept map), PRD-03 (desktop app, ref scanning) and PRD-04 (diff engine, `summarise-change`, comparison view). PRD-05 (data map) is still to be written; this increment comes first.

## Problem

The comparison view answers "what did this change do". It does not answer "how did this system get to where it is": when a concept appeared, when a dependency or integration crept in, when a part grew or split. The developer wants a changelog of the architecture over time, readable in the app and by agents from the CLI.

## Users

- **The developer**, looking back over weeks of merges to the default branch to see how the system's shape changed and when.
- **AI agents** working in a repo, who need a short, factual history of architectural change before they propose the next one.

## Outcome

For any repository, the inspector produces an architecture changelog: one entry per merge to main that changed the architecture, saying what changed in concept terms. In the app, a timeline replays the concept map through that history. From the CLI, the same changelog prints as text or Markdown and can be kept in a file for agents.

Success signals:

- On codebase-inspector's own history, the changelog shows the arrival of the CLI, the viewer, the desktop app, comparison and review as separate entries, in order, without reading commit messages.
- Scrubbing the timeline on sample-desktop shows the moment `core` was extracted from `electron/`.
- An agent reading `.cbi/CHANGELOG-ARCHITECTURE.md` can say which parts changed in the last week and which PRs did it.

## User journeys

1. **Read the changelog.** `cbi history` lists entries newest first: date, merge commit and PR number if known, author, and the structural changes grouped by concept (concepts added, removed, renamed, split, merged; relationships and integrations added or removed; deployables and packages; env vars; size and test-coverage shifts). `--since`, `--until`, `--concept` and `--limit` narrow it. `--format markdown|json`.
2. **Keep it for agents.** `cbi history --write` writes `.cbi/CHANGELOG-ARCHITECTURE.md` and updates it incrementally; `cbi prime` mentions it when it exists.
3. **Replay in the app.** A timeline strip under the concept map shows one tick per entry, sized by how much changed. Dragging or stepping through it redraws the map as it was at that point, with what changed at that step marked (PRD-04 marks). Clicking an entry opens the comparison for that merge; the Back chip returns to the timeline position.
4. **Ask for narrative.** For any entry, the user or an agent can open a `summarise-change` task for that pair; once answered, the narrative shows in the changelog and the app. Narratives are never required and never generated automatically.

## Requirements

- H1. History points are first-parent commits before the first merge, then merges to the default branch (merge commits, or the commits a squash-merged PR produced). A repository that never merges uses every first-parent commit. PR numbers come from merge commit messages and, when `gh` is available, from `gh pr list --state merged --json` (read-only).
- H2. Each entry is the PRD-04 structural diff between a point and the previous point. Points whose diff has no architectural change are skipped.
- H3. Concepts in the past come from projecting the current `concepts.json` onto each point by file ownership: files that no longer exist drop out; files that existed only in the past take the owner of their nearest surviving neighbour (same folder, then import neighbours) and are marked provisional. Concepts with no files at a point are absent at that point.
- H4. History builds incrementally: models for points already scanned are reused (ref models are immutable), and only new points are scanned and diffed. Scanning reuses content-addressed parse results across points, so a long history costs roughly the number of distinct file versions, not points times files.
- H5. `cbi history` (text, Markdown, JSON) with `--since`, `--until`, `--concept`, `--limit`, and `--write` maintaining `.cbi/CHANGELOG-ARCHITECTURE.md`.
- H6. App timeline: ticks per entry, scrub to replay, entry click opens the comparison, two-way navigation (PRD-02 V0) throughout, and copy for agent (V12) on an entry gives its changelog text and the commands to reproduce it.
- H7. Never changes a working tree, ref or stash; everything reads git objects.

## Acceptance criteria

- I1. `cbi history` on codebase-inspector lists the major milestones (CLI scan, concept viewer, desktop app, comparison, review images, C# and Vue) as entries in order, each with the concepts it touched.
- I2. On sample-desktop, the entry where `core` appeared shows files moving from Desktop app into the core concept, not a removal and an addition.
- I3. A second `cbi history` run after one new merge scans only that point and finishes in a few seconds.
- I4. In the app, scrubbing the timeline on sample-desktop redraws the map per entry with marks, and clicking an entry opens its comparison with a Back chip to the timeline.
- I5. `.cbi/CHANGELOG-ARCHITECTURE.md` exists after `--write` and matches the Markdown output.

## Non-goals

- Agent-defined concepts at past milestones (decided: project today's concepts back).
- Automatic narratives for every entry.
- Histories of branches other than the default branch.

## Assumptions and risks

- Projection is honest about the present and approximate about the past: a concept that existed under different boundaries long ago will look like today's boundaries. Provisional marks make that visible.
- Very long histories (thousands of merges) may need a cap on the first build (`--since` default of six months) to keep the first run reasonable.

## Open questions

- The default `--since` window for the first build. Default: six months, or the whole history if it is shorter.

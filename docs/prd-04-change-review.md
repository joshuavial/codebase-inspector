# PRD-04: Change review

Builds on PRD-01 (stable IDs, CLI), PRD-02 (concept map) and PRD-03 (desktop app, mapping branches from git objects).

## Problem

A pull request shows changed lines. It does not show what changed in the architecture: which parts of the system gained or lost responsibilities, which new connections or integrations appeared, which tests now cover the new code and which do not. Reviewers, and the agents that open pull requests, rebuild that picture by reading the diff file by file. The developer should see architectural change directly, in the app and in the pull request itself.

## Users

- **The developer reviewing a change**: a feature branch before merging, a pull request, or two worktrees side by side.
- **AI agents** opening or reviewing pull requests, who need a text description of the architectural change they can paste into a PR, and who can write the narrative summary as a judgement task.
- **Other reviewers on a pull request**, who see the description and diagram in the PR thread without installing anything.

## Outcome

Given any two versions of a repository (branches, commits, worktrees or a pull request's base and head), the inspector shows what changed in architectural terms: on the concept map in the app, as text from the CLI, and as a diagram that renders in a pull request thread.

Success signals:

- For a feature branch, the developer sees at a glance which concepts changed and how, before reading any code.
- An agent opening a PR runs one command and pastes a description that a reviewer finds more useful than the file list.
- The PR thread shows a diagram of the changed concepts with no image hosting.

## What counts as an architectural change

Computed deterministically from the two models by stable node IDs:

- concepts added, removed, renamed, split or merged (from ownership changes), and files moving between concepts;
- relationships between concepts added or removed, and changes in the call and import volume behind them;
- integration points added, removed or changed (new external system, different mechanism);
- deployables, packages and dependencies added or removed;
- env vars newly read or no longer read;
- functions and classes added, removed or changed (signature or body), rolled up to their concepts;
- tests added or removed, and changed code with no linked test;
- for UI concepts, components added or removed and changes to what they render.

Each item says which concept it belongs to and links to the code behind it.

## User journeys

1. **Compare in the app.** In a project, choose two sides (worktree, branch, commit, or a pull request by number) and open the comparison. The concept map shows the head with changes marked: added, removed and changed concepts, new and removed arrows, new integration points. A summary panel lists the changes by concept. Drilling into a changed concept shows changed functions; a changed function shows its code diff. A toggle shows the base map with what was removed.
2. **Describe a change from the CLI.** `cbi diff <base> <head>` prints the structural changes as text, Markdown or JSON. `cbi review <pr | branch>` resolves a pull request through `gh` (or a branch against its base) and writes a review folder: `review.md` with the summary and a Mermaid diagram of the changed concepts, and before/after images of the concept map as PNG and SVG.
3. **Add the narrative.** If an agent is available, `cbi review` opens a `summarise-change` judgement task with the structural diff as input. The agent's answer (a few sentences on what the change does to the architecture and what to look at) is added to `review.md` and cached for that pair of versions.
4. **Post to the PR.** `cbi review <pr> --post` posts `review.md` as a PR comment through `gh`, and updates its own earlier comment on later runs instead of adding new ones. Images stay files for the user or an agent to attach; the Mermaid diagram renders in GitHub without them.
5. **Open the comparison in the app.** `cbi open --compare main..pr/2345` (or `--pr 2345`, which uses the PR's base) opens the desktop app on that comparison, and `cbi review` prints the same `cbi://` link at the top of `review.md` for anyone with the app installed.
6. **Concepts for new code.** When the head adds files the base's concepts do not own, the comparison assigns them provisionally by folder and import neighbours, marks them as provisional, and opens a `define-concepts` task for just those files.

## Requirements

### Comparison

- C1. Compare any two of: a worktree's working tree, a branch, a commit, a pull request's base and head. Versions not checked out are mapped from git objects without touching any working tree (PRD-03 A5).
- C2. Compute the change list above from the two models by stable IDs, with renames detected for files and symbols moved without content change.
- C3. Reuse the answer cache so unchanged files keep their summaries and concepts on both sides.

### CLI

- C4. `cbi diff <base> <head> [--format text|markdown|json] [--concept ID]` prints the structural diff, grouped by concept, most significant first.
- C5. `cbi review <target>` writes a review folder with `review.md` (summary, Mermaid diagram of changed concepts and their changed relationships, per-concept details, untested changes) and `before.png`, `after.png`, `before.svg`, `after.svg` of the concept map with changes highlighted.
- C6. `summarise-change` judgement task with the structural diff as input; its answer is included when present and never required.
- C7. `--post` publishes `review.md` to the PR with `gh` only when that flag is given, and edits the inspector's previous comment on that PR rather than adding another.

- C7a. `cbi open --compare <base>..<head>` and `cbi open --pr <number>` open the desktop app (PRD-03 A12a) on the comparison, optionally with `--node`; `review.md` includes the matching `cbi://` link.

### Viewer (app and static)

- C8. A comparison mode on the concept map: added, removed and changed marks with a key, a changes panel grouped by concept, base/head toggle, and two-way navigation throughout.
- C9. A changed function shows its code diff in the drawer; a changed UI component shows its wireframe before and after where screens exist.
- C10. The static viewer from `cbi build --compare <base> <head>` has the same comparison mode, so it can be shared without the app.

## Acceptance criteria

- D1. On codebase-inspector, comparing a merged feature branch with its base lists the concepts it changed and the new relationships, matching what the branch actually did.
- D2. On sample-desktop, comparing two commits where a module moved from `electron/` to `core/` reports a move between concepts, not a removal and an addition.
- D3. `cbi review` on a real pull request writes `review.md` whose Mermaid diagram renders on GitHub, and the PNG and SVG show the changed concepts highlighted.
- D4. `cbi review --post` run twice on the same PR leaves one inspector comment, updated.
- D4a. `cbi open --pr <number>` brings the app to the front showing that pull request's changes against its base.
- D5. No command in this increment changes a working tree, ref or stash in the repository.

## Non-goals

- Hosting images or committing them to the branch (decided: Mermaid plus files).
- Reviewing code style or correctness; this is about architecture.
- Automatic posting without `--post`.
- Comparing more than two versions at once.

## Assumptions and risks

- Concept-level changes are only as good as the concepts on each side; provisional assignment keeps a comparison usable before an agent has looked at the new files.
- Rendering PNG and SVG from the CLI needs a layout engine and a renderer outside the browser, or a headless browser; the architecture decides which.
- Very large diffs could produce unreadable diagrams; the Mermaid diagram shows only changed concepts and their direct neighbours, with the rest summarised as text.

## Open questions

- Whether `review.md` should include a short "risk" section (changed integration points, untested changes) by default. Default: yes, as part of the facts.

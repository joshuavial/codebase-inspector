# ADR-0011: Agent-defined concepts replace the list

Status: Accepted. Date: 2026-10-07.

## Context

The list viewer showed how files are stored. The developer rejected it: too much text, and folders, files and docs are the storage, not the system. In sample-desktop, `electron/` repeats `core/`, and `service/` mixes several jobs. Who defines the conceptual levels was the open question. A hand-drawn diagram goes stale. A fixed taxonomy will not fit every repository. PRD-01 had listed cross-folder regrouping as a non-goal.

## Decision

This supersedes ADR-0010.

A `define-concepts` task asks the agent to name the parts of the system. Concepts nest. Each has a summary and a role from a fixed list. Only a leaf owns files, and every code file and test file belongs to exactly one leaf. A leaf may own files from several folders. Relationships are labelled arrows backed by imports and calls. A relationship that crosses to an external system is an integration point: it has a mechanism and the function where it happens.

The CLI checks the answer. Every code and test file is owned by exactly one leaf. Ids are unique. Roles and external kinds come from the lists. Every relationship end exists. Every leaf-to-leaf import or call pair in production code is covered by a relationship between those leaves or their ancestors; edges from test files are test links, not architecture, and are not counted. A rejected submit lists every failing check.

The main view is a box-and-arrow diagram of the current level, inside a system boundary, with externals outside it. Clicking a concept drills in. Esc and the parent breadcrumb go up one level. The leaf shows classes and functions, calls between them, renders, and a test badge. Symbols owned by other concepts appear as lighter nodes labelled with their concept. Folders, files and docs stay in the model and the CLI. In the viewer they appear only in the drawer's detail.

The answer is stored as `.cbi/concepts.json` and applied on every scan. The viewer writes nothing back.

With no concepts yet, the viewer shows deployables, packages and externals as boxes, so a fresh scan still opens on a diagram.

## Alternatives considered

- Keep the folder list as the main view (ADR-0010).
- A treemap or a file graph, the pictures ADR-0010 deferred.
- Concepts maintained only by hand.
- Levels defined by the tool from folder names.
- Agent-defined concepts, with the CLI checking coverage. This was chosen. It reverses the PRD-01 non-goal that banned regrouping files across folders.

## Consequences

PRD-02 records the change and names the PRD-01 requirements it replaces (ADR-0015). The CLI checks consistency, not whether the concepts are good ones. One answer for sample-monorepo may be too large for an agent's context. Splitting the task per deployable stays open until that repository is mapped this way. Layout runs in the page with vendored elkjs. Incoming links sit on the left and outgoing links on the right. Scroll pans both axes. Pinch or Cmd/Ctrl+scroll zooms around the cursor.

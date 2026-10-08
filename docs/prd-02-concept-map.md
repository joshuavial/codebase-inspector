# PRD-02: Concept map

Amends PRD-01 (`docs/prd-01-orientation-map.md`), which is partly built. Everything in PRD-01 still holds except where this document says it replaces something.

## Problem

The first viewer, a list of folders and files with a detail pane, was rejected: too much text, and the picture should be conceptual rather than a folder tree. A folder tree shows how code is stored, not what the system does. In sample-desktop the folders are not the parts: `electron/` repeats `core/`, and `service/` mixes several jobs.

A clickable mockup on sample-desktop settled the direction, with four changes (colours with a key, zoom, Esc to go up, integration points shown clearly). Leaf views should include the components a component renders, and UI components should be shown as wireframes with minimal styling and their real text.

## Users

Unchanged from PRD-01. Agents now also define the concepts, as judgement work.

## Outcome

The viewer shows a repository as a map of concepts: the parts of the system as boxes with labelled arrows between them, and the outside systems it integrates with. A person clicks into a concept to see its sub-concepts, and at the bottom sees the classes and functions that implement it and which of them have tests. Folders, files and docs leave the main view.

Success signals:

- A person can explain what sample-desktop's parts are and how they connect from the top-level map alone, without opening a file.
- From the top level they reach the functions behind any concept, and their tests, in three or four clicks.
- Every place sample-desktop talks to an outside system is visible as an integration point with its mechanism (HTTP, an executed CLI, IPC, a platform API, or a file read).

## Model the user sees

- **Concept.** A named part of the system with a one-sentence summary and a role. Concepts nest, with up to about seven per level. Only leaf concepts own code. Each code file (source or test) belongs to exactly one leaf concept, and a concept may own files from several folders.
- **Role.** What kind of part a concept is (UI, app process, service, core library, data model, and so on), shown as its colour. Roles are data chosen by the agent from a fixed list.
- **External system.** Something outside the repository that the code talks to, with a kind (platform service, CLI tool, SaaS or API, OS or terminal), also shown as a colour.
- **Relationship.** A labelled arrow between concepts ("polls", "serves snapshot to"). It is backed by import and call edges in the code, which roll up from the code to the concepts that own it.
- **Integration point.** A relationship that crosses the system boundary to an external system. It carries a mechanism (HTTP, exec CLI, IPC, a platform API, file read) and the function where it happens.

Deployables, packages, folders, files and docs stay in the model and in the CLI. In the viewer they appear only in the side drawer of a selected concept.

## User journeys

1. **Define concepts.** After a scan, the agent gets a `define-concepts` task with the file list, the deployables and packages, existing summaries and the import pairs between files. It answers with a concept tree, file ownership, relationships with labels, externals and integration points. The CLI checks the answer: every code file owned by exactly one leaf, every cross-concept import pair covered by a relationship, roles and kinds from the allowed lists. It rejects the answer with the exact gaps if any check fails.
2. **Browse the map.** The developer opens the viewer and sees the top-level concepts inside a system boundary, the externals outside it and a colour key. They zoom and pan freely. Clicking a concept zooms into its sub-concepts; Esc or the breadcrumb goes back up one level. Connections to things outside the current concept show as stubs at the edge of the view.
3. **Reach the code.** At a leaf concept the map shows its classes and functions, the calls between them and a test badge on each one that has tests. The drawer lists the concept's files, tests and integration points.
4. **Keep it current.** After code changes a rescan reopens `define-concepts` only for the files whose ownership is missing or stale. New files must be assigned before the map counts as complete.

## Requirements

These replace PRD-01 R19 to R21 (the list viewer and its overlay). R18 (static viewer from disk), R20's cross-kind search and R22 (no internal kind names) still apply.

### Concepts

- C1. A `define-concepts` judgement task, issued once structure is confirmed, with the inputs listed in journey 1. The answer shape is one nested tree. The CLI validates file ownership and relationship coverage and reports each gap precisely.
- C2. Concepts, roles, externals, relationships, mechanisms and integration points are stored in the model and appear in `cbi show` and `cbi search`.
- C3. After a rescan, the file list in a task covers only new or changed files, with the current concept tree as context, so the agent edits the tree instead of redoing it.
- C4. Concept relationships record the code edges behind them, so the viewer can show the calls behind an arrow.
- C5. JSX element usage and `createElement` calls are recorded as call edges marked as renders, so a component's view shows the components it renders.
- C6. A `sketch-screens` judgement task asks the agent to sketch each UI screen as a declarative region tree (label, component, layout hint, static text, style hints). The CLI checks that every region names a real component and stores the sketch with the model; it is rendered from data, never as raw HTML.
- C7. Environment variables read by the code (`process.env.X`, `import.meta.env.X`, `os.environ`, `os.getenv`) become env var nodes linked to the functions that read them, with any default value and where they are declared (`.env.example`, compose `environment`, config files). Values from real `.env` files are never read or stored.
- C9. HTTP endpoints: client call sites (fetch, axios, request(method, path) wrappers) and server routes (FastAPI with router prefixes, Express, ASP.NET) are matched by method and normalised path, giving `http_calls` edges from the calling function to the route handler, labelled with method and path. A client concept's relationships to an API concept list the endpoints it calls.
- C8. At a leaf concept, symbols in other concepts that its code calls or renders, or that call into it, appear as lighter nodes labelled with their owning concept.

### Viewer

- V0. Two-way navigation is a core principle. Every way into a view (drilling down, a sideways jump to another concept, a search result, a link in the drawer, a grey node) leaves a visible way back: the breadcrumb for up, a "Back to <origin>" chip for anything else, with Backspace and browser back doing the same and restoring the previous zoom and selection. Clicking a grey node first selects it and shows the link in both directions; navigation is a second, explicit step through the drawer's Go to action.
- V1. The main view is a box-and-arrow diagram of the concepts at the current level, laid out automatically, inside a labelled system boundary, with externals outside it.
- V2. Colours encode role (concepts) and kind (externals), with a key showing only the roles and kinds present at the current level. Readable in light and dark mode.
- V3. Two-finger scroll and the mouse wheel pan in both directions; pinch or Cmd/Ctrl+scroll zooms around the cursor; drag pans; zoom in, zoom out and fit controls. Text stays crisp at every zoom level.
- V4. Clicking a concept drills into it with a zoom transition. Esc goes up one level, the same as clicking the parent in the breadcrumb. Browser back and forward follow the same history.
- V5. Arrows that cross the system boundary are integration points. They have their own style and a mechanism label. Inside a concept, its connections to siblings and externals show as stubs at the edge of the view: incoming (callers, renderers, importers) on the left, outgoing on the right, and the relationships drawn into it one level up keep their labels. The drawer for a concept opens with "Used by" and "Uses" lists, each entry a link, and hovering an entry highlights its group in the diagram; the top bar holds only the breadcrumb and the Back chip.
- V6. At a leaf concept the diagram shows its classes and functions, the calls between them, and a test badge with the count of linked tests.
- V7. A side drawer for the selected concept shows its summary, relationships, integration points (with the function where each happens), files and tests. Paths appear only here. Wherever the drawer lists functions (calls, called by, renders, rendered by), each entry shows its owning concept and module, grouped by concept, and `cbi show` does the same in text output.
- V8. Search jumps to any concept, external or code symbol, drilling the map to it.
- V9. UI concepts and React components open on a screen wireframe: a low-fidelity sketch of the screen they appear on, carrying the real static text from the JSX and minimal layout and style hints, in greyscale with the selected component's region highlighted. Beside it: the component's props, what it renders and what data it reads. The code diagram from V6 is one toggle away.
- V10. Environment variables show clearly: each concept box carries a small marker with the count of env vars its code reads, the drawer lists them (name, default, where declared, which functions read them), and the key includes the marker. Search finds env vars by name.
- V12. Every view has a Copy for agent action. It copies a short Markdown block describing what is on screen: project path, model folder, version (worktree, branch or comparison), the selected node with its kind, summary and file, its key relationships, and the exact `cbi` commands that show the rest (`cbi show`, `cbi tests-for`, `cbi search`, `cbi diff`), so it can be pasted into an agent session. Cmd+C or Ctrl+C does the same whenever no text is selected and focus is not in an input; with a text selection it copies the text as usual. The CLI offers the same text with `cbi context <node>`.
- V13. Double-clicking anything that maps to one file (a file, class, function, method, component, test case, grey node) opens it in the user's editor at its line, opening the project folder and reusing an editor window already showing that project. The editor is a setting with presets (VS Code first: `code --reuse-window <project> --goto <file>:<line>`) and a custom command template with `{project}`, `{file}` and `{line}`. The static viewer, which cannot run commands, uses the editor's URL scheme (`vscode://file/<path>:<line>`). Concepts and other multi-file items are unaffected.
- V11. The test overlay from PRD-01 (static links, coverage, last result) applies to the concept map as a mode that recolours boxes by test status, with the key updated to match.

## Acceptance criteria

- B1. On sample-desktop, an agent completes `define-concepts` from `cbi prime` alone, and the CLI's checks pass: all 96 TS/TSX files are owned and no cross-concept import pair is left uncovered.
- B2. The sample-desktop viewer built by `cbi build` matches the agreed mockup: the top level shows five concepts and the externals inside and outside the boundary with a key, and zoom, Esc and drill-down to a leaf with test badges all work.
- B3. Every sample-desktop integration point named in the success signals shows with a mechanism, and the drawer names the function where each happens.
- B4. Selecting a screen shows its wireframe with the region highlighted and the components it renders.
- B5. On sample-monorepo, `define-concepts` is not required for the scan, build and query criteria in PRD-01 (A5 to A7). Without concepts, the viewer falls back to deployables and packages as boxes so the map still opens.

## Non-goals

- Hand-editing concepts in the viewer. The agent edits them through the task, or a person edits `.cbi/concepts.json`.
- Summaries for individual symbols, unchanged from PRD-01.
- A treemap view.
- Live, Storybook-style rendering of real components. Wireframes come first; live rendering is a later feature.

## Assumptions and risks

- **Concept quality depends on the agent.** The CLI checks coverage and consistency, not whether the concepts are good ones. The mockup suggests an agent with the scan data produces a sensible tree for a repo of sample-desktop's size.
- **Large repos.** sample-monorepo has about 1.6k code files. One `define-concepts` answer for the whole repo may exceed an agent's context, so the task may need splitting per deployable or package. That is left until sample-monorepo is mapped with concepts.

## Open questions

- Whether concept definitions should be split per deployable on large repos (see risks).

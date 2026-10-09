# Implementation plan

## Status (2026-10-07)

Merged to main: 1 scaffold, 2 enumeration, 3 tracer bullet, 4 TS resolution, 5 manifests, 6 query, 7A summary tasks and prime, 10A docs, 13 Python parsing and resolution, the deploy-manifest follow-up (Python, Docker, compose, wrangler, skills), and JSX render edges. Running: 9 test ingest. Replaced: deliverable 8 (list viewer) by the PRD-02 concept viewer after the first UI review.

# PRD-01 orientation map

Read `docs/prd-01-orientation-map.md` and `docs/architecture.md` first. Each deliverable is one reviewable change with its tests. Numbers give the order; "parallel with" marks work that can run alongside.

## 1. Scaffold

Outcome: `uv tool install .` puts `cbi` on PATH; `cbi --help` and `cbi prime` run; `pytest` passes.

Scope: `pyproject.toml`, `src/cbi/cli.py` with subcommand stubs, `prime.py` printing the not-initialised guide, a fixture helper that builds a git repo in a temp dir, one test, `.claude/skills/` with `.agent/skills` symlink, README with install and test commands.

Excludes: any scanning.

Checks: `uv run pytest`; `cbi prime` exits 0.

## 2. Init, enumeration and the store

Outcome: `cbi init` creates `.cbi/` (self-ignoring) with `ignore`; `cbi scan` stores workspace, group and file nodes, including nested submodule workspaces with normalised remote IDs, pinned and checked-out commits, drift and uninitialised state. Content hashing reads the working tree, and the no-change shortcut works.

Depends on: 1.

Checks: fixture with a submodule, a tracked symlink, a data dir and an unstaged edit; golden dump; remote normaliser unit tests (ssh and https forms of one repo give one ID); an unstaged edit, a deletion and an ignore-file change each trigger a rescan, and an untouched repo hits the shortcut; `git status --porcelain` on the fixture is empty after init and scan (A8). Timing probe: enumerate and classify sample-monorepo with `scripts/acceptance.sh <repo> <out-dir>`. Cold enumeration was 3.9 s and a no-change rescan 0.3 s on a warm file cache (about 13.4k tracked paths in the superproject, about 2.4k in the code submodule, about 700 in a docs submodule, one submodule uninitialised).

## 3. Tracer bullet on one sample-desktop pair

Outcome: one thin path end to end on the tracer fixture's service class and its test. TS parsing gives symbols for those files; `cbi show` and `cbi search` return them; a `summarise-files` task is issued, answered by hand with `cbi submit`, and shows up in `cbi show`; `cbi build` writes a bare viewer that opens from disk with breadcrumb, children list and detail pane. Editing the file and rescanning reopens its task.

Depends on: 2.

Excludes: resolution, manifests, other task kinds, overlays, chunking.

Checks: a test that runs scan, task, submit, show and build on a copy of those two files in a fixture; the stale-answer rejection (submit after the file changed) and the per-file cache are tested here, because they shape the protocol everything else uses.

## 4. TypeScript parsing, resolution and test linking

Outcome: all TS, TSX and JS gain symbols, import edges (relative, tsconfig `paths`, re-exports), resolved call edges with shadowing checks, node:test test files and cases linked to code by calls, imports, names and literal file reads, and diagnostics for ambiguous calls and unmatched tests.

Depends on: 3.

Checks: fixture covering classes, methods, arrow-function consts, React components, a path alias, a re-export through `index.ts`, a shadowed name, a test reading a CSS file, and a test with no subject; golden dump. On sample-desktop: 32 test files detected, every one linked or carrying an `unmatched_test` diagnostic.

## 5. Manifests and structure overrides (package.json family)

Outcome: deployables and packages from `package.json`, Vite configs and tsconfig projects; build-output entry points mapped to source through `outDir`/`rootDir`; Vite entries read from `index.html`; `part_of` by reachability; `structure.json` applied before detection on every scan.

Depends on: 4 (reachability needs import edges).

Checks: fixtures for a `main` under a tsconfig `outDir`, a Vite config with a non-default `root`, an unresolved entry, and a `structure.json` that adds a manifest-less package and renames a deployable (ID unchanged). On sample-desktop: the four deployables each have member files.

## 6. Query commands

Outcome: `cbi search`, `cbi show`, `cbi tests-for`, `cbi status` complete, each with text and `--json`, and `--help` written for agents.

Depends on: 4. Parallel with: 5.

Checks: tests for each command and both output modes; FTS finds a class, function, test case and folder; `status` lists diagnostics.

## 7. Task protocol and prime

Outcome: all five task kinds, bottom-up blocking, atomic submit that unblocks dependents, cascade only on changed child text, the shared answer cache, `confirm-structure` writing `structure.json` and rerunning manifests and resolution, and `cbi prime` covering all three states.

Depends on: 5, 6.

Checks: unit tests for blocking order, validation errors (JSON path in message, exit 2), idempotent resubmit, cache hit on a second repo with identical files, parent reopening only on changed text. A2: a fresh agent session given only "run `cbi prime` and map this repo" completes all sample-desktop tasks, including creating `core` and `shared` as packages; record the outcome in `docs/acceptance/sample-desktop.md`.

## 8. Viewer

Outcome: the full static viewer: drill-down with single-child collapse, deployable membership view, detail pane, relationships rolled up at build time, chunked symbol data with a chunk manifest and edges in both endpoint chunks, search loaded after first paint, static test overlay.

Depends on: 6. Parallel with: 7 (uses whatever summaries exist).

Checks: rollup unit tests; a synthetic model of sample-monorepo's size (1.6k files, 30k symbols, 100k edges) builds with `tree.js` under 3 MB; Playwright smoke from `file://` on sample-desktop (search into an unopened chunk, drill to a method, see a caller from another group, toggle overlay); no `innerHTML` on model text.

## 9. Test ingest

Outcome: `cbi ingest` for lcov, coverage.py JSON with per-test contexts, and JUnit XML; artifacts merge by artifact path; overlay modes for coverage and results; `prime` prints the generate commands for the detected runners.

Depends on: 8.

Checks: parser tests on small sample files for each format; a coverage.py fixture with contexts producing `tests` edges; unmatched JUnit cases and unmapped coverage paths reported as diagnostics; re-ingesting one suite replaces only its rows. Verify on sample-desktop that Node's coverage with `--enable-source-maps` reports `.ts` paths and lines; if it does not, implement mapping through `.js.map` files here.

## 10. Docs and agent assets

Outcome: doc nodes with titles, presentation-level doc collapse that tolerates stray code, `mentions` edges; skills and repertoires detected as packages.

Depends on: 5. Parallel with: 7, 8, 9.

Checks: fixture with a doc dump over the threshold that contains a `.py` file (still parsed and searchable), a `.claude/skills/x/scripts/` with a test, and a doc naming a symbol in backticks.

## 11. sample-desktop end to end

Outcome: A1, A2, A3 and A7 confirmed together on sample-desktop with all judgement tasks done and all three test suites ingested, and a short usage skill in `.claude/skills/codebase-inspector/SKILL.md` that tells the agent to run `cbi prime`.

Depends on: 7, 9, 10.

Checks: `scripts/acceptance.sh <repo> <out-dir>` on sample-desktop, and a walk through the viewer. Cold scan about 1.4 s. An agent run from `cbi prime` alone kept four deployables and added manifest-less packages `core` and `shared`. Node coverage compiled with source maps reported `.ts` paths (about 5,000 lines, none unmapped).

## 12. sample-apps checkpoint

Outcome: A4 passes. Adds what sample-apps needs: vitest and jest test detection, `bin` entries under `dist/`, `wrangler.toml` entries, several apps sharing a package, one content submodule.

Depends on: 11.

Checks: fixtures for each addition; `scripts/acceptance.sh <repo> <out-dir>` on sample-apps. Cold scan 2.1 s. Two workspaces; the apps depend on a shared package whose `dist` main is a library entry, not a deployable. A cli `bin` under `dist/` resolves to source. A wrangler main of `.open-next/worker.js` resolves to the app root. 65 test files, 712 cases. Scripts whose targets are only tests are not deployables.

## 13. Python parsing and Python manifests

Outcome: Python symbols, imports (src layout, `__init__.py` re-exports, uv path sources), resolved calls with shadowing, pytest tests and test cases; `pyproject.toml` (`[project.scripts]`, uv sources), `Dockerfile*`, `Containerfile` and compose services as deployables.

Depends on: 4 (shares resolver structure). Parallel with: 5 to 12. Start it early so the resolver does not settle around TypeScript only.

Checks: fixture covering dataclasses, nested classes, decorators, relative and absolute imports, an `__init__.py` re-export, `tests/` dirs not mirroring source, and a `compose.yaml.tmpl` decoy; golden dump.

## 14. sample-monorepo checkpoint

Outcome: A5, A6 and A7 pass on sample-monorepo.

Depends on: 10, 12, 13.

Checks: `scripts/acceptance.sh <repo> <out-dir>` on sample-monorepo, including viewer timings. Cold scan 42.8 s (budget 60 s), no-change rescan 0.3 s (budget 10 s), first diagram about 1.1 s, drill and search a few milliseconds. `data/tree.js` was 19.6 MB and loads after the first diagram. A second checkout of the same monorepo scanned in 32.2 s; file ids matched for shared paths, including files whose blobs differed. If the scan exceeds 60 s, profile and fix before closing (limiting resolution to changed files and their importers is the first candidate).

# PRD-02 concept map

Read `docs/prd-02-concept-map.md` and the "Concept map (PRD-02)" section of `docs/architecture.md`. Deliverables 11, 12 and 14 above still apply and run after these.

## 15. Structure task

Outcome: `confirm-structure` and `summarise-deployable` (PRD-01 deliverable 7 part B): the agent confirms deployables and entry points and adds manifest-less packages; answers write `structure.json` and rerun manifests and resolution.

Checks: on sample-desktop, removing the two dev-script deployables and adding `core` and `shared` through a submitted answer; IDs unchanged on rename.

## 16. Env vars

Outcome: env var extraction for TS/JS and Python, declarations from example env files, compose and wrangler, `env` nodes and `reads_env` edges, shown in `cbi show` and found by `cbi search`. Parallel with: 15, 17.

Checks: fixtures for each read form and default; a real `.env` file in the fixture is never opened (assert on file access); sample-desktop's env vars listed.

## 17. Concepts

Outcome: `define-concepts` with its inputs and checks, `.cbi/concepts.json` applied on every scan, concept and external nodes, `owns` and `relates` edges, rescans that ask only about unowned or changed files; `cbi show` and `cbi search` cover concepts. Depends on: 15.

Checks: the checks table in the architecture as unit tests (each failing check reported, all at once); the mockup's `sample-desktop-concepts.json` (minus screens) accepted as an answer on sample-desktop; a rescan after adding a file opens a task listing only that file.

## 18. Screens

Outcome: `sketch-screens`, `.cbi/screens.json`, screen nodes and `sketches` edges. Depends on: 17.

Checks: region components must exist; unsketched UI components must be listed with a reason; the mockup's screens accepted on sample-desktop.

## 19. Concept viewer

Outcome: `cbi build` writes the concept viewer from the mockup's `app.js`: boundary, roles and key, zoom and pan, Esc and history, integration points and stubs, leaf code view with renders, ghost nodes, test badges and env chips, wireframe view with props, renders and reads, search, test overlay mode, and the fallback diagram when no concepts exist. Depends on: 16, 17; wireframes need 18.

Checks: build-time unit tests for rollups behind relationships; Playwright smoke on sample-desktop from `file://` (drill into a leaf, Esc back, zoom, open a screen sketch, search an env var); screenshots compared against the mockup.

## 20. sample-desktop end to end with concepts

Outcome: PRD-02 B1 to B5 on sample-desktop, with an agent doing every task from `cbi prime` alone. Replaces the viewer part of deliverable 11.

# PRD-02 additions

## 32. Reviewer queries

Outcome: `cbi hotspots`, `orphans`, `cycles` and `deps` (matrix and assertion form), `show` ordering, confidence floor and `--all`, test linking through file-local helpers, direct vs transitive `part_of`, env spreads as a note, dev scripts not counted as deployables. From architecture reviews of sample-desktop. Parallel with everything.

Checks: on sample-desktop the queries surface what the reviewers found by hand (a test-only module, a cycle, a high fan-in file, a package with no tests of its own).

# PRD-03 desktop app

Read `docs/prd-03-desktop-app.md` and "Desktop app (PRD-03)" in `docs/architecture.md`.

## 21. Ref scanning

Outcome: `cbi scan --ref`, `--ref` on every read command, `cbi worktrees --json`. Engine for PRD-03 and PRD-04. Parallel with: 22, 26, 32.

Checks: two refs of a fixture scanned with identical IDs for unchanged files; no-mutation test (status, worktree list and refs unchanged); sample-desktop HEAD~5 scanned.

## 22. App shell

Outcome: Electron app with start screen, open folder, recents, first scan and build, tasks panel with agent instruction, live reload on model changes. Parallel with: 21, 26, 32.

Checks: recents and project resolution unit tests; Playwright Electron smoke on a fixture repo; packaged `.app`.

## 23. Worktree and branch switcher

Outcome: switcher listing worktrees (with lane names) and branches from `cbi worktrees`, per-view state, ref models for branches, live rescans of the open worktree. Depends on: 21, 22.

Checks: PRD-03 B3, B4, B5.

## 24. Open in a state

Outcome: `cbi open` and the `cbi://` scheme with validation; switching an open window with a Back chip. Depends on: 22. Parallel with: 23.

Checks: PRD-03 B6a; a malformed link is refused with a message.

# PRD-04 change review

Read `docs/prd-04-change-review.md` and "Change review (PRD-04)" in `docs/architecture.md`.

## 26. Diff engine

Outcome: `src/cbi/diff.py` and `cbi diff` (text, Markdown, JSON) on two models, then on refs once 21 lands. Parallel with: 21, 22, 32.

Checks: fixture pairs for each change kind and a move; golden outputs; sample-desktop HEAD~10..HEAD.

## 27. Review command

Outcome: `cbi review <pr|branch>` with `gh` resolution, `review.md` with Mermaid, provisional concepts for new files, `summarise-change` task, `--post` with comment update. Depends on: 21, 26.

Checks: PRD-04 D3 (Markdown and Mermaid part), D4, D5.

## 28. Review images

Outcome: `render.html` from the viewer code and headless Chrome capture of before/after PNG and SVG. Depends on: 26 and the viewer port (19) settling.

Checks: PRD-04 D3 (images); skipped cleanly without Chrome.

## 29. Comparison mode in the viewer

Outcome: `cbi build --compare`, marks, changes panel, base/head toggle, function code diffs, two-way navigation. Depends on: 26, 19.

Checks: PRD-04 D1, D2 in the static viewer.

## 30. Comparison in the app

Outcome: choose two sides in the app, `cbi open --compare` and `--pr`. Depends on: 23, 24, 29.

Checks: PRD-04 D4a.

# PRD-05 system views

Read `docs/prd-05-system-views.md` and the PRD-02 two-way navigation requirements first. Each slice below ends with its focused tests, the full tests that cover touched code, and one commit.

## 49. PRD and thin-slice plan

Outcome: the system-views PRD fixes the semantic model, user journeys, navigation rules, acceptance criteria and boundaries before implementation.

Checks: documentation style check and a clean diff limited to the PRD and this plan.

## 50. SQL schema model

Outcome: stable table and column nodes, key and foreign-key facts, and source evidence from SQL `CREATE TABLE` and `ALTER TABLE` migrations. Data facts are replaced safely on rescan and contain no layout fields.

Checks: a small migration fixture with composite declarations, inline and table constraints, quoted names and an added foreign key; rescan and stable-ID tests; a model-shape test that refuses layout keys.

## 51. ORM schema model

Outcome: the same table, column and relationship model from SQLAlchemy, Django, Prisma, TypeORM and EF Core declarations, reconciled with migration facts when both exist.

Checks: one small fixture repository per framework, including explicit table names, inferred names, primary keys, nullable fields and one relationship; duplicate declarations merge into one table.

## 52. Table reads and writes

Outcome: `reads_table` and `writes_table` edges from the innermost code symbol or file, extracted from literal SQL and common calls in the five supported ORMs.

Checks: focused SQL and ORM fixture operations, mixed read and write use, multiline SQL, false positives in comments and unrelated methods, and rescan replacement.

## 53. System-view build payloads

Outcome: `data/database.js` and `data/endpoints.js` export layout-free schema and endpoint records. Endpoint notes reuse summaries and docstrings; callers reuse `http_calls`; downstream code and tables follow bounded resolved call paths with direct evidence marked.

Checks: payload unit tests for unmatched routes, note fallback order, callers, direct and downstream table use, stable sorting, and absence of layout fields.

## 54. Database viewer

Outcome: top-level tabs and a zoomable, pannable ERD with automatic browser-side layout, table selection, keys, relationships, Reads and Writes, editor links and concept-map jumps. The existing concept map stays unchanged inside its tab.

Checks: DOM and navigation tests from `file://`, layout helper tests, injection checks, and headless Chrome screenshots of a fixture schema at the overview and selected-table states.

## 55. Endpoint viewer and desktop state

Outcome: the API endpoint list, method and text filters, endpoint details, links to callers, handlers, downstream code and tables, plus cross-view Back and Esc behaviour. Desktop saved state and deep links preserve the selected system tab.

Checks: DOM tests for catalogue content and filters, two-way cross-view navigation and Esc, existing open-in-editor behaviour, desktop state unit tests, a headless Chrome screenshot, `uv run pytest`, and `npm test` in `app/`.

## 56. Target repository check

Outcome: sample-apps and sample-saas are mapped read-only into temporary output directories. Findings needed by their migration and ORM styles are folded into the focused extractors and recorded in acceptance notes.

Checks: both source working trees remain clean; captured database and endpoint screenshots are inspected; final full Python and desktop unit suites pass.

# PRD-07 team mode

Read `docs/prd-07-team-mode.md`, ADR-0023 and "Team mode (PRD-07)" in `docs/architecture.md`. Built before PRD-06.

## 70. Committed answers

Outcome: `team.toml`, `cbi team init`, `answers.jsonl` export after every accepted answer, import on scan, derived-only `.gitignore`, `.gitattributes` line.

Checks: U1 and U3 on fixture repos (clone, two branches); U4 non-team behaviour unchanged.

## 71. cbi check

Outcome: `cbi check` with changed-file detection, all checks, secret patterns, text and GitHub formats, warn mode; CI snippet in the README and `team init` output. Depends on: 70.

Checks: U2 and U5; a secret-looking answer is refused.

# PRD-06 architecture history

Read `docs/prd-06-architecture-history.md` and "Architecture history (PRD-06)" in `docs/architecture.md`.

## 60. History engine

Outcome: `src/cbi/history.py`: points from merges on the default branch, ref models per point, concept projection, per-entry diffs, the index; `cbi history` text, Markdown and JSON with `--since`, `--until`, `--concept`, `--limit`; `--write` for `.cbi/CHANGELOG-ARCHITECTURE.md`; incremental rebuilds.

Checks: fixture repos with merge and squash histories; projection of a moved file and a vanished concept; I1, I2, I3, I5 on codebase-inspector and sample-desktop.

## 61. Timeline in the viewer and app

Outcome: `cbi build --history`, the timeline strip, scrub to replay with marks, entry to comparison with a Back chip, copy for agent on entries; the desktop app builds history in the background. Depends on: 60.

Checks: I4; Playwright scrub and click on sample-desktop.

## 62. Narratives on request

Outcome: `cbi history --narrate <sha>` opening `summarise-change` for an entry, answers shown in the changelog and the app. Depends on: 60. Parallel with: 61.

## After PRD-04

Write PRD-05 (data map: schema from migrations, query table usage, ERD) with sample-apps and sample-saas as targets. sample-saas cold scan was 12.0 s. Compose image commands with no tracked source leave the image deployable without an entry; service commands supply the entries. A package with package-mode off is not a package. Image-only services are externals. The default `evals/` ignore did not cover a nested eval directory of about 6,500 files. 602 test files, 555 with a `tests` edge. One module had fan-in 267; one SQL module was 6,511 lines.

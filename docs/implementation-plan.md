# Implementation plan: PRD-01 orientation map

Read `docs/prd-01-orientation-map.md` and `docs/architecture.md` first. Each deliverable is one reviewable change with its tests. Numbers give the order; "parallel with" marks work that can run alongside.

## 1. Scaffold

Outcome: `uv tool install .` puts `cbi` on PATH; `cbi --help` and `cbi prime` run; `pytest` passes.

Scope: `pyproject.toml`, `src/cbi/cli.py` with subcommand stubs, `prime.py` printing the not-initialised guide, a fixture helper that builds a git repo in a temp dir, one test, `.claude/skills/` with `.agent/skills` symlink, README with install and test commands.

Excludes: any scanning.

Checks: `uv run pytest`; `cbi prime` exits 0.

## 2. Init, enumeration and the store

Outcome: `cbi init` creates `.cbi/` (self-ignoring) with `ignore`; `cbi scan` stores workspace, group and file nodes, including nested submodule workspaces with normalised remote IDs, pinned and checked-out commits, drift and uninitialised state. Content hashing reads the working tree, and the no-change shortcut works.

Depends on: 1.

Checks: fixture with a submodule, a tracked symlink, a data dir and an unstaged edit; golden dump; remote normaliser unit tests (ssh and https forms of one repo give one ID); an unstaged edit, a deletion and an ignore-file change each trigger a rescan, and an untouched repo hits the shortcut; `git status --porcelain` on the fixture is empty after init and scan (A8). Timing probe: enumerate and classify `~/projects/xenota` and record the time in `docs/acceptance/xenota.md`.

## 3. Tracer bullet on one orchestra pair

Outcome: one thin path end to end on `service/` `DeviceRegistry` and its test. TS parsing gives symbols for those files; `cbi show` and `cbi search` return them; a `summarise-files` task is issued, answered by hand with `cbi submit`, and shows up in `cbi show`; `cbi build` writes a bare viewer that opens from disk with breadcrumb, children list and detail pane. Editing the file and rescanning reopens its task.

Depends on: 2.

Excludes: resolution, manifests, other task kinds, overlays, chunking.

Checks: a test that runs scan, task, submit, show and build on a copy of those two files in a fixture; the stale-answer rejection (submit after the file changed) and the per-file cache are tested here, because they shape the protocol everything else uses.

## 4. TypeScript parsing, resolution and test linking

Outcome: all TS, TSX and JS gain symbols, import edges (relative, tsconfig `paths`, re-exports), resolved call edges with shadowing checks, node:test test files and cases linked to code by calls, imports, names and literal file reads, and diagnostics for ambiguous calls and unmatched tests.

Depends on: 3.

Checks: fixture covering classes, methods, arrow-function consts, React components, a path alias, a re-export through `index.ts`, a shadowed name, a test reading a CSS file, and a test with no subject; golden dump. On orchestra: 32 test files detected, every one linked or carrying an `unmatched_test` diagnostic.

## 5. Manifests and structure overrides (package.json family)

Outcome: deployables and packages from `package.json`, Vite configs and tsconfig projects; build-output entry points mapped to source through `outDir`/`rootDir`; Vite entries read from `index.html`; `part_of` by reachability; `structure.json` applied before detection on every scan.

Depends on: 4 (reachability needs import edges).

Checks: fixtures for a `main` under a tsconfig `outDir`, a Vite config with a non-default `root`, an unresolved entry, and a `structure.json` that adds a manifest-less package and renames a deployable (ID unchanged). On orchestra: the four deployables each have member files.

## 6. Query commands

Outcome: `cbi search`, `cbi show`, `cbi tests-for`, `cbi status` complete, each with text and `--json`, and `--help` written for agents.

Depends on: 4. Parallel with: 5.

Checks: tests for each command and both output modes; FTS finds a class, function, test case and folder; `status` lists diagnostics.

## 7. Task protocol and prime

Outcome: all five task kinds, bottom-up blocking, atomic submit that unblocks dependents, cascade only on changed child text, the shared answer cache, `confirm-structure` writing `structure.json` and rerunning manifests and resolution, and `cbi prime` covering all three states.

Depends on: 5, 6.

Checks: unit tests for blocking order, validation errors (JSON path in message, exit 2), idempotent resubmit, cache hit on a second repo with identical files, parent reopening only on changed text. A2: a fresh agent session given only "run `cbi prime` and map this repo" completes all orchestra tasks, including creating `orchestra-core` and `shared` as packages; record the outcome in `docs/acceptance/orchestra.md`.

## 8. Viewer

Outcome: the full static viewer: drill-down with single-child collapse, deployable membership view, detail pane, relationships rolled up at build time, chunked symbol data with a chunk manifest and edges in both endpoint chunks, search loaded after first paint, static test overlay.

Depends on: 6. Parallel with: 7 (uses whatever summaries exist).

Checks: rollup unit tests; a synthetic model of xenota's size (1.6k files, 30k symbols, 100k edges) builds with `tree.js` under 3 MB; Playwright smoke from `file://` on orchestra (search into an unopened chunk, drill to a method, see a caller from another group, toggle overlay); no `innerHTML` on model text.

## 9. Test ingest

Outcome: `cbi ingest` for lcov, coverage.py JSON with per-test contexts, and JUnit XML; artifacts merge by artifact path; overlay modes for coverage and results; `prime` prints the generate commands for the detected runners.

Depends on: 8.

Checks: parser tests on small sample files for each format; a coverage.py fixture with contexts producing `tests` edges; unmatched JUnit cases and unmapped coverage paths reported as diagnostics; re-ingesting one suite replaces only its rows. Verify on orchestra that Node's coverage with `--enable-source-maps` reports `.ts` paths and lines; if it does not, implement mapping through `.js.map` files here.

## 10. Docs and agent assets

Outcome: doc nodes with titles, presentation-level doc collapse that tolerates stray code, `mentions` edges; skills and repertoires detected as packages.

Depends on: 5. Parallel with: 7, 8, 9.

Checks: fixture with a doc dump over the threshold that contains a `.py` file (still parsed and searchable), a `.claude/skills/x/scripts/` with a test, and a doc naming a symbol in backticks.

## 11. Orchestra end to end

Outcome: A1, A2, A3 and A7 confirmed together on orchestra with all judgement tasks done and all three test suites ingested, and a short usage skill in `.claude/skills/codebase-inspector/SKILL.md` that tells the agent to run `cbi prime`.

Depends on: 7, 9, 10.

Checks: `scripts/acceptance.sh ~/projects/orchestra`, results in `docs/acceptance/orchestra.md`, and a walk through the viewer by JV.

## 12. lms checkpoint

Outcome: A4 passes. Adds what lms needs: vitest and jest test detection, `bin` entries under `dist/`, `wrangler.toml` entries, several apps sharing a package, the curriculum submodule.

Depends on: 11.

Checks: fixtures for each addition; `scripts/acceptance.sh ~/projects/lms`, results in `docs/acceptance/lms.md`.

## 13. Python parsing and Python manifests

Outcome: Python symbols, imports (src layout, `__init__.py` re-exports, uv path sources), resolved calls with shadowing, pytest tests and test cases; `pyproject.toml` (`[project.scripts]`, uv sources), `Dockerfile*`, `Containerfile` and compose services as deployables.

Depends on: 4 (shares resolver structure). Parallel with: 5 to 12. Start it early so the resolver does not settle around TypeScript only.

Checks: fixture covering dataclasses, nested classes, decorators, relative and absolute imports, an `__init__.py` re-export, `tests/` dirs not mirroring source, and a `compose.yaml.tmpl` decoy; golden dump.

## 14. xenota checkpoint

Outcome: A5, A6 and A7 pass on xenota.

Depends on: 10, 12, 13.

Checks: `scripts/acceptance.sh ~/projects/xenota` with timings; viewer timings in the Playwright smoke script; results in `docs/acceptance/xenota.md`. If the scan exceeds 60 s, profile and fix before closing (limiting resolution to changed files and their importers is the first candidate).

## After PRD-01

fundsorter and xcd are the next scale checks. Write PRD-02 (change review) once orchestra's map has been used for a while.

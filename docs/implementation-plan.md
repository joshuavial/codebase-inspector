# Implementation plan: PRD-01 orientation map

Read `docs/prd-01-orientation-map.md` and `docs/architecture.md` first. Each deliverable is one reviewable change with its tests. Numbers give the order; "parallel with" marks work that can run alongside.

## 1. Scaffold

Outcome: `uv tool install .` puts `cbi` on PATH; `cbi --help` and `cbi prime` run; `pytest` passes.

Scope: `pyproject.toml`, `src/cbi/cli.py` with subcommand stubs, `prime.py` printing the not-initialised guide, one test, `.claude/skills/` with `.agent/skills` symlink, README with install and test commands.

Excludes: any scanning.

Checks: `uv run pytest`; `cbi prime` exits 0.

## 2. Init and file enumeration

Outcome: `cbi init` creates `.cbi/` (self-ignoring) with `ignore` and `config.toml`; `cbi scan` stores workspace, group and file nodes from `git ls-files`, including nested submodule workspaces with drift and uninitialised state.

Depends on: 1.

Checks: fixture repo with a submodule, a tracked symlink and a data dir; golden dump; `git status --porcelain` on the fixture is empty after init and scan (A8).

## 3. TypeScript parsing and resolution (orchestra slice)

Outcome: TS, TSX and JS files gain symbol nodes, import edges and resolved call edges; tests and test cases are detected for node:test, vitest and jest and linked to code.

Depends on: 2.

Checks: fixture covering classes, methods, arrow-function consts, React components, `tsconfig` path aliases, and a `x.test.ts` pair; golden dump. On orchestra: 32 test files detected, `DeviceRegistry` methods present.

## 4. Manifests and deployables

Outcome: deployables, packages and resources from manifests, `part_of` edges by entry-point reachability, `depends_on` edges.

Depends on: 3 (reachability needs import edges).

Checks: per-manifest fixtures (package.json with vite and electron, pyproject with scripts and uv sources, `Dockerfile.x`, `Containerfile`, compose with services and images, a `.tmpl` decoy). On orchestra: the four deployables and the two packages from A1 (the rules may miss some; deliverable 6 lets the agent correct them).

## 5. Query commands and store search

Outcome: `cbi search`, `cbi show`, `cbi tests-for`, `cbi status`, each with text and `--json`, and `--help` written for agents.

Depends on: 3. Parallel with: 4.

Checks: tests on a fixture for each command and both output modes; FTS finds a class, function, test case and folder.

## 6. Judgement tasks and prime

Outcome: tasks generated bottom-up with briefs and schemas; `cbi tasks`, `cbi task`, `cbi submit` with validation and the shared answer cache; `cbi prime` covers all three states.

Depends on: 4, 5.

Checks: unit tests for blocking order, validation errors (JSON path in message, exit 2), cache hit on a second repo with identical files, invalidation when a file changes. A2: a fresh agent session given only "run `cbi prime` and map this repo" completes all orchestra tasks; record the transcript outcome in `docs/acceptance/orchestra.md`.

## 7. Viewer

Outcome: `cbi build` writes the static viewer with drill-down, detail pane, treemap, graph tab, search and the static test overlay.

Depends on: 5. Parallel with: 6 (uses whatever summaries exist).

Checks: build-time rollup unit tests; Playwright smoke from `file://` on orchestra (search, drill to a method, overlay toggle); no `innerHTML` on model text.

## 8. Test ingest

Outcome: `cbi ingest` for lcov, coverage.py JSON with contexts, and JUnit XML; overlay modes for coverage and results; `prime` prints the generate command for the detected runner.

Depends on: 7.

Checks: parser tests on small sample files for each format, including unmatched JUnit cases being reported. A3 on orchestra: JV builds orchestra's tests and runs `node --test --experimental-test-coverage --test-reporter=lcov --test-reporter-destination=<out>/lcov.info --test-reporter=junit --test-reporter-destination=<out>/junit.xml` on the compiled test files, then ingests both.

## 9. Docs and agent assets

Outcome: doc nodes with titles, collapse of large doc dirs, `mentions` edges; skills and repertoires detected as packages.

Depends on: 4. Parallel with: 6, 7, 8.

Checks: fixture with a `docs/` dump over the threshold, a `.claude/skills/x/scripts/` with a test, and a doc naming a symbol in backticks.

## 10. lms checkpoint

Outcome: A4 passes. Fixes from what lms exposes (multiple apps sharing a package, Supabase functions, the curriculum submodule).

Depends on: 4, 7, 9.

Checks: `scripts/acceptance.sh ~/projects/lms`, results recorded in `docs/acceptance/lms.md`.

## 11. Python parsing

Outcome: Python symbols, imports (src layout, `__init__.py`, uv path sources), resolved calls and pytest tests and test cases.

Depends on: 3 (shares resolver structure). Parallel with: 4 to 9.

Checks: fixture covering dataclasses, nested classes, decorators, relative and absolute imports, `tests/` dirs not mirroring source; golden dump.

## 12. xenota checkpoint

Outcome: A5, A6 and A7 pass on xenota.

Depends on: 9, 10, 11.

Checks: `scripts/acceptance.sh ~/projects/xenota` with timings; viewer timings measured in the Playwright smoke script; results in `docs/acceptance/xenota.md`. If the scan exceeds 60 s, profile and fix before closing (incremental resolution is the first candidate, per architecture).

## 13. Orchestra end to end

Outcome: A1 to A3 and A7 confirmed together on orchestra with all judgement tasks done, and a short usage skill in `.claude/skills/codebase-inspector/SKILL.md` that tells the agent to run `cbi prime`.

Depends on: 6, 8, 9.

Checks: acceptance script plus a manual walk through the viewer by JV.

## After PRD-01

fundsorter and xcd are the next scale checks. Write PRD-02 (change review) once orchestra's map has been used for a while.

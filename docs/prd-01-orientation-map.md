# PRD-01: Orientation map

## Problem

Agents and developers working in a repository they do not know, or one that agents have grown faster than anyone has read it, rebuild their understanding from scratch: list directories, open files, grep for names. Agents repeat this every session. Existing tools cover pieces of the job. C4 tools are drawn by hand, symbol indexers have no idea what a part is for, and LLM wiki generators produce prose with no structure to query or keep current.

## Users

- **AI agents working in a codebase** (Claude Code, Codex and similar). They need a fast way to answer "what is this part, what does it touch, which tests cover it" from the command line, and they do the judgement work the tool cannot.
- **The developer directing those agents.** They need a picture they can explore from the top down to a method, and search, to understand a repo or check what agents have built.

## Outcome

Running the inspector on a repository produces a model of it that a person can browse and an agent can query. The model goes from the workspace down to individual methods, says what each part does, and links tests to the code they exercise.

Success signals:

- On sample-desktop, an agent that has run `cbi prime` answers orientation questions ("what does the service do", "which tests cover the registry") with `cbi` queries instead of reading files.
- A person can find any file, class, function, test or doc in sample-desktop from the viewer's search and drill to it from the workspace in a few clicks.
- The same tool scans sample-monorepo, which has about 1.6k code files across submodules, without a code change, and its viewer stays responsive.

## Model the user sees

The map is one tree. Each node has a kind, and a kind can be absent from a repo without leaving a gap.

| Kind | What it is | Examples |
|---|---|---|
| workspace | A repository; a git submodule is a nested workspace | sample-desktop, sample-monorepo > its code submodule |
| deployable | Something that runs or ships on its own | Electron app, service daemon, CLI, container image, site |
| package | A library or workspace member, including skills and repertoires | core, a package inside the code submodule, a `.claude/skills` skill |
| module, folder, component | A nestable grouping of files | a Python subpackage, `src/components` |
| file | A source file | `service/registry.ts` |
| class, function, method, component, interface, ... | Code symbols, shown by their real kind | `DeviceRegistry`, `revoke()` |
| test file, test case | Tests, in the tree where they sit | `registry.test.ts` > "revokes a device" |
| doc | Markdown and doc-site pages, searchable, not parsed for symbols | `docs/setup.md` |

External dependencies sit outside the tree and are shown on request.

Relationships: imports, calls, tests (test case to the code it exercises), part-of (a file belongs to a deployable; a file can belong to several), depends-on (between packages and deployables, from manifests), mentions (a doc to the code it names), and pins (a workspace to the submodule commit it records). Relationships between deep nodes also show at every level above them.

## User journeys

1. **Map a repo.** In the repo, the agent runs `cbi init` then `cbi scan`. The scan reports what it found and how many judgement tasks are waiting.
2. **Do the judgement work.** The agent runs `cbi tasks`, takes a task (for example "name and summarise these 12 files"), reads the inputs the task lists, and submits a JSON answer. The CLI rejects malformed answers with a reason. Tasks run bottom-up: a folder's summary task opens once its files are done. The agent may hand tasks to subagents.
3. **Learn the tool.** An agent with no prior knowledge runs `cbi prime` and gets a short guide matched to the repo's current state: not initialised, scanned with tasks pending, or complete. Each command's `--help` covers its options and output.
4. **Query.** The agent runs `cbi search <text>`, `cbi show <node>` (summary, children, relationships, tests) or `cbi tests-for <node>`, in text or `--json`.
5. **Browse.** The developer runs `cbi build` and opens the viewer from disk. They start at the workspace, drill into deployables, packages and folders down to methods, follow relationships, and search across every kind.
6. **See tests.** With no extra setup the viewer shows which code has tests linked to it by static analysis. If coverage or result files are supplied with `cbi ingest`, the viewer shows measured coverage and pass/fail as well.
7. **Re-run.** After code changes, `cbi scan` reparses only changed files and reopens only the judgement tasks whose inputs changed.

## Requirements

### Mapping

- R1. Enumerate files from git for the repo and every initialised submodule; never walk the filesystem or follow tracked symlinks.
- R2. Model submodules as nested workspaces identified by their normalised remote URL. Record the pinned and checked-out commits, flag when they differ, and show uninitialised submodules as empty nodes.
- R3. Detect deployables and packages from manifests: `package.json`, `vite.config.*`, `pyproject.toml` (including `[project.scripts]` and uv path sources), `Dockerfile*`, `Containerfile`, compose files, `wrangler.toml`, `Cargo.toml`. Map entry points that name build output (`dist-*/…/main.js`) or HTML script tags back to source files. Ignore template files such as `*.tmpl`.
- R4. Parse TypeScript, TSX, JavaScript and Python into classes, functions, methods, React components and interfaces, with signatures, docstrings and line ranges. Other languages appear as file nodes.
- R5. Resolve import edges between files and packages. Resolve call edges where the callee name can be bound (same file, explicitly imported name, method on the same class); mark each edge with its source and confidence.
- R6. Detect test files and test cases for node:test, vitest, jest and pytest. Link test cases to the code they import and call, and boost links where file names match.
- R7. Treat skills, repertoires and other agent assets as packages and parse them like code. Treat markdown as doc nodes, collapse large doc-only directories to one node, and exclude data, fixtures, eval snapshots, generated and tracked build output through an ignore file that `init` writes and the user can edit.
- R8. Give every node a stable ID derived from its workspace, path and qualified name, so the same code keeps the same ID across scans.
- R9. Re-scan incrementally by the content of files on disk, including unstaged edits, deletions and changes to the ignore file.

### Judgement tasks

- R10. Generate tasks for work that needs judgement: naming and summarising files, folders, packages, deployables and the workspace, and confirming or correcting the detected structure (deployables, their entry points, and packages that have no manifest). Structure corrections persist and apply to every later scan. Symbols keep their signature and docstring and get no AI summary in this increment.
- R11. Give each task its inputs and the exact JSON shape expected. Validate answers and report errors precisely enough for an agent to fix them. Reject answers to a task whose inputs changed since it was issued. Accepting an answer opens the tasks that were waiting on it.
- R12. Cache accepted file summaries per file content hash, in a cache shared across repos, so identical code is never summarised twice. A parent summary reopens only when a child's summary text changes.

### Agent interface

- R13. `cbi prime` prints a guide to the tool that reflects the current repo's state.
- R14. Every command has `--help` written for an agent reader, and every read command supports `--json`.
- R15. Query commands: `search`, `show`, `tests-for`.

### Tests

- R16. Ingest lcov, coverage.py JSON (including per-test contexts) and JUnit XML, mapping coverage to source nodes (through source maps when the tests ran on compiled output) and results to test cases. Several artifacts for one repo merge; a later artifact from the same source file replaces the earlier one.
- R17. For each repo, `cbi prime` or `cbi ingest --help` shows the command that produces those files with output outside tracked paths.

### Viewer

- R18. `cbi build` writes a static viewer that opens from disk with no server.
- R19. Drill down from the workspace to methods with a breadcrumb, showing each node's children as a list, summary, signature, relationships rolled up to the visible level, and linked tests. Chains of single-child folders collapse into one step. A deployable lists the files that are part of it.
- R20. Search across every kind from one box, with results grouped by kind, and jump to any result with its ancestors expanded.
- R21. Show a test overlay on the children list and detail pane: static test links, or measured coverage and pass/fail when ingested.
- R22. Show the concrete kind (class, method, module, folder) everywhere; internal schema names never appear in the UI.

### Storage

- R23. `cbi init` creates a hidden `.cbi/` directory in the repo that ignores itself through its own `.gitignore`, so no tracked file changes. `--out <dir>` puts the model elsewhere.

## Acceptance criteria

- A1. On sample-desktop: init, scan, all judgement tasks completed by an agent, build and query work end to end. The model has the four deployables (Electron main, renderer, loopback service, and a second UI) each with member files, `core` and `shared` as packages (through the structure task, since they have no manifest), and all 32 test files detected, each either linked to code or listed as unmatched with a reason.
- A2. On sample-desktop, an agent given only "run `cbi prime`" completes the task loop without reading the inspector's source or docs.
- A3. On sample-desktop, with lcov and JUnit from all three test suites (electron, renderer, service), the viewer shows per-file coverage on the TypeScript sources and per-test pass/fail.
- A4. On sample-apps: scan, build and query work with no judgement tasks done. The apps, `shared` and the submodule appear as separate nodes.
- A5. On sample-monorepo: scan, build and query work with no judgement tasks done. The code submodule appears as a nested workspace with its uv packages as packages, `docs/research` collapses to one doc node, and the `.agent/skills` symlinks are not double-counted.
- A6. On sample-monorepo, a cold scan finishes in under 60 seconds and a re-scan with no changes in under 10 seconds. The viewer's first paint is under 2 seconds and search and drill-down respond in under 200 ms.
- A7. Search in the viewer and in `cbi search` finds a known class, function, test case, doc and folder in each of sample-desktop and sample-monorepo.
- A8. Running the inspector changes no tracked file in the target repo.

## Non-goals

- The CLI never calls an LLM and never runs the target's tests or code.
- Precise, type-resolved call graphs (SCIP) are a later upgrade.
- AI summaries for individual symbols, and AI regrouping of files into components that cut across folders.
- Istanbul and Playwright result formats. They follow once a target needs them.
- A treemap or node-link graph view. The list and detail views come first; a picture is added once they have been used.
- Resources from compose files (databases, queues, caches).
- Change review, snapshot diffing and the quiz (PRD-02 and later).
- Parsers for Rust, Go, shell and other languages beyond file nodes.

## Assumptions and risks

- **Deployable detection is heuristic.** sample-desktop's four targets come from one `package.json`. The deployable-confirmation task lets the agent correct what the manifest rules miss.
- **Name-resolved calls miss dynamic dispatch.** A package that injects stores and services will leave many of its calls unresolved. Edges carry confidence and the viewer can hide low-confidence ones.
- **Agent quality varies.** Summaries are only as good as the agent that writes them. The CLI can check JSON shape, not truth.
- **Static test links overstate coverage.** A test that imports a module is linked to it even if it exercises one function. The overlay labels static links as such.
- Placeholder names (`cbi`, `.cbi/`) change when the product is named.

## Open questions

- Product name.
- Whether summaries should be regenerated when only a child's summary changed, or only when the node's own files changed. Default: both, since a folder summary is built from its children's.

# Architecture

Covers PRD-01 (`docs/prd-01-orientation-map.md`). Living document: update it when a decision changes. Review findings that shaped it are in `scratch/review/` (Astra, Fable, Grok).

## Constraints from the PRD

- Deterministic CLI, no LLM calls, never executes target code. Agents supply judgement through a task protocol.
- Works on any repo without installing its dependencies or building it.
- xenota scale: ~1.6k code files, ~30k symbols, ~100k edges, cold scan under 60 s, no-change rescan under 10 s, viewer first paint under 2 s.
- Viewer opens from `file://` with no server.
- Leaves tracked files in the target untouched.

## Runtime and tools

| Choice | Version | Why |
|---|---|---|
| Python | >= 3.11 (developed on 3.13) | Agent skills already ship Python. coverage.py formats are native. |
| uv | 0.12 | Install with `uv tool install`, so `cbi` is on PATH with an isolated environment. |
| tree-sitter (py-tree-sitter) | 0.25 | Error-tolerant parsing for every language we need. Held below 0.26: 0.26.0 segfaults on node access after a few parses of one file (deliverable 3), 0.25.2 does not. |
| tree-sitter-language-pack | 1.21 | Prebuilt grammars for Python, TypeScript, TSX, JavaScript and 150+ others in one wheel. Checked: `get_parser("tsx")` and `("python")` work on 3.13. |
| SQLite (stdlib `sqlite3`) with FTS5 | 3.53 on macOS | The model store. Fast `show`/`tests-for` queries and full-text `search` with no extra dependency. FTS5 checked present. |
| argparse (stdlib) | | Enough for a dozen subcommands. Help text is the agent's documentation, so it is written by hand either way. |
| pytest | latest | Tests for the mapper. |
| Viewer: plain JS, no build step | | One static folder. The only vendored library is MiniSearch. |
| MiniSearch | 7.2 | Small client-side full-text index that can be prebuilt and loaded with `loadJSON`. |

Packaging (deliverable 1): build backend is `uv_build`, pytest sits in the `dev` dependency group, and runtime dependencies are floored at the versions above (`>=`), not pinned; `uv.lock` pins them for development.

Alternatives rejected: SCIP indexers (need each repo's dependencies installed); a TypeScript mapper on web-tree-sitter (WASM grammar management, nothing else in the skill stack uses Node); a served viewer (no PRD-01 need). Treemap (d3-hierarchy) and graph (Cytoscape) views are deferred until the list view has been used.

## Repository layout

```
pyproject.toml            package "codebase-inspector", script "cbi"
src/cbi/
  cli.py                  argparse entry, one function per subcommand, help text
  prime.py                state-aware agent guide
  store.py                SQLite schema, migrations, queries
  ids.py                  node ID rules, remote URL normaliser
  files.py                git enumeration, content hashing, submodules, ignore rules
  manifests.py            deployable / package detection, build-output to source mapping
  parse/
    typescript.py         TS, TSX, JS
    python.py             Python
  resolve.py              import and call resolution, test linking
  docs.py                 markdown nodes, collapse, mentions
  tasks.py                judgement task generation, validation, cache
  ingest.py               lcov, coverage.py JSON, JUnit XML
  build.py                viewer export
  viewer/                 index.html, app.js, style.css, vendor/minisearch.min.js (copied by build)
tests/
  fixtures/               builders for small synthetic repos (one per language + a submodule case)
  test_*.py
scripts/acceptance.sh     runs the acceptance checks against a sample repo
.claude/skills/           project skills; .agent/skills -> ../.claude/skills
docs/
```

## Data model

One SQLite file per mapped repo at `.cbi/model.db`.

**nodes**: `id` (text, primary key), `parent_id`, `kind`, `display_kind`, `name`, `workspace_id`, `path`, `start_line`, `end_line`, `lang`, `loc`, `content_hash`, `signature`, `doc`, `summary`, `summary_source` (`agent`, `docstring`, null), `attrs` (JSON).

- `kind` is the internal type: `workspace`, `deployable`, `package`, `group`, `file`, `symbol`, `test`, `doc`, `external`.
- `display_kind` is what users and agents see: `class`, `method`, `function`, `component`, `interface`, `module`, `folder`, `skill`, `test case`, `doc collection`, and so on. The viewer and CLI text output only ever print `display_kind`. `--json` includes both.
- Workspace `attrs` hold `remote`, `pinned_commit`, `checked_out_commit`, `drift` and `initialised`.

**edges**: `src`, `dst`, `kind` (`imports`, `calls`, `tests`, `part_of`, `depends_on`, `mentions`, `pins`), `source` (`treesitter`, `manifest`, `naming`, `coverage`, `agent`), `confidence` (0 to 1), `weight`. Containment is `parent_id`, not an edge.

**diagnostics**: `node_id`, `kind` (`parse_error`, `unresolved_entry`, `ambiguous_call`, `unmatched_test`, `unmapped_coverage`), `detail`. `cbi status` summarises them.

**file_state**: `path`, `mtime_ns`, `size`, `content_hash`, `parser_version`. Used for incremental scans.

**coverage_lines**: `file_id`, `line`, `hits`, `artifact`. **results**: `test_node_id`, `status`, `duration_ms`, `artifact`. Ingesting an artifact replaces only rows from the same artifact path, so several suites merge. A line counts as covered if any artifact hit it.

**tasks**: `id`, `kind`, `node_id`, `input_hash`, `state` (`blocked`, `open`, `done`), `depends_on` (JSON list).

**search**: FTS5 table over `name`, `display_kind`, `path`, `signature`, `doc`, `summary`.

Enumeration details settled in deliverable 2:

- File nodes have `display_kind` `source file`, `test file`, `doc`, `file` (anything else) or `symlink`, and `attrs.role` (`code`, `test`, `doc`, `other`). Markdown gets `kind` `doc`.
- A workspace node's `workspace_id` and `path` refer to its parent workspace (the mount path). `attrs.root` is its path from the top repo, and `attrs.remote` is the normalised remote, never the raw URL, so credentials in a URL are not stored.
- `file_state.path` is relative to the top repo. A `meta` table holds the no-change fingerprint (ignore file, `structure.json`, parser version, every workspace's pinned and checked-out commit).
- The schema version is SQLite's `user_version`. On a mismatch the model is dropped and rebuilt, since it is derived from the repo and answers live in the shared cache.
- `.cbi/ignore` patterns match paths from the top repo root, so they reach into submodules. An ignored submodule path skips the whole submodule.

Parsing and tasks, settled in deliverable 3:

- The TypeScript parser walks the syntax tree rather than running query files: top-level statements (unwrapping `export`) and class members. Symbol `kind` is `symbol`; display kinds are `class`, `method`, `function` (including arrow-function and function-expression consts), `component` and `interface`. Signatures are the declaration text up to the body, whitespace collapsed. A doc is a `/** */` comment ending on the line above.
- In test files, `test`, `it`, `describe`, `test.skip`-style calls and `t.test` subtests with a string name become `kind` `test` nodes: display kind `test case`, or `test suite` for `describe`. Nested cases are children of their suite, and their qualified name joins names with ` > ` (`#double > doubles`).
- Duplicate qualified names: each gets `~<8 hex of sha1(signature)>`; a later duplicate with an identical signature adds `~2`, `~3` after that (`#same~f361afdb`, `#same~f361afdb~2`).
- A file is reparsed when its content hash or parser version changed, or its file ID is new to the model (a workspace ID change).
- `summarise-files` covers code and test files. A folder's files are split, in path order, into batches of 15; batch n is task `sf-<8 hex of sha1(folder ID)>-<n>` and lists only its uncached files. Files at a workspace root use the workspace as the task's node. `tasks.inputs` holds the node IDs a brief lists. `input_hash` is a hash of the protocol version, parser version and each listed file's ID and content hash. A file whose content changed loses its agent summary until it is answered again.
- The answer cache is attached to the model connection (`ATTACH ... AS cache`), so a submit writes the cache, the summaries and the task state in one transaction. A task's files are given as paths from the top repo, which is also what the answer echoes.

Resolution, settled in deliverable 4:

- The parser stores each code file's facts (imports, exports, re-exports, top-level names, call sites, literal reads) as JSON in a `facts` table keyed by file ID, so resolution reruns over every file without reparsing unchanged ones.
- JS uses the tree-sitter `javascript` grammar. `require("x")` counts as an import (whole module, or the destructured names), and a file with no ES exports offers all its top-level names to importers, which covers CommonJS.
- Specifiers resolve inside their own workspace: relative paths with extensions and `index`, a `.js` import naming its `.ts` source, then the nearest `tsconfig.json` `paths` (longest prefix) and `baseUrl`, following relative `extends`. Package names, including workspace packages, are external until manifests exist (deliverable 5).
- An import edge goes to the file that defines each imported name, after following re-exports; it goes to the imported module itself only when no name resolved (namespace, side-effect or unresolved default imports).
- Calls are kept at parse time only when the callee could bind (`f()`, `new F()`, `<F />`, `ns.f()`, `Class.f()`, `this.f()`). `ambiguous_call` counts calls with more than one candidate, such as two same-name definitions in a file. Calls on other receivers (`registry.put()`) and functions passed as values (`createElement(Card)`) get neither an edge nor a diagnostic.
- Test links come from the innermost test case, or from the test file for code outside any case (top level, helpers). Confidences: a call's own (1.0, or 0.6 through `this`), 1.0 for a literal read, 0.8 for a name match (beside the test, or one folder up from `__tests__`, `test` or `tests`), 0.5 for an imported code file. A read path is tried from the test's folder, then with leading `./` and `../` dropped from each folder above, because the working directory and a compiled `__dirname` are unknown.
- `unmatched_test` covers parsed (TS and JS) test files only; Python test files are linked from deliverable 13. Its detail lists the external imports and any read paths missing from the model.

**Structure overrides**: `.cbi/structure.json`, written only by accepted `confirm-structure` answers and editable by hand. It lists deployables (name, display kind, source entry points) and packages (name, directory) to add, rename or remove. It is applied at the start of manifest detection on every scan, so a correction outlives rescans.

### Node IDs

IDs are stable across scans and machines, which PRD-02 needs for diffing.

- workspace: the normalised remote, `host/owner/repo` lowercased, with scheme, user, port and `.git` removed. `git@github.com:xenota-collective/xenon.git` and `https://github.com/xenota-collective/xenon` both become `github.com/xenota-collective/xenon`. With no remote: `local:<dirname>`. A local path or `file://` remote also gives `local:<repo dir name>`, so IDs do not depend on the machine. A relative `.gitmodules` URL (`../lib.git`) is resolved against the parent's `origin` first. Commits are data on the workspace node, never part of the ID, so the same submodule in two superprojects shares IDs.
- file / doc: `<workspace>:<repo-relative path>`.
- symbol / test case: `<file id>#<qualified name>` (`#DeviceRegistry.revoke`). Two definitions with the same qualified name get a suffix from the first 8 hex characters of a hash of their signature text; only definitions with identical signatures fall back to `~2`, `~3` by source order.
- group: `<workspace>:<dir>/`. deployable and package: `<workspace>:deployable:<name>` / `:package:<name>`. A renamed deployable keeps its old ID in `structure.json` as `id`, so the agent's rename does not change it.

## Pipeline (`cbi scan`)

1. **Enumerate** (`files.py`). `git ls-files` per workspace gives the tracked path list; `git submodule status` gives submodules, pinned commit and drift. Content identity comes from the working tree, not the index: each file is `stat`ed, and only when `mtime_ns` or `size` differ from `file_state` is it read and hashed (sha1 of bytes). This catches unstaged edits. Tracked symlinks are recorded as file nodes and never followed. `.cbi/ignore` (gitignore syntax) filters paths.
2. **No-change shortcut.** If no file was added, removed or rehashed to a new value, the ignore file and `structure.json` are unchanged, every workspace's checked-out commit is unchanged, and the parser version is unchanged, the scan stops here.
3. **Classify.** By extension and path: code (Python, TS, TSX, JS), doc (markdown), test (by name pattern and framework), other (file node only). `init` writes `.cbi/ignore` from heuristics: directories named `fixtures`, `evals`, `test-data`, `dist*`, `build`; files with minified-looking lines; directories over 200 files that are more than 90% data (json, txt, csv, jsonl). Doc collapse is presentation only: a directory over 100 files where at most 10% are code and at least half are markdown becomes a `doc collection` node (the outermost such directory wins). The first rule, at least 90% markdown, missed xenota's `docs/research` at 89.9%, because research artefacts (`.out`, `.log`, `.jsonl`) fill the rest. Everything inside is still enumerated, parsed if code, and searchable; the viewer loads its children on demand.
4. **Manifests** (`manifests.py`). Apply `structure.json`, then one rule per manifest type returns deployables, packages and `depends_on` edges. Entry points are mapped back to source:
   - Build output: a path under a tsconfig `outDir` maps to the matching `.ts`/`.tsx` under its `rootDir`. `package.json` `main`, `bin` and script commands that run `node <path>` go through this map.
   - Vite: the `index.html` at the config's `root` (default the config's directory) is read and its `<script type="module" src>` entries become the entry points.
   - An entry point that maps to no tracked source becomes an `unresolved_entry` diagnostic and is listed in the `confirm-structure` task.

   After step 6, entry points are followed through import edges and every reached file gets a `part_of` edge, so one file can be part of several deployables.
5. **Parse** (`parse/`). Only files whose content hash or parser version changed. One tree-sitter query set per language captures definitions (class, function, method, arrow-function const, React component = capitalised function returning JSX, interface, type alias), imports, re-exports, call sites, literal file reads (`readFileSync("…")`, `open("…")`) and docstrings or JSDoc.
6. **Resolve** (`resolve.py`).
   - **Imports.** Relative paths, `tsconfig` `paths` aliases, Python packages from `src/` layout and `__init__.py`, and uv path sources. Re-exports (`export … from`, names imported into an `__init__.py` or `index.ts`) are followed to the defining file.
   - **Calls.** Bound when the callee is defined in the same file, imported by name, or is `self.x` / `this.x` on the enclosing class, after checking local scope: a parameter or local variable with the same name shadows the binding. Confidence is 1.0 for direct binds and 0.6 for `self`/`this`. Anything ambiguous gets no edge and an `ambiguous_call` diagnostic count on the file.
   - **Tests.** A test case links to every symbol it calls (resolved) with `source=treesitter`, and to every module it imports with lower confidence. A file name match (`x.test.ts` to `x.ts`, `test_x.py` to `x.py`) adds `source=naming`. A literal read of a tracked file links the test to that file. A test file with no links gets an `unmatched_test` diagnostic.
7. **Docs** (`docs.py`). Title from the first heading. A `mentions` edge goes to any node whose path or qualified name appears in backticks or a link.
8. **Tasks** (`tasks.py`). Regenerate tasks whose input hash changed.

Resolution reruns across the workspace whenever the shortcut in step 2 does not apply. Deliverable 2 measures enumeration on xenota and deliverable 14 measures the whole scan; if resolution is too slow, limit it to changed files and their importers.

## Judgement task protocol

The CLI never calls a model. Tasks are the contract with the calling agent.

| Kind | Node | Inputs given to the agent | Answer |
|---|---|---|---|
| `summarise-files` | a group | up to ~15 files in it: path, content hash, symbol outline, docstrings, imports | per file: `summary` (1 to 3 sentences) |
| `summarise-group` | group, package | child summaries, child names | `summary`, optional `display_name`, `display_kind` from an allowed list |
| `confirm-structure` | workspace | detected deployables with evidence and entry points, unresolved entries, top-level directories without a manifest | the corrected deployables (name, display kind, source entry points) and packages (name, directory) |
| `summarise-deployable` | deployable | entry points, member package and group summaries | `summary` |
| `summarise-workspace` | workspace | deployable and package summaries, README head | `summary` |

Rules:

- **Per-file cache.** `summarise-files` batches files only to save the agent round trips. Each file's answer is stored and cached separately, keyed by `(file content hash, protocol version)`. Adding a file to a folder opens a task for that file only.
- **Bottom-up.** `summarise-group` waits for its files and subgroups. `summarise-deployable` waits for `confirm-structure`. A parent reopens only when a child's summary text changes, not when a child is resubmitted unchanged.
- **Stale answers.** Every brief includes the task's `input_hash`, and the answer must echo it. If the inputs changed since the brief was issued, `submit` rejects the answer and tells the agent to fetch the task again.
- **Atomic submit.** Accepting an answer stores it, marks the task done and opens newly unblocked tasks in one transaction. Submitting the same answer twice is a no-op. Accepting `confirm-structure` writes `structure.json` and reruns steps 4 and 6.

Commands:

- `cbi tasks [--kind K] [--limit N] [--json]` lists open tasks.
- `cbi task <id>` prints the brief: what to do, which files to read, the `input_hash`, and the JSON Schema of the answer.
- `cbi submit <id> [FILE|-]` validates and stores the answer. Errors name the JSON path and the problem, and exit with code 2.

The answer cache is `~/.cache/codebase-inspector/answers.db` (moved with `CBI_CACHE_DIR`). Before opening a task, the scan fills it from the cache when every input is cached. Bumping the protocol version invalidates old answers.

Validation is hand-written checks against a small dict per task kind (required keys, types, lengths, allowed `display_kind` values). The schema printed in the brief is generated from the same dict.

## Agent interface

`cbi prime` reads `.cbi/` and prints one of three guides, each under ~60 lines:

- **Not initialised.** What the tool is, `cbi init`, `cbi scan`.
- **Tasks pending.** The task loop with one worked example, the count by kind, and a note that independent tasks can go to subagents.
- **Complete.** The query commands with examples on this repo's real node names, and the ingest commands for this repo's test runners (node:test, vitest, pytest detected from manifests).

`--help` on every subcommand states inputs, output shape and exit codes. Read commands: `search`, `show`, `tests-for`, `tasks`, `task`, `status`; all take `--json`.

## Test ingest

`cbi ingest <file>...` detects the format by content:

- lcov (`SF:` / `DA:` records): line coverage per file, rolled up to symbols by line range.
- coverage.py JSON (`meta.format`): line coverage. When `contexts` are present, `tests` edges go from each test case to the symbols covering its lines, with `source=coverage` and confidence 1.0.
- JUnit XML: `testcase` `file`/`classname`/`name` matched to test-case nodes by file and name.

Paths in artifacts must name tracked source files. When tests ran on compiled output, the coverage has to be remapped through source maps before or during collection: path rewriting alone is wrong because compilation moves lines (orchestra's service config sets `removeComments`). `cbi prime` prints the per-repo commands. For orchestra each suite is compiled with source maps into a directory outside the repo and run with Node's source-map support, roughly:

```
npx tsc -p electron/tsconfig.test.json --sourceMap --outDir "$OUT/electron"
node --enable-source-maps --test --experimental-test-coverage \
  --test-reporter=lcov --test-reporter-destination="$OUT/electron.lcov" \
  --test-reporter=junit --test-reporter-destination="$OUT/electron.junit.xml" \
  "$OUT/electron/**/*.test.js"
```

with the same for the renderer and service suites (service with `NODE_ENV=test`). Deliverable 9 verifies that Node reports source paths and lines this way. If it does not, ingest maps through the emitted `.js.map` files itself. Any path still not matching a tracked file is an `unmapped_coverage` diagnostic, never silently dropped.

## Viewer (`cbi build`)

Output: `.cbi/viewer/` with `index.html`, `app.js`, `style.css`, `vendor/minisearch.min.js`, and `data/`.

Data is written as JavaScript files that call a global loader (`cbiLoad("tree", {...})`), because `<script>` tags load from `file://` where `fetch()` does not.

- `data/tree.js`: every node down to file level (id, parent, display_kind, name, loc, test status, short summary), edges rolled up to file level and above, `part_of` membership per deployable, and a chunk manifest mapping every symbol ID to its chunk. Budget: under 3 MB for xenota, checked in deliverable 8 with a synthetic model of xenota's size.
- `data/f-<n>.js`: symbol nodes, symbol edges and full summaries, chunked by group, each under ~500 KB. A symbol-level edge is written into the chunks of both endpoints, so callers in other groups show up.
- `data/search.js`: prebuilt MiniSearch index over every node, storing only id, name, display_kind and path. It loads after first paint; until it arrives, search falls back to a name match over `tree.js`.

Rollups are computed at build time. An edge between two symbols counts towards each ancestor pair up to their lowest common ancestor, so the UI never aggregates.

Layout: a breadcrumb and search box on top. Chains of single-child folders show as one breadcrumb step (`nucleus/src/nucleus`). The left side lists the focused node's children with display kind, LOC and a test overlay chip. A deployable's children are the folders containing its `part_of` files, with counts that do not double-count shared files. The right side shows the selected node's detail: summary, signature, docstring, path as a `vscode://file/...:line` link, incoming and outgoing relationships at the current level, linked tests or tested code, and diagnostics. Low-confidence edges are hidden by default.

Test overlay modes: static links (has tests / no tests), coverage percentage (when ingested), last result (pass / fail / skipped). A legend states which mode and source is showing.

## Security and failure handling

- The CLI only reads the target through `git` and file reads, and only writes under `.cbi/` (or `--out`) and the shared cache.
- `git` is invoked with fixed argv lists, never through a shell.
- Parse errors in one file become a `parse_error` diagnostic and the scan continues.
- Submitted answers are data: they are stored as text and rendered in the viewer with `textContent`, never as HTML, because an agent could paste content from the repo.
- `.cbi/` is created with its own `.gitignore` containing `*`.

## Test strategy

- Unit tests per module against small synthetic repos built by fixtures (`git init` in a temp dir, so submodule cases are real).
- Golden tests: scan a fixture and compare a sorted dump of nodes and edges to a checked-in expected file.
- Acceptance runs on orchestra, lms and xenota through `scripts/acceptance.sh <repo>`, which prints node counts by kind, timings, diagnostics and the A-criteria checks. Run by hand, not in CI, because they read repos outside this one.
- Viewer: a Playwright smoke script loads the built viewer from `file://`, searches, drills to a method and toggles the overlay.

## Deferred decisions

- SCIP ingestion for precise calls.
- Treemap and graph views.
- Compose resources and a `config.toml`.
- Snapshot storage per commit for PRD-02.
- Serving the viewer, if change review or quizzing needs it.

# Architecture

Covers PRD-01 to PRD-07 (`docs/prd-0*.md`). Living document: update it when a decision changes. The reasons behind the significant decisions are in the ADR register, `docs/adr/README.md`. Review findings that shaped it are recorded in `docs/planning/decision-log.md`.

## Constraints from the PRD

- Deterministic CLI, no LLM calls, never executes target code. Agents supply judgement through a task protocol.
- Works on any repo without installing its dependencies or building it.
- sample-monorepo scale: ~1.6k code files, ~30k symbols, ~100k edges, cold scan under 60 s, no-change rescan under 10 s, viewer first paint under 2 s.
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
  data.py                 schema and table-use extraction
  system_views.py         database and endpoint viewer projections
  build.py                viewer export
  viewer/                 index.html, app.js, style.css, vendor/minisearch.min.js (copied by build)
tests/
  fixtures/               builders for small synthetic repos (one per language + a submodule case)
  test_*.py
scripts/acceptance.sh     runs the acceptance checks against a sample repo
.agent/skills/            project skills (created when the first one is added)
docs/
```

## Data model

One SQLite file per mapped repo at `.cbi/model.db`.

**nodes**: `id` (text, primary key), `parent_id`, `kind`, `display_kind`, `name`, `workspace_id`, `path`, `start_line`, `end_line`, `lang`, `loc`, `content_hash`, `signature`, `doc`, `summary`, `summary_source` (`agent`, `docstring`, null), `attrs` (JSON).

- `kind` is the internal type: `workspace`, `deployable`, `package`, `group`, `file`, `symbol`, `test`, `doc`, `external`, `table`, `column`.
- `display_kind` is what users and agents see: `class`, `method`, `function`, `component`, `interface`, `module`, `folder`, `skill`, `test case`, `doc collection`, and so on. The viewer and CLI text output only ever print `display_kind`. `--json` includes both.
- Workspace `attrs` hold `remote`, `pinned_commit`, `checked_out_commit`, `drift` and `initialised`.

**edges**: `src`, `dst`, `kind` (`imports`, `calls`, `tests`, `part_of`, `depends_on`, `mentions`, `pins`, `foreign_key`, `reads_table`, `writes_table`), `source` (`treesitter`, `manifest`, `naming`, `coverage`, `agent`, `data`), `confidence` (0 to 1), `weight`. Containment is `parent_id`, not an edge.

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

- workspace: the normalised remote, `host/owner/repo` lowercased, with scheme, user, port and `.git` removed. `git@github.com:example/sample-lib.git` and `https://github.com/example/sample-lib` both become `github.com/example/sample-lib`. With no remote: `local:<dirname>`. A local path or `file://` remote also gives `local:<repo dir name>`, so IDs do not depend on the machine. A relative `.gitmodules` URL (`../lib.git`) is resolved against the parent's `origin` first. Commits are data on the workspace node, never part of the ID, so the same submodule in two superprojects shares IDs.
- file / doc: `<workspace>:<repo-relative path>`.
- symbol / test case: `<file id>#<qualified name>` (`#DeviceRegistry.revoke`). Two definitions with the same qualified name get a suffix from the first 8 hex characters of a hash of their signature text; only definitions with identical signatures fall back to `~2`, `~3` by source order.
- group: `<workspace>:<dir>/`. deployable and package: `<workspace>:deployable:<name>` / `:package:<name>`. A renamed deployable keeps its old ID in `structure.json` as `id`, so the agent's rename does not change it.

## Pipeline (`cbi scan`)

1. **Enumerate** (`files.py`). `git ls-files` per workspace gives the tracked path list; `git submodule status` gives submodules, pinned commit and drift. Content identity comes from the working tree, not the index: each file is `stat`ed, and only when `mtime_ns` or `size` differ from `file_state` is it read and hashed (sha1 of bytes). This catches unstaged edits. Tracked symlinks are recorded as file nodes and never followed. `.cbi/ignore` (gitignore syntax) filters paths.
2. **No-change shortcut.** If no file was added, removed or rehashed to a new value, the ignore file and `structure.json` are unchanged, every workspace's checked-out commit is unchanged, and the parser version is unchanged, the scan stops here.
3. **Classify.** By extension and path: code (Python, TS, TSX, JS), doc (markdown), test (by name pattern and framework), other (file node only). `init` writes `.cbi/ignore` from heuristics: directories named `fixtures`, `evals`, `test-data`, `dist*`, `build`; files with minified-looking lines; directories over 200 files that are more than 90% data (json, txt, csv, jsonl). Doc collapse is presentation only: a directory over 100 files where at most 10% are code and at least half are markdown becomes a `doc collection` node (the outermost such directory wins). The first rule, at least 90% markdown, missed sample-monorepo's `docs/research` at 89.9%, because research artefacts (`.out`, `.log`, `.jsonl`) fill the rest. Everything inside is still enumerated, parsed if code, and searchable; the viewer loads its children on demand.
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

Resolution reruns across the workspace whenever the shortcut in step 2 does not apply. Deliverable 2 measures enumeration on sample-monorepo and deliverable 14 measures the whole scan; if resolution is too slow, limit it to changed files and their importers.

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

Paths in artifacts must name tracked source files. When tests ran on compiled output, the coverage has to be remapped through source maps before or during collection: path rewriting alone is wrong because compilation moves lines (sample-desktop's service config sets `removeComments`). `cbi prime` prints the per-repo commands. For sample-desktop each suite is compiled with source maps into a directory outside the repo and run with Node's source-map support, roughly:

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

- `data/tree.js`: every node down to file level (id, parent, display_kind, name, loc, test status, short summary), edges rolled up to file level and above, `part_of` membership per deployable, and a chunk manifest mapping every symbol ID to its chunk. Budget: under 3 MB for sample-monorepo, checked in deliverable 8 with a synthetic model of sample-monorepo's size.
- `data/f-<n>.js`: symbol nodes, symbol edges and full summaries, chunked by group, each under ~500 KB. A symbol-level edge is written into the chunks of both endpoints, so callers in other groups show up.
- `data/search.js`: prebuilt MiniSearch index over every node, storing only id, name, display_kind and path. It loads after first paint; until it arrives, search falls back to a name match over `tree.js`.

Rollups are computed at build time. An edge between two symbols counts towards each ancestor pair up to their lowest common ancestor, so the UI never aggregates.

Layout: a breadcrumb and search box on top. Chains of single-child folders show as one breadcrumb step (`pkg/src/pkg`). The left side lists the focused node's children with display kind, LOC and a test overlay chip. A deployable's children are the folders containing its `part_of` files, with counts that do not double-count shared files. The right side shows the selected node's detail: summary, signature, docstring, path as a `vscode://file/...:line` link, incoming and outgoing relationships at the current level, linked tests or tested code, and diagnostics. Low-confidence edges are hidden by default.

Test overlay modes: static links (has tests / no tests), coverage percentage (when ingested), last result (pass / fail / skipped). A legend states which mode and source is showing.

## Concept map (PRD-02)

Covers `docs/prd-02-concept-map.md`. The mockup on branch `d08-mockup` (`mockup/`) is the reference for the data shapes and the viewer: `sample-desktop-concepts.json` is a real agent answer, `derive.py` holds the checks, and `app.js` is the starting point for the real viewer.

### Agent-authored files

Agent answers that shape the map live in `.cbi/` as JSON next to `structure.json`, applied on every scan, written only by accepted task answers and editable by hand:

- `.cbi/concepts.json`: `{summary, concepts: [{id, name, summary, role, children?, files?}], externals: [{id, name, summary, kind}], relationships: [{from, to, label, via?, at?, minor?, basis?}]}`. Only leaf concepts have `files` (repo-relative paths). `role` is one of `ui`, `app`, `service`, `core`, `data`. External `kind` is one of `platform`, `cli`, `saas`, `terminal`, `storage` (`os` is accepted as `terminal`). A relationship whose `to` or `from` is an external is an integration point and needs `via`, the mechanism (free text, short: `HTTP`, `exec CLI`, `IPC`, `security CLI`; `mechanism` is accepted as an alias), and `at`, where it happens (`path:function`). `minor: true` marks a relationship drawn lighter.
- `.cbi/screens.json`: `{screens: [{id, name, device, root: region}]}` where a region is `{id, label?, component?, layout?, text?, style?, children?}`. `component` names either a parsed component or a detected screen template file. `layout` is `row`, `column` or `grid`; `style` is a short list of hints (`card`, `list`, `button`, `badge`, `input`, `heading`, `muted`). `text` is static text from the source template; dynamic values are written as `{expr}` and rendered as grey placeholders.

Keeping these as files rather than only in the database means a rescan never loses them, a person can edit them, and the change-review increment can diff them.

### Model

- Concepts are nodes with `kind = 'concept'`, `display_kind` from the role ("interface", "service"), `parent_id` pointing at the parent concept or the workspace. The concept tree is a second hierarchy beside the file tree; the file tree stays for the CLI and the drawer.
- `owns` edges go from a leaf concept to each file it owns. A symbol's concept is its file's owner.
- Externals reuse `kind = 'external'` with `display_kind` from their kind.
- `relates` edges carry `attrs = {label, mechanism?, basis?, integration: bool}`. The code edges behind a relationship are found at build time by rolling `imports` and `calls` edges up to the owning leaves and their ancestors, and stored in the viewer data so an arrow can list the calls behind it.
- Env vars are nodes with `kind = 'env'`, `display_kind = 'env var'`, id `<workspace>:env:<NAME>`, and `reads_env` edges from the reading symbol (or file, at top level) with `attrs = {default?}`. Declarations (`.env.example`, `.env.sample`, compose `environment`, `wrangler.toml` `[vars]`) add `declared_in` to the env node's attrs. Files named `.env` or `.env.*` other than the example and sample forms are never opened.
- Screens are stored as one JSON blob per screen in node attrs (`kind = 'screen'`, parent = the UI concept that owns its entry component or template), and each region with a `component` gets a `sketches` edge from the screen to that component or template file.

### Tasks

Two new kinds join the protocol; the rules for stale answers, atomic submit and caching are unchanged.

| Kind | Opens when | Inputs | Checks on submit |
|---|---|---|---|
| `define-concepts` | `confirm-structure` is done | workspace summary; deployables and packages with summaries; every code and test file with its summary and symbol outline; file-level import and call pairs with counts; detected env vars; on a rescan, the current `concepts.json` and the list of unowned or changed files only | every code and test file owned by exactly one leaf; only leaves own files; ids unique; roles and kinds from the lists; every relationship end exists; every leaf-to-leaf import or call pair across concepts covered by a relationship between the two leaves or any of their ancestors; integration points have a mechanism; at most 9 children per concept (warning) |
| `sketch-screens` | `define-concepts` is done and the repo has parsed UI components or detected screen templates | UI concepts and their components; each component's template or JSX body, props signature and render edges; Vue routes; HTML, Jinja, Django and Razor screen templates with inferred routes and includes; candidate screen entry points | every region `component` is a real component or detected screen template; every component owned by a UI concept and every detected screen template appears in at least one screen or is listed in `unsketched` with a reason |

`cbi task` prints the check list with the brief, and a rejected submit lists every failing check, not just the first. The `define-concepts` brief for a large repo may exceed one agent's context; splitting per deployable is deferred until sample-monorepo needs it (PRD-02 open question).

`confirm-structure` and `summarise-deployable` from PRD-01 are still needed and come first.

### Env var extraction

Part of the parsers, stored as facts like calls and reads:

- TypeScript and JavaScript: `process.env.X`, `process.env["X"]`, `import.meta.env.X`, with a default from `?? "..."` or `|| "..."`. `...process.env` spreads are recorded as a whole-environment pass-through on the file.
- Python: `os.environ["X"]`, `os.environ.get("X", default)`, `os.getenv("X", default)`, and `environ` imported from `os`.
- Only names matching `[A-Z_][A-Z0-9_]*` are kept.

### Viewer

The concept viewer replaces the bare list viewer from PRD-01 deliverable 3. It is built from the mockup's `app.js`, rewired to read `cbi build` output:

- `data/concepts.js`: concept tree, externals, relationships with their rolled-up code edges, env vars per concept, screens, and per-leaf symbol lists with calls (including `via: jsx` renders), test counts and env chips. Small enough to load at once for sample-desktop; for sample-monorepo the per-leaf symbol lists move to the existing chunk files.
- Layout with elkjs 0.12 (`elk.bundled.js`, vendored, about 1.6 MB) running layered layout per view. Zoom and pan change the SVG `viewBox`, so text stays sharp.
- Colours come from role and kind classes with light and dark values on `:root`; the key is built from the roles and kinds present in the current view.
- When the model has no concepts yet, the viewer shows deployables, packages and externals as boxes with `depends_on` edges, so a fresh scan still opens on a diagram (PRD-02 B4).

Model text is still set with `textContent` only. Wireframe text is data, rendered into plain elements with class names from the style hints, never as HTML.

## System views (PRD-05)

Covers `docs/prd-05-system-views.md`.

- **Schema facts.** `data.py` derives tables, columns, keys and foreign keys from SQL migrations and supported ORM declarations. Repeated declarations merge by database table name and retain every source location. A scan replaces only edges with `source = 'data'` and table and column nodes.
- **Code access.** Literal SQL and recognised ORM chains produce `reads_table` and `writes_table` edges from the innermost enclosing symbol, or from the file when no symbol contains the use. The edge attrs retain source path, line and extraction form. Extraction reads text only and never imports project code or connects to a database.
- **Routes.** Server routes remain facts on handler nodes. Next.js app-router files add routes from exported HTTP verb functions and their file path. Existing `http_calls` edges link callers to handlers.
- **Build projections.** `system_views.py` writes layout-free `data/database.js` and `data/endpoints.js`. Endpoint notes use existing handler, doc and file summaries. Endpoint downstream code follows resolved calls to a bounded depth, and touched tables reuse the table-use edges.
- **Viewer.** Concept map, Database and API endpoints are hash-addressed top-level tabs. The database layout, positions and relationship routes are calculated only in browser code. Cross-view links carry an origin tab and selection so the Back chip, browser back, Backspace and Esc follow the concept-map navigation rules.
- **Desktop.** The Electron shell stores the complete viewer hash and therefore restores system tabs and selections without a second database or endpoint implementation.

## Desktop app (PRD-03)

Covers `docs/prd-03-desktop-app.md`. Decided in ADRs (`docs/adr/`): a thin Electron shell over the installed `cbi` CLI.

- **Layout.** `app/` holds the Electron app (TypeScript, its own `package.json`, electron-builder for an unsigned arm64 `.app`, following sample-desktop's packaging). The Python package is unchanged; the app depends on `cbi` being on PATH or set in its settings.
- **Engine.** The app never reads or writes the model itself. It runs `cbi` with fixed argv (no shell): `init`, `scan`, `build`, `status --json`, `worktrees --json`, `scan --ref`. The window shows the viewer folder that `cbi build` writes, so the app and the static viewer are the same code.
- **Projects.** Recent projects live in the app's `userData` as JSON (path, display name, pinned, last opened, last view). A project is keyed by its main worktree (`git rev-parse --git-common-dir`).
- **Versions.** Worktrees are mapped in place in their own `.cbi/`. Branches and commits without a worktree are mapped with `cbi scan --ref`, which lists files with `git ls-tree` and reads blobs through one `git cat-file --batch` process into `<model dir>/refs/<commit>/model.db`. A commit's model is immutable and reused. No command changes a working tree, ref or stash.
- **Freshness.** The app watches the open worktree (Node `fs.watch`, debounced) and `.cbi/model.db`; a change triggers `cbi scan` then `cbi build`, and the viewer reloads keeping its URL hash, which holds the view state.
- **Opening in a state.** `cbi open` resolves the repository and the requested version, then hands the app a `cbi://open?repo=<path>&ref=<ref>&node=<id>` link (or `&compare=<base>..<head>`) with macOS `open`. The app registers the scheme with `app.setAsDefaultProtocolClient` and handles `open-url`; it validates every parameter (the repo must be a git repository on disk, refs must resolve) and refuses anything else with a visible message. A link opening while the app runs switches the existing window and leaves a Back chip.

## Change review (PRD-04)

Covers `docs/prd-04-change-review.md`.

- **Inputs.** Two models: a worktree's, or a ref model from `cbi scan --ref`. A pull request resolves to its base and head commits through `gh pr view --json`.
- **Diff engine.** `src/cbi/diff.py` compares two models by stable IDs and produces one JSON change list (the shape is documented in `cbi diff --help`): concepts (added, removed, renamed, split, merged, files moved), relationships, integration points, deployables and packages, env vars, symbols, tests and untested changes, component renders. A file or symbol whose content hash is unchanged but whose path or qualified name moved is a move.
- **New code without concepts.** Files the base's concepts do not own get a provisional owner (the concept owning most of their import neighbours, else the folder's majority owner), marked provisional, and a `define-concepts` task opens for just those files.
- **Text.** `cbi diff` renders the change list as text, Markdown or JSON. `cbi review` writes `review.md`: the `cbi://` link, summary counts, a Mermaid `flowchart LR` of changed concepts and their direct neighbours (classes for added, removed and changed), per-concept details, untested changes and changed integration points.
- **Narrative.** A `summarise-change` task takes the change list as input and returns a short narrative, cached by the pair of commits.
- **Images.** A static `render.html` built from the viewer code takes a state and a change list, lays out with elkjs, and marks when it is ready. `cbi review` runs headless system Chrome on it: `--screenshot` for `before.png` and `after.png`, and the page writes the SVG markup for `before.svg` and `after.svg`. Without Chrome or Chromium the images are skipped with a message.
- **Posting.** `--post` runs `gh pr comment`, and on later runs finds its own earlier comment by a hidden marker and edits it with `gh api`.
- **Viewer.** Comparison mode reads `data/diff.js` written by `cbi build --compare`: marks on boxes and edges, a changes panel, a base/head toggle, and code diffs in the drawer for changed functions (the build embeds the two versions of each changed function's source).

## Architecture history (PRD-06)

Covers `docs/prd-06-architecture-history.md`. Decided in ADR-0021 and ADR-0022.

- **Points.** `src/cbi/history.py` lists history points with `git log --first-parent --merges` on the default branch (falling back to `--first-parent` without `--merges` when the repo has no merge commits), oldest first, from `--since`. PR numbers come from merge messages (`Merge pull request #N`, `(#N)`) and, when `gh` is on PATH, `gh pr list --state merged --json number,mergeCommit,title` (read-only, cached in the model folder).
- **Models.** Each point is scanned with the existing ref scanning into `refs/<sha>/model.db` (immutable, reused). Parsing is content-addressed by blob id across refs, so unchanged files are not reparsed.
- **Projection.** `history.project_concepts(current, point_model)` assigns each file at a point to a current leaf concept: same file id, else nearest surviving neighbour by folder then by import neighbours, marked provisional. Concept nodes with no files at a point are omitted there.
- **Entries.** Each entry is `diff.compare(previous_point, point)` (PRD-04) on the projected models, stored as JSON in `history/<sha>.json` beside the models. Empty diffs are not entries. A `history/index.json` lists entries with date, sha, PR, author and change counts.
- **Outputs.** `cbi history` renders entries as text, Markdown or JSON; `--write` regenerates `.cbi/CHANGELOG-ARCHITECTURE.md` from the index. `cbi build --history` writes `data/history.js` (the index plus per-entry marks) for the viewer timeline; the desktop app calls `cbi history --json` and `cbi build --history` in the background (PRD-03 quiet scans).
- **Narratives.** `cbi history --narrate <sha>` opens a `summarise-change` task for that entry's pair; answers are cached per pair and shown when present.

## Team mode (PRD-07)

Covers `docs/prd-07-team-mode.md`; decided in ADR-0023.

- **Opt-in.** `.cbi/team.toml` marks a team repo (`check = "fail" | "warn"`, `brief_budget`). `cbi team init` writes it, rewrites `.cbi/.gitignore` to `model.db*`, `viewer/`, `refs/`, `reviews/`, `history/`, `ignore.local`, appends `.cbi/answers.jsonl linguist-generated=true` to `.gitattributes`, and exports answers. It prints, never runs, git commands.
- **Answers file.** `src/cbi/team.py` keeps `.cbi/answers.jsonl` in sync with the shared answer cache for this repo's keys: written after every accepted answer when `team.toml` exists, sorted by (kind, key), one compact JSON object per line, so concurrent branches add different lines.
- **Import.** At the start of task generation, a team repo loads `answers.jsonl` into the answer cache, so tasks whose input is covered never open.
- **Check.** `cbi check [--base REF] [--format text|github]` runs scan and task generation in memory, finds files changed since the merge base, and reports: changed code or test files without a summary; files without a concept owner when concepts exist; JSON files failing their task checks; `answers.jsonl` entries missing for accepted answers; answer text matching secret patterns. Exit 1 on any, unless `check = "warn"`.
- **Opened tasks on a branch** are limited to changed files because unchanged files are already answered from the committed file.

## Decisions made during implementation

Recorded during the build; the code is the reference where these and earlier sections differ.

- **Doc collapse** (d02): a directory over 100 files with at most 10% code and at least half markdown becomes a `doc collection`; sample-monorepo's `docs/research` (89.9% markdown) collapses inside `docs/`.
- **tree-sitter** (d03): pinned to `>=0.25,<0.26`; 0.26.0 segfaults on node access after repeated parses.
- **Parse facts** (d04): parse output is stored in a `facts` table so resolution reruns without reparsing. A file with no ES exports offers all top-level names (CommonJS). `ambiguous_call` counts only calls with several candidates.
- **structure.json** (d05): `deployables: [{id?, name, display_kind?, entry_points?, remove?}]`, `packages: [{id?, name, directory?, remove?}]`. Vite deployables are named `<root dir>-web`, script deployables after the script. Every `package.json` below the root is a package; files get `part_of` to their deepest package. Package-name imports resolve within their own workspace; `exports` maps are not read.
- **Query** (d06): `query.py` owns search, show, tests-for and status; `tests-for --json` is `{node, tests, coverage}`; an ambiguous name lists candidates and exits 1.
- **Tasks** (d07): `summarise-group` display kinds are folder, module, component, library, skill, repertoire, tests, scripts, config, examples, docs. Docs-only folders get no task. Group and workspace answers are cached by a hash of child names, kinds and summaries plus README, never by IDs. Packages are linked to files by `part_of`, not parenthood, so they get no summary task yet; the concept map replaces package summaries.
- **Docs** (d10): titles from front matter or the first heading; search body capped at 20,000 characters; `mentions` by path or link at 1.0, by unique qualified name at 0.8, bare names ignored. The minified rule needs more than half a JS or CSS file's bytes on lines of 1,000+ characters. FTS rows are updated by rowid (by id scanned the whole table: 595 s on sample-monorepo, now 21 s).
- **Python** (d13): tests that do not mirror the source tree match the single `<stem>.py` in their own pyproject. `import a.b` binds the module. A `nodes_file` index keeps sample-monorepo's scan from spending about 50 s on node lookups.
- **Deploy manifests** (d15): a Docker `COPY` destination is matched to a tracked file by dropping leading directories; compose files in one directory merge; image-only services are externals `<ws>:service:<name>`.
- **Renders** (d16): `edges.attrs` (JSON) added; calls from JSX tags and `createElement(X)` carry `{"via": "jsx"}` and print as renders.

## Security and failure handling

- The CLI only reads the target through `git` and file reads, and only writes under `.cbi/` (or `--out`) and the shared cache.
- `git` is invoked with fixed argv lists, never through a shell.
- Parse errors in one file become a `parse_error` diagnostic and the scan continues.
- Submitted answers are data: they are stored as text and rendered in the viewer with `textContent`, never as HTML, because an agent could paste content from the repo.
- `.cbi/` is created with its own `.gitignore` containing `*`.

## Test strategy

- Unit tests per module against small synthetic repos built by fixtures (`git init` in a temp dir, so submodule cases are real).
- Golden tests: scan a fixture and compare a sorted dump of nodes and edges to a checked-in expected file.
- Acceptance runs on sample-desktop, sample-apps and sample-monorepo through `scripts/acceptance.sh <repo> <out-dir>`, which prints node counts by kind, timings, diagnostics and the A-criteria checks. Run by hand, not in CI, because they read repos outside this one.
- Viewer: a Playwright smoke script loads the built viewer from `file://`, searches, drills to a method and toggles the overlay.

## Deferred decisions

- SCIP ingestion for precise calls.
- Treemap view.
- Compose resources and a `config.toml`.
- Snapshot storage per commit for PRD-02.
- Serving the viewer, if change review or quizzing needs it.

# Architecture

Covers PRD-01 (`docs/prd-01-orientation-map.md`). Living document: update it when a decision changes.

## Constraints from the PRD

- Deterministic CLI, no LLM calls, never executes target code. Agents supply judgement through a task protocol.
- Works on any repo without installing its dependencies or building it.
- xenota scale: ~1.6k code files, ~30k symbols, ~100k edges, cold scan under 60 s, viewer first paint under 2 s.
- Viewer opens from `file://` with no server.
- Leaves tracked files in the target untouched.

## Runtime and tools

| Choice | Version | Why |
|---|---|---|
| Python | >= 3.11 (developed on 3.13) | Agent skills already ship Python. coverage.py formats are native. |
| uv | 0.12 | Install with `uv tool install`, so `cbi` is on PATH with an isolated environment. |
| tree-sitter (py-tree-sitter) | 0.26 | Incremental-safe, error-tolerant parsing for every language we need. |
| tree-sitter-language-pack | 1.21 | Prebuilt grammars for Python, TypeScript, TSX, JavaScript and 150+ others in one wheel. Checked: `get_parser("tsx")` and `("python")` work on 3.13. |
| SQLite (stdlib `sqlite3`) with FTS5 | 3.53 on macOS | The model store. Gives the CLI fast `show`/`tests-for` queries and full-text `search` with no extra dependency. FTS5 checked present. |
| argparse (stdlib) | | Enough for a dozen subcommands. Help text is the agent's documentation, so it is written by hand either way. |
| pytest | latest | Tests for the mapper. |
| Viewer: plain JS, no build step | | One static folder. Libraries are vendored minified files, so nothing to install. |
| MiniSearch | 7.2 | Small client-side full-text index that can be prebuilt and loaded with `loadJSON`. Chosen over FlexSearch for the simpler API and prebuilt index support. |
| Cytoscape.js | 3.34 | Node-link view of a focused node's children and their rolled-up edges. Built-in layouts only. ELK (`elkjs`) is added only if those layouts prove unreadable. |
| d3-hierarchy | 3.x (from d3 7.9) | Squarified treemap for the children panel. |

Alternatives rejected: SCIP indexers (need each repo's dependencies installed, see PRD non-goals); a TypeScript mapper on web-tree-sitter (WASM grammar management, nothing else in the skill stack uses Node); a served viewer (no PRD-01 need, adds a process).

## Repository layout

```
pyproject.toml            package "codebase-inspector", script "cbi"
src/cbi/
  cli.py                  argparse entry, one function per subcommand, help text
  prime.py                state-aware agent guide
  store.py                SQLite schema, migrations, queries
  files.py                git enumeration, submodules, ignore rules
  manifests.py            deployable / package / resource detection
  parse/
    python.py             tree-sitter queries + symbol/import/call extraction
    typescript.py         TS, TSX, JS
  resolve.py              import and call resolution, test linking
  docs.py                 markdown nodes, collapse, mentions
  tasks.py                judgement task generation, validation, cache
  ingest.py               lcov, coverage.py JSON, JUnit XML
  build.py                viewer export
  viewer/                 index.html, app.js, style.css, vendor/*.min.js (copied by build)
tests/
  fixtures/               small synthetic repos (one per language + a submodule case)
  test_*.py
.claude/skills/           project skills; .agent/skills -> ../.claude/skills
docs/
```

## Data model

One SQLite file per mapped repo at `.cbi/model.db`.

**nodes**: `id` (text, primary key), `parent_id`, `kind`, `display_kind`, `name`, `workspace_id`, `path`, `start_line`, `end_line`, `lang`, `loc`, `content_hash`, `signature`, `doc`, `summary`, `summary_source` (`agent`, `docstring`, null), `attrs` (JSON).

- `kind` is the internal type: `workspace`, `deployable`, `package`, `group`, `file`, `symbol`, `test`, `doc`, `resource`, `external`.
- `display_kind` is what users and agents see: `class`, `method`, `function`, `component`, `interface`, `module`, `folder`, `skill`, `test case`, and so on. The viewer and CLI text output only ever print `display_kind`. `--json` includes both.

**edges**: `src`, `dst`, `kind` (`imports`, `calls`, `tests`, `part_of`, `depends_on`, `mentions`, `pins`), `source` (`treesitter`, `manifest`, `naming`, `coverage`, `agent`), `confidence` (0 to 1), `weight`. Containment is `parent_id`, not an edge.

**coverage**: `node_id`, `lines_total`, `lines_hit`, `source_file`. **results**: `test_node_id`, `status`, `duration_ms`, `source_file`.

**tasks**: `id`, `kind`, `node_id`, `input_hash`, `state` (`blocked`, `open`, `done`), `depends_on` (JSON list).

**search**: FTS5 table over `name`, `display_kind`, `path`, `signature`, `doc`, `summary`.

### Node IDs

IDs are stable across scans and machines, which PRD-02 needs for diffing.

- workspace: normalised remote URL (`github.com/blackwood-systems/lms`), or `local:<dirname>` with no remote.
- file / doc: `<workspace>:<repo-relative path>`.
- symbol / test case: `<file id>#<qualified name>` (`#DeviceRegistry.revoke`). Overloads and duplicate names get `~2`, `~3` by source order.
- group: `<workspace>:<dir>/`. deployable and package: `<workspace>:deployable:<name>` / `:package:<name>`.

Submodules are keyed by remote, so xenota's and xcd's xenon share IDs.

## Pipeline (`cbi scan`)

1. **Enumerate** (`files.py`). `git ls-files -s` per workspace gives path and blob hash in one call; `git submodule status` gives submodules, pinned commit and drift. Tracked symlinks are recorded as file nodes and never followed. `.cbi/ignore` (gitignore syntax) filters paths.
2. **Classify.** By extension and path: code (Python, TS, TSX, JS), doc (markdown), test (by name pattern and framework), other (file node only). `init` writes `.cbi/ignore` from heuristics: directories named `fixtures`, `evals`, `test-data`, `dist*`, `build`; files with minified-looking lines; directories over 200 files that are more than 90% data (json, txt, csv, jsonl). It also lists doc directories over 100 markdown files with no code, which collapse to one doc node.
3. **Manifests** (`manifests.py`). One rule per manifest type returns deployables, packages, resources and depends-on edges. For deployables, the entry points are followed through import edges after step 5, and every reached file gets a `part_of` edge, so one file can be part of several deployables.
4. **Parse** (`parse/`). Only files whose blob hash changed. One tree-sitter query file per language captures definitions (class, function, method, arrow-function const, React component = capitalised function returning JSX, interface, type alias), imports, call sites and docstrings or JSDoc.
5. **Resolve** (`resolve.py`).
   - **Imports.** Relative paths, `tsconfig` `paths` aliases, Python packages from `src/` layout and `__init__.py`, and uv path sources.
   - **Calls.** Bound when the callee is defined in the same file, imported by name, or is `self.x` / `this.x` on the enclosing class. Otherwise dropped. Confidence is 1.0 for direct binds and 0.6 for `self`/`this`.
   - **Tests.** A test case links to every symbol it calls (resolved) with `source=treesitter`, and to every module it imports with lower confidence. A file name match (`x.test.ts` to `x.ts`, `test_x.py` to `x.py`) adds `source=naming`.
6. **Docs** (`docs.py`). Title from the first heading. A `mentions` edge goes to any node whose path or qualified name appears in backticks or a link.
7. **Tasks** (`tasks.py`). Regenerate tasks whose input hash changed.

Incremental rule: a node's stored data is reused when its blob hash is unchanged. Resolution reruns across the workspace each scan because it is cheap compared with parsing (benchmark on xenota in deliverable 7; if it is not cheap, limit it to changed files and their importers).

## Judgement task protocol

The CLI never calls a model. Tasks are the contract with the calling agent.

Task kinds in PRD-01:

| Kind | Node | Inputs given to the agent | Answer |
|---|---|---|---|
| `summarise-files` | a group | up to ~15 files in it: path, symbol outline, docstrings, imports | per file: `summary` (1 to 3 sentences) |
| `summarise-group` | group, package | child summaries, child names | `summary`, optional `display_name`, `display_kind` from an allowed list |
| `confirm-deployables` | workspace | detected deployables with evidence, manifests | the corrected list: name, kind, entry points |
| `summarise-deployable` | deployable | entry points, part-of package and group summaries | `summary` |
| `summarise-workspace` | workspace | deployable and package summaries, README head | `summary` |

Tasks open bottom-up: `summarise-group` waits for its files and subgroups, `summarise-deployable` waits for `confirm-deployables`.

Commands:

- `cbi tasks [--kind K] [--limit N] [--json]` lists open tasks.
- `cbi task <id>` prints the brief: what to do, which files to read, and the JSON Schema of the answer.
- `cbi submit <id> [FILE|-]` validates the answer and stores it. Errors name the JSON path and the problem, and exit with code 2.

The answer cache is `~/.cache/codebase-inspector/answers.db`, keyed by `(task kind, input hash, protocol version)`. Before opening a task, the scan checks the cache and fills the answer if it is there. Bumping the protocol version invalidates old answers.

Validation is hand-written checks against a small dict per task kind (required keys, types, lengths, allowed `display_kind` values). A JSON Schema library is not needed for five shapes; the schema printed in the brief is generated from the same dict.

## Agent interface

`cbi prime` reads `.cbi/` and prints one of three guides, each under ~60 lines:

- **Not initialised.** What the tool is, `cbi init`, `cbi scan`.
- **Tasks pending.** The task loop with one worked example, the count by kind, and a note that independent tasks can go to subagents.
- **Complete.** The query commands with examples on this repo's real node names, and the ingest command for this repo's test runner (node:test, vitest, pytest detected from manifests).

`--help` on every subcommand states inputs, output shape and exit codes. Read commands: `search`, `show`, `tests-for`, `tasks`, `task`, `status`; all take `--json`.

## Test ingest

`cbi ingest <file>...` detects the format by content:

- lcov (`SF:` / `DA:` records): line coverage per file, rolled up to symbols by line range.
- coverage.py JSON (`meta.format`): line coverage. When `contexts` are present, `tests` edges go from each test case to the symbols covering its lines, with `source=coverage` and confidence 1.0.
- JUnit XML: `testcase` `file`/`classname`/`name` matched to test-case nodes by file and name. Unmatched results are counted and reported, not dropped silently.

## Viewer (`cbi build`)

Output: `.cbi/viewer/` with `index.html`, `app.js`, `style.css`, `vendor/`, and `data/`.

Data is written as JavaScript files that call a global loader (`cbiLoad("ws-xenon", {...})`), because `<script>` tags load from `file://` where `fetch()` does not.

- `data/tree.js`: every node down to file level (id, parent, display_kind, name, loc, test status, short summary), plus edges rolled up to file level and above. For xenota this is ~5k nodes.
- `data/f-<n>.js`: symbol nodes, symbol edges and full summaries, chunked by group so each chunk is under ~500 KB. Loaded when the user opens a file or group.
- `data/search.js`: prebuilt MiniSearch index over every node, symbols included, storing only id, name, display_kind and path.

Rollups are computed at build time. An edge between two symbols counts towards each ancestor pair up to their lowest common ancestor, so the UI never aggregates.

Layout: a breadcrumb and search box on top. The left side shows the focused node's children as a treemap (area = LOC, colour = test overlay) with a list toggle. The right side shows the selected node's detail: summary, signature, docstring, path as a `vscode://file/...:line` link, incoming and outgoing relationships at the current level, and linked tests or tested code. A third tab shows the Cytoscape graph of the focused node's children and the edges between them. Low-confidence edges are hidden by default.

Test overlay modes: static links (has tests / no tests), coverage percentage (when ingested), last result (pass / fail / skipped). A legend states which mode and source is showing.

## Security and failure handling

- The CLI only reads the target through `git` and file reads, and only writes under `.cbi/` (or `--out`) and the shared cache.
- `git` is invoked with fixed argv lists, never through a shell.
- Parse errors in one file are recorded on that file node (`attrs.parse_error`) and the scan continues. `cbi status` lists them.
- Submitted answers are data: they are stored as text and rendered in the viewer with `textContent`, never as HTML, because an agent could paste content from the repo.
- `.cbi/` is created with its own `.gitignore` containing `*`.

## Test strategy

- Unit tests per module against small synthetic repos in `tests/fixtures/` (built with `git init` in a temp dir by a fixture, so submodule cases are real).
- Golden tests: scan a fixture and compare a sorted dump of nodes and edges to a checked-in expected file.
- Acceptance runs on orchestra, lms and xenota are scripted in `scripts/acceptance.sh`, which prints node counts by kind, timings and the A-criteria checks. They are run by hand, not in CI, because they read repos outside this one.
- Viewer: a Playwright smoke script loads the built orchestra viewer from `file://`, searches, drills to a method and toggles the overlay.

## Configuration

`.cbi/config.toml` (written by `init`, optional to edit): language overrides, extra test name patterns, doc collapse threshold. CLI flags win over config. The cache path can be moved with `CBI_CACHE_DIR`.

## Deferred decisions

- SCIP ingestion for precise calls.
- Snapshot storage per commit for PRD-02.
- Serving the viewer, if change review or quizzing needs it.

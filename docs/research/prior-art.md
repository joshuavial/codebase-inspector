# Prior art for a codebase inspector: levels, edge kinds, formats and navigation at scale

## Architecture models

**C4 model** ([c4model.com](https://c4model.com)). It has four levels: **System Context**, **Container** (a separately deployable or runnable unit such as an app, DB, SPA or lambda), **Component** (a grouping of code behind an interface inside one container) and **Code** (UML class level, which C4 itself says is optional and best auto-generated). People and external systems sit beside these. Each relationship is one directed edge with a description and a technology ("uses", "reads from"). Views are filtered projections of a single model.

**Structurizr DSL / JSON workspace** ([docs.structurizr.com/dsl/language](https://docs.structurizr.com/dsl/language), [JSON schema](https://github.com/structurizr/json)). A workspace has two parts:
- a `model`: `person`, `softwareSystem`, `container`, `component`, plus `deploymentEnvironment`, `deploymentNode`, `infrastructureNode` and `containerInstance`. Elements carry tags, properties, `url` and `perspectives`.
- `views`: `systemLandscape`, `systemContext`, `container`, `component`, `dynamic`, `deployment`, `filtered`, `image`.

Relationships are stored once, and **implied relationships** propagate up the hierarchy automatically: a component-to-component edge shows up as a container-to-container edge. That is the collapse rule needed for drill-down. The JSON is a reasonable interchange target for the upper levels, but it has no level below component.

**arc42 §5 Building Block View** ([docs.arc42.org/section-5](https://docs.arc42.org/section-5/)). Recursive decomposition: Level 1 is a whitebox of the whole system made of blackboxes, and each blackbox can open into a Level 2 whitebox, then Level 3. Every blackbox records its responsibility, interfaces and location (the source path). Depth is unbounded and has no fixed names. This is the main argument for making levels a recursive `contains` tree with a `kind` label rather than a fixed enum of depths.

**Backstage catalog** ([descriptor format](https://backstage.io/docs/features/software-catalog/descriptor-format), [well-known relations](https://backstage.io/docs/features/software-catalog/well-known-relations)).
- Kinds: `Domain`, `System`, `Component` (`spec.type` service, website or library), `API` (openapi, asyncapi, graphql, grpc), `Resource`, `Group`, `User`, `Location`, `Template`.
- Relations come in paired forward and inverse names: `partOf`/`hasPart`, `dependsOn`/`dependencyOf`, `providesApi`/`apiProvidedBy`, `consumesApi`/`apiConsumedBy`, `ownedBy`/`ownerOf`, `parentOf`/`childOf`, `memberOf`/`hasMember`.
- Entities are YAML documents with `apiVersion`, `kind`, `metadata` and `spec`.

Its ideas worth taking: API as a first-class entity, ownership, and storing inverse relations explicitly.

## Symbol and code-intelligence formats

**SCIP** ([scip.proto](https://github.com/sourcegraph/scip/blob/main/scip.proto)). Structure: Index → Document (path, language) → Occurrence (range, symbol, `symbol_roles`, `enclosing_range`) plus SymbolInformation (symbol, documentation, relationships, `kind`, `display_name`, `enclosing_symbol`).
- **SymbolRole** bit flags: Definition, Import, WriteAccess, ReadAccess, Generated, **Test**, ForwardDefinition.
- **Relationship** fields: `is_reference`, `is_implementation`, `is_type_definition`, `is_definition`.
- **Kind** has about 85 values. The ones that matter here are Package, Module, Namespace, File, Class, Struct, Interface, Trait, Protocol, Enum, EnumMember, Union, Type, TypeAlias, Function, Method, Constructor, StaticMethod, AbstractMethod, Getter, Setter, Accessor, Property, Field, Constant, Variable, Macro, Parameter, TypeParameter, Event, Delegate, Mixin, Extension, Object, Library. The rest cover theorem provers, Haskell and the like.
- Symbol strings are globally unique and structured: `scheme manager package version descriptors`, with descriptor suffixes Namespace `/`, Type `#`, Term `.`, Method `().`, TypeParameter, Parameter, Meta, Local and Macro.

That symbol string is a ready-made stable ID scheme across a polyglot monorepo. Indexers already exist: scip-typescript, scip-java, scip-python, scip-go, rust-analyzer, scip-clang, scip-ruby, scip-dotnet.

**LSIF** ([spec](https://microsoft.github.io/language-server-protocol/specifications/lsif/0.6.0/specification/)) is SCIP's predecessor: a graph of vertices (`document`, `range`, `resultSet`, `definitionResult`, `referenceResult`, `moniker`, `packageInformation`) and edges (`contains`, `next`, `item`, `textDocument/definition`, ...). It is verbose and hard to stream. Sourcegraph moved to SCIP for these reasons ([announcement](https://sourcegraph.com/blog/announcing-scip)). Don't emit it.

**universal-ctags** ([docs](https://docs.ctags.io/en/latest/man/ctags.1.html)). Kinds are defined per language (`ctags --list-kinds-full`), with `scope` and `roles` fields (def, ref, imported) and JSON output (`--output-format=json`). It supports 100+ languages with no build step, so it is the cheap fallback for languages that have no SCIP indexer.

**Sourcegraph code navigation** ([docs](https://sourcegraph.com/docs/code-search/code-navigation)) has two tiers: precise navigation from uploaded SCIP, and search-based (heuristic) navigation as the fallback. Copy this two-tier precision model and record a `confidence` or `source` on every edge.

**Kythe** ([schema](https://kythe.io/docs/schema/)). Nodes (`record`, `function`, `variable`, `package`, `file`, `anchor`) and typed edges (`defines/binding`, `ref`, `ref/call`, `childof`, `extends`, `satisfies`, `overrides`, `typed`). Its edge vocabulary is a good reference, but the toolchain is heavy. Skip the tooling.

## Tree-sitter mappers

**Tree-sitter tags queries** ([docs](https://tree-sitter.github.io/tree-sitter/4-code-navigation.html)). Captures are `@definition.{class,function,method,module,interface,macro,constant,type}` and `@reference.{call,class,implementation,type}`. Many grammars ship a `tags.scm`. These are file-local and unresolved: the output is name matching, not a binding.

**Aider repo map** ([aider.chat/docs/repomap](https://aider.chat/docs/repomap.html)). It runs the tags queries, builds a file graph from definition and reference name matches, ranks it with personalised PageRank, then trims to a token budget. It shows that heuristic def/ref edges plus ranking are enough for an LLM-facing summary of large repos.

**GitHub stack-graphs** ([repo](https://github.com/github/stack-graphs)) does incremental, file-local name resolution behind GitHub's "precise" navigation for Python, JS and TS. I believe the repo is archived, but I didn't check that, so confirm it before depending on it.

**code2flow** ([repo](https://github.com/scottrogowski/code2flow)) produces heuristic call graphs for Python, JS, Ruby and PHP as DOT or JSON. It has nodes, `calls` edges and file/class groups. It is good enough for a first pass and inaccurate on dynamic dispatch.

## Dependency and metrics visualisers

**dependency-cruiser** ([options](https://github.com/sverweij/dependency-cruiser/blob/main/doc/options-reference.md), [rules](https://github.com/sverweij/dependency-cruiser/blob/main/doc/rules-reference.md)).
- JSON output has `modules[]`, each with `source`, `dependencies[]` (`resolved`, `dependencyTypes` such as `local`, `npm`, `core`, `type-only`, `dynamic`), `circular` and `valid`, plus a `summary.violations` block.
- Rules are `forbidden`, `allowed` and `required`, written as from/to path regexes (e.g. no-circular, no-orphans, not-to-test-from-src).
- **`--collapse "^packages/[^/]+"`** folds modules into folder nodes and aggregates their edges. The `archi` and `ddot` reporters are preset folder-level collapses.

The path-regex collapse is the simplest working version of level aggregation.

**Madge** ([repo](https://github.com/pahen/madge)) emits an adjacency list in JSON (`{file: [deps]}`) and supports `--circular`, `--orphans` and Graphviz output. It offers nothing beyond dependency-cruiser.

**CodeCharta** ([cc.json docs](https://codecharta.com/docs/general/cc-json-format)).
- Format: `{projectName, apiVersion, nodes: [{name, type: Folder|File, attributes: {rloc, mcc, ...}, children}], edges: [{fromNodeName, toNodeName, attributes}], attributeTypes, attributeDescriptors, blacklist, markedPackages}`.
- It renders as a 3D treemap "code city": area = size, height = metric, colour = metric, with edges drawn on hover.
- Importers include SonarQube, git log, tokei and SourceMonitor.

The node tree plus a per-node metric dictionary is the right shape for an overlay such as coverage. The format stops at file level.

**CodeSee** ([acquisition](https://www.schneider.im/gitkraken-acquired-codesee)) was acquired by GitKraken in May 2024 and folded into GitKraken's DevEx platform. The standalone Codebase Maps product is effectively gone. Its pattern: an auto-generated folder/file map, coloured by language or ownership, with dependency arrows shown on selection and "tours" layered over the top.

## LLM-assisted architecture mapping (2025–26)

- **DeepWiki / Devin Wiki** ([docs](https://docs.devin.ai/work-with-devin/deepwiki)) produces a wiki with a page hierarchy (overview, then subsystems, then components), Mermaid diagrams and source-linked citations, plus chat over it. A `.devin/wiki.json` file steers which pages get generated. The levels are prose pages, not a typed model.
- **GitDiagram** ([repo](https://github.com/ahmedsadawi/gitdiagram)) feeds the file tree and README to an LLM, which writes a Mermaid flowchart with `click` links to paths. It is one level deep and makes mistakes on large repos.
- **Swark** ([repo](https://github.com/swark-io/swark)) is a VS Code extension that uses the Copilot LM API to produce a Mermaid architecture diagram from sampled files. Also one level.
- **CodeViz** ([codeviz.ai](https://codeviz.ai)) is a VS Code extension with an LLM-generated, C4-like architecture view that drills down into an analysis-based call graph, with nodes linked to source.
- Google **Code Wiki** (late 2025) follows the same pattern as DeepWiki.

All of these produce Mermaid or prose with no schema. LLMs are good at naming, grouping and describing (system, container and component levels and their responsibilities) and weak at exhaustive edges. Use static analysis for edges and the LLM for labels and boundaries.

## Test-to-code mapping

| Format | Granularity | Per-test? |
|---|---|---|
| **lcov** ([geninfo(1)](https://manpages.debian.org/lcov/geninfo.1)) | `SF` file, `FN`/`FNDA` function hits, `DA` lines, `BRDA` branches; `TN` test name | Only if you run once per test and set `TN` |
| **Cobertura XML** ([DTD](https://github.com/cobertura/web/blob/master/htdocs/xml/coverage-04.dtd)) | packages → classes → methods → lines, with line-rate and branch-rate | No |
| **Istanbul `coverage-final.json`** ([schema](https://github.com/istanbuljs/istanbuljs/blob/main/docs/raw-output.md)) | `statementMap`/`fnMap`/`branchMap` with ranges, counts in `s`/`f`/`b` | No |
| **coverage.py JSON** ([contexts](https://coverage.readthedocs.io/en/latest/contexts.html)) | lines and executed branches; `--show-contexts` adds `contexts: {line: [test ids]}` | **Yes**: `dynamic_context = test_function`, or pytest-cov `--cov-context=test` |
| **JaCoCo** | exec files per session | Yes, with per-test sessions via a listener |
| **JUnit XML** ([de facto schema](https://github.com/testmoapp/junitxml)) | `testsuite`/`testcase` (`classname`, `name`, `file`, `time`), with `failure`/`skipped` | Results only, no coverage |

Native per-test attribution exists only in coverage.py and JaCoCo. Elsewhere you either run a test or test file per process, or fall back to static linking: test file → imports and calls → subject. SCIP's `Test` role helps with that.

## Recommendations

### 1. Level taxonomy

Model levels as one recursive `contains` tree. Each node has a `kind`; a node's depth comes from its place in the tree, not from its kind. Canonical kinds, coarsest to finest:

1. `workspace`: the repo root, or a superproject with submodules
2. `system`: C4 system or Backstage System; usually one per repo, several in a big monorepo
3. `container`: a deployable or runnable unit or a published library. Detect these from manifests (package.json, go.mod, Cargo.toml, pom.xml, Dockerfile, k8s/serverless config). A git submodule is a container (or system) with a `submodule` flag.
4. `component`: a cohesive module or folder grouping behind an interface. Seed from folders, refine with the LLM.
5. `file`
6. `type`: class, struct, interface, trait, enum or protocol. Keep SCIP's Kind as the subkind.
7. `callable`: function, method or constructor, with SCIP Kind as the subkind.
8. Optional `member`: field, property or constant. Hidden by default.

Kinds for tests: `test-suite` (a test file or class) and `test-case`, which live in the same tree. Add `api` (an OpenAPI/gRPC/GraphQL spec or exported surface) and `resource` (DB, queue, bucket) as non-tree nodes. Allow components to nest (arc42-style recursion) and let the UI skip empty levels.

### 2. Edge kinds

- `contains`: the tree
- `imports` / `depends_on`: module and package level, with subtypes local, external, type-only and dynamic
- `calls`
- `references`
- `inherits` / `implements`: SCIP `is_implementation`
- `type_of`
- `provides_api` / `consumes_api`
- `reads` / `writes`: to a resource
- `tests`: test-case → callable, type or file
- `owned_by`: optional, from CODEOWNERS

Every edge carries `source ∈ {scip, ctags, treesitter, coverage, llm, manifest}`, a `confidence` and a `weight`. Edges between deep nodes roll up the tree automatically, the way Structurizr implies relationships and dependency-cruiser collapses folders.

### 3. Formats to reuse or emit

- **Ingest**: SCIP where an indexer exists, ctags or tree-sitter `tags.scm` otherwise; dependency-cruiser JSON for JS/TS; lcov, Cobertura, Istanbul and coverage.py-with-contexts for coverage; JUnit XML for test results.
- **IDs**: use SCIP symbol strings for symbols and repo-relative paths for files.
- **Internal model**: one streaming JSONL nodes/edges file per container, merged by the workspace. This is the one thing to invent, and it should stay thin.
- **Emit**: Structurizr JSON for the system/container/component levels (it gets C4 diagrams and PlantUML or Mermaid exports for free), cc.json for metric treemaps, and Backstage `catalog-info.yaml` as an optional export.

### 4. Visualisation patterns at 10k+ files

- **Semantic zoom and drill-down**: only the children of the focused node are expanded, and edges to everything else are aggregated into weighted edges at the deepest visible ancestor (dependency-cruiser collapse, Structurizr implied relationships). Breadcrumbs keep the path visible.
- **A treemap or code city as the overview**: area = LOC, colour = coverage or churn. It scales where node-link graphs don't, as CodeCharta has shown on large repos.
- **Node-link only for the local neighbourhood**: the focus node plus 1–2 hops, with hierarchical edge bundling ([Holten 2006](https://www.win.tue.nl/vis1/home/dholten/papers/bundles_infovis.pdf)) when cross-component edges pile up.
- **A dependency structure matrix (DSM)** for component-to-component views with hundreds of nodes.
- **Search as the main navigation**: a fuzzy index over every level, returning hits grouped by kind; selecting a hit jumps to and expands its ancestor chain.
- **A coverage overlay** that colours each node by the line or branch coverage rolled up to that level. Selecting a callable lists the test-cases that cover it, and selecting a test lists the callables it reaches.
- Lazy-load child graphs per container, and pre-compute rollups at index time so the UI never aggregates 13k files on the client.

**Sources**: [CodeSee acquisition](https://www.schneider.im/gitkraken-acquired-codesee), [DeepWiki docs](https://docs.devin.ai/work-with-devin/deepwiki), [SCIP proto](https://github.com/sourcegraph/scip/blob/main/scip.proto), plus the inline links above.

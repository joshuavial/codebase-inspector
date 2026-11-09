# Launch Metadata Draft: Topics, Homepage, and v0.4.0 Highlights

Prepared for JV approval (cbi-6pq.6, updated for v0.4.0 launch in cbi-ecw.6).
Per hard limits: **Do not apply to GitHub repo until JV confirms.**

---

## 1. Repository Homepage & Description Drafts

### Option A (Recommended based on demand evidence): Agent Codebase Map
* **Description:** Fast, deterministic codebase map for AI coding agents. 100% local, links tests to code, eliminates grep loops, zero LLM tokens.
* **Homepage URL:** https://github.com/joshuavial/codebase-inspector (or dedicated docs site once published)
* **v0.4.0 Feature References:** 25 native MCP tools and 3 prompts over stdio JSON-RPC (`cbi mcp`), `cbi mcp --install` automated configuration generator for Claude Code, Cursor, Windsurf, Antigravity, and VS Code, deterministic symbol resolution, and instant test linkage (`cbi tests-for`).

### Option B (Alternative): Architecture PR Review
* **Description:** Deterministic architecture review for pull requests and CI. Structural diffs, Mermaid graphs, and boundary checks with no model inside.
* **Homepage URL:** https://github.com/joshuavial/codebase-inspector
* **v0.4.0 Feature References:** Automated PR architecture reviews (`cbi review`), database schema migration and HTTP route impact analysis with Mermaid visualization, visual ERD generation (`cbi tables --format mermaid`), reusable GitHub Action, and multi-repo showcase compilation (`cbi gallery`).

---

## 2. GitHub Topics Draft

Recommended 12 topics:
```
codebase-map
coding-agents
mcp-server
ast
tree-sitter
python
claude-code
developer-tools
code-intelligence
architecture-review
test-selection
static-analysis
```

---

## 3. Demo GIF Storyboard (30 Seconds)

Script for creating `docs/images/cbi-demo.gif`:

1. **Scene 1 (0:00 - 0:06) — Instant Scan:**
   - Terminal prompt in `httpx`.
   - Run `cbi scan`.
   - Shows: `scanned in 6.9 s (95 classes, 122 functions, 539 test cases)`. Zero tokens consumed.
2. **Scene 2 (0:06 - 0:14) — Test Linkage (`cbi tests-for`):**
   - Run `cbi tests-for class:HTTPTransport`.
   - Instantly shows exact test cases in `tests/client/test_proxies.py`. No grep loop!
3. **Scene 3 (0:14 - 0:22) — Cycle & Boundary Auditing:**
   - Run `cbi cycles`.
   - Instantly outputs exact multi-hop import cycles in yellow/green terminal text.
4. **Scene 4 (0:22 - 0:30) — PR Architecture Review (v0.4.0):**
   - Run `cbi review HEAD~1..HEAD`.
   - Generates Mermaid diagram and structural change overview, surfacing database migration and HTTP endpoint impacts.

---

## 4. v0.4.0 Release Highlights

CBI v0.4.0 brings significant enhancements across user-facing architecture views and agent-facing MCP capabilities.

### Major User-Facing Enhancements

* **Visual System Views & ERD Export:**
  * `cbi tables --format markdown` exports schema tables in GitHub Flavored Markdown.
  * `cbi tables --format mermaid` generates visual Mermaid `erDiagram` diagrams documenting tables, columns, primary/foreign keys, and relational cardinality.
  * `cbi endpoints --format markdown` outputs GFM tables detailing HTTP routes, methods, handler functions, caller traces, and accessed database tables.
* **Database Migration & HTTP Route Impacts in Reviews:**
  * `cbi diff` and `cbi review` detect schema migrations (added, altered, dropped tables and columns) and HTTP endpoint changes.
  * Migrations and route modifications are rendered directly into Mermaid diagrams and PR markdown summaries.
* **Multi-Repo Architecture Showcase Gallery:**
  * First-class `cbi gallery` CLI subcommand compiling multi-repository architecture showcases with interactive dependency diagrams, system views, and review histories.
* **Production Reusable GitHub Action:**
  * Local reusable GitHub Action (`action.yml`) featuring automated package name matching, depth-0 git history guard, and zero-drift verification for CI pipelines.
* **Hardened Test Harness & Stability:**
  * Resilient Playwright browser detection with graceful fallback skips across viewer tests (`cbi-ecw.1`).
  * Process-group reaping and test determinism improvements for headless renders.

### Major Agent-Facing Enhancements

* **25 Native MCP Tools:**
  * Comprehensive stdio JSON-RPC Model Context Protocol server under `cbi mcp` expanded from 5 tools in v0.3.0 to 25 native tools:
    * *Workspace & Indexing:* `cbi_init`, `cbi_scan`, `cbi_prime`, `cbi_task`, `cbi_submit`, `cbi_worktrees`
    * *Query & Context:* `cbi_status`, `cbi_context`, `cbi_search`, `cbi_show`, `cbi_query`
    * *System Views:* `cbi_tables` (with Markdown & Mermaid ERD support via `format`), `cbi_endpoints` (with Markdown table support via `format`), `cbi_concepts`
    * *Architecture & Boundaries:* `cbi_hotspots`, `cbi_cycles`, `cbi_orphans`, `cbi_deps`
    * *Test & Verification:* `cbi_tests_for`, `cbi_check`, `cbi_ingest`
    * *Evolution & Review:* `cbi_history`, `cbi_diff`, `cbi_review`
  * 3 native MCP Prompts (`cbi-review`, `cbi-triage`, `cbi-brief`) and resources support over stdio JSON-RPC.
* **Automated Client Configuration (`cbi mcp --install`):**
  * One-command client configuration generator supporting Claude Code, Cursor, Windsurf, Antigravity, and VS Code.
* **Unified Local Smoke Verification Harness:**
  * `scripts/smoke_all.py` validating 21 end-to-end checkpoints offline across CLI, MCP, GitHub Action, and Gallery workflows.

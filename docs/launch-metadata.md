# Launch Metadata Draft: Topics and Homepage

Prepared for JV approval (cbi-6pq.6).
Per hard limits: **Do not apply to GitHub repo until JV confirms.**

---

## 1. Repository Homepage & Description Drafts

### Option A (Recommended based on demand evidence): Agent Codebase Map
* **Description:** Fast, deterministic codebase map for AI coding agents. 100% local, links tests to code, eliminates grep loops, zero LLM tokens.
* **Homepage URL:** https://github.com/joshuavial/codebase-inspector (or dedicated docs site once published)

### Option B (Alternative): Architecture PR Review
* **Description:** Deterministic architecture review for pull requests and CI. Structural diffs, Mermaid graphs, and boundary checks with no model inside.
* **Homepage URL:** https://github.com/joshuavial/codebase-inspector

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
4. **Scene 4 (0:22 - 0:30) — PR Architecture Review:**
   - Run `cbi review HEAD~1..HEAD`.
   - Generates Mermaid diagram and structural change overview.

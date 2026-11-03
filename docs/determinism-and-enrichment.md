# Determinism and Agent Enrichment

This document defines the boundary between what Codebase Inspector (`cbi`) computes deterministically and what requires agent enrichment. It responds to reviews from the four-model architecture challenge to eliminate overclaiming and make the tool's execution model explicit.

---

## 1. Core Principle

CBI separates **structural ground truth** from **semantic judgement**:
* The `cbi` engine itself contains **no LLM**, calls **no network endpoints**, and executes **no target code**.
* Given the same git commit and committed metadata, every scan, query, and CI check produces the exact same SQLite database and reports byte-for-byte.
* Semantic comprehension (purpose summaries, high-level domain concepts, screen sketches, and PR change narratives) is delegated to external AI coding agents via a structured, validated task protocol.

---

## 2. What is Deterministic (Computed Directly from Source)

The following components are computed entirely through static analysis, AST extraction, and deterministic graph algorithms:

| Capability | Engine Mechanism | Guarantee |
|---|---|---|
| **AST & Symbol Extraction** | `tree-sitter` (Python, TS/TSX/JS, C#, Vue) | Complete, reproducible symbol tree (classes, functions, methods, exports, interfaces). Error-tolerant on syntax mistakes. |
| **Dependency & Call Resolution** | Lexical and import graph analysis | Maps static imports, intra-package calls, and package dependencies across files. |
| **Test Linkage** | Test discovery heuristics + coverage/JUnit ingestion | Bidirectional mapping between implementation code and test cases (`tests-for`). Ingests `coverage.py`, `lcov`, and JUnit XML reports. |
| **Database & Route Extraction** | SQL migration parsing & web framework route scrapers | Extracts DB tables, columns, relations, and REST/API endpoints directly from definitions. |
| **Graph Metrics & Quality Signals** | Directed graph algorithms | Computes dependency cycles, orphan/unreferenced files, structural hotspots (git churn × complexity), and layering rule violations (`deps`). |
| **Architectural PR Diffs** | Git diff + symbol cross-referencing | Identifies exact modified AST nodes, affected callers, altered endpoints, schema migrations, and affected test suites without calling an LLM. |
| **CI Gate (`cbi check`)** | SQLite query validation | Checks in pull requests whether the codebase map is fresh and verifies architectural boundaries. Operates with 0 tokens and 0 network egress. |

---

## 3. What Requires Agent Enrichment (Judgement Tasks)

Certain representations require high-level engineering judgement that cannot be derived from syntax alone. CBI flags these as explicit judgement tasks:

| Enrichment Area | What the Agent Supplies | Why Static Analysis Cannot Derive It |
|---|---|---|
| **File & Package Summaries** | 1–3 sentence plain English descriptions of responsibilities | Code comments are often missing or stale; variable and class names rarely describe higher-level intent. |
| **Concept Mapping** | Grouping folders and packages into bounded domain concepts (e.g. "Order Processing", "Authentication Engine") | Architecture boundaries span arbitrary directory structures and conventions that vary across frameworks. |
| **Concept Relationships** | Semantic edge labels (e.g. "emits events to", "authorizes via") | AST edges establish function calls and imports, not domain interactions. |
| **UI Screen Sketches** | High-level wireframe layouts in SVG/Mermaid | Pure component ASTs do not express visual hierarchy without executing browser engines. |
| **PR Change Narratives** | High-level architectural narrative of *why* a PR modified a subsystem | The git diff shows *what* changed; synthesizing author intent and systemic consequences requires reasoning. |

---

## 4. The Task and Submit Protocol

Enrichment follows an asynchronous, verifiable protocol:

1. **Detection:** When `cbi scan` runs, it indexes the code deterministically and identifies gaps in semantic summaries or concepts.
2. **Task Generation:** The CLI creates structured tasks (`cbi tasks`). Each task includes:
   - Target node ID (file, package, or concept).
   - Extracted deterministic context (exported symbols, callers, imports, tests).
   - Prompt specification for the agent.
3. **Agent Completion:** The developer's agent (Claude Code, Codex, Antigravity, etc.) queries `cbi context <target>`, generates the answer, and runs:
   ```bash
   cbi submit --task <task-id> --content "<answer>"
   ```
4. **Validation:** The `cbi` CLI strictly validates submissions before writing them to `.cbi/model.db`:
   - Checks schema, length, and formatting rules.
   - Verifies that all referenced node IDs and symbol identifiers exist in the current AST.
   - Refuses hallucinated references or malformed structures.
5. **Persistence in Team Mode:** In team mode (`.cbi/team/`), verified answers are saved as version-controlled JSON files committed alongside the code. Subsequent scans by other team members or CI jobs load these committed answers deterministically.

---

## 5. Summary of Claims

* **Cold Scan:** 100% deterministic, immediate structural map and test links.
* **Cold PR Review (`cbi review`):** Deterministic AST impact review, modified symbol list, endpoint/schema diffs, and Mermaid change graphs. No synthetic narratives.
* **Enriched Review:** High-level architectural narrative and concept impact overlays added only after an agent completes the judgement tasks.
* **CI Gate:** 100% deterministic verification that committed architecture maps match current code.

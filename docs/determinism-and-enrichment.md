# Determinism and Agent Enrichment

This document defines the boundary between what Codebase Inspector (`cbi`) computes deterministically and what requires agent enrichment. It responds to reviews from the four-model architecture challenge to eliminate overclaiming and make the tool's execution model explicit.

---

## 1. Core Principle

CBI separates **structural ground truth** from **semantic judgement**:
* The mapping engine contains **no LLM**, requires **no network access**, and executes **no target code**. CLI commands can perform an optional release update check; set `CBI_NO_UPDATE_CHECK=1` to disable it. PR lookup and explicit review posting also use GitHub when requested.
* Given the same source, committed metadata and tool version, static analysis produces reproducible structural facts. The SQLite files and reports are not guaranteed byte-identical: scan timestamps, local provenance and runtime details can differ.
* Semantic comprehension (purpose summaries, high-level domain concepts, screen sketches, and PR change narratives) is delegated to external AI coding agents via a structured, validated task protocol.

---

## 2. What is Deterministic (Computed Directly from Source)

The following components are computed entirely through static analysis, AST extraction, and deterministic graph algorithms:

| Capability | Engine Mechanism | Guarantee |
|---|---|---|
| **AST & Symbol Extraction** | `tree-sitter` (Python, TS/TSX/JS, C#, Vue) | Reproducible symbol facts for supported syntax (classes, functions, methods, exports, interfaces). Unsupported or dynamic forms can remain unresolved; parse errors are reported. |
| **Dependency & Call Resolution** | Lexical and import graph analysis | Maps static imports, intra-package calls, and package dependencies across files. |
| **Test Linkage** | Test discovery heuristics + coverage/JUnit ingestion | Bidirectional mapping between implementation code and test cases (`tests-for`). Ingests `coverage.py`, `lcov`, and JUnit XML reports. |
| **Database & Route Extraction** | SQL migration parsing & web framework route scrapers | Extracts DB tables, columns, relations, and REST/API endpoints directly from definitions. |
| **Graph Metrics & Quality Signals** | Directed graph algorithms | Computes dependency cycles, orphan/unreferenced files, structural hotspots (fan-in, fan-out, lines of code or symbol count), and layering rule violations (`deps`). |
| **Architectural PR Diffs** | Git diff + symbol cross-referencing | Identifies exact modified AST nodes, affected callers, altered endpoints, schema migrations, and affected test suites without calling an LLM. |
| **CI Gate (`cbi check`)** | SQLite query validation | Checks whether changed files have current committed summaries and valid judgement documents. Boundary assertions use `cbi deps --forbid`. The gate uses no model or network for its analysis. |

### Layering Constraints and Forbid Output (`cbi deps --forbid`)

Architectural boundaries are enforced deterministically using `cbi deps --forbid <FROM>:<TO>` (or `<FROM>-><TO>`). When `--json` is specified, `cbi deps` outputs a structured violation report:

```json
{
  "level": "package",
  "include_tests": false,
  "passed": true,
  "rules": [
    {
      "spec": "src:core",
      "passed": true,
      "violations": []
    }
  ]
}
```

When a violation occurs:
* `passed` is `false`.
* The failing rule has `"passed": false`.
* `violations` contains a list of `{"from": "<source_file>", "to": "<target_file>"}` pairs.
* The command exits with code `1` (or `0` when all forbid rules pass).

---

## 3. What Requires Agent Enrichment (Judgement Tasks)

Certain representations require high-level engineering judgement that cannot be derived from syntax alone. CBI flags these as explicit judgement tasks:

| Enrichment Area | What the Agent Supplies | Why Static Analysis Cannot Derive It |
|---|---|---|
| **File & Package Summaries** | 1–3 sentence plain English descriptions of responsibilities | Code comments are often missing or stale; variable and class names rarely describe higher-level intent. |
| **Concept Mapping** | Grouping folders and packages into bounded domain concepts (e.g. "Order Processing", "Authentication Engine") | Architecture boundaries span arbitrary directory structures and conventions that vary across frameworks. |
| **Concept Relationships** | Semantic edge labels (e.g. "emits events to", "authorizes via") | AST edges establish function calls and imports, not domain interactions. |
| **UI Screen Sketches** | Structured screen and flow descriptions in `screens.json` | Pure component ASTs do not express visual hierarchy without executing browser engines. |
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
   cbi task TASK_ID --json
   cbi submit TASK_ID answer.json
   ```
4. **Validation:** The `cbi` CLI strictly validates submissions before writing them to `.cbi/model.db`:
   - Checks schema, length, and formatting rules.
   - Checks task-specific references and evidence against the supplied model or brief.
   - Rejects invalid references or malformed structures; validation does not prove narrative claims.
5. **Persistence in Team Mode:** In team mode, accepted answers are exported to `.cbi/answers.jsonl`, with concepts, structure and screens in the corresponding `.cbi/*.json` documents committed alongside the code. Subsequent scans by other team members or CI jobs load these committed answers deterministically.

---

## 5. Summary of Claims

* **Cold Scan:** 100% deterministic, immediate structural map and test links.
* **Cold PR Review (`cbi review`):** Deterministic AST impact review, modified symbol list, endpoint/schema diffs, and Mermaid change graphs. No synthetic narratives.
* **Enriched Review:** High-level architectural narrative and concept impact overlays added only after an agent completes the judgement tasks.
* **CI Gate:** 100% deterministic verification that committed architecture maps match current code.

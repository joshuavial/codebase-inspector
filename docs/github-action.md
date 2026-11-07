# Codebase Inspector GitHub Action

The Codebase Inspector GitHub Action provides deterministic architectural verification and automated PR change reviews for your CI pipeline.

It runs 100% locally in your GitHub Actions runner using AST parsing and graph analysis — **zero network calls, zero third-party telemetry, and zero LLM tokens consumed**.

---

## What It Does

1. **Architectural Drift Gate (`cbi check`):**
   - Verifies that every changed code and test file has an assigned concept owner and up-to-date summary.
   - Checks that committed architecture models (`concepts.json`, `structure.json`, `screens.json`, `answers.jsonl`) remain consistent with source code.
   - Emits native GitHub Actions annotations (`::error` and `::warning`) pointing directly to files needing attention.
   - Fails CI if unowned files or unreviewed changes are detected (configurable).

2. **PR Architectural Review & Diagram (`cbi review`):**
   - Compares the pull request against the base branch (`base-ref` or `github.base_ref`).
   - Generates a structural change overview, untested change analysis, and a visual **Mermaid flowchart** of modified components and relationships.
   - Automatically publishes the full Markdown review to the GitHub Actions **Job Summary** tab.
   - Exports the Markdown payload as a step output for PR commenting workflows.

---

## Quick Start

Create `.github/workflows/cbi.yml` in your repository:

```yaml
name: Architecture Check

on:
  pull_request:
    branches: [main]
  push:
    branches: [main]

permissions:
  contents: read

jobs:
  check:
    name: Codebase Architecture Integrity
    runs-on: ubuntu-latest
    steps:
      - name: Checkout Code
        uses: actions/checkout@v4
        with:
          fetch-depth: 0 # Full history needed to resolve merge base

      - name: Run Codebase Inspector
        uses: joshuavial/codebase-inspector@v0.3.0
        with:
          base-ref: ${{ github.base_ref || 'main' }}
          fail-on-problems: true
          review: true
```

---

## Posting Architectural Reviews as PR Comments

To automatically post the Mermaid architecture diagram and review directly on pull requests, combine Codebase Inspector with a PR comment step:

```yaml
name: Architecture Review

on:
  pull_request:
    types: [opened, synchronize, reopened]

permissions:
  contents: read
  pull-requests: write

jobs:
  review:
    name: Architecture Review & CI Gate
    runs-on: ubuntu-latest
    steps:
      - name: Checkout Code
        uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Run Codebase Inspector Check & Review
        id: cbi
        uses: joshuavial/codebase-inspector@v0.3.0
        with:
          base-ref: ${{ github.base_ref }}
          fail-on-problems: true
          review: true

      - name: Comment PR with Architecture Review
        if: github.event_name == 'pull_request' && steps.cbi.outputs.review-markdown != ''
        uses: peter-evans/create-or-update-comment@v4
        with:
          issue-number: ${{ github.event.pull_request.number }}
          body: ${{ steps.cbi.outputs.review-markdown }}
          comment-author: 'github-actions[bot]'
```

---

## Action Reference

### Inputs

| Input | Description | Type | Default | Required |
|---|---|---|---|---|
| `base-ref` | Target branch or commit SHA to compare changes against. For pull requests, use `${{ github.base_ref }}`. | string | `main` | No |
| `fail-on-problems` | Whether to fail the workflow if `cbi check` discovers unowned files, missing summaries, or schema inconsistencies. | boolean | `true` | No |
| `review` | Whether to generate the structural architectural review and Mermaid diff diagram for pull requests. | boolean | `true` | No |
| `python-version` | Python runtime version for `uv` environment setup. | string | `3.13` | No |

### Outputs

| Output | Description | Example |
|---|---|---|
| `check-status` | Final status of the architectural integrity check (`passed` or `failed`). | `passed` |
| `problems-count` | Number of architectural violations or missing summaries detected. | `0` |
| `review-markdown` | Complete Markdown architectural review with Mermaid diagram and changed concept details. | `"# Review ..."` |
| `review-file` | Absolute path to the generated `review.md` file on the runner filesystem. | `"/tmp/cbi-review/review.md"` |

---

## Configuration & Team Mode

In repositories using CBI **Team Mode** (`cbi team init`), the judgement half of the codebase map is committed to git:

- `.cbi/concepts.json`: Concept definitions, hierarchy, and explicit file ownership.
- `.cbi/answers.jsonl`: Cryptographically hashed answers for accepted summaries and architectural decisions.
- `.cbi/team.toml`: Team-level settings and policy configuration.

When `cbi check` runs in CI:
1. It compares changed files against `.cbi/concepts.json` and `.cbi/answers.jsonl`.
2. Any newly introduced file without a concept owner or summary is flagged.
3. If `team.toml` specifies `check = "warn"`, warnings are annotated on GitHub without failing the run. If `check = "strict"` (default), unresolved files fail the gate.

To fix CI failures locally before pushing:
```bash
# 1. Inspect open tasks for newly added or changed files
uv run cbi tasks

# 2. Assign files to concepts or author summaries
uv run cbi submit <task-id> answer.json

# 3. Verify locally against your base branch
uv run cbi check --base main
```

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
        uses: joshuavial/codebase-inspector@v0.5.0
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
        uses: joshuavial/codebase-inspector@v0.5.0
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
| `base-ref` | Target branch or commit SHA to compare changes against. For pull requests, use `${{ github.base_ref }}`. Requires full history (`fetch-depth: 0`). | string | `main` | No |
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

## Git Checkout Depth Requirement (`fetch-depth: 0`)

Codebase Inspector relies on Git to identify files modified relative to the target branch:
- `cbi check` computes the merge base between your current PR commit (`HEAD`) and the target base branch (`base-ref`).
- `cbi review` extracts the structural commit range diff (`base-ref..HEAD`) and parses modified ASTs.

The default GitHub Actions checkout action (`actions/checkout@v4`) creates a **shallow clone** (`fetch-depth: 1`) containing only the head commit. Under shallow clones:
- The base branch (e.g. `main` or `origin/main`) is not fetched into local Git history.
- Merge-base resolution fails with obscure `git rev-parse` or `git merge-base` errors.

To avoid this, always set `fetch-depth: 0` in `actions/checkout`:
```yaml
- name: Checkout Code
  uses: actions/checkout@v4
  with:
    fetch-depth: 0
```

### Shallow Checkout Guard

The Action automatically validates that `base-ref` is resolvable and shares a common merge-base with `HEAD` before executing `cbi check`. If a shallow checkout prevents resolution, the Action halts immediately and emits a GitHub Actions `::error` annotation:

```text
::error::Base ref 'main' is not resolvable because the repository checkout is shallow. Please configure actions/checkout with 'fetch-depth: 0' to enable merge-base resolution.
```

---

## Local Action Installation & Package Detection

When the Action runs, it installs Codebase Inspector without requiring remote network downloads whenever local sources are available:

1. **Composite Action Path:** If `${{ github.action_path }}/pyproject.toml` exists, it installs from the action path (`uv tool install "${{ github.action_path }}" --force`).
2. **Local Repository / Monorepo:** If `./pyproject.toml` exists and declares package name `codebase-inspector` or `cbi` (e.g., when testing in this repository or a monorepo checkout), it installs locally via:
   ```bash
   uv tool install . --force
   ```
3. **Remote Git Fallback:** Only if neither local path contains a Codebase Inspector package does it fall back to installing from remote Git (`uv tool install git+https://github.com/joshuavial/codebase-inspector --force`).

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

# Vision

Working name: codebase-inspector. The product name is still open; `cbi` and `.cbi/` are placeholders that change with it.

A developer or an agent dropped into an unfamiliar codebase needs to know what the parts are, what each one does, how they connect and which tests cover them. Reading files answers this slowly and agents do it again every session. The inspector builds that picture once, keeps it current, and serves it two ways: a layered, clickable viewer for people and a query CLI for agents.

The inspector is a deterministic command-line tool. It has no LLM inside it. AI agents working in a codebase call it: the CLI parses what can be parsed, hands the agent the work that needs judgement (naming parts, writing summaries), validates the answers and stores them. `cbi prime` and `--help` teach an agent how to use it, so a skill only has to say "run `cbi prime`".

## Increments

1. **Orientation** (PRD-01). Map a repository from the workspace down to methods, with tests linked to the code they exercise. Browse it in a static viewer and query it from the CLI.
2. **Change review** (PRD-02, not yet written). Map what a branch changed onto the structure: which parts moved, which tests cover the diff, what the summaries now say. Stable node IDs in PRD-01 exist so two snapshots can be compared.
3. **Quiz** (later). Use the model's summaries and call flows to ask a developer how parts of the system work and check the answers.

## Target ladder

The sample repositories are ordered by size and by the parts of the model each one tests.

| Repo | Code files | What it tests |
|---|---|---|
| orchestra | ~100 TS | Full loop on a small repo; one manifest building four deployables |
| lms | ~440 TS/TSX | Several apps plus a shared package, Supabase, one submodule |
| fundsorter | ~1.9k Python + TS | Polyglot, compose services, flat Python test dirs, big data dirs to exclude |
| xenota, xcd | ~1.6k code in ~13k files | Python monorepo in a submodule, markdown-heavy superproject, skills with tests |

social-media-manager (~29 code files) and spokecut (~96) are the same size as orchestra or smaller. They are useful later as Rust and doc-heavy checks.

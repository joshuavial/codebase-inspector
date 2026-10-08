# Vision

Working name: codebase-inspector. The product name is still open; `cbi` and `.cbi/` are placeholders that change with it.

A developer or an agent dropped into an unfamiliar codebase needs to know what the parts are, what each one does, how they connect and which tests cover them. Reading files answers this slowly and agents do it again every session. The inspector builds that picture once, keeps it current, and serves it two ways: a layered, clickable viewer for people and a query CLI for agents.

The inspector is a deterministic command-line tool. It has no LLM inside it. AI agents working in a codebase call it: the CLI parses what can be parsed, hands the agent the work that needs judgement (naming parts, writing summaries), validates the answers and stores them. `cbi prime` and `--help` teach an agent how to use it, so a skill only has to say "run `cbi prime`".

## Increments

1. **Orientation** (PRD-01). Map a repository from the workspace down to methods, with tests linked to the code they exercise. Browse it in a static viewer and query it from the CLI.
2. **Concept map** (PRD-02). Show the repository as agent-defined concepts with labelled relationships and integration points, drilling down to code and tests, with UI components shown as wireframes.
3. **Desktop app** (PRD-03). Open projects, keep recent ones, switch between worktrees and branches, and let the CLI open the app in a given state.
4. **Change review** (PRD-04). Show what a pull request, branch or worktree changed in architectural terms, in the app, as text from the CLI, and as a Mermaid diagram and images for the PR thread.
5. **Data map** (PRD-05, not yet written). Rebuild the database schema from SQL migrations, parse queries into table reads and writes, and show an ERD with the tables each concept and function touches highlighted. Targets sample-apps and sample-saas, since sample-desktop has no database.
6. **Architecture history** (PRD-06). A changelog of the architecture over time: one entry per merge to main, replayable on the concept map in the app and printable from the CLI for agents.
7. **Team mode** (PRD-07). Commit the judgement half of the map with the code, keep it current per pull request, and gate it in CI without a model.
8. **Quiz** (later). Use the model's summaries and call flows to ask a developer how parts of the system work and check the answers.

Later still: live, Storybook-style rendering of real UI components alongside the wireframes.

## Target ladder

The sample repositories are ordered by size and by the parts of the model each one tests.

| Repo | Code files | What it tests |
|---|---|---|
| sample-desktop | ~100 TS | Full loop on a small repo; one manifest building four deployables |
| sample-apps | ~440 TS/TSX | Several apps, a shared package, a database, one submodule |
| sample-saas | ~1.9k Python + TS | Polyglot, compose services, flat Python test dirs, big data dirs to exclude |
| sample-monorepo | ~1.6k code in ~13k files | Python monorepo in a submodule, markdown-heavy superproject, skills with tests |
| sample-dotnet | C# and Vue | ASP.NET Core and Vue, mapped from a branch as well as the working tree |

Two smaller repositories (about 29 and about 96 code files) are the same size as sample-desktop or smaller. One is Rust and one is documentation-heavy. They are sideways checks, not the next step up in size.

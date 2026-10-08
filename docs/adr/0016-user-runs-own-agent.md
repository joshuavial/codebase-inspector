# ADR-0016: The user runs their own agent

Status: Accepted. Date: 2026-10-07.

## Context

The desktop app can run the deterministic scan and show the fallback map of deployables, packages and externals. The concept map still needs judgement tasks (ADR-0009, ADR-0011). The app could start an agent on an unmapped project, or call a model API itself. Either choice picks a vendor, needs credentials, and puts an LLM behind a tool that has none.

## Decision

The desktop app does not launch an agent and does not call an LLM. On a project whose judgement tasks are still open, it shows the fallback map, the task counts by kind, and a copyable instruction: run `cbi prime` in that path and complete the tasks. As answers are submitted, by whatever agent the user is running, the map updates.

Scans go through the same code as `cbi scan`. The app adds no second path that calls a model.

## Alternatives considered

- The app launches an agent. Rejected.
- The app calls an LLM API. Rejected.

## Consequences

A first open is useful before any agent has run. Finishing the concept map, the wireframes and the change narrative stays work for the user's own agent. The app shares the task list and the answer cache with the CLI. It does not need a model key. PRD-03 A9 and A11 state this.

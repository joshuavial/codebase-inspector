# ADR-0009: Deterministic CLI and agent tasks

Status: Accepted. Date: 2026-10-07.

## Context

Judgement is required for names, groupings and summaries. The first recommendation put that call inside the product: a skill would run a headless model once per batch. That chooses a vendor, hides fan-out, and makes the CLI's output depend on a model. The agents already working in these repositories can read, judge and delegate. They need a contract.

The same CLI has to answer questions, or those agents will grep the tree again.

## Decision

The inspector is a deterministic CLI. It makes no LLM call. It parses what it can parse, then hands out the work that needs judgement. `cbi tasks` lists open tasks. `cbi task <id>` prints the brief, the inputs, an input hash and the answer shape. `cbi submit` checks the answer and stores it. The calling agent writes the answer. Sending tasks to subagents is that agent's choice.

`cbi prime` prints a short guide for the repository's current state: not initialised, tasks pending, or complete. `--help` on every command states inputs, output and exit codes. A skill only has to say to run `cbi prime`.

The CLI is also the query tool. `search`, `show`, `tests-for` and `status` print text or `--json`. Prime points agents at those commands.

A submit must echo the brief's input hash. If the inputs changed, the submit is rejected and the agent fetches the task again. Accepting an answer stores it and opens the tasks that were waiting, in one transaction. Submitting the same answer twice does nothing. File summaries are cached per content hash (ADR-0006). A parent task reopens only when a child's summary text changes.

The checks cover shape: required keys, types, lengths and allowed labels. They do not check that a summary is true.

## Alternatives considered

- The tool runs a configurable headless LLM command per batch. The recommended default was `claude -p`. The skill would own that loop. Rejected.
- The tool itself fans out to subagents.
- A hand-written skill as the only documentation, with no `prime` command.
- Leaving queries to the agent grepping the repository. PRD-01 adds `search`, `show` and `tests-for` so prime can point at them.

## Consequences

Summary quality follows the agent that submitted it. The protocol version is part of the cache key, so a shape change drops old answers. The brief's JSON Schema is generated from the same checks that `submit` runs. Later task kinds (`define-concepts`, `sketch-screens`, `summarise-change`) use these same submit rules. Symbols get no summary task in PRD-01.

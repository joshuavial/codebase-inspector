# ADR-0013: Environment variables as nodes

Status: Accepted. Date: 2026-10-07.

## Context

Configuration shows up as names read in code and declared in examples and compose files. The concept map has to show those names on the part that reads them. A real env file holds secrets. Copying it into the model would put those secrets in the database, the cache and the viewer.

## Decision

The parsers record environment reads as facts, the same way they record calls. TypeScript and JavaScript: `process.env.X`, `process.env["X"]`, `import.meta.env.X`, and a spread of `process.env` as a pass-through on the file. Python: `os.environ["X"]`, `os.environ.get`, `os.getenv`, and `environ` imported from `os`. Only names matching `[A-Z_][A-Z0-9_]*` are kept.

Each name is a node with kind `env`, display kind `env var`, and id `<workspace>:env:<NAME>`. A `reads_env` edge runs from the reading symbol, or from the file when the read is at top level. A default is kept when the code supplies it as a literal (`??`, `||`, or the Python default). Declarations add `declared_in` from `.env.example`, `.env.sample`, compose `environment` and wrangler `[vars]`.

Files named `.env` or `.env.*`, other than `.env.example` and `.env.sample`, are skipped before they are opened. They are not file nodes.

The viewer shows a count on the concept box, lists the vars in the drawer, and includes the marker in the key. Search finds a var by name. This is PRD-02 scope.

## Alternatives considered

- Leave env reads as ordinary calls, with no nodes of their own.
- Read `.env` so the viewer can show current values. Rejected. Those files are never opened, and values from them are never stored.

## Consequences

A spread is one read of `*` on the file, not an invented list of names. Example values come only from the example or sample file. If both exist and disagree, the lexicographically first path wins. Compose and wrangler contribute declaration paths. Assignment and deletion are not reads. An augmented assignment is a read.

# Remaining static test boundaries

`unsupported_test_mechanism` records a source location and the mechanism the
inspector cannot fully resolve. It remains visible even when a test has other
static bindings: a partial link is not a claim of complete coverage.

Computed pytest plugin lists, computed fixture names, fixture factories and
dynamic `request.getfixturevalue` selection are runtime registration boundaries.
Literal registered fixtures and literal `getfixturevalue` names are resolved.
Directly parametrized arguments are values rather than fixture requests unless
pytest's `indirect` option requests fixture resolution.

The same diagnostic kind covers unbounded import/file/SQL paths, child-process
execution and in-process HTTP app/URL/handler ambiguity. `cbi status` counts
these independently from `unmatched_test`, which means a test has no tracked
static target. Neither category establishes that a test is ineffective.

Use explicit static paths or ingest per-test coverage to supply stronger
execution evidence. Scanning only reads source syntax; it never invokes pytest,
imports a target module, launches a subprocess or starts an HTTP server.

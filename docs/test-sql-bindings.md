# SQL and migration test contracts

A Python test that explicitly enumerates a literal directory with `Path.glob`
or `Path.rglob` links to the tracked SQL files selected by that pattern. Reads
of the enumerated file variable preserve the same links. Directory constants,
local variables and `Path(__file__)` expressions use the literal evaluator
described in [test path bindings](test-path-bindings.md).

These are static contract relationships (`source=treesitter`, confidence 0.8,
`via=sql_glob`), not proof that SQL executed. A normal `*.sql` glob selects only
that directory; `rglob` and explicit `**` patterns can select descendants. The
resolver neither reads database contents nor walks the filesystem. It only
matches SQL paths already in the current workspace model, never files selected
by a guessed schema or test name. An unresolved pattern produces a
`unsupported_test_mechanism` diagnostic instead of a speculative test link.

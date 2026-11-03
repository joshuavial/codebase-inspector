# Literal test imports and file contracts

Python tests can bind to tracked modules loaded with `importlib.import_module`
(including imported aliases), and to files loaded with
`importlib.util.spec_from_file_location`, `runpy.run_path`, `open`, or
`Path.read_text` / `read_bytes`. These supplementary static links use
`source=treesitter`, confidence 1.0, and an edge `via` attribute describing the
mechanism. They describe the literal target, not measured execution or coverage.

A read-only AST pass follows module and function-local literal constants,
`Path(__file__)`, `.parent`, `.parents[n]`, literal `/` and `joinpath` joins,
`os.path` joins, and literal string concatenation. It respects imported aliases,
shadowed parameters, reassignment, and conditional scopes. Context-manager
targets replace prior literals; exception handlers and `finally` blocks do not
reuse values that preceding `try` regions may have overwritten. Each `match` case starts from its own incoming snapshot, and pattern captures
replace prior literals. Literal assignments within each branch still bind in sequence. It uses the existing
workspace module and tracked-file resolvers. It never imports or executes target
code, evaluates arbitrary expressions, or walks directories outside the model.

Unknown values and missing or external targets produce
`unsupported_test_mechanism` diagnostics with a source location and mechanism.
A resolved target removes the unmatched-test status only for the linked test
file; a static relationship does not establish coverage of a whole module.

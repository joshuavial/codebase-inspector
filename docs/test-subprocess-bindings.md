# Subprocess test bindings

Static test resolution never executes a child program. A literal argv pointing
to a tracked script, or `python -m` with a literal tracked module, produces a
`tests` edge at confidence 0.8 with `via=subprocess`. Literal inline Python
programs contribute their visible tracked imports at the same confidence.

Inline code may also construct dynamic paths and imports. It therefore retains
an `unsupported_test_mechanism` diagnostic, even when visible imports bind.
Dynamic argv, shell commands and unresolved child programs carry the same
explicit execution-boundary diagnostic, including source path and line. Status
counts these diagnostics separately from tests with no bindings.

All supplemental Python mechanisms share a per-resolve syntax-tree cache and
existing symbol spans. Syntax errors and tracked symlinks are skipped. No target
module is imported and no target tests are run by the inspector.

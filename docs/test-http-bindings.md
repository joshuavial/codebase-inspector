# In-process HTTP test links

Static Python test linking recognizes `TestClient` imported from
`fastapi.testclient` or `starlette.testclient`, including import aliases and
context-manager use. Its application argument must identify a tracked app.
Literal HTTP calls on that client link the test case to the registered production
handler, with `source=treesitter`, confidence `0.9` and `via=in_process_http`.

Application/router mount facts determine the eligible handlers and full paths.
An unrelated application with the same route receives no link. Function parameters and local bindings
shadow file-scope app/client aliases; registered fixture clients are restored only
for the fixture arguments that pytest selected. Conditional aliases remain known
only when all branches agree. Literal URL IDs
match server route parameters, query strings are ignored and verbs must agree.
An ambiguous handler selection remains unresolved. Remote HTTP libraries and
mock-only applications do not imply a test link to a production route.

Registered pytest fixtures reuse the fixture resolver's selected bindings,
including named fixtures and ancestor `conftest.py` registrations. A fixture that
returns or yields a statically identified client supplies that client's app
context to its requesting test. Function indexing matches each AST declaration
(including its first decorator) to the corresponding modeled symbol start. An
unmodeled nested helper cannot replace its enclosing test or fixture body. Ordinary helper functions with fixture-like names
do not register a client. Parsing and matching never import or run target code.

Dynamic URLs and application arguments that cannot identify a tracked app receive
`unsupported_test_mechanism` diagnostics with source location and a `dynamic_url`
or `dynamic_app` resolution boundary. Ambiguous handler selection is labelled
`ambiguous_route`. Runtime app factories and arbitrary client wrappers require
runtime coverage evidence; they do not produce speculative handler links.

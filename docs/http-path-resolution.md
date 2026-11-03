# Static client path resolution

HTTP client facts preserve bounded literal expressions before matching server routes.
File-scope literal configuration, local string values, concatenation and conditional
alternatives compose inside TypeScript templates and Python f-strings. A TypeScript
parameter whose type is a finite string-literal union, directly or through a local
type alias, expands to those resource or action names. Expansion is capped at 64
alternatives to keep scanning bounded.

For example, with `const API_BASE = "/v2"` and a parameter
`resource: "books" | "films"`, the expression
`` `${API_BASE}/admin/${resource}/${id}/revisions` `` produces both
`/v2/admin/books/{param}/revisions` and `/v2/admin/films/{param}/revisions`.
A request wrapper forwarding a path through a literal configured prefix preserves
that prefix on its callers. An absolute literal API base drops its scheme and host
while retaining its configured path prefix. The resulting HTTP edges retain the concrete server
path, including its mount prefixes.

Unbounded parameters remain `{param}`. They can match a server path parameter,
but cannot stand in for a server's literal resource or action. A broad type such
as `"books" | string` is unbounded, and a parameter shadows a file-scope literal
with the same name. Dynamic calls retain unresolved diagnostics instead of
inventing links to every concrete route. Values requiring runtime configuration,
external module evaluation or arbitrary computation are not evaluated; target
code is never executed.

Calls with entirely dynamic URLs are retained as `http_unresolved_calls` facts,
with caller and source line. They produce `unmatched_http_call` diagnostics marked
`resolution=dynamic_client` and never become guessed HTTP edges. For a recognized
request wrapper, local call sites carry this diagnostic; an uncalled wrapper
retains its own unresolved site so the resolution boundary stays visible.

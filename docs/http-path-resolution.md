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

Conditional statement arms use independent copies of the incoming literal values.
A name that an arm can assign becomes unknown after the statement. Loop bodies
start with names that the loop can assign unknown, since the loop can run zero
or multiple times. Try bodies, handlers and finalizers also use independent
uncertain inputs for names they can assign, because an exception can interrupt
an assignment sequence. Derived URLs retain that uncertainty and produce an
unresolved-call diagnostic rather than guessing a server prefix from a suffix.
Finite conditional expressions and request wrappers with bounded literal branch
prefixes still retain all their alternatives, up to the same 64-alternative cap.

TypeScript `const` and `let` bindings stay inside their lexical block, including
loop and catch scopes. Function-scoped `var` declarations shadow module literals
before their declaration. Python function-local assignments likewise shadow
module values throughout the function. A closure binding that shadows a module
constant remains unresolved rather than borrowing the same-named global value.
These rules also govern file-scope configuration collection; values encountered
inside conditional or nested scopes do not become unconditional global settings.

Local function and class declarations also shadow same-named module literals.
Their declared names are collected without treating their nested bodies as outer
assignments. A declaration replaces any earlier local literal, and class-body
attributes stay inside the class namespace. The resulting function/class value
is not treated as a URL string. Named function and class expressions keep their
self-binding inside their body and leave an outer same-named literal unchanged.

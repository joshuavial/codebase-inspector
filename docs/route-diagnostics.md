# HTTP resolution boundaries

An `unmatched_http_call` is a static mapping limitation, not a dead-route finding.
Every new diagnostic has a `resolution` label. `cbi status` includes counts per
label in text and in `diagnostics.unmatched_http_call.resolution_boundaries`.

- `static_unresolved`: no tracked route or statically resolved consumer was found.
  The absence of a binding does not establish that a route is unused.
- `dynamic_client`: a client path contains unknown segments. For server routes,
  a compatible generic path is evidence of a possible consumer, without an edge.
- `external_callback_candidate`: a webhook/callback-shaped path has no resolved
  consumer. This is a path-based hint, not proof of external use or authentication.

Only concrete static matches create HTTP edges. Callback naming and wildcard
compatibility never invent a consumer. Ingest runtime evidence separately when
static source cannot establish usage.

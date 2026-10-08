# ADR-0005: Static test links plus ingest

Status: Accepted. Date: 2026-10-07.

## Context

The map should show which code has tests with no extra setup. Coverage and pass or fail are already files the projects know how to write, and they are closer to the truth than a static guess. Running those tests from the inspector would execute repository code and would depend on that project's toolchain.

## Decision

Static links are always computed. A test case links to the symbols it calls and, at lower confidence, to the modules it imports. A literal read of a tracked file links the test to that file. A file-name match adds a link: `x.test.ts` to `x.ts`, and `test_x.py` to `x.py`. The overlay labels static links as static.

Confidence on a static `tests` edge is the call's own confidence, 1.0 for a literal read, 0.8 for a name match, and 0.5 for an imported code file. A test file with no links is an `unmatched_test` diagnostic.

`cbi ingest` reads artifacts the user supplies. PRD-01 accepts lcov, coverage.py JSON (including per-test contexts) and JUnit XML. Line coverage maps onto source. When the tests ran on compiled output, the map goes through source maps, because compilation moves lines. Results map onto test-case nodes. Several artifacts merge. A later artifact from the same path replaces rows from that path.

The CLI never runs the target's tests or any other target code. `cbi prime` prints the command that writes artifacts outside tracked paths.

## Alternatives considered

- Static links only.
- Ingested artifacts only, with no static links.
- The inspector runs the project's tests. Rejected for PRD-01 and kept as a standing rule.
- Ingest Istanbul and Playwright reports in PRD-01, as the interview first listed. They wait until a target needs them.

## Consequences

A static link overstates coverage when a test imports a module and exercises one function. The label says the link is static. Ingested per-test contexts add `tests` edges at confidence 1.0 with source `coverage`. A Python test that does not mirror the source tree matches the single `<stem>.py` in its own project. An ambiguous stem matches nothing. Paths that still miss a tracked file are `unmapped_coverage` diagnostics.

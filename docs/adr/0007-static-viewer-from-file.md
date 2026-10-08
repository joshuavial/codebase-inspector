# ADR-0007: Static viewer opened from file://

Status: Accepted. Date: 2026-10-07.

## Context

PRD-01 needs a picture a person can open after one command. A server would be another process to install and keep running. The page has to work from a `file://` URL. In that context `fetch` of local files is blocked, so the data cannot be loaded as JSON over HTTP.

## Decision

`cbi build` writes a static folder: `index.html`, plain JavaScript, CSS and data scripts. Each data file calls a global loader and is included with a script tag. A prebuilt search index loads after first paint. Until it arrives, search matches names in the tree already loaded. There is no server in PRD-01. The folder opens from disk.

The first load carries the tree down to file level, edges rolled up to that level, and a manifest of symbol chunks. Symbol detail is loaded by group. An edge is written into the chunks of both ends.

## Alternatives considered

- A single self-contained HTML file.
- A served application. Rejected for PRD-01.
- The recommendation, which was kept: a static directory, opened from `file://`, with lazy data chunks and a prebuilt search index.

## Consequences

The viewer has no application build of its own. Rollups are computed when the folder is written, so the page does not aggregate edges. ADR-0011 changes what the main view draws. This ADR stays the delivery: the same folder, still opened from disk, is what the desktop shell shows (ADR-0019). A Playwright smoke test loads a built viewer from `file://`.

# ADR-0014: Two-way navigation

Status: Accepted. Date: 2026-10-07.

## Context

In the concept mockup, clicking a node owned by another concept jumped straight there. The link that justified the jump was not on screen, and the way back was easy to miss. Drill-down, search, drawer links and grey nodes each had a way in. They did not share a way out. The developer made two-way navigation a core principle: every entry needs an obvious return.

## Decision

Every way into a view leaves a visible way back.

Drilling down uses the breadcrumb. Esc goes up one level, the same action as clicking the parent crumb. A sideways move leaves a "Back to <origin>" chip. That covers a jump to another concept, a search result, a drawer link and a grey node. Backspace and the browser's back control do the same and restore the previous zoom and selection.

Clicking a grey node selects it first. The drawer shows the link in both directions, and navigation is a second, explicit step. On arrival, the edges to and from the origin are highlighted. Esc still means up one level, not back along the jump.

The top bar holds the breadcrumb and the Back chip. "Used by" and "Uses" are the first section of the concept drawer, grouped and linked. Hovering an entry highlights its group in the diagram. Callers and callees in the drawer name the concept and the module that own the function. `cbi show` prints the same.

## Alternatives considered

- Jump as soon as a grey node is clicked, with browser history as the only return.
- One-way drill-down, with search as the way back.
- A context strip in the top banner for "used by" and "uses". That strip was removed after it was tried. The lists moved into the drawer.

## Consequences

PRD-02 V0 states the rule. PRD-03 keeps it when the window adds the project and the branch. PRD-04 comparison mode keeps it. View state lives in the URL hash, so a reload can restore the place. Opening the desktop app from a link leaves the same Back chip (ADR-0019).

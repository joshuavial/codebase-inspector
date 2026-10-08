# ADR-0012: Agent-drawn wireframes

Status: Accepted. Date: 2026-10-07.

## Context

A leaf that lists a component's props still does not show the screen. Three ways to show it were on the table: a sketch from the source, screenshots from a running build, and a live render in the style of Storybook. The last two need the target built and running. The inspector does not run target code (ADR-0005, ADR-0009).

## Decision

A `sketch-screens` task asks the agent to sketch each UI screen as data. A screen is a tree of regions. A region has a label, a component, a layout hint (`row`, `column` or `grid`), the static text from the JSX, and a short list of style hints. Dynamic values are written as `{expr}` and drawn as placeholders.

The CLI checks that every named component is a real component node, and that every component owned by a UI concept appears on a screen or in an `unsketched` list with a reason. The sketch is stored with the model, in `.cbi/screens.json`, and rendered from that data into plain elements. It is never inserted as HTML. Selecting a component highlights its region and shows its props, what it renders, and what data it reads. The code diagram stays one toggle away.

Live, Storybook-style rendering of real components is a later increment in the vision. It is not part of PRD-02.

## Alternatives considered

- Screenshots taken from a running build and attached to the component. Rejected.
- Live rendering of the real components. Rejected for PRD-02.
- Bare boxes, with no text and no layout. A follow-up required the real static text from the JSX and minimal styling. The sketch carries both.

## Consequences

Wireframe text is data. Style hints are class names the viewer defines, not a copy of the target's CSS. An agent cannot put markup through the sketch. The task opens after concepts exist, and only when the repository has React components. Greyscale keeps the sketch distinct from a finished UI.

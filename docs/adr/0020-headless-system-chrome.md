# ADR-0020: Headless system Chrome for review images

Status: Accepted. Date: 2026-10-07.

## Context

ADR-0018 needs PNG and SVG of the concept map before and after a change. Those pictures have to match the layout the viewer already draws with elkjs. A second layout implementation would diverge. The command also has to finish on a machine that has no extra browser installed by this project, and it has to produce `review.md` either way.

## Decision

`cbi review` writes a static render page from the viewer code, loads it with headless system Chrome, and takes PNG with Chrome's screenshot flag. The page writes the SVG markup for `before.svg` and `after.svg`. The page marks when layout is finished, and the screenshot waits for that.

If Chrome or Chromium is not on the machine, the images are skipped and the command says so. `review.md` and the Mermaid diagram are still written.

## Alternatives considered

- Playwright, with a browser the tool manages. Rejected.
- Pure-Python SVG, with no browser. Rejected.
- No image files. Rejected. The files are produced when system Chrome is present.

## Consequences

The Python package does not ship a browser. Image generation uses the browser the machine already has, so colours, layout and change marks stay the ones the viewer draws. A checkout without Chrome still gets the Markdown review and can post it. The render page is static, same as ADR-0007, and takes the change list as data.

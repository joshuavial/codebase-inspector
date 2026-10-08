# ADR-0018: Mermaid plus image files for pull requests

Status: Accepted. Date: 2026-10-07.

## Context

Reviewers on a pull request will not install the inspector. The pull request thread has to show the architectural change anyway. GitHub renders a Mermaid diagram inside a Markdown comment. A picture of the map before and after is still wanted as a file. Putting those pictures on a host, or committing them to the branch, would make the tool publish or write to the repository.

## Decision

`cbi review` writes a review folder. `review.md` holds the summary counts, a `cbi://` link (ADR-0019), the structural diff (ADR-0017), untested changes, changed integration points, and a Mermaid flowchart of the changed concepts and their direct neighbours. It also writes `before.png`, `after.png`, `before.svg` and `after.svg`.

`--post` publishes `review.md` as a pull request comment through `gh`. A later run finds that comment by a hidden marker and edits it. The flag is required. Images stay files. The user or an agent attaches them. The Mermaid diagram renders in GitHub without the images.

The diagram draws changed concepts and their direct neighbours. Everything else is text.

## Alternatives considered

- Images only, which need hosting or a binary attachment before the comment is useful.
- Mermaid only, with no PNG or SVG files.
- The tool hosts the images, or commits them onto the branch. Both were rejected. The decision is Mermaid in the comment, plus image files beside it.

## Consequences

A reviewer sees a diagram with no extra install. PNG and SVG need a renderer on the machine that runs the command (ADR-0020). A large diff stays readable because unchanged concepts are not all drawn. Posting twice leaves one inspector comment.

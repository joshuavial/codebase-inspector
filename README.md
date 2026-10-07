# codebase-inspector

`cbi` is a deterministic CLI that maps a git repository into a layered model (workspace, deployables, packages, folders, files, symbols, tests) that AI agents can query and people can browse in a static viewer. It never calls a model and never runs the target's code.

Design docs: `docs/vision.md`, `docs/prd-01-orientation-map.md`, `docs/architecture.md`, `docs/implementation-plan.md`.

## Install

Needs Python 3.11 or later and [uv](https://docs.astral.sh/uv/).

```
uv tool install .
cbi prime
```

## Develop and test

```
uv sync
uv run pytest
uv run cbi --help
```

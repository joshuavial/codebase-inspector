# codebase-inspector

`cbi` maps a git repository into a layered model: workspace, deployables, packages, folders, files, symbols and tests. People browse it in a viewer. Agents query it from the command line. The tool never calls a model and never runs the target's code. Agents supply the judgement (names, summaries, concepts) through a task protocol, and `cbi check` can gate that work in CI.

## Install

Needs Python 3.11 or later and [uv](https://docs.astral.sh/uv/).

```
uv tool install .
cbi prime
```

## Quick start

From the repository to map:

```
cbi prime
cbi scan
cbi build
cbi open
```

`cbi prime` prints the next step for the current repo. `cbi scan` builds the deterministic model. `cbi build` writes a static viewer that opens from disk. `cbi open` opens the desktop app on that project when the app is installed.

Judgement tasks (`cbi tasks`) ask for file summaries and a concept map. Submit answers with `cbi submit`. Query with `cbi search`, `cbi show` and `cbi tests-for`.

## Desktop app

The app in `app/` is a thin Electron shell over the installed `cbi` CLI. It remembers recent projects, switches worktrees and branches, and shows the same viewer. See `app/README.md`.

```
cd app
npm install
npm start
```

## Team mode

`cbi team init` opts a repository in and prints a GitHub Actions snippet. The job checks out the repo, installs cbi and runs `cbi check`. The check reads the working tree. It does not call a model or the network.

```yaml
- uses: actions/checkout@v4
- uses: astral-sh/setup-uv@v5
- run: uv tool install .
- run: cbi check
```

## Develop and test

```
uv sync
uv run pytest
uv run cbi --help
```

Design notes live in `docs/vision.md`, `docs/architecture.md` and `docs/implementation-plan.md`.

## License

Released under the MIT license. See [LICENSE](LICENSE).

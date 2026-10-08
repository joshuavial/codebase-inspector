# codebase-inspector

`cbi` maps a git repository into a layered model: workspace, deployables, packages, folders, files, symbols and tests. People browse it in a viewer. Agents query it from the command line. The tool never calls a model and never runs the target's code. Agents supply the judgement (names, summaries, concepts) through a task protocol, and `cbi check` can gate that work in CI.

## Install

You need git and [uv](https://docs.astral.sh/uv/) (Python 3.11 or later). Desktop builds are on the [Releases](https://github.com/joshuavial/codebase-inspector/releases) page. The builds are unsigned.

### macOS

Download the arm64 `.dmg` or `.zip`. Move Codebase Inspector to Applications.

Gatekeeper blocks an unsigned app the first time you open it. Control-click the app, choose Open, then Open again. After it is in Applications you can also clear the download flag:

```
xattr -dr com.apple.quarantine "/Applications/Codebase Inspector.app"
```

### Windows

Download the `.exe` installer or the `.zip` and run it.

SmartScreen says Windows protected your PC. Choose More info, then Run anyway.

### Linux

Download the `.AppImage` or the `.deb`. Mark the AppImage executable (`chmod +x`) and run it. Install the `.deb` with `sudo apt install ./<downloaded.deb>`, using the file name from the release.

### Command line

From a checkout:

```
uv tool install .
```

From the 0.1.0 wheel:

```
uv tool install https://github.com/joshuavial/codebase-inspector/releases/download/v0.1.0/codebase_inspector-0.1.0-py3-none-any.whl
```

Or from git:

```
uv tool install git+https://github.com/joshuavial/codebase-inspector
```

Then `cbi prime`.

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

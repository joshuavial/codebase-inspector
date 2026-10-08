# Codebase Inspector app

A thin Electron shell over the installed `cbi` CLI. It opens a git repository, runs `cbi init` (when `.cbi/ignore` is missing), `cbi scan` and `cbi build`, and shows the viewer that build writes. The CLI is unchanged: the app and the CLI share the repository's `.cbi/` model.

Journeys covered: open a project, the first map, the recent list, switching worktrees and branches, and `cbi open` / `cbi://` links. `cbi://` links are handled in this process (`open-url` and a second instance). `npm start` registers the scheme for the dev Electron binary only when `CBI_SKIP_PROTOCOL` is unset. A packaged app does not register the `cbi://` scheme or its icon with macOS until it is launched from the place you keep it. `scripts/install-app.sh` builds the app, installs the `cbi` CLI, and puts the app in `/Applications`.

## Requirements

Node 20 or later, and the `cbi` CLI on `PATH` (`uv tool install .` from a checkout). A packaged app does not inherit a terminal's `PATH`, so it also looks in `~/.local/bin/cbi`. Set another path on the start screen, or launch with `CBI_BIN` pointing at the executable.

## Develop

```
cd app
npm install
npm start
```

`npm start` compiles TypeScript and opens the shell. Recent projects, the cbi path, and per worktree or branch view state (`views.json`) are JSON files in the app's userData directory (`~/Library/Application Support/Codebase Inspector`). `CBI_APP_USER_DATA` points that directory somewhere else. The smoke test also sets `CBI_PICK_FOLDER` so Open folder returns that path instead of the system dialog.

## Test

Unit tests use node:test, compiled with `tsc` and run as plain JavaScript. No test runner package.

```
npm test
```

The Playwright smoke launches the Electron app, opens a temporary git repository through the folder button, and checks the fallback map (the `fixture-cli` deployable). It needs `uv` and this checkout's Python environment.

```
npm run smoke
```

## Package

```
npm run package
```

This writes an unsigned arm64 app to `release/mac-arm64/Codebase Inspector.app`. `scripts/install-app.sh` copies that app to `/Applications` and installs the CLI. Gatekeeper will refuse a double-click until the app is signed; `npm start` is the way to run it in development. A tagged release also builds an unsigned Windows installer and zip, and a Linux AppImage and deb.

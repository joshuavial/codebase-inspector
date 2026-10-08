# ADR-0019: Electron shell over the CLI

Status: Accepted. Date: 2026-10-07.

## Context

The desktop app opens projects, remembers them, and switches worktrees and branches. It has to show the same map as the static viewer and run the same scans. A second reader of the SQLite model would drift from `cbi`. The CLI also has to put the app on a chosen project, version and node, including a pull request diff, so an agent can bring that view to the front.

## Decision

The app is a thin Electron shell over the installed `cbi` command. The window loads the viewer folder that `cbi build` writes. Init, scan, build, status, worktrees and `scan --ref` are `cbi` invocations with a fixed argument list, not a shell. The app does not read or write the model itself. The Python package is unchanged. The app uses `cbi` on `PATH`, or a path set in its settings.

The app lives in `app/`. It is TypeScript, packaged with electron-builder as an unsigned arm64 `.app` for macOS, following sample-desktop's packaging.

`cbi open` resolves the repository and the requested version, focuses the app, and prints a `cbi://` link. The app registers the scheme. It checks every parameter: the path is a git repository on disk, and refs resolve. Anything else is refused with a message in the window. A link opened while the app is running switches the existing window and leaves a Back chip (ADR-0014). Opening a state never checks out a branch, creates a worktree, stashes, or otherwise changes a ref or a working tree.

Recent projects are stored in the app's user data: path, display name, pin, last opened, last view. A project is keyed by its main worktree. A linked worktree is mapped in place in its own `.cbi/`. A branch or commit with no worktree is mapped with `cbi scan --ref` into a database under the model dir, from git objects. That database is reused while the commit is unchanged.

## Alternatives considered

- Tauri. Rejected.
- pywebview. Rejected.
- The app reads SQLite and watches files itself, duplicating the CLI.
- The CLI only prints a filesystem path, and the user finds the window. `cbi open` and `cbi://` were chosen so a terminal, a pull request comment or a chat link can open a state.

## Consequences

The app and the static viewer are one UI. macOS on Apple Silicon is the first platform. Windows and Linux are outside PRD-03. The app stores nothing in the repository beyond the existing `.cbi/`. File watches debounce and then run `cbi scan` and `cbi build`. The viewer reloads and keeps its URL hash. The shell still does not launch an agent (ADR-0016).

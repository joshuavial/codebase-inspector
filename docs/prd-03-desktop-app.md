# PRD-03: Desktop app

Builds on PRD-01 (CLI and model) and PRD-02 (concept map viewer). The viewer stays the same; this increment gives it a home that knows about projects, worktrees and branches.

## Problem

Today a person uses the inspector by running `cbi init`, `cbi scan` and `cbi build` in a terminal, then opening an HTML file from a hidden folder. Each repository, worktree and branch is a separate manual run, and nothing remembers which projects were mapped. Finding and switching maps across repositories and their worktrees is most of the friction.

## Users

- **The developer**, who wants to open a project's map in a couple of clicks, come back to it later, and flip between the worktrees and branches being worked on.
- **AI agents** are unchanged: they still do the judgement work through the CLI. The app does not run agents.

## Outcome

A desktop app that opens any git repository as a project, remembers it, and shows its concept map for whichever worktree or branch is selected, kept current as the code changes.

Success signals:

- The developer opens a repository that has not been mapped before and sees a map within seconds, without using a terminal.
- Reopening the app shows recent projects, and one click brings back the last map.
- In a project with several worktrees, the developer switches between them from a list and each shows its own map.
- A branch that is not checked out anywhere can be viewed without the app touching the working tree.

## User journeys

1. **Open a project.** From the start screen, choose a folder, drag a folder onto the window, or pick from recent projects. A folder inside a git repository opens that repository; a folder that is not in a repository is refused with a clear message.
2. **First map.** On a project with no model, the app runs the deterministic scan and shows the fallback map (deployables, packages, externals). A panel says the concept map needs an agent, shows how many judgement tasks are waiting, and offers a copyable instruction for the user's own agent ("run `cbi prime` in <path> and complete the tasks"). As the agent submits answers, the map updates live.
3. **Come back.** The start screen lists recent projects with name, path, last opened, current branch and whether the map is complete or waiting on tasks. Projects can be pinned, renamed for display and removed from the list. A project whose folder has moved or been deleted is marked and can be located again or removed.
4. **Switch worktree.** A project shows its worktrees (the main checkout and every linked worktree, from `git worktree list`) with branch names. A worktree whose directory name is recorded in local git config as `cbi.worktree.<handle>` is labelled with that directory name; otherwise the label is the branch name. Selecting one shows that worktree's map, scanned in place with its own `.cbi/`.
5. **Look at a branch.** The same switcher lists local branches (and, on request, remote ones). Selecting a branch that is not checked out maps it from git objects, never by checking it out or creating a worktree.
6. **Stay current.** While a worktree is open, file changes trigger a rescan after a short pause and the map updates in place, keeping the user's position and selection. The header shows when the map was last scanned and whether the agent work is stale.
7. **Open from the CLI.** `cbi open` in a repository opens the app on that project's current worktree. Flags select the state: `--worktree <name>`, `--branch <name>`, `--commit <sha>`, `--node <id or name>` (drilled to that concept or function, with the drawer open). An agent or a script can use it to put a specific view in front of the user. The same states are reachable as `cbi://` links, so a link in a terminal, a PR comment or a chat message opens the app in that state. If the app is already open, it switches to the state in the existing window, and the Back chip returns to where the user was.
8. **Share.** Any view can be exported as the static viewer folder (as `cbi build` writes today) or opened in the browser.

## Requirements

### Projects

- A1. Open a project from a folder chooser, drag and drop, or the recent list. The project root is the repository's main worktree, whichever worktree folder was chosen.
- A2. Store recent projects locally (path, display name, pinned, last opened, last selected worktree or branch), most recent first, with pin, rename and remove. Nothing is stored in the repository other than the existing self-ignoring `.cbi/`.
- A3. Detect missing or moved project folders and offer to relocate or remove them.

### Worktrees and branches

- A4. List the project's worktrees and local branches, marking the current one and any that already have a model. Remote branches are listed on request after a fetch the user starts.
- A5. A worktree is mapped in place (its own `.cbi/`). A branch without a worktree is mapped from git objects into the app's own storage, read-only. The app never runs `git checkout`, `git switch`, `git worktree add`, `git stash` or any command that changes a working tree or ref.
- A6. Switching keeps per-worktree view state (position, selection, open drawer sections), so going back returns to where the user was.
- A7. Answers to judgement tasks are shared across worktrees and branches through the existing answer cache, so a worktree that differs from main in a few files only needs those files' tasks.

### Map and freshness

- A8. The app shows the PRD-02 viewer unchanged, including two-way navigation, with the project, worktree and branch in the window's top bar.
- A9. Scans run in the background through the same code as `cbi scan`; the app never calls an LLM or runs an agent.
- A10. File changes in the open worktree rescan automatically after a short pause. A branch view rescans when the branch's head moves.
- A11. When judgement tasks are open, a panel shows their counts by kind and a copyable agent instruction; the map refreshes as answers arrive, whoever submits them.

### Opening in a state

- A12a. `cbi open [path] [--worktree NAME | --branch NAME | --commit SHA] [--node ID]` opens or focuses the app in that state, adding the project to the recent list if needed. It prints the equivalent `cbi://` link.
- A12b. A `cbi://` URL scheme registered by the app encodes the same state (project path or remote, version, node, and any comparison from PRD-04). Unknown or unsafe values are refused with a message in the app, never acted on silently.
- A12c. Opening a state never changes the repository; the version rules in A5 apply.

### Platform

- A12. macOS on Apple Silicon first, installed as a normal app. The CLI keeps working on its own; the app and the CLI read and write the same `.cbi/` model.

## Acceptance criteria

- B1. Opening sample-desktop from the folder chooser shows its fallback map without a terminal, and its concept map once an agent has completed the tasks.
- B2. After a restart, the recent list shows sample-desktop, codebase-inspector and sample-monorepo with correct branches and states, and one click restores the last view.
- B3. In a repository with several worktrees, every worktree is listed with its branch and label, and switching shows each one's own map within two seconds when already scanned.
- B4. Selecting a branch that is not checked out shows its map, and `git status` and `git worktree list` in the repository are unchanged afterwards.
- B5. Editing a file in the open worktree updates the map without losing the current position.
- B6a. `cbi open --branch <branch> --node "Sign in"` from a terminal brings the app to the front on that branch's map, drilled to Sign in; pasting the printed `cbi://` link into a browser does the same.
- B6. Deleting a project's folder marks it as missing on the start screen instead of failing.

## Non-goals

- Launching or managing agents from the app (decided: the user runs their own agent).
- Editing code, committing, or any git operation that changes the repository.
- Windows and Linux builds.
- Comparing two worktrees or branches; that is PRD-04.
- Accounts, sync or sharing projects between machines.

## Assumptions and risks

- Mapping a branch from git objects needs a scan mode that reads blobs instead of the working tree. That mode is also what PRD-04 needs for comparisons, so it is built once.
- Large repositories (sample-monorepo) take about 25 seconds to scan cold; the first open shows progress rather than a blank window.
- Live rescans on every save could be costly on large repos; the pause and the no-change shortcut keep them cheap, and this is checked on sample-monorepo.

## Open questions

- Worktree label: the worktree directory name when local git config contains `cbi.worktree.<handle>`, otherwise the branch name.

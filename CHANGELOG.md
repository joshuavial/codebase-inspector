# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-10-10

First public release.

### Added

- `cbi scan` maps a git repository into a model of the workspace, deployables, packages, folders, files, symbols and tests. The tool does not call a model and does not run the target's code.
- Judgement tasks (`cbi tasks`, `cbi submit`) ask an agent for file summaries and a concept map.
- Concepts and screen sketches (React, Vue, HTML pages and server templates), stored in the model and shown in the viewer.
- Queries: `cbi search`, `cbi show`, `cbi tests-for` and `cbi status`. Reviewer queries: `cbi hotspots`, `cbi orphans`, `cbi cycles` and `cbi deps`.
- `cbi context` writes a short markdown brief for an agent.
- `cbi diff` compares two versions of the model.
- `cbi review` writes `review.md` with a Mermaid flowchart, and before and after PNG and SVG images when Chrome or Chromium is installed.
- `cbi ingest` reads lcov, coverage.py JSON and JUnit XML.
- Team mode (`cbi team init`) and `cbi check` for CI. The check reads the working tree. It does not call a model or the network.
- `cbi open` hands the desktop app a `cbi://` link. `cbi open-file` opens one file in the editor.
- A static viewer that opens from disk, with no server: a concept map, wireframes and a comparison.
- A desktop app for recent projects, worktrees and branches, a live rescan, the same viewer, and `cbi://` links.
- The app and `cbi prime` say when a newer release is available, with release notes and a download link. Nothing installs itself.
- `cbi open` and `cbi://` links open the app in the background without taking focus.
- Languages: Python, TypeScript and JavaScript (including TSX), Vue, and C#.

### Known limits

- Release builds are unsigned. macOS Gatekeeper and Windows SmartScreen warn the first time you open one.
- macOS is the primary development and test platform. Windows and Linux builds are produced, and the command line and the app avoid macOS-only paths, but day to day testing happens on macOS.

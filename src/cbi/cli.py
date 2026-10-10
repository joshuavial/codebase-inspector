"""Command line entry point for cbi."""

import argparse
import datetime as dt
import json
import os
import sqlite3
import shutil
import sys
import time
from pathlib import Path

from cbi import build, check, concepts, context, data, diff, docs, editor, files, graph, history, ingest, manifests, open_link, parse, parts, prime, query, render, resolve, review, screens, store, tasks, team, update_check
from cbi.ids import file_id

COMMANDS = {
    "init": "Create .cbi/ in this repo and write the ignore file.",
    "team": "Opt in to committing the map's judgement.",
    "scan": "Map the repo into .cbi/model.db and open judgement tasks.",
    "check": "Fail when changed files have no summary, owner or committed answer.",
    "worktrees": "List this repo's worktrees and local branches.",
    "prime": "Print a guide to this tool for the current repo's state. Start here.",
    "status": "Show scan state, task counts and diagnostics.",
    "search": "Full-text search over every node.",
    "show": "Show a node: summary, children, relationships, tests.",
    "context": "Print a short Markdown description of a node to paste into an agent.",
    "tests-for": "List the tests linked to a node.",
    "hotspots": "Rank files, folders, packages and concepts by fan-in, fan-out, size or symbols.",
    "orphans": "List production code nothing in production reaches, and code no deployable reaches.",
    "cycles": "List import cycles between files, folders and packages.",
    "deps": "Show a dependency matrix, or fail when a layering rule is broken.",
    "tasks": "List open judgement tasks.",
    "task": "Print the brief for one task, with the answer's JSON shape.",
    "submit": "Validate and store the answer to a task.",
    "ingest": "Load coverage or test result files (lcov, coverage.py JSON, JUnit XML).",
    "build": "Write the static viewer to .cbi/viewer/.",
    "diff": "Print what changed in the architecture between two models.",
    "render": "Write a PNG and an SVG of one concept-map view.",
    "open": "Open the desktop app on this repo, at a worktree, branch, commit, comparison or node.",
    "open-file": "Open one file, symbol or test in the editor.",
    "review": "Write a review of a pull request, branch or commit.",
    "history": "Print the architecture changelog for the default branch.",
}


def package_version():
    """Installed distribution version. pyproject.toml is the source."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("codebase-inspector")
    except PackageNotFoundError:
        return "0.1.0"


def build_parser():
    parser = argparse.ArgumentParser(
        prog="cbi",
        description="Map a codebase into a model that agents can query and people can browse. "
        "New here? Run `cbi prime`.",
    )
    parser.add_argument("--version", action="version", version=f"cbi {package_version()}")
    sub = parser.add_subparsers(dest="command", metavar="<command>", required=True)
    for name, help_text in COMMANDS.items():
        cmd = sub.add_parser(name, help=help_text, description=DESCRIPTIONS.get(name, help_text),
                             formatter_class=argparse.RawDescriptionHelpFormatter)
        if name in ("init", "scan", "check", *READERS):
            cmd.add_argument("--out", metavar="DIR", type=Path,
                             help="model directory to use instead of .cbi/ in the repo root")
        if name in ("search", "show", "tests-for", "tasks", "task", "hotspots", "orphans", "cycles", "deps"):
            cmd.add_argument("--json", action="store_true", help="print JSON instead of text")
    cmds = sub.choices
    cmds["search"].add_argument("text", nargs="+", help="words to look for; each word also matches as a prefix")
    cmds["search"].add_argument("--limit", type=int, default=20, help="most results to print (default 20)")
    cmds["search"].add_argument("--kind", metavar="K", help="only nodes of this display kind (class, test case, folder) or kind")
    cmds["status"].add_argument("--out", metavar="DIR", type=Path, help="model directory to use instead of .cbi/ in the repo root")
    cmds["status"].add_argument("--json", action="store_true", help="print JSON instead of text")
    cmds["show"].add_argument("node", help="a node ID, a repo-relative path, path#qualified.name, or a symbol name")
    cmds["context"].add_argument("node", help="a node ID, a repo-relative path, path#qualified.name, or a symbol name")
    cmds["show"].add_argument("--min-confidence", type=float, default=None, metavar="F",
                              help="hide edges below F (text default 0.6; --json keeps them all unless this is set)")
    cmds["show"].add_argument("--all", action="store_true", help="do not cap relationships or tests at 10")
    cmds["hotspots"].add_argument("--by", choices=("fan-in", "fan-out", "loc", "symbols"), default="fan-in",
                                  help="rank by this metric (default fan-in)")
    cmds["hotspots"].add_argument("--kind", metavar="K", help="only this display kind or kind")
    cmds["hotspots"].add_argument("--limit", type=int, default=20, help="most rows per list (default 20)")
    cmds["deps"].add_argument("--level", choices=("package", "folder", "concept", "deployable"), default="package",
                              help="what a row of the matrix is (default package)")
    cmds["deps"].add_argument("--from", dest="start", help="only dependencies that leave this node")
    cmds["deps"].add_argument("--to", dest="end", help="only dependencies that enter this node")
    cmds["deps"].add_argument("--forbid", action="append", default=[], metavar="FROM:TO",
                              help="exit 1 when a production import runs from FROM to TO")
    cmds["deps"].add_argument("--include-tests", action="store_true", help="count imports from test files too")
    cmds["tests-for"].add_argument("node", help="a node ID, a repo-relative path, path#qualified.name, or a symbol name")
    cmds["tasks"].add_argument("--kind", help="only tasks of this kind, such as summarise-files")
    cmds["tasks"].add_argument("--limit", type=int, help="most tasks to list")
    cmds["tasks"].add_argument("--offset", type=int, default=0, help="skip this many open tasks; use with --limit to batch")
    cmds["task"].add_argument("id", help="task ID from `cbi tasks`")
    brief_mode = cmds["task"].add_mutually_exclusive_group()
    brief_mode.add_argument("--part", type=int, metavar="N", help="print part N of a large brief, from 1")
    brief_mode.add_argument("--parts", action="store_true", help="list the parts of a large define-concepts or sketch-screens brief")
    brief_mode.add_argument("--check", metavar="FILE", type=Path, help="check a draft answer without storing it")
    cmds["submit"].add_argument("id", help="task ID from `cbi tasks`")
    cmds["submit"].add_argument("file", nargs="?", default="-", help="answer JSON file, or - for stdin (default)")
    prime_model = cmds["prime"].add_mutually_exclusive_group()
    prime_model.add_argument("--out", metavar="DIR", type=Path, help="model directory to read instead of .cbi/")
    prime_model.add_argument("--ref", metavar="REF", help="print the guide and task counts for this stored ref model")
    cmds["diff"].description = diff.HELP
    cmds["diff"].add_argument("base", nargs="?", help="base git ref")
    cmds["diff"].add_argument("head", nargs="?", help="head git ref")
    cmds["diff"].add_argument("--base-model", type=Path, metavar="PATH",
                              help="base model.db, or a directory that contains one")
    cmds["diff"].add_argument("--head-model", type=Path, metavar="PATH",
                              help="head model.db, or a directory that contains one")
    cmds["diff"].add_argument("--out", metavar="DIR", type=Path,
                              help="model directory to scan refs into, instead of .cbi/ in the repo root")
    cmds["diff"].add_argument("--format", choices=("text", "markdown", "json"), default="text",
                              help="text (default), markdown or json")
    cmds["diff"].add_argument("--concept", metavar="ID", help="only changes for this concept, by id")
    cmds["render"].description = render.HELP
    cmds["render"].add_argument("--view", required=True, metavar="top|ID", help="top, or a concept id")
    cmds["render"].add_argument("--compare", metavar="BASE..HEAD",
                                help="highlight changes between two git refs, same as cbi diff")
    cmds["render"].add_argument("--side", choices=("base", "head"), default="head",
                                help="base draws removed and changed; head (default) draws added and changed")
    cmds["render"].add_argument("--png", required=True, type=Path, metavar="PATH", help="PNG file to write")
    cmds["render"].add_argument("--svg", required=True, type=Path, metavar="PATH", help="SVG file to write")
    cmds["render"].add_argument("--out", metavar="DIR", type=Path,
                                help="model directory to use instead of .cbi/ in the repo root")
    cmds["review"].description = review.HELP
    cmds["review"].add_argument("target", help="a pull request number, a branch, a commit, or base..head")
    cmds["review"].add_argument("--base", metavar="REF", help="base ref when the target is a branch or commit")
    cmds["review"].add_argument("--out", metavar="DIR", type=Path,
                                help="model directory to scan refs into, instead of .cbi/ in the repo root")
    cmds["review"].add_argument("--out-dir", metavar="DIR", type=Path,
                                help="folder for review.md (default .cbi/reviews/<base>..<head>)")
    cmds["review"].add_argument("--post", action="store_true",
                                help="post review.md as a pull request comment, or update the earlier one")
    cmds["history"].add_argument("--out", metavar="DIR", type=Path,
                                  help="model directory to use instead of .cbi/")
    cmds["history"].add_argument("--format", choices=("text", "markdown", "json"), default="text")
    cmds["history"].add_argument("--since", help="include entries on or after this date (default six months)")
    cmds["history"].add_argument("--until", help="include entries on or before this date")
    cmds["history"].add_argument("--concept", metavar="ID", help="only changes involving this concept")
    cmds["history"].add_argument("--limit", type=int, help="most entries to print, newest first")
    cmds["history"].add_argument("--write", action="store_true",
                                  help="write .cbi/CHANGELOG-ARCHITECTURE.md")
    cmds["history"].add_argument("--narrate", metavar="SHA",
                                  help="open a summarise-change task for one entry")
    cmds["build"].add_argument("--compare", metavar="BASE..HEAD",
                               help="also write data/diff.js for this base..head comparison")
    cmds["build"].add_argument("--history", action="store_true",
                               help="include the default-branch timeline and replay data")
    cmds["ingest"].description = ingest.HELP
    cmds["ingest"].add_argument("--out", metavar="DIR", type=Path,
                                help="model directory to use instead of .cbi/ in the repo root")
    cmds["ingest"].add_argument("files", nargs="+", metavar="file", help="lcov, coverage.py JSON or JUnit XML file")
    ref_help = "branch, tag or commit. scan stores its model; the other commands read it"
    for name in ("scan", "search", "show", "tests-for", "status", "build", "tasks", "task", "submit",
                 "ingest", "hotspots", "orphans", "cycles", "deps", "open-file"):
        cmds[name].add_argument("--ref", metavar="REF", help=ref_help)
    viewed = cmds["context"].add_mutually_exclusive_group()
    viewed.add_argument("--ref", metavar="REF", help=ref_help)
    viewed.add_argument("--compare", metavar="BASE..HEAD",
                        help="describe the node on the head of this comparison, and include cbi diff")
    team_cmd = cmds["team"]
    team_sub = team_cmd.add_subparsers(dest="team_command", metavar="<command>", required=True)
    team_init = team_sub.add_parser(
        "init", help="Write team.toml, export answers, and ignore only derived files.",
        description=TEAM_INIT_HELP, formatter_class=argparse.RawDescriptionHelpFormatter)
    team_init.add_argument("--out", metavar="DIR", type=Path,
                           help="model directory to use instead of .cbi/ in the repo root")
    cmds["check"].add_argument("--base", metavar="REF",
                               help="compare against the merge base with this ref instead of the default branch")
    cmds["check"].add_argument("--format", choices=("text", "github"), default="text",
                               help="text (default) or github annotations")
    cmds["worktrees"].add_argument("--json", action="store_true", help="print JSON")
    cmds["worktrees"].add_argument("--out", metavar="DIR", type=Path,
                                   help="model directory whose refs/ holds branch models (default .cbi/)")
    cmds["open"].add_argument("path", nargs="?",
                              help="a repository, or a folder or file inside one (default: the current directory)")
    version = cmds["open"].add_mutually_exclusive_group()
    version.add_argument("--worktree", metavar="NAME", help="worktree directory name, lane or path")
    version.add_argument("--branch", metavar="NAME", help="local branch, without checking it out")
    version.add_argument("--commit", metavar="SHA", help="commit, without checking it out")
    cmds["open"].add_argument("--node", metavar="ID_OR_NAME", help="concept, file or symbol to open")
    cmds["open"].add_argument("--compare", metavar="BASE..HEAD", help="open the comparison of these two refs")
    cmds["open"].add_argument("--pr", metavar="N", help="open the comparison of this pull request and its base")
    cmds["open-file"].add_argument("node", help="a node ID, a repo-relative path, path#qualified.name, or a symbol name")
    cmds["open-file"].add_argument("--editor", choices=editor.EDITORS, default="vscode",
                                   help="vscode (default), cursor, or none")
    cmds["open-file"].add_argument("--template", metavar="CMD",
                                   help="command template with {project}, {file} and {line}; overrides --editor")
    cmds["build"].add_argument("--editor", choices=editor.EDITORS, default="vscode",
                               help="URL scheme the static viewer uses: vscode (default), cursor, or none")
    return parser


READERS = ("search", "show", "context", "tests-for", "tasks", "task", "submit", "build",
           "hotspots", "orphans", "cycles", "deps", "open-file")

TEAM_INIT_HELP = """\
Opt in to team mode. Writes team.toml, rewrites .gitignore so only derived
files are ignored (model.db, viewer/, refs/, reviews/, history/, ignore.local), exports
accepted answers to answers.jsonl, and adds a .gitattributes line marking
that file generated.

Prints the git commands to commit those files. Does not commit or push.
Running it again keeps team.toml and does not duplicate the attributes line.
With --out DIR the files go to DIR and the repo's .gitattributes is left
unchanged.

Exit codes: 0 done, 1 not inside a git repo."""


DESCRIPTIONS = {
    "init": """\
Create .cbi/ in the root of the git repo containing the current directory.
.cbi/ holds a .gitignore of `*`, so no tracked file changes, and `ignore`,
a gitignore-syntax list of tracked paths to leave out of the model (build
output, data dirs, minified files, and fixtures or test-data dirs that are
mostly data). Edit `ignore` freely; rerunning
init keeps it and changes nothing else. A team repo (`.cbi/team.toml`)
keeps its derived-only gitignore; init does not replace that with `*`.

Exit codes: 0 done, 1 not inside a git repo.""",
    "team": """\
Opt in to committing the map's judgement instead of ignoring all of .cbi/.
`cbi team init` writes the marker, the answers file and the gitignore.
It prints git commands and does not run them.

Exit codes: 0 done, 1 not inside a git repo, 2 unknown team command.""",
    "scan": """\
Map the repo and every initialised submodule into DIR/model.db from the
files git tracks, reading content from the working tree, so unstaged edits
count. If nothing changed since the last scan (files, ignore file,
structure.json, concepts.json, screens.json, checked-out commits, and in
team mode answers.jsonl), the scan stops early.

In team mode (`.cbi/team.toml`), scan loads answers.jsonl into the answer
cache before opening tasks.

Prints node counts by kind, the time taken and whether the no-change
shortcut applied.

--ref REF maps that branch, tag or commit from git objects (`git ls-tree`
and one `git cat-file --batch` per object database, including submodule
gitlinks) and stores the model at refs/<commit>/model.db inside the model
directory. A commit's tree does not change, so a second scan reuses that
file when the parser version and the ignore file are unchanged. The first
line of output is the full commit it resolved to. Nothing in a ref scan
checks out, switches, stashes, resets or writes a ref or a working tree.
structure.json and concepts.json for that commit are written beside the
ref model, not into the worktree's .cbi/.

Exit codes: 0 done, 1 not inside a git repo, unknown ref, or not
initialised (run `cbi init`).""",
    "worktrees": """\
List the repo's worktrees (main checkout and every linked worktree) and
its local branches.

--json prints {worktrees: [{path, branch, head, lane, has_model,
model_complete, current}], branches: [{name, head, lane, has_ref_model,
current}]}. A worktree's model is its own .cbi/model.db; model_complete
means that model has no open or blocked task. A branch has a ref model
when refs/<head>/model.db exists in the model directory (--out, or .cbi/
of this worktree). lane is the worktree's directory name when local git
config has cbi.worktree.<handle> for that directory, otherwise the branch
name. current marks the worktree you are in and its branch.

Exit codes: 0 done, 1 not inside a git repo.""",
    **query.HELP,
    "context": """\
Print a short Markdown block describing one node, for pasting into an agent
session. It names the project and its absolute path, the model folder
(.cbi/ or --out), and the version: this worktree and its branch, a ref and
its commit, or a base..head comparison. Then the node's display kind, name,
id and file:line, its summary, its concept and parent chain, and the top
relationships in and out (at most 10 each, with the other end's concept).
A concept lists its child concepts and how many files it owns instead of
symbol details. The block also gives the linked test count, the names of
environment variables the code reads (never their values or defaults), the
integration points, and a To see more list of commands with cd and the
flags filled in: cbi show, cbi tests-for, cbi search, cbi diff when this is
a comparison, and a sqlite3 query for the raw edges.

--compare BASE..HEAD reads the head model (scanning both refs first, the
same as cbi diff) and cannot be combined with --ref. The show, tests-for
and search commands in the block use --ref HEAD so they open that model.

Exit codes: 0 printed, 1 not found, ambiguous, unknown ref, or no model,
2 compare is not base..head.

Example: cbi context src/app.ts#main""",
    **graph.HELP,
    "tasks": """\
List open judgement tasks, one per line: task ID, kind, the node it covers
and how many files or children it lists. Take one with `cbi task <id>`.
Kinds: summarise-files, summarise-group (a folder or package, from its
children's summaries), confirm-structure (one per workspace; accepting it
writes structure.json), summarise-deployable (one per deployable, after
confirm-structure), summarise-workspace, define-concepts (the concept
map), sketch-screens (region trees for UI screens) and summarise-change
(a short narrative of one diff, cached by the two commits). Tasks run
bottom-up: a group or workspace task is blocked, and not listed, until
its children are summarised. define-concepts opens once confirm-structure
is done; sketch-screens opens once that map is done and the repo has UI
components or screen templates. A review can open define-concepts for the new files on
a ref model, and summarise-change for that commit pair.

--json prints a list of {id, kind, node_id, node_display_kind, node_path,
files}. --limit N and --offset N batch that list: offset skips the first
N open tasks, after the kind filter and the usual order.

Exit codes: 0 done, 1 no model (run `cbi scan`).""",
    "task": """\
Print the brief for one task: what to do, the files to read with their
symbol outline (or, for group and workspace tasks, the children with their
summaries and the README head; for confirm-structure, the detected
deployables, packages and bare directories; for summarise-deployable, its
entry points and member summaries), the input_hash your answer must copy,
and the JSON Schema of the answer. define-concepts also prints its checks,
the files to assign and the import and call pairs. sketch-screens prints
its checks, component templates, render edges, screen template files and routes. A
blocked task lists
what it waits on. Then write the answer to a file and run
`cbi submit <id> <file>`.

The line under the title is `size: N bytes`, the length of the text this
command prints.

--parts lists the parts of a define-concepts or sketch-screens brief that
is over the byte budget (team.toml brief_budget, otherwise CBI_BRIEF_BUDGET
in bytes, otherwise 150 KB). --part N
prints part N, from 1. Concept parts are one per package or deployable,
then a cross-area part. Screen parts are one per UI deployable's page
tree, and the JSX inside a part is not truncated. The answer is still one
JSON file. --check FILE runs the same checks as submit and stores nothing.

--json prints the brief, or the part index, as one JSON object.

Exit codes: 0 done, 1 unknown task or no model, 2 a missing part, a draft
the checks reject, or parts asked of another kind.""",
    "submit": """\
Validate an answer and store it. Reads FILE, or stdin when FILE is - or
missing. On success the task is done, the answer is cached (file summaries
by file content, group and workspace summaries by their inputs) so any repo
with identical inputs reuses it, and the tasks it unblocked open and are
listed. Submitting the same answer again changes nothing; a new summary
text reopens the parent's task. Accepting confirm-structure writes
structure.json and reruns manifest detection and resolution in this command.
An accepted define-concepts answer writes concepts.json and applies it in
the same command. An accepted sketch-screens answer writes screens.json
and applies it in the same command. A define-concepts warning (more than
9 children) is printed and does not reject on its own.

Rejected answers print one line per problem, each starting with the JSON
path it refers to ($.files[2].summary: empty). An answer whose input_hash
no longer matches (the files changed and were rescanned) is rejected as
stale: run `cbi task <id>` again.

Exit codes: 0 accepted, 1 no model, 2 answer rejected or unknown task.""",
    "build": """\
Write a static viewer to DIR/viewer/ (.cbi/viewer/ by default): open
index.html straight from disk, no server needed. It draws the concept map
(deployables, packages and externals when the model has no concepts), with
zoom, search and a detail drawer. Prints the path of index.html.

--compare BASE..HEAD scans both git refs (or reuses the stored models) and
writes the head viewer plus data/diff.js. That file is the change list, the
base concepts and relationships needed to draw removed things, the base
screens of a changed component, and the base and head source of each changed
function. The viewer turns comparison mode on when the file has data.
--ref cannot be combined with --compare. A concept is provisional when its
node attr provisional is true; assigning those concepts is the review command.

Exit codes: 0 done, 1 no model, unknown ref, or not initialised, 2 compare
is not base..head or it was combined with --ref.""",
    "diff": diff.HELP,
    "open": """\
Open the desktop app on this repository. Prints a cbi://open link and hands
it to macOS `open`, which starts the app when it is not already running.
With no flags the link names the current worktree. --worktree, --branch and
--commit choose another version and cannot be combined. --node is an id or
a name; a name is resolved in that version's model when one exists.

--compare BASE..HEAD opens the comparison of those two refs. Both refs must
resolve. --pr N resolves the pull request with
`gh pr view N --json baseRefOid,headRefOid` (read-only) and opens the
comparison of those two commits. A gh failure is printed and nothing is
guessed. --compare and --pr cannot be combined with each other or with
--worktree, --branch or --commit. --node still selects a concept or function.

The link is repo=<absolute path>&ref=<ref or worktree path>&node=<id>, or
repo=<absolute path>&compare=<base>..<head>&node=<id>. Opening a state does
not check out, switch, stash or write a ref.

Exit codes: 0 the link was opened, 1 not a git repo, unknown worktree or
ref, gh failed, node not found, or no app handles cbi://, 2 compare or pr
is not the right shape, or it was combined with another version flag.""",
    "open-file": """\
Open one file, symbol or test in an editor. The node is an id, a
repo-relative path, path#qualified.name, or a symbol name. Prints the
command, then runs it with no shell. A path with spaces stays one argument.

--editor is vscode (default), cursor, or none. --template is a command
with {project}, {file} and {line}; when set it replaces --editor. code
and cursor are found on PATH, or in the macOS app bundle.

The project is this worktree. --ref opens the file in a worktree that
already has that branch or that commit checked out. Otherwise it writes
a read-only copy from git show into the snapshot cache and opens that.
It does not check out, switch, or write inside the repository.

A concept, folder, deployable, package or external does not map to one
file, and nothing is launched.

Exit codes: 0 the editor was started, 1 the node was not found, it is not
one file, the file is missing, or the editor program was not found, 2 the
template is empty or has an unclosed quote.""",
    "review": review.HELP,
    "check": check.HELP,
}


def _paths(args):
    root = files.repo_root(Path.cwd())
    out = args.out.resolve() if args.out else root / ".cbi"
    return root, out


def cmd_init(args):
    root, out = _paths(args)
    out.mkdir(parents=True, exist_ok=True)
    # Team mode rewrote this file. Putting `*` back would hide the committed judgement.
    if (out / "team.toml").is_file():
        if not (out / ".gitignore").exists():
            (out / ".gitignore").write_text(team.DERIVED_GITIGNORE)
    else:
        (out / ".gitignore").write_text("*\n")
    ignore = out / "ignore"
    if ignore.exists():
        print(f"{out} already initialised; kept {ignore}")
    else:
        ignore.write_text(files.default_ignore(root))
        print(f"Created {out} and wrote {ignore}. Edit it to skip more paths, then run `cbi scan`.")
    return 0


def _read(path):
    return path.read_text() if path.exists() else None


def _scan_fingerprint(workspaces, ignore_text, out, structure_text, concepts_text, screens_text):
    """The no-change fingerprint. Team mode also hashes answers.jsonl."""
    directory = team.team_dir(out)
    answers = _read(directory / "answers.jsonl") if directory else None
    return files.fingerprint(
        workspaces, ignore_text, structure_text, concepts_text, screens_text,
        answers_text=answers, team=directory is not None,
    )


def _map(root, out, ignore_text, workspaces, tracked, states, commit=None):
    """Run the scan pipeline over an already enumerated tree. root supplies file bytes."""
    concepts_text = _read(out / "concepts.json")
    screens_text = _read(out / "screens.json")
    fp = _scan_fingerprint(
        workspaces, ignore_text, out, _read(out / "structure.json"), concepts_text, screens_text)
    conn = store.open_db(out / "model.db")
    try:
        tasks.attach_cache(conn)
        old = store.file_states(conn)
        same_files = {p: s[2] for p, s in states.items()} == {p: s[2] for p, s in old.items()}
        shortcut = same_files and store.get_meta(conn, "fingerprint") == fp
        with conn:
            store.replace_file_states(conn, {p: s[:4] for p, s in states.items()})
            store.set_meta(conn, "scanned_at", time.strftime("%Y-%m-%dT%H:%M:%S%z"))
            store.set_meta(conn, "parser_version", str(files.PARSER_VERSION))
            store.set_meta(conn, "ignore", files.ignore_token(ignore_text))
            # content_hash is the git blob id. A model written before that misses this key,
            # so the next scan rehashes instead of reusing the old digest from mtime.
            store.set_meta(conn, "content_id", "blob")
            if commit:
                store.set_meta(conn, "commit", commit)
            if not shortcut:
                known = {r[0] for r in conn.execute("SELECT id FROM nodes WHERE kind = 'file'")}
                store.replace_enumerated_nodes(conn, files.build_nodes(workspaces, tracked, states))
                _parse_changed(conn, root, tracked, states, old, known)
                store.drop_orphan_symbols(conn)
                resolve.resolve(conn, root)
                data.apply(conn, root)
                manifests.apply(conn, root, _read(out / "structure.json"))
                concepts.apply(conn, concepts_text)
                screens.apply(conn, screens_text, root)
                tasks.refresh(conn, root, out)
                # ponytail: full search rebuild per scan; index only changed nodes if it gets slow.
                store.reindex(conn)
                docs.index(conn, root)
                # refresh may have written structure.json or concepts.json from the answer cache
                fp = _scan_fingerprint(
                    workspaces, ignore_text, out, _read(out / "structure.json"),
                    _read(out / "concepts.json"), _read(out / "screens.json"))
                store.set_meta(conn, "fingerprint", fp)
        return shortcut, store.counts_by_display_kind(conn), tasks.task_counts(conn)
    finally:
        conn.close()


def scan(root, out):
    """Run the scan pipeline on the working tree. Returns (shortcut hit, counts, (open, blocked))."""
    ignore_text = _read(out / "ignore")
    workspaces, tracked = files.enumerate_repo(root, files.Ignore(ignore_text or ""))
    conn = store.open_db(out / "model.db")
    try:
        tasks.attach_cache(conn)
        old = store.file_states(conn) if store.get_meta(conn, "content_id") == "blob" else {}
    finally:
        conn.close()
    states = files.hash_files(root, tracked, old)
    return _map(root, out, ignore_text, workspaces, tracked, states)


def scan_ref(root, out, ref, *, seed=None, force=False):
    """Map one commit from git objects into out/refs/<sha>/model.db.

    Returns (sha, reused, counts, (open, blocked)). A stored model is reused when
    the schema, parser version and ignore file still match.
    """
    ignore_text = _read(out / "ignore")
    sha = files.resolve_commit(root, ref)
    home = out / "refs" / sha
    db = home / "model.db"
    if not force and store.ref_reusable(db, files.ignore_token(ignore_text), files.PARSER_VERSION):
        conn = store.read_only(db)
        try:
            return sha, True, store.counts_by_display_kind(conn), tasks.task_counts(conn)
        finally:
            conn.close()
    home.mkdir(parents=True, exist_ok=True)
    if seed and not db.exists():
        shutil.copy2(seed, db)
    tree = files.CommitTree(root, sha, files.Ignore(ignore_text or ""))
    try:
        _shortcut, counts, task_counts = _map(
            tree, home, ignore_text, tree.workspaces, tree.tracked, tree.file_states(), sha)
    finally:
        tree.close()
    return sha, False, counts, task_counts


def _parse_changed(conn, root, tracked, states, old, known):
    """Parse code files whose content or parser version changed, or that are new to the model."""
    by_ws = {}
    for _top, ws, rel in tracked:
        by_ws.setdefault(ws["id"], []).append(rel)
    roots = {wid: files.cs_test_roots(paths) for wid, paths in by_ws.items()}
    for top, ws, rel in tracked:
        state = states.get(top)
        if not state or state[4]:  # gone from disk, or a symlink
            continue
        role, lang = files.classify(rel, roots.get(ws["id"], ()))
        fid = file_id(ws["id"], rel)
        prev = old.get(top)
        if lang not in parse.LANGS or (prev and prev[2:4] == state[2:4] and fid in known):
            continue
        source = (root / top).read_bytes()
        nodes, facts, has_error = parse.symbol_nodes(fid, ws["id"], rel, lang, source, role == "test")
        store.replace_file_symbols(conn, ws["id"], rel, len(source.splitlines()), nodes, fid, facts)
        if any(n["kind"] == "test" for n in nodes):
            conn.execute(
                "UPDATE nodes SET display_kind = 'test file', attrs = json_set(attrs, '$.role', 'test') "
                "WHERE id = ? AND json_extract(attrs, '$.role') != 'test'",
                (fid,),
            )
        store.set_diagnostic(conn, fid, "parse_error", "tree-sitter reported syntax errors" if has_error else None)


def cmd_scan(args):
    root, out = _paths(args)
    if not (out / "ignore").exists():
        print(f"{out} is not initialised. Run `cbi init` first.", file=sys.stderr)
        return 1
    start = time.perf_counter()
    if args.ref:
        sha, reused, counts, task_counts = scan_ref(root, out, args.ref)
        print(sha)
        status = "reused" if reused else "scanned"
    else:
        shortcut, counts, task_counts = scan(root, out)
        status = "no changes since the last scan" if shortcut else "scanned"
    elapsed = time.perf_counter() - start
    print(f"{status} in {elapsed:.1f} s")
    for kind, count in counts.items():
        print(f"  {kind}: {count}")
    open_n, _blocked_n = task_counts
    line = tasks.task_headline(*task_counts)
    print(line + ("; run `cbi tasks`" if open_n else ""))
    return 0


class NoModel(Exception):
    pass


def _locate(args):
    """(repo root, model home, model db, commit sha or None).

    With --ref the home is refs/<sha>/ under the model directory, so task
    answers and the viewer land beside that commit's model.
    """
    root, out = _paths(args)
    ref = getattr(args, "ref", None)
    if not ref:
        return root, out, out / "model.db", None
    sha = files.resolve_commit(root, ref)
    home = out / "refs" / sha
    return root, home, home / "model.db", sha


def _model(args):
    _root, _home, path, sha = _locate(args)
    if not path.exists():
        if sha:
            raise NoModel(f"no model for {sha}. Run `cbi scan --ref {args.ref}` first.")
        raise NoModel(f"no model at {path}. Run `cbi init` and `cbi scan` first.")
    conn = store.open_db(path)
    tasks.attach_cache(conn)
    return conn


def _read_model(args):
    """Open a model a read command must not write.

    status, show, search, tests-for, hotspots, orphans, cycles, deps and context
    use this. History will too, when that command exists. The model is not created,
    migrated, or switched to WAL, and the answer cache is attached read-only or skipped.
    """
    _root, _home, path, sha = _locate(args)
    if not path.exists():
        if sha:
            raise NoModel(f"no model for {sha}. Run `cbi scan --ref {args.ref}` first.")
        raise NoModel(f"no model at {path}. Run `cbi init` and `cbi scan` first.")
    try:
        conn = store.read_only(path)
    except sqlite3.Error as err:
        raise NoModel(f"{path} is not a cbi model ({err})") from err
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version != store.SCHEMA_VERSION:
        conn.close()
        raise NoModel(
            f"{path} is schema {version}; this cbi expects {store.SCHEMA_VERSION}. Rescan it.")
    tasks.attach_cache(conn, readonly=True)
    return conn


def _query(args, fn):
    conn = _read_model(args)
    try:
        return fn(conn, args)
    finally:
        conn.close()


def _source(root, sha):
    """Working tree, or the commit's blobs when sha is set. Caller closes the tree."""
    if sha is None:
        return None
    return files.CommitTree(root, sha, files.Ignore(""))


def _print_json(value):
    print(json.dumps(value, indent=2))


def cmd_search(args):
    return _query(args, query.search)


def cmd_show(args):
    return _query(args, query.show)


def _place(root, model_root, model_db, ref=None, sha=None, compare=None):
    return context.Place(
        repo=root, model_root=model_root, model_db=model_db,
        branch=None if sha or compare else context.current_branch(root),
        ref=None if compare else ref, sha=sha, compare=compare,
    )


def cmd_context(args):
    root, out = _paths(args)
    if args.compare:
        sides = open_link.parse_compare(args.compare)
        if not sides:
            print("compare must be base..head", file=sys.stderr)
            return 2
        try:
            base_conn, head_conn = diff.models_for_refs(sides[0], sides[1], root, out)
        except diff.DiffError as err:
            print(err, file=sys.stderr)
            return err.code
        try:
            head_sha = store.get_meta(head_conn, "commit") or sides[1]
            place = _place(root, out, out / "refs" / head_sha / "model.db", sha=head_sha, compare=sides)
            return context.emit(head_conn, args.node, place)
        finally:
            base_conn.close()
            head_conn.close()
    root, _home, path, sha = _locate(args)
    conn = _read_model(args)
    try:
        place = _place(root, out, path, ref=args.ref, sha=sha)
        return context.emit(conn, args.node, place)
    finally:
        conn.close()


def cmd_tests_for(args):
    return _query(args, query.tests_for)


def cmd_status(args):
    code = _query(args, query.status)
    if code == 0 and not args.json:
        _print_update_notice()
    return code


def _print_update_notice():
    line = update_check.notice()
    if line:
        print(line)


def cmd_hotspots(args):
    return _query(args, graph.hotspots)


def cmd_orphans(args):
    return _query(args, graph.orphans)


def cmd_cycles(args):
    return _query(args, graph.cycles)


def cmd_deps(args):
    return _query(args, graph.deps)


def cmd_tasks(args):
    conn = _model(args)
    try:
        if args.offset < 0:
            print("--offset must be 0 or greater", file=sys.stderr)
            return 2
        found = tasks.open_tasks(conn, args.kind, args.limit, args.offset)
        if args.json:
            _print_json(found)
            return 0
        for t in found:
            print(f"{t['id']}  {t['kind']}  {t['node_display_kind']} {t['node_path'] or t['node_id']}  ({t['files']} files)")
        if not found:
            print("no open tasks")
        return 0
    finally:
        conn.close()


def _brief_text(b):
    if b["kind"] == "define-concepts":
        return concepts.format_brief(b)
    if b["kind"] == "sketch-screens":
        return screens.format_brief(b)
    if b["kind"] != "summarise-files":
        return tasks.format_brief(b)
    lines = [f"# Task {b['id']}: {b['kind']} ({b['state']})", f"node: {b['node_id']}", f"input_hash: {b['input_hash']}", "",
             b["instructions"], ""]
    for f in b["files"]:
        lines.append(f"## {f['path']}  (content {f['content_hash'][:12]})")
        for o in f["outline"]:
            lines.append(f"  {o['display_kind']:<12} L{o['lines']:<9} {o['signature']}")
            if o["doc"]:
                lines.append(f"  {'':<12} {'':<10} {o['doc'].splitlines()[0]}")
        lines.append("")
    example = {"input_hash": b["input_hash"], "files": [{"path": f["path"], "summary": "..."} for f in b["files"]]}
    lines += ["## Answer schema", json.dumps(b["answer_schema"], indent=2), "", "## Answer template",
              json.dumps(example, indent=2), "",
              f"Submit with: cbi submit {b['id']} answer.json   (or pipe the JSON to `cbi submit {b['id']} -`)"]
    return "\n".join(lines)


def _emit_brief(b, text, as_json):
    """Print a brief. `size` / `bytes` is the length of the text form, which is what an agent reads."""
    stamped = tasks.sized(parts.insert_note(text, parts.over_note(b, text)))
    if as_json:
        payload = dict(b)
        payload["bytes"] = len(stamped.encode())
        if parts.over_note(b, text):
            payload["over_budget"] = True
        _print_json(payload)
        return
    sys.stdout.write(stamped)


def cmd_task(args):
    root, home, _path, sha = _locate(args)
    conn = _model(args)
    source = _source(root, sha)
    token = parts.bind(home)
    try:
        if args.check is not None:
            return _cmd_check(args, conn, source or root)
        try:
            b = tasks.brief(conn, args.id, source or root)
        except tasks.UnknownTask as err:
            print(err, file=sys.stderr)
            return 1
        if args.parts or args.part is not None:
            return _cmd_parts(args, conn, b, source or root)
        _emit_brief(b, _brief_text(b), args.json)
        return 0
    finally:
        parts.unbind(token)
        if source:
            source.close()
        conn.close()


def _cmd_check(args, conn, root):
    try:
        text = args.check.read_text()
    except OSError as err:
        print(f"rejected: cannot read the answer: {err}", file=sys.stderr)
        return 2
    try:
        warnings = tasks.check(conn, args.id, text, root)
    except tasks.UnknownTask as err:
        print(err, file=sys.stderr)
        return 1
    except tasks.AnswerError as err:
        if args.json:
            _print_json({"ok": False, "errors": str(err).splitlines()})
        else:
            print(f"rejected:\n{err}", file=sys.stderr)
        return 2
    if args.json:
        _print_json({"ok": True, "warnings": warnings})
    elif warnings:
        print("ok")
        print("\n".join(warnings))
    else:
        print("ok")
    return 0


def _cmd_parts(args, conn, brief, root):
    if brief["kind"] not in parts.SPLIT_KINDS:
        print(f"{brief['kind']} briefs are not split", file=sys.stderr)
        return 2
    spec = parts.split_brief(conn, brief, root)
    if args.parts:
        if args.json:
            _print_json(parts.index_payload(spec))
        else:
            sys.stdout.write(parts.index_text(spec))
        return 0
    if args.part < 1 or args.part > len(spec["parts"]):
        print(f"part {args.part} is outside 1..{len(spec['parts'])}", file=sys.stderr)
        return 2
    part = spec["parts"][args.part - 1]
    if args.json:
        payload = dict(part["brief"])
        payload["bytes"] = part["bytes"]
        _print_json(payload)
    else:
        sys.stdout.write(part["text"])
    return 0


def cmd_submit(args):
    root, home, _path, sha = _locate(args)
    conn = _model(args)
    source = _source(root, sha)
    try:
        try:
            text = sys.stdin.read() if args.file == "-" else Path(args.file).read_text()
        except OSError as err:
            print(f"rejected: cannot read the answer: {err}", file=sys.stderr)
            return 2
        try:
            print(tasks.submit(conn, args.id, text, source or root, home))
        except (tasks.AnswerError, tasks.UnknownTask) as err:
            print(f"rejected: {err}" if isinstance(err, tasks.UnknownTask) else f"rejected:\n{err}", file=sys.stderr)
            return 2
        return 0
    finally:
        if source:
            source.close()
        conn.close()


def cmd_render(args):
    root, out = _paths(args)
    try:
        if args.compare:
            base_ref, head_ref = render.split_compare(args.compare)
            base, head = diff.models_for_refs(base_ref, head_ref, root, out)
            try:
                changes = diff.compare(base, head)
                side = base if args.side == "base" else head
                render.render_view(side, changes, args.view, args.side, args.png, args.svg, root)
            finally:
                base.close()
                head.close()
        else:
            conn = _model(args)
            try:
                render.render_view(conn, None, args.view, args.side, args.png, args.svg, root)
            finally:
                conn.close()
    except (render.RenderError, diff.DiffError) as err:
        print(err, file=sys.stderr)
        return err.code
    print(Path(args.png).resolve())
    print(Path(args.svg).resolve())
    return 0


def cmd_review(args):
    root, out = _paths(args)
    try:
        print(review.review(root, args.target, base=args.base, model=out, out_dir=args.out_dir, post=args.post))
    except review.ReviewError as err:
        print(err, file=sys.stderr)
        return err.code
    return 0


def cmd_history(args):
    root, out = _paths(args)
    try:
        if args.narrate:
            print(history.narrate(out, args.narrate))
            return 0
        since = args.since
        if since is None:
            since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=history.DEFAULT_DAYS)).date().isoformat()
        entries = history.build_history(root, out, since, args.until)
        shown = history.select(entries, args.since, args.until, args.concept, args.limit)
        if args.write:
            path = history.write_changelog(out, shown)
            print(path)
        else:
            sys.stdout.write(history.render(shown, args.format))
    except history.HistoryError as err:
        print(err, file=sys.stderr)
        return err.code
    return 0


def cmd_diff(args):
    root = out = None
    if args.base and args.head and not (args.base_model or args.head_model):
        root, out = _paths(args)
    try:
        base, head = diff.open_pair(args.base_model, args.head_model, args.base, args.head, root, out)
    except diff.DiffError as err:
        print(err, file=sys.stderr)
        return err.code
    try:
        result = diff.compare(base, head)
    finally:
        base.close()
        head.close()
    sys.stdout.write(diff.render(result, args.format, args.concept))
    return 0


def cmd_build(args):
    if args.compare and args.history:
        print("pass --compare or --history, not both", file=sys.stderr)
        return 2
    if args.compare:
        return _cmd_build_compare(args)
    if args.history:
        return _cmd_build_history(args)
    root, out = _paths(args)
    _root, home, path, sha = _locate(args)
    conn = _model(args)
    source = _source(root, sha)
    place = _place(root, out, path, ref=args.ref, sha=sha)
    try:
        print(build.build(conn, home / "viewer", source or root, place=place,
                          editor=args.editor, project=root, ref_sha=sha))
    finally:
        if source:
            source.close()
        conn.close()
    return 0


def _cmd_build_history(args):
    if args.ref:
        print("pass --history or --ref, not both", file=sys.stderr)
        return 2
    root, out = _paths(args)
    index = out / "history" / "index.json"
    if not index.is_file():
        print("history has not been built. Run `cbi history` first.", file=sys.stderr)
        return 1
    try:
        entries = json.loads(index.read_text()).get("entries") or []
    except (OSError, json.JSONDecodeError) as err:
        print(f"cannot read history index: {err}", file=sys.stderr)
        return 1
    payload = []
    for entry in entries:
        base_conn = head_conn = base_src = head_src = None
        try:
            base_conn = diff.open_model(out / "refs" / entry["base"] / "model.db")
            head_conn = diff.open_model(out / "refs" / entry["sha"] / "model.db")
            base_src = files.CommitTree(root, entry["base"], files.Ignore(""))
            head_src = files.CommitTree(root, entry["sha"], files.Ignore(""))
            comparison = build.compare_payload(
                head_conn, base_conn, entry["changes"], head_src, base_src, entry["base"], entry["sha"])
            payload.append({
                "sha": entry["sha"], "base": entry["base"], "date": entry["date"],
                "author": entry["author"], "pr": entry.get("pr"), "title": entry.get("title"),
                "change_count": entry["change_count"], "narrative": entry.get("narrative"),
                "text": history.render([entry], "text"), "model": build.concept_view(head_conn, head_src),
                "diff": comparison,
            })
        except diff.DiffError as err:
            print(err, file=sys.stderr)
            return err.code
        finally:
            for source in (base_src, head_src):
                if source:
                    source.close()
            for conn in (base_conn, head_conn):
                if conn:
                    conn.close()
    conn = _model(args)
    try:
        print(build.build(conn, out / "viewer", root, history={"entries": payload},
                          editor=args.editor, project=root))
    finally:
        conn.close()
    return 0


def _cmd_build_compare(args):
    if args.ref:
        print("pass --compare or --ref, not both", file=sys.stderr)
        return 2
    sides = open_link.parse_compare(args.compare)
    if not sides:
        print("compare must be base..head", file=sys.stderr)
        return 2
    root, out = _paths(args)
    try:
        base_conn, head_conn = diff.models_for_refs(sides[0], sides[1], root, out)
    except diff.DiffError as err:
        print(err, file=sys.stderr)
        return err.code
    base_sha = store.get_meta(base_conn, "commit") or sides[0]
    head_sha = store.get_meta(head_conn, "commit") or sides[1]
    base_src = files.CommitTree(root, base_sha, files.Ignore(""))
    head_src = files.CommitTree(root, head_sha, files.Ignore(""))
    try:
        changes = diff.compare(base_conn, head_conn)
        place = _place(root, out, out / "refs" / head_sha / "model.db", sha=head_sha, compare=sides)
        print(build.build(head_conn, out / "viewer", head_src, compare={
            "base": base_conn, "base_root": base_src, "changes": changes,
            "base_label": base_sha, "head_label": head_sha,
        }, place=place, editor=args.editor, project=root, ref_sha=head_sha))
    finally:
        base_src.close()
        head_src.close()
        base_conn.close()
        head_conn.close()
    return 0


def cmd_open(args):
    return open_link.run(args)


def cmd_open_file(args):
    root, _home, _path, sha = _locate(args)
    conn = _model(args)
    try:
        return editor.open_node(
            conn, args.node, project=root, worktree=root, ref_model=sha is not None,
            editor=args.editor, template=args.template, sha=sha,
            branch=editor.branch_name(root, args.ref) if sha else "",
        )
    finally:
        conn.close()


def cmd_worktrees(args):
    root, out = _paths(args)
    data = files.inventory(root, out)
    if args.json:
        _print_json(data)
        return 0
    print("worktrees:")
    for w in data["worktrees"]:
        mark = "*" if w["current"] else " "
        branch = w["branch"] or "(detached)"
        if w["model_complete"]:
            state = "model complete"
        elif w["has_model"]:
            state = "model"
        else:
            state = "no model"
        print(f"{mark} {w['path']}  {branch}  {w['head'][:12]}  {w['lane'] or branch}  {state}")
    print("branches:")
    for b in data["branches"]:
        mark = "*" if b["current"] else " "
        ref = "ref model" if b["has_ref_model"] else "no ref model"
        print(f"{mark} {b['name']}  {b['head'][:12]}  {b['lane']}  {ref}")
    return 0


def cmd_ingest(args):
    root, _ = _paths(args)
    conn = _model(args)
    try:
        unmapped = 0
        for f in args.files:
            try:
                r = ingest.ingest(conn, root, Path.cwd(), f)
            except (OSError, ingest.UnknownFormat, ValueError, SyntaxError) as err:
                print(f"{f}: not loaded: {err}", file=sys.stderr)
                return 2
            unmapped += r["unmapped"]
            print(f"{f}: {r['format']}, {r['lines']} lines in {r['files']} files, {r['results']} test results, "
                  f"{r['edges']} coverage test links, {r['unmapped']} unmapped")
        if unmapped:
            print(f"{unmapped} paths or test cases matched nothing in the model; see the unmapped_coverage diagnostics")
        return 0
    finally:
        conn.close()


def cmd_check(args):
    root, out = _paths(args)
    return check.run(root, out, args.base, args.format, scan)


def cmd_team(args):
    root, out = _paths(args)
    if args.team_command == "init":
        return team.cmd_init(root, out)
    print(f"cbi team {args.team_command}: not implemented yet", file=sys.stderr)
    return 2


HANDLERS = {"init": cmd_init, "team": cmd_team, "scan": cmd_scan, "check": cmd_check, "worktrees": cmd_worktrees, "search": cmd_search,
            "show": cmd_show, "context": cmd_context, "tests-for": cmd_tests_for, "status": cmd_status, "tasks": cmd_tasks,
            "task": cmd_task, "submit": cmd_submit, "build": cmd_build, "diff": cmd_diff, "render": cmd_render,
            "review": cmd_review, "history": cmd_history, "open": cmd_open, "open-file": cmd_open_file,
            "hotspots": cmd_hotspots, "orphans": cmd_orphans, "cycles": cmd_cycles, "deps": cmd_deps}
HANDLERS["ingest"] = cmd_ingest


def _silence_broken_pipe():
    """Point stdout at devnull so the interpreter's exit flush does not raise again."""
    try:
        fd = sys.stdout.fileno()
    except (AttributeError, OSError, ValueError):
        return
    try:
        null = os.open(os.devnull, os.O_WRONLY)
    except OSError:
        return
    try:
        os.dup2(null, fd)
    finally:
        os.close(null)


def _is_broken_pipe(err):
    """A closed stdout. Windows reports that as EINVAL, not EPIPE."""
    if isinstance(err, BrokenPipeError):
        return True
    if sys.platform != "win32" or not isinstance(err, OSError):
        return False
    # 109 ERROR_BROKEN_PIPE, 232 ERROR_NO_DATA. errno 22 is the EINVAL mapping.
    if getattr(err, "winerror", None) in (109, 232):
        return True
    return err.errno == 22


def _configure_windows_output():
    """Use UTF-8 for redirected Windows output instead of the legacy code page."""
    if sys.platform != "win32":
        return
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if not reconfigure:
            continue
        try:
            reconfigure(encoding="utf-8")
        except (OSError, ValueError):
            pass


def main(argv=None):
    _configure_windows_output()
    try:
        return _main(argv)
    except OSError as err:
        if not _is_broken_pipe(err):
            raise
        _silence_broken_pipe()
        return 0


def _main(argv=None):
    args = build_parser().parse_args(argv)
    if args.command == "prime":
        try:
            code = prime.run(args.out, args.ref)
            if code == 0:
                _print_update_notice()
            return code
        except (files.NotARepo, files.BadRef) as err:
            print(err, file=sys.stderr)
            return 1
    handler = HANDLERS.get(args.command)
    if not handler:
        print(f"cbi {args.command}: not implemented yet", file=sys.stderr)
        return 2
    try:
        return handler(args)
    except (files.NotARepo, files.BadRef, NoModel) as err:
        print(err, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

"""Command line entry point for cbi."""

import argparse
import sys
import time
from pathlib import Path

from cbi import files, prime, store

COMMANDS = {
    "init": "Create .cbi/ in this repo and write the ignore file.",
    "scan": "Map the repo into .cbi/model.db and open judgement tasks.",
    "prime": "Print a guide to this tool for the current repo's state. Start here.",
    "status": "Show scan state, task counts and diagnostics.",
    "search": "Full-text search over every node.",
    "show": "Show a node: summary, children, relationships, tests.",
    "tests-for": "List the tests linked to a node.",
    "tasks": "List open judgement tasks.",
    "task": "Print the brief for one task, with the answer's JSON shape.",
    "submit": "Validate and store the answer to a task.",
    "ingest": "Load coverage or test result files (lcov, coverage.py JSON, JUnit XML).",
    "build": "Write the static viewer to .cbi/viewer/.",
}


def build_parser():
    parser = argparse.ArgumentParser(
        prog="cbi",
        description="Map a codebase into a model that agents can query and people can browse. "
        "New here? Run `cbi prime`.",
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>", required=True)
    for name, help_text in COMMANDS.items():
        cmd = sub.add_parser(name, help=help_text, description=DESCRIPTIONS.get(name, help_text),
                             formatter_class=argparse.RawDescriptionHelpFormatter)
        if name in ("init", "scan"):
            cmd.add_argument("--out", metavar="DIR", type=Path,
                             help="model directory to use instead of .cbi/ in the repo root")
    return parser


DESCRIPTIONS = {
    "init": """\
Create .cbi/ in the root of the git repo containing the current directory.
.cbi/ holds a .gitignore of `*`, so no tracked file changes, and `ignore`,
a gitignore-syntax list of tracked paths to leave out of the model (fixtures,
build output, data dirs, minified files). Edit `ignore` freely; rerunning
init keeps it and changes nothing else.

Exit codes: 0 done, 1 not inside a git repo.""",
    "scan": """\
Map the repo and every initialised submodule into DIR/model.db from the
files git tracks, reading content from the working tree, so unstaged edits
count. If nothing changed since the last scan (files, ignore file,
structure.json, checked-out commits), the scan stops early.

Prints node counts by kind, the time taken and whether the no-change
shortcut applied.

Exit codes: 0 done, 1 not inside a git repo or not initialised (run
`cbi init`).""",
}


def _paths(args):
    root = files.repo_root(Path.cwd())
    out = args.out.resolve() if args.out else root / ".cbi"
    return root, out


def cmd_init(args):
    root, out = _paths(args)
    out.mkdir(parents=True, exist_ok=True)
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


def scan(root, out):
    """Run the scan pipeline. Returns (shortcut hit, node counts by display kind)."""
    ignore_text = _read(out / "ignore")
    workspaces, tracked = files.enumerate_repo(root, files.Ignore(ignore_text or ""))
    conn = store.open_db(out / "model.db")
    try:
        old = store.file_states(conn)
        states = files.hash_files(root, tracked, old)
        fp = files.fingerprint(workspaces, ignore_text, _read(out / "structure.json"))
        same_files = {p: s[2] for p, s in states.items()} == {p: s[2] for p, s in old.items()}
        shortcut = same_files and store.get_meta(conn, "fingerprint") == fp
        with conn:
            store.replace_file_states(conn, {p: s[:4] for p, s in states.items()})
            if not shortcut:
                store.replace_enumerated_nodes(conn, files.build_nodes(workspaces, tracked, states))
                store.set_meta(conn, "fingerprint", fp)
        return shortcut, store.counts_by_display_kind(conn)
    finally:
        conn.close()


def cmd_scan(args):
    root, out = _paths(args)
    if not (out / "ignore").exists():
        print(f"{out} is not initialised. Run `cbi init` first.", file=sys.stderr)
        return 1
    start = time.perf_counter()
    shortcut, counts = scan(root, out)
    elapsed = time.perf_counter() - start
    status = "no changes since the last scan" if shortcut else "scanned"
    print(f"{status} in {elapsed:.1f} s")
    for kind, count in counts.items():
        print(f"  {kind}: {count}")
    return 0


HANDLERS = {"init": cmd_init, "scan": cmd_scan}


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.command == "prime":
        prime.run()
        return 0
    handler = HANDLERS.get(args.command)
    if not handler:
        print(f"cbi {args.command}: not implemented yet", file=sys.stderr)
        return 2
    try:
        return handler(args)
    except files.NotARepo as err:
        print(err, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

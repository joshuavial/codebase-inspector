"""Command line entry point for cbi."""

import argparse
import sys

from cbi import prime

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
        sub.add_parser(name, help=help_text, description=help_text)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.command == "prime":
        prime.run()
        return 0
    print(f"cbi {args.command}: not implemented yet", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())

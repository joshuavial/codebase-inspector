"""Command line entry point for cbi."""

import argparse
import json
import sys
import time
from pathlib import Path

from cbi import build, files, parse, prime, store, tasks
from cbi.ids import file_id

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
        if name in ("init", "scan", *READERS):
            cmd.add_argument("--out", metavar="DIR", type=Path,
                             help="model directory to use instead of .cbi/ in the repo root")
        if name in ("search", "show", "tasks", "task"):
            cmd.add_argument("--json", action="store_true", help="print JSON instead of text")
    cmds = sub.choices
    cmds["search"].add_argument("text", help="words to look for; each word also matches as a prefix")
    cmds["search"].add_argument("--limit", type=int, default=20, help="most results to print (default 20)")
    cmds["show"].add_argument("node", help="a node ID, a repo-relative path, path#qualified.name, or a symbol name")
    cmds["tasks"].add_argument("--kind", help="only tasks of this kind, such as summarise-files")
    cmds["tasks"].add_argument("--limit", type=int, help="most tasks to list")
    cmds["task"].add_argument("id", help="task ID from `cbi tasks`")
    cmds["submit"].add_argument("id", help="task ID from `cbi tasks`")
    cmds["submit"].add_argument("file", nargs="?", default="-", help="answer JSON file, or - for stdin (default)")
    return parser


READERS = ("search", "show", "tasks", "task", "submit", "build")


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
    "search": """\
Full-text search over node names, kinds, paths, signatures, docs and
summaries. Prints one line per hit, best first: display kind, name, path
and line, then the node ID to pass to `cbi show`.

--json prints a list of {id, display_kind, name, path, start_line}.

Exit codes: 0 done (even with no hits), 1 no model (run `cbi scan`).""",
    "show": """\
Show one node: its kind, path and lines, summary, signature, doc and
children. NODE can be a node ID, a path from the repo root
(service/registry.ts), a path with a qualified name
(service/registry.ts#DeviceRegistry.load), or a bare symbol name
(DeviceRegistry) when only one symbol has it.

--json prints the node's columns plus `children`, a list of
{id, display_kind, name}.

Exit codes: 0 found, 1 not found, ambiguous (candidates are listed) or no
model.""",
    "tasks": """\
List open judgement tasks, one per line: task ID, kind, the node it covers
and how many files it lists. Take one with `cbi task <id>`.

--json prints a list of {id, kind, node_id, node_display_kind, node_path,
files}.

Exit codes: 0 done, 1 no model (run `cbi scan`).""",
    "task": """\
Print the brief for one task: what to do, the files to read with their
symbol outline, the input_hash your answer must copy, and the JSON Schema
of the answer. Then write the answer to a file and run
`cbi submit <id> <file>`.

--json prints the brief as one JSON object.

Exit codes: 0 done, 1 unknown task or no model.""",
    "submit": """\
Validate an answer and store it. Reads FILE, or stdin when FILE is - or
missing. On success the task is done and each file summary is cached by
file content, so identical files in any repo reuse it. Submitting the same
answer again changes nothing.

Rejected answers print one line per problem, each starting with the JSON
path it refers to ($.files[2].summary: empty). An answer whose input_hash
no longer matches (the files changed and were rescanned) is rejected as
stale: run `cbi task <id>` again.

Exit codes: 0 accepted, 1 no model, 2 answer rejected or unknown task.""",
    "build": """\
Write a static viewer to DIR/viewer/ (.cbi/viewer/ by default): open
index.html straight from disk, no server needed. It shows a breadcrumb,
the focused node's children and a detail pane with summary, signature and
doc. Prints the path of index.html.

Exit codes: 0 done, 1 no model (run `cbi scan`).""",
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
        tasks.attach_cache(conn)
        old = store.file_states(conn)
        states = files.hash_files(root, tracked, old)
        fp = files.fingerprint(workspaces, ignore_text, _read(out / "structure.json"))
        same_files = {p: s[2] for p, s in states.items()} == {p: s[2] for p, s in old.items()}
        shortcut = same_files and store.get_meta(conn, "fingerprint") == fp
        with conn:
            store.replace_file_states(conn, {p: s[:4] for p, s in states.items()})
            if not shortcut:
                known = {r[0] for r in conn.execute("SELECT id FROM nodes WHERE kind = 'file'")}
                store.replace_enumerated_nodes(conn, files.build_nodes(workspaces, tracked, states))
                _parse_changed(conn, root, tracked, states, old, known)
                store.drop_orphan_symbols(conn)
                tasks.refresh(conn)
                # ponytail: full search rebuild per scan; index only changed nodes if it gets slow.
                store.reindex(conn)
                store.set_meta(conn, "fingerprint", fp)
        return shortcut, store.counts_by_display_kind(conn), len(tasks.open_tasks(conn))
    finally:
        conn.close()


def _parse_changed(conn, root, tracked, states, old, known):
    """Parse code files whose content or parser version changed, or that are new to the model."""
    for top, ws, rel in tracked:
        state = states.get(top)
        if not state or state[4]:  # gone from disk, or a symlink
            continue
        role, lang = files.classify(rel)
        fid = file_id(ws["id"], rel)
        prev = old.get(top)
        if lang not in parse.LANGS or (prev and prev[2:4] == state[2:4] and fid in known):
            continue
        source = (root / top).read_bytes()
        nodes, has_error = parse.symbol_nodes(fid, ws["id"], rel, lang, source, role == "test")
        store.replace_file_symbols(conn, ws["id"], rel, len(source.splitlines()), nodes)
        store.set_diagnostic(conn, fid, "parse_error", "tree-sitter reported syntax errors" if has_error else None)


def cmd_scan(args):
    root, out = _paths(args)
    if not (out / "ignore").exists():
        print(f"{out} is not initialised. Run `cbi init` first.", file=sys.stderr)
        return 1
    start = time.perf_counter()
    shortcut, counts, open_count = scan(root, out)
    elapsed = time.perf_counter() - start
    status = "no changes since the last scan" if shortcut else "scanned"
    print(f"{status} in {elapsed:.1f} s")
    for kind, count in counts.items():
        print(f"  {kind}: {count}")
    print(f"{open_count} judgement tasks open" + ("; run `cbi tasks`" if open_count else ""))
    return 0


class NoModel(Exception):
    pass


def _model(args):
    _, out = _paths(args)
    path = out / "model.db"
    if not path.exists():
        raise NoModel(f"no model at {path}. Run `cbi init` and `cbi scan` first.")
    conn = store.open_db(path)
    tasks.attach_cache(conn)
    return conn


def _print_json(value):
    print(json.dumps(value, indent=2))


def _search_query(text):
    """Each word as a quoted FTS5 prefix term, so user text cannot inject query syntax."""
    words = text.split()
    return " ".join('"' + w.replace('"', '""') + '"*' for w in words)


def cmd_search(args):
    conn = _model(args)
    query = _search_query(args.text)
    rows = conn.execute(
        "SELECT n.id, n.display_kind, n.name, n.path, n.start_line FROM search s JOIN nodes n ON n.id = s.id "
        # Weights per column: id, name, display_kind, path, signature, doc, summary.
        "WHERE search MATCH ? ORDER BY bm25(search, 0, 10, 2, 3, 2, 1, 1) LIMIT ?",
        (query, args.limit),
    ).fetchall() if query else []
    hits = [dict(zip(("id", "display_kind", "name", "path", "start_line"), r)) for r in rows]
    if args.json:
        _print_json(hits)
        return 0
    for h in hits:
        where = f"{h['path']}:{h['start_line']}" if h["start_line"] else h["path"]
        print(f"{h['display_kind']:<12} {h['name']}  {where}\n  {h['id']}")
    if not hits:
        print(f"no matches for {args.text!r}")
    return 0


SHOW_COLUMNS = ("id", "parent_id", "kind", "display_kind", "name", "workspace_id", "path", "start_line",
                "end_line", "lang", "loc", "content_hash", "signature", "doc", "summary", "summary_source", "attrs")


def _resolve(conn, ref):
    """Node IDs matching ref, tried as an ID, a path, path#qualified.name, then a symbol name."""
    if conn.execute("SELECT 1 FROM nodes WHERE id = ?", (ref,)).fetchone():
        return [ref]
    path, sep, qualname = ref.partition("#")
    path = path.strip("/")
    found = [r[0] for r in conn.execute(
        "SELECT n.id FROM nodes n LEFT JOIN nodes w ON w.id = n.workspace_id "
        "WHERE n.kind IN ('file', 'doc', 'group') AND (n.path = ? OR "
        "coalesce(json_extract(w.attrs, '$.root'), '') || '/' || n.path = ?) ORDER BY n.id",
        (path, path),
    )]
    if sep:
        found = [f"{f}#{qualname}" for f in found]
        found = [i for i in found if conn.execute("SELECT 1 FROM nodes WHERE id = ?", (i,)).fetchone()]
    if found:
        return found
    return [r[0] for r in conn.execute(
        "SELECT id FROM nodes WHERE kind IN ('symbol', 'test') AND name = ? ORDER BY id", (ref,))]


def cmd_show(args):
    conn = _model(args)
    ids = _resolve(conn, args.node)
    if len(ids) != 1:
        print(f"no node matches {args.node!r}" if not ids else f"{args.node!r} matches {len(ids)} nodes:", file=sys.stderr)
        for i in ids:
            print(f"  {i}", file=sys.stderr)
        return 1
    node = dict(zip(SHOW_COLUMNS, conn.execute(f"SELECT {', '.join(SHOW_COLUMNS)} FROM nodes WHERE id = ?", ids).fetchone()))
    node["attrs"] = json.loads(node["attrs"]) if node["attrs"] else None
    node["children"] = [
        {"id": r[0], "display_kind": r[1], "name": r[2], "start_line": r[3], "end_line": r[4]}
        for r in conn.execute(
            "SELECT id, display_kind, name, start_line, end_line FROM nodes WHERE parent_id = ? "
            "ORDER BY start_line, name", ids)
    ]
    if args.json:
        _print_json(node)
        return 0
    print(f"{node['name']} ({node['display_kind']})")
    print(f"  id: {node['id']}")
    if node["path"]:
        lines = f":{node['start_line']}-{node['end_line']}" if node["start_line"] else ""
        print(f"  path: {node['path']}{lines}")
    if node["loc"]:
        print(f"  lines of code: {node['loc']}")
    if node["summary"] or node["kind"] not in ("symbol", "test"):  # symbols get no summaries in PRD-01
        print(f"  summary: {node['summary'] or '(none yet)'}")
    if node["signature"]:
        print(f"  signature: {node['signature']}")
    if node["doc"]:
        print("  doc: " + node["doc"].replace("\n", "\n       "))
    if node["children"]:
        print(f"  children ({len(node['children'])}):")
        for c in node["children"]:
            lines = f"  L{c['start_line']}-{c['end_line']}" if c["start_line"] else ""
            print(f"    {c['display_kind']:<12} {c['name']}{lines}")
    return 0


def cmd_tasks(args):
    conn = _model(args)
    found = tasks.open_tasks(conn, args.kind, args.limit)
    if args.json:
        _print_json(found)
        return 0
    for t in found:
        print(f"{t['id']}  {t['kind']}  {t['node_display_kind']} {t['node_path'] or t['node_id']}  ({t['files']} files)")
    if not found:
        print("no open tasks")
    return 0


def cmd_task(args):
    conn = _model(args)
    try:
        b = tasks.brief(conn, args.id)
    except tasks.UnknownTask as err:
        print(err, file=sys.stderr)
        return 1
    if args.json:
        _print_json(b)
        return 0
    print(f"# Task {b['id']}: {b['kind']} ({b['state']})")
    print(f"node: {b['node_id']}")
    print(f"input_hash: {b['input_hash']}\n")
    print(b["instructions"] + "\n")
    for f in b["files"]:
        print(f"## {f['path']}  (content {f['content_hash'][:12]})")
        for o in f["outline"]:
            print(f"  {o['display_kind']:<12} L{o['lines']:<9} {o['signature']}")
            if o["doc"]:
                print(f"  {'':<12} {'':<10} {o['doc'].splitlines()[0]}")
        print()
    example = {"input_hash": b["input_hash"], "files": [{"path": f["path"], "summary": "..."} for f in b["files"]]}
    print("## Answer schema")
    print(json.dumps(b["answer_schema"], indent=2))
    print("\n## Answer template")
    print(json.dumps(example, indent=2))
    print(f"\nSubmit with: cbi submit {b['id']} answer.json   (or pipe the JSON to `cbi submit {b['id']} -`)")
    return 0


def cmd_submit(args):
    conn = _model(args)
    try:
        text = sys.stdin.read() if args.file == "-" else Path(args.file).read_text()
    except OSError as err:
        print(f"rejected: cannot read the answer: {err}", file=sys.stderr)
        return 2
    try:
        print(tasks.submit(conn, args.id, text))
    except (tasks.AnswerError, tasks.UnknownTask) as err:
        print(f"rejected: {err}" if isinstance(err, tasks.UnknownTask) else f"rejected:\n{err}", file=sys.stderr)
        return 2
    return 0


def cmd_build(args):
    _, out = _paths(args)
    conn = _model(args)
    print(build.build(conn, out / "viewer"))
    return 0


HANDLERS = {"init": cmd_init, "scan": cmd_scan, "search": cmd_search, "show": cmd_show,
            "tasks": cmd_tasks, "task": cmd_task, "submit": cmd_submit, "build": cmd_build}


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
    except (files.NotARepo, NoModel) as err:
        print(err, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

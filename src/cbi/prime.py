"""State-aware guide for an agent meeting cbi for the first time.

Three states: not initialised or not scanned, judgement tasks pending, and complete.
"""

import json
import shlex
from pathlib import Path

from cbi import files, ingest, parts, store, tasks

NOT_INITIALISED = """\
# cbi: codebase inspector

cbi maps a git repository into a model you can query from the command line,
instead of listing directories and grepping. The model is one tree:

  workspace (the repo; submodules are nested workspaces)
    deployable (something that runs or ships: an app, a service, a CLI)
    package (a library, workspace member or agent skill)
      folder or module
        file
          class, function, method, component, test case

Nodes are linked by imports, calls, tests (test case to the code it
exercises), part-of, depends-on and doc mentions.

cbi never calls a model and never runs the repo's code. Work that needs
judgement, such as summarising files and confirming what the deployables
are, comes back to you as tasks with a JSON answer to submit.

By default every output goes in a hidden .cbi/ directory that ignores
itself, so no tracked file in the repo changes. When the repo must stay untouched,
pass `--out DIR` to init, scan, prime and the other commands.
They read and write DIR instead of .cbi/.

## This repo is not mapped yet

Run these from the repo root:

  cbi init    # create .cbi/ and write .cbi/ignore (edit it to skip data dirs)
  cbi scan    # map the repo; reports what it found and how many tasks wait

Or, to leave the repo untouched:

  cbi init --out DIR
  cbi scan --out DIR
  cbi prime --out DIR

Then run `cbi prime` again. It will show the next step for the repo's
new state.

Every command has `--help` describing its inputs, output and exit codes.
"""

INTRO = """\
# cbi: codebase inspector

This repo is mapped into a model you can query instead of listing
directories and grepping: workspace > deployable/package > folder > file >
class/function/method, linked by imports, calls and tests. `cbi show`,
`cbi search`, `cbi tests-for` and `cbi context` work now; every command has `--help`.
"""

# Printed only when this guide was given --out. A repo that already has .cbi/ is the default,
# and the not-initialised guide is what explains --out before a model exists.
OUT_NOTE = "Pass `--out DIR` on every command when the repo must stay untouched."


def _intro(out_flag):
    text = INTRO.rstrip("\n")
    if out_flag:
        text += "\n" + OUT_NOTE
    return text + "\n"


def run(out=None):
    """Print the guide for the repo containing the current directory. Returns the exit code."""
    try:
        root = files.repo_root(Path.cwd())
    except files.NotARepo:
        print(NOT_INITIALISED, end="")
        return 0
    db = (out.resolve() if out else root / ".cbi") / "model.db"
    if not db.exists():
        print(NOT_INITIALISED, end="")
        return 0
    conn = store.open_db(db)
    token = parts.bind(db.parent)
    try:
        tasks.attach_cache(conn)
        if not conn.execute("SELECT 1 FROM nodes LIMIT 1").fetchone():
            print(NOT_INITIALISED, end="")
            return 0
        counts = conn.execute(
            "SELECT kind, sum(state = 'open'), sum(state = 'blocked') FROM tasks GROUP BY kind ORDER BY kind"
        ).fetchall()
        pending = [c for c in counts if c[1] or c[2]]
        flag = "" if out is None else " --out " + shlex.quote(str(db.parent))
        guide = pending_guide(conn, root, pending, flag) if pending else complete_guide(conn, root, db.parent, flag)
        print(guide, end="")
    finally:
        parts.unbind(token)
        conn.close()
    return 0


def pending_guide(conn, root, counts, out_flag=""):
    open_n, blocked_n = tasks.task_counts(conn)
    lines = [_intro(out_flag), f"## {tasks.task_headline(open_n, blocked_n)}", "",
             "Summaries come from you: cbi never calls a model. Tasks by kind:", ""]
    lines += [f"  {kind:<20} {opened} open, {blocked} blocked" for kind, opened, blocked in counts]
    lines += ["", """\
Tasks run bottom-up. File summaries and confirm-structure are both open first, and they do not wait on each other.
Accepting confirm-structure opens define-concepts beside any file summaries still open.
summarise-deployable stays blocked until confirm-structure is done and that deployable's member files are summarised.
sketch-screens opens after define-concepts is done, when the repo has React components.
A folder task opens once its files and subfolders are summarised, and the workspace task opens last.
""", f"""\
## The loop

  cbi tasks{out_flag}                      # open tasks
  cbi task <id>{out_flag}                  # the brief: what to read, input_hash, answer schema
  cbi submit <id> answer.json{out_flag}    # or pipe the JSON to `cbi submit <id>{out_flag} -`

Repeat until `cbi tasks{out_flag}` prints "no open tasks", then run `cbi prime{out_flag}` again.
"""]
    lines += parts.large_lines(conn, root, out_flag)
    [first] = tasks.open_tasks(conn, limit=1) or [None]
    if first:
        b = tasks.brief(conn, first["id"], root)
        template = tasks.answer_template(b)
        if b["kind"] == "summarise-files":
            entries = [json.dumps(f) for f in template["files"][:2]]
            body = [f'  {{"input_hash": "{b["input_hash"]}", "files": [']
            body += [f"    {e}," for e in entries[:-1]] + [f"    {entries[-1]}", "  ]}"]
        else:
            body = ["  " + json.dumps(template)]
        lines += ["## Worked example", "", f"  $ cbi task {b['id']}{out_flag}",
                  f"  (a {b['kind']} brief for {b['node_id']}; read what it lists)"]
        if b["kind"] == "confirm-structure" and b.get("directories"):
            lines.append("  " + tasks.STRUCTURE_EMPTY)
            lines += ["  " + line for line in b.get("directory_note") or []]
            add = tasks.structure_add_line(b.get("libraries") or [])
            if add:
                lines.append("  " + add)
        lines.append("  $ cat > answer.json <<'EOF'")
        lines += [line.replace('"..."', '"<1 to 3 sentences>"') for line in body]
        lines += ["  EOF", f"  $ cbi submit {b['id']} answer.json{out_flag}", ""]
    lines.append(f"""\
A rejected answer exits 2 and prints one line per problem, starting with
its JSON path ($.files[1].summary: empty). Fix those and submit again.
"stale" means the inputs changed: run `cbi task <id>{out_flag}` again.

Open tasks do not depend on each other, so you can hand several to
subagents at once: give each a task ID and tell it to run `cbi task <id>{out_flag}`,
read what the brief lists and `cbi submit <id>{out_flag}` the answer.
""")
    lines += ["## Ingest", ""]
    lines.extend(ingest.guide_lines(conn, root, out_flag))
    lines.append("")
    return "\n".join(lines)


def _viewer_sentence(model_dir, out_flag):
    path = Path(model_dir) / "viewer" / "index.html"
    verb = "wrote" if path.is_file() else "writes"
    return f"`cbi build{out_flag}` {verb} the static viewer to {path}."


def complete_guide(conn, root, model_dir, out_flag=""):
    top = conn.execute("SELECT id, name, summary FROM nodes WHERE kind = 'workspace' AND parent_id IS NULL").fetchone()
    lines = [_intro(out_flag), "## The map is complete", "", tasks.task_headline(*tasks.task_counts(conn)), ""]
    if top and top[2]:
        lines += [f"{top[1]}: {top[2]}", ""]
    lines += ["Ask the model before opening files. Examples on this repo:", ""]
    symbol = conn.execute(
        # The symbol with the most tests linked to it, then the most incoming edges.
        "SELECT n.id, n.name FROM nodes n LEFT JOIN edges e ON e.dst = n.id WHERE n.kind = 'symbol' "
        "GROUP BY n.id ORDER BY sum(e.kind = 'tests') DESC, count(e.dst) DESC, n.id LIMIT 1"
    ).fetchone()
    folder = conn.execute(
        "SELECT g.path FROM nodes g WHERE g.kind = 'group' AND g.workspace_id = ? AND instr(g.path, '/') = 0 "
        "ORDER BY (SELECT count(*) FROM nodes f WHERE f.kind = 'file' AND f.workspace_id = g.workspace_id "
        "AND substr(f.path, 1, length(g.path) + 1) = g.path || '/') DESC, g.path LIMIT 1",
        (top[0] if top else None,),
    ).fetchone()
    examples = []
    if folder:
        examples.append((_cbi(f"show {folder[0]}/", out_flag), "a folder: summary, children"))
    if symbol:
        file_id, qualname = symbol[0].split("#", 1)
        file_path = conn.execute("SELECT workspace_id, path FROM nodes WHERE id = ?", (file_id,)).fetchone()
        path = tasks._read_path(conn, *file_path)
        examples += [(_cbi(f"search {symbol[1]}", out_flag), "full text over names, paths, docs, summaries"),
                     (_cbi(f"show {path}", out_flag), "a file: summary, symbols, imports"),
                     (_cbi(f"show {path}#{qualname}", out_flag), "a symbol: signature, calls, callers"),
                     (_cbi(f"tests-for {path}", out_flag), "tests linked to the file or its symbols"),
                     (_cbi(f"context {path}#{qualname}", out_flag), "Markdown to paste into an agent")]
    width = max((len(c) for c, _ in examples), default=0)
    lines += [f"  {c:<{width}}  # {why}" for c, why in examples]
    lines += ["", f"""\
Add --json to any read command for machine-readable output. `cbi show`
takes a node ID, a path from the repo root, path#Qualified.name or a bare
symbol name. `cbi hotspots`, `cbi orphans`, `cbi cycles` and `cbi deps`
rank the graph, list unreferenced code, report import cycles and check a
layering rule with `--forbid`. After code changes, run `cbi scan{out_flag}`: it
reparses only changed files and reopens only the tasks whose inputs
changed (check `cbi prime{out_flag}`). {_viewer_sentence(model_dir, out_flag)}
"""]
    lines += ["## Ingest", ""]
    lines.extend(ingest.guide_lines(conn, root, out_flag))
    lines.append("")
    return "\n".join(lines)


def _cbi(command, out_flag):
    """`cbi show a/` or, when the model is outside the repo, `cbi show --out DIR a/`."""
    name, _, rest = command.partition(" ")
    if not out_flag:
        return f"cbi {command}"
    return f"cbi {name}{out_flag} {rest}".rstrip()

"""confirm-structure and summarise-deployable: briefs, checks, structure.json, blocking and the cache."""

import json
import sqlite3

from cbi import resolve, store, tasks
from cbi.cli import main

FILES = {
    "package.json": json.dumps({
        "name": "demo",
        "main": "dist/main.js",
        "bin": {"demo-tool": "bin/missing.js"},
        "scripts": {
            "dev:electron": "node electron/dev.js",
            "verify:package:mobile": "node scripts/verify.js",
        },
    }),
    "tsconfig.json": '{"compilerOptions": {"outDir": "dist", "rootDir": "src"}}',
    "src/main.ts": 'import { core } from "../core/lib";\nexport function main() { return core(); }\n',
    "src/main.test.ts": "import { main } from './main';\ntest('m', () => { main(); });\n",
    "electron/dev.js": "console.log('dev');\n",
    "scripts/verify.js": "console.log('verify');\n",
    "core/lib.ts": "export function core() { return 1; }\n",
    "shared/util.ts": "export const n = 1;\n",
}


def run(capsys, *argv):
    capsys.readouterr()
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def run_json(capsys, *argv):
    code, out, err = run(capsys, *argv, "--json")
    assert code == 0, err
    return json.loads(out)


def submit(capsys, tmp_path, task_id, value):
    path = tmp_path / "answer.json"
    path.write_text(value if isinstance(value, str) else json.dumps(value))
    return run(capsys, "submit", task_id, str(path))


def db():
    return sqlite3.connect(".cbi/model.db")


def task_row(kind, name):
    return db().execute(
        "SELECT t.id, t.state FROM tasks t JOIN nodes n ON n.id = t.node_id WHERE t.kind = ? AND n.name = ?",
        (kind, name),
    ).fetchone()


def members(node_id):
    ws = node_id.split(":deployable:")[0].split(":package:")[0]
    return {r[0].removeprefix(ws + ":") for r in db().execute(
        "SELECT src FROM edges WHERE kind = 'part_of' AND dst = ?", (node_id,))}


def answer_files(capsys, tmp_path):
    for t in run_json(capsys, "tasks", "--kind", "summarise-files"):
        brief = run_json(capsys, "task", t["id"])
        body = {"input_hash": brief["input_hash"],
                "files": [{"path": f["path"], "summary": f"About {f['path']}."} for f in brief["files"]]}
        assert submit(capsys, tmp_path, t["id"], body)[0] == 0


def corrections(brief):
    deployables = []
    kept = None
    for d in brief["deployables"]:
        if d["name"] == "demo-tool":
            deployables.append({"id": d["id"], "remove": True})
        else:
            kept = d["id"]
            deployables.append({"id": d["id"], "name": "server"})
    body = {"input_hash": brief["input_hash"], "deployables": deployables,
            "packages": [{"name": "core", "directory": "core"}, {"name": "shared", "directory": "shared"}]}
    return body, kept


def test_confirm_structure_brief_lists_detection(make_repo, monkeypatch, capsys, tmp_path):
    monkeypatch.chdir(make_repo(FILES, name="demo"))
    assert main(["init"]) == 0 and main(["scan"]) == 0
    task_id, state = task_row("confirm-structure", "demo")
    assert state == "open"
    brief = run_json(capsys, "task", task_id)
    by_name = {d["name"]: d for d in brief["deployables"]}
    assert set(by_name) == {"demo", "demo-tool"}
    assert by_name["demo-tool"]["unresolved"] == ["bin/missing.js"]
    assert by_name["demo-tool"]["entry_points"] == []
    assert brief["packages"] == []
    assert brief["directories"] == ["core", "electron", "scripts", "shared", "src"]
    # core/lib.ts is imported from src. The other bare directories are not.
    assert brief["libraries"] == ["core"]
    assert brief["directory_note"] == [
        "# library, source files imported from elsewhere: core",
        "# scripts or tests, no production file outside imports them: electron, scripts, shared, src",
    ]
    code, text, _ = run(capsys, "task", task_id)
    assert code == 0 and "unresolved: bin/missing.js" in text and "core" in text and brief["input_hash"] in text
    assert "Empty arrays accept detection as it is and do not add a package" in text
    assert "a manifest-less library is created only when you add it" in text
    note, template_text = text.split("## Answer template", 1)
    assert "# library, source files imported from elsewhere: core" in note
    assert "# scripts or tests, no production file outside imports them: electron, scripts, shared, src" in note
    assert 'To add that library, put this in packages: {"name": "core", "directory": "core"}' in note
    template = json.loads(template_text.split("Submit with:", 1)[0])
    assert template == {"input_hash": brief["input_hash"], "deployables": [], "packages": []}

    # summarise-deployable exists but stays blocked until this answer is accepted.
    sd_id, sd_state = task_row("summarise-deployable", "demo")
    assert sd_state == "blocked"
    blocked = run_json(capsys, "task", sd_id)
    assert task_id in blocked["waiting_on"]

    # Submitting the printed template accepts detection and does not invent a package.
    code, _, err = submit(capsys, tmp_path, task_id, template)
    assert code == 0, err
    assert db().execute("SELECT name FROM nodes WHERE kind = 'package'").fetchall() == []


def test_test_import_does_not_make_a_directory_a_library(tmp_path):
    conn = store.open_db(tmp_path / "model.db")
    rows = [
        ("local:r", None, "workspace", "workspace", "r", None, "", '{"root": ""}'),
        ("local:r:service/a.ts", None, "file", "source file", "a.ts", "local:r", "service/a.ts", '{"role": "code"}'),
        ("local:r:src/a.test.ts", None, "file", "test file", "a.test.ts", "local:r", "src/a.test.ts", '{"role": "test"}'),
        ("local:r:core/lib.ts", None, "file", "source file", "lib.ts", "local:r", "core/lib.ts", '{"role": "code"}'),
        ("local:r:app/main.ts", None, "file", "source file", "main.ts", "local:r", "app/main.ts", '{"role": "code"}'),
    ]
    conn.executemany(
        "INSERT INTO nodes (id, parent_id, kind, display_kind, name, workspace_id, path, attrs) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
    conn.executemany(
        "INSERT INTO edges (src, dst, kind, source) VALUES (?, ?, 'imports', 'treesitter')",
        [("local:r:src/a.test.ts", "local:r:service/a.ts"),
         ("local:r:app/main.ts", "local:r:core/lib.ts")])
    libraries, scripts = tasks._classify_directories(conn, ["app", "core", "service", "src"])
    assert libraries == ["core"]
    assert scripts == ["app", "service", "src"]
    conn.close()


def test_confirm_structure_rejects_every_check(make_repo, monkeypatch, capsys, tmp_path):
    monkeypatch.chdir(make_repo(FILES, name="demo"))
    assert main(["init"]) == 0 and main(["scan"]) == 0
    task_id = task_row("confirm-structure", "demo")[0]
    brief = run_json(capsys, "task", task_id)
    bad = {
        "input_hash": brief["input_hash"],
        "deployables": [
            {"id": "nope", "remove": "yes", "extra": True},
            {"entry_points": ["/tmp/abs.js", "../outside.ts"]},
            {"id": brief["deployables"][0]["id"], "remove": True},
            {"id": brief["deployables"][0]["id"], "name": "again"},
        ],
        "packages": [{"name": " ", "directory": "missing"}, {"name": "core"}],
        "colour": "red",
    }
    code, _, err = submit(capsys, tmp_path, task_id, bad)
    assert code == 2
    for line in ("$.colour: unknown key",
                 "$.deployables[0].extra: unknown key",
                 "$.deployables[0].remove: expected boolean, got str",
                 "$.deployables[0].id: 'nope' is not a detected deployable",
                 "$.deployables[1].name: required",
                 "$.deployables[1].entry_points[0]: expected a path relative to the repo root",
                 "$.deployables[1].entry_points[1]: expected a path relative to the repo root",
                 f"$.deployables[3].id: {brief['deployables'][0]['id']!r} given twice",
                 "$.packages[0].name: empty",
                 "$.packages[0].directory: no tracked file under 'missing'",
                 "$.packages[1].directory: required"):
        assert line in err, line
    assert task_row("confirm-structure", "demo")[1] == "open"
    code, _, err = submit(capsys, tmp_path, task_id, {"input_hash": "0" * 16, "deployables": [], "packages": []})
    assert code == 2 and "$.input_hash: stale" in err


def test_accept_writes_structure_keeps_ids_and_reruns(make_repo, monkeypatch, capsys, tmp_path):
    root = make_repo(FILES, name="demo")
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    task_id = task_row("confirm-structure", "demo")[0]
    body, kept = corrections(run_json(capsys, "task", task_id))
    calls = []
    real = resolve.resolve

    def spy(conn, repo_root):
        calls.append(repo_root)
        return real(conn, repo_root)

    monkeypatch.setattr("cbi.tasks.resolve.resolve", spy)
    code, out, err = submit(capsys, tmp_path, task_id, body)
    assert code == 0, err
    assert "accepted" in out and len(calls) == 1
    assert task_row("confirm-structure", "demo")[1] == "done"

    doc = json.loads((root / ".cbi" / "structure.json").read_text())
    renamed = next(d for d in doc["deployables"] if d.get("name") == "server")
    assert renamed["id"] == kept
    assert {d["id"].split(":deployable:", 1)[1] for d in doc["deployables"] if d.get("remove")} == {"demo-tool"}
    assert {p["name"] for p in doc["packages"]} == {"core", "shared"}

    conn = db()
    found = {r[0]: r[1] for r in conn.execute("SELECT id, name FROM nodes WHERE kind = 'deployable'")}
    assert found == {kept: "server"}
    assert members(kept) >= {"src/main.ts", "core/lib.ts"}
    assert "electron/dev.js" not in members(kept)
    assert members("local:demo:package:core") == {"core/lib.ts"}
    assert members("local:demo:package:shared") == {"shared/util.ts"}
    assert ("local:demo:deployable:demo", "local:demo:package:core") in conn.execute(
        "SELECT src, dst FROM edges WHERE kind = 'depends_on'").fetchall()
    # The removed deployables took their summary tasks with them; the renamed one is still blocked on files.
    assert task_row("summarise-deployable", "server")[1] == "blocked"
    assert task_row("summarise-deployable", "dev:electron") is None

    code, out, _ = submit(capsys, tmp_path, task_id, body)
    assert code == 0 and "nothing changed" in out and len(calls) == 1
    run(capsys, "scan")
    assert db().execute("SELECT name FROM nodes WHERE id = ?", (kept,)).fetchone()[0] == "server"


def test_summarise_deployable_blocks_then_summarises(make_repo, monkeypatch, capsys, tmp_path):
    monkeypatch.chdir(make_repo(FILES, name="demo"))
    assert main(["init"]) == 0 and main(["scan"]) == 0
    cs = task_row("confirm-structure", "demo")[0]
    body, kept = corrections(run_json(capsys, "task", cs))
    assert submit(capsys, tmp_path, cs, body)[0] == 0
    sd, state = task_row("summarise-deployable", "server")
    assert state == "blocked"
    code, _, err = submit(capsys, tmp_path, sd, {"input_hash": "x", "summary": "Ships the server."})
    assert code == 2 and "blocked" in err

    answer_files(capsys, tmp_path)
    assert task_row("summarise-deployable", "server")[1] == "open"
    brief = run_json(capsys, "task", sd)
    assert brief["entry_points"] == ["src/main.ts"]
    files = {f["path"]: f["summary"] for f in brief["files"]}
    assert files["src/main.ts"] == "About src/main.ts." and files["core/lib.ts"] == "About core/lib.ts."
    assert [p["name"] for p in brief["packages"]] == ["core"]
    code, text, _ = run(capsys, "task", sd)
    assert code == 0 and "About core/lib.ts." in text and "src/main.ts" in text

    bad = {"input_hash": brief["input_hash"], "summary": " ", "colour": "red"}
    code, _, err = submit(capsys, tmp_path, sd, bad)
    assert code == 2 and "$.summary: empty" in err and "$.colour: unknown key" in err

    code, out, err = submit(capsys, tmp_path, sd, {"input_hash": brief["input_hash"], "summary": "Ships the server."})
    assert code == 0 and "accepted" in out, err
    assert run_json(capsys, "show", kept)["summary"] == "Ships the server."
    code, out, _ = submit(capsys, tmp_path, sd, {"input_hash": brief["input_hash"], "summary": "Ships the server."})
    assert code == 0 and "nothing changed" in out
    # The workspace summary stays blocked on the deployable until that summary exists, then lists it.
    assert task_row("summarise-workspace", "demo")[1] == "blocked"


def test_changed_member_summary_reopens_deployable(make_repo, monkeypatch, capsys, tmp_path):
    monkeypatch.chdir(make_repo(FILES, name="demo"))
    assert main(["init"]) == 0 and main(["scan"]) == 0
    cs = task_row("confirm-structure", "demo")[0]
    body, _kept = corrections(run_json(capsys, "task", cs))
    submit(capsys, tmp_path, cs, body)
    answer_files(capsys, tmp_path)
    sd = task_row("summarise-deployable", "server")[0]
    brief = run_json(capsys, "task", sd)
    submit(capsys, tmp_path, sd, {"input_hash": brief["input_hash"], "summary": "Ships the server."})
    # Finish the folders so the workspace itself is answered, then change one member file.
    while found := [t for t in run_json(capsys, "tasks")
                    if t["kind"] not in ("summarise-workspace", "define-concepts")]:
        for t in found:
            b = run_json(capsys, "task", t["id"])
            submit(capsys, tmp_path, t["id"], {"input_hash": b["input_hash"], "summary": f"About {b['node']['name']}."})
    ws = task_row("summarise-workspace", "demo")
    assert ws[1] == "open"
    b = run_json(capsys, "task", ws[0])
    assert any(c["name"] == "server" and c["summary"] == "Ships the server." for c in b["children"])
    submit(capsys, tmp_path, ws[0], {"input_hash": b["input_hash"], "summary": "A demo server."})
    assert task_row("summarise-workspace", "demo")[1] == "done"

    # The file task is done, so it is not listed; answer it again from its id.
    file_id = db().execute(
        "SELECT t.id FROM tasks t JOIN nodes n ON n.id = t.node_id WHERE t.kind = 'summarise-files' AND n.path = 'core'"
    ).fetchone()[0]
    fb = run_json(capsys, "task", file_id)
    changed = {"input_hash": fb["input_hash"], "files": [
        {"path": f["path"], "summary": "A different summary." if f["path"] == "core/lib.ts" else f"About {f['path']}."}
        for f in fb["files"]]}
    code, out, err = submit(capsys, tmp_path, file_id, changed)
    assert code == 0, err
    assert task_row("summarise-deployable", "server")[1] == "open"
    assert sd in out
    assert task_row("summarise-workspace", "demo")[1] == "blocked"


def test_second_repo_reuses_structure_and_deployable_summary(make_repo, monkeypatch, capsys, tmp_path):
    def build(name):
        monkeypatch.chdir(make_repo(FILES, name=name))
        assert main(["init"]) == 0 and main(["scan"]) == 0

    build("first")
    cs = task_row("confirm-structure", "first")[0]
    body, kept = corrections(run_json(capsys, "task", cs))
    submit(capsys, tmp_path, cs, body)
    answer_files(capsys, tmp_path)
    sd = task_row("summarise-deployable", "server")[0]
    brief = run_json(capsys, "task", sd)
    submit(capsys, tmp_path, sd, {"input_hash": brief["input_hash"], "summary": "Ships the server."})

    build("second")
    assert db().execute("SELECT state FROM tasks WHERE kind = 'confirm-structure'").fetchone()[0] == "done"
    assert db().execute("SELECT state FROM tasks WHERE kind = 'summarise-deployable'").fetchone()[0] == "done"
    assert db().execute("SELECT id, name FROM nodes WHERE kind = 'deployable'").fetchone() == (
        "local:second:deployable:demo", "server")
    assert kept == "local:first:deployable:demo"
    doc = json.loads((make_repo.__wrapped__ if False else open(".cbi/structure.json")).read() if False else
                     open(".cbi/structure.json").read())
    assert doc["deployables"]
    assert any(d["id"] == "local:second:deployable:demo" and d["name"] == "server" for d in doc["deployables"])
    assert {p["id"] for p in doc["packages"]} == {"local:second:package:core", "local:second:package:shared"}
    assert run_json(capsys, "show", "local:second:deployable:demo")["summary"] == "Ships the server."


def test_stale_when_detection_changes(make_repo, monkeypatch, capsys, tmp_path):
    root = make_repo(FILES, name="demo")
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    task_id = task_row("confirm-structure", "demo")[0]
    body, _kept = corrections(run_json(capsys, "task", task_id))
    assert submit(capsys, tmp_path, task_id, body)[0] == 0
    pkg = json.loads((root / "package.json").read_text())
    # A new script whose entry is not already claimed. A second script on an existing
    # entry is dropped as a duplicate and would not change the detection hash.
    pkg["scripts"]["extra"] = "node core/lib.ts"
    (root / "package.json").write_text(json.dumps(pkg))
    assert main(["scan"]) == 0
    code, _, err = submit(capsys, tmp_path, task_id, body)
    assert code == 2 and "$.input_hash: stale" in err
    assert task_row("confirm-structure", "demo")[1] == "open"


def test_hand_edit_is_kept_and_reopens_the_task(make_repo, monkeypatch, capsys, tmp_path):
    root = make_repo(FILES, name="demo")
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    task_id = task_row("confirm-structure", "demo")[0]
    body, kept = corrections(run_json(capsys, "task", task_id))
    assert submit(capsys, tmp_path, task_id, body)[0] == 0
    path = root / ".cbi" / "structure.json"
    doc = json.loads(path.read_text())
    renamed = next(d for d in doc["deployables"] if d.get("id") == kept)
    renamed["name"] = "api"
    path.write_text(json.dumps(doc, indent=2) + "\n")
    assert main(["scan"]) == 0
    written = json.loads(path.read_text())
    assert next(d for d in written["deployables"] if d.get("id") == kept)["name"] == "api"
    assert task_row("confirm-structure", "demo")[1] == "open"
    assert db().execute("SELECT name FROM nodes WHERE id = ?", (kept,)).fetchone()[0] == "api"
    brief = run_json(capsys, "task", task_id)
    assert brief["overrides"]["deployables"]
    assert next(d["name"] for d in brief["overrides"]["deployables"] if d["id"] == kept) == "api"

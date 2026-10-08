"""The thin end-to-end path: scan, tasks, task, submit, show, search and build on a TS pair."""

import io
import json
import sqlite3
from pathlib import Path

import pytest

from cbi.cli import main

PAIR = Path(__file__).parent / "fixtures" / "tracer"
SUBJECT = "service/registry.ts"
TEST = "service/registry.test.ts"


def run(capsys, *argv):
    capsys.readouterr()
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def run_json(capsys, *argv):
    code, out, err = run(capsys, *argv, "--json")
    assert code == 0, err
    return json.loads(out)


@pytest.fixture
def pair_repo(make_repo, monkeypatch):
    def make(name="repo", files=(SUBJECT, TEST)):
        root = make_repo({rel: (PAIR / Path(rel).name).read_text() for rel in files}, name=name)
        monkeypatch.chdir(root)
        assert main(["init"]) == 0
        return root
    return make


def answer(brief, **summaries):
    return json.dumps({
        "input_hash": brief["input_hash"],
        "files": [{"path": f["path"], "summary": summaries.get(f["path"], f"Summary of {f['path']}.")} for f in brief["files"]],
    })


def submit(capsys, tmp_path, task_id, text):
    path = tmp_path / "answer.json"
    path.write_text(text)
    return run(capsys, "submit", task_id, str(path))


def file_task(capsys):
    [task] = [t for t in run_json(capsys, "tasks") if t["kind"] == "summarise-files"]
    return task


def test_tracer_loop(pair_repo, tmp_path, capsys):
    root = pair_repo()
    code, out, _ = run(capsys, "scan")
    assert code == 0 and "2 judgement tasks open" in out and "class: 1" in out and "test case: 2" in out

    task = file_task(capsys)
    assert task["kind"] == "summarise-files" and task["node_path"] == "service" and task["files"] == 2
    brief = run_json(capsys, "task", task["id"])
    assert [f["path"] for f in brief["files"]] == [TEST, SUBJECT]
    outline = {o["name"]: o for o in brief["files"][1]["outline"]}
    assert outline["DeviceRegistry"]["signature"] == "class DeviceRegistry"
    assert outline["DeviceRegistry"]["doc"] == "Keeps paired devices in memory, keyed by device ID."
    assert brief["answer_schema"]["required"] == ["input_hash", "files"]
    code, text, _ = run(capsys, "task", task["id"])
    assert code == 0 and brief["input_hash"] in text and '"answer_schema"' not in text and "maxLength" in text

    summary = "Holds paired devices in memory and lets the service revoke them."
    good = answer(brief, **{SUBJECT: summary})
    code, out, _ = submit(capsys, tmp_path, task["id"], good)
    assert code == 0 and "accepted 2" in out
    assert run_json(capsys, "tasks", "--kind", "summarise-files") == []
    code, out, _ = submit(capsys, tmp_path, task["id"], good)
    assert code == 0 and "nothing changed" in out

    code, out, _ = run(capsys, "show", "DeviceRegistry")
    assert code == 0
    assert "DeviceRegistry (class)" in out and "signature: class DeviceRegistry" in out
    assert "doc: Keeps paired devices in memory" in out and "method       revoke  L20-25" in out
    shown = run_json(capsys, "show", SUBJECT)
    assert shown["summary"] == summary and shown["display_kind"] == "source file"
    assert [c["name"] for c in shown["children"]] == ["DeviceRecord", "DeviceRegistry"]
    method = run_json(capsys, "show", f"{SUBJECT}#DeviceRegistry.put")
    assert method["id"] == f"local:repo:{SUBJECT}#DeviceRegistry.put" and method["doc"] == "Adds or replaces a device."
    assert run(capsys, "show", "nothing-like-this")[0] == 1

    hits = run_json(capsys, "search", "revoke")
    assert {h["id"] for h in hits} >= {f"local:repo:{SUBJECT}#DeviceRegistry.revoke", f"local:repo:{TEST}#revokes a device"}
    assert run_json(capsys, "search", "lets the service")[0]["id"] == f"local:repo:{SUBJECT}"
    assert run_json(capsys, "search", 'dev"ice OR') == []

    code, out, _ = run(capsys, "build")
    viewer = root / ".cbi" / "viewer"
    assert code == 0 and out.strip() == str(viewer / "index.html")
    tree = (viewer / "data" / "tree.js").read_text()
    assert tree.startswith('cbiLoad("tree", ') and summary in tree
    payload = json.loads(tree.removeprefix('cbiLoad("tree", ').removesuffix(");\n"))
    assert any(n["id"] == f"local:repo:{SUBJECT}#DeviceRegistry" for n in payload["nodes"])
    html = (viewer / "index.html").read_text()
    assert "app.js" in html and "data/tree.js" not in html
    assert 's.src = "data/tree.js"' in (viewer / "app.js").read_text()
    assert "innerHTML" not in (viewer / "app.js").read_text()


def test_validation_errors_name_the_json_path(pair_repo, tmp_path, capsys):
    pair_repo()
    run(capsys, "scan")
    task = file_task(capsys)
    brief = run_json(capsys, "task", task["id"])
    bad = {"input_hash": brief["input_hash"], "files": [{"path": SUBJECT, "summary": " "}, {"path": "x.ts", "summary": "s"}], "extra": 1}
    code, _, err = submit(capsys, tmp_path, task["id"], json.dumps(bad))
    assert code == 2 and "$.files[0].summary: empty" in err and "$.extra: unknown key" in err
    del bad["extra"]
    bad["files"][0]["summary"] = "ok"
    code, _, err = submit(capsys, tmp_path, task["id"], json.dumps(bad))
    assert code == 2 and "$.files[1].path: 'x.ts' is not in this task" in err and f"$.files: missing '{TEST}'" in err
    code, _, err = submit(capsys, tmp_path, task["id"], "{not json")
    assert code == 2 and err.startswith("rejected:\n$: not valid JSON")
    assert run(capsys, "submit", "sf-nope-1", "-")[0] == 2
    assert {t["kind"] for t in run_json(capsys, "tasks")} == {"confirm-structure", "summarise-files"}


def test_stale_answer_rejected_after_rescan(pair_repo, tmp_path, capsys, monkeypatch):
    root = pair_repo()
    run(capsys, "scan")
    task = file_task(capsys)
    old_brief = run_json(capsys, "task", task["id"])
    first = answer(old_brief)
    assert submit(capsys, tmp_path, task["id"], first)[0] == 0

    with open(root / SUBJECT, "a") as f:
        f.write("export const extra = () => 1;\n")
    run(capsys, "scan")
    reopened = file_task(capsys)
    assert reopened["id"] == task["id"] and reopened["files"] == 1
    assert run_json(capsys, "show", SUBJECT)["summary"] is None
    assert run_json(capsys, "show", TEST)["summary"] == f"Summary of {TEST}."

    code, _, err = submit(capsys, tmp_path, task["id"], first)
    assert code == 2 and "$.input_hash: stale" in err and f"cbi task {task['id']}" in err

    new_brief = run_json(capsys, "task", task["id"])
    assert [f["path"] for f in new_brief["files"]] == [SUBJECT]
    monkeypatch.setattr("sys.stdin", io.StringIO(answer(new_brief, **{SUBJECT: "Now with extra."})))
    assert run(capsys, "submit", task["id"], "-")[0] == 0
    assert run_json(capsys, "show", SUBJECT)["summary"] == "Now with extra."


def test_answer_cache_is_shared_across_repos(pair_repo, tmp_path, capsys, answer_cache):
    pair_repo("first")
    run(capsys, "scan")
    task = file_task(capsys)
    brief = run_json(capsys, "task", task["id"])
    assert submit(capsys, tmp_path, task["id"], answer(brief, **{SUBJECT: "Cached summary."}))[0] == 0
    assert (answer_cache / "answers.db").exists()

    pair_repo("second", files=(SUBJECT,))
    code, out, _ = run(capsys, "scan")
    assert code == 0 and "2 judgement tasks open" in out
    assert run_json(capsys, "tasks", "--kind", "summarise-files") == []
    assert run_json(capsys, "show", SUBJECT)["summary"] == "Cached summary."
    conn = sqlite3.connect(Path.cwd() / ".cbi" / "model.db")
    assert conn.execute("SELECT count(*) FROM tasks WHERE state = 'open' AND kind = 'summarise-files'").fetchone() == (0,)


def test_read_commands_need_a_model(make_repo, monkeypatch, capsys):
    monkeypatch.chdir(make_repo({"a.ts": "export {};\n"}))
    for argv in (["show", "a.ts"], ["search", "a"], ["tasks"], ["build"]):
        code, _, err = run(capsys, *argv)
        assert code == 1 and "cbi scan" in err

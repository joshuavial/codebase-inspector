"""Large-brief parts, draft checks, task paging, and concurrent submits."""

import json
import multiprocessing
import os
import sqlite3
import time
from pathlib import Path

from cbi import parts, store, tasks
from cbi.cli import main

PAD = "p" * 80


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
    path = tmp_path / f"answer-{task_id}.json"
    path.write_text(json.dumps(value))
    return run(capsys, "submit", task_id, str(path))


def scan(make_repo, monkeypatch, files, name="repo"):
    root = make_repo(files, name=name)
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    return root


def confirm(capsys, tmp_path):
    [task] = run_json(capsys, "tasks", "--kind", "confirm-structure")
    brief = run_json(capsys, "task", task["id"])
    code, _, err = submit(capsys, tmp_path, task["id"], {
        "input_hash": brief["input_hash"], "deployables": [], "packages": [],
    })
    assert code == 0, err


def test_brief_header_states_its_size(make_repo, monkeypatch, capsys):
    scan(make_repo, monkeypatch, {"src/a.ts": "export function a() { return 1; }\n"})
    [task] = run_json(capsys, "tasks", "--kind", "summarise-files")
    code, text, err = run(capsys, "task", task["id"])
    assert code == 0, err
    size = int(text.splitlines()[1].removeprefix("size: ").removesuffix(" bytes"))
    assert size == len(text.encode())
    listed = run_json(capsys, "task", task["id"])
    assert listed["bytes"] == size


def test_tasks_limit_and_offset(make_repo, monkeypatch, capsys):
    files = {f"p{i}/a.ts": "export const a = 1;\n" for i in range(4)}
    scan(make_repo, monkeypatch, files)
    whole = run_json(capsys, "tasks", "--kind", "summarise-files")
    assert len(whole) == 4
    page = run_json(capsys, "tasks", "--kind", "summarise-files", "--limit", "2", "--offset", "1")
    assert [row["id"] for row in page] == [row["id"] for row in whole[1:3]]
    code, _, err = run(capsys, "tasks", "--offset", "-1")
    assert code == 2 and "offset" in err


def _submit_one(root, cache, task_id, payload, ready, start, queue):
    os.environ["CBI_CACHE_DIR"] = cache
    os.chdir(root)
    ready.put(task_id)
    if not start.wait(60):
        queue.put("not started")
        return
    from cbi.cli import main
    path = Path(cache) / f"{task_id}.json"
    path.write_text(payload)
    try:
        queue.put(main(["submit", task_id, str(path)]))
    except Exception as exc:
        queue.put(f"error {exc}")


def test_parallel_submits_from_several_processes(make_repo, monkeypatch, capsys, tmp_path):
    files = {f"p{i}/a.ts": "export const a = 1;\n" for i in range(4)}
    root = scan(make_repo, monkeypatch, files, name="parallel")
    tasks = run_json(capsys, "tasks", "--kind", "summarise-files")
    answers = []
    for task in tasks:
        brief = run_json(capsys, "task", task["id"])
        answers.append((task["id"], json.dumps({
            "input_hash": brief["input_hash"],
            "files": [{"path": item["path"], "summary": f"About {item['path']}."} for item in brief["files"]],
        })))
    ctx = multiprocessing.get_context("spawn")
    ready, start, queue = ctx.Queue(), ctx.Event(), ctx.Queue()
    cache = os.environ["CBI_CACHE_DIR"]
    procs = [
        ctx.Process(target=_submit_one, args=(str(root), cache, task_id, payload, ready, start, queue))
        for task_id, payload in answers
    ]
    for proc in procs:
        proc.start()
    for _ in procs:
        assert ready.get(timeout=60)
    conn = sqlite3.connect(root / ".cbi" / "model.db", timeout=30)
    conn.execute("BEGIN IMMEDIATE")
    start.set()
    time.sleep(0.4)
    conn.rollback()
    conn.close()
    codes = [queue.get(timeout=60) for _ in procs]
    for proc in procs:
        proc.join(30)
    assert codes == [0, 0, 0, 0]
    assert not run_json(capsys, "tasks", "--kind", "summarise-files")


def test_concept_parts_follow_areas_and_check_does_not_submit(make_repo, monkeypatch, capsys, tmp_path):
    files = {
        "pkg-a/package.json": '{"name": "pkg-a", "private": true}\n',
        "pkg-a/a.ts": f"import {{ b }} from '../pkg-b/b';\nimport {{ c }} from './c';\nexport function a() {{ return b() + c(); }}\n",
        "pkg-a/c.ts": "export function c() { return 1; }\n",
        "pkg-b/package.json": '{"name": "pkg-b", "private": true}\n',
        "pkg-b/b.ts": f"/** {PAD} */\nexport function b() {{ return 1; }}\n",
    }
    root = scan(make_repo, monkeypatch, files, name="areas")
    confirm(capsys, tmp_path)
    [task] = run_json(capsys, "tasks", "--kind", "define-concepts")
    whole = run_json(capsys, "task", task["id"], "--parts")
    assert whole["split"] is False
    monkeypatch.setenv("CBI_BRIEF_BUDGET", str(whole["brief_bytes"] - 1))
    spec = run_json(capsys, "task", task["id"], "--parts")
    assert spec["split"] is True and spec["budget"] == whole["brief_bytes"] - 1
    names = [part["name"] for part in spec["parts"]]
    assert "package pkg-a" in names and "package pkg-b" in names and any(name.startswith("cross-area") for name in names)
    by_name = {}
    for part in spec["parts"]:
        code, text, err = run(capsys, "task", task["id"], "--part", str(part["index"]))
        assert code == 0, err
        assert text.startswith("# Task") and f"part: {part['index']} of" in text
        assert len(text.encode()) == part["bytes"]
        by_name[part["name"]] = text
    area = by_name["package pkg-a"]
    assert "pkg-a/a.ts" in area and "pkg-a/c.ts" in area and "pkg-b/b.ts" not in area.split("## Import")[0]
    assert "pkg-a/a.ts -> pkg-a/c.ts" in area
    assert "pkg-a/a.ts -> pkg-b/b.ts" not in area
    cross = next(text for name, text in by_name.items() if name.startswith("cross-area"))
    assert "pkg-a/a.ts -> pkg-b/b.ts" in cross
    assert "package pkg-a:" in cross and "package pkg-b:" in cross
    brief = run_json(capsys, "task", task["id"])
    draft = {
        "input_hash": brief["input_hash"], "summary": "Two packages.",
        "concepts": [{"id": "a", "name": "A", "summary": "Package a.", "role": "core", "files": ["pkg-a/a.ts"]}],
        "externals": [], "relationships": [],
    }
    path = tmp_path / "draft.json"
    path.write_text(json.dumps(draft))
    code, _, err = run(capsys, "task", task["id"], "--check", str(path))
    assert code == 2 and "pkg-a/c.ts" in err and "pkg-b/b.ts" in err
    assert not (root / ".cbi" / "concepts.json").exists()
    draft["concepts"] = [
        {"id": "a", "name": "A", "summary": "Package a.", "role": "core", "files": ["pkg-a/a.ts", "pkg-a/c.ts"]},
        {"id": "b", "name": "B", "summary": "Package b.", "role": "core", "files": ["pkg-b/b.ts"]},
    ]
    draft["relationships"] = [{"from": "a", "to": "b", "label": "uses", "basis": "imports"}]
    path.write_text(json.dumps(draft))
    code, out, err = run(capsys, "task", task["id"], "--check", str(path))
    assert code == 0 and out.strip() == "ok", err
    assert not (root / ".cbi" / "concepts.json").exists()
    conn = store.open_db(root / ".cbi" / "model.db")
    try:
        state = conn.execute("SELECT state FROM tasks WHERE id = ?", (task["id"],)).fetchone()[0]
    finally:
        conn.close()
    assert state == "open"
    code, _, err = run(capsys, "task", task["id"], "--part", "0")
    assert code == 2 and "outside" in err
    code, _, err = run(capsys, "task", task["id"], "--parts")
    # summarise-files is the wrong kind
    [files_task] = run_json(capsys, "tasks", "--kind", "summarise-files", "--limit", "1")
    code, _, err = run(capsys, "task", files_task["id"], "--parts")
    assert code == 2 and "not split" in err


def test_a_brief_under_the_budget_is_one_part(make_repo, monkeypatch, capsys, tmp_path):
    scan(make_repo, monkeypatch, {"src/a.ts": "export function a() { return 1; }\n"}, name="small")
    confirm(capsys, tmp_path)
    [task] = run_json(capsys, "tasks", "--kind", "define-concepts")
    spec = run_json(capsys, "task", task["id"], "--parts")
    assert spec["split"] is False and len(spec["parts"]) == 1
    assert spec["brief_bytes"] <= spec["budget"]
    code, part, err = run(capsys, "task", task["id"], "--part", "1")
    whole_code, whole, whole_err = run(capsys, "task", task["id"])
    assert code == 0 and whole_code == 0, err or whole_err
    assert part == whole


def test_screen_parts_keep_whole_jsx(make_repo, monkeypatch, capsys, tmp_path):
    def component(name, marker):
        body = "\n".join(f"<i>{marker}-{i}</i>" for i in range(420))
        return f"export function {name}() {{ return <div>\n{body}\n</div>; }}\n"

    root = scan(make_repo, monkeypatch, {
        "a/package.json": '{"name": "a", "main": "App.tsx"}\n',
        "a/App.tsx": component("App", "app-end"),
        "b/package.json": '{"name": "b", "main": "Page.tsx"}\n',
        "b/Page.tsx": component("Page", "page-end"),
    }, name="screens")
    confirm(capsys, tmp_path)
    [task] = run_json(capsys, "tasks", "--kind", "define-concepts")
    brief = run_json(capsys, "task", task["id"])
    paths = sorted(item["path"] for item in brief["files"])
    answer = {
        "input_hash": brief["input_hash"], "summary": "Two screens.",
        "concepts": [{"id": "ui", "name": "UI", "summary": "The screens.", "role": "ui", "files": paths}],
        "externals": [], "relationships": [],
    }
    assert submit(capsys, tmp_path, task["id"], answer)[0] == 0
    [screen] = run_json(capsys, "tasks", "--kind", "sketch-screens")
    code, whole, err = run(capsys, "task", screen["id"])
    assert code == 0 and "jsx truncated" in whole, err
    monkeypatch.setenv("CBI_BRIEF_BUDGET", "1")
    spec = run_json(capsys, "task", screen["id"], "--parts")
    assert spec["split"] is True
    names = " ".join(part["name"] for part in spec["parts"])
    assert "deployable a" in names and "deployable b" in names
    seen = set()
    for part in spec["parts"]:
        code, text, err = run(capsys, "task", screen["id"], "--part", str(part["index"]))
        assert code == 0, err
        assert "jsx truncated" not in text
        if "app-end-419" in text:
            seen.add("app")
            assert "app-end-0" in text
        if "page-end-419" in text:
            seen.add("page")
    assert seen == {"app", "page"}
    assert not (root / ".cbi" / "screens.json").exists()


def test_current_concepts_are_printed_once(make_repo, monkeypatch, capsys, tmp_path):
    files = {
        "pkg-a/package.json": '{"name": "pkg-a", "private": true}\n',
        "pkg-b/package.json": '{"name": "pkg-b", "private": true}\n',
    }
    for i in range(24):
        files[f"pkg-a/a{i:02}.ts"] = (
            f"import {{ b{i} }} from '../pkg-b/b{i:02}';\nexport const a{i} = b{i}();\n"
        )
        files[f"pkg-b/b{i:02}.ts"] = f"export function b{i}() {{ return {i}; }}\n"
    root = scan(make_repo, monkeypatch, files, name="concepts-once")
    confirm(capsys, tmp_path)
    [task] = run_json(capsys, "tasks", "--kind", "define-concepts")
    brief = run_json(capsys, "task", task["id"])
    paths = sorted(item["path"] for item in brief["files"])
    children = []
    for i in range(8):
        child = {
            "id": f"c{i}", "name": f"Part {i}", "role": "core",
            "summary": ("CONCEPTMARKER " if i == 0 else "") + ("m" * 560),
        }
        if i == 0:
            child["files"] = paths
        children.append(child)
    answer = {
        "input_hash": brief["input_hash"], "summary": "Two packages and a map.",
        "concepts": [{"id": "root", "name": "Root", "summary": "The system.", "role": "core", "children": children}],
        "externals": [], "relationships": [],
    }
    assert submit(capsys, tmp_path, task["id"], answer)[0] == 0
    conn = store.open_db(root / ".cbi" / "model.db")
    try:
        fresh = tasks.brief(conn, task["id"], root)
    finally:
        conn.close()
    full = len(parts.render_text(fresh).encode())
    concept_bytes = len(json.dumps(fresh["concepts"]).encode())
    limit = concept_bytes + 8000
    assert concept_bytes < limit < full
    monkeypatch.setenv("CBI_BRIEF_BUDGET", str(limit))
    spec = run_json(capsys, "task", task["id"], "--parts")
    assert spec["split"] is True and len(spec["parts"]) >= 2
    hits = 0
    for part in spec["parts"]:
        code, text, err = run(capsys, "task", task["id"], "--part", str(part["index"]))
        assert code == 0, err
        hits += "CONCEPTMARKER" in text
        assert len(text.encode()) == part["bytes"]
    assert hits == 1
    joined = ""
    for part in spec["parts"]:
        if part["name"].startswith("cross-area"):
            _, text, _ = run(capsys, "task", task["id"], "--part", str(part["index"]))
            joined += text
    assert "pkg-a/a00.ts -> pkg-b/b00.ts" in joined and "pkg-a/a23.ts -> pkg-b/b23.ts" in joined


def test_prime_explains_parts_when_the_brief_is_large(make_repo, monkeypatch, capsys, tmp_path):
    scan(make_repo, monkeypatch, {"src/a.ts": "export function a() { return 1; }\n"}, name="prime")
    code, out, err = run(capsys, "prime")
    assert code == 0 and "--parts" not in out, err
    confirm(capsys, tmp_path)
    monkeypatch.setenv("CBI_BRIEF_BUDGET", "1")
    code, out, err = run(capsys, "prime")
    assert code == 0, err
    assert "--parts" in out and "--part 1" in out and "--check answer.json" in out and "cbi submit" in out
    assert "## Large briefs" in out and "seeds/" in out and "fixture builders" in out

"""A generated repo of about 1,500 files: parts under the budget, a checked draft, parallel submits."""

import json
import multiprocessing
import os
import sqlite3
import time
from collections import defaultdict

from cbi.cli import main

from test_parts import _submit_one, run, run_json

PACKAGES = [f"pkg-{name}" for name in "abcdef"]
DOC = "p" * 120


def _source(pkg, n, extra=""):
    return (
        f"/** {DOC} */\n"
        f"{extra}"
        f"export function f_{n}({DOC}) {{ return {n}; }}\n"
    )


def _files():
    files = {}
    for pkg in PACKAGES:
        files[f"{pkg}/package.json"] = json.dumps({"name": pkg, "private": True}) + "\n"
        for n in range(250):
            extra = ""
            if pkg == "pkg-a" and n == 0:
                extra = 'import { f_0 as other } from "../pkg-b/f000";\n'
            files[f"{pkg}/f{n:03}.ts"] = _source(pkg, n, extra)
    return files


def test_large_repo_parts_check_and_parallel_submits(make_repo, monkeypatch, capsys, tmp_path):
    root = make_repo(_files(), name="large")
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    tasks = run_json(capsys, "tasks", "--kind", "summarise-files", "--limit", "4")
    assert len(tasks) == 4
    answers = []
    for task in tasks:
        brief = run_json(capsys, "task", task["id"])
        answers.append((task["id"], json.dumps({
            "input_hash": brief["input_hash"],
            "files": [{"path": item["path"], "summary": "A generated file."} for item in brief["files"]],
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
    codes = [queue.get(timeout=90) for _ in procs]
    for proc in procs:
        proc.join(30)
    assert codes == [0, 0, 0, 0], codes

    [structure] = run_json(capsys, "tasks", "--kind", "confirm-structure")
    brief = run_json(capsys, "task", structure["id"])
    code, _, err = run(capsys, "submit", structure["id"], str(_write(tmp_path, {
        "input_hash": brief["input_hash"], "deployables": [], "packages": [],
    })))
    assert code == 0, err
    [task] = run_json(capsys, "tasks", "--kind", "define-concepts")
    spec = run_json(capsys, "task", task["id"], "--parts")
    assert spec["split"] is True
    assert spec["brief_bytes"] > spec["budget"]
    assert len(spec["parts"]) >= 7
    assert all(part["bytes"] <= spec["budget"] for part in spec["parts"])
    assert any(part["name"] == "package pkg-a" for part in spec["parts"])
    assert any(part["name"].startswith("cross-area") for part in spec["parts"])
    code, sample, err = run(capsys, "task", task["id"], "--part", "1")
    assert code == 0, err
    assert len(sample.encode()) == spec["parts"][0]["bytes"]
    assert len(sample.encode()) <= spec["budget"]

    owned = defaultdict(list)
    for part in spec["parts"]:
        if not part["name"].startswith("package "):
            continue
        body = run_json(capsys, "task", task["id"], "--part", str(part["index"]))
        for item in body["files"]:
            owned[item["path"].split("/", 1)[0]].append(item["path"])
    concepts = [
        {"id": pkg, "name": pkg, "summary": f"The {pkg} files.", "role": "core", "files": sorted(paths)}
        for pkg, paths in sorted(owned.items())
    ]
    assert sum(len(item["files"]) for item in concepts) == 1500
    answer = {
        "input_hash": run_json(capsys, "task", task["id"], "--part", "1")["input_hash"],
        "summary": "Six generated packages.",
        "concepts": concepts,
        "externals": [],
        "relationships": [{"from": "pkg-a", "to": "pkg-b", "label": "uses", "basis": "imports"}],
    }
    code, out, err = run(capsys, "task", task["id"], "--check", str(_write(tmp_path, answer)))
    assert code == 0 and out.strip() == "ok", err
    assert not (root / ".cbi" / "concepts.json").exists()


def _write(tmp_path, value):
    path = tmp_path / "answer.json"
    path.write_text(json.dumps(value))
    return path

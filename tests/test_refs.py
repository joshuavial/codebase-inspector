"""Scan a branch, tag or commit from git objects, and list worktrees."""

import hashlib
import json
import os
import shutil
import sqlite3
import stat
import subprocess
from pathlib import Path

from cbi import files, store
from cbi.cli import main

WS = "github.com/acme/app"
LIB = "github.com/acme/lib"


def git(cwd, *args):
    return subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@example.com", "-c", "commit.gpgsign=false",
         "-c", "protocol.file.allow=always", *args],
        cwd=cwd, check=True, capture_output=True, text=True,
    ).stdout


def run(capsys, *argv):
    capsys.readouterr()
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def scan_ref(capsys, ref):
    code, out, err = run(capsys, "scan", "--ref", ref)
    assert code == 0, err
    return out.splitlines()[0], out


def nodes(db):
    conn = sqlite3.connect(db)
    rows = conn.execute("SELECT id, kind, path, content_hash, attrs FROM nodes").fetchall()
    conn.close()
    return {row[0]: row for row in rows}


def answer(brief):
    if brief["kind"] == "summarise-files":
        return {"input_hash": brief["input_hash"],
                "files": [{"path": f["path"], "summary": f"About {f['path']}."} for f in brief["files"]]}
    if brief["kind"] == "confirm-structure":
        return {"input_hash": brief["input_hash"], "deployables": [], "packages": []}
    if brief["kind"] == "define-concepts":
        return {"input_hash": brief["input_hash"], "summary": "A demo app.",
                "concepts": [{"id": "app", "name": "App", "summary": "The app.", "role": "app",
                              "files": [f["path"] for f in brief["files"]]}],
                "externals": [], "relationships": []}
    return {"input_hash": brief["input_hash"], "summary": f"About {brief['node']['path'] or 'the repo'}."}


def finish(capsys, tmp_path, ref, limit=40):
    done = []
    for _ in range(limit):
        code, out, err = run(capsys, "tasks", "--ref", ref, "--json")
        assert code == 0, err
        found = json.loads(out)
        if not found:
            return done
        for task in found:
            code, out, err = run(capsys, "task", task["id"], "--ref", ref, "--json")
            assert code == 0, err
            path = tmp_path / "answer.json"
            path.write_text(json.dumps(answer(json.loads(out))))
            code, out, err = run(capsys, "submit", task["id"], str(path), "--ref", ref)
            assert code == 0, err
            done.append(task["id"])
    raise AssertionError("tasks still open")


def two_branches(make_repo, monkeypatch):
    """App on main and other, with one real submodule and one gitlink whose objects are missing."""
    lib = make_repo({"lib.py": "def lib():\n    return 1\n"}, name="lib")
    files = {
        "README.md": "# app\n",
        "src/same.py": "def same():\n    return 1\n",
        "src/only_main.py": "def only_main():\n    return 1\n",
        ".env": "SECRET=1\n",
        ".env.example": "SECRET=\n",
    }
    root = make_repo(files, name="app")
    git(root, "remote", "add", "origin", "https://github.com/acme/app.git")
    git(root, "submodule", "add", "-q", str(lib), "vendor/lib")
    git(root, "config", "-f", ".gitmodules", "submodule.vendor/lib.url", "https://github.com/acme/lib.git")
    git(root / "vendor" / "lib", "remote", "set-url", "origin", "https://github.com/acme/lib.git")
    ghost = "ab" * 20
    git(root, "add", ".gitmodules")
    git(root, "update-index", "--add", "--cacheinfo", f"160000,{ghost},vendor/ghost")
    git(root, "commit", "-q", "-m", "submodules")
    git(root, "checkout", "-q", "-b", "other")
    git(root, "rm", "-q", "src/only_main.py")
    (root / "src" / "only_other.py").write_text("def only_other():\n    return 2\n")
    git(root, "add", "src/only_other.py")
    git(root, "commit", "-q", "-m", "other")
    git(root, "checkout", "-q", "main")
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    return root, ghost


def test_ref_scan_maps_both_branches_without_a_checkout(make_repo, monkeypatch, capsys):
    root, ghost = two_branches(make_repo, monkeypatch)
    main_sha, out = scan_ref(capsys, "main")
    assert out.splitlines()[0] == main_sha and len(main_sha) == 40
    assert "scanned" in out and "reused" not in out
    other_sha, _ = scan_ref(capsys, "other")
    assert other_sha != main_sha

    main_db = root / ".cbi" / "refs" / main_sha / "model.db"
    other_db = root / ".cbi" / "refs" / other_sha / "model.db"
    assert main_db.exists() and not (root / ".cbi" / "model.db").exists()
    assert not (root / ".cbi" / "structure.json").exists()
    assert not (root / ".cbi" / "viewer").exists()

    main_nodes, other_nodes = nodes(main_db), nodes(other_db)
    shared = set(main_nodes) & set(other_nodes)
    for node_id in (f"{WS}:src/same.py", f"{WS}:src/same.py#same", f"{LIB}:lib.py", f"{LIB}:lib.py#lib",
                    f"{WS}:README.md", f"{WS}:.env.example"):
        assert node_id in shared
        assert main_nodes[node_id][3] == other_nodes[node_id][3]
    assert f"{WS}:src/only_main.py" in main_nodes and f"{WS}:src/only_main.py" not in other_nodes
    assert f"{WS}:src/only_other.py" in other_nodes and f"{WS}:src/only_other.py" not in main_nodes
    assert f"{WS}:.env" not in main_nodes and f"{WS}:.env" not in other_nodes

    lib_attrs = json.loads(main_nodes[LIB][4])
    assert lib_attrs["initialised"] and not lib_attrs["drift"]
    assert lib_attrs["pinned_commit"] == lib_attrs["checked_out_commit"] == git(root, "rev-parse", f"{main_sha}:vendor/lib").strip()
    ghost_attrs = json.loads(main_nodes["local:ghost"][4])
    assert ghost_attrs["pinned_commit"] == ghost and not ghost_attrs["initialised"]
    assert ghost_attrs["checked_out_commit"] is None and not ghost_attrs["drift"]

    same = main_nodes[f"{WS}:src/same.py"][3]
    assert same == git(root, "rev-parse", f"{main_sha}:src/same.py").strip()
    assert same == files.blob_id(b"def same():\n    return 1\n")

    db_mtime = main_db.stat().st_mtime_ns
    db_bytes = hashlib.sha256(main_db.read_bytes()).hexdigest()
    again, out = scan_ref(capsys, main_sha[:12])
    assert again == main_sha and "reused" in out and "scanned" not in out
    git(root, "tag", "v1", main_sha)
    tagged, out = scan_ref(capsys, "v1")
    assert tagged == main_sha and "reused" in out and "scanned" not in out
    assert main_db.stat().st_mtime_ns == db_mtime
    assert hashlib.sha256(main_db.read_bytes()).hexdigest() == db_bytes

    code, _, err = run(capsys, "show", "src/same.py")
    assert code == 1 and "no model" in err
    (root / "src" / "same.py").write_text("def same():\n    return 9\n")
    dirty, out = scan_ref(capsys, "HEAD")
    assert dirty == main_sha and "reused" in out
    assert main_db.stat().st_mtime_ns == db_mtime
    code, out, err = run(capsys, "scan")
    assert code == 0, err
    work = nodes(root / ".cbi" / "model.db")
    dirty_hash = work[f"{WS}:src/same.py"][3]
    assert dirty_hash == git(root, "hash-object", "src/same.py").strip()
    assert dirty_hash != same
    assert work[f"{WS}:README.md"][3] == git(root, "rev-parse", "HEAD:README.md").strip()

    code, out, err = run(capsys, "show", "src/same.py")
    assert code == 0 and "same.py" in out
    for argv in (
        ["show", "src/same.py", "--ref", "other"],
        ["search", "same", "--ref", "other"],
        ["tests-for", "src/same.py", "--ref", "other"],
        ["status", "--ref", "other"],
        ["tasks", "--ref", "other"],
        ["build", "--ref", "other"],
    ):
        code, out, err = run(capsys, *argv)
        assert code == 0, (argv, err, out)
    assert (root / ".cbi" / "refs" / other_sha / "viewer" / "index.html").exists()
    assert not (root / ".cbi" / "viewer").exists()
    code, _, err = run(capsys, "show", "src/only_other.py")
    assert code == 1 and "only_other.py" in err
    code, _, err = run(capsys, "scan", "--ref", "no-such-ref")
    assert code == 1 and err.strip() == "unknown ref no-such-ref"
    code, _, err = run(capsys, "show", "src/same.py", "--ref", "no-such-ref")
    assert code == 1 and "unknown ref no-such-ref" in err

    ignore = root / ".cbi" / "ignore"
    ignore.write_text(ignore.read_text() + "src/only_main.py\n")
    rescanned, out = scan_ref(capsys, "main")
    assert rescanned == main_sha and "scanned" in out and "reused" not in out
    assert f"{WS}:src/only_main.py" not in nodes(main_db)
    monkeypatch.setattr(files, "PARSER_VERSION", files.PARSER_VERSION + 1)
    _, out = scan_ref(capsys, "main")
    assert "scanned" in out and "reused" not in out
    conn = sqlite3.connect(main_db)
    conn.execute("PRAGMA user_version = 1")
    conn.commit()
    conn.close()
    _, out = scan_ref(capsys, "main")
    assert "scanned" in out and "reused" not in out
    conn = sqlite3.connect(main_db)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == store.SCHEMA_VERSION
    finally:
        conn.close()


def _git_shim(directory):
    """A git on PATH that refuses every subcommand except read-only ones."""
    real = shutil.which("git")
    log = directory / "git.log"
    script = directory / "git"
    script.write_text(f"""#!/usr/bin/env python3
import os, sys
args = sys.argv[1:]
i = 0
while i < len(args):
    a = args[i]
    if a == "--":
        i += 1
        break
    if a in ("-C", "-c", "--git-dir", "--work-tree", "--namespace"):
        i += 2
        continue
    if a.startswith("-"):
        i += 1
        continue
    break
cmd = args[i] if i < len(args) else ""
rest = args[i + 1:]
ok = cmd in ("rev-parse", "ls-tree", "cat-file")
if cmd == "config":
    ok = any(a == "--get" or a.startswith("--get=") or a == "--get-regexp" for a in rest)
    ok = ok and not any(a in ("--add", "--unset", "--unset-all", "--replace-all") for a in rest)
line = "OK " if ok else "DENIED "
with open({str(log)!r}, "a") as fh:
    fh.write(line + " ".join(sys.argv) + "\\n")
if not ok:
    sys.exit(99)
os.execv({real!r}, [{real!r}, *sys.argv[1:]])
""")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return log


def _snapshot(root):
    def capture(*args):
        return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True).stdout
    return capture("status", "--porcelain"), capture("worktree", "list", "--porcelain"), capture("for-each-ref")


def test_ref_scan_does_not_touch_the_worktree_or_refs(make_repo, monkeypatch, capsys, tmp_path):
    root, _ghost = two_branches(make_repo, monkeypatch)
    (root / "src" / "same.py").write_text("def same():\n    return 9\n")
    before = _snapshot(root)
    assert b"same.py" in before[0]
    shim = tmp_path / "bin"
    shim.mkdir()
    log = _git_shim(shim)
    old = os.environ["PATH"]
    os.environ["PATH"] = str(shim) + os.pathsep + old
    try:
        code, out, err = run(capsys, "scan", "--ref", "main")
    finally:
        os.environ["PATH"] = old
    assert code == 0, err
    assert _snapshot(root) == before
    recorded = log.read_text()
    assert "DENIED" not in recorded
    assert recorded.count("cat-file --batch") == 2  # one process per object database, not per file
    assert "^{commit}" in recorded


def test_ref_tasks_reuse_the_answer_cache(make_repo, monkeypatch, capsys, tmp_path):
    root, _ghost = two_branches(make_repo, monkeypatch)
    main_sha, out = scan_ref(capsys, "main")
    assert "judgement tasks open" in out and not out.splitlines()[-1].startswith("0 ")
    assert finish(capsys, tmp_path, "main")
    code, out, err = run(capsys, "tasks", "--ref", "main")
    assert code == 0 and out.strip() == "no open tasks"

    db = root / ".cbi" / "refs" / main_sha
    shutil.rmtree(db)
    sha, out = scan_ref(capsys, main_sha)
    assert sha == main_sha and "scanned" in out
    assert out.splitlines()[-1] == "0 judgement tasks open, 0 blocked"
    assert not (root / ".cbi" / "structure.json").exists()
    assert (db / "structure.json").exists()

    other_sha, out = scan_ref(capsys, "other")
    assert "judgement tasks open" in out and not out.splitlines()[-1].startswith("0 ")
    conn = sqlite3.connect(root / ".cbi" / "refs" / other_sha / "model.db")
    same_id, summary = conn.execute(
        "SELECT id, summary FROM nodes WHERE kind = 'file' AND path = 'src/same.py'").fetchone()
    assert summary == "About src/same.py."
    other_id, other_summary = conn.execute(
        "SELECT id, summary FROM nodes WHERE kind = 'file' AND path = 'src/only_other.py'").fetchone()
    assert other_summary is None
    open_inputs = [json.loads(raw) for raw, in conn.execute(
        "SELECT inputs FROM tasks WHERE kind = 'summarise-files' AND state = 'open'")]
    assert open_inputs and all(same_id not in batch for batch in open_inputs)
    assert any(other_id in batch for batch in open_inputs)


def test_worktrees_json(make_repo, tmp_path, monkeypatch, capsys):
    root = make_repo({"src/a.py": "def a():\n    return 1\n"}, name="app")
    git(root, "remote", "add", "origin", "https://github.com/acme/app.git")
    lane = tmp_path / "lane-wt"
    detached = tmp_path / "detached-wt"
    git(root, "worktree", "add", "-q", "-b", "lane", str(lane))
    git(root, "worktree", "add", "--detach", "-q", str(detached))
    git(root, "config", "--local", "cbi.worktree.lane-wt.mode", "window")
    monkeypatch.chdir(root)

    code, out, err = run(capsys, "worktrees", "--json")
    assert code == 0, err
    early = json.loads(out)
    assert early["worktrees"][0]["current"] and not early["worktrees"][0]["has_model"]
    assert all(not b["has_ref_model"] for b in early["branches"])

    assert main(["init"]) == 0 and main(["scan"]) == 0
    code, out, err = run(capsys, "worktrees", "--json")
    data = json.loads(out)
    here = next(w for w in data["worktrees"] if w["current"])
    assert Path(here["path"]).resolve() == root.resolve()
    assert here["branch"] == "main" and here["lane"] == "main" and here["has_model"] and not here["model_complete"]
    lane_row = next(w for w in data["worktrees"] if Path(w["path"]).resolve() == lane.resolve())
    assert lane_row["branch"] == "lane" and lane_row["lane"] == "lane-wt" and not lane_row["has_model"]
    det = next(w for w in data["worktrees"] if Path(w["path"]).resolve() == detached.resolve())
    assert det["branch"] is None and det["lane"] is None and not det["current"]
    assert [w["current"] for w in data["worktrees"]].count(True) == 1
    assert data["branches"][0]["name"] == "main" and data["branches"][0]["current"]

    conn = sqlite3.connect(root / ".cbi" / "model.db")
    conn.execute("UPDATE tasks SET state = 'done'")
    conn.commit()
    conn.close()
    data = json.loads(run(capsys, "worktrees", "--json")[1])
    assert next(w for w in data["worktrees"] if w["current"])["model_complete"]

    main_sha, _ = scan_ref(capsys, "main")
    data = json.loads(run(capsys, "worktrees", "--json")[1])
    by_name = {b["name"]: b for b in data["branches"]}
    assert by_name["main"]["has_ref_model"] and by_name["lane"]["has_ref_model"]  # same commit
    assert by_name["main"]["head"] == main_sha and by_name["lane"]["lane"] == "lane-wt"
    (lane / "src" / "b.py").write_text("def b():\n    return 2\n")
    git(lane, "add", "src/b.py")
    git(lane, "commit", "-q", "-m", "lane")
    data = json.loads(run(capsys, "worktrees", "--json")[1])
    by_name = {b["name"]: b for b in data["branches"]}
    assert by_name["main"]["has_ref_model"] and not by_name["lane"]["has_ref_model"]
    assert by_name["lane"]["head"] != main_sha

    monkeypatch.chdir(lane)
    data = json.loads(run(capsys, "worktrees", "--json", "--out", str(root / ".cbi"))[1])
    current = next(w for w in data["worktrees"] if w["current"])
    assert Path(current["path"]).resolve() == lane.resolve() and current["lane"] == "lane-wt"
    assert next(b for b in data["branches"] if b["current"])["name"] == "lane"

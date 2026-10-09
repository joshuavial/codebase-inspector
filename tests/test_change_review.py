"""cbi review: pull requests, Mermaid, provisional concepts, the narrative, posting."""

import json
import os
import sqlite3
import subprocess
from pathlib import Path

from conftest import write_standin

import pytest

from cbi import diff, render, review, store
from cbi.cli import main

MERMAID = """\
flowchart LR
  classDef added fill:#d8f3dc,stroke:#1b7f3a
  classDef removed fill:#fde2e1,stroke:#b42318
  classDef changed fill:#fff3c4,stroke:#b54708
  born["Born"]:::added
  gone["Going"]:::removed
  app["App"]:::changed
  disk["Disk"]
  app -->|"calls"| born
  app -->|"http"| disk
  app -.->|"reads (removed)"| disk
"""

CONCEPTS = {
    "summary": "demo",
    "concepts": [
        {"id": "app", "name": "App", "summary": "The caller.", "role": "app", "files": ["app/b.ts"]},
        {"id": "core", "name": "Core", "summary": "The function.", "role": "core", "files": ["core/a.ts"]},
    ],
    "externals": [],
    "relationships": [{"from": "app", "to": "core", "label": "calls", "basis": "imports"}],
}

BASE_FILES = {
    "core/a.ts": "export function a() { return 1 }\n",
    "app/b.ts": 'import { a } from "../core/a";\nexport function b() { return a(); }\n',
    "legacy/old.ts": "export function old() { return 3 }\n",
}


@pytest.fixture(autouse=True)
def _skip_review_images(monkeypatch):
    """These reviews do not launch Chrome. Tests of the image files replace this stub."""
    monkeypatch.setattr(
        "cbi.render.render_images",
        lambda model, change_list, out_dir: {"skipped": render.SKIPPED},
    )


def run(capsys, *argv):
    capsys.readouterr()
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def git(cwd, *args):
    return subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@example.com", "-c", "commit.gpgsign=false", *args],
        cwd=cwd, check=True, capture_output=True, text=True,
    ).stdout.strip()


def commit_files(root, files, message="head"):
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", message)


def sha(root, ref="HEAD"):
    return git(root, "rev-parse", ref)


def seed_concepts(root, commit, document):
    home = root / ".cbi" / "refs" / commit
    home.mkdir(parents=True, exist_ok=True)
    (home / "concepts.json").write_text(json.dumps(document, indent=2) + "\n")


def snapshot(root):
    def capture(*args):
        return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True).stdout
    return {
        "status": capture("status", "--porcelain=v1", "-z"),
        "stash": capture("stash", "list"),
        "refs": capture("for-each-ref"),
        "head": capture("rev-parse", "HEAD"),
    }


def mermaid_block(text):
    start = text.index("```mermaid\n") + len("```mermaid\n")
    end = text.index("\n```", start)
    return text[start:end] + "\n"


def fake_gh(tmp_path, monkeypatch, pr):
    state = tmp_path / "gh-state.json"
    log = tmp_path / "gh.log"
    state.write_text(json.dumps({"repo": "acme/widgets", "pr": pr, "comments": [], "next_id": 1}))
    script = write_standin(tmp_path / "bin", "gh", """#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
state_path = Path(os.environ["CBI_FAKE_GH"])
log_path = Path(os.environ["CBI_FAKE_GH_LOG"])
with log_path.open("a") as fh:
    fh.write(json.dumps(sys.argv[1:]) + "\\n")
args = sys.argv[1:]
state = json.loads(state_path.read_text())

def save():
    state_path.write_text(json.dumps(state))

if args[:2] == ["pr", "view"]:
    fields = args[args.index("--json") + 1].split(",")
    print(json.dumps({key: state["pr"][key] for key in fields}))
    raise SystemExit(0)
if args[:2] == ["repo", "view"]:
    print(json.dumps({"nameWithOwner": state["repo"]}))
    raise SystemExit(0)
if args[:2] == ["pr", "comment"]:
    body = Path(args[args.index("--body-file") + 1]).read_text()
    cid = state.get("next_id", 1)
    state.setdefault("comments", []).append({"id": cid, "body": body})
    state["next_id"] = cid + 1
    save()
    print("https://example.test/pull/1#issuecomment-%s" % cid)
    raise SystemExit(0)
if args[:1] == ["api"] and "--paginate" in args:
    print(json.dumps(state.get("comments", [])))
    raise SystemExit(0)
if args[:1] == ["api"] and "--method" in args:
    raw = next(arg for arg in args if arg.startswith("body=@"))
    body = Path(raw.split("=", 1)[1][1:]).read_text()
    target = next(arg for arg in args if "issues/comments/" in arg)
    cid = int(target.rstrip("/").split("/")[-1])
    for comment in state["comments"]:
        if comment["id"] == cid:
            comment["body"] = body
            save()
            print(json.dumps({"id": cid}))
            raise SystemExit(0)
    sys.stderr.write("no comment %s\\n" % cid)
    raise SystemExit(1)
sys.stderr.write("unexpected gh %s\\n" % " ".join(args))
raise SystemExit(2)
""")
    monkeypatch.setenv("PATH", str(script.parent) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("CBI_FAKE_GH", str(state))
    monkeypatch.setenv("CBI_FAKE_GH_LOG", str(log))
    return state, log


def gh_calls(log):
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text().splitlines() if line.strip()]


def test_mermaid_matches_known_good_and_rejects_a_broken_diagram():
    diagram = {
        "nodes": [
            {"id": "disk", "label": "Disk", "status": "neighbour"},
            {"id": "app", "label": "App", "status": "changed"},
            {"id": "gone", "label": "Going", "status": "removed"},
            {"id": "born", "label": "Born", "status": "added"},
        ],
        "edges": [
            {"src": "app", "dst": "disk", "label": "reads (removed)", "removed": True},
            {"src": "app", "dst": "born", "label": "calls", "removed": False},
            {"src": "app", "dst": "disk", "label": "http", "removed": False},
        ],
    }
    text = review.render_mermaid(diagram)
    assert text == MERMAID
    assert review.valid_mermaid(text)
    assert not review.valid_mermaid(text.replace("flowchart LR", "flowchart TD"))
    broken = text.replace('disk["Disk"]\n', "")
    assert not review.valid_mermaid(broken)


def test_diagram_draws_changed_nodes_and_direct_neighbours_only(tmp_path):
    def fill(path, edges):
        conn = store.open_db(path)
        with conn:
            for nid, name, kind in (
                ("a", "Apple", "concept"), ("b", "Bee", "concept"), ("c", "Cee", "concept"),
                ("d", "Dee", "concept"), ("e", "Eel", "concept"), ("x", "Ex", "external"),
            ):
                conn.execute(
                    "INSERT INTO nodes (id, kind, display_kind, name) VALUES (?, ?, ?, ?)",
                    (nid, kind, kind, name),
                )
            for src, dst, label, via in edges:
                attrs = {"label": label}
                if via:
                    attrs["via"] = via
                    attrs["integration"] = True
                conn.execute(
                    "INSERT INTO edges (src, dst, kind, source, attrs) VALUES (?, ?, 'relates', 'agent', ?)",
                    (src, dst, json.dumps(attrs)),
                )
        conn.close()

    base, head = tmp_path / "base.db", tmp_path / "head.db"
    fill(base, [("a", "b", "uses", None), ("b", "e", "old", None), ("d", "c", "side", None)])
    fill(head, [("a", "b", "uses", None), ("b", "c", "starts", None), ("d", "c", "side", None),
                ("b", "x", "calls", "http")])
    result = {"grouping": "concept", "groups": [{
        "id": "b", "name": "Bee", "kind": "concept",
        "changes": [{"kind": "symbol-added", "summary": "bee", "before": None, "after": None, "code": []}],
    }]}
    base_conn, head_conn = diff.open_model(base), diff.open_model(head)
    try:
        diagram = review.build_diagram(result, base_conn, head_conn)
    finally:
        base_conn.close()
        head_conn.close()
    assert {node["id"] for node in diagram["nodes"]} == {"a", "b", "c", "e", "x"}
    assert {node["id"] for node in diagram["nodes"] if node["status"] == "changed"} == {"b"}
    assert {item["id"] for item in diagram["omitted"]} == {"d"}
    labels = {(edge["src"], edge["dst"], edge["label"], edge["removed"]) for edge in diagram["edges"]}
    assert ("b", "x", "http", False) in labels
    assert ("b", "e", "old (removed)", True) in labels
    assert ("d", "c", "side", False) not in labels
    assert review.valid_mermaid(review.render_mermaid(diagram))
    assert "Dee" in review._omitted_text(diagram)


def test_review_of_a_range_writes_the_folder_and_does_not_call_gh(make_repo, monkeypatch, capsys, tmp_path):
    root = make_repo(BASE_FILES)
    monkeypatch.chdir(root)
    state, log = fake_gh(tmp_path, monkeypatch, {"number": 1, "url": "https://example.test/1",
                                                  "baseRefName": "main", "baseRefOid": "0" * 40,
                                                  "headRefOid": "1" * 40})
    assert main(["init"]) == 0
    base = sha(root)
    commit_files(root, {"app/b.ts": BASE_FILES["app/b.ts"] + "export function more() { return b(); }\n"})
    head = sha(root)
    (root / "legacy" / "old.ts").write_text("export function old() { return 9 }\n")
    before = snapshot(root)
    code, out, err = run(capsys, "review", f"{base}..{head}", "--out-dir", str(tmp_path / "out"))
    assert code == 0, err
    assert gh_calls(log) == []
    text = (tmp_path / "out" / "review.md").read_text()
    assert text.startswith(f"cbi://open?repo={root.resolve()}&compare={base}..{head}\n")
    assert f"# Review repo {base[:12]}..{head[:12]}" in text
    assert review.MARKER in text
    assert "## Narrative" not in text
    assert render.SKIPPED in text and render.SKIPPED in out
    assert not (tmp_path / "out" / "before.png").exists()
    block = mermaid_block(text)
    assert review.valid_mermaid(block)
    assert "flowchart LR" in block
    assert "summarise-change sc-" in out
    assert snapshot(root) == before


def _two_commits(make_repo, monkeypatch):
    root = make_repo(BASE_FILES)
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    base = sha(root)
    commit_files(root, {"app/b.ts": BASE_FILES["app/b.ts"] + "export function more() { return b(); }\n"})
    return root, base, sha(root)


def test_review_heading_uses_the_remote_repo_name(make_repo, monkeypatch, capsys, tmp_path):
    root = make_repo(BASE_FILES, name="review-images")
    git(root, "remote", "add", "origin", "git@github.com:Acme/SampleDesktop.git")
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    base = sha(root)
    commit_files(root, {"app/b.ts": BASE_FILES["app/b.ts"] + "export function more() { return b(); }\n"})
    head = sha(root)
    code, out, err = run(capsys, "review", f"{base}..{head}", "--out-dir", str(tmp_path / "out"))
    assert code == 0, err
    text = (tmp_path / "out" / "review.md").read_text()
    heading = next(line for line in text.splitlines() if line.startswith("# Review "))
    assert heading == f"# Review SampleDesktop {base[:12]}..{head[:12]}"
    assert text.startswith(f"cbi://open?repo={root.resolve()}&compare={base}..{head}\n")


def test_review_writes_the_image_files(make_repo, monkeypatch, capsys, tmp_path):
    root, base, head = _two_commits(make_repo, monkeypatch)
    seen = {}

    def fake(model, change_list, out_dir):
        seen["model"] = {key: Path(value) for key, value in model.items()}
        seen["changes"] = change_list
        seen["out"] = Path(out_dir)
        written = {}
        for name in ("before.png", "before.svg", "after.png", "after.svg"):
            path = Path(out_dir) / name
            path.write_bytes(b"img")
            written[name] = path
        return written

    monkeypatch.setattr("cbi.render.render_images", fake)
    folder = tmp_path / "out"
    code, out, err = run(capsys, "review", f"{base}..{head}", "--out-dir", str(folder))
    assert code == 0, err
    assert seen["model"]["base"] == root / ".cbi" / "refs" / base
    assert seen["model"]["head"] == root / ".cbi" / "refs" / head
    assert seen["out"] == folder
    assert isinstance(seen["changes"]["groups"], list)
    text = (folder / "review.md").read_text()
    assert "- before.png" in text and "- after.svg" in text
    assert "Attach them to the pull request comment by hand." in text
    assert (folder / "before.png").read_bytes() == b"img"
    assert (folder / "after.svg").is_file()
    assert "images: before.png, before.svg, after.png, after.svg" in out


def test_review_keeps_the_folder_when_images_fail(make_repo, monkeypatch, capsys, tmp_path):
    _root, base, head = _two_commits(make_repo, monkeypatch)

    def boom(model, change_list, out_dir):
        raise render.RenderError("Chrome failed: boom")

    monkeypatch.setattr("cbi.render.render_images", boom)
    folder = tmp_path / "out"
    code, out, err = run(capsys, "review", f"{base}..{head}", "--out-dir", str(folder))
    assert code == 0, err
    text = (folder / "review.md").read_text()
    assert "Images were not written: Chrome failed: boom" in text
    assert "Chrome failed: boom" in out
    assert err == ""
    assert not (folder / "before.png").exists()


def test_provisional_owner_and_the_define_concepts_task(make_repo, monkeypatch, capsys, tmp_path):
    root = make_repo(BASE_FILES)
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    base = sha(root)
    commit_files(root, {
        "app/c.ts": 'import { b } from "./b";\nexport function c() { return b(); }\n',
        "core/extra.ts": "export function extra() { return 2 }\n",
        "tie.ts": 'import { a } from "./core/a";\nimport { b } from "./app/b";\n'
                  "export function tie() { return a() + b(); }\n",
        "legacy/old.ts": "export function old() { return 4 }\n",
    })
    head = sha(root)
    seed_concepts(root, base, CONCEPTS)
    seed_concepts(root, head, CONCEPTS)
    code, out, err = run(capsys, "review", f"{base}..{head}")
    assert code == 0, err
    folder = root / ".cbi" / "reviews" / f"{base}..{head}"
    text = (folder / "review.md").read_text()
    block = mermaid_block(text)
    assert review.valid_mermaid(block)
    assert 'app["App (provisional)"]:::changed' in block
    assert 'core["Core (provisional)"]:::changed' in block
    assert 'app -->|"calls"| core' in block
    assert "provisional" in text
    assert "app/c.ts" in text and "core/extra.ts" in text and "tie.ts" in text
    assert "legacy/old.ts" not in text.split("## Provisional")[-1] if "## Provisional" in text else "legacy/old.ts" not in [
        line for line in text.splitlines() if "provisional" in line and "task" not in line
    ]
    code, diff_out, diff_err = run(capsys, "diff", base, head)
    assert code == 0, diff_err
    assert "provisional" in diff_out
    for path, owner, how in (("app/c.ts", "App", "imports"), ("core/extra.ts", "Core", "folder"), ("tie.ts", "App", "imports")):
        assert f"{path}  {owner}  {how}" in diff_out
    assert "legacy/old.ts" not in diff_out.split("provisional", 1)[-1]
    code, listed, list_err = run(capsys, "tasks", "--ref", head, "--kind", "define-concepts", "--json")
    assert code == 0, list_err
    tasks = json.loads(listed)
    assert [task["id"] for task in tasks] == [task["id"] for task in tasks if task["id"].startswith("dcp-")]
    assert len(tasks) == 1
    code, brief_out, brief_err = run(capsys, "task", tasks[0]["id"], "--ref", head, "--json")
    assert code == 0, brief_err
    brief = json.loads(brief_out)
    assert [item["path"] for item in brief["files"]] == ["app/c.ts", "core/extra.ts", "tie.ts"]
    db = root / ".cbi" / "refs" / head / "model.db"
    conn = sqlite3.connect(db)
    try:
        owned = [row[0] for row in conn.execute("SELECT dst FROM edges WHERE kind = 'owns'")]
    finally:
        conn.close()
    assert not any("c.ts" in item or item.endswith("tie.ts") or "extra.ts" in item for item in owned)


def test_pr_resolution_reads_gh_and_does_not_post(make_repo, monkeypatch, capsys, tmp_path):
    root = make_repo({"src/a.ts": "export function a() { return 1 }\n"})
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    base = sha(root)
    commit_files(root, {"src/a.ts": "export function a() { return 2 }\n"})
    head = sha(root)
    _state, log = fake_gh(tmp_path, monkeypatch, {
        "number": 12, "url": "https://example.test/pull/12", "baseRefName": "main",
        "baseRefOid": base, "headRefOid": head,
    })
    code, out, err = run(capsys, "review", "12", "--out-dir", str(tmp_path / "pr"))
    assert code == 0, err
    calls = gh_calls(log)
    assert calls == [["pr", "view", "12", "--json", "baseRefName,headRefOid,baseRefOid,number,url"]]
    text = (tmp_path / "pr" / "review.md").read_text()
    assert f"compare={base}..{head}" in text.splitlines()[0]
    assert "https://example.test/pull/12" in text
    assert review.MARKER in text
    assert "posted:" not in out


def test_narrative_is_cached_by_the_commit_pair(make_repo, monkeypatch, capsys, tmp_path):
    root = make_repo({"src/a.ts": "export function a() { return 1 }\n"})
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    base = sha(root)
    commit_files(root, {"src/a.ts": "export function a() { return 2 }\n"}, "b")
    middle = sha(root)
    commit_files(root, {"src/a.ts": "export function a() { return 3 }\n"}, "c")
    tip = sha(root)
    code, out, err = run(capsys, "review", f"{base}..{middle}", "--out-dir", str(tmp_path / "one"))
    assert code == 0, err
    assert "## Narrative" not in (tmp_path / "one" / "review.md").read_text()
    task_id = next(line.split()[1] for line in out.splitlines() if line.startswith("summarise-change"))
    code, brief_out, brief_err = run(capsys, "task", task_id, "--ref", middle, "--json")
    assert code == 0, brief_err
    brief = json.loads(brief_out)
    assert brief["input_hash"] == review.change_hash(base, middle)
    assert brief["changes"]["grouping"]
    answer = tmp_path / "answer.json"
    answer.write_text(json.dumps({"input_hash": brief["input_hash"], "narrative": "The billing concept grew a new door."}))
    code, _submitted, submit_err = run(capsys, "submit", task_id, str(answer), "--ref", middle)
    assert code == 0, submit_err
    code, _again, err = run(capsys, "review", f"{base}..{middle}", "--out-dir", str(tmp_path / "two"))
    assert code == 0, err
    second = (tmp_path / "two" / "review.md").read_text()
    assert "## Narrative" in second
    assert "The billing concept grew a new door." in second
    assert f"`{task_id}` (done)" in second
    code, _other, err = run(capsys, "review", f"{base}..{tip}", "--out-dir", str(tmp_path / "three"))
    assert code == 0, err
    third = (tmp_path / "three" / "review.md").read_text()
    assert "The billing concept grew a new door." not in third
    assert "## Narrative" not in third
    assert review.change_hash(base, middle) != review.change_hash(base, tip)


def test_post_creates_a_comment_then_updates_it(make_repo, monkeypatch, capsys, tmp_path):
    root = make_repo({"src/a.ts": "export function a() { return 1 }\n"})
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    base = sha(root)
    commit_files(root, {"src/a.ts": "export function a() { return 2 }\n"})
    head = sha(root)
    state, log = fake_gh(tmp_path, monkeypatch, {
        "number": 7, "url": "https://example.test/pull/7", "baseRefName": "main",
        "baseRefOid": base, "headRefOid": head,
    })
    code, out, err = run(capsys, "review", "7", "--post", "--out-dir", str(tmp_path / "posted"))
    assert code == 0, err
    assert "posted: created" in out
    saved = json.loads(state.read_text())
    assert len(saved["comments"]) == 1
    assert review.MARKER in saved["comments"][0]["body"]
    assert saved["comments"][0]["body"] == (tmp_path / "posted" / "review.md").read_text()
    saved["comments"][0]["body"] = review.MARKER + "\nSTALE-BODY\n"
    state.write_text(json.dumps(saved))
    code, out, err = run(capsys, "review", "7", "--post", "--out-dir", str(tmp_path / "posted"))
    assert code == 0, err
    assert "posted: updated" in out
    saved = json.loads(state.read_text())
    assert len(saved["comments"]) == 1
    body = saved["comments"][0]["body"]
    assert "STALE-BODY" not in body
    assert body == (tmp_path / "posted" / "review.md").read_text()
    assert review.MARKER in body
    calls = gh_calls(log)
    comments = [call for call in calls if call[:2] == ["pr", "comment"]]
    patches = [call for call in calls if "--method" in call and "PATCH" in call]
    assert len(comments) == 1
    assert len(patches) == 1
    assert patches[0][patches[0].index("--method") + 1] == "PATCH"
    code, out, err = run(capsys, "review", f"{base}..{head}", "--out-dir", str(tmp_path / "quiet"))
    assert code == 0, err
    assert "posted:" not in out
    assert len(json.loads(state.read_text())["comments"]) == 1


def test_post_without_a_pull_request_writes_the_review_and_stops(make_repo, monkeypatch, capsys, tmp_path):
    root = make_repo({"src/a.ts": "export function a() { return 1 }\n"})
    monkeypatch.chdir(root)
    _state, log = fake_gh(tmp_path, monkeypatch, {
        "number": 1, "url": "u", "baseRefName": "main", "baseRefOid": "a" * 40, "headRefOid": "b" * 40,
    })
    assert main(["init"]) == 0
    base = sha(root)
    commit_files(root, {"src/a.ts": "export function a() { return 2 }\n"})
    head = sha(root)
    code, _out, err = run(capsys, "review", f"{base}..{head}", "--post", "--out-dir", str(tmp_path / "kept"))
    assert code == 2
    assert "--post needs a pull request number" in err
    assert (tmp_path / "kept" / "review.md").exists()
    assert not any(call[:2] == ["pr", "comment"] for call in gh_calls(log))


def test_a_branch_uses_its_merge_base(make_repo, monkeypatch, capsys, tmp_path):
    root = make_repo({"src/a.ts": "export function a() { return 1 }\n"})
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    main_sha = sha(root)
    git(root, "checkout", "-q", "-b", "feature")
    commit_files(root, {"src/a.ts": "export function a() { return 2 }\n"})
    feature = sha(root)
    code, out, err = run(capsys, "review", "feature", "--out-dir", str(tmp_path / "branch"))
    assert code == 0, err
    text = (tmp_path / "branch" / "review.md").read_text()
    assert f"compare={main_sha}..{feature}" in text.splitlines()[0]
    assert "summarise-change" in out


def test_review_does_not_change_the_worktree_or_refs(make_repo, monkeypatch, capsys, tmp_path):
    root = make_repo({"src/a.ts": "export function a() { return 1 }\n", "README.md": "keep\n"})
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    base = sha(root)
    commit_files(root, {"src/a.ts": "export function a() { return 2 }\n"})
    head = sha(root)
    (root / "README.md").write_text("dirty\n")
    before = snapshot(root)
    code, _out, err = run(capsys, "review", f"{base}..{head}", "--out-dir", str(tmp_path / "safe"))
    assert code == 0, err
    after = snapshot(root)
    assert after == before


def test_without_concepts_the_diagram_uses_packages(make_repo, monkeypatch, capsys, tmp_path):
    files = {
        "left/package.json": json.dumps({"name": "left"}) + "\n",
        "left/src/a.ts": "export function a() { return 1 }\n",
        "right/package.json": json.dumps({"name": "right", "dependencies": {"left": "1.0.0"}}) + "\n",
        "right/src/b.ts": 'import { a } from "../../left/src/a";\nexport function b() { return a(); }\n',
    }
    root = make_repo(files)
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    base = sha(root)
    files["right/src/c.ts"] = 'import { b } from "./b";\nexport function c() { return b(); }\n'
    commit_files(root, files)
    head = sha(root)
    code, _out, err = run(capsys, "review", f"{base}..{head}", "--out-dir", str(tmp_path / "pkgs"))
    assert code == 0, err
    text = (tmp_path / "pkgs" / "review.md").read_text()
    block = mermaid_block(text)
    assert review.valid_mermaid(block)
    assert "flowchart LR" in block
    assert "right" in block
    assert "## Deployables, packages and folders" in text
    assert "App (provisional)" not in block


def test_review_counts_an_injection_call_and_ignores_one_from_a_test(tmp_path):
    def node(**kwargs):
        row = {"parent_id": None, "workspace_id": "local:repo", "path": "", "content_hash": None,
               "signature": "", "attrs": None}
        row.update(kwargs)
        return row

    app = node(id="app", kind="concept", display_kind="service", name="App")
    core = node(id="core", kind="concept", display_kind="core", name="Core")
    source = node(id="local:repo:a.ts", kind="file", display_kind="source file", name="a.ts", path="a.ts")
    other = node(id="local:repo:b.ts", kind="file", display_kind="source file", name="b.ts", path="b.ts")
    test = node(id="local:repo:a.test.ts", kind="file", display_kind="test file", name="a.test.ts", path="a.test.ts")
    run = node(id="local:repo:a.ts#run", kind="symbol", display_kind="function", name="run", path="a.ts")
    append = node(id="local:repo:b.ts#append", kind="symbol", display_kind="method", name="append", path="b.ts")
    test_run = node(id="local:repo:a.test.ts#run", kind="symbol", display_kind="function", name="run", path="a.test.ts")
    nodes = [app, core, source, other, test, run, append, test_run]
    owns = [
        ("app", "local:repo:a.ts", "owns", 1, None),
        ("app", "local:repo:a.test.ts", "owns", 1, None),
        ("core", "local:repo:b.ts", "owns", 1, None),
    ]
    relates = ("app", "core", "relates", 1, json.dumps({"label": "records to"}))
    inject = json.dumps({"via": "injection"})
    base_db, head_db = tmp_path / "base.db", tmp_path / "head.db"

    def write(path, edges):
        conn = store.open_db(path)
        conn.executemany(
            "INSERT INTO nodes (id, parent_id, kind, display_kind, name, workspace_id, path, content_hash, signature, attrs) "
            "VALUES (:id, :parent_id, :kind, :display_kind, :name, :workspace_id, :path, :content_hash, :signature, :attrs)",
            nodes,
        )
        conn.executemany(
            "INSERT INTO edges (src, dst, kind, source, weight, attrs) VALUES (?, ?, ?, 'treesitter', ?, ?)",
            edges,
        )
        conn.commit()
        conn.close()

    write(base_db, [*owns, relates])
    write(head_db, [*owns, relates,
                    ("local:repo:a.ts#run", "local:repo:b.ts#append", "calls", 2, inject),
                    ("local:repo:a.test.ts#run", "local:repo:b.ts#append", "calls", 9, inject)])
    base_conn, head_conn = diff.open_model(base_db), diff.open_model(head_db)
    try:
        result = diff.compare(base_conn, head_conn)
        diagram = review.build_diagram(result, base_conn, head_conn)
        mermaid = review.render_mermaid(diagram)
    finally:
        base_conn.close()
        head_conn.close()
    text = review.render_review(tmp_path, "a" * 40, "b" * 40, {}, result, diagram, mermaid, None, None, None)
    assert "calls 0 -> 2" in text
    assert "calls 0 -> 11" not in text
    assert "calls 0 -> 9" not in text

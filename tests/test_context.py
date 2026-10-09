"""cbi context: a short Markdown block for one node, with no env values."""

import importlib.util
import json
import shlex
import sqlite3
import subprocess
from pathlib import Path

from cbi import build, context
from cbi.cli import main

_spec = importlib.util.spec_from_file_location(
    "context_fixture_viewer", Path(__file__).with_name("test_viewer.py"))
_viewer = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_viewer)
API, APP, ENV, FN, KEYCHAIN, WS = _viewer.API, _viewer.APP, _viewer.ENV, _viewer.FN, _viewer.KEYCHAIN, _viewer.WS
_edge, _node, concept_model = _viewer._edge, _viewer._node, _viewer.concept_model

SECRET = "s3cr3t-default-value"
EXAMPLE = "example-token-value"


def _place(tmp_path, **kw):
    root = kw.pop("repo", tmp_path)
    model = kw.pop("model_root", root / ".cbi")
    return context.Place(repo=root, model_root=model, branch=kw.pop("branch", "main"), **kw)


def _run(capsys, *argv):
    capsys.readouterr()
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_version_lines(tmp_path):
    repo = tmp_path / "repo"
    model = repo / ".cbi"
    work = context.Place(repo, model, branch="main")
    assert work.version_line() == f"worktree {work.repo} on main"
    assert context.Place(repo, model).version_line() == f"worktree {work.repo}"
    sha = "a" * 40
    assert context.Place(repo, model, ref="v1", sha=sha).version_line() == f"ref v1 ({sha})"
    assert context.Place(repo, model, ref=sha, sha=sha).version_line() == f"ref {sha}"
    assert context.Place(repo, model, compare=("HEAD~1", "HEAD")).version_line() == "comparison HEAD~1..HEAD"


def test_symbol_block_omits_secrets_and_quotes_the_id(tmp_path):
    conn = concept_model(tmp_path)
    conn.execute(
        "UPDATE nodes SET attrs = ? WHERE id = ?",
        (json.dumps({"declared_in": [".env.example"], "example": EXAMPLE, "default": SECRET}), ENV),
    )
    conn.commit()
    place = _place(tmp_path)
    text = context.render(conn, FN, place)

    assert text.startswith("# verify\n")
    assert "Project: fixture\n" in text
    assert f"Path: {place.repo}\n" in text
    assert f"Model: {place.model_root}\n" in text
    assert f"Version: worktree {place.repo} on main\n" in text
    assert "kind: function\n" in text
    assert f"id: `{FN}`\n" in text
    assert "file: `a.ts:1`\n" in text
    assert "summary:" not in text
    assert "concept: App / API\n" in text
    assert "calls\n- `Store` (Store)\n" in text
    assert "rendered by\n- `Board` (UI)\n" in text
    assert "Tests: 1 linked\n" in text
    assert "Environment: API_TOKEN\n" in text
    assert "LOG_LEVEL" not in text
    assert SECRET not in text and EXAMPLE not in text and "default" not in text
    assert "API verifies tokens with Keychain via security CLI at a.ts:verify" in text
    assert f"cbi show {shlex.quote(FN)}" in text
    assert f"cbi tests-for {shlex.quote(FN)}" in text
    assert "cbi search verify" in text
    assert "cbi diff" not in text
    assert "--out" not in text
    assert "--ref" not in text
    assert f"sqlite3 {shlex.quote(str(place.model_db))}" in text
    assert FN in text.split("sqlite3", 1)[1]
    assert len(text.splitlines()) <= context.LINE_CAP
    assert text.endswith("```\n")


def test_concept_block_lists_children_and_owned_files(tmp_path):
    conn = concept_model(tmp_path)
    _edge(conn, APP, API, "relates", attrs={"kind": "hosts"})
    conn.commit()
    place = _place(tmp_path)
    api = context.render(conn, API, place)
    app = context.render(conn, APP, place)

    assert "kind: service\n" in api
    assert f"id: `{API}`\n" in api
    assert "file:" not in api
    assert "summary: Serves tokens.\n" in api
    assert "parents: App\n" in api
    assert "children:" not in api
    assert "owned files: 2\n" in api
    assert "Environment: API_TOKEN, LOG_LEVEL\n" in api
    assert "Tests: 1 linked\n" in api
    assert "verifies tokens with\n- `Keychain`" in api
    assert "hosted by\n- `App`" in api
    body, _, points = api.partition("Integration points")
    assert "hosted by" in body
    assert "App hosts API" not in points
    assert "API verifies tokens with Keychain via security CLI at a.ts:verify" in points
    assert SECRET not in api and "info" not in api and "default" not in api
    assert len(api.splitlines()) <= context.LINE_CAP

    assert "children: API, Store\n" in app
    assert "owned files: 3\n" in app
    assert "parents:" not in app
    assert "file:" not in app


def test_env_node_keeps_declared_paths_and_drops_values(tmp_path):
    conn = concept_model(tmp_path)
    conn.execute(
        "UPDATE nodes SET attrs = ? WHERE id = ?",
        (json.dumps({"declared_in": [".env.example", "compose"], "example": EXAMPLE, "default": SECRET}), ENV),
    )
    conn.commit()
    text = context.render(conn, ENV, _place(tmp_path))
    assert "kind: env var\n" in text
    assert "declared in: .env.example, compose\n" in text
    assert SECRET not in text and EXAMPLE not in text
    assert "Environment:" not in text
    assert "cbi search API_TOKEN" in text


def test_custom_out_and_comparison_flags(tmp_path):
    conn = concept_model(tmp_path)
    out = tmp_path / "model"
    db = out / "refs" / "abc" / "model.db"
    place = context.Place(repo=tmp_path, model_root=out, model_db=db, compare=("base", "head"), sha="abc")
    text = context.render(conn, FN, place)
    flag = "--out " + shlex.quote(str(place.model_root))
    assert "Version: comparison base..head\n" in text
    assert flag in text
    assert f"cbi show {shlex.quote(FN)} {flag} --ref head" in text
    assert f"cbi diff base head {flag}" in text
    assert shlex.quote(str(place.model_db)) in text
    assert "refs/abc/model.db" in text.replace("\\", "/")


def test_ref_commands_name_the_ref(tmp_path):
    conn = concept_model(tmp_path)
    sha = "b" * 40
    place = context.Place(repo=tmp_path, model_root=tmp_path / ".cbi", ref="v1", sha=sha)
    text = context.render(conn, FN, place)
    assert f"Version: ref v1 ({sha})\n" in text
    assert "--out" not in text
    assert "--ref v1" in text
    assert "cbi diff" not in text


def test_long_block_drops_bullets_and_keeps_commands(tmp_path):
    conn = concept_model(tmp_path)
    for i in range(40):
        node_id = f"{WS}:b.ts#extra{i}"
        _node(conn, id=node_id, parent_id=f"{WS}:b.ts", kind="symbol", display_kind="function",
              name=f"extra{i}", path="b.ts", start_line=i + 1)
        _edge(conn, FN, node_id, "calls")
    conn.commit()
    text = context.render(conn, FN, _place(tmp_path))
    assert len(text.splitlines()) <= context.LINE_CAP
    assert "To see more" in text
    assert f"cbi show {shlex.quote(FN)}" in text
    assert "sqlite3 " in text
    assert "- ... " in text or text.count("\n- `extra") < 40


def test_embed_matches_render_and_build_writes_it(tmp_path):
    conn = concept_model(tmp_path)
    place = _place(tmp_path)
    payload = build.concept_view(conn)
    embedded = context.embed(conn, payload, place)
    assert embedded["workspace"] == WS
    assert embedded["blocks"][FN] == context.render(conn, FN, place)
    assert embedded["blocks"][API] == context.render(conn, API, place)
    assert embedded["blocks"][APP] == context.render(conn, APP, place)
    assert embedded["blocks"][KEYCHAIN] == context.render(conn, KEYCHAIN, place)
    assert FN in embedded["blocks"] and API in embedded["blocks"]

    viewer = tmp_path / "viewer"
    build.build(conn, viewer, place=place)
    raw = (viewer / "data" / "context.js").read_text()
    assert raw.startswith('cbiLoad("context", ')
    written = json.loads(raw.removeprefix('cbiLoad("context", ').removesuffix(");\n"))
    assert written["blocks"][FN] == embedded["blocks"][FN]
    conn.close()


def test_empty_concept_summary(tmp_path):
    conn = concept_model(tmp_path)
    conn.execute("UPDATE nodes SET summary = NULL WHERE id = ?", (API,))
    conn.commit()
    text = context.render(conn, API, _place(tmp_path))
    assert "summary: (none yet)\n" in text


def test_context_on_a_scanned_symbol_and_concept(make_repo, monkeypatch, capsys):
    root = make_repo({"a.ts": "export function hi() { return 1; }\n"})
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    db = root / ".cbi" / "model.db"
    conn = sqlite3.connect(db)
    fn = conn.execute("SELECT id FROM nodes WHERE name = 'hi' AND kind = 'symbol'").fetchone()[0]
    file_id = fn.split("#", 1)[0]
    concept = f"{WS}:concept:cli"
    env = f"{WS}:env:SECRET"
    with conn:
        conn.execute(
            "INSERT INTO nodes (id, parent_id, kind, display_kind, name, workspace_id, summary) "
            "VALUES (?, ?, 'concept', 'service', 'CLI', ?, 'The command.')",
            (concept, WS, WS),
        )
        conn.execute(
            "INSERT INTO edges (src, dst, kind, source, confidence) VALUES (?, ?, 'owns', 'fixture', 1)",
            (concept, file_id),
        )
        conn.execute(
            "INSERT INTO nodes (id, parent_id, kind, display_kind, name, workspace_id, attrs) "
            "VALUES (?, ?, 'env', 'env var', 'SECRET', ?, ?)",
            (env, WS, WS, json.dumps({"example": EXAMPLE})),
        )
        conn.execute(
            "INSERT INTO edges (src, dst, kind, source, confidence, attrs) VALUES (?, ?, 'reads_env', 'fixture', 1, ?)",
            (fn, env, json.dumps({"default": SECRET})),
        )
    conn.close()
    before = db.stat().st_mtime_ns

    code, out, err = _run(capsys, "context", fn)
    assert code == 0, err
    assert f"id: `{fn}`" in out
    assert "kind: function" in out
    assert "concept: CLI" in out
    assert "Environment: SECRET" in out
    assert SECRET not in out and EXAMPLE not in out and "default" not in out
    assert f"cbi show {shlex.quote(fn)}" in out
    assert "cbi tests-for" in out and "cbi search hi" in out and "sqlite3 " in out
    assert "--out" not in out
    assert len(out.splitlines()) <= context.LINE_CAP
    assert db.stat().st_mtime_ns == before

    code, out, err = _run(capsys, "context", concept)
    assert code == 0, err
    assert "owned files: 1" in out
    assert "children:" not in out
    assert SECRET not in out and EXAMPLE not in out
    assert db.stat().st_mtime_ns == before

    code, _, err = _run(capsys, "context", "no-such-node")
    assert code == 1 and "no node matches" in err


def test_context_compare_and_bad_compare(make_repo, monkeypatch, tmp_path, capsys):
    root = make_repo({"a.ts": "export function hi() { return 1; }\n"})
    monkeypatch.chdir(root)
    path = root / "a.ts"
    path.write_text("export function hi() { return 2; }\n")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@example.com", "-c", "commit.gpgsign=false",
         "commit", "-q", "-m", "next"],
        cwd=root, check=True, capture_output=True,
    )
    out = tmp_path / "model"
    assert main(["init", "--out", str(out)]) == 0
    code, text, err = _run(capsys, "context", "--compare", "HEAD~1..HEAD", "--out", str(out), "a.ts#hi")
    assert code == 0, err
    assert "comparison HEAD~1..HEAD" in text
    assert "a.ts#hi" in text
    assert "cbi diff" in text and "HEAD~1" in text and "--ref HEAD" in text
    assert "refs/" in text.replace("\\", "/")
    assert not (root / ".cbi").exists()
    assert len(text.splitlines()) <= context.LINE_CAP

    code, _, err = _run(capsys, "context", "--out", str(out), "--ref", "HEAD", "no-such-node")
    assert code == 1 and "no node matches" in err

    code, _, err = _run(capsys, "context", "--compare", "HEAD...HEAD", "--out", str(out), "a.ts#hi")
    assert code == 2 and "compare must be base..head" in err


def test_viewer_sources_expose_copy_for_agent():
    root = Path(__file__).resolve().parents[1]
    app = (root / "src/cbi/viewer/app.js").read_text(encoding="utf-8")
    assert "Copy for agent" in app and "copy-agent" in app
    assert 'ev.key === "c" || ev.key === "C"' in app
    assert "function cbiCopy" in app and "getSelection" in app
    html = (root / "src/cbi/viewer/index.html").read_text()
    assert 'id="toast"' in html and "data/context.js" in html
    main = (root / "app/src/main.ts").read_text()
    assert "clipboard-sanitized-write" in main
    assert "CommandOrControl+C" in main and "cbiCopy()" in main

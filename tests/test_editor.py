"""Editor command: template splitting, path checks, and which items open."""

import importlib.util
import os
import stat
import subprocess
from pathlib import Path

import pytest

from cbi import build, editor
from cbi.cli import main
from cbi.editor import EditorError


def _concept_model():
    path = Path(__file__).with_name("test_viewer.py")
    spec = importlib.util.spec_from_file_location("cbi_test_viewer", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.concept_model


concept_model = _concept_model()


def test_preset_splits_and_spaces_stay_one_argument():
    assert editor.split_template(editor.TEMPLATES["vscode"]) == [
        "code", "--reuse-window", "{project}", "--goto", "{file}:{line}",
    ]
    assert editor.split_template("cmd \"a b\" 'c d'") == ["cmd", "a b", "c d"]
    assert editor.fill_template('open "{file}"', "/p", "/a file.ts", 3) == ["open", "/a file.ts"]
    # A semicolon is a character in the argument, not a shell separator.
    assert editor.fill_template("echo {file};", "/p", "/a", 1) == ["echo", "/a;"]
    assert editor.fill_template("echo {line}", "/p", "/a", 0) == ["echo", "1"]


def test_empty_or_unclosed_template_is_an_error():
    with pytest.raises(EditorError) as empty:
        editor.split_template("   ")
    assert empty.value.code == 2
    with pytest.raises(EditorError) as quote:
        editor.split_template('open "unterminated')
    assert quote.value.code == 2


def test_resolve_worktree_ref_and_escape(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    (work / "a.ts").write_text("x\n")
    opened = editor.resolve_target("a.ts", 4, project=work, worktree=work, ref=False)
    assert opened == {"project": str(work.resolve()), "file": str((work / "a.ts").resolve()), "line": 4}
    assert editor.resolve_target("a.ts", 0, project=work, worktree=work, ref=False)["line"] == 1
    with pytest.raises(EditorError, match="not on disk"):
        editor.resolve_target("gone.ts", 1, project=work, worktree=work, ref=False)
    with pytest.raises(EditorError, match="not checked out"):
        editor.resolve_target("gone.ts", 1, project=work, worktree=work, ref=True)
    present = editor.resolve_target("a.ts", 2, project=work, worktree=work, ref=True)
    assert present["file"] == str((work / "a.ts").resolve())
    with pytest.raises(EditorError, match="outside"):
        editor.resolve_target("../secret", 1, project=work, worktree=work, ref=False)
    with pytest.raises(EditorError, match="outside"):
        editor.resolve_target("/etc/passwd", 1, project=work, worktree=work, ref=False)
    with pytest.raises(EditorError, match="no file"):
        editor.resolve_target("a\x00b", 1, project=work, worktree=work, ref=False)
    with pytest.raises(EditorError, match="no file"):
        editor.resolve_target(".", 1, project=work, worktree=work, ref=False)


def test_symlink_outside_is_refused_and_inside_is_opened(tmp_path):
    work = tmp_path / "work"
    (work / "sub").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text("x")
    (work / "link.txt").symlink_to(secret)
    with pytest.raises(EditorError, match="outside"):
        editor.resolve_target("link.txt", 1, project=work, worktree=work, ref=False)
    target = work / "sub" / "a.txt"
    target.write_text("x")
    (work / "inside.txt").symlink_to(target)
    opened = editor.resolve_target("inside.txt", 1, project=work, worktree=work, ref=False)
    assert opened["file"] == str(target.resolve())


def test_only_one_file_items_open():
    open_kinds = [
        ("file", "file"), ("file", "source file"), ("file", "test file"),
        ("symbol", "class"), ("symbol", "function"), ("symbol", "method"),
        ("symbol", "component"), ("symbol", "interface"), ("test", "test case"),
    ]
    for kind, display in open_kinds:
        assert editor.opens_in_editor(kind, display, "a.ts")
    closed = [
        ("concept", "service"), ("group", "folder"), ("deployable", "web app"),
        ("package", "library"), ("external", "cli tool"), ("workspace", "workspace"),
        ("env", "env var"), ("screen", "screen"), ("doc", "doc"),
        ("file", "symlink"), ("test", "test suite"),
    ]
    for kind, display in closed:
        assert not editor.opens_in_editor(kind, display, "a.ts")
    assert not editor.opens_in_editor("symbol", "function", "")
    assert not editor.opens_in_editor("symbol", "function", None)


def test_code_is_found_on_path_then_in_the_app_bundle(tmp_path):
    home = tmp_path / "home"
    bundle = home / "Applications" / "Visual Studio Code.app" / "Contents" / "Resources" / "app" / "bin" / "code"
    bundle.parent.mkdir(parents=True)
    bundle.write_text("#!/bin/sh\n")
    bundle.chmod(bundle.stat().st_mode | stat.S_IEXEC)
    on_path = tmp_path / "bin" / "code"
    on_path.parent.mkdir()
    on_path.write_text("#!/bin/sh\n")
    on_path.chmod(on_path.stat().st_mode | stat.S_IEXEC)
    have = {str(on_path), str(bundle)}
    check = lambda path: path in have
    mac = {"platform": "darwin"}
    assert editor.find_program("code", path_env=str(on_path.parent), home=home, is_executable=check, **mac) == str(on_path)
    assert editor.find_program("code", path_env="", home=home, is_executable=check, **mac) == str(bundle)
    assert editor.find_program("code", path_env="", home=tmp_path / "nobody", is_executable=lambda _path: False, **mac) is None
    argv = editor.command_argv(
        "vscode", None, "/proj", "/proj/a.ts", 2, path_env="", home=str(home), is_executable=check, **mac,
    )
    assert argv == [str(bundle), "--reuse-window", "/proj", "--goto", "/proj/a.ts:2"]
    with pytest.raises(EditorError, match="VS Code was not found"):
        editor.command_argv(
            "vscode", None, "/p", "/p/a.ts", 1, path_env="", home=str(tmp_path / "empty"),
            is_executable=lambda _path: False,
        )
    with pytest.raises(EditorError, match="No editor is configured"):
        editor.command_argv("none", None, "/p", "/p/a.ts", 1, path_env="", home=str(home))


def test_templates_match_the_desktop_app():
    text = (Path(__file__).parents[1] / "app" / "src" / "editor.ts").read_text()
    html = (Path(__file__).parents[1] / "app" / "src" / "index.html").read_text()
    for name, template in editor.TEMPLATES.items():
        assert template in text
        if name == "vscode":
            assert f'data-command="{template}"' in html
    app = (Path(__file__).parents[1] / "src" / "cbi" / "viewer" / "app.js").read_text()
    found = app.split("const OPEN_KINDS = new Set([", 1)[1].split("])", 1)[0]
    kinds = {part.strip().strip('"') for part in found.split(",") if part.strip()}
    assert kinds == set(editor.OPEN_DISPLAY_KINDS)
    assert "double-click jumps" not in app
    assert "openTargetFor" in app


def test_build_writes_the_editor_config(tmp_path):
    conn = concept_model(tmp_path)
    project = tmp_path / "proj"
    project.mkdir()
    viewer = build.build(conn, tmp_path / "viewer", project=project)
    text = (viewer.parent / "data" / "editor.js").read_text()
    assert text.startswith('cbiLoad("editor", ')
    assert '"editor":"vscode"' in text
    assert project.resolve().as_posix() in text
    html = viewer.read_text()
    assert html.index("open-editor.js") < html.index("app.js") < html.index("data/editor.js")
    assert html.index("app.js") < html.index("data/diff.js") < html.index("data/concepts.js")
    assert (viewer.parent / "open-editor.js").is_file()
    none = build.build(conn, tmp_path / "none", editor="none", project=project)
    assert '"editor":"none"' in (none.parent / "data" / "editor.js").read_text()
    cursor = build.build(conn, tmp_path / "cursor", editor="cursor", project=project)
    assert '"editor":"cursor"' in (cursor.parent / "data" / "editor.js").read_text()
    unknown = build.build(conn, tmp_path / "other", editor="emacs", project=project)
    assert '"editor":"vscode"' in (unknown.parent / "data" / "editor.js").read_text()
    assert '"sha"' not in (viewer.parent / "data" / "editor.js").read_text()
    sha = "a" * 40
    ref = build.build(conn, tmp_path / "ref", project=project, ref_sha=sha)
    payload = (ref.parent / "data" / "editor.js").read_text()
    assert sha in payload
    script = (ref.parent / "open-editor.js").read_text()
    assert "Copy git show command" in script
    assert "git show " in script


def test_launch_does_not_use_a_shell(monkeypatch):
    seen = {}

    def fake_popen(argv, **kwargs):
        seen["argv"] = argv
        seen["kwargs"] = kwargs

    monkeypatch.setattr(editor.subprocess, "Popen", fake_popen)
    editor.launch(["/bin/echo", "hi"])
    assert seen["argv"] == ["/bin/echo", "hi"]
    assert seen["kwargs"]["start_new_session"] is True
    assert seen["kwargs"].get("shell") is not True

    seen.clear()
    editor.launch([r"C:\Program Files\code.cmd", "--goto", r"C:\proj\a.ts:1"], platform="win32")
    assert seen["argv"][0] == "cmd.exe"
    assert seen["argv"][1:4] == ["/d", "/s", "/c"]
    assert "code.cmd" in seen["argv"][4]
    assert seen["kwargs"]["creationflags"] & 0x00000200
    assert seen["kwargs"].get("shell") is not True
    assert "start_new_session" not in seen["kwargs"]


def test_windows_editor_lookup_prefers_code_cmd(tmp_path):
    assert editor.command_names("code", "win32") == ["code.cmd", "code.exe", "code"]
    assert editor.command_names("git", "win32") == ["git.exe", "git.cmd", "git"]
    assert editor.command_names("code", "linux") == ["code"]
    home = tmp_path / "home"
    cmd = r"C:\bin\code.cmd"
    exe = r"C:\bin\code.exe"
    have = {cmd, exe}

    def check(path):
        return path in have

    assert editor.find_program(
        "code", path_env=r"C:\empty;C:\bin", home=home, is_executable=check,
        platform="win32", where=lambda _name: None,
    ) == cmd
    assert editor.find_program(
        "code", path_env=r"C:\empty", home=home, is_executable=check,
        platform="win32", where=lambda _name: exe,
    ) == exe
    assert editor.find_program(
        "code", path_env="", home=home, is_executable=lambda _path: False,
        platform="linux", where=lambda _name: exe,
    ) is None


def test_snapshot_cache_follows_the_platform(tmp_path, monkeypatch):
    monkeypatch.delenv("CBI_SNAPSHOT_DIR", raising=False)
    home = tmp_path / "home"
    assert editor.snapshot_cache(home=home, platform="win32", env={}) == (
        home / "AppData" / "Local" / "codebase-inspector" / "snapshots"
    )
    assert editor.snapshot_cache(home=home, platform="linux", env={}) == (
        home / ".cache" / "codebase-inspector" / "snapshots"
    )
    assert editor.snapshot_cache(home=home, platform="darwin", env={}) == (
        home / "Library" / "Caches" / "codebase-inspector" / "snapshots"
    )
    assert editor.snapshot_cache(platform="linux", env={"XDG_CACHE_HOME": str(tmp_path / "xdg")}) == (
        tmp_path / "xdg" / "codebase-inspector" / "snapshots"
    )
    assert editor.snapshot_cache(
        home=home, platform="linux", env={"XDG_CACHE_HOME": str(tmp_path / "xdg")},
    ) == home / ".cache" / "codebase-inspector" / "snapshots"
    assert editor.snapshot_cache(platform="win32", env={"LOCALAPPDATA": str(tmp_path / "local")}) == (
        tmp_path / "local" / "codebase-inspector" / "snapshots"
    )


def _fake_code(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    code = bin_dir / "code"
    code.write_text("#!/bin/sh\nexit 0\n")
    code.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ.get("PATH", ""))
    launched = []
    monkeypatch.setattr(editor, "launch", lambda argv: launched.append(list(argv)))
    return code, launched


def test_open_file_prints_and_runs_argv(make_repo, monkeypatch, tmp_path, capsys):
    root = make_repo({"src/my app.py": "\ndef greet():\n    return 1\n"})
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    assert main(["scan"]) == 0
    code, launched = _fake_code(tmp_path, monkeypatch)
    capsys.readouterr()
    rc = main(["open-file", "greet"])
    out, err = capsys.readouterr()
    assert rc == 0, err
    assert len(launched) == 1
    argv = launched[0]
    assert argv[0] == str(code)
    assert argv[1:3] == ["--reuse-window", str(root.resolve())]
    assert argv[3] == "--goto"
    assert argv[4].endswith("src/my app.py:2")
    assert len(argv) == 5
    assert "src/my app.py" in out
    capsys.readouterr()
    rc = main(["open-file", "src"])
    _out, err = capsys.readouterr()
    assert rc == 1
    assert len(launched) == 1
    assert "does not map to one file" in err
    capsys.readouterr()
    rc = main(["open-file", "--editor", "none", "greet"])
    _out, err = capsys.readouterr()
    assert rc == 1
    assert "No editor is configured." in err
    assert len(launched) == 1


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _side_repo(tmp_path):
    """main has one copy of src/pay.py. side has another and is not checked out."""
    root = tmp_path / "hq"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    (root / "src").mkdir()
    (root / "src" / "pay.py").write_text("def arrears():\n    return 0\n")
    _git(root, "add", "src/pay.py")
    _git(root, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "main")
    _git(root, "checkout", "-q", "-b", "feature/side-by-side")
    side_text = "def arrears():\n    return 1\n"
    (root / "src" / "pay.py").write_text(side_text)
    _git(root, "add", "src/pay.py")
    _git(root, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "side")
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True,
    ).stdout.strip()
    _git(root, "checkout", "-q", "main")
    return root, sha, side_text


def test_ref_opens_the_worktree_that_has_the_branch(tmp_path):
    root, sha, side_text = _side_repo(tmp_path)
    other = tmp_path / "side-work"
    _git(root, "worktree", "add", "-q", str(other), "feature/side-by-side")
    cache = tmp_path / "cache"
    before = subprocess.run(["git", "status", "--porcelain"], cwd=root, check=True, capture_output=True, text=True).stdout
    opened = editor.resolve_ref_target(
        "src/pay.py", 1, repo=root, branch="feature/side-by-side", sha=sha, cache_dir=cache,
    )
    assert editor.branch_name(root, "feature/side-by-side") == "feature/side-by-side"
    assert editor.branch_name(root, sha) == ""
    assert editor.branch_name(root, "--end-of-options") == ""
    assert opened["notice"] is None
    assert opened["project"] == str(other.resolve())
    assert opened["file"] == str((other / "src" / "pay.py").resolve())
    assert opened["line"] == 1
    assert Path(opened["file"]).read_text() == side_text
    assert not cache.exists()
    after = subprocess.run(["git", "status", "--porcelain"], cwd=root, check=True, capture_output=True, text=True).stdout
    assert after == before


def test_ref_opens_a_worktree_at_the_same_commit(tmp_path):
    root, sha, side_text = _side_repo(tmp_path)
    other = tmp_path / "detached"
    _git(root, "worktree", "add", "--detach", "-q", str(other), sha)
    cache = tmp_path / "cache"
    opened = editor.resolve_ref_target(
        "src/pay.py", 1, repo=root, branch="feature/side-by-side", sha=sha, cache_dir=cache,
    )
    assert opened["notice"] is None
    assert opened["project"] == str(other.resolve())
    assert Path(opened["file"]).read_text() == side_text
    assert not cache.exists()


def test_ref_snapshot_is_created_and_reused(tmp_path, monkeypatch):
    root, sha, side_text = _side_repo(tmp_path)
    cache = tmp_path / "cache"
    calls = []
    real = editor.git_show_blob

    def show(repo, commit, rel):
        calls.append([repo, commit, rel])
        return real(repo, commit, rel)

    seen = []
    run = subprocess.run

    def spy(argv, *args, **kwargs):
        if argv and argv[0] == "git":
            seen.append(list(argv))
        return run(argv, *args, **kwargs)

    monkeypatch.setattr(editor.subprocess, "run", spy)
    opened = editor.resolve_ref_target(
        "src/pay.py", 2, repo=root, branch="feature/side-by-side", sha=sha,
        cache_dir=cache, show_blob=show,
    )
    assert len(calls) == 1
    assert calls[0][1:] == [sha, "src/pay.py"]
    snap = Path(opened["file"])
    assert snap.read_text() == side_text
    assert stat.S_IMODE(snap.stat().st_mode) == 0o444
    assert opened["project"] == str(snap.parent.parent.resolve())
    assert f"hq@feature-side-by-side-{sha[:12]}" in opened["project"]
    assert "/" not in Path(opened["project"]).name
    assert opened["line"] == 2
    assert opened["notice"] == (
        f"Opened a read-only copy from feature/side-by-side ({sha[:7]}); not checked out locally."
    )
    assert snap.resolve().is_relative_to(cache.resolve())
    with pytest.raises(ValueError):
        snap.resolve().relative_to(root.resolve())
    assert (root / "src" / "pay.py").read_text() != side_text
    stamp = snap.stat().st_mtime_ns
    again = editor.resolve_ref_target(
        "src/pay.py", 2, repo=root, branch="feature/side-by-side", sha=sha,
        cache_dir=cache, show_blob=show,
    )
    assert again["file"] == opened["file"]
    assert len(calls) == 1
    assert snap.stat().st_mtime_ns == stamp
    def git_args(argv):
        args = list(argv[1:])
        while args and args[0].startswith("-"):
            args = args[2:] if args[0] in {"-c", "-C"} else args[1:]
        return args

    assert not any(
        git_args(argv)[:1] in (["checkout"], ["switch"], ["restore"]) or git_args(argv)[:2] == ["worktree", "add"]
        for argv in seen
    )
    monkeypatch.delenv("CBI_SNAPSHOT_DIR", raising=False)
    assert editor.snapshot_cache(home=tmp_path / "home") == (
        tmp_path / "home" / "Library" / "Caches" / "codebase-inspector" / "snapshots"
    )


def test_ref_snapshot_refuses_a_path_that_escapes(tmp_path):
    root, sha, _side = _side_repo(tmp_path)
    cache = tmp_path / "cache"
    cache.mkdir()

    def boom(*_args, **_kwargs):
        raise AssertionError("git was called")

    for rel in ("../secret", "/etc/passwd", "src/../../secret", "foo/../../../etc/passwd", "a\x00b"):
        with pytest.raises(EditorError):
            editor.resolve_ref_target(
                rel, 1, repo=root, branch="feature/side-by-side", sha=sha, cache_dir=cache,
                list_worktrees=boom, show_blob=boom,
            )
    assert list(cache.iterdir()) == []


def test_open_file_ref_writes_a_snapshot_and_leaves_the_repo(make_repo, monkeypatch, tmp_path, capsys):
    root = make_repo({"src/app.py": "def greet():\n    return 1\n"})
    monkeypatch.chdir(root)
    _git(root, "checkout", "-q", "-b", "side")
    side_text = "def greet():\n    return 2\n"
    (root / "src" / "app.py").write_text(side_text)
    _git(root, "add", "src/app.py")
    _git(root, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "side")
    _git(root, "checkout", "-q", "main")
    assert main(["init"]) == 0
    assert main(["scan", "--ref", "side"]) == 0
    _code, launched = _fake_code(tmp_path, monkeypatch)
    before = subprocess.run(["git", "status", "--porcelain"], cwd=root, check=True, capture_output=True, text=True).stdout
    trees = subprocess.run(["git", "worktree", "list", "--porcelain"], cwd=root, check=True, capture_output=True, text=True).stdout
    capsys.readouterr()
    rc = main(["open-file", "--ref", "side", "src/app.py"])
    out, err = capsys.readouterr()
    assert rc == 0, err
    assert "Opened a read-only copy from side (" in err
    assert "not checked out locally." in err
    assert len(launched) == 1
    goto = launched[0][-1]
    snap = Path(goto.rsplit(":", 1)[0])
    assert snap.read_text() == side_text
    assert stat.S_IMODE(snap.stat().st_mode) == 0o444
    assert "src/app.py" in out
    assert (root / "src" / "app.py").read_text() != side_text
    after = subprocess.run(["git", "status", "--porcelain"], cwd=root, check=True, capture_output=True, text=True).stdout
    assert after == before
    assert subprocess.run(
        ["git", "worktree", "list", "--porcelain"], cwd=root, check=True, capture_output=True, text=True,
    ).stdout == trees
    capsys.readouterr()
    rc = main(["open-file", "--ref", "side", "src/app.py"])
    _out, err = capsys.readouterr()
    assert rc == 0, err
    assert len(launched) == 2
    assert Path(launched[1][-1].rsplit(":", 1)[0]) == snap

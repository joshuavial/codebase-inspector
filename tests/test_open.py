"""cbi open builds a cbi:// link and does not touch the repository."""

import os
import subprocess
import urllib.parse

from conftest import write_standin

import pytest

from cbi.cli import main
from cbi import open_link
from cbi.open_link import (
    NO_HANDLER,
    build_compare_url,
    build_url,
    parse_compare,
    valid_name,
    valid_node_id,
    valid_pr,
)

IDS = [
    "app",
    "bearer-auth",
    "ui/login",
    "local:repo",
    "local:repo:src/",
    "local:repo:src/shapes/circle.ts",
    "local:repo:src/shapes/circle.ts#Circle.area",
    "local:repo:src/shapes/circle.test.ts#measures the area",
    "local:repo:core/tests/test_geometry.py#TestCircle > test_area",
    "local:repo:core/tests/test_geometry.py#TestCircle > TestNested > test_unit",
    "local:repo:src/a.ts#same~f361afdb~2",
    "github.com/example/sample-lib:src/app.ts#Foo.bar",
    "local:fixture-app:deployable:fixture-cli",
    "local:repo:env:PORT",
    "local:repo:package:pkg",
    "local:repo:service:db",
]

REJECTED = [
    "",
    "../etc/passwd",
    "local:repo:../../etc/passwd",
    "$(id)",
    "`id`",
    "id;rm -rf /",
    "id|id",
    "id && id",
    "id\nid",
    "<script>",
    "id > /tmp/pwn",
    "local:repo:src/a.ts#foo > /tmp/pwn",
    "http://evil.example",
    "-rf",
]


def _query(url):
    parsed = urllib.parse.urlparse(url)
    assert parsed.scheme == "cbi" and parsed.netloc == "open"
    return urllib.parse.parse_qs(parsed.query)


def _porcelain(repo):
    return subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo, check=True, capture_output=True, text=True,
    ).stdout


def _head(repo):
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True,
    ).stdout.strip()


def _open(monkeypatch, capsys, argv):
    opened = {}

    def launch(url):
        opened["url"] = url
        return 0, ""

    monkeypatch.setattr(open_link, "open_url", launch)
    code = main(["open", *argv])
    out = capsys.readouterr()
    return code, out.out, out.err, opened


@pytest.mark.parametrize("node", IDS)
def test_node_id_grammar_accepts_real_ids(node):
    assert valid_node_id(node)


@pytest.mark.parametrize("node", REJECTED)
def test_node_id_grammar_rejects_traversal_and_injection(node):
    assert not valid_node_id(node)
    assert not valid_name(node)


def test_names_with_spaces_are_names_not_ids():
    assert valid_name("Sign in")
    assert valid_name("measures the area")
    assert not valid_node_id("Sign in")


@pytest.mark.parametrize("text,sides", [
    ("main..feature", ("main", "feature")),
    ("refs/heads/main..refs/heads/feature", ("refs/heads/main", "refs/heads/feature")),
])
def test_compare_shape(text, sides):
    assert parse_compare(text) == sides


@pytest.mark.parametrize("text", ["main", "main...feature", "main..", "..feature", "main..feature;rm", ""])
def test_compare_shape_rejects(text):
    assert parse_compare(text) is None


def test_pr_shape():
    assert valid_pr("1") and valid_pr("2345")
    assert not valid_pr("0") and not valid_pr("01") and not valid_pr("12;rm") and not valid_pr("-1")


def test_build_url_round_trips_a_node_with_spaces():
    node = "local:repo:src/a.test.ts#measures the area"
    url = build_url("/tmp/repo", "/tmp/repo", node)
    found = _query(url)
    assert found["repo"] == ["/tmp/repo"]
    assert found["ref"] == ["/tmp/repo"]
    assert found["node"] == [node]
    assert "compare" not in found and "pr" not in found


def test_open_prints_the_current_worktree_and_does_not_change_git(make_repo, monkeypatch, capsys):
    repo = make_repo({"README.md": "# app\n"})
    monkeypatch.chdir(repo)
    head = _head(repo)
    code, out, err, opened = _open(monkeypatch, capsys, [])
    assert code == 0 and err == ""
    found = _query(out.strip())
    assert found["repo"] == [str(repo)] and found["ref"] == [str(repo)]
    assert "node" not in found
    assert opened["url"] == out.strip()
    assert _porcelain(repo) == ""
    assert _head(repo) == head
    assert not (repo / ".cbi").exists()


def test_open_branch_commit_and_worktree(make_repo, monkeypatch, capsys, tmp_path):
    repo = make_repo({"README.md": "# app\n"}, name="app")
    lane = tmp_path / "lane"
    subprocess.run(["git", "worktree", "add", "-q", "-b", "lane", str(lane)], cwd=repo, check=True)
    sha = _head(repo)
    monkeypatch.chdir(repo)

    code, out, _err, _opened = _open(monkeypatch, capsys, ["--branch", "lane"])
    assert code == 0 and _query(out.strip())["ref"] == ["lane"]
    assert _query(out.strip())["repo"] == [str(repo)]

    code, out, _err, _opened = _open(monkeypatch, capsys, ["--commit", sha[:7]])
    assert code == 0 and _query(out.strip())["ref"] == [sha]

    code, out, _err, _opened = _open(monkeypatch, capsys, ["--worktree", "lane"])
    assert code == 0 and _query(out.strip())["ref"] == [str(lane.resolve())]
    assert _porcelain(repo) == ""
    assert _head(repo) == sha


def test_open_resolves_a_node_name_and_an_id(make_repo, monkeypatch, capsys):
    repo = make_repo({
        "src/app.ts": "export function greet() { return 1; }\n",
        "src/app.test.ts": (
            'import { test } from "node:test";\nimport { greet } from "./app";\n'
            'test("measures the area", () => { greet(); });\n'
        ),
    })
    monkeypatch.chdir(repo)
    assert main(["init"]) == 0
    assert main(["scan"]) == 0
    capsys.readouterr()

    code, out, err, _opened = _open(monkeypatch, capsys, ["--node", "greet"])
    assert code == 0 and err == ""
    assert _query(out.strip())["node"] == ["local:repo:src/app.ts#greet"]

    code, out, err, _opened = _open(monkeypatch, capsys, ["--node", "measures the area"])
    assert code == 0 and err == ""
    assert _query(out.strip())["node"] == ["local:repo:src/app.test.ts#measures the area"]

    node = "local:repo:src/app.ts#greet"
    code, out, _err, _opened = _open(monkeypatch, capsys, ["--node", node])
    assert code == 0 and _query(out.strip())["node"] == [node]
    assert _porcelain(repo) == ""


def test_open_reports_an_ambiguous_name(make_repo, monkeypatch, capsys):
    repo = make_repo({
        "src/a.ts": "export function greet() { return 1; }\n",
        "src/b.ts": "export function greet() { return 2; }\n",
    })
    monkeypatch.chdir(repo)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    capsys.readouterr()
    code, out, err, opened = _open(monkeypatch, capsys, ["--node", "greet"])
    assert code == 1 and out == "" and "opened" not in opened
    assert "matches 2 nodes" in err
    assert "local:repo:src/a.ts#greet" in err and "local:repo:src/b.ts#greet" in err


def test_open_rejects_injection_and_unknown_versions(make_repo, monkeypatch, capsys):
    repo = make_repo({"README.md": "# app\n"})
    monkeypatch.chdir(repo)
    code, out, err, opened = _open(monkeypatch, capsys, ["--node", "$(id)"])
    assert code == 1 and out == "" and "opened" not in opened
    assert "not valid" in err

    code, out, err, opened = _open(monkeypatch, capsys, ["--node", "local:repo:../../etc/passwd"])
    assert code == 1 and "not valid" in err and "opened" not in opened

    code, out, err, _opened = _open(monkeypatch, capsys, ["--branch", "no-such-branch"])
    assert code == 1 and out == "" and "unknown ref" in err

    code, out, err, _opened = _open(monkeypatch, capsys, ["--worktree", "missing"])
    assert code == 1 and "unknown worktree" in err

    code, out, err, _opened = _open(monkeypatch, capsys, ["--commit", "deadbeef"])
    assert code == 1 and "unknown ref" in err
    assert _porcelain(repo) == ""


def _git_text(repo, *args):
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True,
    ).stdout


def _snapshot(repo):
    return (
        _porcelain(repo),
        _head(repo),
        _git_text(repo, "stash", "list"),
        _git_text(repo, "for-each-ref"),
    )


def _second_commit(repo):
    base = _head(repo)
    readme = repo / "README.md"
    readme.write_text("# next\n")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@example.com", "-c", "commit.gpgsign=false",
         "commit", "-q", "-m", "next"],
        cwd=repo, check=True,
    )
    return base, _head(repo)


def _fake_gh(tmp_path, monkeypatch, body):
    bin_dir = tmp_path / "ghbin"
    path = write_standin(bin_dir, "gh", body)
    monkeypatch.setenv("PATH", f"{path.parent}{os.pathsep}{os.environ.get('PATH', '')}")
    return path


def test_open_compare_prints_the_link_and_does_not_change_git(make_repo, monkeypatch, capsys):
    repo = make_repo({"README.md": "# app\n"})
    base, head = _second_commit(repo)
    monkeypatch.chdir(repo)
    before = _snapshot(repo)
    code, out, err, opened = _open(monkeypatch, capsys, ["--compare", f"{base}..main", "--node", "local:repo"])
    assert code == 0 and err == ""
    found = _query(out.strip())
    assert found["repo"] == [str(repo)]
    assert found["compare"] == [f"{base}..main"]
    assert found["node"] == ["local:repo"]
    assert "ref" not in found and "pr" not in found
    assert opened["url"] == out.strip()
    assert opened["url"] == build_compare_url(repo, f"{base}..main", "local:repo")
    assert _snapshot(repo) == before
    assert not (repo / ".cbi").exists()
    assert head == _head(repo)


def test_open_pr_resolves_with_gh_on_path(make_repo, monkeypatch, capsys, tmp_path):
    repo = make_repo({"README.md": "# app\n"})
    base, head = _second_commit(repo)
    monkeypatch.chdir(repo)
    before = _snapshot(repo)
    calls = tmp_path / "gh-args"
    _fake_gh(tmp_path, monkeypatch, f"""import pathlib, sys
pathlib.Path({str(calls)!r}).write_text("\\n".join(sys.argv[1:]) + "\\n", encoding="utf-8", newline="\\n")
sys.stdout.write('{{"baseRefOid":"{base}","headRefOid":"{head}"}}\\n')
""")
    code, out, err, opened = _open(monkeypatch, capsys, ["--pr", "2345"])
    assert code == 0 and err == ""
    found = _query(out.strip())
    assert found["compare"] == [f"{base}..{head}"]
    assert "pr" not in found
    assert opened["url"] == out.strip()
    assert calls.read_text().splitlines() == ["pr", "view", "2345", "--json", "baseRefOid,headRefOid"]
    assert _snapshot(repo) == before
    assert not (repo / ".cbi").exists()


def test_open_pr_shows_gh_failures_and_does_not_guess(make_repo, monkeypatch, capsys, tmp_path):
    repo = make_repo({"README.md": "# app\n"})
    base, _head_sha = _second_commit(repo)
    monkeypatch.chdir(repo)

    def boom(url):
        raise AssertionError(url)

    monkeypatch.setattr(open_link, "open_url", boom)
    _fake_gh(tmp_path, monkeypatch, """import sys
sys.stderr.write("no such pull request\\n")
raise SystemExit(1)
""")
    assert main(["open", "--pr", "2345"]) == 1
    failed = capsys.readouterr()
    assert failed.out == "" and "no such pull request" in failed.err

    _fake_gh(tmp_path, monkeypatch, f"""import sys
sys.stdout.write('{{"baseRefOid":"{base}"}}\\n')
""")
    assert main(["open", "--pr", "2345"]) == 1
    partial = capsys.readouterr()
    assert partial.out == "" and "baseRefOid and headRefOid" in partial.err

    _fake_gh(tmp_path, monkeypatch, """import sys
sys.stdout.write('{"baseRefOid":"main","headRefOid":"main"}\\n')
""")
    assert main(["open", "--pr", "2345"]) == 1
    named = capsys.readouterr()
    assert named.out == "" and "baseRefOid and headRefOid" in named.err
    assert not (repo / ".cbi").exists()


def test_open_compare_rejects_a_bad_shape_and_an_unknown_ref(make_repo, monkeypatch, capsys):
    repo = make_repo({"README.md": "# app\n"})
    monkeypatch.chdir(repo)

    def boom(url):
        raise AssertionError(url)

    monkeypatch.setattr(open_link, "open_url", boom)
    assert main(["open", "--compare", "main..no-such"]) == 1
    assert "unknown ref" in capsys.readouterr().err

    assert main(["open", "--compare", "main...feature"]) == 2
    assert "base..head" in capsys.readouterr().err

    assert main(["open", "--pr", "12;rm"]) == 2
    assert "pull request number" in capsys.readouterr().err

    assert main(["open", "--compare", "main..main", "--pr", "1"]) == 2
    assert "not both" in capsys.readouterr().err

    assert main(["open", "--compare", "main..main", "--branch", "main"]) == 2
    assert "not both" in capsys.readouterr().err
    assert not (repo / ".cbi").exists()


def test_version_flags_are_mutually_exclusive(make_repo, monkeypatch, capsys):
    repo = make_repo({"README.md": "# app\n"})
    monkeypatch.chdir(repo)
    with pytest.raises(SystemExit) as info:
        main(["open", "--branch", "main", "--commit", "abc"])
    assert info.value.code == 2


def test_missing_handler_prints_the_link_and_a_message(make_repo, monkeypatch, capsys):
    repo = make_repo({"README.md": "# app\n"})
    monkeypatch.chdir(repo)
    monkeypatch.setattr(open_link, "open_url", lambda url: (1, "No application knows how to open URL"))
    assert main(["open"]) == 1
    out = capsys.readouterr()
    assert out.out.strip().startswith("cbi://open?")
    assert NO_HANDLER in out.err


def test_open_uses_fixed_git_argv(make_repo, monkeypatch, capsys):
    repo = make_repo({"README.md": "# app\n"})
    monkeypatch.chdir(repo)
    calls = []
    real = subprocess.run

    def spy(*args, **kwargs):
        cmd = args[0] if args else kwargs.get("args")
        calls.append(list(cmd))
        if cmd and cmd[0] in {"open", "xdg-open", "cmd"}:
            raise AssertionError(cmd)
        return real(*args, **kwargs)

    monkeypatch.setattr(subprocess, "run", spy)
    code, _out, _err, _opened = _open(monkeypatch, capsys, ["--branch", "main"])
    assert code == 0
    git = [cmd for cmd in calls if cmd and cmd[0] == "git"]
    assert any(cmd[1:3] == ["rev-parse", "--verify"] for cmd in git)
    forbidden = {"checkout", "switch", "stash", "reset", "commit", "add", "merge", "rebase", "clean"}
    for cmd in git:
        assert cmd[1] not in forbidden
        assert cmd[1:3] != ["worktree", "add"]


class _Run:
    def __init__(self):
        self.returncode = 0
        self.stderr = ""
        self.stdout = ""


def test_open_url_uses_xdg_open_without_an_activation_token(monkeypatch):
    seen = {}
    monkeypatch.setenv("DESKTOP_STARTUP_ID", "steal")
    monkeypatch.setenv("XDG_ACTIVATION_TOKEN", "steal")

    def run(argv, **kwargs):
        seen["argv"] = argv
        seen["env"] = kwargs.get("env")
        return _Run()

    monkeypatch.setattr(open_link.sys, "platform", "linux")
    monkeypatch.setattr(open_link.subprocess, "run", run)
    assert open_link.open_url("cbi://open?repo=/tmp/r") == (0, "")
    assert seen["argv"] == ["xdg-open", "cbi://open?repo=/tmp/r"]
    assert "DESKTOP_STARTUP_ID" not in seen["env"]
    assert "XDG_ACTIVATION_TOKEN" not in seen["env"]
    assert seen["env"]["PATH"] == os.environ["PATH"]


def _install_shell32(monkeypatch, execute):
    class Shell32:
        ShellExecuteW = staticmethod(execute)

    class Windll:
        shell32 = Shell32()

    monkeypatch.setattr(open_link.ctypes, "windll", Windll(), raising=False)


def test_open_url_does_not_activate_on_windows(monkeypatch):
    monkeypatch.setattr(open_link.sys, "platform", "win32")
    calls = []

    def execute(*args):
        calls.append(args)
        return 42

    _install_shell32(monkeypatch, execute)
    assert open_link.open_url("cbi://open?repo=C:/src") == (0, "")
    assert calls == [(None, "open", "cbi://open?repo=C:/src", None, None, open_link.SW_SHOWNOACTIVATE)]


def test_open_url_shell_execute_error_is_a_failure(monkeypatch):
    monkeypatch.setattr(open_link.sys, "platform", "win32")

    def execute(*_args):
        return 2

    _install_shell32(monkeypatch, execute)
    code, detail = open_link.open_url("cbi://open?repo=C:/src")
    assert code == 1
    assert "ShellExecute failed (2)" in detail


def test_open_url_falls_back_to_start_when_shell32_is_missing(monkeypatch):
    monkeypatch.setattr(open_link.sys, "platform", "win32")
    monkeypatch.setattr(open_link.ctypes, "windll", None, raising=False)
    seen = {}

    def run(argv, **_kwargs):
        seen["argv"] = argv
        return _Run()

    monkeypatch.setattr(open_link.subprocess, "run", run)
    assert open_link.open_url("cbi://x") == (0, "")
    assert seen["argv"] == ["cmd", "/c", "start", "", "cbi://x"]


def test_open_url_uses_open_g_on_macos(monkeypatch):
    seen = {}

    def run(argv, **_kwargs):
        seen["argv"] = argv
        return _Run()

    monkeypatch.setattr(open_link.sys, "platform", "darwin")
    monkeypatch.setattr(open_link.subprocess, "run", run)
    assert open_link.open_url("cbi://open?repo=/tmp/r") == (0, "")
    assert seen["argv"] == ["open", "-g", "cbi://open?repo=/tmp/r"]

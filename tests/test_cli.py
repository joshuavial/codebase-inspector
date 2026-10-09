import io
import json
import subprocess
from pathlib import Path

import pytest

import cbi.cli as cli
from cbi.cli import COMMANDS, main


def test_version_matches_the_package(capsys):
    text = (Path(__file__).parents[1] / "pyproject.toml").read_text()
    assert 'version = "0.1.0"' in text
    app = json.loads((Path(__file__).parents[1] / "app" / "package.json").read_text())
    assert app["version"] == "0.1.0"
    with pytest.raises(SystemExit) as caught:
        main(["--version"])
    assert caught.value.code == 0
    assert capsys.readouterr().out.strip() == "cbi 0.1.0"


def test_help_lists_every_command(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["--help"])
    assert exit_info.value.code == 0
    out = capsys.readouterr().out
    for name in COMMANDS:
        assert name in out


def test_windows_redirected_output_uses_utf8(monkeypatch):
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="cp1252")
    with monkeypatch.context() as patch:
        patch.setattr(cli.sys, "platform", "win32")
        patch.setattr(cli.sys, "stdout", stream)
        patch.setattr(cli, "_main", lambda _argv: print("left → right") or 0)
        assert cli.main([]) == 0
        stream.flush()
    assert raw.getvalue().decode("utf-8") == "left → right\n"


def test_prime_prints_not_initialised_guide(make_repo, monkeypatch, capsys):
    repo = make_repo({"src/app.ts": "export const x = 1;\n", "README.md": "# app\n"})
    monkeypatch.chdir(repo)
    assert main(["prime"]) == 0
    out = capsys.readouterr().out
    assert "cbi init" in out and "cbi scan" in out
    assert "--out DIR" in out and "must stay untouched" in out
    assert len(out.splitlines()) < 60
    assert not (repo / ".cbi").exists()


def test_make_repo_commits_files(make_repo):
    repo = make_repo({"a.py": "x = 1\n", "pkg/b.py": "y = 2\n"})
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.split()
    assert tracked == ["a.py", "pkg/b.py"]
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout
    assert status == ""

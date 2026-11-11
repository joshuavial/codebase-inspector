import io
import json
from pathlib import Path

import pytest

import cbi.cli as cli
from cbi import files
from cbi.cli import COMMANDS, main


def test_version_matches_the_package(capsys):
    text = (Path(__file__).parents[1] / "pyproject.toml").read_text()
    assert 'version = "0.5.0"' in text
    app = json.loads((Path(__file__).parents[1] / "app" / "package.json").read_text())
    assert app["version"] == "0.5.0"
    with pytest.raises(SystemExit) as caught:
        main(["--version"])
    assert caught.value.code == 0
    assert capsys.readouterr().out.strip() == "cbi 0.5.0"


def test_help_lists_every_command(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["--help"])
    assert exit_info.value.code == 0
    out = capsys.readouterr().out
    for name in COMMANDS:
        assert name in out


def test_windows_redirected_output_uses_utf8(monkeypatch):
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="cp1252", newline="\n")
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
    tracked = files._git(repo, "ls-files").decode().split()
    assert tracked == ["a.py", "pkg/b.py"]
    status = files._git(repo, "status", "--porcelain").decode()
    assert status == ""


def test_query_schema(make_repo, monkeypatch, capsys):
    repo = make_repo({"a.py": "x = 1\n"})
    monkeypatch.chdir(repo)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    assert main(["query", "--schema"]) == 0
    out = capsys.readouterr().out
    assert "Model Schema:" in out
    assert "nodes" in out and "edges" in out

    assert main(["query", "--schema", "--json"]) == 0
    out_json = capsys.readouterr().out
    data = json.loads(out_json)
    assert "nodes" in data and "edges" in data


def test_query_select(make_repo, monkeypatch, capsys):
    repo = make_repo({"a.py": "def foo(): pass\n"})
    monkeypatch.chdir(repo)
    assert main(["init"]) == 0 and main(["scan"]) == 0

    # Text format
    assert main(["query", "SELECT id, kind, name FROM nodes WHERE kind = 'symbol'"]) == 0
    out = capsys.readouterr().out
    assert "foo" in out
    assert "id" in out and "kind" in out

    # JSON format
    assert main(["query", "SELECT id, kind, name FROM nodes WHERE kind = 'symbol'", "--json"]) == 0
    out_json = capsys.readouterr().out
    payload = json.loads(out_json)
    assert payload["row_count"] >= 1
    assert any(r["name"] == "foo" for r in payload["rows"])


def test_query_disallows_writes_and_missing_sql(make_repo, monkeypatch, capsys):
    repo = make_repo({"a.py": "x = 1\n"})
    monkeypatch.chdir(repo)
    assert main(["init"]) == 0 and main(["scan"]) == 0

    # Missing SQL argument
    assert main(["query"]) == 2
    err = capsys.readouterr().err
    assert "provide a SQL statement" in err

    # Non-read query
    assert main(["query", "INSERT INTO nodes (id) VALUES ('x')"]) == 1
    err_insert = capsys.readouterr().err
    assert "only read-only queries are permitted" in err_insert


def test_prime_in_non_git_directory(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["prime"]) == 0
    out = capsys.readouterr().out
    assert "Not inside a git repository" in out
    assert "git init" in out


def test_missing_model_error_mentions_scan_and_preserves_out(make_repo, monkeypatch, capsys, tmp_path):
    repo = make_repo({"a.py": "x = 1\n"})
    monkeypatch.chdir(repo)
    # Reader without model mentions cbi scan
    assert main(["context"]) == 1
    err = capsys.readouterr().err
    assert "no model at" in err and "Run `cbi scan` first." in err

    # Reader with --out mentions cbi scan --out
    custom_out = tmp_path / "custom-out"
    assert main(["context", "--out", str(custom_out)]) == 1
    err_out = capsys.readouterr().err
    assert f"Run `cbi scan --out {custom_out}` first." in err_out


def test_cli_json_flags():
    parser = cli.build_parser()

    args_diff = parser.parse_args(["diff", "--json"])
    assert args_diff.json is True

    args_history = parser.parse_args(["history", "--json"])
    assert args_history.json is True

    args_review = parser.parse_args(["review", "HEAD", "--json"])
    assert args_review.json is True

    args_check = parser.parse_args(["check", "--json"])
    assert args_check.json is True

    args_check_fmt = parser.parse_args(["check", "--format", "json"])
    assert args_check_fmt.format == "json"


def test_deps_argument_aliases():
    parser = cli.build_parser()

    args_from_to = parser.parse_args(["deps", "--from", "src", "--to", "core"])
    assert args_from_to.start == "src"
    assert args_from_to.end == "core"

    args_start_end = parser.parse_args(["deps", "--start", "src", "--end", "core"])
    assert args_start_end.start == "src"
    assert args_start_end.end == "core"


def test_deps_start_end_aliases_match_from_to(make_repo, monkeypatch, capsys):
    files = {
        "package.json": json.dumps({"name": "root"}),
        "src/a.ts": "import { b } from '../lib/b';\nexport const a = b;\n",
        "lib/b.ts": "export const b = 1;\n",
    }
    repo = make_repo(files)
    monkeypatch.chdir(repo)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    capsys.readouterr()

    # Query with --from and --to
    assert main(["deps", "--level", "folder", "--from", "src", "--to", "lib", "--json"]) == 0
    out_from_to = capsys.readouterr().out
    data_from_to = json.loads(out_from_to)

    # Query with --start and --end aliases
    assert main(["deps", "--level", "folder", "--start", "src", "--end", "lib", "--json"]) == 0
    out_start_end = capsys.readouterr().out
    data_start_end = json.loads(out_start_end)

    assert data_start_end == data_from_to
    assert len(data_start_end["edges"]) == 1
    assert data_start_end["edges"][0]["from"] == "src"
    assert data_start_end["edges"][0]["to"] == "lib"

    # Text mode produces identical output
    assert main(["deps", "--level", "folder", "--from", "src", "--to", "lib"]) == 0
    text_from_to = capsys.readouterr().out
    assert main(["deps", "--level", "folder", "--start", "src", "--end", "lib"]) == 0
    text_start_end = capsys.readouterr().out
    assert text_start_end == text_from_to


def test_hotspots_argument_aliases():
    parser = cli.build_parser()

    args_by = parser.parse_args(["hotspots", "--by", "loc"])
    assert args_by.by == "loc"

    args_metric = parser.parse_args(["hotspots", "--metric", "loc"])
    assert args_metric.by == "loc"


def test_hotspots_metric_alias_matches_by(make_repo, monkeypatch, capsys):
    files = {
        "a.py": "x = 1\n",
        "b.py": "import a\ny = 2\n",
    }
    repo = make_repo(files)
    monkeypatch.chdir(repo)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    capsys.readouterr()

    # JSON format: --by loc vs --metric loc
    assert main(["hotspots", "--by", "loc", "--json"]) == 0
    out_by_json = capsys.readouterr().out
    data_by_json = json.loads(out_by_json)

    assert main(["hotspots", "--metric", "loc", "--json"]) == 0
    out_metric_json = capsys.readouterr().out
    data_metric_json = json.loads(out_metric_json)

    assert data_metric_json == data_by_json
    assert data_metric_json["by"] == "loc"

    # Text format: --by loc vs --metric loc
    assert main(["hotspots", "--by", "loc"]) == 0
    text_by = capsys.readouterr().out

    assert main(["hotspots", "--metric", "loc"]) == 0
    text_metric = capsys.readouterr().out

    assert text_metric == text_by
    assert "by loc" in text_metric





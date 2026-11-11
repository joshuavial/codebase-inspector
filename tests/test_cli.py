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

    args_scan = parser.parse_args(["scan", "--json"])
    assert args_scan.json is True

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


def test_scan_json_output(make_repo, monkeypatch, capsys):
    files = {
        "a.py": "def foo(): pass\n",
        "b.py": "class Bar:\n    pass\n",
    }
    repo = make_repo(files)
    monkeypatch.chdir(repo)
    assert main(["init"]) == 0
    capsys.readouterr()

    # 1. cbi scan --json produces valid JSON parseable by json.loads with required fields
    assert main(["scan", "--json"]) == 0
    out_json = capsys.readouterr().out
    data = json.loads(out_json)
    assert data["ref"] is None
    assert data["shortcut"] is False
    assert isinstance(data["counts"], dict)
    assert "source file" in data["counts"]
    assert "open_tasks" in data and isinstance(data["open_tasks"], int)
    assert "blocked_tasks" in data and isinstance(data["blocked_tasks"], int)
    assert "elapsed_seconds" in data and isinstance(data["elapsed_seconds"], float)
    assert "excluded_executables" in data and isinstance(data["excluded_executables"], int)

    # Subsequent scan should hit shortcut
    assert main(["scan", "--json"]) == 0
    data_shortcut = json.loads(capsys.readouterr().out)
    assert data_shortcut["shortcut"] is True
    assert data_shortcut["ref"] is None

    # 2. cbi scan --ref HEAD --json emits resolved SHA and counts
    assert main(["scan", "--ref", "HEAD", "--json"]) == 0
    out_ref = capsys.readouterr().out
    data_ref = json.loads(out_ref)
    assert data_ref["ref"] is not None and len(data_ref["ref"]) == 40
    assert isinstance(data_ref["shortcut"], bool)
    assert isinstance(data_ref["counts"], dict)
    assert "source file" in data_ref["counts"]
    assert "open_tasks" in data_ref and isinstance(data_ref["open_tasks"], int)
    assert "blocked_tasks" in data_ref and isinstance(data_ref["blocked_tasks"], int)
    assert "elapsed_seconds" in data_ref and isinstance(data_ref["elapsed_seconds"], float)

    # 3. cbi scan without --json preserves existing human-readable text output
    assert main(["scan"]) == 0
    out_text = capsys.readouterr().out
    assert "Excluded tracked executable files:" in out_text
    assert ("scanned in" in out_text) or ("no changes since the last scan in" in out_text)
    assert "judgement tasks" in out_text

    assert main(["scan", "--ref", "HEAD"]) == 0
    out_ref_text = capsys.readouterr().out
    assert len(out_ref_text.splitlines()[0]) == 40
    assert "judgement tasks" in out_ref_text


def test_layers_and_dead_help(capsys):
    parser = cli.build_parser()
    subparsers_action = [a for a in parser._actions if a.__class__.__name__ == "_SubParsersAction"][0]

    # Verify options parity between layers and deps
    deps_sub = subparsers_action.choices["deps"]
    layers_sub = subparsers_action.choices["layers"]
    deps_opts = {opt for a in deps_sub._actions for opt in a.option_strings}
    layers_opts = {opt for a in layers_sub._actions for opt in a.option_strings}
    assert layers_opts == deps_opts
    for expected in ("--level", "--from", "--start", "--to", "--end", "--forbid", "--include-tests", "--out", "--ref", "--json"):
        assert expected in layers_opts

    # Verify options parity between dead and orphans
    orphans_sub = subparsers_action.choices["orphans"]
    dead_sub = subparsers_action.choices["dead"]
    orphans_opts = {opt for a in orphans_sub._actions for opt in a.option_strings}
    dead_opts = {opt for a in dead_sub._actions for opt in a.option_strings}
    assert dead_opts == orphans_opts
    for expected in ("--fail", "--out", "--ref", "--json"):
        assert expected in dead_opts

    # Test --help execution for layers and deps
    with pytest.raises(SystemExit) as exc_layers:
        main(["layers", "--help"])
    assert exc_layers.value.code == 0
    out_layers = capsys.readouterr().out
    assert "--level" in out_layers and "--forbid" in out_layers and "--json" in out_layers

    with pytest.raises(SystemExit) as exc_deps:
        main(["deps", "--help"])
    assert exc_deps.value.code == 0
    out_deps = capsys.readouterr().out
    assert "--level" in out_deps and "--forbid" in out_deps and "--json" in out_deps

    # Test --help execution for dead and orphans
    with pytest.raises(SystemExit) as exc_dead:
        main(["dead", "--help"])
    assert exc_dead.value.code == 0
    out_dead = capsys.readouterr().out
    assert "--fail" in out_dead and "--json" in out_dead

    with pytest.raises(SystemExit) as exc_orphans:
        main(["orphans", "--help"])
    assert exc_orphans.value.code == 0
    out_orphans = capsys.readouterr().out
    assert "--fail" in out_orphans and "--json" in out_orphans


def test_layers_matches_deps_json_and_forbid(make_repo, monkeypatch, capsys):
    files = {
        "package.json": json.dumps({"name": "root"}),
        "src/a.ts": "import { b } from '../lib/b';\nexport const a = b;\n",
        "lib/b.ts": "export const b = 1;\n",
    }
    repo = make_repo(files)
    monkeypatch.chdir(repo)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    capsys.readouterr()

    # 1. cbi layers --json matches cbi deps --json
    assert main(["layers", "--json"]) == 0
    out_layers_json = capsys.readouterr().out
    assert main(["deps", "--json"]) == 0
    out_deps_json = capsys.readouterr().out
    assert json.loads(out_layers_json) == json.loads(out_deps_json)

    # 2. --level folder with --json matches
    assert main(["layers", "--level", "folder", "--json"]) == 0
    out_layers_folder = capsys.readouterr().out
    assert main(["deps", "--level", "folder", "--json"]) == 0
    out_deps_folder = capsys.readouterr().out
    assert json.loads(out_layers_folder) == json.loads(out_deps_folder)

    # 3. Text output matches
    assert main(["layers", "--level", "folder"]) == 0
    text_layers = capsys.readouterr().out
    assert main(["deps", "--level", "folder"]) == 0
    text_deps = capsys.readouterr().out
    assert text_layers == text_deps

    # 4. --forbid passes when no forbidden imports exist
    assert main(["layers", "--level", "folder", "--forbid", "lib:src"]) == 0
    out_layers_ok = capsys.readouterr().out
    assert main(["deps", "--level", "folder", "--forbid", "lib:src"]) == 0
    out_deps_ok = capsys.readouterr().out
    assert out_layers_ok == out_deps_ok

    # 5. --forbid fails (exits 1) identically when forbidden imports exist
    assert main(["layers", "--level", "folder", "--forbid", "src:lib"]) == 1
    out_layers_fail = capsys.readouterr().out
    assert main(["deps", "--level", "folder", "--forbid", "src:lib"]) == 1
    out_deps_fail = capsys.readouterr().out
    assert out_layers_fail == out_deps_fail
    assert "src/a.ts → lib/b.ts" in out_layers_fail

    # 6. --forbid with --json fails identically
    assert main(["layers", "--level", "folder", "--forbid", "src:lib", "--json"]) == 1
    out_layers_fail_json = capsys.readouterr().out
    assert main(["deps", "--level", "folder", "--forbid", "src:lib", "--json"]) == 1
    out_deps_fail_json = capsys.readouterr().out
    assert json.loads(out_layers_fail_json) == json.loads(out_deps_fail_json)


def test_dead_matches_orphans_json_and_fail(make_repo, monkeypatch, capsys):
    repo_files = {
        "package.json": json.dumps({"name": "app", "main": "src/main.ts"}),
        "src/main.ts": "import { helper } from './helper';\nexport const x = helper;\n",
        "src/helper.ts": "export const helper = 42;\n",
    }
    repo = make_repo(repo_files)
    monkeypatch.chdir(repo)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    capsys.readouterr()

    # 1. cbi dead --json matches cbi orphans --json on clean code
    assert main(["dead", "--json"]) == 0
    out_dead_json = capsys.readouterr().out
    assert main(["orphans", "--json"]) == 0
    out_orphans_json = capsys.readouterr().out
    assert json.loads(out_dead_json) == json.loads(out_orphans_json)
    assert json.loads(out_dead_json)["passed"] is True

    # 2. Text output matches on clean code
    assert main(["dead"]) == 0
    text_dead = capsys.readouterr().out
    assert main(["orphans"]) == 0
    text_orphans = capsys.readouterr().out
    assert text_dead == text_orphans

    # 3. cbi dead --fail exits 0 on clean code
    assert main(["dead", "--fail"]) == 0
    out_dead_fail = capsys.readouterr().out
    assert main(["orphans", "--fail"]) == 0
    out_orphans_fail = capsys.readouterr().out
    assert out_dead_fail == out_orphans_fail
    assert "production code with no production importer or caller:\n  none" in out_dead_fail

    assert main(["dead", "--fail", "--json"]) == 0
    out_dead_fail_json = capsys.readouterr().out
    assert main(["orphans", "--fail", "--json"]) == 0
    out_orphans_fail_json = capsys.readouterr().out
    assert json.loads(out_dead_fail_json) == json.loads(out_orphans_fail_json)

    # 4. Introduce an orphaned production file
    (repo / "src" / "orphan.ts").write_text("export const unused = 100;\n")
    files._git(repo, "add", "-A")
    assert main(["scan"]) == 0
    capsys.readouterr()

    # 5. cbi dead --fail exits 1 on orphans
    assert main(["dead", "--fail"]) == 1
    err_dead = capsys.readouterr().out
    assert main(["orphans", "--fail"]) == 1
    err_orphans = capsys.readouterr().out
    assert err_dead == err_orphans
    assert "src/orphan.ts" in err_dead

    # 6. cbi dead --fail --json exits 1 on orphans and emits identical JSON
    assert main(["dead", "--fail", "--json"]) == 1
    err_dead_json = capsys.readouterr().out
    assert main(["orphans", "--fail", "--json"]) == 1
    err_orphans_json = capsys.readouterr().out
    assert json.loads(err_dead_json) == json.loads(err_orphans_json)
    data = json.loads(err_dead_json)
    assert data["passed"] is False
    assert any(item["path"] == "src/orphan.ts" for item in data["unreferenced"])

    # 7. Without --fail, exits 0 for backwards compatibility
    assert main(["dead", "--json"]) == 0
    capsys.readouterr()
    assert main(["orphans", "--json"]) == 0
    capsys.readouterr()







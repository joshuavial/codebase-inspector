"""Agent guide: prime in each state, the shared task count, and a closed stdout pipe."""

import json
import os
import shlex
import sqlite3
import subprocess
import sys

from cbi import prime, store
from cbi.cli import main


def run(capsys, *argv):
    capsys.readouterr()
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_prime_with_out_names_that_directory(make_repo, monkeypatch, tmp_path, capsys):
    root = make_repo({"a.ts": "export const x = 1;\n"}, name="outside")
    monkeypatch.chdir(root)
    model = tmp_path / "model"
    assert main(["init", "--out", str(model)]) == 0
    assert main(["scan", "--out", str(model)]) == 0
    assert not (root / ".cbi").exists()
    code, out, err = run(capsys, "prime", "--out", str(model))
    assert code == 0, err
    flag = "--out " + shlex.quote(str(model.resolve()))
    assert flag in out
    assert f"cbi tasks {flag}" in out and f"cbi submit" in out
    assert f"Run `cbi build {flag}` after every five" in out
    assert prime.OUT_NOTE in out

    conn = store.open_db(model / "model.db")
    try:
        given = prime.complete_guide(conn, root, model, " --out " + shlex.quote(str(model.resolve())))
        own = prime.complete_guide(conn, root, model, "")
    finally:
        conn.close()
    assert prime.OUT_NOTE in given and flag in given
    assert prime.OUT_NOTE not in own and "--out " not in own

    db = sqlite3.connect(model / "model.db")
    open_n, blocked_n = db.execute(
        "SELECT coalesce(sum(state = 'open'), 0), coalesce(sum(state = 'blocked'), 0) FROM tasks"
    ).fetchone()
    headline = f"{int(open_n)} judgement tasks open, {int(blocked_n)} blocked"
    code, scan_out, err = run(capsys, "scan", "--out", str(model))
    assert code == 0, err
    assert scan_out.rstrip().endswith(headline + "; run `cbi tasks`")
    assert f"## {headline}" in out


def test_prime_prints_commands_for_detected_runners(make_repo, monkeypatch, capsys):
    package = {
        "scripts": {
            "test:service": "tsc -p service/tsconfig.test.json && cross-env NODE_ENV=test "
                            'node --test "dist-service-test/service/**/*.test.js"',
        },
        "devDependencies": {"vitest": "1.0.0"},
    }
    root = make_repo({
        "package.json": json.dumps(package),
        "pyproject.toml": '[project]\nname = "demo"\n\n[dependency-groups]\ndev = ["pytest"]\n',
        "service/a.ts": "export const a = 1;\n",
    }, name="runners")
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    code, out, err = run(capsys, "prime")
    assert code == 0, err
    assert "node:test (package.json):" in out
    assert "vitest (package.json):" in out
    assert "pytest (pyproject.toml):" in out
    assert "service/tsconfig.test.json" in out and "NODE_ENV=test" in out
    assert 'coverage json --show-contexts -o "$OUT/coverage.json"' in out
    assert "npx vitest run --coverage" in out
    assert "ln -s" not in out and "mobile-shell" not in out


def _closed_stdout(argv, cwd):
    """Run cbi with stdout already a pipe whose read end is closed."""
    read_fd, write_fd = os.pipe()
    os.close(read_fd)
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    proc = subprocess.Popen(
        [sys.executable, "-c",
         "import sys; from cbi.cli import main; raise SystemExit(main(sys.argv[1:]))",
         *argv],
        cwd=cwd, env=env, stdout=write_fd, stderr=subprocess.PIPE,
    )
    os.close(write_fd)
    _out, err = proc.communicate(timeout=30)
    return proc.returncode, err.decode()


def test_closed_pipe_exits_quietly(make_repo, monkeypatch, capsys):
    root = make_repo({
        "a.ts": "export function a() { return 1; }\n",
        "a.test.ts": "import { a } from './a';\ntest('a', () => { a(); });\n",
    }, name="pipe")
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    task_id = sqlite3.connect(root / ".cbi" / "model.db").execute(
        "SELECT id FROM tasks WHERE state = 'open' ORDER BY id LIMIT 1"
    ).fetchone()[0]
    for argv in (["task", task_id], ["orphans"]):
        code, err = _closed_stdout(argv, root)
        assert code == 0, err
        assert "Traceback" not in err and "BrokenPipeError" not in err
    code, out, err = run(capsys, "task", task_id)
    assert code == 0 and task_id in out and err == ""
    code, out, err = run(capsys, "orphans")
    assert code == 0 and "production code" in out and err == ""

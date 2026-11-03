"""Target text uses UTF-8 even when the host defaults to a Windows code page."""

import builtins
import json
from pathlib import Path

import pytest

from cbi import ingest, manifests, store, tasks, team
from cbi.cli import main


@pytest.fixture
def windows_default(make_repo, monkeypatch):
    root = make_repo({
        "package.json": '{"name":"māori-demo","main":"src/main.ts"}',
        "pyproject.toml": '[project]\nname = "māori-demo"\nversion = "1.0"\n',
        "tsconfig.json": '{"compilerOptions":{"baseUrl":".","paths":{"@demo/*":["src/*"]}},"description":"māori"}',
        "src/main.ts": 'import { value } from "@demo/value";\nexport const main = value;\n',
        "src/value.ts": 'export const value = "māori";\n',
        "README.md": "# Māori demo\n",
        "coverage.json": json.dumps({"meta": {"format": 3, "version": "māori"}, "files": {"src/main.ts": {"executed_lines": [1]}}}, ensure_ascii=False),
    })
    real_path_open, real_open = Path.open, builtins.open

    def path_open(path, mode="r", buffering=-1, encoding=None, errors=None, newline=None):
        if "b" not in mode and encoding in (None, "locale") and path.is_relative_to(root):
            encoding = "cp1252"
        return real_path_open(path, mode, buffering, encoding, errors, newline)

    def file_open(file, mode="r", buffering=-1, encoding=None, errors=None, newline=None, **kwargs):
        if isinstance(file, (str, Path)) and "b" not in mode and encoding in (None, "locale") and Path(file).is_relative_to(root):
            encoding = "cp1252"
        return real_open(file, mode, buffering, encoding, errors, newline, **kwargs)

    monkeypatch.setattr(Path, "open", path_open)
    monkeypatch.setattr(builtins, "open", file_open)
    monkeypatch.chdir(root)
    return root


def test_scan_and_manifest_reads_ignore_windows_default(windows_default, capsys):
    root = windows_default
    assert main(["init"]) == 0
    assert main(["scan"]) == 0
    ws = manifests._Workspace("demo", "demo", root, [])
    assert ws.json("package.json")["name"] == "māori-demo"
    assert ws.toml("pyproject.toml")["project"]["name"] == "māori-demo"
    assert ws.text("README.md") == "# Māori demo\n"
    conn = store.open_db(root / ".cbi" / "model.db")
    try:
        assert conn.execute("SELECT 1 FROM edges WHERE kind = 'imports'").fetchone()
        result = ingest.ingest(conn, root, root, root / "coverage.json")
        assert result["files"] == 1
        [task_id] = conn.execute("SELECT id FROM tasks WHERE kind = 'summarise-workspace'").fetchone()
        brief = tasks.brief(conn, task_id, root)
        assert "Māori" in brief["readme"]["head"]
        (root / "README.md").write_bytes(b"# Demo\xff\n")
        assert "\ufffd" in tasks.brief(conn, task_id, root)["readme"]["head"]
    finally:
        conn.close()


def test_invalid_utf8_artifact_has_actionable_error(windows_default, capsys):
    root = windows_default
    assert main(["init"]) == 0
    assert main(["scan"]) == 0
    artifact = root / "coverage.json"
    artifact.write_bytes(b'{"invalid": "\xff"}')
    assert main(["ingest", str(artifact)]) == 2
    assert "'utf-8' codec can't decode byte" in capsys.readouterr().err
    (root / ".cbi" / "ignore").write_bytes(b"# invalid \xff\n")
    assert main(["scan"]) == 1
    assert "Save the file with UTF-8 encoding" in capsys.readouterr().err


@pytest.mark.parametrize("summary", ["A café service.", "A Māori service."])
def test_team_answers_round_trip_with_windows_text_defaults(windows_default, summary):
    out = windows_default / ".cbi"
    out.mkdir()
    key = ("summarise-workspace", "reviewed-input")
    row = team._canon(*key, tasks.PROTOCOL_VERSION, {"summary": summary})
    path, count, changed = team._store(out, {key: row})
    assert count == 1 and changed
    assert summary.encode("utf-8") in path.read_bytes()
    assert team._parse(path.read_text(encoding="utf-8"))[key] == row
    assert team._store(out, {key: row}) == (path, 1, False)
    (out / "team.toml").write_text(team.TEMPLATE, encoding="utf-8")
    conn = store.open_db(out / "model.db")
    try:
        tasks.attach_cache(conn)
        assert team.import_answers(conn, out) == 1
        [answer] = conn.execute("SELECT answer FROM cache.summary_answers WHERE input_hash = ?", (key[1],)).fetchone()
        assert json.loads(answer) == {"summary": summary}
    finally:
        conn.close()

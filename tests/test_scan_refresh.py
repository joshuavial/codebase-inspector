"""Judgement refreshes reuse mechanical facts but still update summaries and search."""
import json

from cbi import cli, progress, resolve, store, tasks
from test_parts import run_json


def test_answer_only_refresh_preserves_mechanical_relationships(make_repo, monkeypatch, capsys):
    root = make_repo({"src/a.py": "from .b import helper\nvalue = helper()\n",
                      "src/b.py": "def helper():\n    return 1\n"})
    monkeypatch.chdir(root)
    assert cli.main(["init"]) == cli.main(["scan"]) == cli.main(["team", "init"]) == 0
    conn = store.open_db(root / ".cbi/model.db")
    before = conn.execute("SELECT * FROM edges WHERE source = 'treesitter' ORDER BY src, dst, kind").fetchall()
    digest = conn.execute("SELECT content_hash FROM nodes WHERE path = 'src/b.py'").fetchone()[0]
    conn.close()
    # Team initialization adds scan exclusions; establish that mechanical baseline.
    assert cli.main(["scan"]) == 0
    def unexpected(*args, **kwargs):
        raise AssertionError("unchanged mechanical relationships were rebuilt")
    monkeypatch.setattr(resolve, "resolve", unexpected)
    path = root / ".cbi/answers.jsonl"
    from cbi import team
    record = team._canon(team.FILE_KIND, digest, tasks.PROTOCOL_VERSION, "Returns the default value.")
    path.write_text(json.dumps(record) + "\n")
    assert cli.main(["scan"]) == 0
    conn = store.open_db(root / ".cbi/model.db")
    assert conn.execute("SELECT * FROM edges WHERE source = 'treesitter' ORDER BY src, dst, kind").fetchall() == before
    assert conn.execute("SELECT summary FROM nodes WHERE path = 'src/b.py'").fetchone()[0] == "Returns the default value."
    conn.close()
    assert run_json(capsys, "search", "default")


def test_scan_progress_uses_stderr(make_repo, monkeypatch, capsys):
    monkeypatch.setattr(progress.Progress, "MIN_SECONDS", 0)
    root = make_repo({"a.py": "value = 1\n", "b.py": "value = 2\n"})
    monkeypatch.chdir(root)
    assert cli.main(["init"]) == 0
    capsys.readouterr()
    assert cli.main(["scan"]) == 0
    output = capsys.readouterr()
    assert "enumerate" in output.err and "parse" in output.err and "resolve" in output.err
    assert "2/2" in output.err
    assert "[scan" not in output.out

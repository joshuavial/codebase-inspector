"""Guards for the hotspots found on sample-monorepo and sample-saas (docs/acceptance/v0.1-scale.md)."""

import re
import subprocess
import time

from cbi import context, data, history, parse, store
from cbi.cli import main
from cbi.parse import python


def test_find_words_matches_the_regex_it_replaced():
    cases = [
        ("export function  run(a,\n  b) {", "function run(a, b)"),
        ("def f(x):\n    return x", "def f(x):"),
        ("class A { def f(x) }", "def f(x)"),
        ("ab ab  c", "ab c"),
        ("nothing here", "def g()"),
        ("", "x"),
        ("tail word", ""),
    ]
    for text, signature in cases:
        words = signature.split()
        match = re.search(r"\s*".join(re.escape(w) for w in words), text) if words else None
        assert parse._find_words(text, words) == (match.span() if match else None), (text, signature)


def test_string_literals_skip_comments_and_count_lines():
    text = (
        'a = "x\\\ny"  # "not a literal"\n'
        "q = '''SELECT * FROM t'''\n"
        "/* 'skip'\n */ s = `tick\\` + \"tail\\"
    )
    assert list(data._string_literals(text)) == [
        ("x\\\ny", 1), ("SELECT * FROM t", 3), ("tick\\", 5), ("tail\\", 5)]
    masked = data._without_comments(text)
    assert len(masked) == len(text) and masked.count("\n") == text.count("\n")
    assert '"not a literal"' not in masked and "'skip'" not in masked and '"x\\\ny"' in masked


def test_uses_are_not_searched_without_tables(make_repo, monkeypatch, capsys):
    root = make_repo({"app.py": 'def f(db):\n    return db.execute("SELECT * FROM users")\n'})
    monkeypatch.chdir(root)

    def boom(*_args):
        raise AssertionError("parse_uses ran with no tables")

    monkeypatch.setattr(data, "parse_uses", boom)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    capsys.readouterr()


def test_env_read_walks_parents_only_for_calls_and_subscripts(monkeypatch):
    calls = []
    real = python._py_written
    monkeypatch.setattr(python, "_py_written", lambda node: calls.append(node.type) or real(node))
    source = b"import os\n\ndef f(a, b):\n    x = a + b * 2\n    return os.environ.get('HOME', x)\n"
    parse.symbol_nodes("w:m.py", "w", "m.py", "python", source, False)
    assert calls and set(calls) <= {"call", "subscript"}


def test_test_counts_use_an_index(tmp_path):
    conn = store.open_db(tmp_path / "model.db")
    nodes = [("f", "file", "f.py")] + [(f"f#C{i}", "symbol", "f.py") for i in range(3000)]
    conn.executemany(
        "INSERT INTO nodes (id, kind, display_kind, name, path) VALUES (?, ?, ?, ?, ?)",
        [(nid, kind, kind, nid, path) for nid, kind, path in nodes])
    edges = [(f"t#{i}", f"f#C{i % 3000}.m{i}", "tests", "treesitter", 1.0) for i in range(30000)]
    edges += [("t#a", "f#C1", "tests", "naming", 0.8), ("t#low", "f#C1", "tests", "naming", 0.1),
              ("t#file", "f", "tests", "naming", 0.8)]
    conn.executemany("INSERT INTO edges (src, dst, kind, source, confidence) VALUES (?, ?, ?, ?, ?)", edges)
    facts = context._facts(conn)
    started = time.perf_counter()
    counts = {nid: context._test_count({"id": nid, "kind": kind}, facts) for nid, kind, _path in nodes}
    # Scanning every test edge per node took tens of seconds at this size.
    assert time.perf_counter() - started < 2
    assert counts["f#C1"] == 11  # ten on its methods, t#a on itself; not t#low, not C10..C19's tests
    assert counts["f#C10"] == 10
    assert counts["f"] == 1
    conn.close()


def test_diff_parses_only_changed_files_for_the_head(make_repo, monkeypatch, capsys):
    root = make_repo({f"m{i}.py": f"def f{i}():\n    return {i}\n" for i in range(6)})
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false"]
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True).stdout.strip()
    (root / "m0.py").write_text("def f0():\n    return 10\n")
    subprocess.run([*git, "commit", "-qam", "change"], cwd=root, check=True)
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    parsed = []
    real = parse.symbol_nodes
    monkeypatch.setattr(parse, "symbol_nodes", lambda fid, *rest: parsed.append(fid) or real(fid, *rest))
    assert main(["diff", base, "HEAD"]) == 0
    capsys.readouterr()
    assert len(parsed) == 7  # six for the base, then only m0.py for the head


def test_ref_scans_reuse_table_work_for_unchanged_files(make_repo, monkeypatch, capsys):
    files = {"schema.sql": "CREATE TABLE users (id INT PRIMARY KEY);\n",
             "app.py": 'def f(db):\n    return db.execute("SELECT * FROM users")\n',
             "other.py": "def g():\n    return 1\n"}
    root = make_repo(files)
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True).stdout.strip()
    (root / "other.py").write_text("def g():\n    return 2\n")
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false"]
    subprocess.run([*git, "commit", "-qam", "change"], cwd=root, check=True)
    monkeypatch.chdir(root)
    data._DECLARATIONS.clear()
    data._USES.clear()
    scanned = []
    real = data.parse_uses
    monkeypatch.setattr(data, "parse_uses", lambda text, tables: scanned.append(text) or real(text, tables))
    assert main(["init"]) == 0 and main(["diff", base, "HEAD"]) == 0
    capsys.readouterr()
    assert len(scanned) == 3  # app.py and other.py for the base, then only the changed other.py
    conn = store.read_only(next((root / ".cbi" / "refs").glob("*/model.db")))
    assert conn.execute("SELECT count(*) FROM edges WHERE kind = 'reads_table'").fetchone()[0] == 1
    conn.close()


def test_history_projection_indexes_folders():
    import sqlite3

    point = sqlite3.connect(":memory:")
    point.executescript(
        "CREATE TABLE nodes (id TEXT, path TEXT, content_hash TEXT, kind TEXT, workspace_id TEXT, attrs TEXT);"
        "CREATE TABLE edges (src TEXT, dst TEXT, kind TEXT);")
    paths = [f"d{i % 40}/f{i}.py" for i in range(20000)]
    point.executemany("INSERT INTO nodes VALUES (?, ?, ?, 'file', NULL, NULL)", [(f"w:{p}", p, p) for p in paths])
    document = {"summary": "s", "externals": [], "relationships": [], "concepts": [
        {"id": "a", "name": "A", "summary": "a", "role": "core", "files": paths[:40]}]}
    started = time.perf_counter()
    projected, provisional = history.project_concepts(document, point)
    # Every other file is placed by its folder; scanning all files per file took minutes at this size.
    assert time.perf_counter() - started < 5
    assert len(projected["concepts"][0]["files"]) == 20000 and len(provisional) == 19960

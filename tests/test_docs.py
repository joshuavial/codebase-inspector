import json
import sqlite3

import pytest

from cbi import docs
from cbi.cli import main
from cbi.docs import references, title
from cbi.files import default_ignore


def test_title_prefers_front_matter_then_first_heading_outside_fences():
    assert title("---\ntitle: 'Front'\nx: 1\n---\n# Heading\n") == "Front"
    assert title("---\nx: 1\n---\nintro\n## Second level ##\n# Later\n") == "Second level"
    assert title("```\n# not a heading\n```\n# Real\n") == "Real"
    assert title("no headings\n#hashtag\n") is None


def test_references_skip_fenced_code():
    spans, links = references("See `a.py` and [b](docs/b.md \"t\").\n```\n`c.py` [d](d.md)\n```\n")
    assert spans == ["a.py"] and links == ["docs/b.md"]


@pytest.fixture
def repo(make_repo, monkeypatch):
    files = {
        "src/registry.py": "def helper():\n    pass\n",
        "src/app.ts": "export class DeviceRegistry {\n  load() {}\n  revoke() {}\n}\nexport function helper() {}\n",
        "docs/guide.md": (
            "---\ntitle: Operator guide\n---\n# Ignored heading\n"
            "Start in `src/registry.py`, then `DeviceRegistry.revoke()` and `src/app.ts#DeviceRegistry`.\n"
            "Also [the app](../src/app.ts#L3), [notes](notes/n1.md#intro), `src/` and [web](https://x.y/z).\n"
            "Unknown `nope.py`, a word `load` and `helper`.\n"
            "```\n`src/app.ts` in a fence\n```\n"
        ),
        "README.md": "intro\n# Readme title\nquokkaword here\n",
    }
    files.update({f"docs/notes/n{i}.md": f"# Note {i}\n" for i in range(110)})
    # Python symbols come with deliverable 13; until then the .py file is a searchable file node.
    files["docs/notes/tool.ts"] = "export function zebrafunc() {\n  return 1;\n}\n"
    files["docs/notes/yakscript.py"] = "def yak():\n    return 1\n"
    files["docs/notes/n0.md"] = "# Note 0\nRefers to `zebrafunc`.\n"
    root = make_repo(files)
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    assert main(["scan"]) == 0
    return root


def _db(root):
    return sqlite3.connect(root / ".cbi" / "model.db")


def _search(capsys, text):
    capsys.readouterr()
    assert main(["search", text, "--json"]) == 0
    return [h["id"] for h in json.loads(capsys.readouterr().out)]


def test_doc_titles(repo):
    rows = dict(_db(repo).execute("SELECT path, doc FROM nodes WHERE kind = 'doc'"))
    assert rows["docs/guide.md"] == "Operator guide"
    assert rows["README.md"] == "Readme title"
    assert rows["docs/notes/n5.md"] == "Note 5"


def test_mentions_edges(repo):
    edges = dict(_db(repo).execute(
        "SELECT dst, confidence FROM edges WHERE kind = 'mentions' AND src = 'local:repo:docs/guide.md'"))
    assert edges == {
        "local:repo:src/registry.py": 1.0,
        "local:repo:src/app.ts": 1.0,  # link with a line anchor
        "local:repo:src/app.ts#DeviceRegistry": 1.0,
        "local:repo:src/app.ts#DeviceRegistry.revoke": 0.8,
        "local:repo:docs/notes/n1.md": 1.0,  # heading anchor falls back to the file
        "local:repo:src/": 1.0,
        # `helper` is defined in both registry.py and app.ts, so the bare name is ambiguous and links nothing;
        # `load` is DeviceRegistry.load, not a qualified name
    }


def test_doc_collection_keeps_code_parsed_and_searchable(repo, capsys):
    db = _db(repo)
    assert db.execute("SELECT display_kind FROM nodes WHERE id = 'local:repo:docs/'").fetchone() == ("doc collection",)
    assert db.execute("SELECT kind FROM nodes WHERE id = 'local:repo:docs/notes/tool.ts#zebrafunc'").fetchone() == ("symbol",)
    assert db.execute("SELECT COUNT(*) FROM nodes WHERE parent_id = 'local:repo:docs/notes/'").fetchone()[0] == 112
    assert "local:repo:docs/notes/tool.ts#zebrafunc" in _search(capsys, "zebrafunc")
    assert "local:repo:docs/notes/yakscript.py" in _search(capsys, "yakscript")
    assert db.execute("SELECT 1 FROM edges WHERE src = 'local:repo:docs/notes/n0.md' AND kind = 'mentions' "
                      "AND dst = 'local:repo:docs/notes/tool.ts#zebrafunc'").fetchone()


def test_search_finds_doc_title_and_body(repo, capsys):
    assert _search(capsys, "operator guide")[0] == "local:repo:docs/guide.md"
    assert _search(capsys, "quokkaword") == ["local:repo:README.md"]


def test_rescan_after_edit_replaces_title_and_mentions(repo, capsys):
    (repo / "docs" / "guide.md").write_text("# New title\nOnly `src/app.ts`.\n")
    assert main(["scan"]) == 0
    db = _db(repo)
    assert db.execute("SELECT doc FROM nodes WHERE path = 'docs/guide.md'").fetchone() == ("New title",)
    assert [r[0] for r in db.execute("SELECT dst FROM edges WHERE src = 'local:repo:docs/guide.md'")] == [
        "local:repo:src/app.ts"]


def _sequential(conn, root):
    """The single-threaded doc pass `docs.index` replaced: (titles, search rows, edges) it would write."""
    targets = docs._Targets(conn)
    titles, search, edges = {}, {}, set()
    for nid, wid, path, name in conn.execute(
            "SELECT id, workspace_id, path, name FROM nodes WHERE kind = 'doc'").fetchall():
        top = targets.top(wid, path)
        try:
            text = (root / top).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        heading = title(text)
        titles[nid] = heading
        search[nid] = (f"{name} {heading or ''}".strip(), docs.front_matter(text)[1][:docs.SEARCH_TEXT_LIMIT])
        for dst, confidence in docs.mentions(targets, top, targets.ws_root.get(wid, ""), text).items():
            if dst != nid:
                edges.add((nid, dst, confidence))
    return titles, search, edges


def _indexed(conn, ids):
    """(titles, search rows, edges) currently stored for the given doc ids."""
    marks = ",".join("?" * len(ids))
    titles = dict(conn.execute(f"SELECT id, doc FROM nodes WHERE id IN ({marks})", ids))
    search = {nid: (name, doc) for nid, name, doc in conn.execute(
        f"SELECT id, name, doc FROM search WHERE id IN ({marks})", ids)}
    edges = set(conn.execute(
        "SELECT src, dst, confidence FROM edges WHERE kind = 'mentions' AND source = 'markdown'"))
    return titles, search, edges


def _edge_rows(conn):
    return conn.execute("SELECT src, dst, confidence FROM edges WHERE kind = 'mentions' "
                        "AND source = 'markdown' ORDER BY rowid").fetchall()


def test_parallel_index_matches_sequential_baseline(repo):
    conn = _db(repo)
    expected_titles, expected_search, expected_edges = _sequential(conn, repo)
    docs.index(conn, repo)
    titles, search, edges = _indexed(conn, list(expected_titles))
    assert titles == expected_titles
    assert search == expected_search
    assert edges == expected_edges
    assert len(expected_titles) == 112 and expected_edges  # every doc read, mentions found


def test_index_output_is_identical_across_worker_counts(repo, monkeypatch):
    conn = _db(repo)
    runs = []
    for workers in (1, 2, 16):
        monkeypatch.setattr(docs, "_workers", lambda workers=workers: workers)
        docs.index(conn, repo)
        runs.append((
            conn.execute("SELECT id, doc FROM nodes WHERE kind = 'doc' ORDER BY id").fetchall(),
            conn.execute("SELECT id, name, doc FROM search ORDER BY rowid").fetchall(),
            _edge_rows(conn),  # insertion order too, not just the set
        ))
    assert runs[0] == runs[1] == runs[2]
    edges = runs[0][2]
    assert edges == sorted(edges)  # grouped by doc id, then target id


def test_index_skips_missing_files_and_keeps_the_rest(repo):
    conn = _db(repo)
    (repo / "docs" / "guide.md").unlink()
    docs.index(conn, repo)
    assert not conn.execute("SELECT 1 FROM edges WHERE src = 'local:repo:docs/guide.md'").fetchone()
    # The unreadable doc keeps its old title; the others are still indexed.
    assert conn.execute("SELECT doc FROM nodes WHERE path = 'docs/guide.md'").fetchone() == ("Operator guide",)
    assert conn.execute("SELECT doc FROM nodes WHERE path = 'docs/notes/n7.md'").fetchone() == ("Note 7",)
    assert conn.execute("SELECT 1 FROM edges WHERE src = 'local:repo:docs/notes/n0.md' "
                        "AND dst = 'local:repo:docs/notes/tool.ts#zebrafunc'").fetchone()


def test_index_replaces_undecodable_bytes(repo):
    conn = _db(repo)
    (repo / "README.md").write_bytes(b"# Caf\xe9 \xff title\nSee `src/app.ts`.\n")
    docs.index(conn, repo)
    heading = conn.execute("SELECT doc FROM nodes WHERE path = 'README.md'").fetchone()[0]
    assert heading == "Caf\ufffd \ufffd title"
    assert conn.execute("SELECT 1 FROM edges WHERE src = 'local:repo:README.md' "
                        "AND dst = 'local:repo:src/app.ts'").fetchone()


def test_index_handles_many_docs(make_repo, monkeypatch):
    count = 600
    files = {"src/core.ts": "export function corefunc() {\n  return 1;\n}\n"}
    files.update({
        f"docs/d{i:03}.md": f"# Doc {i}\nUses `src/core.ts` and [next](d{(i + 1) % count:03}.md).\n"
        for i in range(count)})
    root = make_repo(files)
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    assert main(["scan"]) == 0
    conn = _db(root)
    expected = _sequential(conn, root)
    titles, search, edges = _indexed(conn, list(expected[0]))
    assert (titles, search, edges) == expected
    assert len(titles) == count and titles["local:repo:docs/d042.md"] == "Doc 42"
    assert len(edges) == 2 * count
    assert ("local:repo:docs/d599.md", "local:repo:docs/d000.md", 1.0) in edges


def test_minified_needs_most_bytes_on_long_lines(make_repo):
    rule = "." + "a { color: red; }" * 70 + "\n"  # one ~1,200 character line
    handwritten = "".join(f".c{i} {{ display: grid; gap: {i}px; }}\n" for i in range(800)) + rule * 3
    root = make_repo({
        "src/styles.css": handwritten,  # a few long lines in a long file
        "public/vendor.css": "/* x */\n" + rule * 4,
    })
    text = default_ignore(root)
    assert "/public/vendor.css\n" in text
    assert "styles.css" not in text


def test_committed_virtualenvs_are_ignored(make_repo):
    root = make_repo({
        "app.py": "print(1)\n",
        "env-copy/pyvenv.cfg": "home = /usr/bin\n",
        "env-copy/lib/python3.12/site-packages/lib_a/core.py": "def a():\n    return 1\n",
        "notes/pyvenv.md": "not a venv\n",
    })
    text = default_ignore(root)
    assert "/env-copy/\n" in text
    assert "notes" not in text

import json
import sqlite3

import pytest

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

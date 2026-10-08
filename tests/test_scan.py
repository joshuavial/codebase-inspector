import json
import os
import sqlite3
import subprocess
from pathlib import Path

import pytest

from cbi.cli import main
from cbi.files import workspace_title

GOLDEN = Path(__file__).parent / "golden" / "scan.txt"


def git(cwd, *args):
    return subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@example.com", "-c", "commit.gpgsign=false",
         "-c", "protocol.file.allow=always", *args],
        cwd=cwd, check=True, capture_output=True, text=True,
    ).stdout


@pytest.fixture
def app(make_repo, monkeypatch):
    """A repo with an initialised and an uninitialised submodule, a tracked symlink,
    a data dir, a fixtures dir, build output and a minified file. Clean on return."""
    lib = make_repo({"lib.py": "def f():\n    pass\n", "README.md": "# lib\n"}, name="lib")
    other = make_repo({"x.py": "x = 1\n"}, name="other")
    files = {
        "README.md": "# app\n",
        "src/app.ts": "export const app = 1;\n",
        "src/app.test.ts": "import { app } from './app';\n",
        "src/util.py": "def util():\n    return 1\n",
        "tests/test_util.py": "from src.util import util\n",
        "docs/guide.md": "# Guide\n",
        ".claude/skills/demo/SKILL.md": "# demo\n",
        "logo.png": "not really a png\n",
        "fixtures/sample.json": "{}\n",
        "dist/bundle.js": "console.log(1);\n",
        "public/vendor.js": "var a=" + "1+" * 600 + "1;\n",
    }
    files.update({f"data/item{i}.json": "{}\n" for i in range(201)})
    root = make_repo(files, name="app")
    (root / ".agent").mkdir()
    os.symlink("../.claude/skills", root / ".agent" / "skills")
    git(root, "remote", "add", "origin", "git@github.com:Acme/App.git")
    git(root, "submodule", "add", "-q", str(lib), "vendor/lib")
    git(root, "submodule", "add", "-q", str(other), "vendor/other")
    # Stable URLs, so the golden dump does not hold temp paths. The relative one
    # resolves against origin for the uninitialised submodule's ID.
    git(root, "config", "-f", ".gitmodules", "submodule.vendor/lib.url", "https://github.com/acme/lib.git")
    git(root, "config", "-f", ".gitmodules", "submodule.vendor/other.url", "../other.git")
    git(root, "add", ".agent/skills", ".gitmodules")
    git(root, "commit", "-q", "-m", "submodules and symlink")
    git(root, "submodule", "deinit", "-q", "-f", "vendor/other")
    git(root / "vendor" / "lib", "remote", "set-url", "origin", "https://github.com/acme/lib.git")
    monkeypatch.chdir(root)
    assert git(root, "status", "--porcelain") == ""
    return root


def scan(capsys):
    capsys.readouterr()
    assert main(["scan"]) == 0
    return capsys.readouterr().out


def nodes(root):
    conn = sqlite3.connect(root / ".cbi" / "model.db")
    rows = conn.execute(
        "SELECT id, parent_id, kind, display_kind, name, workspace_id, path, lang, content_hash, attrs "
        "FROM nodes ORDER BY id"
    ).fetchall()
    conn.close()
    return {row[0]: row for row in rows}


def dump(root):
    lines = []
    for row in nodes(root).values():
        attrs = json.loads(row[9]) if row[9] else None
        for key in ("pinned_commit", "checked_out_commit"):
            if attrs and attrs.get(key):
                attrs[key] = "<commit>"  # commit hashes depend on the clock
        lines.append(json.dumps([*row[:9], attrs]))
    return "\n".join(lines) + "\n"


def test_init_writes_self_ignoring_dir_and_ignore_file(app, capsys):
    assert main(["init"]) == 0
    assert (app / ".cbi" / ".gitignore").read_text() == "*\n"
    ignore = (app / ".cbi" / "ignore").read_text()
    for line in ("/fixtures/", "dist*/", "build/", "/data/", "/public/vendor.js"):
        assert line in ignore.splitlines()
    (app / ".cbi" / "ignore").write_text(ignore + "logo.png\n")
    assert main(["init"]) == 0
    assert (app / ".cbi" / "ignore").read_text() == ignore + "logo.png\n"


def test_fixtures_and_test_data_stay_when_they_are_code(make_repo, monkeypatch, capsys):
    root = make_repo({
        "e2e/test-data/check.ts": "export const check = 1;\n",
        "e2e/test-data/client.cs": "class Client {}\n",
        "fixtures/leases.json": "{}\n",
        "fixtures/notes.txt": "n\n",
        "fixtures/dump.sql": "-- dump\n",
        "fixtures/helper.ts": "export {};\n",
        "src/app.ts": "export const app = 1;\n",
        "kept/fixtures/a.ts": "export {};\n",
        "kept/fixtures/b.cs": "class B {}\n",
        "tied/test-data/a.json": "{}\n",
        "tied/test-data/b.ts": "export {};\n",
        "sql-only/test-data/seed.sql": "select 1;\n",
    }, name="repo")
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    ignore = (root / ".cbi" / "ignore").read_text().splitlines()
    assert "/fixtures/" in ignore and "/sql-only/test-data/" in ignore
    assert not any("e2e/test-data" in line or "kept/fixtures" in line or "tied/test-data" in line for line in ignore)
    assert main(["scan"]) == 0
    conn = sqlite3.connect(root / ".cbi" / "model.db")
    paths = {row[0] for row in conn.execute("SELECT path FROM nodes WHERE kind IN ('file', 'doc')")}
    conn.close()
    assert {"e2e/test-data/check.ts", "e2e/test-data/client.cs", "kept/fixtures/a.ts", "tied/test-data/b.ts"} <= paths
    assert "fixtures/leases.json" not in paths and "sql-only/test-data/seed.sql" not in paths


def test_scan_requires_init(app, capsys):
    assert main(["scan"]) == 1
    assert "cbi init" in capsys.readouterr().err


def test_init_and_scan_leave_repo_clean(app, capsys):
    main(["init"])
    scan(capsys)
    assert git(app, "status", "--porcelain") == ""


def test_out_dir(app, tmp_path, capsys):
    out = tmp_path / "model"
    assert main(["init", "--out", str(out)]) == 0
    assert main(["scan", "--out", str(out)]) == 0
    assert (out / "model.db").exists() and not (app / ".cbi").exists()


def test_golden_dump(app, capsys):
    (app / "src" / "util.py").write_text("def util():\n    return 2\n")  # unstaged edit
    git(app / "vendor" / "lib", "commit", "-q", "--allow-empty", "-m", "drift")
    before = git(app, "status", "--porcelain")
    main(["init"])
    out = scan(capsys)
    assert git(app, "status", "--porcelain") == before
    assert "source file: 3" in out and "scanned" in out

    found = nodes(app)
    ws = "github.com/acme/app"
    assert found[f"{ws}:.agent/skills"][3] == "symlink"
    assert not any(i.startswith(f"{ws}:.agent/skills/") for i in found)
    assert not any("data/" in i or "fixtures/" in i or "dist/" in i or "vendor.js" in i for i in found)
    lib = json.loads(found["github.com/acme/lib"][9])
    assert lib["drift"] and lib["initialised"] and lib["pinned_commit"] != lib["checked_out_commit"]
    other = json.loads(found["github.com/acme/other"][9])
    assert not other["initialised"] and other["checked_out_commit"] is None
    assert not any(row[5] == "github.com/acme/other" for row in found.values())

    text = dump(app)
    if os.environ.get("CBI_UPDATE_GOLDEN"):
        GOLDEN.write_text(text)
    assert text == GOLDEN.read_text()


def test_workspace_title_prefers_the_remote_name():
    assert workspace_title(Path("/tmp/review-images"), "git@github.com:Acme/SampleDesktop.git") == "SampleDesktop"
    assert workspace_title(Path("/tmp/review-images"), None, "vendor/lib") == "lib"
    assert workspace_title(Path("/tmp/review-images"), "   ", "vendor/lib") == "lib"


def test_workspace_name_comes_from_the_remote(make_repo, monkeypatch, capsys, tmp_path):
    root = make_repo({"a.py": "x = 1\n"}, name="review-images")
    git(root, "remote", "add", "origin", "git@github.com:Acme/SampleDesktop.git")
    monkeypatch.chdir(root)
    out = tmp_path / "model"
    assert main(["init", "--out", str(out)]) == 0
    assert main(["scan", "--out", str(out)]) == 0
    conn = sqlite3.connect(out / "model.db")
    row = conn.execute(
        "SELECT id, name FROM nodes WHERE kind = 'workspace' AND parent_id IS NULL"
    ).fetchone()
    conn.close()
    assert row == ("github.com/acme/sampledesktop", "SampleDesktop")


def test_linked_worktree_uses_the_main_folder_name(make_repo, monkeypatch, capsys, tmp_path):
    root = make_repo({"a.py": "x = 1\n"}, name="proj")
    link = tmp_path / "review-images"
    git(root, "worktree", "add", "--detach", "-q", str(link), "HEAD")
    monkeypatch.chdir(link)
    out = tmp_path / "model"
    assert main(["init", "--out", str(out)]) == 0
    assert main(["scan", "--out", str(out)]) == 0
    conn = sqlite3.connect(out / "model.db")
    name = conn.execute(
        "SELECT name FROM nodes WHERE kind = 'workspace' AND parent_id IS NULL"
    ).fetchone()[0]
    conn.close()
    assert name == "proj"


def test_remote_case_change_rescans(make_repo, monkeypatch, capsys):
    root = make_repo({"a.py": "x = 1\n"}, name="lane")
    git(root, "remote", "add", "origin", "git@github.com:Acme/App.git")
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    assert "scanned" in scan(capsys)
    assert nodes(root)["github.com/acme/app"][4] == "App"
    git(root, "remote", "set-url", "origin", "git@github.com:Acme/APP.git")
    assert "scanned" in scan(capsys)
    assert nodes(root)["github.com/acme/app"][4] == "APP"


def test_no_change_shortcut_and_rescans(app, capsys):
    main(["init"])
    assert "scanned" in scan(capsys)
    assert "no changes" in scan(capsys)

    os.utime(app / "README.md")  # new mtime, same content
    assert "no changes" in scan(capsys)

    (app / "src" / "util.py").write_text("def util():\n    return 3\n")
    assert "scanned" in scan(capsys)
    assert "no changes" in scan(capsys)

    (app / "docs" / "guide.md").unlink()
    assert "scanned" in scan(capsys)
    assert "github.com/acme/app:docs/guide.md" not in nodes(app)
    assert "github.com/acme/app:docs/" not in nodes(app)

    with open(app / ".cbi" / "ignore", "a") as f:
        f.write("*.png\n")
    assert "scanned" in scan(capsys)
    assert "github.com/acme/app:logo.png" not in nodes(app)
    assert "no changes" in scan(capsys)

    git(app / "vendor" / "lib", "commit", "-q", "--allow-empty", "-m", "move")
    assert "scanned" in scan(capsys)


def test_rescan_keeps_later_columns(app, capsys):
    main(["init"])
    scan(capsys)
    db = sqlite3.connect(app / ".cbi" / "model.db")
    with db:
        db.execute("UPDATE nodes SET summary = 'kept' WHERE id = 'github.com/acme/app:src/'")
    (app / "src" / "app.ts").write_text("export const app = 2;\n")
    assert "scanned" in scan(capsys)
    assert db.execute("SELECT summary FROM nodes WHERE id = 'github.com/acme/app:src/'").fetchone() == ("kept",)

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
        "dist/bundle.min.js": "console.log(1);\n",
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
    for line in ("/fixtures/**/*.[jJ][sS][oO][nN]", "*.min.js", "/data/**/*.[jJ][sS][oO][nN]", "/public/vendor.js"):
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
        "fixtures/extra.json": "{}\n",
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
    assert "/fixtures/**/*.[jJ][sS][oO][nN]" in ignore and "/fixtures/**/*.[tT][xX][tT]" in ignore
    assert not any("e2e/test-data" in line or "kept/fixtures" in line or "tied/test-data" in line for line in ignore)
    assert main(["scan"]) == 0
    conn = sqlite3.connect(root / ".cbi" / "model.db")
    paths = {row[0] for row in conn.execute("SELECT path FROM nodes WHERE kind IN ('file', 'doc')")}
    conn.close()
    assert {"e2e/test-data/check.ts", "e2e/test-data/client.cs", "kept/fixtures/a.ts", "tied/test-data/b.ts",
            "fixtures/helper.ts", "fixtures/dump.sql", "sql-only/test-data/seed.sql"} <= paths
    assert "fixtures/leases.json" not in paths


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


def test_scan_auto_inits_out_dir_when_clean_or_missing(make_repo, monkeypatch, tmp_path, capsys):
    root = make_repo({"a.py": "x = 1\n", "fixtures/sample.json": "{}\n"})
    monkeypatch.chdir(root)
    out = tmp_path / "custom_model"
    assert not out.exists()

    # Running cbi scan --out without running cbi init first succeeds
    assert main(["scan", "--out", str(out)]) == 0
    assert out.is_dir()
    assert (out / ".gitignore").read_text(encoding="utf-8") == "*\n"
    assert (out / "ignore").exists()
    assert (out / "model.db").exists()
    assert not (root / ".cbi").exists()

    # Default ignore rules should be written
    ignore_text = (out / "ignore").read_text(encoding="utf-8")
    assert "/fixtures/**/*.[jJ][sS][oO][nN]" in ignore_text

    # Re-scanning an already-initialized --out directory reuses existing ignore rules without overwriting
    custom_rule = "*.custom_ext\n"
    (out / "ignore").write_text(ignore_text + custom_rule, encoding="utf-8")
    assert main(["scan", "--out", str(out)]) == 0
    assert (out / "ignore").read_text(encoding="utf-8") == ignore_text + custom_rule


def test_scan_auto_inits_existing_clean_out_dir(make_repo, monkeypatch, tmp_path):
    root = make_repo({"a.py": "x = 1\n"})
    monkeypatch.chdir(root)
    out = tmp_path / "clean_dir"
    out.mkdir()
    assert not (out / "ignore").exists()

    assert main(["scan", "--out", str(out)]) == 0
    assert (out / "ignore").exists()
    assert (out / "model.db").exists()


def test_golden_dump(app, capsys):
    (app / "src" / "util.py").write_text(
        "def util():\n    return 2\n", encoding="utf-8", newline="\n",
    )  # unstaged edit; LF so the working-tree hash matches the golden
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


def test_default_ignore_preserves_source_in_artifact_directories(make_repo, monkeypatch, capsys):
    source = {
        "evals/run.py": "print('evaluate')\n",
        "scripts/build/build.sh": "#!/bin/sh\necho build\n",
        "dist/helpers.ts": "export const helper = 1;\n",
        "fixtures/schema.sql": "create table sample (id integer);\n",
        "fixtures/setup": "#!/usr/bin/env python3\nprint('setup')\n",
        "data/runner.json": "#!/bin/sh\necho run\n",
    }
    artifacts = {f"data/item{i}.json": "{}\n" for i in range(201)}
    artifacts.update({"fixtures/one.json": "{}\n", "fixtures/two.json": "{}\n", "fixtures/three.json": "{}\n",
                      "evals/one.json": "{}\n", "evals/two.json": "{}\n"})
    root = make_repo({**source, **artifacts})
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    assert main(["scan"]) == 0
    paths = {row[6] for row in nodes(root).values()}
    assert source.keys() <= paths
    assert not artifacts.keys() & paths


def test_init_scan_check_report_excluded_tracked_source(make_repo, monkeypatch, capsys):
    root = make_repo({
        "hidden/run.sh": "#!/bin/sh\necho run\n",
        "hidden/schema.sql": "select 1;\n",
        "hidden/tool": "#!/usr/bin/env python3\nprint('run')\n",
        "hidden/data.json": "{}\n",
        "visible.py": "value = 1\n",
    })
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    assert "Excluded tracked executable files: 0" in capsys.readouterr().out
    (root / ".cbi" / "ignore").write_text("hidden/\n")
    for command in ("init", "scan", "check", "scan"):
        assert main([command]) == 0
        assert "Excluded tracked executable files: 3" in capsys.readouterr().out


def test_excluded_source_audit_includes_ignored_submodules_and_skips_links(app, tmp_path):
    from cbi.files import Ignore, excluded_source_files

    outside = tmp_path / "outside.sh"
    outside.write_text("#!/bin/sh\necho outside\n")
    os.symlink(outside, app / "link.sh")
    git(app, "add", "link.sh")
    assert excluded_source_files(app, Ignore("vendor/lib/\nlink.sh\n")) == ["vendor/lib/lib.py"]


def test_generated_artifact_rules_cover_later_data_but_keep_new_source(make_repo, monkeypatch, capsys):
    root = make_repo({f"data/item{i}.json": "{}\n" for i in range(201)})
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    ignore = (root / ".cbi" / "ignore").read_bytes()
    added = {
        "data/item201.json": "{}\n",
        "data/item202.JSON": "{}\n",
        "data/nested/batch.jsonl": "{}\n",
        "data/run.py": "print('run')\n",
        "data/nested/tool.JSON": "#!/usr/bin/env python3\nprint('run')\n",
        "data/nested/run.sh": "#!/bin/sh\necho run\n",
        "data/nested/schema.sql": "select 1;\n",
    }
    for name, text in added.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    git(root, "add", "data")
    git(root, "commit", "-m", "grow data directory")
    assert main(["scan"]) == 0
    paths = {row[6] for row in nodes(root).values()}
    artifacts = {"data/item201.json", "data/item202.JSON", "data/nested/batch.jsonl"}
    assert not artifacts & paths
    source = set(added) - artifacts
    assert source <= paths
    assert (root / ".cbi" / "ignore").read_bytes() == ignore
    assert main(["scan", "--ref", "HEAD"]) == 0
    sha = git(root, "rev-parse", "HEAD").strip()
    conn = sqlite3.connect(root / ".cbi" / "refs" / sha / "model.db")
    ref_paths = {row[0] for row in conn.execute("SELECT path FROM nodes WHERE kind = 'file'")}
    conn.close()
    assert source <= ref_paths and not artifacts & ref_paths
    # Explicit rules outside the generated block retain their normal meaning.
    (root / ".cbi" / "ignore").write_bytes(ignore + b"data/nested/tool.JSON\n")
    assert main(["scan"]) == 0
    assert "data/nested/tool.JSON" not in {row[6] for row in nodes(root).values()}


def test_named_build_sources_added_after_init_survive_artifact_rules(make_repo, monkeypatch):
    from cbi import files

    root = make_repo({f"data/item{i}.json": "{}\n" for i in range(201)}, name="named-source")
    monkeypatch.chdir(root)
    assert main(["init"]) == 0
    source = {
        "data/CMakeLists.txt": "cmake_minimum_required(VERSION 3.20)\nproject(sample)\n",
        "data/Makefile": "all:\n\t@echo ready\n",
        "data/Dockerfile": "FROM scratch\n",
        "data/justfile": "build:\n    echo ready\n",
        "data/GNUmakefile": "all:\n\t@echo ready\n",
        "data/Containerfile": "FROM scratch\n",
        "data/Dockerfile.preview.txt": "FROM scratch\n",
    }
    for name, text in {**source, "data/notes.txt": "Saved output.\n"}.items():
        (root / name).write_text(text)
    git(root, "add", "data")
    git(root, "commit", "-m", "add named build sources")
    assert main(["scan"]) == 0
    paths = {row[6] for row in nodes(root).values()}
    assert source.keys() <= paths
    assert "data/notes.txt" not in paths
    assert all(files.source_like(path) for path in source)
    assert main(["scan", "--ref", "HEAD"]) == 0
    sha = git(root, "rev-parse", "HEAD").strip()
    conn = sqlite3.connect(root / ".cbi" / "refs" / sha / "model.db")
    ref_paths = {row[0] for row in conn.execute("SELECT path FROM nodes WHERE kind = 'file'")}
    conn.close()
    assert source.keys() <= ref_paths and "data/notes.txt" not in ref_paths

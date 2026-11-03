"""Read commands open a model they cannot write, and do not create a journal."""

import shutil
import sqlite3
import subprocess

from cbi import store, tasks
from cbi.cli import main

FILES = {"src/app.ts": "export function hello() { return 1; }\n"}
READS = (
    ("status",),
    ("search", "hello"),
    ("show", "src/app.ts"),
    ("tests-for", "src/app.ts"),
    ("hotspots",),
    ("orphans",),
    ("cycles",),
    ("deps",),
    ("context", "src/app.ts"),
)


def run(capsys, *argv):
    capsys.readouterr()
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def _sidecars(directory):
    return [path.name for path in directory.iterdir() if path.name.endswith(("-wal", "-shm"))]



def _export_snapshot(source, dest):
    # An offline export can use a rollback journal, allowing normal read locks
    # without writable WAL sidecars in the snapshot's read-only directory.
    reader = store.read_only(source)
    target = sqlite3.connect(dest)
    try:
        reader.backup(target)
        target.execute("PRAGMA journal_mode = DELETE")
    finally:
        target.close()
        reader.close()


def test_read_only_connection_leaves_no_journal(tmp_path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    conn = store.open_db(src / "model.db")
    tasks.attach_cache(conn)
    conn.close()
    copy = tmp_path / "copy"
    copy.mkdir()
    dest = copy / "model.db"
    _export_snapshot(src / "model.db", dest)
    dest.chmod(0o444)
    copy.chmod(0o555)
    cache = tmp_path / "answer-cache"
    answers = cache / "answers.db"
    with sqlite3.connect(answers) as writable:
        writable.execute("PRAGMA journal_mode = DELETE")
    writable.close()
    answers.chmod(0o444)
    cache.chmod(0o555)
    missing = tmp_path / "no-cache"
    try:
        reader = store.read_only(dest)
        try:
            assert reader.execute("PRAGMA busy_timeout").fetchone()[0] == store.BUSY_MS
            assert reader.execute("PRAGMA user_version").fetchone()[0] == store.SCHEMA_VERSION
            assert reader.execute("SELECT count(*) FROM nodes").fetchone()[0] == 0
            tasks.attach_cache(reader, readonly=True)
            assert reader.execute("SELECT count(*) FROM cache.file_summaries").fetchone()[0] == 0
        finally:
            reader.close()
        assert _sidecars(copy) == []
        assert _sidecars(cache) == []
        monkeypatch.setenv("CBI_CACHE_DIR", str(missing))
        reader = store.read_only(dest)
        try:
            tasks.attach_cache(reader, readonly=True)
            assert reader.execute("SELECT count(*) FROM nodes").fetchone()[0] == 0
        finally:
            reader.close()
        assert not missing.exists()
        assert _sidecars(copy) == []
    finally:
        copy.chmod(0o755)
        cache.chmod(0o755)


def test_read_commands_work_on_a_chmod_copy(make_repo, monkeypatch, capsys, tmp_path):
    root = make_repo(FILES)
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    assert main(["scan", "--ref", "HEAD"]) == 0
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    copy = tmp_path / "model"
    copy.mkdir()
    dest = copy / "model.db"
    _export_snapshot(root / ".cbi" / "model.db", dest)
    ref_dir = root / ".cbi" / "refs" / sha
    ref_db = ref_dir / "model.db"
    with sqlite3.connect(ref_db) as writable:
        writable.execute("PRAGMA journal_mode = DELETE")
    writable.close()
    dest.chmod(0o444)
    ref_db.chmod(0o444)
    copy.chmod(0o555)
    ref_dir.chmod(0o555)
    missing = tmp_path / "no-cache"
    monkeypatch.setenv("CBI_CACHE_DIR", str(missing))
    copy_before, ref_before = _sidecars(copy), _sidecars(ref_dir)
    try:
        for argv in READS:
            code, out, err = run(capsys, *argv, "--out", str(copy))
            assert code == 0, (argv, err)
            assert out.strip()
        code, out, err = run(capsys, "status", "--ref", "HEAD")
        assert code == 0 and "last scan:" in out, err
        assert _sidecars(copy) == copy_before == []
        assert _sidecars(ref_dir) == ref_before == []
        assert not missing.exists()
    finally:
        copy.chmod(0o755)
        ref_dir.chmod(0o755)


def test_immutable_reads_require_an_explicit_frozen_snapshot(tmp_path):
    src = tmp_path / "source.db"
    conn = store.open_db(src)
    conn.close()
    directory = tmp_path / "frozen"
    directory.mkdir()
    snapshot = directory / "model.db"
    shutil.copy(src, snapshot)
    snapshot.chmod(0o444)
    directory.chmod(0o555)
    try:
        reader = store.read_only(snapshot, immutable=True)
        try:
            assert reader.execute("PRAGMA user_version").fetchone() == (store.SCHEMA_VERSION,)
        finally:
            reader.close()
        assert _sidecars(directory) == []
    finally:
        directory.chmod(0o755)


def test_readonly_wal_directory_gets_a_clean_diagnostic(make_repo, monkeypatch, capsys):
    root = make_repo(FILES)
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    directory = root / ".cbi"
    path = directory / "model.db"
    path.chmod(0o444)
    directory.chmod(0o555)
    try:
        code, _out, err = run(capsys, "tasks", "--json")
        assert code == 1
        assert "WAL sidecar" in err and "--out DIR" in err
        assert "Traceback" not in err
    finally:
        directory.chmod(0o755)
        path.chmod(0o644)

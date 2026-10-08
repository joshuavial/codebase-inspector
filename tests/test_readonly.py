"""Read commands open a model they cannot write, and do not create a journal."""

import shutil
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


def test_read_only_connection_leaves_no_journal(tmp_path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    conn = store.open_db(src / "model.db")
    tasks.attach_cache(conn)
    conn.close()
    copy = tmp_path / "copy"
    copy.mkdir()
    dest = copy / "model.db"
    shutil.copy(src / "model.db", dest)
    dest.chmod(0o444)
    copy.chmod(0o555)
    cache = tmp_path / "answer-cache"
    answers = cache / "answers.db"
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
    shutil.copy(root / ".cbi" / "model.db", dest)
    ref_dir = root / ".cbi" / "refs" / sha
    ref_db = ref_dir / "model.db"
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

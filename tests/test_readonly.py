"""Read commands open a model they cannot write, and do not create a journal."""

import json
import os
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest

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
    ("endpoints",),
    ("tables",),
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
        if not os.access(copy, os.W_OK):
            assert _sidecars(copy) == []
        if not os.access(cache, os.W_OK):
            assert _sidecars(cache) == []
        monkeypatch.setenv("CBI_CACHE_DIR", str(missing))
        reader = store.read_only(dest)
        try:
            tasks.attach_cache(reader, readonly=True)
            assert reader.execute("SELECT count(*) FROM nodes").fetchone()[0] == 0
        finally:
            reader.close()
        assert not missing.exists()
        if not os.access(copy, os.W_OK):
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
        if not os.access(copy, os.W_OK):
            assert _sidecars(copy) == copy_before == []
        if not os.access(ref_dir, os.W_OK):
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


def test_readonly_wal_directory_supports_read_commands(make_repo, monkeypatch, capsys, tmp_path):
    root = make_repo(FILES)
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    directory = root / ".cbi"
    path = directory / "model.db"
    with sqlite3.connect(path) as conn:
        task_id = conn.execute("SELECT id FROM tasks WHERE kind = 'summarise-files'").fetchone()[0]
    conn.close()
    before = path.read_bytes()
    assert before[18] == 2  # Retain the WAL format; do not export to DELETE journaling.
    assert _sidecars(directory) == []
    entries = set(directory.iterdir())
    path.chmod(0o444)
    directory.chmod(0o555)
    frozen = not os.access(path, os.W_OK) and not os.access(directory, os.W_OK)
    missing_cache = tmp_path / "missing-cache"
    monkeypatch.setenv("CBI_CACHE_DIR", str(missing_cache))
    try:
        for argv in (*READS, ("tasks", "--json"), ("task", task_id, "--json")):
            code, out, err = run(capsys, *argv)
            assert code == 0, (argv, err)
            assert out.strip()
            if frozen:
                assert "frozen snapshot" in err
            assert "Traceback" not in err
        brief = json.loads(out)
        answer = tmp_path / "answer.json"
        answer.write_text(json.dumps({"input_hash": brief["input_hash"], "files": [
            {"path": file["path"], "summary": "A frozen file summary."} for file in brief["files"]]}))
        code, _out, err = run(capsys, "task", task_id, "--check", str(answer))
        assert code == 0, err
        if frozen:
            assert "frozen snapshot" in err
            assert set(directory.iterdir()) == entries
        assert path.read_bytes() == before
        assert not missing_cache.exists()
    finally:
        directory.chmod(0o755)
        path.chmod(0o644)


def test_existing_readonly_wal_uses_normal_locking(make_repo, monkeypatch, capsys):
    root = make_repo(FILES)
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    directory = root / ".cbi"
    path = directory / "model.db"
    writer = sqlite3.connect(path)
    writer.execute("INSERT INTO meta VALUES ('wal_answer', 'current')")
    writer.commit()
    assert _sidecars(directory)
    path.chmod(0o444)
    directory.chmod(0o555)
    capsys.readouterr()
    try:
        reader = store.read_only(path)
        try:
            assert reader.execute("SELECT value FROM meta WHERE key = 'wal_answer'").fetchone() == ("current",)
        finally:
            reader.close()
        assert "frozen snapshot" not in capsys.readouterr().err
    finally:
        directory.chmod(0o755)
        path.chmod(0o644)
        writer.close()


def test_readonly_file_in_writable_directory_still_sees_a_late_writer(
        make_repo, monkeypatch, capsys):
    root = make_repo(FILES)
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    path = root / ".cbi/model.db"
    path.chmod(0o444)
    original_uri = store.read_uri
    writers = []

    def interleave_uri(candidate, **kwargs):
        uri = original_uri(candidate, **kwargs)
        assert "immutable=1" not in uri
        # A writable directory is still mutable, even if this file was read-only
        # when the reader started. Let a writer obtain access after URI creation.
        path.chmod(0o644)
        writer = sqlite3.connect(path)
        writer.execute("INSERT INTO meta VALUES ('late_answer', 'current')")
        writer.commit()
        writers.append(writer)
        return uri

    monkeypatch.setattr(store, "read_uri", interleave_uri)
    capsys.readouterr()
    try:
        reader = store.read_only(path)
        try:
            assert reader.execute("SELECT value FROM meta WHERE key = 'late_answer'").fetchone() == ("current",)
        finally:
            reader.close()
        assert "frozen snapshot" not in capsys.readouterr().err
    finally:
        path.chmod(0o644)
        for writer in writers:
            writer.close()


@pytest.mark.parametrize("file_mode,directory_mode", [
    (0o644, 0o755), (0o664, 0o775), (0o444, 0o755), (0o644, 0o555),
    (0o464, 0o575), (0o446, 0o557),
])
def test_non_owner_access_does_not_freeze_an_owner_writable_database(
        make_repo, monkeypatch, capsys, file_mode, directory_mode):
    root = make_repo(FILES)
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    directory = root / ".cbi"
    path = directory / "model.db"
    path.chmod(file_mode)
    directory.chmod(directory_mode)
    original_access = os.access
    original_uri = store.read_uri
    writers = []

    def non_owner_access(candidate, mode, *args, **kwargs):
        if mode == os.W_OK:
            return False
        return original_access(candidate, mode, *args, **kwargs)

    def owner_writes_after_uri(candidate, **kwargs):
        uri = original_uri(candidate, **kwargs)
        assert "immutable=1" not in uri
        path.chmod(0o644)
        directory.chmod(0o755)
        writer = sqlite3.connect(path)
        writer.execute("INSERT INTO meta VALUES ('owner_answer', 'current')")
        writer.commit()
        writers.append(writer)
        return uri

    monkeypatch.setattr(store.os, "access", non_owner_access)
    monkeypatch.setattr(store, "read_uri", owner_writes_after_uri)
    capsys.readouterr()
    try:
        reader = store.read_only(path)
        try:
            assert reader.execute("SELECT value FROM meta WHERE key = 'owner_answer'").fetchone() == ("current",)
        finally:
            reader.close()
        assert "frozen snapshot" not in capsys.readouterr().err
    finally:
        path.chmod(0o644)
        directory.chmod(0o755)
        for writer in writers:
            writer.close()


def test_windows_frozen_predicate_probes_both_create_and_write_permissions(tmp_path, monkeypatch):
    import errno
    import tempfile

    path = tmp_path / "model.db"
    path.write_bytes(b"unchanged")
    original_probe = tempfile.mkstemp
    original_open = os.open
    for deny_create, deny_write in ((False, False), (False, True), (True, False), (True, True)):
        calls = []

        def probe(*args, **kwargs):
            calls.append("directory")
            if deny_create:
                raise PermissionError(errno.EACCES, "directory ACL denies creation")
            return original_probe(*args, **kwargs)

        def open_database(candidate, flags, *args, **kwargs):
            if Path(candidate) == path:
                calls.append("database")
                assert not flags & (os.O_TRUNC | os.O_CREAT)
                if deny_write:
                    raise PermissionError(errno.EACCES, "database ACL denies writes")
            return original_open(candidate, flags, *args, **kwargs)

        with monkeypatch.context() as patch:
            patch.setattr(store.sys, "platform", "win32")
            patch.setattr(tempfile, "mkstemp", probe)
            patch.setattr(os, "open", open_database)
            uri = store.read_uri(path, frozen_fallback=True)
        assert ("immutable=1" in uri) == (deny_create and deny_write)
        assert "directory" in calls
        assert ("database" in calls) == deny_create
        assert path.read_bytes() == b"unchanged"
        assert set(tmp_path.iterdir()) == {path}


@pytest.mark.parametrize("target", ["model", "cache"])
def test_frozen_candidate_rechecks_wal_before_connecting(
        make_repo, monkeypatch, capsys, target):
    import errno
    import sys
    import tempfile

    root = make_repo(FILES)
    monkeypatch.chdir(root)
    assert main(["init"]) == 0 and main(["scan"]) == 0
    model = root / ".cbi/model.db"
    path = model if target == "model" else tasks.cache_path()
    path.chmod(0o444)
    path.parent.chmod(0o555)
    original_uri = store.read_uri
    writers = []

    frozen_parent = True
    if sys.platform == "win32":
        original_mkstemp = tempfile.mkstemp

        def win_mkstemp(*args, **kwargs):
            if frozen_parent and Path(kwargs.get("dir", "")).resolve() == path.parent.resolve():
                raise PermissionError(errno.EACCES, "directory ACL denies file creation")
            return original_mkstemp(*args, **kwargs)

        monkeypatch.setattr(tempfile, "mkstemp", win_mkstemp)

    def interleave_uri(candidate, **kwargs):
        nonlocal frozen_parent
        uri = original_uri(candidate, **kwargs)
        if candidate == path:
            assert "immutable=1" in uri
            frozen_parent = False
            path.chmod(0o644)
            path.parent.chmod(0o755)
            writer = sqlite3.connect(path)
            sql = ("INSERT INTO meta VALUES ('changed_answer', 'current')" if target == "model" else
                   f"INSERT INTO file_summaries VALUES ('changed', {tasks.PROTOCOL_VERSION}, 'current')")
            writer.execute(sql)
            writer.commit()
            writers.append(writer)
        return uri

    monkeypatch.setattr(store, "read_uri", interleave_uri)
    capsys.readouterr()
    try:
        reader = store.read_only(model)
        try:
            if target == "cache":
                tasks.attach_cache(reader, readonly=True)
            sql = ("SELECT value FROM meta WHERE key = 'changed_answer'" if target == "model" else
                   "SELECT summary FROM cache.file_summaries WHERE content_hash = 'changed'")
            assert reader.execute(sql).fetchone() == ("current",)
        finally:
            reader.close()
        assert "frozen snapshot" not in capsys.readouterr().err
    finally:
        path.chmod(0o644)
        path.parent.chmod(0o755)
        for writer in writers:
            writer.close()


@pytest.mark.parametrize("suffix", ["-wal", "-shm", "-journal"])
def test_sidecar_created_after_uri_disables_immutable_at_connect(tmp_path, monkeypatch, suffix):
    path = tmp_path / "model.db"
    store.open_db(path).close()
    original_uri = store.read_uri

    def interleave_uri(candidate, **kwargs):
        uri = original_uri(candidate, **kwargs)
        assert "immutable=1" in uri
        Path(str(path) + suffix).touch()
        return uri

    def observe_connect(database_uri, **kwargs):
        assert "immutable=1" not in database_uri
        raise LookupError("connect observed")

    with monkeypatch.context() as patch:
        patch.setattr(store, "read_uri", interleave_uri)
        patch.setattr(store.sqlite3, "connect", observe_connect)
        with pytest.raises(LookupError, match="connect observed"):
            store.read_only(path, immutable=True)
    assert "immutable=1" not in store.read_uri(path, immutable=True)



def test_windows_probe_resource_errors_do_not_imply_a_frozen_directory(tmp_path, monkeypatch):
    import errno
    import tempfile

    path = tmp_path / "model.db"
    path.write_bytes(b"unchanged")

    def exhausted_probe(*args, **kwargs):
        raise OSError(errno.ENOSPC, "no space for a permission probe")

    with monkeypatch.context() as patch:
        patch.setattr(store.sys, "platform", "win32")
        patch.setattr(tempfile, "mkstemp", exhausted_probe)
        uri = store.read_uri(path, frozen_fallback=True)
    assert "immutable=1" not in uri

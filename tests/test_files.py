from cbi.files import BASE_IGNORE, Ignore, classify, cs_test_roots, default_ignore, doc_collections


def test_base_ignore_excludes_credentials_and_private_keys(make_repo):
    ignore = Ignore(BASE_IGNORE)
    secrets = [
        "id_rsa",
        "id_rsa.pub",
        "id_rsa_deploy",
        "server.pem",
        "private.key",
        "credentials.json",
        "gcp-service-account.json",
        "nested/keys/id_rsa",
        "nested/keys/id_rsa.pub",
        "nested/keys/id_rsa_deploy",
        "certs/server.pem",
        "certs/private.key",
        "auth/credentials.json",
        "config/gcp-service-account.json",
    ]
    for path in secrets:
        assert ignore(path), f"expected {path} to be ignored by BASE_IGNORE"

    non_secrets = [
        "src/keys.ts",
        "app.json",
        "server.js",
        "src/credentials.py",
        "package.json",
    ]
    for path in non_secrets:
        assert not ignore(path), f"expected {path} to not be ignored by BASE_IGNORE"

    repo = make_repo({"src/app.py": "print(1)\n"})
    default_text = default_ignore(repo)
    default_rules = Ignore(default_text)
    for path in secrets:
        assert default_rules(path), f"expected {path} to be ignored by default_ignore"
    for path in non_secrets:
        assert not default_rules(path), f"expected {path} to not be ignored by default_ignore"



def test_ignore_follows_gitignore_rules():
    ignore = Ignore("# comment\nfixtures/\ndist*/\n/data/\n*.min.js\ndocs/**/draft.md\n!keep.min.js\n")
    assert ignore("a/fixtures/x.ts")
    assert ignore("dist-electron/main.js")
    assert ignore("data/1.json")
    assert not ignore("src/data/1.json")  # anchored to the root
    assert ignore("lib/x.min.js")
    assert not ignore("keep.min.js")  # negation
    assert ignore("docs/a/b/draft.md") and ignore("docs/draft.md")
    assert not ignore("fixtures")  # dir-only rule does not match a file of that name
    assert ignore("fixtures", is_dir=True)
    assert not Ignore("")("anything")


def test_classify():
    assert classify("src/app.ts") == ("code", "typescript")
    assert classify("src/app.test.tsx") == ("test", "tsx")
    assert classify("src/__tests__/x.js") == ("test", "javascript")
    assert classify("tests/test_util.py") == ("test", "python")
    assert classify("tests/conftest.py") == ("test", "python")
    assert classify("server/conftest.py") == ("test", "python")
    assert classify("e2e/fixtures/auth.ts") == ("test", "typescript")
    assert classify("src/components/Panel.dom-test.tsx") == ("test", "tsx")
    assert classify("README.md") == ("doc", "markdown")
    assert classify("logo.png") == ("other", None)
    assert classify("src/App.cs") == ("code", "csharp")
    assert classify("src/App.vue") == ("code", "vue")
    assert classify("tests/WidgetTests.cs") == ("test", "csharp")
    assert classify("src/Greatest.cs") == ("code", "csharp")
    assert classify("src/contest.cs") == ("code", "csharp")
    assert classify("src/Widget.cs", ["src"]) == ("test", "csharp")
    assert classify("src/__tests__/A.vue") == ("test", "vue")
    assert classify("e2e/cypress/e2e/invoices.cy.ts") == ("test", "typescript")
    assert classify("cypress/e2e/smoke.cy.js") == ("test", "javascript")
    assert classify("cypress/e2e/plain.ts") == ("test", "typescript")
    assert classify("cypress/support/commands.ts") == ("code", "typescript")
    assert classify("cypress/e2e.ts") == ("code", "typescript")


def test_cs_test_roots_are_test_project_directories():
    assert cs_test_roots([
        "App.Tests/App.Tests.csproj", "Tests.csproj", "lib/demo.tests.csproj", "App/App.csproj",
        "Support.Testing/Support.Testing.csproj",
        "tests/App.IntegrationTests/App.IntegrationTests.csproj",
        "tests/App.UnitTests/App.UnitTests.csproj",
    ]) == [
        "tests/App.IntegrationTests", "tests/App.UnitTests", "Support.Testing", "App.Tests", "lib",
    ]
    roots = cs_test_roots(["tests/App.IntegrationTests/App.IntegrationTests.csproj"])
    assert classify("tests/App.IntegrationTests/ApiFactory.cs", roots) == ("test", "csharp")
    assert classify("src/Program.cs", roots) == ("code", "csharp")


def test_doc_collection_is_over_100_files_mostly_markdown_and_little_code():
    notes = [f"docs/notes/n{i}.md" for i in range(101)]
    assert doc_collections(notes + ["src/a.py"]) == {"docs"}
    assert doc_collections(notes[:100]) == set()
    assert doc_collections(notes + [f"docs/x{i}.py" for i in range(12)]) == {"docs/notes"}
    # research artefacts that are not code do not stop the collapse
    assert doc_collections(notes + [f"docs/notes/r{i}.log" for i in range(30)]) == {"docs"}
    assert doc_collections([f"img/{i}.png" for i in range(150)]) == set()


def test_shebang_classification_reads_only_bounded_prefixes(make_repo, monkeypatch):
    from pathlib import Path
    from cbi import files

    root = make_repo({"asset.bin": "x" * (2 * 1024 * 1024),
                      "launch": "#!/bin/sh\n" + "# padding\n" * 100000})
    workspaces, tracked = files.enumerate_repo(root)
    states = {path: (0, 0, "blob", files.PARSER_VERSION, False) for path, _, _ in tracked}
    original = Path.read_bytes

    def no_whole_file(path):
        if path.parent == root:
            raise AssertionError("classification requested the whole file")
        return original(path)

    original_open = Path.open
    reads = []

    class BoundedReader:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.stream.close()

        def read(self, size=-1):
            assert 0 <= size <= 4096, "classification reads must be bounded"
            reads.append(size)
            return self.stream.read(size)

    def bounded_open(path, *args, **kwargs):
        stream = original_open(path, *args, **kwargs)
        return BoundedReader(stream) if path.parent == root else stream

    monkeypatch.setattr(Path, "read_bytes", no_whole_file)
    monkeypatch.setattr(Path, "open", bounded_open)
    nodes = files.build_nodes(workspaces, tracked, states, root)
    assert next(n for n in nodes if n.get("path") == "launch")["lang"] == "shell"
    assert reads and max(reads) <= 4096


def test_shebang_classification_streams_git_prefix_without_caching_blob(make_repo, monkeypatch):
    from cbi import files

    root = make_repo({"asset.bin": "x" * (2 * 1024 * 1024),
                      "launch": "#!/bin/sh\n" + "# padding\n" * 100000})
    sha = files.resolve_commit(root, "HEAD")
    tree = files.CommitTree(root, sha)

    def no_whole_blob(*args):
        raise AssertionError("classification requested the whole Git blob")

    monkeypatch.setattr(files._Batch, "get", no_whole_blob)
    reads = []

    class BoundedReader:
        def __init__(self, stream):
            self.stream = stream

        def __getattr__(self, name):
            return getattr(self.stream, name)

        def read(self, size=-1):
            assert 0 <= size <= 65536, "Git blob reads must use a fixed-size buffer"
            reads.append(size)
            return self.stream.read(size)

    batch = tree._batch(tree.git_dir)
    batch.proc.stdout = BoundedReader(batch.proc.stdout)
    try:
        nodes = files.build_nodes(tree.workspaces, tree.tracked, tree.file_states(), tree)
        assert next(n for n in nodes if n.get("path") == "launch")["lang"] == "shell"
        assert reads and max(reads) <= 65536
        assert not batch.cache
    finally:
        tree.close()


def _git(cwd, *args):
    import subprocess

    return subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@example.com", "-c", "commit.gpgsign=false",
         "-c", "protocol.file.allow=always", *args],
        cwd=cwd, check=True, capture_output=True,
    ).stdout


def _disk_hashes(root, tracked):
    """What hash_files gave before the index fast path: the blob id of every raw file."""
    import os
    from cbi import files

    out = {}
    for top, _, _ in tracked:
        full = root / top
        if os.path.islink(full):
            out[top] = files.blob_id(os.fsencode(os.readlink(full)))
        elif full.is_file():
            out[top] = files.blob_id(full.read_bytes())
    return out


def _count_reads(monkeypatch):
    """Record every working-tree file hash_files reads from disk."""
    from cbi import files

    reads = []
    real = files.blob_id_file

    def counting(handle):
        reads.append(handle.name)
        return real(handle)

    monkeypatch.setattr(files, "blob_id_file", counting)
    return reads


def test_clean_tracked_files_take_their_index_blob_id_without_open(make_repo, monkeypatch):
    from cbi import files

    root = make_repo({"src/a.py": "a = 1\n", "docs/b.md": "# b\n", "c.txt": ""})
    workspaces, tracked = files.enumerate_repo(root)
    assert workspaces[0]["index_shas"]["src/a.py"] == _git(root, "rev-parse", ":src/a.py").decode().strip()

    def no_open(*args, **kwargs):
        raise AssertionError("a clean tracked file was read from disk")

    monkeypatch.setattr(files, "open", no_open, raising=False)
    monkeypatch.setattr(files, "blob_id_file", no_open)
    states = files.hash_files(root, tracked, {})
    assert {top: s[2] for top, s in states.items()} == _disk_hashes(root, tracked)
    for top, state in states.items():
        st = (root / top).stat()
        assert state[:2] == (st.st_mtime_ns, st.st_size)
        assert state[2] == _git(root, "hash-object", "--no-filters", top).decode().strip()


def test_unstaged_edits_are_hashed_from_disk(make_repo, monkeypatch):
    from cbi import files

    root = make_repo({"a.py": "a = 1\n", "b.py": "b = 1\n", "c.py": "c = 1\n"})
    (root / "a.py").write_bytes(b"a = 2\n")  # same length as the index blob
    (root / "b.py").write_bytes(b"b = 'longer'\n")
    (root / "c.py").unlink()
    _, tracked = files.enumerate_repo(root)
    reads = _count_reads(monkeypatch)
    states = files.hash_files(root, tracked, {})
    assert {top: s[2] for top, s in states.items()} == _disk_hashes(root, tracked)
    assert "c.py" not in states
    assert sorted(reads) == sorted(str(root / p) for p in ("a.py", "b.py"))


def test_converted_or_unchecked_files_are_hashed_from_disk(make_repo, monkeypatch):
    from cbi import files

    root = make_repo({
        ".gitattributes": "crlf.txt text eol=crlf\nfiltered.bin filter=custom\n",
        "crlf.txt": "one\ntwo\n",
        "filtered.bin": "raw\n",
        "assumed.py": "x = 1\n",
        "skipped.py": "y = 1\n",
        "clean.py": "z = 1\n",
    })
    # The index keeps LF while the working tree holds CRLF, and git sees no change.
    (root / "crlf.txt").write_bytes(b"one\r\ntwo\r\n")
    _git(root, "add", "crlf.txt")
    assert _git(root, "diff-files", "--name-only") == b""
    _git(root, "update-index", "--assume-unchanged", "assumed.py")
    (root / "assumed.py").write_bytes(b"x = 2\n")
    _git(root, "update-index", "--skip-worktree", "skipped.py")
    (root / "skipped.py").write_bytes(b"y = 2\n")
    _, tracked = files.enumerate_repo(root)
    reads = _count_reads(monkeypatch)
    states = files.hash_files(root, tracked, {})
    assert {top: s[2] for top, s in states.items()} == _disk_hashes(root, tracked)
    assert states["crlf.txt"][2] != _git(root, "rev-parse", ":crlf.txt").decode().strip()
    read = {p.removeprefix(str(root) + "/").replace("\\", "/") for p in reads}
    assert read == {"crlf.txt", "filtered.bin", "assumed.py", "skipped.py"}


def test_autocrlf_without_attributes_still_hashes_raw_bytes(make_repo, monkeypatch):
    from cbi import files

    root = make_repo({"win.txt": "one\ntwo\n", "plain.txt": "lf\n"})
    _git(root, "config", "core.autocrlf", "true")
    (root / "win.txt").write_bytes(b"one\r\ntwo\r\n")
    _git(root, "add", "win.txt")
    assert _git(root, "diff-files", "--name-only") == b""
    _, tracked = files.enumerate_repo(root)
    reads = _count_reads(monkeypatch)
    states = files.hash_files(root, tracked, {})
    assert {top: s[2] for top, s in states.items()} == _disk_hashes(root, tracked)
    assert [p.replace("\\", "/").rsplit("/", 1)[-1] for p in reads] == ["win.txt"]


def test_stat_matches_reuse_old_hashes_without_asking_git(make_repo, monkeypatch):
    import subprocess
    from cbi import files

    root = make_repo({"a.py": "a = 1\n"})
    _, tracked = files.enumerate_repo(root)
    first = files.hash_files(root, tracked, {})
    real = subprocess.run

    def no_git(argv, *args, **kwargs):
        raise AssertionError(f"unexpected git call {argv}")

    monkeypatch.setattr(subprocess, "run", no_git)
    assert files.hash_files(root, tracked, first) == first
    monkeypatch.setattr(subprocess, "run", real)


def test_git_failure_falls_back_to_disk(make_repo, monkeypatch):
    import subprocess
    from cbi import files

    root = make_repo({"a.py": "a = 1\n"})
    _, tracked = files.enumerate_repo(root)
    real = subprocess.run

    def failing_diff_files(argv, *args, **kwargs):
        if "diff-files" in argv:
            return subprocess.CompletedProcess(argv, 128, b"", b"fatal")
        return real(argv, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", failing_diff_files)
    reads = _count_reads(monkeypatch)
    states = files.hash_files(root, tracked, {})
    assert {top: s[2] for top, s in states.items()} == _disk_hashes(root, tracked)
    assert len(reads) == 1


def test_submodule_files_and_symlinks_hash_like_disk(make_repo, monkeypatch, tmp_path):
    import os

    import pytest
    from cbi import files

    lib = make_repo({"lib.py": "def f():\n    pass\n", "edit.py": "e = 1\n"}, name="lib")
    root = make_repo({"app.py": "import lib\n", "target.md": "# t\n"}, name="app")
    try:
        os.symlink("target.md", root / "link.md")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    _git(root, "submodule", "add", "-q", str(lib), "vendor/lib")
    _git(root, "add", "link.md")
    _git(root, "commit", "-q", "-m", "submodule and symlink")
    (root / "vendor" / "lib" / "edit.py").write_bytes(b"e = 22\n")

    workspaces, tracked = files.enumerate_repo(root)
    sub = next(ws for ws in workspaces if ws["root"] == "vendor/lib")
    assert set(sub["index_shas"]) == {"lib.py", "edit.py"}
    assert "link.md" not in workspaces[0]["index_shas"]
    reads = _count_reads(monkeypatch)
    states = files.hash_files(root, tracked, {})
    assert {top: s[2] for top, s in states.items()} == _disk_hashes(root, tracked)
    assert states["link.md"][4] is True
    assert states["link.md"][2] == files.blob_id(b"target.md")
    assert [os.path.relpath(p, root).replace("\\", "/") for p in reads] == ["vendor/lib/edit.py"]
